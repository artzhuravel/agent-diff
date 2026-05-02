"""Patch reviewed alias suggestions into an ``app.yaml`` config.

Module-level helper used by the ``suggest_aliases`` stage runner.
The CLI form (``python -m replica_pipeline.aliases.apply ...``) was retired
in favour of ``python -m replica_pipeline.build_replica app.yaml --stage suggest_aliases``,
which runs the whole suggest+review+apply chain in one invocation.

The suggester emits schema-name candidates — by definition these are
*name variants*, not property aliases. So accepted candidates are
appended to ``name_variants:`` when the resource uses the new two-tier
shape, and to the legacy ``aliases:`` field when the resource still
uses the single-bag form. The format the user picked is preserved.
"""

from __future__ import annotations

import re

# These keys are not resource names — used to skip them while detecting
# resource-name lines. Kept in sync with ``config.py``'s loader.
_NON_RESOURCE_KEYS = frozenset({
    "aliases", "primary_key", "self_id_fields",
    "name_variants", "property_aliases",
})

# The list-keys this patcher knows how to insert under, in priority order.
# ``name_variants`` wins when both are present (the new format is
# preferred); ``aliases`` is the legacy fallback.
_INSERTION_KEYS = ("name_variants", "aliases")


def patch_config(text: str, new_aliases: dict[str, list[str]]) -> str:
    """Insert new aliases into raw YAML text, preserving comments.

    Detects indentation dynamically so it works with both hand-written
    configs (6-space alias entries) and yaml.safe_dump output (4-space).
    For each resource, inserts under ``name_variants:`` if present, else
    under ``aliases:``. If neither list exists, the resource is skipped
    (the loader will accept an empty config but this patcher doesn't
    create new keys to avoid surprising the user).
    """
    # Detect the indent used for resource names under "resources:"
    resource_indent = ""
    for line in text.split("\n"):
        if re.match(r"^resources:\s*$", line):
            continue
        resource_match = re.match(r"^(\s+)(\w+):\s*$", line)
        if resource_match and resource_match.group(2) not in _NON_RESOURCE_KEYS:
            resource_indent = resource_match.group(1)
            break

    lines = text.split("\n")
    # Per-resource insertion record: which list-key, and where the last
    # existing entry under that list lives. Storing both lets us prefer
    # ``name_variants`` over ``aliases`` when both happen to coexist.
    insert_records: dict[str, dict[str, tuple[int, str]]] = {}
    current_resource: str | None = None
    active_list_key: str | None = None

    for index, line in enumerate(lines):
        resource_match = re.match(rf"^{resource_indent}(\w+):\s*$", line)
        if resource_match and resource_match.group(1) not in _NON_RESOURCE_KEYS:
            current_resource = (
                resource_match.group(1) if resource_match.group(1) in new_aliases else None
            )
            active_list_key = None
            continue
        if current_resource is None:
            continue

        # Look for the start of any insertion-target list.
        list_start_match = re.match(r"^\s+(\w+):\s*$", line)
        if list_start_match and list_start_match.group(1) in _INSERTION_KEYS:
            active_list_key = list_start_match.group(1)
            continue

        alias_line_match = re.match(r"^(\s+)- ", line)
        if active_list_key is not None and alias_line_match:
            alias_indent = alias_line_match.group(1)
            insert_records.setdefault(current_resource, {})[active_list_key] = (
                index, alias_indent,
            )
            continue
        if active_list_key is not None and (re.match(r"^\s+#", line) or not line.strip()):
            continue
        if active_list_key is not None:
            active_list_key = None

    # Pick one list-key per resource (prefer name_variants), then sort the
    # insertions by line index descending so earlier inserts don't shift
    # later indexes.
    chosen: dict[str, tuple[int, str]] = {}
    for resource, by_key in insert_records.items():
        for preferred_key in _INSERTION_KEYS:
            if preferred_key in by_key:
                chosen[resource] = by_key[preferred_key]
                break

    for resource in sorted(chosen, key=lambda r: chosen[r][0], reverse=True):
        idx, indent = chosen[resource]
        new_lines = [f"{indent}- {alias}" for alias in sorted(new_aliases[resource])]
        lines[idx + 1 : idx + 1] = new_lines

    return "\n".join(lines)
