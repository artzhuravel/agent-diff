"""``extend`` entrypoint — add new endpoints to an existing replica.

A separate command from ``run.py`` because it skips the first-time
scaffolding stages (init / configure / suggest_aliases) and swaps the
``implement`` stage for ``extend``, which scans the existing target
directory to decide create-vs-extend per resource.

By default runs the full extend chain — ``extract → implement_responses
→ extend → register_tests → seed_template → test_endpoints`` — mirroring
``replica_pipeline.build_replica``'s "do everything" default. Use ``--up-to-stage extend``
to stop after generating code (e.g. to inspect the diff before paying
for the testing pass).

Usage::

    # Full chain — extend + register + test the new endpoints:
    python -m replica_pipeline.extend_replica app.yaml

    # Restrict to a single resource:
    python -m replica_pipeline.extend_replica app.yaml --resource tasks

    # Build prompts without calling the LLM:
    python -m replica_pipeline.extend_replica app.yaml --dry-run

    # Stop after generating code (skip register_tests/seed/test):
    python -m replica_pipeline.extend_replica app.yaml --up-to-stage extend
"""

from __future__ import annotations

import argparse
from pathlib import Path

from replica_pipeline._cli import (
    add_common_args,
    add_stage_args,
    build_run_context,
    dispatch_stages,
    slice_stages,
)
from replica_pipeline.extraction.runner import run_extract
from replica_pipeline.implementation.runner import run_extend, run_implement_responses
from replica_pipeline.testing.register import run_register_tests
from replica_pipeline.testing.runner import run_test_endpoints_stage
from replica_pipeline.testing.seed import run_seed_template


# Canonical extend-pipeline order. ``init``, ``configure``, and
# ``suggest_aliases`` are intentionally absent — those only run during
# first-time scaffolding. ``extract`` runs to refresh endpoints.json /
# resources.json so the new endpoints are visible to ``run_extend``.
_STAGE_RUNNERS = {
    "extract": run_extract,
    "implement_responses": run_implement_responses,
    "extend": run_extend,
    "register_tests": run_register_tests,
    "seed_template": run_seed_template,
    "test_endpoints": run_test_endpoints_stage,
}
_STAGES = list(_STAGE_RUNNERS)


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(
        description="Extend an existing replica with new endpoints listed in app.yaml.",
    )
    parser.add_argument("config", type=Path, help="Path to app.yaml")
    add_stage_args(parser, _STAGES)
    add_common_args(parser)

    args = parser.parse_args(argv)
    ctx = build_run_context(args)
    dispatch_stages(_STAGE_RUNNERS, slice_stages(args, _STAGES), ctx)
    print("\nExtend complete.")


if __name__ == "__main__":
    main()
