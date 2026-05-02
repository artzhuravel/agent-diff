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

from .utils.text import IDENTIFIER_PATTERN, canonical_forms, normalize_identifier


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
    """Closed-world resource definitions, split across two tiers.

    Two tier-specific tables back the resolution logic the rest of the
    pipeline uses:

    * ``name_variants_lookup`` — schema/entity-name forms only. **Strict,
      cross-resource unique.** Drives URL-subject inference (Group A
      walks and the rightmost-alias rule in ``find_endpoint_references``).
      The strictness is what protects endpoint-to-resource assignment:
      a single URL token always resolves to a single resource.
    * ``property_aliases_by_resource`` — role-word / field-name aliases.
      **May overlap across resources** (Path B). The same alias can be a
      property_alias of multiple resources because the same field name
      can mean different things in different schemas (e.g. ``insert_after``
      points at sections in ``SectionRequest`` but at tasks in
      ``SectionTaskInsertRequest``). Resolution is contextual — see
      ``resolve_with_context``.

    Mixed-tier collisions (alias is name_variant of A and
    property_alias of B for any A != B) are still rejected at load time:
    a name_variant is a strict global claim, and another resource
    can't simultaneously claim the same token as a property-level
    alias.

    Two convenience views are also provided for callers that don't
    need contextual resolution:

    * ``aliases_lookup`` — name_variants ∪ property_aliases that have
      exactly one owner. Multi-owner property_aliases are excluded
      (their resolution requires context). Useful for token-match
      style scans (e.g. the alias suggester).
    * ``aliases_by_resource`` — per-resource union of name_variants and
      property_aliases. Useful for displays / cross-references where
      tier doesn't matter.

    PK suffixes (``_id``, ``_gid``, ``_node_id``) are expanded at load
    time on whichever tier each base alias lives in: ``user`` (a name
    variant) yields ``user``, ``user_id``, ``user_gid`` in
    ``name_variants_by_resource``; ``assignee`` (a property alias)
    yields the same forms in ``property_aliases_by_resource``.
    """

    name_variants_lookup: Mapping[str, str]
    name_variants_by_resource: Mapping[str, frozenset[str]]
    property_aliases_by_resource: Mapping[str, frozenset[str]]
    aliases_lookup: Mapping[str, str]
    aliases_by_resource: Mapping[str, frozenset[str]]
    primary_keys_lookup: Mapping[str, str]

    def resolve_with_context(
        self,
        alias: str,
        context_resource: str | None,
    ) -> str | None:
        """Path B contextual resolver — name_variants strict, property aliases contextual.

        Resolution order:

        1. ``name_variants_lookup`` is consulted first; a strict hit
           wins immediately because name_variants are globally unique.
        2. If ``context_resource`` is provided and that resource claims
           the alias as a ``property_alias``, it wins. This is how
           overlapping property_aliases are disambiguated — the schema
           being walked supplies the context, not the lookup.
        3. As a context-free fallback, if exactly **one** resource
           claims the alias via ``property_aliases``, it wins. Multi-
           owner aliases without context resolve to ``None`` (caller
           must drop the reference rather than guess).
        """
        nv = self.name_variants_lookup.get(alias)
        if nv is not None:
            return nv
        if context_resource is not None:
            if alias in self.property_aliases_by_resource.get(context_resource, frozenset()):
                return context_resource
        owners = [
            resource
            for resource, aliases in self.property_aliases_by_resource.items()
            if alias in aliases
        ]
        if len(owners) == 1:
            return owners[0]
        return None


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

    name_variants_lookup: dict[str, str] = {}
    name_variants_by_resource: dict[str, frozenset[str]] = {}
    property_aliases_by_resource: dict[str, frozenset[str]] = {}
    primary_keys_lookup: dict[str, str] = {}
    legacy_alias_resources: list[str] = []

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

        # Read tier-specific fields and the legacy single-tier ``aliases:``.
        # The two are mutually exclusive: mixing them is ambiguous and the
        # loader rejects it loudly so the user picks one.
        legacy_aliases_raw = resource_raw.get("aliases")
        name_variants_raw = resource_raw.get("name_variants")
        property_aliases_raw = resource_raw.get("property_aliases")

        if legacy_aliases_raw is not None and (
            name_variants_raw is not None or property_aliases_raw is not None
        ):
            raise ValueError(
                f"app_config 'resources.{canonical}': cannot mix legacy "
                f"'aliases:' with 'name_variants:' / 'property_aliases:'. "
                f"Pick one form — either the legacy single bag or the new "
                f"two-tier split."
            )

        if legacy_aliases_raw is not None:
            # Legacy mode: every entry is treated as URL-eligible. This
            # preserves pre-#3 behavior verbatim, including the bias toward
            # over-attribution that motivated the split.
            name_variants_input = legacy_aliases_raw
            property_aliases_input: list[str] = []
            legacy_alias_resources.append(canonical)
        else:
            name_variants_input = name_variants_raw or []
            property_aliases_input = property_aliases_raw or []

        if not isinstance(name_variants_input, list) or not all(
            isinstance(alias, str) for alias in name_variants_input
        ):
            field_name = "aliases" if legacy_aliases_raw is not None else "name_variants"
            raise ValueError(
                f"app_config 'resources.{canonical}.{field_name}' must be "
                f"a list of strings"
            )
        if not isinstance(property_aliases_input, list) or not all(
            isinstance(alias, str) for alias in property_aliases_input
        ):
            raise ValueError(
                f"app_config 'resources.{canonical}.property_aliases' must "
                f"be a list of strings"
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

        # Build the two base sets. The canonical's singular AND plural
        # forms are seeded into name_variants automatically — both
        # because URL inference needs them (``user_gid`` resolves only
        # when ``user`` is in name_variants) AND because the
        # per-resource configure prompt's "Existing setup" section
        # reflects this state. Showing the LLM ``[user, users, ...]``
        # already classified prevents it from re-classifying ``user``
        # as a property_alias on subsequent runs. Property aliases that
        # duplicate a name variant are silently coalesced into the
        # name_variants tier — the broader privilege wins.
        name_variants_base: set[str] = set(canonical_forms(canonical))
        for alias in name_variants_input:
            normalized = normalize_identifier(alias)
            if not normalized:
                field_name = "aliases" if legacy_aliases_raw is not None else "name_variants"
                raise ValueError(
                    f"app_config 'resources.{canonical}.{field_name}' "
                    f"contains {alias!r}, which normalizes to an empty "
                    f"string — aliases must contain at least one letter"
                )
            name_variants_base.add(normalized)

        property_aliases_base: set[str] = set()
        for alias in property_aliases_input:
            normalized = normalize_identifier(alias)
            if not normalized:
                raise ValueError(
                    f"app_config 'resources.{canonical}.property_aliases' "
                    f"contains {alias!r}, which normalizes to an empty "
                    f"string — aliases must contain at least one letter"
                )
            property_aliases_base.add(normalized)
        property_aliases_base -= name_variants_base

        # Expand aliases with PK suffixes: user → user, user_id, user_node_id.
        # Expansion runs on each tier independently so that, e.g., the
        # PK-suffixed form of a property alias (``assignee_id``) also
        # resolves to the right resource without leaking into URL-subject
        # inference (which only consults ``name_variants_*``).
        pk_names: set[str] = set(naming.pk_field_names)
        pk_names.update(naming.self_id_fields)
        pk_names.add(primary_key)

        def _expand_with_pk(base_set: set[str]) -> set[str]:
            expanded = set(base_set)
            for alias in base_set:
                if any(alias.endswith(f"_{pk_name}") for pk_name in pk_names):
                    continue
                for pk_name in pk_names:
                    expanded.add(f"{alias}_{pk_name}")
            return expanded

        name_variants_expanded = _expand_with_pk(name_variants_base)
        property_aliases_expanded = _expand_with_pk(property_aliases_base)

        # Tier-aware collision check.
        #
        # Name_variants are GLOBALLY strict: a single URL token may not
        # resolve to two resources, otherwise endpoint subject inference
        # becomes non-deterministic. We enforce that here as we go.
        for alias in name_variants_expanded:
            previous = name_variants_lookup.get(alias)
            if previous is not None and previous != canonical:
                raise ValueError(
                    f"name_variant {alias!r} declared in both "
                    f"'resources.{previous}.name_variants' and "
                    f"'resources.{canonical}.name_variants' — entity-name "
                    f"forms must point at exactly one resource"
                )
            name_variants_lookup[alias] = canonical

        # Property_aliases are PER-RESOURCE: the same field name can mean
        # different things in different schemas (Path B). Cross-resource
        # overlap is allowed; resolution at walk time uses the schema's
        # binding as context. The mixed-tier check (alias declared as
        # name_variant of A and property_alias of B for any A != B) runs
        # in a deferred pass after all resources have been processed,
        # because we need the full ``name_variants_lookup`` to perform it.
        property_aliases_by_resource[canonical] = frozenset(property_aliases_expanded)

        name_variants_by_resource[canonical] = frozenset(name_variants_expanded)
        primary_keys_lookup[canonical] = primary_key

    # Deferred mixed-tier check. A property_alias of resource R must not
    # collide with a name_variant of a *different* resource: a name_variant
    # is a strict global claim that the alias *names* an entity, and another
    # resource can't simultaneously claim the same alias as a property-level
    # role-word reference.
    for canonical, property_aliases in property_aliases_by_resource.items():
        for alias in property_aliases:
            nv_owner = name_variants_lookup.get(alias)
            if nv_owner is not None and nv_owner != canonical:
                raise ValueError(
                    f"alias {alias!r} declared as a property_alias of "
                    f"'resources.{canonical}' AND a name_variant of "
                    f"'resources.{nv_owner}' — name_variants are global "
                    f"entity-name claims; another resource cannot use the "
                    f"same alias as a property-level reference"
                )

    if legacy_alias_resources:
        # One-shot stderr notice — this isn't a hard error and we don't want
        # to depend on Python's warnings filter behaving sanely under CLI.
        import sys
        print(
            f"[config] DEPRECATION: resources {legacy_alias_resources} use "
            f"the legacy 'aliases:' field; migrate to 'name_variants:' + "
            f"'property_aliases:' to take advantage of stricter URL-subject "
            f"inference. The legacy field continues to work for now.",
            file=sys.stderr,
        )

    # Build the legacy union views from the tier-specific tables. These
    # exist for callers that don't need contextual resolution (alias
    # suggesters, displays, audit code). Multi-owner property_aliases
    # are excluded from ``aliases_lookup`` because they have no single
    # answer without context — those callers should use
    # ``resolve_with_context`` directly.
    aliases_lookup: dict[str, str] = dict(name_variants_lookup)
    property_alias_owners: dict[str, set[str]] = {}
    for resource, aliases in property_aliases_by_resource.items():
        for alias in aliases:
            property_alias_owners.setdefault(alias, set()).add(resource)
    for alias, owners in property_alias_owners.items():
        if alias in aliases_lookup:
            # name_variant already claimed this alias — name_variants always
            # win in the legacy union view.
            continue
        if len(owners) == 1:
            aliases_lookup[alias] = next(iter(owners))

    aliases_by_resource: dict[str, frozenset[str]] = {
        resource: name_variants_by_resource.get(resource, frozenset())
        | property_aliases_by_resource.get(resource, frozenset())
        for resource in name_variants_by_resource
    }

    resources = ResourcesConfig(
        name_variants_lookup=MappingProxyType(name_variants_lookup),
        name_variants_by_resource=MappingProxyType(name_variants_by_resource),
        property_aliases_by_resource=MappingProxyType(property_aliases_by_resource),
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

