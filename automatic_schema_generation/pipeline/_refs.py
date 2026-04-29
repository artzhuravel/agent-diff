"""Generic ``$ref`` walking helpers.

Multiple stages need to (a) collect every ``$ref`` value from an
arbitrary JSON-shaped node and (b) take a set of seed schema names and
follow the ``$ref`` chain transitively. The two stages that need this
historically reimplemented the same recursion (one as a method named
``_collect_refs``, the other as a nested ``harvest``) — this module is
the canonical implementation.

Vocabulary:
  - **prefix** — the leading substring that identifies refs we care
    about, e.g. ``"#/schemas/"`` for the dereferenced docs that the
    extraction stage emits, or ``"#/components/schemas/"`` for raw
    OpenAPI input.
  - **name** — the bit after the prefix; usually the canonical schema
    name like ``TaskCompact``.
"""

from __future__ import annotations

from typing import Any


def collect_refs(node: Any, prefix: str) -> set[str]:
    """Return every ``$ref`` name found under ``node`` (recursive).

    Walks dicts and lists. A name is the substring of the ``$ref``
    value after ``prefix`` — refs that don't start with ``prefix`` are
    ignored.
    """
    out: set[str] = set()
    _collect_into(node, prefix, out)
    return out


def _collect_into(node: Any, prefix: str, out: set[str]) -> None:
    if isinstance(node, dict):
        ref = node.get("$ref")
        if isinstance(ref, str) and ref.startswith(prefix):
            out.add(ref[len(prefix):])
        for value in node.values():
            _collect_into(value, prefix, out)
    elif isinstance(node, list):
        for item in node:
            _collect_into(item, prefix, out)


def transitive_closure(
    seeds: set[str],
    schemas: dict[str, Any],
    prefix: str,
    *,
    exclude: set[str] | None = None,
) -> set[str]:
    """Expand ``seeds`` to every schema name reachable via ``$ref``.

    For each seed, look up its body in ``schemas`` and walk the refs;
    add new names to the frontier; repeat until exhausted. Names in
    ``exclude`` are treated as boundaries — neither emitted in the
    result nor recursed into.
    """
    excluded = exclude or set()
    visited: set[str] = set()
    frontier = set(seeds) - excluded

    while frontier:
        name = frontier.pop()
        if name in visited or name in excluded:
            continue
        visited.add(name)
        schema = schemas.get(name)
        if isinstance(schema, dict):
            nested = collect_refs(schema, prefix)
            frontier.update(nested - visited - excluded)

    return visited
