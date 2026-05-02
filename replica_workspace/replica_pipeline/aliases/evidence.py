"""Per-resource evidence gathering for the ``configure`` stage.

The configure stage now runs one LLM call per resource. Each call is
fed a ``ResourceEvidence`` block carrying the spec slice relevant to
that resource — bound schemas, candidate schemas, URL paths, and the
cross-resource collision flags that downstream prompts surface as
counter-evidence (Defense 1 of the collision strategy).

The matching merge-time defense (Defense 3) lives in
``aliases/configure.py`` and operates on the *outputs* of the per-
resource LLM calls.

Two design choices worth flagging:

* Match tokens are ``canonical + singular + plural`` only — NOT the
  resource's existing aliases. Reusing existing aliases would propagate
  any over-aliasing from previous configure runs into the matching
  step, producing artificial cross-resource collisions that don't
  reflect the spec. Anchoring on canonical names gives a clean,
  predictable baseline regardless of how messy the current ``app.yaml``
  is.
* Single-word tokens use snake_case word-boundary matching; multi-word
  canonicals (e.g. ``task_templates``) fall back to substring match on
  the joined name. This catches ``TaskTemplateRecipe`` for
  ``task_templates`` without false-matching ``tasking_metadata`` for
  ``tasks``.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any

from replica_pipeline.config import PipelineConfig
from replica_pipeline.utils.text import canonical_forms, normalize_identifier


_HTTP_METHODS = ("get", "post", "put", "patch", "delete")
_BODY_TRUNCATE_CHARS = 2000

# Substrings that mark a schema name as an operation-specific request/
# response shape rather than a variant of the entity itself. Matched
# against the normalized (snake_case) name with surrounding underscores
# so partial-word collisions (e.g. ``modify`` inside ``modifier``) don't
# fire. The list is conservative — anything that's a recognizable
# imperative verb in REST-style action paths qualifies.
_OPERATION_VERB_TOKENS = (
    "_add_", "_remove_", "_set_", "_unset_", "_modify_", "_change_",
    "_update_", "_duplicate_", "_instantiate_", "_save_as_", "_count_",
    "_search_", "_insert_", "_addtask_", "_removetask_", "_addtags_",
    "_addfollowers_", "_removefollowers_",
)
_REF_PREFIX = "#/components/schemas/"
# Property names so generic that a $ref-pointing-at-resource match is
# noise rather than signal — they don't function as role words.
_GENERIC_FIELD_NAMES = frozenset({
    "data", "value", "items", "result", "results", "object", "entity",
    "id", "gid", "type", "kind",
})
# Cap on role-word candidates surfaced per resource — prevents prompt
# bloat when a spec has many cross-typed fields.
_ROLE_WORD_CAP = 30


@dataclass(frozen=True)
class CandidateSchema:
    """A schema name that token-matches the resource but isn't a direct hit.

    Bound schemas (whose normalized name *equals* one of the resource's
    match tokens) are kept separately — those don't need LLM verdicts.
    Candidates do, and ``also_matches`` carries the cross-resource
    collision context the prompt uses as Defense 1.

    ``looks_like_operation`` flags candidates whose name pattern matches
    an action-specific request/response shape (e.g.
    ``TaskAddFollowersRequest``). The prompt surfaces this as
    counter-evidence so the LLM marks them ``distinct`` rather than
    pulling them into ``name_variants`` — the previous run's biggest
    name_variants pollution was exactly this class of schema.
    """
    name: str
    normalized: str
    body_json: str
    matched_tokens: tuple[str, ...]
    # ``also_matches`` is sorted by other-resource name. Each entry is
    # ``(other_resource_canonical, tuple_of_tokens_that_matched)`` so the
    # prompt can quote which token caused the cross-match.
    also_matches: tuple[tuple[str, tuple[str, ...]], ...]
    looks_like_operation: bool


@dataclass(frozen=True)
class RoleWordCandidate:
    """A field name that points at this resource from other schemas.

    Computed by walking every schema's properties (recursing through
    ``allOf`` / ``oneOf`` / ``anyOf``) and recording each property whose
    value $refs into a schema bound to this resource. Strong signal that
    the field name is a property_alias for the resource — a User-typed
    ``assignee`` field on TaskBase is exactly the evidence the per-
    resource configure prompt was missing. ``occurrences`` lists the
    distinct ``(source_resource, source_schema)`` pairs where the field
    appears, so the prompt can show the LLM the spread.
    """
    field_name: str
    occurrences: tuple[tuple[str, str], ...]


@dataclass(frozen=True)
class ResourceEvidence:
    """Everything the configure prompt needs to verdict one resource."""
    resource_name: str
    primary_key: str
    existing_name_variants: tuple[str, ...]
    existing_property_aliases: tuple[str, ...]
    # ``bound_schemas`` holds (schema_name, json_body) for schemas whose
    # normalized name directly matches a resource token. These are
    # informational — the LLM doesn't re-verdict them.
    bound_schemas: tuple[tuple[str, str], ...]
    candidates: tuple[CandidateSchema, ...]
    # Cross-talk evidence: field names in OTHER resources' schemas whose
    # value $refs into this resource's bound schemas. Sorted by
    # occurrence count descending, capped at ``_ROLE_WORD_CAP``.
    role_word_candidates: tuple[RoleWordCandidate, ...]
    # ``url_paths`` is a sorted list of ``(method, path)`` tuples for
    # paths whose segments contain at least one resource token. Helps
    # the LLM ground its verdicts in actual API surface.
    url_paths: tuple[tuple[str, str], ...]


def gather_all_evidence(
    spec: dict[str, Any],
    config: PipelineConfig,
) -> dict[str, ResourceEvidence]:
    """Three-pass evidence gathering for every declared resource.

    Pass 1 builds a global ``schema_name → {resource: matched_tokens}``
    map so each resource's ``CandidateSchema`` knows which other
    resources also match the same schema. Pass 2 walks every schema's
    properties to surface **role-word candidates** — field names in
    other resources' schemas whose value $refs at this resource. Pass 3
    walks the spec per-resource to assemble per-resource evidence using
    the maps from passes 1 and 2.

    Returns a dict keyed by canonical resource name; the caller
    typically iterates resources in sorted order to keep prompt names
    deterministic.
    """
    resource_names = sorted(config.resources.aliases_by_resource.keys())
    resource_tokens: dict[str, set[str]] = {
        resource: canonical_forms(resource) for resource in resource_names
    }

    schemas = (spec.get("components") or {}).get("schemas") or {}
    if not isinstance(schemas, dict):
        schemas = {}

    # Pass 1: schema → {resource: matched_tokens}.
    schema_matches: dict[str, dict[str, tuple[str, ...]]] = {}
    for schema_name in schemas:
        normalized = normalize_identifier(schema_name)
        for resource, tokens in resource_tokens.items():
            hits = _matches_resource(normalized, tokens)
            if hits:
                schema_matches.setdefault(schema_name, {})[resource] = hits

    # Pass 2: cross-talk role-word evidence. For each resource R, collect
    # field names from OTHER resources' schemas whose value $refs into a
    # schema bound to R. The previous run's biggest gap was missing role
    # words for ``users`` (no ``assignee``, ``owner``, etc.) because each
    # per-resource prompt only saw its own token-matching schemas — this
    # pass closes that gap by surfacing typed cross-resource references.
    role_word_candidates_by_resource = _gather_role_word_candidates(
        schemas, schema_matches,
    )

    # Pass 3: per-resource evidence.
    evidence_by_resource: dict[str, ResourceEvidence] = {}
    for resource in resource_names:
        bound: list[tuple[str, str]] = []
        candidates: list[CandidateSchema] = []
        my_tokens = resource_tokens[resource]

        for schema_name, body in schemas.items():
            matches = schema_matches.get(schema_name) or {}
            if resource not in matches:
                continue
            normalized = normalize_identifier(schema_name)
            body_json = json.dumps(body, indent=2) if body is not None else "{}"
            if len(body_json) > _BODY_TRUNCATE_CHARS:
                body_json = body_json[:_BODY_TRUNCATE_CHARS] + "\n... (truncated)"

            if normalized in my_tokens:
                # Direct name hit — no LLM verdict needed.
                bound.append((schema_name, body_json))
                continue

            also_matches = tuple(
                sorted(
                    (
                        (other_resource, other_hits)
                        for other_resource, other_hits in matches.items()
                        if other_resource != resource
                    ),
                    key=lambda entry: entry[0],
                )
            )
            candidates.append(
                CandidateSchema(
                    name=schema_name,
                    normalized=normalized,
                    body_json=body_json,
                    matched_tokens=matches[resource],
                    also_matches=also_matches,
                    looks_like_operation=_looks_like_operation_schema(normalized),
                )
            )

        candidates.sort(key=lambda candidate: candidate.name)

        # URL paths whose segments contain a resource token. We list
        # both fixed and parameterized paths because the LLM uses them
        # to spot CRUD shape (e.g. ``/users`` + ``/users/{user_id}``).
        url_paths: list[tuple[str, str]] = []
        for path, path_item in (spec.get("paths") or {}).items():
            if not isinstance(path_item, dict):
                continue
            normalized_segments = {
                normalize_identifier(segment.strip("{}"))
                for segment in path.split("/")
                if segment
            }
            if not (normalized_segments & my_tokens):
                # When the resource's canonical token is multi-word,
                # also try a substring fallback against each segment so
                # ``/task_templates/...`` is captured for ``task_templates``.
                if not any(
                    "_" in token and any(token in seg for seg in normalized_segments)
                    for token in my_tokens
                ):
                    continue
            for method in _HTTP_METHODS:
                operation = path_item.get(method)
                if isinstance(operation, dict):
                    url_paths.append((method.upper(), path))
        url_paths.sort(key=lambda entry: (entry[1], entry[0]))

        existing_nvs = tuple(
            sorted(config.resources.name_variants_by_resource.get(resource, frozenset()))
        )
        existing_props = tuple(
            sorted(config.resources.property_aliases_by_resource.get(resource, frozenset()))
        )

        primary_key = config.resources.primary_keys_lookup.get(resource, "id")

        role_word_candidates = tuple(
            role_word_candidates_by_resource.get(resource, ())[:_ROLE_WORD_CAP]
        )

        evidence_by_resource[resource] = ResourceEvidence(
            resource_name=resource,
            primary_key=primary_key,
            existing_name_variants=existing_nvs,
            existing_property_aliases=existing_props,
            bound_schemas=tuple(bound),
            candidates=tuple(candidates),
            role_word_candidates=role_word_candidates,
            url_paths=tuple(url_paths),
        )

    return evidence_by_resource


def _matches_resource(
    schema_normalized: str,
    resource_tokens: set[str],
) -> tuple[str, ...]:
    """Tokens from ``resource_tokens`` that hit in the schema's normalized name.

    Single-word tokens use snake_case word-boundary matching to avoid
    spurious hits like ``task`` inside ``tasking_metadata``. Multi-word
    tokens (``task_templates``, ``pull_requests``) fall back to
    substring matching since their parts span underscores.
    """
    schema_word_set = set(schema_normalized.split("_"))
    hits: list[str] = []
    for token in resource_tokens:
        if "_" in token:
            if token in schema_normalized:
                hits.append(token)
        else:
            if token in schema_word_set:
                hits.append(token)
    return tuple(sorted(hits))


def _looks_like_operation_schema(normalized: str) -> bool:
    """True for schema names that look like an operation request/response.

    The pattern ``*_<verb>_*_request`` / ``*_<verb>_*_response`` is the
    common shape across REST specs for action-style endpoint bodies
    (``addFollowers``, ``duplicate``, ``setParent``, etc.). Schemas with
    this pattern are almost never variants of the entity itself —
    they're per-operation parameter shapes that just happen to share a
    token with the entity name. Surfacing this in the prompt as
    counter-evidence keeps them out of ``name_variants``.
    """
    if not (normalized.endswith("_request") or normalized.endswith("_response")):
        return False
    # Wrap in underscores so we can substring-match verb tokens unambiguously.
    padded = f"_{normalized}_"
    return any(verb in padded for verb in _OPERATION_VERB_TOKENS)


def _gather_role_word_candidates(
    schemas: dict[str, Any],
    schema_matches: dict[str, dict[str, tuple[str, ...]]],
) -> dict[str, list[RoleWordCandidate]]:
    """For each resource R, find field names in OTHER resources' schemas
    whose values $ref into a schema bound to R.

    This is the cross-talk pass. Without it, a per-resource configure
    prompt for ``users`` only sees user-token-matching schemas — the
    fact that ``task.assignee: $ref UserCompact`` exists in TaskBase is
    invisible. With it, the users prompt gets a "Role-word candidates"
    section enumerating ``assignee``, ``owner``, ``follower``, etc.,
    each annotated with where the field appears.
    """
    # field_name → target_resource → list of (source_resource, source_schema)
    accumulator: dict[str, dict[str, list[tuple[str, str]]]] = {}

    for source_schema_name, source_schema in schemas.items():
        source_resources = set(schema_matches.get(source_schema_name, {}).keys())
        if not source_resources:
            continue
        for field_name, field_schema in _walk_schema_properties(source_schema):
            if field_name in _GENERIC_FIELD_NAMES:
                continue
            target_schema_name = _extract_ref_target(field_schema)
            if not target_schema_name:
                continue
            target_resources = set(schema_matches.get(target_schema_name, {}).keys())
            for target_resource in target_resources:
                if target_resource in source_resources:
                    # Self-reference (e.g. tasks's parent → tasks). The
                    # cross-talk is meant to surface foreign references,
                    # so skip same-resource hits.
                    continue
                # Pick one source resource for the occurrence — when a
                # source schema matches multiple resources, the first
                # alphabetically wins. Avoids over-counting.
                source_resource = sorted(source_resources)[0]
                accumulator.setdefault(field_name, {}).setdefault(target_resource, []).append(
                    (source_resource, source_schema_name)
                )

    by_target: dict[str, list[RoleWordCandidate]] = {}
    for field_name, by_target_inner in accumulator.items():
        for target_resource, occurrences in by_target_inner.items():
            unique_occurrences = tuple(sorted(set(occurrences)))
            by_target.setdefault(target_resource, []).append(
                RoleWordCandidate(field_name=field_name, occurrences=unique_occurrences)
            )

    for target in by_target:
        # Sort by occurrence count desc (frequent fields first), then
        # alphabetically for stability across runs.
        by_target[target].sort(
            key=lambda candidate: (-len(candidate.occurrences), candidate.field_name),
        )
    return by_target


def _walk_schema_properties(
    schema: Any,
) -> Any:
    """Yield ``(field_name, field_schema)`` for every property in ``schema``.

    Walks ``properties`` directly and recurses into ``allOf`` / ``oneOf``
    / ``anyOf`` branches so composition-style schemas (very common in
    Asana's spec) are covered. Does NOT follow ``$ref`` — the caller
    handles that explicitly via ``_extract_ref_target``. Generator-style
    so callers can enumerate large schemas without materializing a list.
    """
    if not isinstance(schema, dict):
        return
    properties = schema.get("properties")
    if isinstance(properties, dict):
        for field_name, field_schema in properties.items():
            if isinstance(field_name, str):
                yield field_name, field_schema
    for key in ("allOf", "oneOf", "anyOf"):
        for branch in schema.get(key) or []:
            yield from _walk_schema_properties(branch)


def _extract_ref_target(field_schema: Any) -> str | None:
    """Extract the schema name a property points at via ``$ref``.

    Looks past one layer of ``allOf`` / ``oneOf`` / ``anyOf`` and into
    array ``items`` so ``[{"$ref": ...}]`` and ``allOf: [{"$ref": ...}]``
    forms are both recognized. Returns ``None`` for properties that
    aren't typed as a $ref to a component schema.
    """
    if not isinstance(field_schema, dict):
        return None
    ref = field_schema.get("$ref")
    if isinstance(ref, str) and ref.startswith(_REF_PREFIX):
        return ref[len(_REF_PREFIX):]
    for key in ("allOf", "oneOf", "anyOf"):
        for branch in field_schema.get(key) or []:
            target = _extract_ref_target(branch)
            if target:
                return target
    items = field_schema.get("items")
    if isinstance(items, dict):
        return _extract_ref_target(items)
    return None
