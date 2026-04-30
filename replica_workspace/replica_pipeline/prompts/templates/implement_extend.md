# Entity Extension: {{RESOURCE_NAME}}

You are adding new endpoints to the **{{RESOURCE_NAME}}** resource for the
{{APP_NAME}} API replica. The resource already exists in the codebase — your
job is to add **only the new endpoints listed below**, reusing the existing
model, operations, serializers, and route file conventions.

The full OpenAPI spec is available at: `{{OPENAPI_PATH}}`
If anything in this prompt is unclear, read the spec directly to resolve it.

**Read the existing files in `{{TARGET_DIR}}` first** before writing anything.
You need to understand the existing structure to extend it correctly.

Files you may edit (all under `{{TARGET_DIR}}`):
- `database/schema.py` — only if a new endpoint requires a column that doesn't already exist
- `database/operations.py` — add new functions for the new endpoints
- `core/serializers.py` — only if a new endpoint returns a shape no existing serializer can produce
- `api/routes.py` — add new handler functions and Route entries

---

## Identity

- Table name: `{{TABLE_NAME}}`
- Model class: `{{MODEL_CLASS_NAME}}`
- Primary key: `{{PRIMARY_KEY}}`

## Already implemented — do not modify

The following endpoints already have handlers in `api/routes.py`. Do not
change their handlers, the columns they read/write, or the serializers
they call. Treat them as a fixed contract:

{{ALREADY_IMPLEMENTED}}

## New endpoints to add

These are the **only** endpoints you should implement. Do not add any
other endpoints — even if the spec defines them.

{{ENDPOINTS_TO_ADD}}

## Bound schemas (reference)

These are the component schemas that represent **{{RESOURCE_NAME}}** in the
API. The existing model class should already cover most of these. Use them
to check whether the new endpoints need columns that aren't on the model
yet.

```json
{{BOUND_SCHEMAS}}
```

## Referenced schemas (reference)

These schemas appear in the new endpoints' request/response bodies but
aren't direct representations of **{{RESOURCE_NAME}}**.

```json
{{REFERENCED_SCHEMAS}}
```

---

## Rules

### Model (`database/schema.py`)

- If the new endpoints reference fields that already exist on `{{MODEL_CLASS_NAME}}`,
  reuse them.
- If a new endpoint requires a column that doesn't exist yet, add it to the
  existing class as `Mapped[Optional[T]]` with `nullable=True` so existing
  rows remain valid. Use the same type-mapping conventions as the rest of
  the file (`String(N)` / `Integer` / `Boolean` / `JSONB` for nested
  objects / `String(50)` for ISO timestamps).
- **Do NOT** rename or remove existing columns.
- **Do NOT** add ForeignKey columns or `relationship()` declarations in
  this pass — Pass 2 handles relationships if needed.
- If the existing class is a thin stub (only PK + tablename), flesh out the
  columns the new endpoints require.

### Operations (`database/operations.py`)

- Add new functions for the new endpoints. Reuse existing functions where
  possible (e.g. an existing `get_{{ENTITY_SLUG}}` for ID lookups).
- Every function takes `Session` as the first argument.
- Use `generate_id("{{ENTITY_SLUG}}")` for new IDs and `now_iso()` for
  timestamps.
- Use `session.flush()` after mutations — never `session.commit()`.
- Filter out `is_deleted` rows in reads.
- Cursor pagination: fetch `limit + 1` rows, return next cursor from the
  last row.

### Serializers (`core/serializers.py`)

- Reuse existing serializers wherever the response shape matches.
- Only add a new serializer when the new endpoint returns a shape no
  existing serializer can produce.

### Routes (`api/routes.py`)

- One async handler per new endpoint, matching the pattern of existing
  handlers in the file.
- Insert new `Route(...)` entries in the `routes: list[Route]` block,
  **above** the `/{_unknown_path:path}` catch-all if one exists.
- Fixed paths before parameterized paths.
- Use `_session(request)`, `_principal_user_id(request)`,
  `_parse_json_body(request)`, `_pagination_params(request)` — the same
  request helpers the existing handlers use.
- **Error responses**: {{IMPLEMENTED_ERRORS}}

### What NOT to do

- Do not modify existing handlers, operations, or serializers for endpoints
  in the "Already implemented" list.
- Do not rename, retype, or drop existing columns.
- Do not add endpoints that aren't in the "New endpoints to add" list.
- Do not modify other resources' models, handlers, or serializers.
- Do not modify `database/base.py`.
- Do not hard-delete records — use soft-delete via `is_deleted`.
- Do not add ForeignKey, relationship(), or association tables — Pass 2
  handles those.
