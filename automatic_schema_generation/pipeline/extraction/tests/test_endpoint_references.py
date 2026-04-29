"""Tests for the per-endpoint reference aggregator."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import yaml

from pipeline.config import PipelineConfig, load_config
from pipeline.extraction.endpoint_references import (
    EndpointReferences,
    Reference,
    find_endpoint_references,
)


def _config(tmp_path: Path, resources: dict[str, Any]) -> PipelineConfig:
    spec_path = tmp_path / "spec.json"
    spec_path.write_text('{"paths": {}, "components": {"schemas": {}}}')
    cfg_path = tmp_path / "app.yaml"
    cfg_path.write_text(yaml.safe_dump({
        "app_slug": "test",
        "app_name": "Test",
        "openapi_path": "spec.json",
        "target_dir": "out",
        "resources": resources,
    }))
    return load_config(cfg_path)


def _by_kind(refs: list[Reference], *kinds: str) -> list[Reference]:
    """Filter a unified reference list by one or more ``kind`` discriminators."""
    return [reference for reference in refs if reference.kind in kinds]


def test_subject_inference_rightmost_alias(tmp_path: Path) -> None:
    config = _config(tmp_path, {
        "users": {"aliases": ["user", "owner"]},
        "repos": {"aliases": ["repo"]},
        "issues": {"aliases": ["issue"]},
    })
    spec = {
        "paths": {
            "/repos/{owner}/{repo}/issues/{issue_id}": {
                "get": {"responses": {"200": {"description": "ok"}}},
            },
        },
    }
    result = find_endpoint_references(
        "get", "/repos/{owner}/{repo}/issues/{issue_id}", spec, config, {}
    )
    assert result.subject == "issues"
    assert result.subject_source == "url_rightmost_alias"
    assert result.method == "GET"


def test_subject_inference_action_verb_fall_through(tmp_path: Path) -> None:
    """``lock`` isn't a resource — fall through to ``{issue_id}``."""
    config = _config(tmp_path, {
        "users": {"aliases": ["user", "owner"]},
        "repos": {"aliases": ["repo"]},
        "issues": {"aliases": ["issue"]},
    })
    spec = {
        "paths": {
            "/repos/{owner}/{repo}/issues/{issue_id}/lock": {
                "post": {"responses": {"200": {"description": "ok"}}},
            },
        },
    }
    result = find_endpoint_references(
        "post", "/repos/{owner}/{repo}/issues/{issue_id}/lock", spec, config, {}
    )
    assert result.subject == "issues"
    assert result.subject_source == "url_rightmost_alias"


def test_subject_inference_no_alias_hit(tmp_path: Path) -> None:
    """Utility endpoints with no resource words give ``subject = None``."""
    config = _config(tmp_path, {"users": {"aliases": ["user"]}})
    spec = {
        "paths": {
            "/rate_limit": {
                "get": {"responses": {"200": {"description": "ok"}}},
            },
        },
    }
    result = find_endpoint_references("get", "/rate_limit", spec, config, {})
    assert result.subject is None
    assert result.subject_source == "no_alias_in_url"


def test_path_and_parameter_references_populated(tmp_path: Path) -> None:
    config = _config(tmp_path, {
        "users": {"aliases": ["user"]},
        "repos": {"aliases": ["repo"]},
    })
    spec = {
        "paths": {
            "/repos/{repo}": {
                "get": {
                    "parameters": [
                        {"name": "user_id", "in": "query"},
                    ],
                    "responses": {"200": {"description": "ok"}},
                },
            },
        },
    }
    result = find_endpoint_references("get", "/repos/{repo}", spec, config, {})
    path_resources = {
        reference.resource
        for reference in _by_kind(result.references, "url_segment", "path_parameter")
    }
    assert path_resources == {"repos"}
    parameter_resources = {
        reference.resource
        for reference in _by_kind(result.references, "query", "header", "cookie")
    }
    assert parameter_resources == {"users"}
    assert result.subject == "repos"


def test_body_references_from_request_and_response(tmp_path: Path) -> None:
    config = _config(tmp_path, {
        "issues": {"aliases": ["issue"]},
        "users": {"aliases": ["user"]},
    })
    spec = {
        "paths": {
            "/issues": {
                "post": {
                    "requestBody": {
                        "content": {
                            "application/json": {
                                "schema": {"$ref": "#/components/schemas/IssueCreate"},
                            },
                        },
                    },
                    "responses": {
                        "201": {
                            "content": {
                                "application/json": {
                                    "schema": {"$ref": "#/components/schemas/Issue"},
                                },
                            },
                        },
                    },
                },
            },
        },
        "components": {"schemas": {}},
    }
    bindings = {"IssueCreate": "issues", "Issue": "issues"}
    result = find_endpoint_references("post", "/issues", spec, config, bindings)
    body_refs = _by_kind(result.references, "body_request", "body_response")
    kinds = {reference.kind for reference in body_refs}
    assert kinds == {"body_request", "body_response"}
    assert all(reference.resource == "issues" for reference in body_refs)


def test_property_references_walked_from_inline_body(tmp_path: Path) -> None:
    """Inline request body fields are picked up by the property-level walker."""
    config = _config(tmp_path, {"users": {"aliases": ["user"]}})
    spec = {
        "paths": {
            "/issues": {
                "post": {
                    "requestBody": {
                        "content": {
                            "application/json": {
                                "schema": {
                                    "type": "object",
                                    "properties": {
                                        "user_id": {"type": "integer"},
                                        "title": {"type": "string"},
                                    },
                                },
                            },
                        },
                    },
                    "responses": {"201": {"description": "created"}},
                },
            },
        },
    }
    result = find_endpoint_references("post", "/issues", spec, config, {})
    property_refs = _by_kind(result.references, "property")
    resources = {reference.resource for reference in property_refs}
    assert "users" in resources


def test_missing_operation_returns_empty_record(tmp_path: Path) -> None:
    config = _config(tmp_path, {"users": {"aliases": ["user"]}})
    result = find_endpoint_references("get", "/missing", {}, config, {})
    assert result.references == []
    assert result.subject is None
