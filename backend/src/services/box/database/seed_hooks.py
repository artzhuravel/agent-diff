"""Pre-insert hook for the Box seeder.

JSON cannot carry binary content, so the Box seed JSON references file
bytes by relative path: each ``box_file_versions`` record optionally
declares a ``local_path`` field pointing at a file in
``backend/seeds/box/filesystem/...``. This hook reads each referenced
file, synthesizes a matching ``box_file_contents`` row carrying the
bytes, and pops the sentinel field so it doesn't reach the INSERT.

The mechanism is opt-in: only ``box_file_versions`` records that include
``local_path`` participate. Versions without the field get inserted as
plain rows (with no content row), which matches the historical behavior.

This file is discovered automatically by the generic seeder
(``backend/utils/seed_template.py``) — naming and signature must match
``before_insert(seed_data, Base)``.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any


# ``parents[4]`` resolves to ``backend/`` regardless of where the repo is
# cloned. Layout: ``backend/src/services/box/database/seed_hooks.py``.
_BACKEND_ROOT = Path(__file__).resolve().parents[4]
_REPO_ROOT = _BACKEND_ROOT.parent


def before_insert(seed_data: dict[str, Any], _base: Any) -> None:
    """Translate ``local_path`` sentinels into ``box_file_contents`` rows.

    Mutates ``seed_data`` in place. Idempotent for a single dict — running
    it twice on the same dict is a no-op since the sentinels are popped
    on first pass.
    """
    versions = seed_data.get("box_file_versions") or []
    if not versions:
        return

    content_records: list[dict[str, Any]] = []
    for version in versions:
        if "local_path" not in version:
            continue
        local_path = version.pop("local_path")

        # The seed JSON uses the repo-root convention
        # ``examples/box/seeds/filesystem/...``. In Docker the same
        # files are mounted at ``backend/seeds/box/...``; for local
        # dev the original path resolves under the repo root.
        remapped = local_path.replace("examples/box/seeds/", "seeds/box/", 1)
        candidate = _BACKEND_ROOT / remapped
        if not candidate.exists():
            candidate = _REPO_ROOT / local_path

        if not candidate.exists():
            print(f"  [warn] missing binary content: {local_path}")
            continue
        try:
            content = candidate.read_bytes()
        except Exception as exc:  # noqa: BLE001 — surfaced inline, not swallowed
            print(f"  [warn] failed to read {local_path}: {exc}")
            continue

        # ``box_file_contents`` is 1-to-1 with ``box_file_versions`` and
        # reuses the version's id as its own primary key.
        content_records.append({
            "id": version["id"],
            "version_id": version["id"],
            "content": content,
        })

    if content_records:
        seed_data.setdefault("box_file_contents", []).extend(content_records)
