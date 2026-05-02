"""Prompt construction for the ``configure`` stage.

The configure stage now runs one LLM call per resource, each with a
focused evidence brief assembled by ``aliases/evidence.py``. The
prompts ask the LLM to verdict candidate schemas as either name
variants of THIS resource, role/property aliases of THIS resource, or
distinct concepts. Cross-resource collision flags (Defense 1 of the
collision strategy) are surfaced inline as counter-evidence so the
LLM defaults to ``distinct`` when ambiguity is real.
"""

from __future__ import annotations

from replica_pipeline.aliases.evidence import ResourceEvidence
from replica_pipeline.utils.text import canonical_forms


def build_configure_prompt(evidence: ResourceEvidence, app_name: str) -> str:
    """Render the per-resource configure prompt as a single string.

    The prompt is structured as: header → existing setup → bound
    schemas (informational, no verdict needed) → candidate schemas
    (each with cross-resource flags) → URL paths → output contract.
    The LLM produces a YAML block scoped to this one resource.
    """
    resource = evidence.resource_name
    lines: list[str] = []
    lines.append(
        f"You are configuring aliases for the `{resource}` resource of the "
        f"{app_name} API replica."
    )
    lines.append("")
    lines.append(
        "This is one of several per-resource configure prompts the pipeline "
        "runs. Each asks you to decide which schema names alias to a single "
        "resource. **Be conservative** — over-aliasing causes silent "
        "mis-attribution of endpoints downstream."
    )
    lines.append("")
    lines.append("---")
    lines.append("")
    lines.append("# Existing setup")
    lines.append(f"- Canonical name: `{resource}`")
    lines.append(f"- Primary key: `{evidence.primary_key}`")
    if evidence.existing_name_variants:
        lines.append("- Already-declared `name_variants`:")
        for alias in evidence.existing_name_variants:
            lines.append(f"  - `{alias}`")
    else:
        lines.append("- Already-declared `name_variants`: (none)")
    if evidence.existing_property_aliases:
        lines.append("- Already-declared `property_aliases`:")
        for alias in evidence.existing_property_aliases:
            lines.append(f"  - `{alias}`")
    else:
        lines.append("- Already-declared `property_aliases`: (none)")
    lines.append("")

    lines.append("---")
    lines.append("")
    lines.append("# Bound schemas")
    lines.append("")
    if evidence.bound_schemas:
        lines.append(
            f"These schemas already directly name `{resource}` (their "
            f"normalized name matches a resource token). They are part of "
            f"`{resource}` and you do NOT need to verdict them — they are "
            f"shown so you understand the entity's shape and can use that "
            f"shape when verdicting candidates below."
        )
        lines.append("")
        for name, body_json in evidence.bound_schemas:
            lines.append(f"## `{name}`")
            lines.append("```json")
            lines.append(body_json)
            lines.append("```")
            lines.append("")
    else:
        lines.append(
            f"_(No schema in the spec directly matches `{resource}` by name. "
            f"The candidates below are your only structural evidence.)_"
        )
        lines.append("")

    lines.append("---")
    lines.append("")
    lines.append("# Candidate schemas")
    lines.append("")
    if evidence.candidates:
        lines.append(
            f"These schemas mention a `{resource}` token in their name but "
            f"are not direct hits. For each, decide whether it's a "
            f"**name_variant** of `{resource}` (same entity, different "
            f"projection), a **property_alias** (a role-word field whose "
            f"VALUE is `{resource}`), or **distinct** (a different concept "
            f"or a different resource entirely)."
        )
        lines.append("")
        lines.append("Two flags appear inline below as counter-evidence:")
        lines.append("")
        lines.append(
            "* **CROSS-RESOURCE FLAG** — this candidate also matches another "
            "declared resource. Default to `distinct` unless you can "
            f"specifically justify the candidate as a variant of `{resource}` "
            "and not the other resource — the pipeline detects collisions "
            "when both resources claim the same alias and rejects the merge."
        )
        lines.append(
            "* **OPERATION-SCHEMA FLAG** — this candidate's name pattern "
            "matches an action-style request/response shape (e.g. "
            "`*_add_*_request`, `*_count_response`, `*_duplicate_request`). "
            "These describe the parameters of a single operation, not the "
            "entity itself, and almost always belong as `distinct`. Mark as "
            "`name_variant` only if the schema's field set is structurally a "
            f"`{resource}` projection — usually it isn't."
        )
        lines.append("")
        for index, candidate in enumerate(evidence.candidates, start=1):
            lines.append(f"## {index}. `{candidate.name}`")
            lines.append(f"- normalized: `{candidate.normalized}`")
            lines.append(
                f"- matched tokens: `{', '.join(candidate.matched_tokens)}`"
            )
            if candidate.also_matches:
                flag_parts = [
                    f"`{other}` (via tokens: {', '.join(f'`{t}`' for t in tokens)})"
                    for other, tokens in candidate.also_matches
                ]
                lines.append(
                    "- **CROSS-RESOURCE FLAG** — this candidate also matches: "
                    + "; ".join(flag_parts)
                )
            if candidate.looks_like_operation:
                lines.append(
                    "- **OPERATION-SCHEMA FLAG** — name pattern matches an "
                    "action-specific request/response shape; default to "
                    "`distinct` unless its fields are structurally a "
                    f"`{resource}` projection."
                )
            if not candidate.also_matches and not candidate.looks_like_operation:
                lines.append("- flags: none (clean hit)")
            lines.append("- schema body:")
            lines.append("```json")
            lines.append(candidate.body_json)
            lines.append("```")
            lines.append("")
    else:
        lines.append(
            f"_(No candidate schemas matched `{resource}` tokens. Output "
            f"only the canonical name and its singular/plural in "
            f"`name_variants`.)_"
        )
        lines.append("")

    lines.append("---")
    lines.append("")
    lines.append("# Role-word candidates")
    lines.append("")
    if evidence.role_word_candidates:
        lines.append(
            f"These field names appear in OTHER resources' schemas with values "
            f"$ref'ing into `{resource}`-bound schemas. They are strong "
            f"candidates for `{resource}.property_aliases` — the spec uses "
            f"these names as fields whose VALUE is a `{resource}` reference. "
            f"Add the field names below to `property_aliases` unless you can "
            f"justify a different interpretation from the cited evidence."
        )
        lines.append("")
        for candidate in evidence.role_word_candidates:
            occurrence_strs = [
                f"`{source_res}.{source_schema}`"
                for source_res, source_schema in candidate.occurrences[:5]
            ]
            extra = (
                f" (+{len(candidate.occurrences) - 5} more)"
                if len(candidate.occurrences) > 5 else ""
            )
            lines.append(
                f"- `{candidate.field_name}` — appears in: "
                + ", ".join(occurrence_strs) + extra
            )
        lines.append("")
    else:
        lines.append(
            f"_(No cross-resource role-word evidence found for `{resource}`. "
            f"Properties of other resources don't $ref into `{resource}`-"
            f"bound schemas.)_"
        )
        lines.append("")

    lines.append("---")
    lines.append("")
    lines.append("# URL paths mentioning this resource")
    lines.append("")
    if evidence.url_paths:
        lines.append(
            f"Paths whose segments contain a `{resource}` token. Use these "
            f"to spot CRUD shape — a token with both `/<token>` and "
            f"`/<token>/{{...}}` paths typically owns its own URL family "
            f"and should be its own resource, not aliased into `{resource}`."
        )
        lines.append("")
        for method, path in evidence.url_paths:
            lines.append(f"- `{method} {path}`")
        lines.append("")
    else:
        lines.append(
            f"_(No paths in the spec contain `{resource}` tokens. The "
            f"resource may be addressed only via parent paths.)_"
        )
        lines.append("")

    lines.append("---")
    lines.append("")
    lines.append("# Output")
    lines.append("")
    lines.append("Required behavior:")
    lines.append("")
    # The "entity-name-wins" rule deserves its own paragraph because
    # the previous run misclassified the singular form as a
    # property_alias even when the YAML example showed it under
    # name_variants. Calling out the *reason* (entity-name vs role-word
    # interpretation precedence) makes the rule applicable, not just
    # memorized.
    forms = canonical_forms(resource)
    canonical_singular = next(
        (form for form in forms if not form.endswith("s") or form.endswith("ss")),
        resource,
    )
    canonical_plural = next(
        (form for form in forms if form.endswith("s") and not form.endswith("ss")),
        resource,
    )
    lines.append(
        f"1. **The singular and plural canonical forms MUST be in "
        f"`name_variants`.** For this resource that means `{canonical_singular}` "
        f"AND `{canonical_plural}` both belong in `name_variants` — they are "
        f"already listed under \"Existing setup\" above. **Do not move them "
        f"to `property_aliases`** even if the same word also appears as a "
        f"field name elsewhere in the spec (e.g. `project_membership.{canonical_singular}`). "
        f"The entity-name interpretation always wins over the role-word "
        f"interpretation when there's overlap: `{canonical_singular}` IS the "
        f"name of the entity, so it goes in `name_variants` first; its use "
        f"as a field name is a separate fact that doesn't override that. "
        f"The runner will auto-correct misclassification, but get it right "
        f"in the response — silent corrections are noisier in audit logs."
    )
    lines.append(
        "2. **Every field name listed under `Role-word candidates` above "
        "should appear in `property_aliases`** unless you can name a "
        "specific reason it doesn't apply. The cited evidence (typed "
        "$refs from other schemas) is the spec's own classification."
    )
    lines.append(
        "3. **Operation-flagged candidates default to `distinct`.** Only "
        "promote one to `name_variants` if its body is structurally an "
        "entity projection — most carry only operation parameters."
    )
    lines.append(
        "4. **Cross-resource-flagged candidates default to `distinct`.** "
        "Promote only with specific justification; the merge step will "
        "reject ambiguous claims."
    )
    lines.append("")
    lines.append(
        "Respond ONLY with a YAML block (no markdown fences, no prose) "
        f"scoped to `{resource}`:"
    )
    lines.append("")
    lines.append(f"{resource}:")
    lines.append(f"  primary_key: {evidence.primary_key}")
    lines.append("  name_variants:")
    lines.append("    - <singular>")
    lines.append("    - <plural>")
    lines.append("    - <other-name-variants>")
    lines.append("  property_aliases:")
    lines.append("    - <role-word>")
    lines.append("    - <role-word>")
    lines.append("")
    lines.append(
        "Include `self_id_fields:` only if the resource has multiple "
        "identity fields (e.g. `id` + `node_id`). Use empty list "
        "(`property_aliases: []`) if there are no role words."
    )
    return "\n".join(lines)
