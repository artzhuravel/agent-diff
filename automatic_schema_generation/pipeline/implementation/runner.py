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
from pipeline.implementation.build_prompt import (
    build_extend_prompt,
    build_pass1_prompt,
    build_pass2_prompt,
)
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
    """``implement`` stage — call the LLM for each resource (Pass 1 + Pass 2).

    Two modes:
      * Endpoint-centric (default): ``app.yaml`` lists ``selected_endpoints``
        and only those handlers/operations get generated. Each resource that
        owns at least one selected endpoint is processed.
      * Resource-centric (``--all-endpoints-per-resource``): every endpoint of
        every resource in ``app.yaml`` gets implemented, ignoring any
        ``selected_endpoints`` list.

    Selected endpoints that don't exist in the spec are skipped with a
    warning, on the assumption that the user will correct the typo and
    rerun. The stage fails only if zero valid endpoints survive.
    """
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

    # Validate selection mode + figure out which endpoints to keep per resource.
    # ``selected_per_resource`` is either ``None`` (resource-centric: keep all)
    # or a ``{resource_name: set[endpoint_key]}`` filter.
    selected_per_resource = _resolve_selection(ctx, config, endpoints_doc, resources_doc)

    if selected_per_resource is None:
        resource_names = ctx.only_resources or sorted(resources_doc["resources"].keys())
    else:
        # Endpoint-centric: only resources that own a selected endpoint.
        resource_names = sorted(selected_per_resource.keys())
        if ctx.only_resources:
            resource_names = [name for name in resource_names if name in set(ctx.only_resources)]

    if not resource_names:
        print("  [skip] no resources to implement after selection filtering")
        return

    order = _dependency_order(resource_names, resources_doc)
    print(f"  Order: {' → '.join(order)}")

    for index, resource_name in enumerate(order, 1):
        print(f"\n  [{index}/{len(order)}] {resource_name}")

        endpoint_filter = (
            selected_per_resource.get(resource_name)
            if selected_per_resource is not None
            else None
        )
        prompt_p1 = build_pass1_prompt(
            resource_name, resources_doc, endpoints_doc, config,
            spec=spec, implemented_constructors=implemented_constructors,
            endpoint_filter=endpoint_filter,
        )
        # Pass 2 only adds value when the resource has FK targets other
        # than itself; for FK-free resources it's a wasted LLM call.
        run_pass2 = _has_outgoing_fks(
            resources_doc["resources"][resource_name], resource_name
        )
        prompt_p2 = (
            build_pass2_prompt(
                resource_name, resources_doc, endpoints_doc, config, spec=spec,
            )
            if run_pass2 else None
        )

        if ctx.dry_run:
            prompt_dir = ctx.prompt_dir
            prompt_dir.mkdir(parents=True, exist_ok=True)
            (prompt_dir / f"{resource_name}_pass1.md").write_text(prompt_p1)
            if prompt_p2 is not None:
                (prompt_dir / f"{resource_name}_pass2.md").write_text(prompt_p2)
            print(f"    [dry-run] Saved prompts to {prompt_dir}")
            continue

        llm_call = make_llm_call(model=ctx.implement_model, timeout=900)

        print(f"    Pass 1 — base model ({len(prompt_p1):,} chars)...")
        llm_call(prompt_p1)

        if prompt_p2 is not None:
            print(f"    Pass 2 — relationships ({len(prompt_p2):,} chars)...")
            llm_call(prompt_p2)
        else:
            print(f"    Pass 2 — skipped (no outgoing FKs)")

        print(f"    Done.")


