"""Per-endpoint reference extraction.

Walks one OpenAPI operation and emits every place it touches a
configured-resource alias. Two lookup tables are consulted:
``name_variants_lookup`` for URL-subject inference (Group A and the
rightmost-alias rule), and ``aliases_lookup`` (the union of name
variants and property aliases) for everything else. The split keeps
role words like ``assignee`` from leaking into URL subject inference
while still letting them resolve at parameter and property sites.

Four narrow walks are composed into a single per-endpoint record:

* **Group A — URL segments** (``find_url_segment_references``): tokens
  parsed from the URL string itself (``/tasks/{task_gid}`` → ``tasks``,
  ``task_gid``). Independent of the spec's ``parameters`` array.
* **Group B — parameters** (``find_parameter_references``): every entry
  in the operation's declared ``parameters`` list — ``path``, ``query``,
  ``header``, ``cookie``.
* **Group C — property** (``find_property_references``): object
  property names and ``$ref``-into-bound-schema values, recursively.
* **Group E — body** (``find_body_references``): top-level schema
  ``$ref``s in the request body and each declared response.

Each walk returns ``list[Reference]`` — a uniform shape with
``(resource, kind, location)``. ``kind`` discriminates the match site
(``url_segment``, ``path``, ``query``, ``header``, ``cookie``,
``body_request``, ``body_response``, ``property``); ``location``
carries the specific match (URL segment, parameter name, dotted
property path, or ``"<media_type>:<schema_name>"`` for body refs).
The composer (``find_endpoint_references``) runs all four against one
operation and infers the operation's subject via the "rightmost URL
alias" rule: walking URL segments right-to-left, the first token whose
normalized form hits ``name_variants_lookup`` is the subject.

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
_PARAMETER_LOCATIONS = frozenset({"path", "query"})


# ---------------------------------------------------------------------------
# Unified reference record + per-endpoint composition.
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class Reference:
    """A single resource reference detected inside one endpoint.

    ``kind`` is one of: ``url_segment``, ``path``, ``query``,
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
# Group A — URL-segment references (parsed from the URL string itself).
# ---------------------------------------------------------------------------


def find_url_segment_references(
    path: str,
    config: PipelineConfig,
) -> list[Reference]:
    """Tokens inferred from the URL string — independent of the spec.

    Walks ``path.split("/")``, strips ``{}`` brackets, and resolves each
    segment against ``name_variants_lookup`` (NOT the broader
    ``aliases_lookup``). This is how we learn that ``/tasks/{task_gid}``
    is "about tasks" even when the spec doesn't declare ``tasks``
    anywhere in its parameters list.

    Using ``name_variants_lookup`` keeps role-word property aliases
    (``assignee``, ``owner``, ``follower``) out of URL-subject inference
    — a path like ``/members/{id}`` should not resolve to ``users`` just
    because ``member`` is a property alias of ``users``. Group B
    (``find_parameter_references``) still picks those up via the
    declared ``parameters`` array using the union table.
    """
    name_variants_lookup = config.resources.name_variants_lookup
    candidates: list[tuple[str, str]] = []  # (token, kind)

    for segment in path.split("/"):
        stripped = segment.strip("{}")
        if stripped:
            candidates.append((stripped, "url_segment"))

    return _dedup_resolve(candidates, name_variants_lookup)


# ---------------------------------------------------------------------------
# Group B — declared-parameter references (path / query / header / cookie).
# ---------------------------------------------------------------------------


