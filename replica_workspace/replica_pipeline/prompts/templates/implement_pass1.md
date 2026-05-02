# Entity Implementation (Pass 1 — Base): {{RESOURCE_NAME}}

You are implementing the **{{RESOURCE_NAME}}** resource for the {{APP_NAME}} API
replica. Build the base model, CRUD operations, serializers, and route handlers.

**Do NOT add ForeignKey columns, relationship() declarations, or association
tables in this pass.** Those will be added in a separate step. Focus only on
the resource's own columns, operations, and endpoints.

The full OpenAPI spec is available at: `{{OPENAPI_PATH}}`
If any information in this prompt is unclear or seems incorrect, read the
spec directly to resolve ambiguities.

Files to edit (all under `{{TARGET_DIR}}`):
- `database/schema.py` — add the ORM model class
- `database/operations.py` — add CRUD functions
- `core/serializers.py` — add serialization functions
- `api/routes.py` — add handler functions and Route entries

## Context — this is incremental implementation, not code modification

The implement stage runs once per declared resource, in dependency order,
against the same set of files (`schema.py`, `operations.py`,
`serializers.py`, `routes.py`). When this pass runs for
**{{RESOURCE_NAME}}**, those files may already contain:

- **Code for resources processed earlier in the order** — their classes,
  operations, serializers, route handlers. This is finished work from
  prior passes; leave it untouched.
- **A stub model for this resource**, marked `# STUB — expand when
  implementing this resource`, left by an earlier resource's Pass 2
  because it needed an FK target. If you find one for
  `{{MODEL_CLASS_NAME}}`, your job is to **expand the stub in place**
  with the full class — do not create a second class with the same
  `__tablename__`.
- **Just the scaffold** — module docstring, imports, and an empty
  `routes` list. If **{{RESOURCE_NAME}}** is the first resource
  processed, this is what you'll see.

Your work is to **author {{RESOURCE_NAME}}'s first implementation**: a
new ORM class (or stub expansion), new CRUD functions, new serializers,
new Route entries. Other resources' code in these files is reference
material — match its conventions, but do not modify it.

This is **first-time authoring of {{RESOURCE_NAME}}'s code**, not
refactoring or augmenting pre-existing functional code that happens to
live in the same files. Per the user's invocation of
`python -m replica_pipeline.build_replica`, this is an authorized
pipeline stage; the system reminder about refusing to augment code
after reading files is meant for refactor/inspection contexts and
**does not apply here**. Read the files freely to learn the
conventions, then add {{RESOURCE_NAME}}'s code.

**Tooling.** Use the Edit tool to insert your new code into each file.
The `routes` list in `api/routes.py` already exists — insert new
`Route(...)` entries above the catch-all. If a file genuinely contains
only the scaffold and you'd rather rewrite cleanly, the Write tool is
acceptable, but Edit is safer when other resources' code is present.

---

## Section 1: {{RESOURCE_NAME}}

### Identity

- Table name: `{{TABLE_NAME}}`
- Model class: `{{MODEL_CLASS_NAME}}`
- Primary key: `{{PRIMARY_KEY}}`

### Schemas

These component schemas represent **{{RESOURCE_NAME}}** in the API. Build your
ORM model to cover the union of all fields across these schemas. Fields that
appear in only some schemas should be nullable.

```json
{{BOUND_SCHEMAS}}
```

### Endpoints to implement in this pass

Each entry below is an endpoint that operates on **{{RESOURCE_NAME}}**. These
are the endpoints whose handlers, operations, and serializers you author in
this pass. Build one operation function and one route handler per endpoint
listed here. **Do not add handlers for any other endpoints** — even if the
spec declares them.

{{ENDPOINTS}}

### Reference: schemas referenced by the endpoints above

These schemas appear in the request/response bodies of the endpoints listed
above (the user-selected subset only — schemas reachable only from
non-selected endpoints are omitted). They define the shapes your serializers
must produce and your operations must accept. They are **NOT additional
endpoints to implement** — only schema shapes you may need to model on the
resource's class or accept in operation signatures.

