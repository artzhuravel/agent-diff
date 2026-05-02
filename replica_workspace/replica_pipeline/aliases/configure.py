"""Auto-configure stage — per-resource LLM calls + collision-aware merge.

Splits cleanly from ``pipeline.config``: that module loads and validates
``app.yaml``. This one is the ``configure`` stage runner — it gathers
per-resource evidence, prompts the LLM once per resource (saving each
prompt to ``prompts/configure_<resource>.md``), parses the responses,
runs the cross-resource collision check (Defense 3), and writes the
result back into ``app.yaml``.

The per-resource design is the architectural piece that bounds LLM
context to one resource at a time and parallelizes naturally. The two
defenses against alias collisions across resources are:

* **Defense 1 — pre-emptive in-prompt counter-evidence.** Each
  candidate schema that also token-matches another declared resource
  is flagged in the prompt; the LLM is instructed to default to
  ``distinct`` when ambiguity is real. Lives in ``aliases/evidence.py``
  and ``prompts/configure.py``.
* **Defense 3 — loud merge-time error.** If two resources' responses
  both claim the same alias after Defense 1, this module rejects the
  merge and reports both resources' verdicts so the user can resolve.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

import yaml

from replica_pipeline.aliases.evidence import gather_all_evidence
from replica_pipeline.config import load_config
from replica_pipeline.prompts.configure import build_configure_prompt
from replica_pipeline.utils.llm import make_llm_call
from replica_pipeline.utils.text import canonical_forms


@dataclass(frozen=True)
class ResourceVerdict:
    """A single resource's parsed LLM response."""
    resource: str
    name_variants: list[str]
    property_aliases: list[str]
    primary_key: str | None
    self_id_fields: list[str]


def run_configure(ctx) -> None:
    """``configure`` stage — one LLM call per resource, collision-checked merge."""
    print("\n=== CONFIGURE — per-resource LLM passes populate aliases and PKs ===")
    config = load_config(ctx.config_path)
    spec = config.load_spec()

    resource_names = ctx.only_resources or sorted(
        config.resources.aliases_by_resource.keys()
    )
    if not resource_names:
        print("  [skip] no resources to configure")
        return

    evidence_by_resource = gather_all_evidence(spec, config)
    ctx.prompt_dir.mkdir(parents=True, exist_ok=True)

    # Build + save every per-resource prompt up-front so dry-runs and
    # real runs leave the same audit trail. Skipping (--only-resources)
    # is honored when dispatching the LLM, but the saved prompts are
    # generated for whichever resources the run targets.
    prompts: dict[str, str] = {}
    for resource in resource_names:
        evidence = evidence_by_resource.get(resource)
        if evidence is None:
            print(f"  [warn] no evidence gathered for {resource} — skipping")
            continue
        prompt = build_configure_prompt(evidence, app_name=config.app_name)
        prompts[resource] = prompt
        (ctx.prompt_dir / f"configure_{resource}.md").write_text(prompt)

    if ctx.dry_run:
        print(
            f"  [dry-run] Saved {len(prompts)} per-resource prompts to "
            f"{ctx.prompt_dir}; skipping LLM"
        )
        return

    llm_call = make_llm_call(model=ctx.configure_model)
    verdicts: dict[str, ResourceVerdict] = {}
    for resource, prompt in prompts.items():
        print(f"  Calling {ctx.configure_model} for {resource}...")
        response = llm_call(prompt)
        verdict = _parse_resource_response(response, resource)
        if verdict is None:
            print(f"  [warn] could not parse response for {resource} — skipping")
            continue
        verdicts[resource] = verdict

    if not verdicts:
        print("  [warn] no resources produced parseable verdicts; app.yaml unchanged")
        return

    # Defense 3 — cross-resource collision detection. We check the
    # union (name_variants ∪ property_aliases) per resource because a
    # single alias colliding across either tier breaks the loader.
    _check_collisions(verdicts)

    _merge_into_yaml(ctx.config_path, verdicts)
    print(f"  Configured {len(verdicts)} resources via {ctx.configure_model}")


