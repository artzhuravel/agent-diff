"""Scan implemented routes and build the test registry.

Imports the app's routes module, reads the Route objects, and writes
``test_registry.json`` — one entry per *implemented* spec endpoint,
carrying the testing-state fields (``tested``, ``test_result``,
``subject``, ``path_params``, ``needs_seed``).

The registry's contract is simple: presence in the file means the
endpoint has a handler in ``routes.py`` and is therefore subject to
testing. Spec endpoints without handlers don't appear here at all —
they live in ``endpoints.json``, which is the full spec catalog.
The two files are complementary: ``endpoints.json`` answers "what
does the API claim to expose?", ``test_registry.json`` answers "of
those, which have been built and what's their test state?".
"""

from __future__ import annotations

import json
import re
import sys
from importlib import import_module
from pathlib import Path
from typing import Any

from replica_pipeline.documentation.builder import (
    generate_api_docs_document,
    write_api_docs_document,
)


def run_register_tests(ctx) -> None:
    """``register_tests`` stage — scan routes.py, emit unified registry.

    The replica's routes module lives under ``backend/src/services/<slug>``;
    we load it via ``import_module`` so we observe whatever Starlette
    actually mounts (not what the spec claimed should exist). The
    sqlalchemy pre-import is a workaround for backend's local
    ``platform/`` package shadowing the stdlib ``platform`` module.
    """
    from replica_pipeline.config import load_config

    config = load_config(ctx.config_path)
    output_dir = ctx.output_dir
    endpoints_path = output_dir / "endpoints.json"

    if not endpoints_path.exists():
        print("\n=== REGISTER TESTS — skipped (run extract first) ===")
        return

    print("\n=== REGISTER TESTS — scanning implemented routes ===")
    import sqlalchemy as _sa  # noqa: F401  — pre-import before path-shadowing kicks in
    backend_src = str(config.target_dir.parent.parent)
    if backend_src not in sys.path:
        sys.path.insert(0, backend_src)
    routes_module = f"services.{config.app_slug}.api.routes"

    # Narrowly catch import errors only — that's what the platform-shadow
    # workaround above is for. Anything else (JSON parse, FS write,
    # stale data) should fail loudly so the user notices instead of
    # getting a silently-empty registry that downstream stages skip past.
    try:
        implemented = scan_implemented_routes(routes_module)
    except ImportError as exc:
        raise SystemExit(
            f"register_tests could not import {routes_module!r}: {exc}\n"
            f"Check that ``{config.target_dir / 'api' / 'routes.py'}`` parses "
            f"and that all required dependencies are installed."
        )

    endpoints_doc = json.loads(endpoints_path.read_text())
    only = set(ctx.only_resources or [])
    registry = build_test_registry(
        implemented, endpoints_doc, config.app_slug, only_resources=only or None,
    )

    # Preserve tested status from a prior registry. Entries that share
    # ``(method, path)`` with a previously-tested entry keep their
    # ``tested`` flag + ``test_result``, so re-running register_tests
    # after an extend exercises only the newly added endpoints. The
    # ``--force-retest`` flag opts out — every entry is left untested
    # so the next test_endpoints run sweeps the full surface.
    #
    # When ``--resource`` is set, we additionally splice unmatched-resource
    # entries from the prior registry into the fresh one so partial
    # rebuilds don't lose the rest of the registry's history.
    registry_path = output_dir / "test_registry.json"
    if registry_path.exists():
        previous = json.loads(registry_path.read_text())
        previous_entries = previous.get("endpoints") or []
        previous_by_key = {
            (entry["method"], entry["path"]): entry
            for entry in previous_entries
        }
        preserved_count = 0
        if not ctx.test_force_retest:
            for entry in registry["endpoints"]:
                prior = previous_by_key.get((entry["method"], entry["path"]))
                if prior and prior.get("tested"):
                    entry["tested"] = True
                    entry["test_result"] = prior.get("test_result")
                    preserved_count += 1
        if only:
            # Splice back entries from prior registry whose subject is
            # outside the ``--resource`` filter — those weren't rebuilt
            # this run and would otherwise vanish. Skip entries that
            # carry an ``implemented: false`` flag from older registries
            # written before the format simplification; the new registry
            # only contains implemented endpoints.
            fresh_keys = {
                (entry["method"], entry["path"])
                for entry in registry["endpoints"]
            }
            spliced = 0
            for entry in previous_entries:
                if (entry["method"], entry["path"]) in fresh_keys:
                    continue
                if entry.get("subject") in only:
                    continue
                if entry.get("implemented") is False:
                    continue
                registry["endpoints"].append(entry)
                spliced += 1
            if spliced:
                print(f"  Spliced {spliced} entry(ies) from prior registry "
                      f"(outside --resource filter)")
        if preserved_count:
            print(
                f"  Preserved tested status for {preserved_count} "
                f"endpoint(s) from previous registry"
            )

    # Counts derived directly from the final entry list. ``implemented_count``
    # is just len(endpoints) since the registry only contains implementeds.
    registry["implemented_count"] = len(registry["endpoints"])

    write_registry(output_dir, registry)
    total = registry["total_spec_endpoints"]
    implemented = registry["implemented_count"]
    print(
        f"  {implemented} implemented, {total - implemented} unimplemented "
        f"(of {total} total)"
    )
    print(f"  Wrote test_registry.json to {output_dir}")

    # Regenerate the implemented-endpoints documentation. Lives outside
    # ``pipeline_out/`` because it's a downstream artifact intended for
    # test-generation tooling and human inspection — same convention as
    # the existing ``examples/<slug>/testsuites/<slug>_docs/`` layout used
    # by hand-curated docs for older replicas.
    repo_root = Path(__file__).parent.parent.parent.parent
    docs_path = (
        repo_root / "examples" / config.app_slug / "testsuites"
        / f"{config.app_slug}_docs" / f"{config.app_slug}_api_full_docs.json"
    )
    implemented_keys = {
        f"{entry['method']} {entry['path']}" for entry in registry["endpoints"]
    }
    api_docs = generate_api_docs_document(config.load_spec(), implemented_keys)
    write_api_docs_document(api_docs, docs_path)
    print(
        f"  Wrote {docs_path.name} "
        f"({len(api_docs)} endpoints) to {docs_path.parent}"
    )