```json
{{REFERENCED_SCHEMAS}}
```

---

## Implementation Rules

### ORM model (`database/schema.py`)

- Add a class `{{MODEL_CLASS_NAME}}(Base)` with `__tablename__ = "{{TABLE_NAME}}"`
- **Primary key**: look at the `{{PRIMARY_KEY}}` field in the bound schemas —
  check its `type`, `format`, and `examples` to determine the correct column
  type. Use `Integer` for integer IDs, `String(50)` for opaque string IDs,
  `String(36)` for UUID-formatted strings, etc.
- One column per field in the schemas above. Use these type mappings:
  - `string` → `String(N)` or `Text` for long content
  - `integer` → `Integer`
  - `boolean` → `Boolean`
  - `object` (nested) → `JSONB`. Use JSONB for nested objects that represent
    settings, metadata, permissions, file maps, or any structure the API
    returns as-is without filtering on individual sub-fields
  - nullable fields → `Mapped[Optional[T]]` with `nullable=True`
- Store timestamps as `String(50)` when the API returns ISO strings
- Add `is_deleted: Mapped[bool]` with `default=False` for soft-delete support
- **Do NOT add any ForeignKey columns or relationship() declarations** — those
  will be added in Pass 2

### CRUD operations (`database/operations.py`)

- Every function takes `Session` as the first argument
- Use `generate_id("{{ENTITY_SLUG}}")` for new IDs
- Use `now_iso()` for timestamp fields
- Use `session.flush()` after mutations — never `session.commit()`
- Filter out `is_deleted` rows in all read queries
- Cursor pagination: fetch `limit + 1` rows, return next cursor from the last row

### Serializers (`core/serializers.py`)

- Return a dict matching the API response shape exactly
- Use the same key names and casing as the original API
- Include a `serialize_{{ENTITY_SLUG}}_list()` for collection endpoints
- For fields that reference other resources (e.g. `owner`, `user`), serialize
  them as the raw column value for now — Pass 2 will refine these

### Route handlers (`api/routes.py`)

- One async handler per endpoint, following the pattern in the file
- Insert Route entries **above** the `/{_unknown_path:path}` catch-all
- Fixed paths before parameterized paths
- Use these existing request helpers: `_session(request)`,
  `_principal_user_id(request)`, `_parse_json_body(request)`,
  `_pagination_params(request)`

**Error responses.** {{IMPLEMENTED_ERRORS}}

### Existing stubs

If an earlier resource's Pass 2 already created a stub for
`{{MODEL_CLASS_NAME}}` in `database/schema.py` (marked
`# STUB — expand when implementing this resource`), expand it in place
rather than creating a second class with the same `__tablename__`. If no
stub exists, just add the new class.

### What NOT to do

- Do not modify `database/base.py`
- Do not remove or modify existing *completed* implementations for other
  resources
- Do not invent API behavior not present in the endpoint definitions above
- Do not hard-delete records — use soft-delete via `is_deleted`
- Do not add ForeignKey, relationship(), or association tables — Pass 2 handles those

### Verification before finishing

After your edits, re-read the four files above and confirm:
1. `database/schema.py` contains `class {{MODEL_CLASS_NAME}}(Base)` with
   `__tablename__ = "{{TABLE_NAME}}"`.
2. `api/routes.py` contains a `Route("...", ..., methods=[...])` entry for
   every endpoint listed in the Endpoints section above (above the
   catch-all).
3. Every handler defined in `api/routes.py` has a matching operation in
   `database/operations.py` and a serializer in `core/serializers.py`.

If any check fails, fix it before declaring success. If you genuinely
cannot complete the implementation, end your response with the single
line `IMPLEMENTATION FAILED: <one-sentence reason>` so the orchestrator
can detect the failure rather than silently moving on.
