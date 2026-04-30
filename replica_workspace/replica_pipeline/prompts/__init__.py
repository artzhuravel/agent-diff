"""LLM prompt construction for every pipeline stage.

Each stage that drives an LLM has its prompts here, so anyone wanting
to inspect or edit prompt text knows exactly where to look:

* ``implement.py`` — Pass 1, Pass 2, and Extend prompts for the
  resource-implementation stage.
* ``implement_responses.py`` — short prompt for ``implement_responses``.
* ``test_endpoints.py`` — per-batch prompt for the ``test_endpoints``
  stage.
* ``configure.py`` — alias/PK auto-configuration prompt.
* ``review.py`` — alias-suggestion review prompt.

Markdown templates live in the sibling ``templates/`` directory.
Example pattern files used by the Pass 2 prompt live in ``mocks/``.
Stage runners import only ``build_*_prompt`` functions; everything
inside this package is prompt construction.
"""
