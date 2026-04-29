"""Cross-endpoint reference grouper.

Walks every operation in a spec via ``find_endpoint_references`` and
groups the resulting references into a map keyed by
``(source_resource, target_resource)``.

- **source** is the operation's inferred subject. When unresolved,
  evidence goes under the bucket key ``"_unresolved_"`` so those
  operations are visible without polluting real pairs.
- **target** is the canonical resource each walker resolved to.

Each evidence record pins the exact location (URL segment, query
parameter, body schema, property path, etc.) so the downstream LLM
handoff can cite specific hit sites instead of bulk counts. Local
multiplicity (scalar vs array) is deferred to a later step — the
walkers don't yet track it, so this grouper records evidence
without cardinality claims.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any

from pipeline.config import PipelineConfig
from pipeline.extraction.endpoint_references import find_endpoint_references

_HTTP_METHODS = frozenset({
    "get", "post", "put", "patch", "delete", "head", "options", "trace",
})
_UNRESOLVED = "_unresolved_"


@dataclass(frozen=True)
class ReferenceEvidence:
    method: str
    path: str
    kind: str       # "url_segment" | "path_parameter" | "query" | "header" | "cookie" | "body_request" | "body_response" | "property"
    location: str   # token / parameter name / property path / media+schema


def group_references_by_pair(
    spec: dict[str, Any],
    config: PipelineConfig,
    bindings: Mapping[str, str],
) -> dict[tuple[str, str], list[ReferenceEvidence]]:
    groups: dict[tuple[str, str], list[ReferenceEvidence]] = {}
    paths = spec.get("paths") or {}
    if not isinstance(paths, dict):
        return groups

    for path, path_item in paths.items():
        if not isinstance(path_item, dict):
            continue
        for method in _HTTP_METHODS:
            if not isinstance(path_item.get(method), dict):
                continue
            result = find_endpoint_references(method, path, spec, config, bindings)
            source = result.subject or _UNRESOLVED
            method_upper = method.upper()

            # All four walks produce the same ``Reference(resource, kind,
            # location)`` shape, so a single loop converts every per-endpoint
            # reference into the cross-endpoint evidence record.
            for reference in result.references:
                groups.setdefault((source, reference.resource), []).append(
                    ReferenceEvidence(method_upper, path, reference.kind, reference.location)
                )
    return groups
