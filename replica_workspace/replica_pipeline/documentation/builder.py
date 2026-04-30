"""Documentation generation — endpoints.json + resources.json + api docs.

Three deterministic builders that produce the structured docs the
pipeline consumes (or that downstream tooling reads):

* ``generate_endpoints_document`` — per-endpoint catalog with
  parameters, body, responses, and Group A/B/C/E reference evidence,
  plus the transitive closure of every component schema reachable
  from any endpoint. ``$ref``s are rewritten from
  ``#/components/schemas/*`` to ``#/schemas/*`` so the top-level
  ``schemas`` block replaces ``spec.components.schemas`` for
  downstream consumption.
* ``generate_resources_document`` — resource-first pivot built on
  top of an ``endpoints.json`` document, grouping endpoint keys,
  bound schemas, and outgoing/incoming reference evidence per
  configured resource.
* ``generate_api_docs_document`` — filtered subset of an endpoints
  document containing only implemented endpoints, with the schemas
  block trimmed to the transitive closure reachable from those
  endpoints. Self-contained: every ``$ref`` resolves locally.

All three are pure of LLM calls and re-runnable; only the
``_meta.generated_at`` field changes between runs.
"""

from __future__ import annotations

import copy
import hashlib
import json
from collections.abc import Mapping
from dataclasses import asdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from replica_pipeline.utils.refs import collect_refs, transitive_closure
from replica_pipeline.config import PipelineConfig
from replica_pipeline.extraction.endpoint_references import find_endpoint_references
from replica_pipeline.extraction.reference_groups import group_references_by_pair
from replica_pipeline.extraction.schema_bindings import build_schema_bindings

_HTTP_METHODS = frozenset({
    "get", "post", "put", "patch", "delete", "head", "options", "trace",
})
_OLD_REF_PREFIX = "#/components/schemas/"
_NEW_REF_PREFIX = "#/schemas/"


# ---------------------------------------------------------------------------
# endpoints.json — per-endpoint catalog with reachable schemas inlined.
# ---------------------------------------------------------------------------


def generate_endpoints_document(
    spec: dict[str, Any],
    config: PipelineConfig,
    bindings: Mapping[str, str] | None = None,
) -> dict[str, Any]:
    """Build the endpoints.json document structure."""
    if bindings is None:
        bindings = build_schema_bindings(spec, config)

    endpoints: dict[str, dict[str, Any]] = {}
    paths = spec.get("paths") or {}
    if isinstance(paths, dict):
        for path, path_item in paths.items():
            if not isinstance(path_item, dict):
                continue
            for method in _HTTP_METHODS:
                operation = path_item.get(method)
                if not isinstance(operation, dict):
                    continue
                entry = _build_entry(method, path, operation, spec, config, bindings)
                endpoints[f"{method.upper()} {path}"] = entry

    schemas = _collect_transitive_schemas(endpoints, spec)
    endpoints = _rewrite_refs(endpoints)
    schemas = _rewrite_refs(schemas)

    return {
        "_meta": {
            "generated_at": datetime.now(timezone.utc).isoformat(),
            "config_path": str(config.config_path) if config.config_path else None,
            "endpoint_count": len(endpoints),
            "schema_count": len(schemas),
        },
        "endpoints": endpoints,
        "schemas": schemas,
    }


def _build_entry(
    method: str,
    path: str,
    operation: dict[str, Any],
    spec: dict[str, Any],
    config: PipelineConfig,
    bindings: Mapping[str, str],
) -> dict[str, Any]:
    result = find_endpoint_references(method, path, spec, config, bindings)
    responses = _deref_responses(operation.get("responses") or {}, spec)
    return {
        "method": method.upper(),
        "path": path,
        "subject": result.subject,
        "subject_source": result.subject_source,
        "parameters": copy.deepcopy(operation.get("parameters") or []),
        "request_body": copy.deepcopy(operation.get("requestBody")),
        "responses": responses,
        # Flat list of unified ``Reference`` records — discriminate via
        # ``kind`` (url_segment / path / query / header / cookie /
        # body_request / body_response / property).
        "references": [asdict(reference) for reference in result.references],
    }


def _deref_responses(
    responses: dict[str, Any],
    spec: dict[str, Any],
) -> dict[str, Any]:
    """Resolve $ref pointers in response objects (components/responses)."""
    component_responses = (spec.get("components") or {}).get("responses") or {}
    result: dict[str, Any] = {}
    for status_code, response in responses.items():
        if isinstance(response, dict) and "$ref" in response:
            ref = response["$ref"]
            prefix = "#/components/responses/"
            if ref.startswith(prefix):
                name = ref[len(prefix):]
                resolved = component_responses.get(name)
                if isinstance(resolved, dict):
                    result[status_code] = copy.deepcopy(resolved)
                    continue
        result[status_code] = copy.deepcopy(response)
    return result


