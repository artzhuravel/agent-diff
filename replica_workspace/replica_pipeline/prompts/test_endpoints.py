"""Prompt construction for the ``test_endpoints`` stage.

Builds the markdown prompt handed to ``claude -p`` for each batch of
endpoints under test. The runner is responsible for batching, dispatch,
and result parsing — anything that shapes the LLM input lives here.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import yaml

from replica_pipeline.utils.refs import collect_refs, transitive_closure


_PROMPT_TEMPLATE = Path(__file__).parent / "templates" / "test_endpoints.md"


def build_test_prompt(
    *,
    app_name: str,
    app_slug: str,
    target_dir: Path,
    subject: str,
    batch_index: int,
    batch_total: int,
    endpoints: list[dict[str, Any]],
    endpoints_doc: dict[str, Any],
    replicas_yaml: Path,
    output_path: Path,
    max_iterations: int,
    repo_root: Path,
) -> str:
    """Render the per-batch test prompt by filling in the markdown template."""
    schemas = collect_schema_closure(endpoints, endpoints_doc)
    placeholders = {
        "APP_NAME": app_name,
        "APP_SLUG": app_slug,
        "SUBJECT": subject,
        "BATCH_INDEX": str(batch_index),
        "BATCH_TOTAL": str(batch_total),
        "ENDPOINT_COUNT": str(len(endpoints)),
        "TARGET_DIR_RELATIVE": _shorten_path(target_dir, repo_root),
        "MOUNT_SUFFIX_HINT": _mount_suffix_for_slug(replicas_yaml, app_slug),
        "ENDPOINTS_BLOCK": render_endpoints_block(endpoints, endpoints_doc),
        "SCHEMAS_JSON": json.dumps(schemas, indent=2),
        "OUTPUT_PATH": _shorten_path(output_path, repo_root),
        "MAX_ITERATIONS": str(max_iterations),
    }
    template = _PROMPT_TEMPLATE.read_text()
    for key, value in placeholders.items():
        template = template.replace(f"{{{{{key}}}}}", value)
    return template


def collect_schema_closure(
    endpoints: list[dict[str, Any]],
    endpoints_doc: dict[str, Any],
) -> dict[str, Any]:
    """Walk ``$ref`` chains starting from each endpoint's responses + body.

    Refs in ``endpoints.json`` use the ``#/schemas/<name>`` prefix
    (rewritten by the extraction stage), so we resolve against the
    top-level ``schemas`` block. Returns the transitive closure as a
    dict keyed by schema name. ``endpoints_doc`` is the spec catalog
    from extract; ``endpoints`` is the per-batch slice the caller wants
    schemas for.
    """
    schemas_block = endpoints_doc.get("schemas") or {}
    endpoints_block = endpoints_doc.get("endpoints") or {}
    ref_prefix = "#/schemas/"

    seeds: set[str] = set()
    for endpoint in endpoints:
        key = f"{endpoint['method']} {endpoint['path']}"
        meta = endpoints_block.get(key) or {}
        seeds.update(collect_refs(meta.get("responses"), ref_prefix))
        seeds.update(collect_refs(meta.get("request_body"), ref_prefix))
        seeds.update(collect_refs(meta.get("parameters"), ref_prefix))

    seen_refs = transitive_closure(seeds, schemas_block, ref_prefix)
    return {name: schemas_block[name] for name in sorted(seen_refs) if name in schemas_block}


def render_endpoints_block(
    endpoints: list[dict[str, Any]],
    endpoints_doc: dict[str, Any],
) -> str:
    """Format the per-endpoint section that goes into the prompt body.

    Includes parameters (path + required query) so the LLM knows what
    input each call needs, plus a one-line shape hint for the request
    body and each response code.
    """
    endpoints_block = endpoints_doc.get("endpoints") or {}
    out: list[str] = []
    for endpoint in endpoints:
        method = endpoint["method"]
        path = endpoint["path"]
        meta = endpoints_block.get(f"{method} {path}") or {}
        out.append(f"### {method} {path}")
        summary = endpoint.get("summary") or ""
        if summary and summary != endpoint.get("subject"):
            out.append(f"_{summary}_")
        if endpoint.get("needs_seed"):
            out.append("Needs a seeded row before this endpoint can be exercised.")

        # Parameters — separate path from query/header, mark required ones.
        parameters = meta.get("parameters") or []
        path_params: list[str] = []
        query_params: list[str] = []
        for parameter in parameters:
            if not isinstance(parameter, dict):
                continue
            name = parameter.get("name") or "?"
            location = parameter.get("in")
            required = parameter.get("required")
            schema_type = (parameter.get("schema") or {}).get("type", "string")
            tag = " (required)" if required else ""
            if location == "path":
                path_params.append(f"{name}: {schema_type}{tag}")
            elif location == "query":
                query_params.append(f"{name}: {schema_type}{tag}")
        if path_params:
            out.append(f"Path parameters: {', '.join(path_params)}")
        if query_params:
            out.append(f"Query parameters: {', '.join(query_params)}")

        request_body = meta.get("request_body")
        if isinstance(request_body, dict):
            content = request_body.get("content") or {}
            for media_type, media in content.items():
                schema = media.get("schema") or {}
                out.append(f"Request body ({media_type}): {_summarize_schema(schema)}")
                break

        responses = meta.get("responses") or {}
        if responses:
            out.append("Responses:")
            for status_code in sorted(responses, key=lambda code: str(code)):
                response = responses[status_code]
                content = (response.get("content") or {}).get("application/json") or {}
                schema = content.get("schema") or {}
                description = (response.get("description") or "").strip().splitlines()
                desc = description[0] if description else ""
                shape = _summarize_schema(schema) if schema else "no body"
                out.append(f"  - {status_code}: {shape} — {desc}")
        out.append("")
    return "\n".join(out)


def _summarize_schema(schema: dict[str, Any]) -> str:
    """Produce a one-line schema hint: ``$ref``, type, or inline JSON snippet."""
    ref = schema.get("$ref")
    if ref:
        return f"`{ref}`"
    schema_type = schema.get("type")
    if schema_type == "array":
        items = schema.get("items") or {}
        return f"array of {_summarize_schema(items)}"
    if schema.get("properties") or schema.get("oneOf") or schema.get("anyOf"):
        return f"inline: {json.dumps(schema, separators=(',', ':'))[:400]}"
    if schema_type:
        return str(schema_type)
    return "unspecified"


def _mount_suffix_for_slug(replicas_yaml: Path, app_slug: str) -> str:
    """Recover the optional path suffix (e.g. ``/api/v1``) from replicas.yaml."""
    if not replicas_yaml.exists():
        return ""
    raw = yaml.safe_load(replicas_yaml.read_text()) or {}
    for entry in raw.get("rest") or []:
        if entry.get("slug") != app_slug:
            continue
        mount_path = entry.get("mount_path", "")
        marker = f"/services/{app_slug}"
        if marker in mount_path:
            return mount_path.split(marker, 1)[1]
    return ""


def _shorten_path(path: Path, anchor: Path) -> str:
    """Render ``path`` relative to ``anchor`` if possible, else return its name."""
    try:
        return str(path.resolve().relative_to(anchor.resolve()))
    except ValueError:
        return path.name