def _parse_resource_response(response: str, resource: str) -> ResourceVerdict | None:
    """Parse the LLM YAML response for a single resource.

    Accepts the new two-tier shape (``name_variants`` +
    ``property_aliases``) and the legacy single-bag shape
    (``aliases``). Legacy bags are taken as ``name_variants`` —
    the URL-subject-eligible default that mirrors pre-#3 behavior.
    """
    text = response.strip()
    if text.startswith("```"):
        text = text.split("\n", 1)[1] if "\n" in text else text
    if text.endswith("```"):
        text = text.rsplit("```", 1)[0]

    try:
        parsed = yaml.safe_load(text)
    except yaml.YAMLError:
        return None
    if not isinstance(parsed, dict):
        return None
    entry = parsed.get(resource)
    if not isinstance(entry, dict):
        return None

    name_variants_raw = entry.get("name_variants")
    property_aliases_raw = entry.get("property_aliases")
    legacy_aliases_raw = entry.get("aliases")

    name_variants: list[str] = []
    property_aliases: list[str] = []

    if isinstance(name_variants_raw, list):
        name_variants = [str(alias) for alias in name_variants_raw if isinstance(alias, str)]
    if isinstance(property_aliases_raw, list):
        property_aliases = [
            str(alias) for alias in property_aliases_raw if isinstance(alias, str)
        ]
    if (
        isinstance(legacy_aliases_raw, list)
        and not name_variants
        and not property_aliases
    ):
        name_variants = [
            str(alias) for alias in legacy_aliases_raw if isinstance(alias, str)
        ]

    if not name_variants and not property_aliases:
        return None

    primary_key = entry.get("primary_key")
    primary_key = primary_key if isinstance(primary_key, str) and primary_key else None

    self_id_fields_raw = entry.get("self_id_fields")
    self_id_fields = (
        [str(field) for field in self_id_fields_raw if isinstance(field, str)]
        if isinstance(self_id_fields_raw, list)
        else []
    )

    return ResourceVerdict(
        resource=resource,
        name_variants=name_variants,
        property_aliases=property_aliases,
        primary_key=primary_key,
        self_id_fields=self_id_fields,
    )


def _check_collisions(verdicts: dict[str, ResourceVerdict]) -> None:
    """Defense 3 — tier-aware collision detection across resources.

    Two failure modes are still fatal under Path B:

    * **name_variants collision** — same alias claimed as a name_variant
      by two or more resources. Name_variants are global entity-name
      claims and must be unique; otherwise URL-subject inference is
      non-deterministic.
    * **mixed-tier collision** — alias is a name_variant of A and a
      property_alias of B (any A != B). A name_variant is a strict
      claim that the alias *names* an entity; another resource cannot
      simultaneously claim the same alias as a property-level
      reference.

    A property_alias-only overlap (same alias claimed as
    ``property_aliases`` by two or more resources, with no name_variant
    claim) is **legitimate** under Path B — the same field name can
    refer to different resources in different schemas, resolved at
    walk time via the schema's binding context. We surface this as an
    informational message so the user knows it happened, but do not
    error.
    """
    name_variant_claims: dict[str, set[str]] = {}
    property_alias_claims: dict[str, set[str]] = {}
    for resource, verdict in verdicts.items():
        for alias in verdict.name_variants:
            name_variant_claims.setdefault(alias, set()).add(resource)
        for alias in verdict.property_aliases:
            property_alias_claims.setdefault(alias, set()).add(resource)

    fatal_lines: list[str] = []

    # Same alias as name_variant in 2+ resources.
    for alias in sorted(name_variant_claims):
        owners = name_variant_claims[alias]
        if len(owners) > 1:
            fatal_lines.append(f"  - {alias!r} claimed as name_variant by:")
            for resource in sorted(owners):
                fatal_lines.append(f"      - {resource}")

    # Mixed-tier: name_variant of A, property_alias of B (different).
    for alias in sorted(set(name_variant_claims) | set(property_alias_claims)):
        nv_owners = name_variant_claims.get(alias, set())
        pa_owners = property_alias_claims.get(alias, set())
        cross_owners = pa_owners - nv_owners
        if nv_owners and cross_owners:
            fatal_lines.append(f"  - {alias!r} mixed-tier collision:")
            for resource in sorted(nv_owners):
                fatal_lines.append(f"      - {resource} (name_variants)")
            for resource in sorted(cross_owners):
                fatal_lines.append(f"      - {resource} (property_aliases)")

    if fatal_lines:
        message = ["[configure] fatal alias collision(s) detected:"]
        message.extend(fatal_lines)
        message.append(
            "Resolve by editing the corresponding `prompts/configure_<resource>.md` "
            "files, then rerun configure with `--resource <name1> <name2>`. "
            "The loader rejects an `app.yaml` containing these collisions, "
            "so the file has not been written."
        )
        raise SystemExit("\n".join(message))

    # Advisory: property_alias-only overlap. Legitimate; surface to user.
    advisory_lines: list[str] = []
    for alias in sorted(property_alias_claims):
        owners = property_alias_claims[alias]
        if alias in name_variant_claims:
            continue
        if len(owners) > 1:
            advisory_lines.append(
                f"  - {alias!r} contextual property_alias claimed by: "
                f"{', '.join(sorted(owners))}"
            )
    if advisory_lines:
        print(
            "[configure] note: property_alias overlap detected — these "
            "resolve contextually at walk time via the schema's binding:"
        )
        for line in advisory_lines:
            print(line)


