"""Config loader — reads app.yaml into a validated PipelineConfig.

Also provides ``auto_configure_resources`` which calls an LLM to
populate aliases and primary keys from the OpenAPI spec.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field
from pathlib import Path
from types import MappingProxyType
from typing import Any

import yaml

from ._text import IDENTIFIER_PATTERN, normalize_identifier


# ---------------------------------------------------------------------------
# Constants + defaults
# ---------------------------------------------------------------------------


_DEFAULT_PRIMARY_KEY: str = "id"

_DEFAULT_QUALIFIER_PREFIXES: tuple[str, ...] = ("parent_",)
_DEFAULT_SELF_ID_FIELDS: tuple[str, ...] = ("id",)
_DEFAULT_PK_FIELD_NAMES: tuple[str, ...] = ("id",)


# ---------------------------------------------------------------------------
# Dataclass hierarchy
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class ResourcesConfig:
    """Closed-world resource definitions.

    ``aliases_lookup``: alias → canonical (reverse map for O(1) token resolution).
    ``aliases_by_resource``: canonical → frozenset of expanded aliases.
    ``primary_keys_lookup``: canonical → PK column name.

    Each alias is expanded with PK field names at load time so ``user``
    yields ``user``, ``user_id``, ``user_node_id`` in the lookup.
    """

    aliases_lookup: Mapping[str, str]
    aliases_by_resource: Mapping[str, frozenset[str]]
    primary_keys_lookup: Mapping[str, str]


@dataclass(frozen=True)
class NamingConfig:
    """Global naming rules applied uniformly across all resources."""

    qualifier_prefixes: tuple[str, ...] = field(
        default_factory=lambda: tuple(_DEFAULT_QUALIFIER_PREFIXES)
    )
    self_id_fields: tuple[str, ...] = field(
        default_factory=lambda: tuple(_DEFAULT_SELF_ID_FIELDS)
    )
    pk_field_names: tuple[str, ...] = field(
        default_factory=lambda: tuple(_DEFAULT_PK_FIELD_NAMES)
    )


@dataclass(frozen=True)
class PipelineConfig:
    """Top-level config for a single pipeline run."""

    app_slug: str
    app_name: str
    openapi_path: Path
    target_dir: Path
    resources: ResourcesConfig
    naming: NamingConfig
    config_path: Path
    # Optional ``"METHOD /path"`` strings; the implement stage emits
    # handlers only for these. Empty tuple = default endpoint-centric
    # mode (the implement stage will refuse to run unless
    # --all-endpoints-per-resource is also set).
    selected_endpoints: tuple[str, ...] = ()

    def load_spec(self) -> dict:
        """Read and parse the OpenAPI spec JSON pointed at by ``openapi_path``."""
        import json
        with open(self.openapi_path) as handle:
            return json.load(handle)


# ---------------------------------------------------------------------------
# Loader
# ---------------------------------------------------------------------------


def load_config(config_path: Path) -> PipelineConfig:
    """Parse a per-app yaml into a ``PipelineConfig``.
    """
    config_path = config_path.resolve()
    if not config_path.exists():
        raise FileNotFoundError(f"app_config not found: {config_path}")

    with open(config_path) as handle:
        raw = yaml.safe_load(handle) or {}
    if not isinstance(raw, dict):
        raise ValueError(
            f"app_config must be a YAML mapping at top level, "
            f"got {type(raw).__name__}"
        )

    config_dir = config_path.parent

    # Required top-level fields.
    app_slug = _require_string(raw, "app_slug")
    app_name = _require_string(raw, "app_name")
    openapi_relative = _require_string(raw, "openapi_path")
    target_relative = _require_string(raw, "target_dir")

    openapi_path = (config_dir / openapi_relative).resolve()
    if not openapi_path.exists():
        raise FileNotFoundError(f"OpenAPI spec not found: {openapi_path}")
    target_dir = (config_dir / target_relative).resolve()

    # Naming — parsed before resources so alias expansion can use pk_field_names.
    naming_raw = raw.get("naming") or {}
    if not isinstance(naming_raw, dict):
        raise ValueError(
            f"app_config 'naming' must be a mapping, "
            f"got {type(naming_raw).__name__}"
        )
    naming = NamingConfig(
        qualifier_prefixes=_as_string_tuple(
            naming_raw, "naming.qualifier_prefixes", _DEFAULT_QUALIFIER_PREFIXES
        ),
        self_id_fields=_as_string_tuple(
            naming_raw, "naming.self_id_fields", _DEFAULT_SELF_ID_FIELDS
        ),
        pk_field_names=_as_string_tuple(
            naming_raw, "naming.pk_field_names", _DEFAULT_PK_FIELD_NAMES
        )
    )

    resources_raw = raw.get("resources")
    if not isinstance(resources_raw, dict) or not resources_raw:
        raise ValueError(
            "app_config 'resources' must be a non-empty mapping of "
            "canonical_name → {aliases, ...}"
        )

    aliases_lookup: dict[str, str] = {}
    aliases_by_resource: dict[str, frozenset[str]] = {}
    primary_keys_lookup: dict[str, str] = {}

    for canonical, resource_raw in resources_raw.items():
        if not isinstance(canonical, str) or not canonical:
            raise ValueError(
                f"app_config 'resources' key must be a non-empty string, "
                f"got {canonical!r}"
            )
        # Resource keys become table names — must be strict snake_case.
        if not IDENTIFIER_PATTERN.fullmatch(canonical):
            raise ValueError(
                f"app_config 'resources' key {canonical!r} must be a "
                f"snake_case identifier (lowercase letters, digits, and "
                f"underscores only, starting with a letter) — e.g. "
                f"``pull_request`` instead of ``PullRequest`` / "
                f"``pull-request`` / ``pullRequest``"
            )
        if not isinstance(resource_raw, dict):
            raise ValueError(
                f"app_config 'resources.{canonical}' must be a mapping, "
                f"got {type(resource_raw).__name__}"
            )

        aliases_raw = resource_raw.get("aliases") or []
        if not isinstance(aliases_raw, list) or not all(
            isinstance(alias, str) for alias in aliases_raw
        ):
            raise ValueError(
                f"app_config 'resources.{canonical}.aliases' must be a "
                f"list of strings"
            )

        default_primary_key = (
            naming.pk_field_names[0]
            if naming.pk_field_names
            else _DEFAULT_PRIMARY_KEY
        )
        primary_key = resource_raw.get("primary_key", default_primary_key)
        if not isinstance(primary_key, str) or not primary_key:
            raise ValueError(
                f"app_config 'resources.{canonical}.primary_key' must be a "
                f"non-empty string, got {primary_key!r}"
            )

        base_aliases: set[str] = {canonical}
        for alias in aliases_raw:
            normalized = normalize_identifier(alias)
            if not normalized:
                raise ValueError(
                    f"app_config 'resources.{canonical}.aliases' "
                    f"contains {alias!r}, which normalizes to an empty "
                    f"string — aliases must contain at least one letter"
                )
            base_aliases.add(normalized)

        # Expand aliases with PK suffixes: user → user, user_id, user_node_id
        pk_names: set[str] = set(naming.pk_field_names)
        pk_names.update(naming.self_id_fields)
        pk_names.add(primary_key)
        aliases = set(base_aliases)
        for alias in base_aliases:
            if any(alias.endswith(f"_{pk_name}") for pk_name in pk_names):
                continue
            for pk_name in pk_names:
                aliases.add(f"{alias}_{pk_name}")

        for alias in aliases:
            previous = aliases_lookup.get(alias)
            if previous is not None and previous != canonical:
                raise ValueError(
                    f"alias {alias!r} appears in both 'resources.{previous}' "
                    f"and 'resources.{canonical}' — each alias must map to "
                    f"exactly one canonical resource"
                )
            aliases_lookup[alias] = canonical

        aliases_by_resource[canonical] = frozenset(aliases)
        primary_keys_lookup[canonical] = primary_key

    resources = ResourcesConfig(
        aliases_lookup=MappingProxyType(aliases_lookup),
        aliases_by_resource=MappingProxyType(aliases_by_resource),
        primary_keys_lookup=MappingProxyType(primary_keys_lookup),
    )

    selected_endpoints = _parse_selected_endpoints(raw.get("selected_endpoints"))

    return PipelineConfig(
        app_slug=app_slug,
        app_name=app_name,
        openapi_path=openapi_path,
        target_dir=target_dir,
        resources=resources,
        naming=naming,
        config_path=config_path,
        selected_endpoints=selected_endpoints,
    )


# ---------------------------------------------------------------------------
# Small validation helpers — shared between fields
# ---------------------------------------------------------------------------


def _require_string(raw: dict[str, Any], key: str) -> str:
    """Read a required top-level string field or raise with the field name."""
    value = raw.get(key)
    if not isinstance(value, str) or not value:
        raise ValueError(
            f"app_config '{key}' must be a non-empty string, got {value!r}"
        )
    return value


_VALID_HTTP_METHODS = frozenset({
    "GET", "POST", "PUT", "PATCH", "DELETE", "HEAD", "OPTIONS", "TRACE",
})


def _parse_selected_endpoints(raw: Any) -> tuple[str, ...]:
    """Validate the optional ``selected_endpoints`` list shape.

    Each entry must be ``"METHOD /path"`` (uppercase method, single
    space, leading slash). Empty / missing means "no selection" — the
    implement stage decides what to do with that.
    """
    if raw is None:
        return ()
    if not isinstance(raw, list):
        raise ValueError(
            f"app_config 'selected_endpoints' must be a list of "
            f"\"METHOD /path\" strings, got {type(raw).__name__}"
        )
    out: list[str] = []
    for entry in raw:
        if not isinstance(entry, str):
            raise ValueError(
                f"app_config 'selected_endpoints' entries must be strings, "
                f"got {type(entry).__name__}: {entry!r}"
            )
        parts = entry.strip().split(" ", 1)
        if len(parts) != 2 or parts[0] not in _VALID_HTTP_METHODS or not parts[1].startswith("/"):
            raise ValueError(
                f"app_config 'selected_endpoints' entry {entry!r} must be "
                f"\"METHOD /path\" (uppercase method, leading slash on path)"
            )
        # Normalise to single-space form
        out.append(f"{parts[0]} {parts[1]}")
    return tuple(out)


def _as_string_tuple(
    raw: dict[str, Any],
    field_path: str,
    default: tuple[str, ...],
) -> tuple[str, ...]:
    """Read an optional ``list[str]`` field into a tuple, fallback to default."""
    # ``field_path`` is the dotted path used in error messages; the
    # raw dict is the parent scope (``naming``/``vocabulary``/...).
    key = field_path.split(".")[-1]
    value = raw.get(key)
    if value is None:
        return default
    if not isinstance(value, (list, tuple)) or not all(
        isinstance(entry, str) for entry in value
    ):
        raise ValueError(
            f"app_config '{field_path}' must be a list of strings, "
            f"got {type(value).__name__}"
        )
    return tuple(value)