def _collect_transitive_schemas(
    endpoints: dict[str, Any],
    spec: dict[str, Any],
) -> dict[str, Any]:
    """Collect every component schema transitively reachable from ``endpoints``."""
    raw_components = (spec.get("components") or {}).get("schemas") or {}
    component_schemas: dict[str, Any] = raw_components if isinstance(raw_components, dict) else {}

    seeds = collect_refs(endpoints, _OLD_REF_PREFIX)
    reachable = transitive_closure(seeds, component_schemas, _OLD_REF_PREFIX)

    return {
        name: copy.deepcopy(component_schemas[name])
        for name in sorted(reachable)
        if name in component_schemas
    }


def _rewrite_refs(node: Any) -> Any:
    """Return a copy of ``node`` with every schema ``$ref`` prefix rewritten."""
    if isinstance(node, dict):
        result: dict[str, Any] = {}
        for key, value in node.items():
            if key == "$ref" and isinstance(value, str) and value.startswith(_OLD_REF_PREFIX):
                result[key] = _NEW_REF_PREFIX + value[len(_OLD_REF_PREFIX):]
            else:
                result[key] = _rewrite_refs(value)
        return result
    if isinstance(node, list):
        return [_rewrite_refs(item) for item in node]
    return node


# ---------------------------------------------------------------------------
# resources.json — resource-first pivot of the endpoints document.
# ---------------------------------------------------------------------------


def generate_resources_document(
    spec: dict[str, Any],
    config: PipelineConfig,
    endpoints_document: dict[str, Any],
    bindings: Mapping[str, str] | None = None,
) -> dict[str, Any]:
    """Build the resources.json document structure."""
    if bindings is None:
        bindings = build_schema_bindings(spec, config)

    groups = group_references_by_pair(spec, config, bindings)
    schemas_block = endpoints_document.get("schemas") or {}
    endpoints_block = endpoints_document.get("endpoints") or {}

    # Invert the bindings map: resource → list of schema names.
    schemas_by_resource: dict[str, list[str]] = {}
    for schema_name, resource in bindings.items():
        schemas_by_resource.setdefault(resource, []).append(schema_name)

    # Partition endpoint keys by subject.
    endpoint_keys_by_subject: dict[str, list[str]] = {}
    for key, entry in endpoints_block.items():
        subject = entry.get("subject")
        if isinstance(subject, str):
            endpoint_keys_by_subject.setdefault(subject, []).append(key)

    resources: dict[str, dict[str, Any]] = {}
    for resource_name in sorted(config.resources.aliases_by_resource.keys()):
        outgoing: dict[str, list[dict[str, Any]]] = {}
        incoming: dict[str, list[dict[str, Any]]] = {}
        for (source, target), evidence_list in groups.items():
            serialized = [asdict(evidence) for evidence in evidence_list]
            if source == resource_name:
                outgoing.setdefault(target, []).extend(serialized)
            if target == resource_name and source != resource_name:
                incoming.setdefault(source, []).extend(serialized)

        bound_names = sorted(schemas_by_resource.get(resource_name, []))
        bound_schemas = {
            name: schemas_block[name]
            for name in bound_names
            if name in schemas_block
        }

        resources[resource_name] = {
            "resource": resource_name,
            "primary_key": config.resources.primary_keys_lookup.get(resource_name),
            "bound_schemas": bound_schemas,
            "endpoint_keys": sorted(endpoint_keys_by_subject.get(resource_name, [])),
            "outgoing_references": outgoing,
            "incoming_references": incoming,
        }

    return {
        "_meta": {
            "generated_at": datetime.now(timezone.utc).isoformat(),
            "config_path": str(config.config_path) if config.config_path else None,
            "resource_count": len(resources),
            "source_endpoints_hash": _hash_document(endpoints_document),
        },
        "resources": resources,
    }


# ---------------------------------------------------------------------------
# api_docs document — implemented-only slice with closure-trimmed schemas.
# ---------------------------------------------------------------------------


