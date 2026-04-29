"""``seed_template`` stage — drop & reseed the postgres template.

Required after ``implement`` regenerates ``database/schema.py``: the
old template schema is shaped against the previous tables, so cloning
a runtime environment from it would mismatch the new ORM models. We
also touch ``platform/api/main.py`` so uvicorn ``--reload`` re-imports
``REST_REPLICAS`` and mounts any newly-registered replica routes.

Docker-compose access is encapsulated by a few small helpers at the
top of this file. They were broken out into a separate module
historically; folded back in here because nothing else needs them.
"""

from __future__ import annotations

import os
import subprocess
from pathlib import Path

from pipeline.config import load_config

# ops/docker-compose.yml relative to this file:
# pipeline/testing/seed.py → repo root via four parents.
_COMPOSE_FILE = Path(__file__).parent.parent.parent.parent / "ops" / "docker-compose.yml"

# Defaults match ops/docker-compose.yml. Override via env so a user
# pointing at an external db (e.g. Neon) doesn't hit a hardcoded
# local password.
_POSTGRES_USER = os.environ.get("PIPELINE_POSTGRES_USER", "postgres")
_POSTGRES_DB = os.environ.get("PIPELINE_POSTGRES_DB", "diff_the_universe")
_BACKEND_SERVICE = os.environ.get("PIPELINE_BACKEND_SERVICE", "backend")
_POSTGRES_SERVICE = os.environ.get("PIPELINE_POSTGRES_SERVICE", "postgres")


def _compose_exec(service: str, *argv: str) -> list[str]:
    """Build a ``docker compose exec -T <service> <argv...>`` command list."""
    return [
        "docker", "compose", "-f", str(_COMPOSE_FILE),
        "exec", "-T", service,
        *argv,
    ]


def _run_psql(sql: str) -> subprocess.CompletedProcess[str]:
    """Run a single SQL statement against the platform postgres container."""
    command = _compose_exec(
        _POSTGRES_SERVICE,
        "psql", "-U", _POSTGRES_USER, "-d", _POSTGRES_DB,
        "-c", sql,
    )
    return subprocess.run(command, capture_output=True, text=True)


def _run_backend(*argv: str) -> subprocess.CompletedProcess[str]:
    """Run a command inside the backend container and capture output."""
    command = _compose_exec(_BACKEND_SERVICE, *argv)
    return subprocess.run(command, capture_output=True, text=True)


def run_seed_template(ctx) -> None:
    """Drop ``<slug>_base`` postgres schema, run the seed command, reload uvicorn."""
    config = load_config(ctx.config_path)
    print(f"\n=== SEED TEMPLATE — drop & reseed {config.app_slug}_base ===")

    if ctx.dry_run:
        print(f"  [dry-run] Would drop {config.app_slug}_base, reseed, and restart backend")
        return
    if not _COMPOSE_FILE.exists():
        print(f"  [skip] docker-compose.yml not found at {_COMPOSE_FILE}")
        return

    drop_result = _run_psql(
        f"DROP SCHEMA IF EXISTS {config.app_slug}_base CASCADE;"
    )
    if drop_result.returncode != 0:
        print(f"  [warn] drop schema failed: {drop_result.stderr.strip()[:300]}")
    else:
        print(f"  Dropped schema {config.app_slug}_base")

    seed_result = _run_backend(
        "python", "utils/seed_template.py", "--app", config.app_slug,
    )
    if seed_result.returncode != 0:
        print(f"  [error] seed failed (rc={seed_result.returncode})")
        print(f"    stdout: {seed_result.stdout.strip()[:500]}")
        print(f"    stderr: {seed_result.stderr.strip()[:500]}")
    else:
        tail_lines = [line for line in seed_result.stdout.split("\n") if line.strip()][-6:]
        for line in tail_lines:
            print(f"    {line}")

    _run_backend("touch", "/app/src/platform/api/main.py")
    print(f"  Triggered uvicorn reload")
