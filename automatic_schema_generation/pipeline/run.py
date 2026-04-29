"""Pipeline orchestrator — dispatches stages in canonical order.

Each stage's body lives in its home package. This file is the dispatch
table: it parses CLI args into a ``RunContext`` and calls each
selected stage's ``run_*`` function in canonical order.

Usage::

    # Full pipeline (init → configure → ... → test_endpoints):
    python -m pipeline.run app.yaml

    # Single stage / range of stages:
    python -m pipeline.run app.yaml --stage init
    python -m pipeline.run app.yaml --up-to-stage register_tests
    python -m pipeline.run app.yaml --from-stage seed_template

    # Restrict to specific resources / subjects:
    python -m pipeline.run app.yaml --resource gists

    # Dry run (build prompts, don't call LLM):
    python -m pipeline.run app.yaml --dry-run
"""

from __future__ import annotations

import argparse
from dataclasses import dataclass
from pathlib import Path

from pipeline.aliases.configure import run_configure
from pipeline.aliases.runner import run_suggest_aliases
from pipeline.extraction.runner import run_extract
from pipeline.implementation.runner import run_implement, run_implement_responses
from pipeline.scaffold import run_init
from pipeline.testing.register import run_register_tests
from pipeline.testing.runner import run_test_endpoints_stage
from pipeline.testing.seed import run_seed_template


@dataclass
class RunContext:
    """Shared run context passed to every stage runner.

    Each stage's ``run_*`` function takes a single ``RunContext``
    argument instead of a long bespoke kwargs list, so the dispatch
    table below can hand stages a uniform handle, and adding a new
    orchestrator-level option only touches this dataclass.
    """

    config_path: Path
    dry_run: bool = False
    only_resources: list[str] | None = None
    configure_model: str = "claude-sonnet-4-5"
    implement_model: str = "claude-opus-4-6"
    test_model: str = "claude-opus-4-6"
    test_batch_size: int = 7
    test_max_iterations: int = 3
    test_force_retest: bool = False
    test_timeout: int = 1800
    # When False (default), the implement stage refuses to run unless
    # ``app.yaml`` lists ``selected_endpoints``. When True, every
    # endpoint of every resource in app.yaml is implemented (the old
    # resource-centric behaviour). Off by default because implementing
    # whole apps in one go is expensive in LLM tokens.
    all_endpoints_per_resource: bool = False

    @property
    def output_dir(self) -> Path:
        """``pipeline_out/`` next to ``app.yaml`` — destination for stage artifacts."""
        return self.config_path.parent / "pipeline_out"

    @property
    def prompt_dir(self) -> Path:
        """``pipeline_prompts/`` next to ``app.yaml`` — saved LLM prompts (dry runs + audit trail)."""
        return self.config_path.parent / "pipeline_prompts"

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


def run_pipeline(ctx: RunContext, stages: list[str] | None = None) -> None:
    """Run the named stages in canonical order against ``ctx``.

    ``stages`` defaults to the full pipeline. Pass a subset to run a
    slice — order in the input is irrelevant; canonical order is
    preserved. Unknown names raise ValueError.
    """
    if stages is None:
        stages = _STAGES
    unknown = [stage for stage in stages if stage not in _STAGE_RUNNERS]
    if unknown:
        raise ValueError(f"Unknown stage(s): {unknown}. Valid: {_STAGES}")

    for stage in _STAGES:
        if stage in stages:
            _STAGE_RUNNERS[stage](ctx)

    print("\nPipeline complete.")


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(description="Run the pipeline orchestrator.")
    parser.add_argument("config", type=Path, help="Path to app.yaml")

    # --stage / --up-to-stage / --from-stage are mutually exclusive ways to
    # build the stages list. None given → full pipeline.
    stage_group = parser.add_mutually_exclusive_group()
    stage_group.add_argument(
        "--stage", choices=_STAGES, default=None,
        help="Run a single stage. Omit to run the full pipeline.",
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
    parser.add_argument("--configure-model", default=RunContext.configure_model, help="Model for alias/PK inference")
    parser.add_argument("--implement-model", default=RunContext.implement_model, help="Model for entity implementation")
    parser.add_argument("--test-model", default=RunContext.test_model, help="Model for test_endpoints stage")
    parser.add_argument("--test-batch-size", type=int, default=RunContext.test_batch_size, help="Endpoints per LLM call in test_endpoints")
    parser.add_argument("--test-max-iterations", type=int, default=RunContext.test_max_iterations, help="Fix-and-retry budget per endpoint")
    parser.add_argument("--test-timeout", type=int, default=RunContext.test_timeout, help="Per-batch claude -p timeout in seconds")
    parser.add_argument("--force-retest", action="store_true", help="Test endpoints already marked tested=true (regression sweep)")
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

    if args.up_to_stage:
        stages = _STAGES[: _STAGES.index(args.up_to_stage) + 1]
    elif args.from_stage:
        stages = _STAGES[_STAGES.index(args.from_stage):]
    elif args.stage:
        stages = [args.stage]
    else:
        stages = None

    ctx = RunContext(
        config_path=args.config,
        dry_run=args.dry_run,
        only_resources=args.resource,
        configure_model=args.configure_model,
        implement_model=args.implement_model,
        test_model=args.test_model,
        test_batch_size=args.test_batch_size,
        test_max_iterations=args.test_max_iterations,
        test_force_retest=args.force_retest,
        test_timeout=args.test_timeout,
        all_endpoints_per_resource=args.all_endpoints_per_resource,
    )
    run_pipeline(ctx, stages)


if __name__ == "__main__":
    main()
