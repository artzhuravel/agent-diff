"""``build`` entrypoint — first-time build of a replica from spec.

Dispatches the full canonical pipeline (init → configure →
suggest_aliases → extract → implement_responses → implement →
register_tests → seed_template → test_endpoints) against an
``app.yaml`` describing the target service. The pair to this is
``replica_pipeline.extend_replica``, which adds endpoints to a replica that's
already been built.

Each stage's body lives in its home package. This file is the
dispatch table: it parses CLI args (via shared helpers in
``_cli.py``) into a ``RunContext`` and calls each selected stage's
``run_*`` function in canonical order.

Usage::

    # Full pipeline (init → configure → ... → test_endpoints):
    python -m replica_pipeline.build_replica app.yaml

    # Single stage / range of stages:
    python -m replica_pipeline.build_replica app.yaml --stage init
    python -m replica_pipeline.build_replica app.yaml --up-to-stage register_tests
    python -m replica_pipeline.build_replica app.yaml --from-stage seed_template

    # Restrict to specific resources / subjects:
    python -m replica_pipeline.build_replica app.yaml --resource gists

    # Dry run (build prompts, don't call LLM):
    python -m replica_pipeline.build_replica app.yaml --dry-run
"""

from __future__ import annotations

import argparse
from pathlib import Path

from replica_pipeline._cli import (
    RunContext,
    add_common_args,
    add_stage_args,
    build_run_context,
    dispatch_stages,
    slice_stages,
)
from replica_pipeline.aliases.configure import run_configure
from replica_pipeline.aliases.runner import run_suggest_aliases
from replica_pipeline.extraction.runner import run_extract
from replica_pipeline.implementation.runner import run_implement, run_implement_responses
from replica_pipeline.scaffold import run_init
from replica_pipeline.testing.register import run_register_tests
from replica_pipeline.testing.runner import run_test_endpoints_stage
from replica_pipeline.testing.seed import run_seed_template


# Canonical stage order. The dict double-duties as the order list
# (Python 3.7+ insertion-ordered) and the dispatch table.
_STAGE_RUNNERS = {
    "init": run_init,
    "configure": run_configure,
    "suggest_aliases": run_suggest_aliases,
    "extract": run_extract,
    "implement_responses": run_implement_responses,
    "implement": run_implement,
    "register_tests": run_register_tests,
    "seed_template": run_seed_template,
    "test_endpoints": run_test_endpoints_stage,
}
_STAGES = list(_STAGE_RUNNERS)


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(description="Run the pipeline orchestrator.")
    parser.add_argument("config", type=Path, help="Path to app.yaml")
    add_stage_args(parser, _STAGES)
    add_common_args(parser)
    parser.add_argument(
        "--configure-model", default=RunContext.configure_model,
        help="Model for alias/PK inference",
    )
    parser.add_argument(
        "--all-endpoints-per-resource",
        action="store_true",
        help=(
            "Implement every endpoint of each resource listed in app.yaml. "
            "Without this flag the implement stage requires a `selected_endpoints` "
            "list in app.yaml and only implements those entries."
        ),
    )

    args = parser.parse_args(argv)
    ctx = build_run_context(
        args,
        configure_model=args.configure_model,
        all_endpoints_per_resource=args.all_endpoints_per_resource,
    )
    dispatch_stages(_STAGE_RUNNERS, slice_stages(args, _STAGES), ctx)
    print("\nPipeline complete.")


if __name__ == "__main__":
    main()
