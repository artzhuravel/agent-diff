"""Shared CLI machinery for the ``replica_pipeline.build_replica`` and ``replica_pipeline.extend_replica`` entrypoints.

The two entrypoints differ in *which* stages they dispatch and a couple
of flags (``build.py`` exposes ``--all-endpoints-per-resource`` and
``--configure-model``; ``extend.py`` doesn't). Everything else — the
mutually exclusive ``--stage``/``--up-to-stage``/``--from-stage`` group,
the standard flags (``--resource``, ``--dry-run``, model overrides,
test-stage tuning), the stage-slicing logic, the ``RunContext``
construction, and the dispatch loop — is identical and lives here.

``RunContext`` itself also lives here because it's the shared state
both entrypoints construct from CLI args. Each stage runner takes a
single ``RunContext`` argument; adding a new orchestrator-level option
is a one-line edit to this dataclass.
"""

from __future__ import annotations

import argparse
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable

from replica_pipeline.utils.llm import (
    DEFAULT_CONFIGURE_MODEL,
    DEFAULT_IMPLEMENT_MODEL,
    DEFAULT_TEST_MODEL,
)


@dataclass
class RunContext:
    """Shared run context passed to every stage runner.

    Each stage's ``run_*`` function takes a single ``RunContext``
    argument instead of a long bespoke kwargs list, so the dispatch
    table can hand stages a uniform handle, and adding a new
    orchestrator-level option only touches this dataclass.
    """

    config_path: Path
    dry_run: bool = False
    only_resources: list[str] | None = None
    configure_model: str = DEFAULT_CONFIGURE_MODEL
    implement_model: str = DEFAULT_IMPLEMENT_MODEL
    test_model: str = DEFAULT_TEST_MODEL
    test_batch_size: int = 7
    test_max_iterations: int = 3
    test_force_retest: bool = False
    test_timeout: int = 1800
    # When False (default), the implement stage refuses to run unless
    # ``app.yaml`` lists ``selected_endpoints``. When True, every
    # endpoint of every resource in app.yaml is implemented (the old
    # resource-centric behaviour). Off by default because implementing
    # whole apps in one go is expensive in LLM tokens. The extend
    # entrypoint never sets this — see ``run_extend``'s explicit
    # rejection of resource-centric mode.
    all_endpoints_per_resource: bool = False

    @property
    def output_dir(self) -> Path:
        """``pipeline_out/`` next to ``app.yaml`` — destination for stage artifacts."""
        return self.config_path.parent / "pipeline_out"

    @property
    def prompt_dir(self) -> Path:
        """``pipeline_prompts/`` next to ``app.yaml`` — saved LLM prompts (dry runs + audit trail)."""
        return self.config_path.parent / "pipeline_prompts"


def add_stage_args(parser: argparse.ArgumentParser, stages: list[str]) -> None:
    """Mutually exclusive ``--stage`` / ``--up-to-stage`` / ``--from-stage``.

    Omitting all three means "run the full pipeline" — see ``slice_stages``.
    """
    group = parser.add_mutually_exclusive_group()
    group.add_argument(
        "--stage", choices=stages, default=None,
        help="Run a single stage. Omit to run the full pipeline.",
    )
    group.add_argument(
        "--up-to-stage", choices=stages, default=None,
        help="Run every stage from the start through this one (inclusive)",
    )
    group.add_argument(
        "--from-stage", choices=stages, default=None,
        help="Run every stage from this one through the end (inclusive)",
    )


def add_common_args(parser: argparse.ArgumentParser) -> None:
    """Flags shared by ``build.py`` and ``extend.py``."""
    parser.add_argument("--resource", nargs="+", metavar="NAME", help="Restrict to specific resources")
    parser.add_argument("--dry-run", action="store_true", help="Build prompts without calling LLM")
    parser.add_argument("--implement-model", default=RunContext.implement_model, help="Model for entity implementation")
    parser.add_argument("--test-model", default=RunContext.test_model, help="Model for test_endpoints stage")
    parser.add_argument("--test-batch-size", type=int, default=RunContext.test_batch_size, help="Endpoints per LLM call in test_endpoints")
    parser.add_argument("--test-max-iterations", type=int, default=RunContext.test_max_iterations, help="Fix-and-retry budget per endpoint")
    parser.add_argument("--test-timeout", type=int, default=RunContext.test_timeout, help="Per-batch claude -p timeout in seconds")
    parser.add_argument("--force-retest", action="store_true", help="Test endpoints already marked tested=true (regression sweep)")


def slice_stages(args: argparse.Namespace, stages: list[str]) -> list[str]:
    """Resolve ``--stage`` / ``--up-to-stage`` / ``--from-stage`` to a subset.

    No flag → full ``stages`` list. Mutual exclusion is enforced by
    ``add_stage_args``'s argparse group, so at most one of the three
    is set.
    """
    if args.up_to_stage:
        return stages[: stages.index(args.up_to_stage) + 1]
    if args.from_stage:
        return stages[stages.index(args.from_stage):]
    if args.stage:
        return [args.stage]
    return list(stages)


def build_run_context(args: argparse.Namespace, **extras: Any) -> RunContext:
    """Build a ``RunContext`` from the common args + per-entrypoint extras.

    ``extras`` covers the entrypoint-specific options that don't appear
    in ``add_common_args`` — e.g. ``configure_model`` (build.py only),
    ``all_endpoints_per_resource`` (build.py only).
    """
    return RunContext(
        config_path=args.config,
        dry_run=args.dry_run,
        only_resources=args.resource,
        implement_model=args.implement_model,
        test_model=args.test_model,
        test_batch_size=args.test_batch_size,
        test_max_iterations=args.test_max_iterations,
        test_force_retest=args.force_retest,
        test_timeout=args.test_timeout,
        **extras,
    )


def dispatch_stages(
    stage_runners: dict[str, Callable[[RunContext], None]],
    selected: list[str],
    ctx: RunContext,
) -> None:
    """Invoke each selected stage in canonical order against ``ctx``.

    The canonical order is the dict's key insertion order — Python 3.7+
    dicts preserve it. ``selected`` is filtered to its intersection with
    the dispatch table, so passing a subset never re-runs unrelated
    stages.
    """
    unknown = [stage for stage in selected if stage not in stage_runners]
    if unknown:
        raise ValueError(f"Unknown stage(s): {unknown}. Valid: {list(stage_runners)}")
    for stage in stage_runners:
        if stage in selected:
            stage_runners[stage](ctx)
