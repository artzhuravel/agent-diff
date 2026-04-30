"""Auto-configure stage — call an LLM to populate aliases / PKs / self-ids.

Splits cleanly from ``pipeline.config``: that module is purely about
loading and validating an existing ``app.yaml``. This one is the
``configure`` stage runner — it walks the spec, asks the LLM for each
resource's aliases and primary key, parses the YAML response, and
writes the result back into ``app.yaml`` (merging with whatever was
there before).
"""

from __future__ import annotations

from collections.abc import Callable
from pathlib import Path
from typing import Any

import yaml

from replica_pipeline.config import load_config
from replica_pipeline.prompts.configure import build_configure_prompt
from replica_pipeline.utils.llm import make_llm_call


def run_configure(ctx) -> None:
    """``configure`` stage — call the LLM and persist resource configs."""
    print("\n=== CONFIGURE — LLM populates aliases and PKs ===")
    config = load_config(ctx.config_path)

    resource_names = ctx.only_resources or sorted(config.resources.aliases_by_resource.keys())
    if ctx.dry_run:
        print(f"  [dry-run] Would call {ctx.configure_model} for: {resource_names}")
        return

    llm_call = make_llm_call(model=ctx.configure_model)
    auto_configure_resources(ctx.config_path, config.openapi_path, resource_names, llm_call)
    print(f"  Configured {len(resource_names)} resources via {ctx.configure_model}")


def auto_configure_resources(
    config_path: Path,
    spec_path: Path,
    resource_names: list[str],
    llm_call: Callable[[str], str],
) -> None:
    """Call an LLM to populate aliases and PKs, then write to config YAML."""
    prompt = build_configure_prompt(spec_path, resource_names)
    response = llm_call(prompt)
    parsed = _parse_auto_configure_response(response, resource_names)

    raw = yaml.safe_load(config_path.read_text()) or {}
    resources_raw = raw.get("resources") or {}
    for resource_name, resource_config in parsed.items():
        existing = resources_raw.get(resource_name) or {}
        existing_aliases = existing.get("aliases") or []
        merged_aliases = sorted(set(existing_aliases) | set(resource_config.get("aliases", [])))
        resources_raw[resource_name] = {"aliases": merged_aliases}
        primary_key = resource_config.get("primary_key")
        if primary_key and primary_key != "id":
            resources_raw[resource_name]["primary_key"] = primary_key
        self_id_fields = resource_config.get("self_id_fields")
        if self_id_fields:
            resources_raw[resource_name]["self_id_fields"] = self_id_fields

    # Merge self_id_fields into naming if any resource specified them
    all_self_ids: set[str] = set()
    for resource_entry in resources_raw.values():
        if isinstance(resource_entry, dict):
            for field in resource_entry.get("self_id_fields") or []:
                all_self_ids.add(field)
    if all_self_ids:
        naming = raw.get("naming") or {}
        existing_self_ids = set(naming.get("self_id_fields") or [])
        naming["self_id_fields"] = sorted(existing_self_ids | all_self_ids)
        raw["naming"] = naming

    raw["resources"] = resources_raw
    config_path.write_text(yaml.safe_dump(raw, default_flow_style=False, sort_keys=False))


def _parse_auto_configure_response(
    response: str,
    resource_names: list[str],
) -> dict:
    """Parse the LLM's YAML response into {resource: {aliases, primary_key}}."""
    # Strip markdown fences if present
    text = response.strip()
    if text.startswith("```"):
        text = text.split("\n", 1)[1] if "\n" in text else text
    if text.endswith("```"):
        text = text.rsplit("```", 1)[0]

    try:
        parsed = yaml.safe_load(text)
    except yaml.YAMLError:
        return {}
    if not isinstance(parsed, dict):
        return {}

    result = {}
    for resource_name in resource_names:
        entry = parsed.get(resource_name)
        if not isinstance(entry, dict):
            continue
        aliases = entry.get("aliases") or []
        if not isinstance(aliases, list):
            continue
        config_entry: dict[str, Any] = {"aliases": [str(alias) for alias in aliases]}
        primary_key = entry.get("primary_key")
        if isinstance(primary_key, str) and primary_key:
            config_entry["primary_key"] = primary_key
        self_id_fields = entry.get("self_id_fields")
        if isinstance(self_id_fields, list) and all(isinstance(field, str) for field in self_id_fields):
            config_entry["self_id_fields"] = self_id_fields
        result[resource_name] = config_entry
    return result
