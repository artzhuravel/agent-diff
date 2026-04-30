"""Stage 1: Mechanical reference extraction from OpenAPI specs."""

from replica_pipeline.extraction.endpoint_references import (
    EndpointReferences,
    Reference,
    find_body_references,
    find_endpoint_references,
    find_parameter_references,
    find_property_references,
    find_url_segment_references,
)
from replica_pipeline.extraction.reference_groups import ReferenceEvidence, group_references_by_pair
from replica_pipeline.extraction.schema_bindings import build_schema_bindings