def _resolve_selection(
    ctx, config, endpoints_doc: dict, resources_doc: dict,
) -> dict[str, set[str]] | None:
    """Translate ``selected_endpoints`` into a per-resource filter.

    Returns ``None`` in resource-centric mode (``--all-endpoints-per-resource``).
    In endpoint-centric mode, returns ``{resource: {endpoint_key, ...}}``.
    Raises ``SystemExit`` if neither a selection nor the flag was supplied.
    """
    if ctx.all_endpoints_per_resource:
        return None

    selected = list(config.selected_endpoints)
    if not selected:
        raise SystemExit(
            "implement stage refuses to run: no `selected_endpoints` in app.yaml. "
            "Either list the endpoints you want under `selected_endpoints:` "
            "(e.g. `\"POST /tasks\"`), or pass --all-endpoints-per-resource "
            "to implement every endpoint of every resource in app.yaml."
        )

    spec_endpoints = endpoints_doc.get("endpoints") or {}
    declared_resources = set(resources_doc.get("resources") or {})

    valid: dict[str, set[str]] = {}
    unknown: list[str] = []
    out_of_scope: list[tuple[str, str]] = []

    for key in selected:
        meta = spec_endpoints.get(key)
        if meta is None:
            unknown.append(key)
            continue
        subject = meta.get("subject")
        if subject not in declared_resources:
            out_of_scope.append((key, subject or "<no subject>"))
            continue
        valid.setdefault(subject, set()).add(key)

    if unknown:
        print(
            f"  [warn] {len(unknown)} selected endpoint(s) not found in spec — "
            f"skipped: {', '.join(unknown)}"
        )
    if out_of_scope:
        formatted = ", ".join(f"{key} (subject={subject})" for key, subject in out_of_scope)
        print(
            f"  [warn] {len(out_of_scope)} selected endpoint(s) belong to a "
            f"resource not declared in app.yaml — skipped: {formatted}"
        )
    if not valid:
        raise SystemExit(
            "implement stage refuses to run: every entry in `selected_endpoints` "
            "was unknown or out-of-scope. Fix the list and rerun."
        )

    matched = sum(len(keys) for keys in valid.values())
    print(
        f"  Selection: {matched} endpoint(s) across "
        f"{len(valid)} resource(s)"
    )
    return valid


def _scan_error_constructors(errors_path: Path) -> list[str]:
    """Extract function names from core/errors.py."""
    if not errors_path.exists():
        return []
    content = errors_path.read_text()
    return re.findall(r"^def (\w+)", content, re.MULTILINE)


def _has_outgoing_fks(resource_doc: dict, resource_name: str) -> bool:
    """True if the resource references any *other* resource via FK.

    Self-references via URL segments don't count — they're nesting, not FKs.
    Used to gate Pass 2 in both ``run_implement`` and ``run_extend``.
    """
    outgoing = resource_doc.get("outgoing_references") or {}
    return bool(set(outgoing.keys()) - {resource_name})


_TABLENAME_RE = re.compile(r'__tablename__\s*=\s*["\']([^"\']+)["\']')
_ROUTE_RE = re.compile(
    r'Route\(\s*"([^"]+)"\s*,\s*\w+\s*,\s*methods=\[([^\]]+)\]'
)


def _scan_implemented_resources(schema_path: Path, app_slug: str) -> set[str]:
    """Resources whose ORM class already has a tablename in schema.py.

    Strips the ``<app_slug>_`` prefix and returns the bare resource names.
    A resource appearing here may be a stub (PK-only) or fully populated —
    we don't distinguish; the extend prompt tells the LLM to flesh it out
    if needed.
    """
    if not schema_path.exists():
        return set()
    content = schema_path.read_text()
    prefix = f"{app_slug}_"
    return {
        tablename[len(prefix):]
        for tablename in _TABLENAME_RE.findall(content)
        if tablename.startswith(prefix)
    }


def _scan_implemented_routes(
    routes_path: Path,
    endpoints_doc: dict,
) -> dict[str, set[str]]:
    """Map ``resource_name → set of "METHOD /path"`` already in routes.py.

    Each ``Route("/p", handler, methods=["X"])`` entry is attributed to its
    subject via ``endpoints.json``; entries with no matching spec endpoint
    (e.g. internal helpers) are dropped.
    """
    if not routes_path.exists():
        return {}
    content = routes_path.read_text()
    spec_endpoints = endpoints_doc.get("endpoints") or {}
    by_resource: dict[str, set[str]] = defaultdict(set)
    for path, methods_str in _ROUTE_RE.findall(content):
        for method in re.findall(r'"([A-Z]+)"', methods_str):
            key = f"{method} {path}"
            meta = spec_endpoints.get(key)
            if meta is None:
                continue
            subject = meta.get("subject")
            if subject:
                by_resource[subject].add(key)
    return dict(by_resource)


