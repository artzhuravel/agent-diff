"""Per-endpoint reference extraction.

Walks one OpenAPI operation and emits every place it touches a
``config.resources.aliases_lookup`` token. Four narrow walks are
composed into a single per-endpoint record:

* **Group A — path** (``find_path_references``): URL segments and
  declared path parameters.
* **Group B — parameter** (``find_parameter_references``): query /
  header / cookie parameters declared on the path item or operation.
* **Group C — property** (``find_property_references``): object
  property names and ``$ref``-into-bound-schema values, recursively.
* **Group E — body** (``find_body_references``): top-level schema
  ``$ref``s in the request body and each declared response.

Each walk returns ``list[Reference]`` — a uniform shape with
``(resource, kind, location)``. ``kind`` discriminates the match site
(``url_segment``, ``path_parameter``, ``query``, ``header``, ``cookie``,
``body_request``, ``body_response``, ``property``); ``location``
carries the specific match (URL segment, parameter name, dotted
property path, or ``"<media_type>:<schema_name>"`` for body refs).
The composer (``find_endpoint_references``) runs all four against one
operation and infers the operation's subject via the "rightmost URL
alias" rule: walking URL segments right-to-left, the first token whose
normalized form hits ``aliases_lookup`` is the subject.

Group D — schema bindings — is built once per spec and lives in
``schema_bindings.py``; it's passed in as ``bindings``.
"""

from __future__ import annotations

from collections.abc import Iterator, Mapping
from dataclasses import dataclass
from typing import Any

from replica_pipeline.utils.text import normalize_identifier
from replica_pipeline.config import PipelineConfig

_SCHEMA_PREFIX = "#/components/schemas/"
_REQUEST_BODY_PREFIX = "#/components/requestBodies/"
_RESPONSE_PREFIX = "#/components/responses/"

_HTTP_METHODS = frozenset({
    "get", "post", "put", "patch", "delete", "head", "options", "trace",
})
_PARAMETER_LOCATIONS = frozenset({"query", "header", "cookie"})


# ---------------------------------------------------------------------------
# Unified reference record + per-endpoint composition.
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class Reference:
    """A single resource reference detected inside one endpoint.

    ``kind`` is one of: ``url_segment``, ``path_parameter``, ``query``,
    ``header``, ``cookie``, ``body_request``, ``body_response``,
    ``property``. ``location`` encodes the specific match site (URL
    segment, parameter name, dotted property path, or
    ``"<media_type>:<schema_name>"`` for body references).
    """
    resource: str
    kind: str
    location: str


@dataclass(frozen=True)
class EndpointReferences:
    method: str
    path: str
    subject: str | None
    subject_source: str   # "url_rightmost_alias" | "no_alias_in_url"
    references: list[Reference]


# ---------------------------------------------------------------------------
# Group A — path references.
# ---------------------------------------------------------------------------


def find_path_references(
    path: str,
    path_item: dict[str, Any],
    config: PipelineConfig,
) -> list[Reference]:
    """URL segments + declared path parameters that hit aliases_lookup.

    Assumes config aliases are fully expanded at load time — the loader
    produces every ``<alias>_<pk>`` form so a single whole-token lookup
    is enough (no split fallback, no suffix stripping at walk time).
    """
    aliases_lookup = config.resources.aliases_lookup
    candidates: list[tuple[str, str]] = []  # (token, kind)

    for segment in path.split("/"):
        stripped = segment.strip("{}")
        if stripped:
            candidates.append((stripped, "url_segment"))

    for block in _parameter_blocks(path_item):
        for parameter in block.get("parameters") or []:
            if not isinstance(parameter, dict) or parameter.get("in") != "path":
                continue
            name = parameter.get("name")
            if isinstance(name, str) and name:
                candidates.append((name, "path_parameter"))

    return _dedup_resolve(candidates, aliases_lookup)


# ---------------------------------------------------------------------------
# Group B — parameter references (query / header / cookie).
# ---------------------------------------------------------------------------


def find_parameter_references(
    path_item: dict[str, Any],
    config: PipelineConfig,
) -> list[Reference]:
    """Non-path parameter hits — the ones ``find_path_references`` skips.

    ``$ref`` parameters (without a local ``name``) are silently skipped;
    resolving them into ``components.parameters`` is a later milestone.
    """
    aliases_lookup = config.resources.aliases_lookup
    candidates: list[tuple[str, str]] = []  # (token, kind)

    for block in _parameter_blocks(path_item):
        for parameter in block.get("parameters") or []:
            if not isinstance(parameter, dict):
                continue
            location = parameter.get("in")
            if location not in _PARAMETER_LOCATIONS:
                continue
            name = parameter.get("name")
            if isinstance(name, str) and name:
                candidates.append((name, location))

    return _dedup_resolve(candidates, aliases_lookup)


# ---------------------------------------------------------------------------
# Group E — body references (request body + responses).
# ---------------------------------------------------------------------------


