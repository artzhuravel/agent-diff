"""Prompt construction for the ``configure`` stage.

Asks the LLM to populate alias lists and primary-key declarations
for each resource by reading the OpenAPI spec. The runner handles
the YAML write-back; this module owns the prompt text.
"""

from __future__ import annotations

from pathlib import Path


_AUTO_CONFIGURE_PROMPT = """\
Read the OpenAPI spec at: {spec_path}

For each resource listed below, examine the spec's component schemas, endpoint
paths, parameters, and response bodies. Then output a YAML block with:

1. **aliases**: every name/variant the spec uses to refer to this resource.
   You MUST include both singular AND plural forms (e.g. user AND users,
   project AND projects). Also include:
   - Role words that resolve to this resource (e.g. owner, assignee, creator,
     author, committer, collaborator all map to users)
   - Schema name variants (e.g. simple_user, full_repository, task_compact)
   - Abbreviated forms (e.g. repo for repository, pr for pull_request)
   Normalize everything to snake_case.

   Do NOT include as aliases:
   - Field or column names that describe a property of the entity, not a
     name for the entity itself
   - Generic positional or structural words that describe where an entity
     sits in a relationship, not what the entity is
   - Abbreviations you invented that do not appear anywhere in the spec

2. **primary_key**: the field name used as the unique identifier. Default is
   "id" — only override if the spec uses something else (e.g. "sha" for
   commits, "name" for branches, "gid" for Asana-style APIs).

3. **self_id_fields**: fields that represent the entity's own identity (not a
   FK to another resource). Usually just the primary key, but some APIs have
   multiple identity fields (e.g. "id" and "node_id" for GitHub, "gid" for
   Asana). Only include if different from the default ["id"].

Resources to configure: {resource_names}

Respond ONLY with a YAML block (no markdown fences, no prose), like:

users:
  aliases:
    - user
    - users
    - owner
    - author
  primary_key: id
projects:
  aliases:
    - project
    - projects
  primary_key: gid
  self_id_fields:
    - gid
"""


def build_configure_prompt(spec_path: Path, resource_names: list[str]) -> str:
    """Render the configure prompt for the given resource list."""
    return _AUTO_CONFIGURE_PROMPT.format(
        spec_path=spec_path,
        resource_names=", ".join(resource_names),
    )
