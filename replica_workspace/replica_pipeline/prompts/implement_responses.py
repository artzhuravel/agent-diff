"""Prompt construction for the ``implement_responses`` stage.

The stage runner asks the LLM to implement standard HTTP error
constructors in ``core/errors.py`` based on the ``responses.json``
slice of the spec. The prompt itself is short and self-contained;
it lives here purely so every stage's prompt construction is in
``pipeline.prompts``.
"""

from __future__ import annotations

from pathlib import Path


def build_implement_responses_prompt(
    *,
    app_name: str,
    target_dir: Path,
    responses_path: Path,
) -> str:
    """Render the implement_responses prompt as a single string.

    ``responses_path`` is referenced by the prompt as the file the LLM
    should read; the caller must ensure it exists on disk before
    invoking ``claude -p``.
    """
    errors_path = f"{target_dir}/core/errors.py"
    return (
        f"Read the file `{responses_path.resolve()}`. It contains the response "
        f"definitions referenced by the resources being implemented from the "
        f"{app_name} API spec, along with the schemas those responses point "
        f"at.\n\n"
        f"Then read the existing `{errors_path}` so you preserve everything "
        f"already there and follow its return-type and import conventions.\n\n"
        f"Implement standard HTTP error constructors in `{errors_path}` — one "
        f"function per status code reachable from the responses file. Each "
        f"constructor takes a single `detail: str` argument and returns a "
        f"`starlette.responses.JSONResponse` shaped to match the spec's error "
        f"schema for that status code. Function names are the lowercase, "
        f"snake_case form of the status reason phrase.\n\n"
        f"Cover the standard codes likely to be reachable from the selected "
        f"endpoints: `bad_request` (400), `unauthorized` (401), `forbidden` "
        f"(403), `not_found` (404), `unprocessable_entity` (422), "
        f"`too_many_requests` (429), `internal_server_error` (500). Add others "
        f"only if the responses file references them. Skip domain-specific or "
        f"resource-specific responses — those belong in per-resource handlers, "
        f"not here.\n\n"
        f"Also include a generic `handle_exception(exc: Exception) -> "
        f"JSONResponse` that maps known internal exception types to the right "
        f"constructor and falls through to `internal_server_error` for "
        f"anything unexpected.\n\n"
        f"Each constructor should:\n"
        f"- Build a body matching the spec's error schema exactly (same field "
        f"names, same nesting — e.g. Asana wraps in `{{\"errors\": "
        f"[{{\"message\": ...}}]}}`).\n"
        f"- Set the HTTP status code via the `status_code` argument of "
        f"`JSONResponse`.\n"
        f"- Return the response object — handlers will `raise` or `return` it "
        f"depending on the framework convention already used in the file.\n\n"
        f"Use the Edit/Write tools to update the file. After editing, re-read "
        f"`{errors_path}` and verify each new constructor is callable as "
        f"`bad_request(\"some detail\")` and returns a `JSONResponse`. If you "
        f"cannot complete the work, end your response with the single line "
        f"`IMPLEMENTATION FAILED: <one-sentence reason>` so the orchestrator "
        f"can detect the failure."
    )
