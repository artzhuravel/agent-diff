"""``suggest_aliases`` stage — find candidate aliases, review, apply.

Wraps the three steps that the orchestrator used to do inline:
  1. ``suggest_aliases`` — walk the spec and emit normalized candidates.
  2. ``review_suggestions`` — call the LLM to verdict each candidate.
  3. ``patch_config`` — write the accepted ones back into ``app.yaml``.

Cache results from step 2 land under ``pipeline_cache/alias_review.json``
so re-runs don't pay the LLM cost again.
"""

from __future__ import annotations

from pathlib import Path

from replica_pipeline.aliases.apply import patch_config
from replica_pipeline.aliases.review import review_suggestions
from replica_pipeline.aliases.suggest import suggest_aliases
from replica_pipeline.config import load_config
from replica_pipeline.utils.llm import make_llm_call


def run_suggest_aliases(ctx) -> None:
    """``suggest_aliases`` stage — find, review, apply schema aliases."""
    config = load_config(ctx.config_path)
    spec = config.load_spec()

    print("\n=== SUGGEST ALIASES — find + review + apply schema aliases ===")
    suggestions = suggest_aliases(spec, config)
    total_candidates = sum(len(values) for values in suggestions.values())

    if total_candidates == 0:
        print("  No alias candidates found.")
        return
    if ctx.dry_run:
        print(f"  [dry-run] {total_candidates} candidates across {len(suggestions)} resources")
        return

    cache_path = ctx.config_path.parent / "pipeline_cache" / "alias_review.json"
    llm_call = make_llm_call(model=ctx.configure_model)
    print(f"  Reviewing {total_candidates} candidates via {ctx.configure_model}...")
    reviewed = review_suggestions(
        suggestions, spec, config, llm_call,
        cache_path=cache_path, prompt_dir=ctx.prompt_dir,
    )

    new_aliases: dict[str, list[str]] = {}
    for resource, entries in reviewed.items():
        existing = config.resources.aliases_by_resource.get(resource, frozenset())
        additions = [
            entry.suggestion.normalized
            for entry in entries
            if entry.verdict == "variant" and entry.suggestion.normalized not in existing
        ]
        if additions:
            new_aliases[resource] = additions

    if not new_aliases:
        print("  No new aliases to apply.")
        return

    total_new = sum(len(values) for values in new_aliases.values())
    print(f"  Applying {total_new} new aliases across {len(new_aliases)} resources...")
    patched = patch_config(ctx.config_path.read_text(), new_aliases)
    ctx.config_path.write_text(patched)
    print(f"  Updated {ctx.config_path}")