def _merge_into_yaml(
    config_path: Path,
    verdicts: dict[str, ResourceVerdict],
) -> None:
    """Write each verdict back into ``app.yaml`` in two-tier shape.

    Existing entries are merged (not replaced) so a configure re-run
    accumulates trustworthy aliases without erasing the user's manual
    additions. Legacy ``aliases:`` bags are migrated into
    ``name_variants:`` in place — the resource is upgraded to the
    two-tier shape on the first configure call after #3 lands.
    """
    raw = yaml.safe_load(config_path.read_text()) or {}
    resources_raw = raw.get("resources") or {}

    for resource, verdict in verdicts.items():
        existing = resources_raw.get(resource) or {}

        existing_name_variants = list(existing.get("name_variants") or [])
        existing_property_aliases = list(existing.get("property_aliases") or [])
        legacy_aliases = existing.get("aliases")
        if legacy_aliases:
            existing_name_variants.extend(legacy_aliases)

        merged_name_variants_set = (
            set(existing_name_variants) | set(verdict.name_variants)
        )
        merged_property_aliases_set = (
            set(existing_property_aliases) | set(verdict.property_aliases)
        )

        # Auto-inject the canonical's singular/plural forms into
        # name_variants. The LLM occasionally classifies the bare
        # singular (e.g. ``user``, ``task``, ``section``) as a
        # property_alias because the same word is also a role-word in
        # field names — but the canonical name's singular IS the entity
        # name and belongs in name_variants regardless. If the form
        # appears in property_aliases too, name_variants wins (broader
        # privilege). This is purely deterministic correction.
        for canonical_form in canonical_forms(resource):
            merged_name_variants_set.add(canonical_form)
            merged_property_aliases_set.discard(canonical_form)

        merged_name_variants = sorted(merged_name_variants_set)
        # Coalesce: an alias declared in both tiers ends up only in
        # name_variants (the broader privilege wins).
        merged_property_aliases = sorted(
            merged_property_aliases_set - merged_name_variants_set
        )

        new_entry: dict[str, Any] = {}
        primary_key = verdict.primary_key or existing.get("primary_key")
        if primary_key and primary_key != "id":
            new_entry["primary_key"] = primary_key
        self_ids = verdict.self_id_fields or existing.get("self_id_fields") or []
        if self_ids:
            new_entry["self_id_fields"] = list(self_ids)
        new_entry["name_variants"] = merged_name_variants
        if merged_property_aliases:
            new_entry["property_aliases"] = merged_property_aliases
        resources_raw[resource] = new_entry

    # Promote per-resource ``self_id_fields`` into the global naming block
    # (the loader expects them there too — preserves earlier behavior).
    all_self_ids: set[str] = set()
    for entry in resources_raw.values():
        if isinstance(entry, dict):
            for field in entry.get("self_id_fields") or []:
                all_self_ids.add(field)
    if all_self_ids:
        naming = raw.get("naming") or {}
        existing_self_ids = set(naming.get("self_id_fields") or [])
        naming["self_id_fields"] = sorted(existing_self_ids | all_self_ids)
        raw["naming"] = naming

    raw["resources"] = resources_raw
    config_path.write_text(yaml.safe_dump(raw, default_flow_style=False, sort_keys=False))
