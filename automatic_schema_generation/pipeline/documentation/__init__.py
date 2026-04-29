"""Stage 2: Structured documentation output (endpoints.json, resources.json)."""

from pipeline.documentation.builder import (
    classify_responses,
    generate_endpoints_document,
    generate_resources_document,
    write_endpoints_document,
    write_resources_document,
)
