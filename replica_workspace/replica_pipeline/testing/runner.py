"""End-to-end endpoint verification stage.

Groups untested endpoints from ``test_registry.json`` by ``subject``,
chunks each subject into batches of N (default 5), builds a prompt
(via ``pipeline.prompts.test_endpoints``) that hands the LLM full
schema metadata + instructions for driving the live replica via curl,
and invokes ``claude -p``. The LLM writes a structured JSON results
file which is parsed back and merged into the registry.

The prompt explicitly allows the LLM to edit replica source files when
it finds bugs, since the dev backend runs uvicorn with ``--reload`` and
picks up edits without a restart. There is no automatic regression
check across batches — see ``--force-retest`` to retest everything.
"""

from __future__ import annotations

import json
import os
import subprocess
from collections import defaultdict
from pathlib import Path
from typing import Any

from replica_pipeline.prompts.test_endpoints import build_test_prompt


def group_by_subject(
    test_entries: list[dict[str, Any]],
    *,
    include_tested: bool = False,
) -> dict[str, list[dict[str, Any]]]:
    """Bucket entries by ``subject`` field, skipping already-tested ones."""
    grouped: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for entry in test_entries:
        if not include_tested and entry.get("tested"):
            continue
        subject = entry.get("subject") or "_unknown"
        grouped[subject].append(entry)
    return dict(grouped)


def chunk(entries: list[dict[str, Any]], batch_size: int) -> list[list[dict[str, Any]]]:
    return [entries[index:index + batch_size] for index in range(0, len(entries), batch_size)]


def parse_results_file(output_path: Path) -> list[dict[str, Any]]:
    """Read the LLM's structured output. Returns [] on missing/malformed."""
    if not output_path.exists():
        return []
    try:
        payload = json.loads(output_path.read_text())
    except json.JSONDecodeError:
        return []
    results = payload.get("results")
    if not isinstance(results, list):
        return []
    return results


def merge_into_registry(
    registry_path: Path,
    results: list[dict[str, Any]],
) -> int:
    """Mark matching entries as tested + attach the LLM's diagnosis."""
    registry = json.loads(registry_path.read_text())
    by_key: dict[tuple[str, str], dict[str, Any]] = {}
    for result in results:
        method = (result.get("method") or "").upper()
        path = result.get("path") or ""
        if not method or not path:
            continue
        by_key[(method, path)] = result

    updated_count = 0
    for entry in registry.get("endpoints", []):
        key = (entry["method"], entry["path"])
        result = by_key.get(key)
        if result is None:
            continue
        entry["tested"] = True
        entry["test_result"] = {
            "passed": bool(result.get("passed")),
            "iterations": result.get("iterations"),
            "diagnosis": result.get("diagnosis"),
            "curl_examples": result.get("curl_examples") or [],
            "code_changes": result.get("code_changes") or [],
        }
        updated_count += 1

    registry_path.write_text(json.dumps(registry, indent=2))
    return updated_count


def _invoke_claude(prompt: str, *, model: str, timeout: int) -> tuple[int, str, str]:
    """Run ``claude -p`` with full tool access and return (rc, stdout, stderr)."""
    env = os.environ.copy()
    env.pop("ANTHROPIC_API_KEY", None)
    try:
        result = subprocess.run(
            ["claude", "-p", "--model", model],
            input=prompt,
            capture_output=True,
            text=True,
            env=env,
            timeout=timeout,
        )
    except FileNotFoundError as exc:
        raise RuntimeError("claude CLI not found on PATH") from exc
    except subprocess.TimeoutExpired:
        return (124, "", f"claude -p timed out after {timeout}s")
    return (result.returncode, result.stdout, result.stderr)


