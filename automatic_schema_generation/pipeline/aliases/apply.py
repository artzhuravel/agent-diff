"""Patch reviewed alias suggestions into an ``app.yaml`` config.

Module-level helper used by the ``suggest_aliases`` stage runner.
The CLI form (``python -m pipeline.aliases.apply ...``) was retired
in favour of ``python -m pipeline.run app.yaml --stage suggest_aliases``,
which runs the whole suggest+review+apply chain in one invocation.
"""

from __future__ import annotations

import re


def patch_config(text: str, new_aliases: dict[str, list[str]]) -> str:
    """Insert new aliases into raw YAML text, preserving comments.

    Detects indentation dynamically so it works with both hand-written
    configs (6-space alias entries) and yaml.safe_dump output (4-space).
    """
    # Detect the indent used for resource names under "resources:"
    resource_indent = ""
    for line in text.split("\n"):
        if re.match(r"^resources:\s*$", line):
            continue
        resource_match = re.match(r"^(\s+)(\w+):\s*$", line)
        if resource_match and resource_match.group(2) not in ("aliases", "primary_key", "self_id_fields"):
            resource_indent = resource_match.group(1)
            break

    lines = text.split("\n")
    insert_after: dict[str, tuple[int, str]] = {}
    current_resource: str | None = None
    in_aliases = False

    for index, line in enumerate(lines):
        resource_match = re.match(rf"^{resource_indent}(\w+):\s*$", line)
        if resource_match and resource_match.group(1) not in ("aliases", "primary_key", "self_id_fields"):
            current_resource = resource_match.group(1) if resource_match.group(1) in new_aliases else None
            in_aliases = False
            continue
        if current_resource is None:
            continue
        if re.match(r"^\s+aliases:\s*$", line):
            in_aliases = True
            continue
        if in_aliases and re.match(r"^(\s+)- ", line):
            alias_indent = re.match(r"^(\s*)", line).group(1)
            insert_after[current_resource] = (index, alias_indent)
            continue
        if in_aliases and (re.match(r"^\s+#", line) or not line.strip()):
            continue
        if in_aliases:
            in_aliases = False

    for resource in sorted(insert_after, key=lambda r: insert_after[r][0], reverse=True):
        idx, indent = insert_after[resource]
        new_lines = [f"{indent}- {alias}" for alias in sorted(new_aliases[resource])]
        lines[idx + 1 : idx + 1] = new_lines

    return "\n".join(lines)
