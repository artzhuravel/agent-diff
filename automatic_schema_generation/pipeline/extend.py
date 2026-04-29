"""``extend`` entrypoint — add new endpoints to an existing replica.

A separate command from ``run.py`` because it skips the first-time
scaffolding stages (init / configure / suggest_aliases) and swaps the
``implement`` stage for ``extend``, which scans the existing target
directory to decide create-vs-extend per resource.

Usage::

    # Add the endpoints listed under `selected_endpoints` in app.yaml:
    python -m pipeline.extend app.yaml

    # Restrict to a single resource:
    python -m pipeline.extend app.yaml --resource tasks

    # Build prompts without calling the LLM:
    python -m pipeline.extend app.yaml --dry-run
"""

from __future__ import annotations

import argparse
from pathlib import Path

from pipeline.extraction.runner import run_extract
from pipeline.implementation.runner import run_extend, run_implement_responses
from pipeline.run import RunContext
from pipeline.testing.register import run_register_tests
from pipeline.testing.runner import run_test_endpoints_stage
from pipeline.testing.seed import run_seed_template


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

    stage_group = parser.add_mutually_exclusive_group()
    stage_group.add_argument(
        "--stage", choices=_STAGES, default=None,
        help="Run a single stage. Omit to run the full extend pipeline.",
    )
    stage_group.add_argument(
        "--up-to-stage", choices=_STAGES, default=None,
        help="Run every stage from the start through this one (inclusive)",
    )
    stage_group.add_argument(
        "--from-stage", choices=_STAGES, default=None,
        help="Run every stage from this one through the end (inclusive)",
    )

    parser.add_argument("--resource", nargs="+", metavar="NAME", help="Restrict to specific resources")
    parser.add_argument("--dry-run", action="store_true", help="Build prompts without calling LLM")
    parser.add_argument("--implement-model", default=RunContext.implement_model, help="Model for entity extension")
    parser.add_argument("--test-model", default=RunContext.test_model, help="Model for test_endpoints stage")
    parser.add_argument("--test-batch-size", type=int, default=RunContext.test_batch_size, help="Endpoints per LLM call in test_endpoints")
    parser.add_argument("--test-max-iterations", type=int, default=RunContext.test_max_iterations, help="Fix-and-retry budget per endpoint")
    parser.add_argument("--test-timeout", type=int, default=RunContext.test_timeout, help="Per-batch claude -p timeout in seconds")
    parser.add_argument("--force-retest", action="store_true", help="Test endpoints already marked tested=true (regression sweep)")

    args = parser.parse_args(argv)

    if args.up_to_stage:
        stages = _STAGES[: _STAGES.index(args.up_to_stage) + 1]
    elif args.from_stage:
        stages = _STAGES[_STAGES.index(args.from_stage):]
    elif args.stage:
        stages = [args.stage]
    else:
        stages = _STAGES

    ctx = RunContext(
        config_path=args.config,
        dry_run=args.dry_run,
        only_resources=args.resource,
        implement_model=args.implement_model,
        test_model=args.test_model,
        test_batch_size=args.test_batch_size,
        test_max_iterations=args.test_max_iterations,
        test_force_retest=args.force_retest,
        test_timeout=args.test_timeout,
    )

    for stage in _STAGES:
        if stage in stages:
            _STAGE_RUNNERS[stage](ctx)

    print("\nExtend complete.")


if __name__ == "__main__":
    main()
