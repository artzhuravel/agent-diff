"""``extract`` stage — walk the spec, emit endpoints + resources docs.

Two outputs land in ``pipeline_out/``:

  * ``endpoints.json`` — every endpoint with parameters, body, responses.
  * ``resources.json`` — endpoints grouped by canonical resource, with
    bound-schema lists and outgoing/incoming reference maps.

The component-level response slice that ``implement_responses`` needs
(formerly ``responses.json``) is computed lazily inside that stage —
it has only one consumer and doesn't need to live as its own artifact.
"""

from __future__ import annotations

import json

from replica_pipeline.config import load_config
from replica_pipeline.documentation.builder import (
    generate_endpoints_document,
    generate_resources_document,
)
from replica_pipeline.extraction.schema_bindings import build_schema_bindings


def run_extract(ctx) -> None:
    """``extract`` stage — generate endpoints + resources docs."""
    config = load_config(ctx.config_path)
    spec = config.load_spec()

    print("\n=== EXTRACT — reference extraction + documentation ===")
    endpoints_doc = generate_endpoints_document(spec, config)
    resources_doc = generate_resources_document(spec, config, endpoints_doc)

    output_dir = ctx.output_dir
    output_dir.mkdir(parents=True, exist_ok=True)
    (output_dir / "endpoints.json").write_text(json.dumps(endpoints_doc, indent=2))
    (output_dir / "resources.json").write_text(json.dumps(resources_doc, indent=2))

    bindings = build_schema_bindings(spec, config)
    endpoint_count = len(endpoints_doc.get("endpoints", {}))
    print(
        f"  {endpoint_count} endpoints, {len(bindings)} schema bindings"
    )
    print(f"  Wrote endpoints.json + resources.json to {output_dir}")