def scan_implemented_routes(routes_module: str) -> list[dict[str, Any]]:
    """Import the routes module and extract all registered Route entries."""
    module = import_module(routes_module)
    routes = getattr(module, "routes", [])

    implemented = []
    for route in routes:
        path = getattr(route, "path", "")
        methods = getattr(route, "methods", set())
        if not path or "unknown_path" in path:
            continue
        for method in methods:
            if method.upper() in ("HEAD", "OPTIONS"):
                continue
            implemented.append({"method": method.upper(), "path": path})
    return implemented


def build_test_registry(
    implemented: list[dict[str, Any]],
    endpoints_doc: dict[str, Any],
    app_slug: str,
    only_resources: set[str] | None = None,
) -> dict[str, Any]:
    """Build the test registry from spec endpoints that have handlers.

    Walks the spec catalog (``endpoints_doc["endpoints"]``) and emits
    one entry per endpoint whose ``(method, path)`` was found in the
    live ``routes.py`` scan. Spec endpoints without handlers, and
    routes-only endpoints without spec metadata, are both excluded —
    the registry is for "implemented + spec-known" routes.

    ``only_resources`` (when set) restricts the rebuilt entries to
    routes whose ``subject`` is in the filter — used by ``--resource``
    for partial rebuilds. The caller splices excluded entries back from
    the prior registry.
    """
    endpoints_block = endpoints_doc.get("endpoints") or {}
    implemented_keys = {f"{r['method']} {r['path']}" for r in implemented}

    test_entries: list[dict[str, Any]] = []
    for key, endpoint_meta in endpoints_block.items():
        if key not in implemented_keys:
            continue
        if only_resources is not None and endpoint_meta.get("subject") not in only_resources:
            continue
        method, path = key.split(" ", 1)
        test_entries.append({
            "method": method,
            "path": path,
            "tested": False,
            "test_result": None,
            "subject": endpoint_meta.get("subject"),
            "summary": endpoint_meta.get("summary") or endpoint_meta.get("subject"),
            "path_params": re.findall(r"\{(\w+)\}", path),
            "needs_seed": method in ("GET", "PUT", "DELETE")
                          and bool(re.search(r"\{\w+\}", path)),
        })

    return {
        "app_slug": app_slug,
        "total_spec_endpoints": len(endpoints_block),
        "endpoints": test_entries,
    }


def write_registry(output_dir: Path, test_registry: dict[str, Any]) -> None:
    output_dir.mkdir(parents=True, exist_ok=True)
    (output_dir / "test_registry.json").write_text(
        json.dumps(test_registry, indent=2)
    )
