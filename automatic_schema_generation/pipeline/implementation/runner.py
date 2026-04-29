"""``implement`` and ``implement_responses`` stage runners.

The two stages share infrastructure (loading the extract output, calling
the LLM, writing prompts during ``--dry-run``) and both live here to
keep them next to ``build_prompt.py``.

Order matters in the full pipeline — ``implement_responses`` runs
first to populate ``core/errors.py`` so each resource implementation
can reference the existing error constructors instead of redefining
them per-handler.
"""

from __future__ import annotations

import json
import re
from collections import defaultdict
from pathlib import Path

from pipeline.config import load_config
from pipeline.implementation.build_prompt import build_pass1_prompt, build_pass2_prompt
from pipeline.llm import make_llm_call


def run_implement_responses(ctx) -> None:
    """``implement_responses`` stage — emit the standard error constructors."""
    config = load_config(ctx.config_path)
    output_dir = ctx.output_dir
    responses_path = output_dir / "responses.json"

    if not responses_path.exists():
        print("\n=== IMPLEMENT RESPONSES — skipped (no responses.json, run extract first) ===")
        return

    responses_doc = json.loads(responses_path.read_text())
    response_count = len(responses_doc.get("responses", {}))

    if response_count == 0:
        print("\n=== IMPLEMENT RESPONSES — skipped (no component responses in spec) ===")
    else:
        print(f"\n=== IMPLEMENT RESPONSES — {response_count} responses ({ctx.implement_model}) ===")
        prompt = (
            f"Read the file `{responses_path.resolve()}`. It contains the "
            f"response definitions referenced by the resources being "
            f"implemented from the {config.app_name} API spec, along with "
            f"their referenced schemas.\n\n"
            f"Implement the standard HTTP error response handlers in "
            f"`{config.target_dir}/core/errors.py`. For each standard error "
            f"response (400 Bad Request, 401 Unauthorized, 403 Forbidden, "
            f"404 Not Found, 500 Internal Server Error, etc.), create a "
            f"constructor function that returns the correct response shape "
            f"matching the schemas in the file.\n\n"
            f"Skip domain-specific or resource-specific responses — only "
            f"implement responses that represent standard HTTP error patterns "
            f"reusable across the endpoints being implemented.\n\n"
            f"Read the existing `{config.target_dir}/core/errors.py` first "
            f"and preserve any code already there."
        )

        if ctx.dry_run:
            prompt_dir = ctx.prompt_dir
            prompt_dir.mkdir(parents=True, exist_ok=True)
            (prompt_dir / "implement_responses.md").write_text(prompt)
            print(f"  [dry-run] Saved prompt to {prompt_dir}/implement_responses.md")
        else:
            llm_call = make_llm_call(model=ctx.implement_model, timeout=600)
            print(f"  Calling {ctx.implement_model}...")
            llm_call(prompt)
            print(f"  Done.")

    constructors = _scan_error_constructors(config.target_dir / "core" / "errors.py")
    (output_dir / "implemented_responses.json").write_text(
        json.dumps({"constructors": constructors}, indent=2)
    )
    print(f"  Found {len(constructors)} error constructors: {constructors}")


def run_implement(ctx) -> None:
    """``implement`` stage — call the LLM for each resource (Pass 1 + Pass 2)."""
    config = load_config(ctx.config_path)
    spec = config.load_spec()

    output_dir = ctx.output_dir
    endpoints_doc = json.loads((output_dir / "endpoints.json").read_text())
    resources_doc = json.loads((output_dir / "resources.json").read_text())

    impl_responses_path = output_dir / "implemented_responses.json"
    implemented_constructors = []
    if impl_responses_path.exists():
        implemented_constructors = json.loads(
            impl_responses_path.read_text()
        ).get("constructors", [])

    print(f"\n=== IMPLEMENT — LLM builds entities ({ctx.implement_model}) ===")
    resource_names = ctx.only_resources or sorted(resources_doc["resources"].keys())
    order = _dependency_order(resource_names, resources_doc)
    print(f"  Order: {' → '.join(order)}")

    for index, resource_name in enumerate(order, 1):
        print(f"\n  [{index}/{len(order)}] {resource_name}")

        prompt_p1 = build_pass1_prompt(
            resource_name, resources_doc, endpoints_doc, config,
            spec=spec, implemented_constructors=implemented_constructors,
        )
        prompt_p2 = build_pass2_prompt(
            resource_name, resources_doc, endpoints_doc, config, spec=spec,
        )

        if ctx.dry_run:
            prompt_dir = ctx.prompt_dir
            prompt_dir.mkdir(parents=True, exist_ok=True)
            (prompt_dir / f"{resource_name}_pass1.md").write_text(prompt_p1)
            (prompt_dir / f"{resource_name}_pass2.md").write_text(prompt_p2)
            print(f"    [dry-run] Saved prompts to {prompt_dir}")
            continue

        llm_call = make_llm_call(model=ctx.implement_model, timeout=900)

        print(f"    Pass 1 — base model ({len(prompt_p1):,} chars)...")
        llm_call(prompt_p1)

        print(f"    Pass 2 — relationships ({len(prompt_p2):,} chars)...")
        llm_call(prompt_p2)

        print(f"    Done.")


def _scan_error_constructors(errors_path: Path) -> list[str]:
    """Extract function names from core/errors.py."""
    if not errors_path.exists():
        return []
    content = errors_path.read_text()
    return re.findall(r"^def (\w+)", content, re.MULTILINE)


def _dependency_order(
    resource_names: list[str],
    resources_doc: dict,
) -> list[str]:
    """Topological sort by outgoing references — deps first."""
    resources = resources_doc.get("resources") or {}
    name_set = set(resource_names)

    in_degree: dict[str, int] = {name: 0 for name in resource_names}
    dependents: dict[str, list[str]] = defaultdict(list)

    for name in resource_names:
        outgoing = (resources.get(name) or {}).get("outgoing_references") or {}
        for target in outgoing:
            if target in name_set and target != name:
                in_degree[name] += 1
                dependents[target].append(name)

    queue = sorted([name for name in resource_names if in_degree[name] == 0])
    order: list[str] = []
    while queue:
        current = queue.pop(0)
        order.append(current)
        for dependent in sorted(dependents.get(current, [])):
            in_degree[dependent] -= 1
            if in_degree[dependent] == 0:
                queue.append(dependent)

    # Cycle fallback — append remaining alphabetically
    remaining = [name for name in resource_names if name not in order]
    order.extend(sorted(remaining))
    return order