def generate_api_docs_document(
    spec: dict[str, Any],
    implemented_keys: set[str],
) -> dict[str, Any]:
    """Curated, flattened docs for implemented endpoints.

    Mirrors the convention of the hand-curated docs at
    ``examples/<slug>/testsuites/<slug>_docs/<slug>_api_full_docs.json``:

    * Output is a flat dict keyed by ``"METHOD /path"`` — no wrapper,
      no ``_meta``, no separate schemas block. Top-level keys are
      endpoint identifiers, values are per-endpoint docs.
    * Each entry: ``{description, parameters: {path|query|header|body:
      {name: {type, required, description}}}}``. ``description`` comes
      from the operation's ``summary`` (preferred) or first paragraph
      of ``description``.
    * Body parameters are flattened with dotted paths
      (``parent.id`` for nested ``parent: {id: ...}``). Object-typed
      parents are documented at their own level too, so both
      ``parent`` and ``parent.id`` appear.
    * All ``$ref`` chains are resolved inline — no refs in the output.

    Sourced from the *original* OpenAPI spec rather than
    ``endpoints.json``, because that's where ``$ref``s in their native
    form live (``#/components/parameters/...``,
    ``#/components/requestBodies/...``).
    """
    paths = spec.get("paths") or {}
    docs: dict[str, dict[str, Any]] = {}

    for key in sorted(implemented_keys):
        method, path = key.split(" ", 1)
        path_item = paths.get(path) or {}
        operation = path_item.get(method.lower()) or {}
        if not operation:
            continue

        entry: dict[str, Any] = {}
        description = _operation_description(operation)
        if description:
            entry["description"] = description

        parameters = _flatten_parameters(operation, path_item, spec)
        if parameters:
            entry["parameters"] = parameters

        docs[key] = entry

    return docs


# ---------------------------------------------------------------------------
# api_docs helpers — flatten, resolve $refs, group by location
# ---------------------------------------------------------------------------


_PARAM_REF_PREFIX = "#/components/parameters/"
_REQUEST_BODY_REF_PREFIX = "#/components/requestBodies/"
_SCHEMA_REF_PREFIX = "#/components/schemas/"


def _operation_description(operation: dict[str, Any]) -> str:
    """Pick a one-paragraph description for the endpoint.

    Prefers ``summary`` (typically a single sentence). Falls back to
    the first paragraph of ``description`` when summary is missing.
    """
    summary = (operation.get("summary") or "").strip()
    if summary:
        return summary
    description = (operation.get("description") or "").strip()
    if description:
        return description.split("\n\n", 1)[0].strip()
    return ""


def _flatten_parameters(
    operation: dict[str, Any],
    path_item: dict[str, Any],
    spec: dict[str, Any],
) -> dict[str, dict[str, dict[str, Any]]]:
    """Resolve + group + flatten parameters by location.

    Walks path_item-level + operation-level parameters, resolves any
    component ``$ref``s, groups by ``in``, and reduces each entry to
    ``{type, required, description}``. Body parameters are pulled from
    ``operation.requestBody`` and flattened with dotted paths.
    """
    component_params = (spec.get("components") or {}).get("parameters") or {}

    grouped: dict[str, dict[str, dict[str, Any]]] = {}
    for source in (path_item.get("parameters") or [], operation.get("parameters") or []):
        for parameter in source:
            if not isinstance(parameter, dict):
                continue
            ref = parameter.get("$ref")
            if isinstance(ref, str) and ref.startswith(_PARAM_REF_PREFIX):
                parameter = component_params.get(ref[len(_PARAM_REF_PREFIX):]) or {}
            location = parameter.get("in")
            name = parameter.get("name")
            if not location or not name:
                continue
            grouped.setdefault(location, {})[name] = {
                "type": _simple_type(parameter.get("schema") or {}, spec),
                "required": bool(parameter.get("required")),
                "description": _short_description(parameter.get("description")),
            }

    body = _flatten_request_body(operation.get("requestBody"), spec)
    if body:
        grouped["body"] = body

    return grouped


def _flatten_request_body(
    request_body: Any,
    spec: dict[str, Any],
) -> dict[str, dict[str, Any]]:
    """Resolve the request body and emit a flat property dict.

    Picks JSON content (``application/json`` preferred, otherwise the
    first media type), resolves the schema's ``$ref`` chain, and walks
    its properties recursively. Object-valued properties contribute
    both their own entry (type=object) and dotted entries for each
    leaf — so ``{parent: {id, type}}`` produces ``parent``, ``parent.id``,
    ``parent.type``.
    """
    if not isinstance(request_body, dict):
        return {}

    component_request_bodies = (spec.get("components") or {}).get("requestBodies") or {}
    ref = request_body.get("$ref")
    if isinstance(ref, str) and ref.startswith(_REQUEST_BODY_REF_PREFIX):
        request_body = component_request_bodies.get(ref[len(_REQUEST_BODY_REF_PREFIX):]) or {}
    if not isinstance(request_body, dict):
        return {}

    content = request_body.get("content") or {}
    media = content.get("application/json")
    if media is None and content:
        # First defined media type, whatever it is.
        media = next(iter(content.values()))
    if not isinstance(media, dict):
        return {}
    schema = media.get("schema")
    if not isinstance(schema, dict):
        return {}

    out: dict[str, dict[str, Any]] = {}
    _walk_body_properties(schema, "", spec, out, visited=set())
    return out