def run_extend(ctx) -> None:
    """``extend`` stage — add new endpoints to an already-generated replica.

    Per resource: check ``database/schema.py`` for an existing tablename.
    Present → extend mode (use ``build_extend_prompt`` with the new
    endpoints). Absent → create mode (fall back to ``build_pass1_prompt``).
    Endpoints already present in ``api/routes.py`` are warned-and-skipped.
    Pass 2 runs only when the resource has outgoing FKs.
    """
    config = load_config(ctx.config_path)

    if not config.selected_endpoints:
        raise SystemExit(
            "extend command requires `selected_endpoints` in app.yaml. "
            "List the new endpoints you want to add (e.g. \"POST /tasks\")."
        )

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

    print(f"\n=== EXTEND — LLM adds endpoints to existing replica ({ctx.implement_model}) ===")

    selected_per_resource = _resolve_selection(ctx, config, endpoints_doc, resources_doc)
    # ``ctx.all_endpoints_per_resource`` is False for the extend entrypoint
    # (it doesn't expose the flag), so ``_resolve_selection`` always returns
    # a dict here — None would indicate resource-centric mode.
    assert selected_per_resource is not None

    resource_names = sorted(selected_per_resource.keys())
    if ctx.only_resources:
        resource_names = [name for name in resource_names if name in set(ctx.only_resources)]
    if not resource_names:
        print("  [skip] no resources to extend after selection filtering")
        return

    schema_path = config.target_dir / "database" / "schema.py"
    routes_path = config.target_dir / "api" / "routes.py"
    implemented_resources = _scan_implemented_resources(schema_path, config.app_slug)
    implemented_routes = _scan_implemented_routes(routes_path, endpoints_doc)

    order = _dependency_order(resource_names, resources_doc)
    print(f"  Order: {' → '.join(order)}")

    for index, resource_name in enumerate(order, 1):
        print(f"\n  [{index}/{len(order)}] {resource_name}")
        requested = selected_per_resource[resource_name]

        if resource_name not in implemented_resources:
            # Brand-new resource — full create flow with Pass 1.
            print(f"    Mode: CREATE (no existing schema entry)")
            prompt_p1 = build_pass1_prompt(
                resource_name, resources_doc, endpoints_doc, config,
                spec=spec, implemented_constructors=implemented_constructors,
                endpoint_filter=requested,
            )
            pass1_filename = f"{resource_name}_pass1.md"
        else:
            already = requested & implemented_routes.get(resource_name, set())
            to_add = requested - already
            if already:
                print(
                    f"    [warn] {len(already)} endpoint(s) already in routes.py — "
                    f"skipping: {', '.join(sorted(already))}"
                )
            if not to_add:
                print(f"    [skip] all requested endpoints are already implemented")
                continue
            print(
                f"    Mode: EXTEND ({len(to_add)} new endpoint(s) to add)"
            )
            # Pass the full set of implemented routes for this resource as
            # the prompt's "fixed contract" — not just ``already`` (which is
            # the intersection with the user's request and only drives the
            # warn/skip log). Otherwise the LLM sees handlers in routes.py
            # that aren't enumerated as off-limits and may rewrite them.
            prompt_p1 = build_extend_prompt(
                resource_name, resources_doc, endpoints_doc, config,
                spec=spec, implemented_constructors=implemented_constructors,
                to_add=to_add,
                already_implemented=implemented_routes.get(resource_name, set()),
            )
            pass1_filename = f"{resource_name}_extend.md"

        run_pass2 = _has_outgoing_fks(
            resources_doc["resources"][resource_name], resource_name
        )
        prompt_p2 = (
            build_pass2_prompt(
                resource_name, resources_doc, endpoints_doc, config, spec=spec,
            )
            if run_pass2 else None
        )

        if ctx.dry_run:
            prompt_dir = ctx.prompt_dir
            prompt_dir.mkdir(parents=True, exist_ok=True)
            (prompt_dir / pass1_filename).write_text(prompt_p1)
            if prompt_p2 is not None:
                (prompt_dir / f"{resource_name}_pass2.md").write_text(prompt_p2)
            print(f"    [dry-run] Saved prompts to {prompt_dir}")
            continue

        llm_call = make_llm_call(model=ctx.implement_model, timeout=900)

        print(f"    Pass 1 ({len(prompt_p1):,} chars)...")
        llm_call(prompt_p1)

        if prompt_p2 is not None:
            print(f"    Pass 2 — relationships ({len(prompt_p2):,} chars)...")
            llm_call(prompt_p2)
        else:
            print(f"    Pass 2 — skipped (no outgoing FKs)")

        print(f"    Done.")


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
