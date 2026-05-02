"""Alias suggestion — deterministic core.

Scans a spec's component schemas for names that contain a token
already in the config's ``aliases_lookup`` and emits them as
candidate aliases for the matching resource. A deterministic
companion to ``schema_bindings``: Group D handles whole-name hits,
this module surfaces partial-hit schemas for the user (or an LLM
reviewer) to approve.

Rules for emitting a candidate:
1. The schema name must NOT already be bound by Group D.
2. The normalized form (snake_case), split on ``_``, must contain
   at least one token that hits ``aliases_lookup``.
3. The schema must be ``$ref``'d at least once somewhere in the
   spec — unused schemas aren't worth proposing.

Multiple tokens in one schema name can hit different resources.
Each hit produces its own ``Suggestion``, so the same schema may
appear under multiple target resources for downstream review.
"""

from __future__ import annotations

from collections import Counter
from dataclasses import dataclass
from typing import Any

from replica_pipeline.utils.text import normalize_identifier
from replica_pipeline.config import PipelineConfig
from replica_pipeline.extraction.schema_bindings import build_schema_bindings

_REF_PREFIX = "#/components/schemas/"


@dataclass(frozen=True)
class Suggestion:
    schema_name: str       # original form (e.g. "full-repository")
    normalized: str        # snake_case (e.g. "full_repository")
    matched_token: str     # the token that hit (e.g. "repository")
    target_resource: str   # canonical (e.g. "repos")
    ref_count: int         # total $ref occurrences in the spec


def suggest_aliases(
    spec: dict[str, Any],
    config: PipelineConfig,
) -> dict[str, list[Suggestion]]:
    """Return ``{resource_name: [suggestion, ...]}`` sorted by ref_count desc.

    Token resolution honors Path B: a token that hits a name_variant
    points at exactly one resource (strict). A token that hits a
    property_alias may point at multiple resources, and each gets its
    own ``Suggestion`` for the LLM to verdict independently. This
    matches the per-resource configure flow — the same candidate
    schema can legitimately be reviewed under multiple resources when
    its name tokens are contextual.
    """
    bindings = build_schema_bindings(spec, config)
    name_variants_lookup = config.resources.name_variants_lookup
    property_aliases_by_resource = config.resources.property_aliases_by_resource
    raw_schemas = (spec.get("components") or {}).get("schemas") or {}
    schemas: dict[str, Any] = raw_schemas if isinstance(raw_schemas, dict) else {}

    ref_counts: Counter[str] = Counter()
    _count_refs(spec, ref_counts)

    groups: dict[str, list[Suggestion]] = {}
    for name in schemas:
        if name in bindings:
            continue
        if ref_counts.get(name, 0) == 0:
            continue
        normalized = normalize_identifier(name)
        seen_resources: set[str] = set()
        for token in normalized.split("_"):
            # Name_variant hit — single owner, stop after recording.
            nv_owner = name_variants_lookup.get(token)
            if nv_owner is not None and nv_owner not in seen_resources:
                seen_resources.add(nv_owner)
                groups.setdefault(nv_owner, []).append(
                    Suggestion(
                        schema_name=name,
                        normalized=normalized,
                        matched_token=token,
                        target_resource=nv_owner,
                        ref_count=ref_counts[name],
                    )
                )
                continue
            # Property_alias hit — possibly multiple owners. Surface a
            # candidate under EACH so per-resource review can verdict
            # independently.
            for owner, aliases in property_aliases_by_resource.items():
                if token in aliases and owner not in seen_resources:
                    seen_resources.add(owner)
                    groups.setdefault(owner, []).append(
                        Suggestion(
                            schema_name=name,
                            normalized=normalized,
                            matched_token=token,
                            target_resource=owner,
                            ref_count=ref_counts[name],
                        )
                    )

    for resource in groups:
        groups[resource].sort(
            key=lambda suggestion: (-suggestion.ref_count, suggestion.schema_name)
        )
    return groups


def _count_refs(node: Any, counts: Counter[str]) -> None:
    """Walk ``node`` and increment the counter for every schema ``$ref``."""
    if isinstance(node, dict):
        for key, value in node.items():
            if key == "$ref" and isinstance(value, str) and value.startswith(_REF_PREFIX):
                counts[value[len(_REF_PREFIX):]] += 1
            else:
                _count_refs(value, counts)
    elif isinstance(node, list):
        for item in node:
            _count_refs(item, counts)


def format_suggestions_yaml(
    suggestions: dict[str, list[Suggestion]],
) -> str:
    """Emit a yaml snippet the user can review and merge into their config."""
    lines = [
        "# Proposed alias additions (raw suggestions, no LLM review).",
        "# Review each entry and delete the ones you don't want, then",
        "# merge into your config.",
        "",
        "resources:",
    ]
    for resource in sorted(suggestions.keys()):
        lines.append(f"  {resource}:")
        lines.append("    aliases:")
        for suggestion in suggestions[resource]:
            lines.append(
                f"      - {suggestion.normalized}"
                f"  # {suggestion.ref_count} refs, token={suggestion.matched_token}"
            )
    return "\n".join(lines) + "\n"