def _walk_body_properties(
    schema: Any,
    prefix: str,
    spec: dict[str, Any],
    out: dict[str, dict[str, Any]],
    visited: set[str],
) -> None:
    """Recurse through a schema's properties, emitting dotted entries.

    Handles ``$ref`` resolution with cycle guard, ``allOf`` composition
    (merges properties from all branches), and nested objects.
    """
    schema = _resolve_schema(schema, spec, visited)
    if not isinstance(schema, dict):
        return

    # ``allOf`` is treated as a property merge — every branch contributes
    # its properties at the same level.
    for branch in schema.get("allOf") or []:
        _walk_body_properties(branch, prefix, spec, out, visited.copy())

    properties = schema.get("properties") or {}
    required = set(schema.get("required") or [])
    for name, prop_schema in properties.items():
        if not isinstance(prop_schema, dict):
            continue
        full_name = f"{prefix}.{name}" if prefix else name
        resolved_prop = _resolve_schema(prop_schema, spec, visited.copy()) or {}
        out[full_name] = {
            "type": _simple_type(prop_schema, spec),
            "required": name in required,
            "description": _short_description(resolved_prop.get("description")),
        }
        # Recurse if the property has further structure to expand. Object
        # schemas come in three flavors here: explicit ``type: object``,
        # bare ``properties`` block, or ``allOf`` composition (which the
        # function header handles by walking each branch with the same
        # prefix). We don't recurse into ``oneOf`` / ``anyOf`` because
        # those represent alternative shapes — flattening would conflate
        # mutually-exclusive properties.
        if (
            resolved_prop.get("properties")
            or resolved_prop.get("type") == "object"
            or resolved_prop.get("allOf")
        ):
            _walk_body_properties(resolved_prop, full_name, spec, out, visited.copy())
        elif resolved_prop.get("type") == "array":
            items = resolved_prop.get("items")
            if isinstance(items, dict):
                items_resolved = _resolve_schema(items, spec, visited.copy()) or {}
                if items_resolved.get("properties") or items_resolved.get("allOf"):
                    _walk_body_properties(items, f"{full_name}[]", spec, out, visited.copy())


def _resolve_schema(
    schema: Any,
    spec: dict[str, Any],
    visited: set[str],
) -> dict[str, Any] | None:
    """Follow ``$ref`` chains in ``components.schemas`` to a concrete body.

    ``visited`` is a set of schema names already on the current chain;
    on a cycle we return ``None`` so the caller can stop.
    """
    component_schemas = (spec.get("components") or {}).get("schemas") or {}
    while isinstance(schema, dict):
        ref = schema.get("$ref")
        if not isinstance(ref, str) or not ref.startswith(_SCHEMA_REF_PREFIX):
            return schema
        name = ref[len(_SCHEMA_REF_PREFIX):]
        if name in visited:
            return None
        visited.add(name)
        schema = component_schemas.get(name)
    return schema if isinstance(schema, dict) else None


def _simple_type(schema: Any, spec: dict[str, Any]) -> str:
    """Reduce a JSON Schema to a one-word type string for docs.

    Resolves a top-level ``$ref`` so the type comes from the target.
    Strips ``"null"`` from union types (``["string", "null"]`` → ``"string"``).
    Falls back to ``"object"`` for composed schemas without an explicit type.
    """
    if not isinstance(schema, dict):
        return "object"
    resolved = _resolve_schema(schema, spec, set()) or schema
    raw_type = resolved.get("type")
    if isinstance(raw_type, list):
        non_null = [t for t in raw_type if t != "null"]
        return non_null[0] if non_null else "object"
    if raw_type:
        return str(raw_type)
    if resolved.get("properties"):
        return "object"
    if resolved.get("oneOf") or resolved.get("anyOf") or resolved.get("allOf"):
        return "object"
    if resolved.get("items"):
        return "array"
    return "object"


def _short_description(value: Any) -> str:
    """First paragraph of a description, trimmed."""
    if not isinstance(value, str):
        return ""
    text = value.strip()
    if not text:
        return ""
    return text.split("\n\n", 1)[0].strip()


def write_api_docs_document(document: dict[str, Any], output_path: Path) -> None:
    """Serialize ``document`` to ``output_path`` as indented JSON."""
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(json.dumps(document, indent=2))


def _hash_document(document: dict[str, Any]) -> str:
    """Stable SHA256 of the document, excluding ``_meta.generated_at``."""
    scrubbed = dict(document)
    meta = dict(document.get("_meta") or {})
    meta.pop("generated_at", None)
    scrubbed["_meta"] = meta
    payload = json.dumps(scrubbed, sort_keys=True).encode("utf-8")
    return hashlib.sha256(payload).hexdigest()