def find_body_references(
    operation: dict[str, Any],
    spec: dict[str, Any],
    bindings: Mapping[str, str],
) -> list[Reference]:
    """Top-level schema ``$ref``s in the body, resolved through Group D bindings.

    Top-level ``$ref``s into ``components.requestBodies`` /
    ``components.responses`` are dereferenced first. Descends into
    ``items`` and ``allOf`` / ``oneOf`` / ``anyOf`` branches, not
    properties (that's Group C). Each emitted reference has
    ``kind="body_request"`` or ``kind="body_response"`` and
    ``location="<media_type>:<schema_name>"``.
    """
    raw_components = spec.get("components")
    components: dict[str, Any] = raw_components if isinstance(raw_components, dict) else {}
    holders: list[tuple[str, dict[str, Any]]] = []  # (kind, content_dict)

    request_body = _deref(
        operation.get("requestBody"),
        _REQUEST_BODY_PREFIX,
        components.get("requestBodies") or {},
    )
    if isinstance(request_body, dict):
        content = request_body.get("content")
        if isinstance(content, dict):
            holders.append(("body_request", content))

    responses = operation.get("responses")
    if isinstance(responses, dict):
        response_components = components.get("responses") or {}
        for response in responses.values():
            response = _deref(response, _RESPONSE_PREFIX, response_components)
            if not isinstance(response, dict):
                continue
            content = response.get("content")
            if isinstance(content, dict):
                holders.append(("body_response", content))

    seen: set[tuple[str, str, str]] = set()
    references: list[Reference] = []
    for kind, content in holders:
        for media_type, media in content.items():
            if not isinstance(media, dict):
                continue
            for resource, schema_name in _walk_body_schema(media.get("schema"), bindings):
                location = f"{media_type}:{schema_name}"
                key = (resource, kind, location)
                if key in seen:
                    continue
                seen.add(key)
                references.append(Reference(resource, kind, location))
    return references


# ---------------------------------------------------------------------------
# Group C — property references (deep-walked over the body schema tree).
# ---------------------------------------------------------------------------


def find_property_references(
    schema: dict[str, Any],
    config: PipelineConfig,
    bindings: Mapping[str, str],
    component_schemas: Mapping[str, Any] | None = None,
    start_schema_name: str | None = None,
) -> list[Reference]:
    """Hits at object property nodes — by name and by ``$ref`` into a bound schema.

    Descends through inline ``properties``, ``items``,
    ``additionalProperties``, and composition branches. If
    ``component_schemas`` is given, ``$ref``s are also followed into
    their target schemas with a visited-set cycle guard; pass
    ``start_schema_name`` to pre-seed visited so self-refs don't loop.
    Each emitted reference has ``kind="property"`` and
    ``location`` = the dotted property path.
    """
    aliases_lookup = config.resources.aliases_lookup
    qualifier_prefixes = config.naming.qualifier_prefixes
    schemas = component_schemas or {}
    visited: set[str] = {start_schema_name} if start_schema_name else set()
    seen: set[tuple[str, str]] = set()
    references: list[Reference] = []

    def record(resource: str, path: tuple[str, ...]) -> None:
        location = ".".join(path)
        key = (resource, location)
        if key in seen:
            return
        seen.add(key)
        references.append(Reference(resource, "property", location))

    def resolve_name(name: str) -> str | None:
        hit = aliases_lookup.get(normalize_identifier(name))
        if hit is not None:
            return hit
        for prefix in qualifier_prefixes:
            if name.startswith(prefix):
                hit = aliases_lookup.get(normalize_identifier(name[len(prefix):]))
                if hit is not None:
                    return hit
        return None

    def walk(node: Any, path: tuple[str, ...]) -> None:
        if not isinstance(node, dict):
            return
        ref_at_top = node.get("$ref")
        if isinstance(ref_at_top, str) and ref_at_top.startswith(_SCHEMA_PREFIX):
            target_name = ref_at_top[len(_SCHEMA_PREFIX):]
            target_resource = bindings.get(target_name)
            if target_resource is not None and path:
                record(target_resource, path)
            if target_name not in visited:
                target_schema = schemas.get(target_name)
                if isinstance(target_schema, dict):
                    visited.add(target_name)
                    walk(target_schema, path)
            return
        for name, child in (node.get("properties") or {}).items():
            if not isinstance(name, str):
                continue
            child_path = path + (name,)
            hit = resolve_name(name)
            if hit is not None:
                record(hit, child_path)
            if isinstance(child, dict):
                walk(child, child_path)
        items = node.get("items")
        if isinstance(items, dict):
            walk(items, path)
        additional = node.get("additionalProperties")
        if isinstance(additional, dict):
            walk(additional, path)
        for key in ("allOf", "oneOf", "anyOf"):
            for branch in node.get(key) or []:
                walk(branch, path)

    walk(schema, ())
    return references


