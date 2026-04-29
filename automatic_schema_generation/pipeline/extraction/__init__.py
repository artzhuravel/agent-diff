"""Stage 1: Mechanical reference extraction from OpenAPI specs."""

from pipeline.extraction.endpoint_references import (
    BodyReference,
    EndpointReferences,
    ParameterReference,
    PathReference,
    PropertyReference,
    find_body_references,
    find_endpoint_references,
    find_parameter_references,
    find_path_references,
    find_property_references,
)
from pipeline.extraction.reference_groups import ReferenceEvidence, group_references_by_pair
from pipeline.extraction.schema_bindings import build_schema_bindings
