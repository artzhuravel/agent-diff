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
    return (
        f"Read the file `{responses_path.resolve()}`. It contains the "
        f"response definitions referenced by the resources being "
        f"implemented from the {app_name} API spec, along with "
        f"their referenced schemas.\n\n"
        f"Implement the standard HTTP error response handlers in "
        f"`{target_dir}/core/errors.py`. For each standard error "
        f"response (400 Bad Request, 401 Unauthorized, 403 Forbidden, "
        f"404 Not Found, 500 Internal Server Error, etc.), create a "
        f"constructor function that returns the correct response shape "
        f"matching the schemas in the file.\n\n"
        f"Skip domain-specific or resource-specific responses — only "
        f"implement responses that represent standard HTTP error patterns "
        f"reusable across the endpoints being implemented.\n\n"
        f"Read the existing `{target_dir}/core/errors.py` first "
        f"and preserve any code already there."
    )