# ---------------------------------------------------------------------------
# Composer — runs all four walks against one operation.
# ---------------------------------------------------------------------------


def find_endpoint_references(
    method: str,
    path: str,
    spec: dict[str, Any],
    config: PipelineConfig,
    bindings: Mapping[str, str],
) -> EndpointReferences:
    path_item: dict[str, Any] = (spec.get("paths") or {}).get(path) or {}
    operation: dict[str, Any] = path_item.get(method.lower()) or {}

    references: list[Reference] = []
    references.extend(find_path_references(path, path_item, config))
    references.extend(find_parameter_references(path_item, config))
    references.extend(find_body_references(operation, spec, bindings))
    component_schemas = (spec.get("components") or {}).get("schemas") or {}
    for schema in _iter_body_schemas(operation, spec):
        references.extend(
            find_property_references(schema, config, bindings, component_schemas)
        )

    subject: str | None = None
    subject_source = "no_alias_in_url"
    aliases_lookup = config.resources.aliases_lookup
    for segment in reversed(path.split("/")):
        stripped = segment.strip("{}")
        if not stripped:
            continue
        resource = aliases_lookup.get(normalize_identifier(stripped))
        if resource is not None:
            subject, subject_source = resource, "url_rightmost_alias"
            break

    return EndpointReferences(
        method=method.upper(),
        path=path,
        subject=subject,
        subject_source=subject_source,
        references=references,
    )


# ---------------------------------------------------------------------------
# Module-private helpers.
# ---------------------------------------------------------------------------


def _dedup_resolve(
    candidates: list[tuple[str, str]],
    aliases_lookup: Mapping[str, str],
) -> list[Reference]:
    """Resolve each ``(token, kind)`` candidate to a ``Reference`` and drop dups."""
    seen: set[tuple[str, str, str]] = set()
    out: list[Reference] = []
    for token, kind in candidates:
        resource = aliases_lookup.get(normalize_identifier(token))
        if resource is None:
            continue
        key = (resource, kind, token)
        if key in seen:
            continue
        seen.add(key)
        out.append(Reference(resource=resource, kind=kind, location=token))
    return out


def _parameter_blocks(path_item: dict[str, Any]) -> list[dict[str, Any]]:
    """Path-level + per-method blocks that may carry a ``parameters`` list."""
    blocks: list[dict[str, Any]] = [path_item]
    for method, operation in path_item.items():
        if method in _HTTP_METHODS and isinstance(operation, dict):
            blocks.append(operation)
    return blocks


def _deref(node: Any, prefix: str, targets: Mapping[str, Any]) -> dict[str, Any] | None:
    """Resolve a ``$ref`` into ``components.<targets>`` if ``node`` carries one.

    Returns ``node`` unchanged when there is no ``$ref``, the resolved
    target dict when the ``$ref`` matches ``prefix``, or ``None`` when
    the node is malformed or the target is missing.
    """
    if not isinstance(node, dict):
        return None
    ref = node.get("$ref")
    if not isinstance(ref, str):
        return node
    if not ref.startswith(prefix):
        return None
    target = targets.get(ref[len(prefix):])
    return target if isinstance(target, dict) else None


def _walk_body_schema(
    schema: Any, bindings: Mapping[str, str],
) -> Iterator[tuple[str, str]]:
    """Yield ``(resource, schema_name)`` for every Group D-bound ``$ref``."""
    if not isinstance(schema, dict):
        return
    ref = schema.get("$ref")
    if isinstance(ref, str) and ref.startswith(_SCHEMA_PREFIX):
        name = ref[len(_SCHEMA_PREFIX):]
        target = bindings.get(name)
        if target is not None:
            yield target, name
        return
    items = schema.get("items")
    if isinstance(items, dict):
        yield from _walk_body_schema(items, bindings)
    for key in ("allOf", "oneOf", "anyOf"):
        for branch in schema.get(key) or []:
            yield from _walk_body_schema(branch, bindings)


def _iter_body_schemas(
    operation: dict[str, Any], spec: dict[str, Any],
) -> Iterator[dict[str, Any]]:
    """Yield each request/response media schema, dereferencing component bodies."""
    raw_components = spec.get("components")
    components: dict[str, Any] = raw_components if isinstance(raw_components, dict) else {}
    contents: list[Any] = []
    request_body = _deref(
        operation.get("requestBody"),
        _REQUEST_BODY_PREFIX,
        components.get("requestBodies") or {},
    )
    if isinstance(request_body, dict):
        contents.append(request_body.get("content"))
    responses = operation.get("responses") or {}
    if isinstance(responses, dict):
        response_components = components.get("responses") or {}
        for response in responses.values():
            response = _deref(response, _RESPONSE_PREFIX, response_components)
            if isinstance(response, dict):
                contents.append(response.get("content"))
    for content in contents:
        if not isinstance(content, dict):
            continue
        for media in content.values():
            if isinstance(media, dict) and isinstance(media.get("schema"), dict):
                yield media["schema"]
