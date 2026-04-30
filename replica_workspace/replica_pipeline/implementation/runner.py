"""``implement`` and ``implement_responses`` stage runners.

The two stages share infrastructure (loading the extract output,
calling the LLM, writing prompts during ``--dry-run``) and both live
here. Prompt construction itself is in ``pipeline.prompts.implement``
(Pass 1, Pass 2, Extend) and ``pipeline.prompts.implement_responses``.

Order matters in the full pipeline — ``implement_responses`` runs
first to populate ``core/errors.py`` so each resource implementation
can reference the existing error constructors instead of redefining
them per-handler.
"""

from __future__ import annotations

import copy
import json
import re
from collections import defaultdict
from pathlib import Path

from replica_pipeline.config import load_config
from replica_pipeline.prompts.implement import (
    build_extend_prompt,
    build_pass1_prompt,
    build_pass2_prompt,
)
from replica_pipeline.prompts.implement_responses import build_implement_responses_prompt
from replica_pipeline.utils.llm import make_llm_call


def run_implement_responses(ctx) -> None:
    """``implement_responses`` stage — emit the standard error constructors.

    Computes the ``components/responses`` slice it needs on the fly from
    the spec + ``resources.json``. The slice is written to
    ``pipeline_out/responses.json`` solely as an LLM input file (the
    prompt tells the LLM to read it) — it's not a cross-stage artifact
    anymore.
    """
    config = load_config(ctx.config_path)
    output_dir = ctx.output_dir
    resources_path = output_dir / "resources.json"

    if not resources_path.exists():
        print("\n=== IMPLEMENT RESPONSES — skipped (resources.json missing, run extract first) ===")
        return

    resources_doc = json.loads(resources_path.read_text())
    spec = config.load_spec()
    responses_doc = _build_responses_doc(spec, resources_doc)
    response_count = len(responses_doc.get("responses", {}))

    if response_count == 0:
        print("\n=== IMPLEMENT RESPONSES — skipped (no component responses referenced by scoped endpoints) ===")
    else:
        # Persist as an LLM input file. Prompt path-references this file;
        # ``run_implement`` rescans ``core/errors.py`` directly afterwards.
        responses_path = output_dir / "responses.json"
        responses_path.write_text(json.dumps(responses_doc, indent=2))

        print(f"\n=== IMPLEMENT RESPONSES — {response_count} responses ({ctx.implement_model}) ===")
        prompt = build_implement_responses_prompt(
            app_name=config.app_name,
            target_dir=config.target_dir,
            responses_path=responses_path,
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
    print(f"  Found {len(constructors)} error constructors: {constructors}")


def _build_responses_doc(spec: dict, resources_doc: dict) -> dict:
    """Compute the ``components/responses`` slice referenced by scoped endpoints.

    Walks the spec's path items, keeps only operations whose
    ``"METHOD /path"`` key appears under some declared resource's
    ``endpoint_keys`` in ``resources.json``, then collects every
    ``$ref``-into-``components/responses`` plus the schemas those
    response bodies reference.
    """
    component_responses = (spec.get("components") or {}).get("responses") or {}
    component_schemas = (spec.get("components") or {}).get("schemas") or {}

    scoped_endpoints: set[str] = set()
    for resource in (resources_doc.get("resources") or {}).values():
        scoped_endpoints.update(resource.get("endpoint_keys") or [])

    scoped_response_names: set[str] = set()
    for path, path_item in (spec.get("paths") or {}).items():
        for method, operation in path_item.items():
            key = f"{method.upper()} {path}"
            if key not in scoped_endpoints:
                continue
            for _code, resp in (operation.get("responses") or {}).items():
                ref = resp.get("$ref", "")
                if ref.startswith("#/components/responses/"):
                    scoped_response_names.add(ref.split("/")[-1])

    responses: dict = {}
    referenced_schemas: dict = {}
    for name in sorted(scoped_response_names):
        body = component_responses.get(name)
        if body is None:
            continue
        responses[name] = copy.deepcopy(body)
        for _media_type, media in (body.get("content") or {}).items():
            schema = media.get("schema") or {}
            ref = schema.get("$ref")
            if isinstance(ref, str) and ref.startswith("#/components/schemas/"):
                schema_name = ref[len("#/components/schemas/"):]
                if schema_name in component_schemas:
                    referenced_schemas[schema_name] = copy.deepcopy(
                        component_schemas[schema_name]
                    )

    return {"responses": responses, "schemas": referenced_schemas}


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

    # Re-scan ``core/errors.py`` directly — the previous design wrote a
    # tiny ``implemented_responses.json`` from ``run_implement_responses``
    # for this stage to read back. The regex pass is cheap and removes
    # one file from the cross-stage handoff.
    implemented_constructors = _scan_error_constructors(
        config.target_dir / "core" / "errors.py"
    )

    print(f"\n=== IMPLEMENT — LLM builds entities ({ctx.implement_model}) ===")

    # Validate selection mode + figure out which endpoints to keep per resource.
    # ``selected_per_resource`` is either ``None`` (resource-centric: keep all)
    # or a ``{resource_name: set[endpoint_key]}`` filter.
    selected_per_resource = _resolve_selection(
        ctx, config, endpoints_doc, resources_doc, stage_name="implement",
    )

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
            # Filename pattern matches ``run_extend``: pass + purpose so
            # mixed create/extend dry-runs in the same prompt_dir don't
            # collide.
            (prompt_dir / f"{resource_name}_pass1_create.md").write_text(prompt_p1)
            if prompt_p2 is not None:
                (prompt_dir / f"{resource_name}_pass2_relationships.md").write_text(prompt_p2)
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
    *, stage_name: str = "implement",
) -> dict[str, set[str]] | None:
    """Translate ``selected_endpoints`` into a per-resource filter.

    Returns ``None`` in resource-centric mode (``--all-endpoints-per-resource``).
    In endpoint-centric mode, returns ``{resource: {endpoint_key, ...}}``.
    Raises ``SystemExit`` if neither a selection nor the flag was supplied.

    ``stage_name`` is woven into error messages so callers from extend
    don't see ``implement stage refuses to run`` and vice-versa.
    """
    if ctx.all_endpoints_per_resource:
        return None

    selected = list(config.selected_endpoints)
    if not selected:
        raise SystemExit(
            f"{stage_name} stage refuses to run: no `selected_endpoints` in app.yaml. "
            f"Either list the endpoints you want under `selected_endpoints:` "
            f"(e.g. `\"POST /tasks\"`), or pass --all-endpoints-per-resource "
            f"to {stage_name} every endpoint of every resource in app.yaml."
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
            f"{stage_name} stage refuses to run: every entry in `selected_endpoints` "
            f"was unknown or out-of-scope. Fix the list and rerun."
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
    """Bare table-name suffixes for every ``__tablename__`` in schema.py.

    Returns the set of strings produced by stripping the ``<app_slug>_``
    prefix from every ``__tablename__ = "..."`` declaration. The set
    includes both proper resource tables (``users``, ``tasks``) and any
    auxiliary tables named with the same prefix (association tables like
    ``user_team_association``, audit/log tables, etc.).

    The extra entries are harmless — the only callsite checks membership
    by canonical resource name, which never collides with auxiliary
    tables — but consumers should not treat the return value as
    "exclusively the canonical resources."

    Resources appearing here may be stubs (PK-only) or fully populated;
    the extend prompt tells the LLM to flesh out a stub if needed, so we
    don't try to distinguish.
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

    The regex assumes the canonical Starlette-style 3-arg ``Route(...)``
    that the LLM codegen emits today. If the file is non-trivially sized
    but the regex matches zero entries — likely because the codegen
    pattern drifted — we surface a warning so the caller can investigate
    rather than silently treating the resource as unimplemented.
    """
    if not routes_path.exists():
        return {}
    content = routes_path.read_text()
    matches = _ROUTE_RE.findall(content)
    if not matches and "Route(" in content:
        print(
            f"  [warn] {routes_path} contains 'Route(' calls but the regex "
            f"matched none — the codegen pattern may have changed. The "
            f"extend stage will treat this resource as unimplemented and "
            f"may regenerate handlers that already exist."
        )
    spec_endpoints = endpoints_doc.get("endpoints") or {}
    by_resource: dict[str, set[str]] = defaultdict(set)
    for path, methods_str in matches:
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
    implemented_constructors = _scan_error_constructors(
        config.target_dir / "core" / "errors.py"
    )

    print(f"\n=== EXTEND — LLM adds endpoints to existing replica ({ctx.implement_model}) ===")

    selected_per_resource = _resolve_selection(
        ctx, config, endpoints_doc, resources_doc, stage_name="extend",
    )
    # The extend entrypoint never exposes ``--all-endpoints-per-resource``,
    # so ``_resolve_selection`` should never return ``None`` here. Explicit
    # check (rather than ``assert``) so the failure mode survives ``-O``.
    if selected_per_resource is None:
        raise SystemExit(
            "extend stage cannot run in resource-centric mode "
            "(--all-endpoints-per-resource). The extend entrypoint requires "
            "an explicit `selected_endpoints` list."
        )

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
            # Filename pattern: ``{resource}_pass1_{mode}.md`` so a single
            # prompt_dir mixing CREATE and EXTEND outputs is unambiguous.
            pass1_filename = f"{resource_name}_pass1_create.md"
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
            pass1_filename = f"{resource_name}_pass1_extend.md"

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
                (prompt_dir / f"{resource_name}_pass2_relationships.md").write_text(prompt_p2)
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
