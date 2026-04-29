"""``extract`` stage — walk the spec, emit endpoints + resources + responses.

Three outputs land in ``pipeline_out/``:

  * ``endpoints.json`` — every endpoint with parameters, body, responses.
  * ``resources.json`` — endpoints grouped by canonical resource, with
    bound-schema lists and outgoing/incoming reference maps.
  * ``responses.json`` — every component-level response referenced by a
    scoped endpoint, plus the schemas those responses ``$ref``.
"""

from __future__ import annotations

import copy
import json
from pathlib import Path
from typing import Any

from pipeline.config import load_config
from pipeline.documentation.builder import (
    generate_endpoints_document,
    generate_resources_document,
)
from pipeline.extraction.schema_bindings import build_schema_bindings


def run_extract(ctx) -> None:
    """``extract`` stage — generate endpoints/resources/responses docs."""
    config = load_config(ctx.config_path)
    spec = config.load_spec()

    print("\n=== EXTRACT — reference extraction + documentation ===")
    endpoints_doc = generate_endpoints_document(spec, config)
    resources_doc = generate_resources_document(spec, config, endpoints_doc)

    output_dir = ctx.output_dir
    output_dir.mkdir(parents=True, exist_ok=True)
    (output_dir / "endpoints.json").write_text(json.dumps(endpoints_doc, indent=2))
    (output_dir / "resources.json").write_text(json.dumps(resources_doc, indent=2))

    responses_doc = _extract_responses(spec, resources_doc)
    (output_dir / "responses.json").write_text(json.dumps(responses_doc, indent=2))

    bindings = build_schema_bindings(spec, config)
    endpoint_count = len(endpoints_doc.get("endpoints", {}))
    response_count = len(responses_doc.get("responses", {}))
    print(
        f"  {endpoint_count} endpoints, {len(bindings)} schema bindings, "
        f"{response_count} component responses"
    )
    print(f"  Wrote endpoints.json + resources.json + responses.json to {output_dir}")


def _extract_responses(spec: dict, resources_doc: dict) -> dict:
    """Extract components/responses referenced by scoped resource endpoints."""
    component_responses = (spec.get("components") or {}).get("responses") or {}
    component_schemas = (spec.get("components") or {}).get("schemas") or {}

    # Endpoints in resources_doc are dereferenced; match the raw spec paths
    # back to scoped operation keys to discover which component responses
    # those endpoints actually use.
    scoped_endpoints: set[str] = set()
    for resource in (resources_doc.get("resources") or {}).values():
        scoped_endpoints.update(resource.get("endpoint_keys") or [])

    scoped_response_names: set[str] = set()
    for path, path_item in (spec.get("paths") or {}).items():
        for method, operation in path_item.items():
            key = f"{method.upper()} {path}"
            if key not in scoped_endpoints:
                continue
            for _code, resp in (operation.get("responses") or {}).items():
                ref = resp.get("$ref", "")
                if ref.startswith("#/components/responses/"):
                    scoped_response_names.add(ref.split("/")[-1])

    responses: dict[str, Any] = {}
    referenced_schemas: dict[str, Any] = {}

    for name in sorted(scoped_response_names):
        body = component_responses.get(name)
        if body is None:
            continue
        responses[name] = copy.deepcopy(body)
        content = body.get("content") or {}
        for _media_type, media in content.items():
            schema = media.get("schema") or {}
            ref = schema.get("$ref")
            if isinstance(ref, str) and ref.startswith("#/components/schemas/"):
                schema_name = ref[len("#/components/schemas/"):]
                if schema_name in component_schemas:
                    referenced_schemas[schema_name] = copy.deepcopy(
                        component_schemas[schema_name]
                    )

    return {"responses": responses, "schemas": referenced_schemas}
