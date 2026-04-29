"""Scan implemented routes and build endpoint documentation + test registry.

Imports the app's routes module, reads the Route objects, matches them
against endpoints.json for metadata, and writes:
  - implemented_endpoints.json — full metadata for implemented endpoints
  - test_registry.json — test manifest with status tracking
"""

from __future__ import annotations

import json
import re
import sys
from importlib import import_module
from pathlib import Path
from typing import Any


def run_register_tests(ctx) -> None:
    """``register_tests`` stage — scan routes.py and emit registry + impl doc.

    The replica's routes module lives under ``backend/src/services/<slug>``;
    we load it via ``import_module`` so we observe whatever Starlette
    actually mounts (not what the spec claimed should exist). The
    sqlalchemy pre-import is a workaround for backend's local
    ``platform/`` package shadowing the stdlib ``platform`` module.
    """
    from pipeline.config import load_config

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

    try:
        implemented = scan_implemented_routes(routes_module)
        endpoints_doc = json.loads(endpoints_path.read_text())
        registry = build_test_registry(implemented, endpoints_doc, config.app_slug)

        # Preserve tested status from a prior registry. Entries that share
        # ``(method, path)`` with a previously-tested entry keep their
        # ``tested`` flag + ``test_result``, so re-running register_tests
        # after an extend exercises only the newly added endpoints. The
        # ``--force-retest`` flag opts out — every entry is left untested
        # so the next test_endpoints run sweeps the full surface.
        registry_path = output_dir / "test_registry.json"
        if not ctx.test_force_retest and registry_path.exists():
            previous = json.loads(registry_path.read_text())
            previous_by_key = {
                (entry["method"], entry["path"]): entry
                for entry in previous.get("endpoints") or []
            }
            preserved_count = 0
            for entry in registry["endpoints"]:
                prior = previous_by_key.get((entry["method"], entry["path"]))
                if prior and prior.get("tested"):
                    entry["tested"] = True
                    entry["test_result"] = prior.get("test_result")
                    preserved_count += 1
            if preserved_count:
                print(
                    f"  Preserved tested status for {preserved_count} "
                    f"endpoint(s) from previous registry"
                )

        # Build implemented_endpoints doc — subset of endpoints.json
        endpoints_block = endpoints_doc.get("endpoints") or {}
        matched: dict[str, Any] = {}
        for route in implemented:
            key = f"{route['method']} {route['path']}"
            if key in endpoints_block:
                matched[key] = endpoints_block[key]

        impl_doc = {
            "endpoints": matched,
            "schemas": endpoints_doc.get("schemas") or {},
        }
        write_registry(output_dir, impl_doc, registry)
        print(
            f"  {registry['implemented_count']} implemented, "
            f"{registry['unimplemented_count']} unimplemented "
            f"(of {registry['total_spec_endpoints']} total)"
        )
        print(f"  Wrote implemented_endpoints.json + test_registry.json to {output_dir}")
    except Exception as exc:
        print(f"  [error] Could not scan routes: {exc}")


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
) -> dict[str, Any]:
    """Build documentation + test registry from implemented routes."""
    endpoints_block = endpoints_doc.get("endpoints") or {}
    schemas_block = endpoints_doc.get("schemas") or {}

    matched_endpoints: dict[str, Any] = {}
    test_entries: list[dict[str, Any]] = []

    for route in implemented:
        method = route["method"]
        path = route["path"]
        key = f"{method} {path}"

        endpoint_meta = endpoints_block.get(key)
        if endpoint_meta:
            matched_endpoints[key] = endpoint_meta

        test_entry: dict[str, Any] = {
            "method": method,
            "path": path,
            "has_spec_metadata": endpoint_meta is not None,
            "tested": False,
            "test_result": None,
        }

        if endpoint_meta:
            test_entry["subject"] = endpoint_meta.get("subject")
            test_entry["summary"] = endpoint_meta.get("summary") or endpoint_meta.get("subject")

            path_params = re.findall(r"\{(\w+)\}", path)
            test_entry["path_params"] = path_params
            test_entry["needs_seed"] = method in ("GET", "PUT", "DELETE") and bool(path_params)

        test_entries.append(test_entry)

    unimplemented = []
    for key in endpoints_block:
        if key not in matched_endpoints:
            parts = key.split(" ", 1)
            if len(parts) == 2:
                unimplemented.append({"method": parts[0], "path": parts[1]})

    return {
        "app_slug": app_slug,
        "total_spec_endpoints": len(endpoints_block),
        "implemented_count": len(matched_endpoints),
        "unimplemented_count": len(unimplemented),
        "endpoints": test_entries,
        "unimplemented": unimplemented,
    }


def write_registry(
    output_dir: Path,
    implemented_endpoints: dict[str, Any],
    test_registry: dict[str, Any],
) -> None:
    output_dir.mkdir(parents=True, exist_ok=True)
    (output_dir / "implemented_endpoints.json").write_text(
        json.dumps(implemented_endpoints, indent=2)
    )
    (output_dir / "test_registry.json").write_text(
        json.dumps(test_registry, indent=2)
    )