def run_test_endpoints_stage(ctx) -> None:
    """``test_endpoints`` stage — drive each batch through ``claude -p``,
    parse the structured results JSON, and merge it into ``test_registry.json``.

    Replicas YAML + repo root paths are derived from this file's location.
    """
    from replica_pipeline.config import load_config

    config = load_config(ctx.config_path)
    output_dir = ctx.output_dir
    repo_root = Path(__file__).parent.parent.parent.parent
    replicas_yaml = repo_root / "backend" / "src" / "services" / "replicas.yaml"

    registry_path = output_dir / "test_registry.json"
    endpoints_path = output_dir / "endpoints.json"

    print(
        f"\n=== TEST ENDPOINTS — drive replica via curl, fix bugs in place "
        f"({ctx.test_model}) ==="
    )
    if ctx.test_force_retest:
        print("  [force] retesting endpoints already marked tested=true")
    if not registry_path.exists() or not endpoints_path.exists():
        print("  [skip] test_registry.json or endpoints.json missing — run register_tests first")
        return

    registry = json.loads(registry_path.read_text())
    endpoints_doc = json.loads(endpoints_path.read_text())

    # The registry only contains implemented endpoints (presence is the
    # contract), so we group all of its entries directly.
    grouped = group_by_subject(registry.get("endpoints") or [], include_tested=ctx.test_force_retest)
    if ctx.only_resources:
        grouped = {name: items for name, items in grouped.items() if name in set(ctx.only_resources)}
    if not grouped:
        print("  [skip] nothing to test (all endpoints already tested — pass --force-retest to retest)")
        return

    prompt_dir = ctx.prompt_dir
    results_dir = output_dir / "test_results"
    prompt_dir.mkdir(parents=True, exist_ok=True)
    results_dir.mkdir(parents=True, exist_ok=True)

    total_batches = 0
    total_attempted = 0
    total_recorded = 0
    total_passed = 0

    for subject in sorted(grouped):
        endpoints = grouped[subject]
        batches = chunk(endpoints, ctx.test_batch_size)
        total_batches += len(batches)
        subject_recorded = 0
        subject_passed = 0

        for batch_index, batch in enumerate(batches, start=1):
            output_path = results_dir / f"{subject}_batch{batch_index}.json"
            prompt = build_test_prompt(
                app_name=config.app_name,
                app_slug=config.app_slug,
                target_dir=config.target_dir,
                subject=subject,
                batch_index=batch_index,
                batch_total=len(batches),
                endpoints=batch,
                endpoints_doc=endpoints_doc,
                replicas_yaml=replicas_yaml,
                output_path=output_path,
                max_iterations=ctx.test_max_iterations,
                repo_root=repo_root,
            )
            (prompt_dir / f"test_{subject}_batch{batch_index}.md").write_text(prompt)
            total_attempted += len(batch)

            if ctx.dry_run:
                print(f"  [dry-run] {subject} batch {batch_index}/{len(batches)} — {len(batch)} endpoints, prompt at pipeline_prompts/test_{subject}_batch{batch_index}.md")
                continue

            print(f"  {subject} batch {batch_index}/{len(batches)} — {len(batch)} endpoints, calling {ctx.test_model} (timeout {ctx.test_timeout}s)...")
            if output_path.exists():
                output_path.unlink()
            return_code, _stdout, stderr = _invoke_claude(prompt, model=ctx.test_model, timeout=ctx.test_timeout)
            if return_code != 0:
                print(f"    [warn] claude exit {return_code}: {stderr.strip()[:300]}")

            results = parse_results_file(output_path)
            if not results:
                print(f"    [warn] no parseable results at {output_path} — endpoints in this batch stay untested")
                continue

            updated = merge_into_registry(registry_path, results)
            passed = sum(1 for result in results if result.get("passed"))
            total_recorded += updated
            total_passed += passed
            subject_recorded += updated
            subject_passed += passed
            print(f"    recorded {updated}/{len(batch)}; {passed} passed")

        print(f"    {subject}: {subject_passed}/{subject_recorded} passed across {len(batches)} batch(es)")

    print(
        f"  Done. Batches: {total_batches}, "
        f"recorded {total_recorded}/{total_attempted}, "
        f"passed {total_passed}"
    )
