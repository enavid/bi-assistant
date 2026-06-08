# Architecture

The backend follows Clean Architecture (Uncle Bob). Each layer depends only on layers inside it, never outward.

```
Entities  <-  Use Cases  <-  Interface Adapters  <-  Frameworks & Drivers
```

## Layers

### Domain (`app/domain/`)

Pure Python dataclasses and Protocol interfaces. No framework imports.

- `entities/workspace.py` — Project, Workspace, ChatSession, Message, Section
- `entities/hr_analytics.py` — GenerationResult, QueryResult
- `interfaces/__init__.py` — ILLMClient, IQueryExecutor, IMetadataService, ISQLValidator

### Use Cases (`app/use_cases/`)

Business logic. Depends only on domain interfaces.

**`hr_analytics/`** — Controlled SQL pipeline:

```
question
  -> DomainClassifier     (is this an HR question?)
  -> QuestionValidator    (is it safe and valid?)
  -> SemanticMapper       (map terms to metadata)
  -> IntentParser         (determine intent from catalog)
  -> DecisionRouter       (choose: SQL / GAP / REJECT / NEEDS_CLARIFICATION)
  -> SQLTemplateEngine    (render SQL from templates)
  -> SQLGenerator         (dynamic SQL if no template)
  -> SQLValidator         (enforce safety rules)
  -> QueryExecutor        (run against HR DB)
  -> ResponseBuilder      (format final response)
```

Entry point: `LLMOrchestrator.arun()` in `orchestrator.py`.
Facade: `HRBIOrchestrationUseCase` in `orchestrate.py`.

**`workspace/`** — Project and SQL execution use cases for the workspace feature.

### Infrastructure (`app/infrastructure/`)

External concerns — all replaceable by swapping implementations.

- `db/` — SQLAlchemy async ORM, Alembic migrations (app database)
- `hr_db/executor.py` — psycopg2 executor for workspace SQL runs
- `hr_db/analytics_executor.py` — validated SQL executor for the analytics pipeline
- `llm/ollama_client.py` — Ollama HTTP client
- `llm/analytics_client.py` — LLM client for SQL fallback generation
- `llm/prompt_builder.py` — prompt construction for LLM fallback
- `metadata/service.py` — loads and caches YAML/JSON metadata files

### API (`app/api/`)

FastAPI routes, schemas, DI, and middleware.

- `routes/` — thin HTTP handlers, delegate to use cases
- `schemas/` — Pydantic request/response models (per-domain files)
- `dependencies.py` — `lru_cache`-based dependency injection
- `middleware/` — request ID injection

### Adapters (`app/adapters/`)

Output formatters not tied to FastAPI.

- `presenters/response_builder.py` — formats orchestrator output into the final API response shape

## Routing outcomes

Each question results in one of four routes:

| Route | Status values | Meaning |
|-------|--------------|---------|
| `SQL` | `VALID`, `NOT_EXECUTED` | Supported intent; SQL was generated (and optionally executed) |
| `GAP` | `DATA_GAP` | HR question but raw data is not available in the current MVP |
| `GAP` | `ANALYTICAL_GAP` | HR question but the analytical method or KPI is not yet defined |
| `REJECT` | `ACCESS_DENIED` | Requests individual/sensitive employee data |
| `REJECT` | `OUT_OF_SCOPE` | Question is outside the HR domain entirely |
| `NEEDS_CLARIFICATION` | `NEEDS_CLARIFICATION` | Ambiguous question; needs user clarification |

**DATA_GAP vs ANALYTICAL_GAP:** `DATA_GAP` means the raw data column or table is missing. `ANALYTICAL_GAP` means the data may exist but no agreed KPI definition or analytical methodology has been formalised (e.g. contractor productivity, workload-hiring alignment).

## Status templates

`sql_templates.yaml` contains a `status_templates` section alongside regular SQL templates. These are special entries (`TPL_ACCESS_DENIED`, `TPL_DATA_GAP`, `TPL_OUT_OF_SCOPE`, `TPL_NEEDS_CLARIFICATION`) that intents can reference as their `sql_template_id`.

When `DecisionRouter` sees that an intent's `sql_template_id` is a status template, it routes directly to the target status without invoking the SQL engine. This allows metadata-authors to mark intents as permanently blocked without writing Python code.

## API response fields

The `/generate` endpoint returns:

| Field | Description |
|-------|-------------|
| `route` | `SQL`, `GAP`, `REJECT`, or `NEEDS_CLARIFICATION` |
| `status` | Fine-grained status (see table above) |
| `message_fa` | Persian explanation shown in the UI |
| `detected_intent` | Intent ID matched by the pipeline |
| `generated_sql` | SQL string (present on SQL route) |
| `data` | Query result rows (present when SQL was executed) |
| `source` | Origin of the answer (`sql`, `gap`, `reject`, `clarification`) |
| `traces` | List of pipeline step traces (step name, status, duration) |
| `warnings` | Non-fatal issues raised during processing |

## Metadata files

The pipeline is metadata-driven. YAML/JSON files in `metadata/` define:

| File | Purpose |
|------|---------|
| `intent_catalog.yaml` | Supported HR intents and their SQL template IDs |
| `sql_templates.yaml` | Parameterised SQL templates; also contains `status_templates` section |
| `semantic_layer.yaml` | Term-to-concept and term-to-column mappings |
| `data_dictionary.yaml` | View columns, types, and access policies |
| `sql_validator_rules.yaml` | Validation rules (blocklist, allowlist) |
| `access_policies.yaml` | Column-level access restrictions per role |
| `kpi_catalog.yaml` | KPI definitions |
| `visualization_rules.yaml` | Chart type per intent |

## Extending the pipeline

**Add a new HR intent:**
1. Add the intent to `intent_catalog.yaml` with `supported_in_phase2: true`.
2. Add a SQL template to `sql_templates.yaml` (or reference a status template if the intent is a known gap).
3. Add semantic terms to `semantic_layer.yaml`.
4. Add a test case to `tests/routing_eval/cases.yaml` so regression is caught automatically.

**Add a new routing eval test case:**

Edit `tests/routing_eval/cases.yaml` — no Python required:

```yaml
- id: my-new-case
  question: "سوال فارسی"
  category: sql          # access_denied | out_of_scope | data_gap | analytical_gap | sql
  description: What edge case this covers
  expect:
    route: SQL
    intent: my_intent_id  # optional
```

Run `make eval` to verify.

**Add a new pipeline step:**
1. Create a class in `app/use_cases/hr_analytics/steps/`.
2. Implement `run(question, context, metadata)` and `arun(...)`.
3. Inject it in `app/api/dependencies.py`.
4. Wire it into `LLMOrchestrator.__init__`.

**Swap a component (e.g., different LLM):**
Replace the injected instance in `app/api/dependencies.py`. The orchestrator uses duck typing — any object with matching methods works.

## Configuration

All settings come from environment variables (`.env` file). See `.env.example` for all available keys.

Key settings:

| Variable | Default | Description |
|----------|---------|-------------|
| `DEFAULT_EXECUTE_SQL` | `false` | Execute SQL or return it only |
| `ENABLE_LLM_SQL_FALLBACK` | `true` | Use LLM when no template matches |
| `VALIDATE_SQL_BEFORE_EXECUTION` | `true` | Run validator before every query |
| `LOG_LEVEL` | `INFO` | DEBUG / INFO / WARNING / ERROR |
| `METADATA_DIR` | `./metadata` | Path to metadata YAML files |
