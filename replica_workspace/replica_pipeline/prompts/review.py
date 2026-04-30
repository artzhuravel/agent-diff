"""Prompt construction for the alias-suggestion review step.

The ``suggest_aliases`` runner finds candidate schema names; this
prompt asks the LLM to classify each candidate as a variant of the
declared resource, a distinct concept, or uncertain.
"""

from __future__ import annotations

import json
from collections.abc import Mapping
from typing import Any

from replica_pipeline.aliases.suggest import Suggestion
from replica_pipeline.config import PipelineConfig


def build_review_prompt(
    resource: str,
    config: PipelineConfig,
    suggestions: list[Suggestion],
    component_schemas: Mapping[str, Any],
) -> str:
    """Render the per-resource review prompt for the LLM.

    Lists existing aliases + the candidate schemas (with their bodies,
    truncated at 2000 chars) and asks the LLM to verdict each as
    ``variant`` / ``distinct`` / ``uncertain``.
    """
    existing = sorted(config.resources.aliases_by_resource.get(resource, frozenset()))
    lines = [
        f'You are reviewing proposed schema aliases for the "{resource}" resource.',
        "",
        f"The full OpenAPI spec is available at: `{config.openapi_path}`",
        "If any schema body below is truncated or unclear, read the spec directly.",
        "",
        f"Existing aliases for {resource}:",
    ]
    for alias in existing:
        lines.append(f"  - {alias}")
    lines.append("")
    lines.append("Candidate aliases to review:")
    lines.append("")
    for index, suggestion in enumerate(suggestions, start=1):
        body = component_schemas.get(suggestion.schema_name)
        body_json = json.dumps(body, indent=2) if body is not None else "<missing>"
        if len(body_json) > 2000:
            body_json = body_json[:2000] + "\n... (truncated)"
        lines.append(f"{index}. schema_name: {suggestion.schema_name}")
        lines.append(f"   ref_count: {suggestion.ref_count}")
        lines.append(f"   matched_token: {suggestion.matched_token}")
        lines.append(f"   schema_body: {body_json}")
        lines.append("")
    lines.append(
        f'For each candidate, decide: is this schema a VARIANT of "{resource}" '
        "(same underlying entity, possibly with more or fewer fields, or a "
        "partial view), or a DISTINCT concept that happens to share a word?"
    )
    lines.append("")
    lines.append("Mark as DISTINCT (not variant):")
    lines.append("- Webhook event payloads (e.g. webhook-team-created, webhook-pull-request-assigned)")
    lines.append("  — these wrap the entity in an event envelope, they are not the entity itself")
    lines.append("- Primitive type schemas that hold a single value like a SHA, ID, or OID")
    lines.append("  — these are field types, not entity variants")
    lines.append("- Configuration, policy, or settings schemas that apply to the entity")
    lines.append("  — these describe rules about the entity, not the entity itself")
    lines.append("- Enum or status value schemas (e.g. ProjectStatus, ProjectVisibility)")
    lines.append("")
    lines.append("Mark as VARIANT only if the schema represents the same underlying entity")
    lines.append("with a different set of fields (compact view, full view, search result, etc.)")
    lines.append("")
    lines.append("Respond in JSON (no markdown fences):")
    lines.append(
        '[{"schema_name": "...", "verdict": "variant" | "distinct" | "uncertain", "reason": "brief one-line explanation"}, ...]'
    )
    return "\n".join(lines)
