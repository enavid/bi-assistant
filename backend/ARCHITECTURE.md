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
  -> DecisionRouter       (choose: SQL / GAP / REJECT)
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

## Metadata files

The pipeline is metadata-driven. YAML/JSON files in `metadata/` define:

| File | Purpose |
|------|---------|
| `intent_catalog.yaml` | Supported HR intents and their SQL template IDs |
| `sql_templates.yaml` | Parameterised SQL templates per intent |
| `semantic_layer.yaml` | Term-to-concept and term-to-column mappings |
| `data_dictionary.yaml` | View columns, types, and access policies |
| `sql_validator_rules.yaml` | Validation rules (blocklist, allowlist) |
| `access_policies.yaml` | Column-level access restrictions per role |
| `kpi_catalog.yaml` | KPI definitions |
| `visualization_rules.yaml` | Chart type per intent |

## Extending the pipeline

**Add a new HR intent:**
1. Add the intent to `intent_catalog.yaml` with `supported_in_phase2: true`.
2. Add a SQL template to `sql_templates.yaml`.
3. Add semantic terms to `semantic_layer.yaml`.
4. Add a test in `tests/test_orchestrator.py`.

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
