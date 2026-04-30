"""Thin wrapper around ``claude -p`` for pipeline LLM calls.

Returns a ``Callable[[str], str]`` so stage runners can hand the
review/configure/implement helpers a model-agnostic caller and stay
unaware of the underlying CLI.

The caller's ``ANTHROPIC_API_KEY`` is stripped from the subprocess
environment so the CLI uses subscription auth (no API key needed)
even when one is set on the host.

Model defaults live here as single-source constants. Bumping a default
is one edit; ``RunContext`` and the CLIs read these via env var with a
constant fallback so a future model upgrade doesn't require touching
every stage's defaults.
"""

from __future__ import annotations

import os
import subprocess
from collections.abc import Callable


# Default model for LLM calls. Override with the ``CLAUDE_PIPELINE_*``
# env vars or with the matching ``--*-model`` CLI flag.
DEFAULT_CONFIGURE_MODEL = os.environ.get("CLAUDE_PIPELINE_CONFIGURE_MODEL", "claude-sonnet-4-6")
DEFAULT_IMPLEMENT_MODEL = os.environ.get("CLAUDE_PIPELINE_IMPLEMENT_MODEL", "claude-opus-4-7")
DEFAULT_TEST_MODEL = os.environ.get("CLAUDE_PIPELINE_TEST_MODEL", "claude-opus-4-7")


def make_llm_call(
    *,
    model: str = DEFAULT_CONFIGURE_MODEL,
    timeout: int = 600,
) -> Callable[[str], str]:
    """Return a ``prompt → response`` callable backed by ``claude -p``."""

    def call(prompt: str) -> str:
        env = os.environ.copy()
        env.pop("ANTHROPIC_API_KEY", None)
        try:
            result = subprocess.run(
                ["claude", "-p", "--model", model],
                input=prompt,
                capture_output=True,
                text=True,
                env=env,
                timeout=timeout,
            )
        except FileNotFoundError:
            raise RuntimeError("claude CLI not found on PATH. Install Claude Code.")
        except subprocess.TimeoutExpired:
            raise RuntimeError(f"claude -p timed out after {timeout}s")
        if result.returncode != 0:
            raise RuntimeError(
                f"claude -p failed (exit {result.returncode}):\n"
                f"{result.stderr.strip()}"
            )
        return result.stdout.strip()

    return call