def find_parameter_references(
    path_item: dict[str, Any],
    config: PipelineConfig,
    context_resource: str | None = None,
) -> list[Reference]:
    """Hits in the operation's declared ``parameters`` array.

    Covers every ``in`` location the spec declares — ``path`` /
    ``query`` / ``header`` / ``cookie``. Path parameters live here too
    (alongside query/header/cookie) because they share the same shape:
    a ``parameters`` array entry with ``in``, ``name``, ``required``,
    ``schema``. URL-segment-only inferences (paths whose pieces aren't
    declared as parameters) come from ``find_url_segment_references``.

    Resolution uses the Path B context-aware resolver. The
    ``context_resource`` argument should be the endpoint's URL subject
    (computed by ``find_endpoint_references``); it disambiguates
    parameters whose name matches a property_alias of multiple
    resources. ``$ref`` parameters (without a local ``name``) are
    silently skipped; resolving them into ``components.parameters`` is
    a later milestone.
    """
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

    return _dedup_resolve_contextual(candidates, config, context_resource)


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
    context_resource: str | None = None,
) -> list[Reference]:
    """Hits at object property nodes — by name and by ``$ref`` into a bound schema.

    Descends through inline ``properties``, ``items``,
    ``additionalProperties``, and composition branches. If
    ``component_schemas`` is given, ``$ref``s are also followed into
    their target schemas with a visited-set cycle guard; pass
    ``start_schema_name`` to pre-seed visited so self-refs don't loop.
    Each emitted reference has ``kind="property"`` and
    ``location`` = the dotted property path.

    Path B resolution: the ``context_resource`` argument seeds the
    context for the outer schema. As the walker follows a ``$ref`` into
    a target schema, the context updates to that target's Group D
    binding (when bound) so that contextual property aliases resolve to
    the right resource. A field named ``insert_after`` walked under
    ``SectionRequest`` (bound to ``sections``) resolves to ``sections``;
    walked under ``SectionTaskInsertRequest`` (bound to ``tasks``) it
    resolves to ``tasks``.
    """
    qualifier_prefixes = config.naming.qualifier_prefixes
    resolver = config.resources.resolve_with_context
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

    def resolve_name(name: str, context: str | None) -> str | None:
        hit = resolver(normalize_identifier(name), context)
        if hit is not None:
            return hit
        for prefix in qualifier_prefixes:
            if name.startswith(prefix):
                hit = resolver(normalize_identifier(name[len(prefix):]), context)
                if hit is not None:
                    return hit
        return None

    def walk(node: Any, path: tuple[str, ...], context: str | None) -> None:
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
                    # Update context to the target schema's binding when
                    # one exists; otherwise keep the parent's context so
                    # unbound nested schemas inherit their enclosing
                    # resource's interpretation.
                    inner_context = bindings.get(target_name) or context
                    walk(target_schema, path, inner_context)
            return
        for name, child in (node.get("properties") or {}).items():
            if not isinstance(name, str):
                continue
            child_path = path + (name,)
            hit = resolve_name(name, context)
            if hit is not None:
                record(hit, child_path)
            if isinstance(child, dict):
                walk(child, child_path, context)
        items = node.get("items")
        if isinstance(items, dict):
            walk(items, path, context)
        additional = node.get("additionalProperties")
        if isinstance(additional, dict):
            walk(additional, path, context)
        for key in ("allOf", "oneOf", "anyOf"):
            for branch in node.get(key) or []:
                walk(branch, path, context)

    walk(schema, (), context_resource)
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

    # Compute the URL subject FIRST so it can seed the context for the
    # parameter and property walks. Subject inference uses
    # ``name_variants_lookup`` only — see the corresponding note on
    # ``find_url_segment_references``. Property aliases (``assignee``,
    # ``follower``) live in the union table but don't qualify as
    # URL-subject markers; otherwise a ``/followers/...`` endpoint would
    # mis-attribute to ``users``.
    subject: str | None = None
    subject_source = "no_alias_in_url"
    name_variants_lookup = config.resources.name_variants_lookup
    for segment in reversed(path.split("/")):
        stripped = segment.strip("{}")
        if not stripped:
            continue
        resource = name_variants_lookup.get(normalize_identifier(stripped))
        if resource is not None:
            subject, subject_source = resource, "url_rightmost_alias"
            break

    references: list[Reference] = []
    references.extend(find_url_segment_references(path, config))
    references.extend(
        find_parameter_references(path_item, config, context_resource=subject)
    )
    references.extend(find_body_references(operation, spec, bindings))
    component_schemas = (spec.get("components") or {}).get("schemas") or {}
    for schema in _iter_body_schemas(operation, spec):
        # Inline body schemas have no Group D binding of their own —
        # seed their walk with the URL subject so contextual property
        # aliases resolve correctly. The walker switches to the target
        # schema's binding when it follows a ``$ref``.
        references.extend(
            find_property_references(
                schema, config, bindings, component_schemas,
                context_resource=subject,
            )
        )

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
    """Resolve each ``(token, kind)`` candidate via a strict lookup; drop dups.

    Used by Group A (URL segments) where the lookup is
    ``name_variants_lookup`` — strict, single-valued, no contextual
    disambiguation needed.
    """
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


def _dedup_resolve_contextual(
    candidates: list[tuple[str, str]],
    config: PipelineConfig,
    context_resource: str | None,
) -> list[Reference]:
    """Resolve via the Path B contextual resolver; drop dups.

    Used by Group B (parameters): a parameter named ``insert_after``
    resolves to the resource that owns it via ``property_aliases``,
    using the endpoint's URL subject as the disambiguating context.
    Tokens that resolve to ``None`` (multi-owner property_aliases with
    no context match) are dropped — better to omit a reference than to
    guess a resource.
    """
    seen: set[tuple[str, str, str]] = set()
    out: list[Reference] = []
    for token, kind in candidates:
        resource = config.resources.resolve_with_context(
            normalize_identifier(token), context_resource,
        )
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
