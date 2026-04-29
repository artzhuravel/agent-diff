"""Documentation generation — endpoints.json + resources.json.

Two deterministic builders that produce the structured docs the
implement stage consumes:

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

Both functions are pure of LLM calls and re-runnable; only the
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

from pipeline._refs import collect_refs, transitive_closure
from pipeline.config import PipelineConfig
from pipeline.extraction.endpoint_references import find_endpoint_references
from pipeline.extraction.reference_groups import group_references_by_pair
from pipeline.extraction.schema_bindings import build_schema_bindings

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


def write_endpoints_document(document: dict[str, Any], output_path: Path) -> None:
    """Serialize ``document`` to ``output_path`` as indented JSON."""
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(json.dumps(document, indent=2))


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
        "references": {
            "path": [asdict(reference) for reference in result.path_references],
            "parameters": [asdict(reference) for reference in result.parameter_references],
            "body": [asdict(reference) for reference in result.body_references],
            "property": [asdict(reference) for reference in result.property_references],
        },
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


def classify_responses(spec: dict[str, Any]) -> tuple[dict[str, Any], dict[str, Any]]:
    """Split components/responses into generic (shared error schema) vs resource-specific.

    Returns (generic_responses, resource_responses). Generic responses use
    a schema referenced by 3+ responses — these are app-wide error patterns.
    Resource-specific responses use a unique schema or have domain-specific content.
    Status-only responses (no body) are included in generic.
    """
    component_responses = (spec.get("components") or {}).get("responses") or {}
    if not component_responses:
        return {}, {}

    # Count how many responses reference each schema.
    from collections import Counter
    schema_usage: Counter[str] = Counter()
    for name, body in component_responses.items():
        ref = _response_schema_ref(body)
        if ref:
            schema_usage[ref] += 1

    # A schema is shared if 3+ responses use it, OR if its name indicates
    # an error/validation pattern (these are generic even if only one
    # response definition references them, since endpoints reuse them widely).
    error_keywords = {"error", "validation"}
    shared_schemas = set()
    for schema, count in schema_usage.items():
        schema_name = schema.rsplit("/", 1)[-1].lower().replace("-", "_")
        if count >= 3 or any(keyword in schema_name for keyword in error_keywords):
            shared_schemas.add(schema)

    component_schemas = (spec.get("components") or {}).get("schemas") or {}
    generic: dict[str, Any] = {}
    resource_specific: dict[str, Any] = {}

    for name, body in component_responses.items():
        content = body.get("content") or {}
        has_body = bool(content)
        ref = _response_schema_ref(body)

        entry = copy.deepcopy(body)
        if ref and ref in component_schemas:
            entry["_resolved_schema"] = copy.deepcopy(component_schemas[ref])

        if not has_body or ref in shared_schemas:
            generic[name] = entry
        else:
            resource_specific[name] = entry

    return generic, resource_specific


def _response_schema_ref(response_body: dict[str, Any]) -> str | None:
    """Extract the schema $ref from a response body, if any."""
    content = response_body.get("content") or {}
    for _media_type, media in content.items():
        schema = media.get("schema") or {}
        ref = schema.get("$ref")
        if isinstance(ref, str):
            return ref
    return None


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


def write_resources_document(document: dict[str, Any], output_path: Path) -> None:
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
