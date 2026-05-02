# replica_pipeline

A pipeline that turns an **OpenAPI spec + a small `app.yaml`** into a working API replica — generated SQLAlchemy models, CRUD ops, serializers, Starlette routes, error handlers, seeded PostgreSQL templates, and curated documentation. The pipeline orchestrates LLM calls (`claude -p`) for the parts that need judgment and pure code for the parts that don't.

The point: take a third-party REST API (Asana, GitHub, Slack, Box, Linear, Google Calendar, Todoist, ...) and produce a self-contained replica that responds to the same endpoints with the same shapes, runs in Docker against a local Postgres, and can be exercised by tests without hitting the real service.

---

## Quick start

Add a new replica from scratch (assumes you've placed `inputs/openapi.<spec>.json` next to `app.yaml`):

```bash
python -m replica_pipeline.build_replica apps/<slug>/app.yaml
```

That runs the full chain — scaffolds the directory, infers aliases, walks the spec, generates code, registers tests, seeds the DB, and exercises the live replica end-to-end.

Add new endpoints to a replica that's already been built:

```bash
# Edit app.yaml — append to selected_endpoints, then:
python -m replica_pipeline.extend_replica apps/<slug>/app.yaml
```

For most day-to-day work, those are the only two commands you need.

---

## The two entrypoints

| Command | When | What it does |
|---|---|---|
| `python -m replica_pipeline.build_replica apps/<slug>/app.yaml` | **First time** building a replica from a fresh `app.yaml` | Runs all 9 stages: `init → configure → suggest_aliases → extract → implement_responses → implement → register_tests → seed_template → test_endpoints` |
| `python -m replica_pipeline.extend_replica apps/<slug>/app.yaml` | **Adding endpoints** to an existing replica | Runs 6 stages: `extract → implement_responses → extend → register_tests → seed_template → test_endpoints` (skips first-time scaffolding) |

Both share `RunContext` and the same shared CLI flags. Both fail loudly if `selected_endpoints` is missing or every entry is unknown.

---

## How the pipeline works (stage-by-stage)

The full chain in canonical order. Each stage's body lives in its home subpackage; entry points dispatch by name.

### 1. `init` — Scaffold the target service directory

Creates the on-disk skeleton at `target_dir` (typically `backend/src/services/<slug>/`):
- `database/base.py`, `database/db.py`, `database/operations.py`
- `core/errors.py`, `core/serializers.py`
- `api/routes.py`
- `__init__.py` files

Empty stubs that subsequent stages fill in. Idempotent — re-running doesn't clobber existing code.

### 2. `configure` — LLM populates aliases + primary keys

Reads each declared resource in `app.yaml` and asks the LLM to produce:
- All schema-name variants the spec uses for that resource (e.g. for `users`: `user`, `simple_user`, `owner`, `assignee`, ...).
- The primary-key field name (default `id`, override for `gid` in Asana, `sha` in GitHub commits, etc.).
- Self-identity fields (additional fields that represent the resource's own identity).

The result is merged back into `app.yaml`. Subsequent stages use this expanded alias set to attribute schemas to resources.

### 3. `suggest_aliases` — Verify alias suggestions

Cross-checks `configure`'s output against the spec's component schemas, calling the LLM again to classify each candidate as `variant` (real alias) / `distinct` (false positive) / `uncertain` (manual review). Verdicts are cached in `pipeline_out/.alias_review_cache.json` so re-runs are free.

### 4. `extract` — Walk the spec, emit machine-readable docs

Pure derivation, no LLM calls. Produces:
- **`pipeline_out/endpoints.json`** — every endpoint in the spec (245 for Asana) with method, path, parameters, request body, responses, and per-endpoint `references` (every spot where the endpoint touches a declared resource alias). Schema closure inlined so prompts don't need to follow `$ref` chains.
- **`pipeline_out/resources.json`** — pivot of the same data by resource: bound schemas, endpoint keys owned, outgoing/incoming reference evidence, dependency-order metadata.

This is the canonical spec snapshot; it gets rebuilt on every `build` and `extend`.

### 5. `implement_responses` — LLM emits standard error constructors

Asks the LLM to populate `core/errors.py` with constructors for the standard HTTP errors the spec declares (`bad_request`, `unauthorized`, `not_found`, `internal_server_error`, etc.). Run once before `implement` so each per-resource handler can `raise not_found(...)` instead of redefining.

### 6. `implement` — LLM generates the service per resource

For each resource that owns a selected endpoint:
- **Pass 1** — base ORM model + CRUD operations + serializers + route handlers, with no FK relationships yet.
- **Pass 2** — adds FK columns, `relationship()` declarations, association tables, and serializer enrichment (only fires if the resource has outgoing FKs to *other* resources).

Resources are processed in topological order (dependencies first) so Pass 2 can wire FKs to already-existing target tables. Pass 1 prompts include the bound schema definitions, full endpoint metadata, and existing error constructors. Pass 2 prompts add evidence of cross-resource references.

### 7. `register_tests` — Scan the live `routes.py`, build the test registry

Imports the just-generated routes module, extracts every `Route(...)` entry, and writes:
- **`pipeline_out/test_registry.json`** — one entry per implemented endpoint with `method`, `path`, `subject`, `summary`, `path_params`, `needs_seed`, `tested`, `test_result`. Tested status is preserved across runs (`--force-retest` opts out).
- **`examples/<slug>/testsuites/<slug>_docs/<slug>_api_full_docs.json`** — curated, flattened documentation of implemented endpoints (description + grouped parameters with type/required/description). Self-contained, no `$ref`s.

The registry is the canonical "what's been built and what's its test status" view.

### 8. `seed_template` — Build PostgreSQL template schemas

Calls `backend/utils/seed_template.py --app <slug>`, which:
- Creates `<slug>_base` (empty) and one schema per `*.json` in `backend/seeds/<slug>/`.
- Each schema gets a full set of tables via `Base.metadata.create_all`.
- Seeded schemas get rows inserted in FK-safe order (per `Base.metadata.sorted_tables`, or an app-specific override in `backend/src/services/<slug>/database/seed_hooks.py`).
- Apps with binary content (Box) ship a `seed_hooks.before_insert(seed_data, Base)` to load file bytes from disk.
- All templates registered in `public.environments` so per-test environments can clone them.

### 9. `test_endpoints` — Drive the live replica via curl, fix bugs in place

Groups untested entries from `test_registry.json` by subject, chunks each subject into batches of N (default 7), and hands each batch to `claude -p` with full schema context + a sandboxed `curl` workflow. The LLM:
- Issues `curl` calls against the running replica.
- Compares responses against expected shapes.
- **Fixes bugs in place** by editing the generated source files (uvicorn `--reload` picks up changes immediately).
- Writes a structured JSON result file per batch (`pipeline_out/test_results/<subject>_batch<N>.json`) with `passed`, `iterations`, `diagnosis`, `curl_examples`, `code_changes`.

Results are merged back into `test_registry.json`. Anything flagged `passed: true` doesn't get re-tested on the next run unless `--force-retest` is passed.

The extend pipeline replaces `implement` with `extend` and skips `init` / `configure` / `suggest_aliases`.

### `extend` (vs `implement`)

`extend` is `implement` aware that the replica already exists:
- Scans `database/schema.py` for `__tablename__` entries to know which resources have models.
- Scans `api/routes.py` for `Route(...)` entries to know which endpoints already have handlers.
- For a resource with no schema entry → CREATE mode (full Pass 1 + Pass 2, like `implement`).
- For a resource with a schema entry → EXTEND mode (uses a different prompt that lists existing handlers as "do not modify" and instructs the LLM to add only the new endpoints).
- For an endpoint already in `routes.py` → warned and skipped.

---

## Configuration: `app.yaml`

Each replica has one config file at `apps/<slug>/app.yaml`. Minimal shape:

```yaml
app_slug: asana
app_name: Asana
openapi_path: inputs/openapi.scoped.json    # relative to app.yaml's dir
target_dir: ../../../backend/src/services/asana   # where to generate code

resources:
  tasks:
    aliases:
      - task
      - tasks
      - task_compact
      - task_request
    primary_key: gid           # default "id"; override for non-standard PKs
    self_id_fields:            # optional; default ["id"]
      - gid

  projects:
    aliases: [project, projects, project_compact]
    primary_key: gid

naming:
  pk_field_names: [gid]        # used for alias expansion (user → user_gid, user_id)
  self_id_fields: [gid]
  qualifier_prefixes: [parent_, source_, target_]   # strip these in property-walk

selected_endpoints:
  - "POST /tasks"
  - "GET /tasks"
  - "GET /tasks/{task_gid}"
  - "PUT /tasks/{task_gid}"
  - "DELETE /tasks/{task_gid}"
  - "POST /tasks/{task_gid}/addProject"
```

Field-by-field:

| Field | Purpose |
|---|---|
| `app_slug` | Used as table-name prefix (`asana_tasks`), routes module path, seeds directory name. Must be snake_case. |
| `app_name` | Human-readable name used in LLM prompts. |
| `openapi_path` | Path to the OpenAPI spec, relative to the YAML file. |
| `target_dir` | Where to generate code. Typically `backend/src/services/<slug>/`. |
| `resources` | Closed-world list of resources to implement. Aliases declared here drive subject-attribution everywhere downstream. |
| `naming` | Cross-resource defaults (PK field naming, qualifier prefixes for things like `parent_user_id`). |
| `selected_endpoints` | The actual contract for what gets implemented. `"METHOD /path"` strings. Without this, `implement` and `extend` refuse to run. |

`selected_endpoints` is the most operator-facing knob. Adding one and re-running `replica_pipeline.extend_replica` is how you grow a replica.

---

## What gets produced

After a successful build:

| Where | What | Persisted? |
|---|---|---|
| `backend/src/services/<slug>/` | The replica code itself: `schema.py`, `operations.py`, `serializers.py`, `routes.py`, `errors.py`, plus base scaffolding. | Yes — committed to git. **The primary product.** |
| `examples/<slug>/testsuites/<slug>_docs/<slug>_api_full_docs.json` | Curated documentation of implemented endpoints. | Yes — committed; consumed by external tooling. |
| `backend/seeds/<slug>/*.json` + PostgreSQL `<slug>_base`, `<slug>_default` schemas | Seeded test fixtures + their materialized DB schemas. | JSON committed; DB schemas exist until dropped. |
| `apps/<slug>/pipeline_out/` | Pipeline working state: `endpoints.json`, `resources.json`, `responses.json`, `test_registry.json`, `test_results/`. | **Gitignored** — local-only. Test registry rebuilds on fresh clones via `register_tests`. |
| `apps/<slug>/prompts/` | Every LLM prompt the run dispatched, saved unconditionally. File names embed stage + target: `configure.md`, `suggest_aliases_<resource>.md`, `implement_responses.md`, `implement_<resource>_pass{1,2}.md`, `extend_<resource>_pass{1,2}.md`, `test_<resource>_batch<N>.md`. | **Gitignored** — debug + audit trail. |

The replica code is the artifact. Everything in `pipeline_out/` and `prompts/` is scaffolding that helps produce it.

---

## Common workflows

### Add a single new endpoint to an existing replica

```yaml
# apps/asana/app.yaml — append to selected_endpoints:
selected_endpoints:
  - ...existing entries...
  - "POST /goals/{goal_gid}/addFollowers"
```

```bash
python -m replica_pipeline.extend_replica apps/asana/app.yaml
```

That runs the full extend chain: refresh the spec walk, regenerate the response constructors (no-op if already built), run the LLM in EXTEND mode for `goals` (the resource owning the new endpoint), register the new route, and exercise it through the test stage.

### Add a brand-new resource to a replica

Two-step:

1. Declare the resource in `app.yaml`:
   ```yaml
   resources:
     ...
     goals:
       aliases: [goal, goals, goal_compact, goal_request, goal_response]
       primary_key: gid

   selected_endpoints:
     - "POST /goals"
     - "GET /goals"
     - "GET /goals/{goal_gid}"
     # ...
   ```
2. Run extend:
   ```bash
   python -m replica_pipeline.extend_replica apps/asana/app.yaml --resource goals
   ```

The `--resource goals` flag scopes to the new resource so `extend` doesn't re-touch the others. Extend will detect `goals` has no schema entry → CREATE mode with full Pass 1 + Pass 2.

### Inspect prompts before paying for an LLM call

```bash
python -m replica_pipeline.build_replica apps/asana/app.yaml --dry-run
# or for a single stage:
python -m replica_pipeline.build_replica apps/asana/app.yaml --stage implement --dry-run
```

Every stage that calls the LLM saves its prompt to `prompts/` regardless of whether it's a real run or a dry-run. With `--dry-run` the LLM call itself is skipped; otherwise the prompt is saved first, the LLM is dispatched, and the file remains for inspection. Filenames carry the stage and the target — e.g. `implement_tasks_pass1.md`, `suggest_aliases_users.md`.

### Run a single stage / a range

```bash
# Single stage:
python -m replica_pipeline.build_replica apps/asana/app.yaml --stage extract

# From a stage to the end:
python -m replica_pipeline.extend_replica apps/asana/app.yaml --from-stage extend

# From the start through a stage:
python -m replica_pipeline.build_replica apps/asana/app.yaml --up-to-stage register_tests
```

`--stage` / `--from-stage` / `--up-to-stage` are mutually exclusive.

### Re-test the whole surface (regression sweep)

```bash
python -m replica_pipeline.build_replica apps/asana/app.yaml --stage test_endpoints --force-retest
```

Default behavior: only entries with `tested: false` get exercised. `--force-retest` bypasses the registry's tested flags and re-tests everything.

### Restrict to specific resources

```bash
python -m replica_pipeline.build_replica apps/asana/app.yaml --resource tasks projects
python -m replica_pipeline.extend_replica apps/asana/app.yaml --resource goals
```

`--resource` filters which resources get touched by `implement`/`extend`/`test_endpoints`. `register_tests` always operates over the full live `routes.py` (with prior-registry splice for entries outside the filter).

### Override LLM models

```bash
python -m replica_pipeline.build_replica apps/asana/app.yaml \
    --configure-model claude-haiku-4-5 \
    --implement-model claude-opus-4-7 \
    --test-model claude-opus-4-7
```

Or set the env vars `CLAUDE_PIPELINE_CONFIGURE_MODEL`, `CLAUDE_PIPELINE_IMPLEMENT_MODEL`, `CLAUDE_PIPELINE_TEST_MODEL`. Defaults live in [`pipeline/utils/llm.py`](pipeline/utils/llm.py).

---

## Project layout

```
replica_workspace/
├── README.md                       # this file
├── apps/
│   └── <slug>/
│       ├── app.yaml                # the per-app config
│       ├── inputs/                 # OpenAPI spec lives here
│       ├── pipeline_out/           # gitignored — pipeline state
│       └── prompts/                # gitignored — every LLM prompt, named by stage + target
├── open_api_schemas/               # raw, full-fidelity vendor specs
├── mockfiles/                      # test fixtures referenced by `mocks` field
└── replica_pipeline/               # the orchestrator package (importable as ``replica_pipeline``)
    ├── __init__.py
    ├── _cli.py                     # RunContext + shared CLI machinery
    ├── build_replica.py            # entrypoint: full pipeline (init → ... → test_endpoints)
    ├── extend_replica.py           # entrypoint: incremental extend (skips first-time scaffolding)
    ├── config.py                   # PipelineConfig domain type + load_config
    ├── scaffold.py                 # init stage runner
    ├── aliases/                    # configure + suggest_aliases stages
    │   ├── apply.py                # patch_config — surgically inserts aliases into app.yaml
    │   ├── configure.py            # run_configure (stage runner)
    │   ├── runner.py               # run_suggest_aliases (stage runner)
    │   ├── review.py               # variant/distinct verdict layer
    │   └── suggest.py              # candidate alias discovery
    ├── extraction/                 # extract stage core
    │   ├── runner.py               # run_extract
    │   ├── endpoint_references.py  # 4-walk reference extractor
    │   ├── reference_groups.py     # cross-endpoint pair grouping
    │   └── schema_bindings.py      # schema → resource binding
    ├── documentation/              # endpoints.json + resources.json + api_docs builder
    │   └── builder.py              # generate_endpoints_document, generate_resources_document, generate_api_docs_document
    ├── implementation/             # implement / implement_responses / extend runners
    │   └── runner.py               # 3 stage runners + scanners (_scan_implemented_resources, _scan_implemented_routes)
    ├── testing/                    # register_tests + test_endpoints + seed_template runners
    │   ├── register.py             # registry build + splice + tested-status preservation
    │   ├── runner.py               # test_endpoints orchestration (batching, dispatch, result merge)
    │   └── seed.py                 # seed_template stage (calls backend/utils/seed_template.py)
    ├── prompts/                    # ALL LLM prompt construction
    │   ├── implement.py            # build_pass1/pass2/extend_prompt + ~10 shared helpers
    │   ├── implement_responses.py  # build_implement_responses_prompt
    │   ├── test_endpoints.py       # build_test_prompt + helpers (collect_schema_closure, render_endpoints_block, ...)
    │   ├── configure.py            # build_configure_prompt
    │   ├── review.py               # build_review_prompt
    │   ├── templates/              # markdown templates loaded by the builders
    │   │   ├── implement_pass1.md
    │   │   ├── implement_pass2.md
    │   │   ├── implement_extend.md
    │   │   └── test_endpoints.md
    │   └── mocks/                  # SQLAlchemy relationship-pattern examples (Pass 2 input)
    │       ├── many_to_many.txt
    │       ├── multiple_fks_same_target.txt
    │       ├── one_to_many.txt
    │       └── self_referential.txt
    └── utils/                      # pure utilities, no domain knowledge
        ├── llm.py                  # claude -p wrapper + DEFAULT_*_MODEL constants
        ├── refs.py                 # generic $ref walker (collect_refs, transitive_closure)
        └── text.py                 # identifier normalization (snake_case, IDENTIFIER_PATTERN)
```

### Where to look for what

| Question | Where to look |
|---|---|
| What does stage X do? | `replica_pipeline/<subpackage>/runner.py` for the stage runner; `replica_pipeline/prompts/<stage>.py` for its prompt. |
| Why does `endpoints.json` have shape Y? | `replica_pipeline/documentation/builder.py:generate_endpoints_document`. |
| What's the LLM going to see for endpoint Z? | Look in `apps/<slug>/prompts/` after any run — every prompt is saved unconditionally. Use `--dry-run` to populate the dir without dispatching the LLM. |
| What's the test status of endpoint Z? | `apps/<slug>/pipeline_out/test_registry.json` (gitignored — runs locally). |
| What does the replica expose? | `examples/<slug>/testsuites/<slug>_docs/<slug>_api_full_docs.json` — curated docs of implemented endpoints. |
| What's *currently* implemented? | The same docs file, OR scan `backend/src/services/<slug>/api/routes.py` for `Route(...)` entries. |

---

## Stage dispatch model

Every stage runner takes a single `RunContext` argument. Adding a new orchestrator-level option is one edit to the dataclass in [`pipeline/_cli.py`](pipeline/_cli.py).

`RunContext` carries:
- `config_path` (path to `app.yaml`)
- `dry_run`, `only_resources`
- model overrides (`configure_model`, `implement_model`, `test_model`)
- testing knobs (`test_batch_size`, `test_max_iterations`, `test_force_retest`, `test_timeout`)
- `all_endpoints_per_resource` (run.py only — implements every endpoint without needing `selected_endpoints`)
- Two computed paths: `output_dir` (= `pipeline_out/`) and `prompt_dir` (= `prompts/`).

Stages don't share state directly — they read/write files in `output_dir`. That keeps individual stages runnable in isolation:

```bash
python -m replica_pipeline.build_replica apps/asana/app.yaml --stage extract       # produce endpoints.json/resources.json
python -m replica_pipeline.build_replica apps/asana/app.yaml --stage register_tests # rebuild test_registry.json from current routes.py
```

---

## Failure modes worth knowing

| Symptom | Likely cause | Fix |
|---|---|---|
| `implement stage refuses to run: no selected_endpoints in app.yaml` | The default mode requires explicit endpoint selection. | Add a `selected_endpoints:` list, OR pass `--all-endpoints-per-resource` to implement everything (expensive). |
| `[warn] N selected endpoint(s) not found in spec — skipped: ...` | Typo in `selected_endpoints` or the spec doesn't actually have that endpoint. | Fix the typo; entries with no spec match are silently dropped (warning, not error). |
| `[warn] N selected endpoint(s) belong to a resource not declared in app.yaml — skipped: ...` | The endpoint's URL doesn't match any declared resource alias. | Add the relevant resource to `resources:` (with aliases), then re-run. |
| `register_tests could not import services.<slug>.api.routes` | The generated `routes.py` has a syntax error or missing dependency. | Inspect the file; fix manually; rerun `register_tests`. |
| `test_endpoints: [skip] nothing to test` | All entries already `tested: true`. | Pass `--force-retest` for a regression sweep, or scope to specific resources. |
| Build hangs at `Calling claude-opus-4-7...` | LLM call timed out or auth issue. | Check `claude` CLI auth (`claude --version`); increase `--test-timeout` for batches. |

---

## See also

- [`backend/utils/seed_template.py`](../backend/utils/seed_template.py) — the generic seeder this pipeline calls.
- [`backend/src/services/replicas.yaml`](../backend/src/services/replicas.yaml) — registry of all replicas + their seed commands.
- Per-app `app.yaml` examples: `apps/{asana,box,calendar,github,linear,slack,todoist}/app.yaml`.
