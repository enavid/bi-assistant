# Trace Evaluation Runner

Runs a batch of questions through the HR BI pipeline and saves full trace results for each question.

---

## Input Format

The runner accepts **JSON** or **CSV** files.

### JSON

A list of question objects. Only `question` is required; all other fields are optional.

```json
[
  {
    "question_id": "q001",
    "question": "تعداد کل کارکنان چقدر است؟",
    "expected_route": "SQL",
    "expected_status": "NOT_EXECUTED",
    "expected_intent": "employee_count_total"
  },
  {
    "question_id": "q002",
    "question": "درآمد ماهانه کارکنان چقدر است؟",
    "expected_route": "REJECT",
    "expected_status": "ACCESS_DENIED"
  },
  {
    "question_id": "q003",
    "question": "آب و هوای تهران چطور است؟",
    "expected_route": "REJECT",
    "expected_status": "OUT_OF_SCOPE"
  }
]
```

### CSV

A CSV file with a `question` column header. All other columns are optional.

```csv
question_id,question,expected_route,expected_status,expected_intent
q001,تعداد کل کارکنان چقدر است؟,SQL,NOT_EXECUTED,employee_count_total
q002,درآمد ماهانه کارکنان چقدر است؟,REJECT,ACCESS_DENIED,
q003,آب و هوای تهران چطور است؟,REJECT,OUT_OF_SCOPE,
```

> **Note:** If `question_id` is missing, the runner assigns `q001`, `q002`, ... automatically.

---

## Output Format

Each question produces one record with the following fields:

| Field | Type | Description |
|-------|------|-------------|
| `question_id` | string | Identifier from input (or auto-generated) |
| `question` | string | The original question text |
| `passed` | bool | `true` if all provided `expected_*` values matched |
| `expected_route` | string\|null | Expected pipeline route from input |
| `actual_route` | string\|null | Route assigned by the pipeline (`SQL`, `REJECT`, `GAP`, ...) |
| `route_match` | bool\|null | Whether route matched; `null` if no expected value |
| `expected_status` | string\|null | Expected status from input |
| `actual_status` | string\|null | Status returned by the pipeline |
| `status_match` | bool\|null | Whether status matched; `null` if no expected value |
| `expected_intent` | string\|null | Expected intent from input |
| `actual_intent` | string\|null | Intent detected by the pipeline |
| `intent_match` | bool\|null | Whether intent matched; `null` if no expected value |
| `source` | string\|null | SQL source (`template`, `llm`, `reject`, ...) |
| `model_called` | string\|null | LLM model name used for SQL generation |
| `template_id` | string\|null | Template ID if a template was used |
| `sql_validator_status` | string\|null | Result of the SQL validator step |
| `executed` | bool | Whether the SQL was executed against the database |
| `row_count` | int\|null | Number of rows returned (only when executed) |
| `visualization` | string\|null | Suggested chart type from visualization plan |
| `total_duration_ms` | float | Total pipeline duration in milliseconds |
| `trace_steps` | list | Each pipeline step with `step`, `status`, `duration_ms`, `decision_by` |
| `error` | string\|null | First error message if the pipeline failed |
| `warnings` | list | Any warnings raised during processing |

### Pipeline stages visible in `trace_steps`

`domain_classifier` → `question_validator` → `semantic_mapper` → `intent_parser` → `decision_router` → `sql_planner` → `sql_validator` → `executor`

---

## How to Run

### Via Makefile (recommended)

```bash
# Run with default example file
make trace-eval

# Run with a custom questions file
make trace-eval INPUT=/path/to/questions.json

# Run a CSV file and save output to a specific location
make trace-eval INPUT=/path/to/questions.csv OUTPUT=/path/to/results

# Run with parallel execution (faster for large batches)
make trace-eval INPUT=/path/to/questions.json CONCURRENCY=4

# Output only JSON
make trace-eval INPUT=/path/to/questions.json FORMAT=json
```

### Direct command

```bash
cd backend
uv run python eval/run_evaluation.py --input /path/to/questions.json
uv run python eval/run_evaluation.py --input /path/to/questions.csv --format csv
uv run python eval/run_evaluation.py --input /path/to/questions.json --output /path/to/results --concurrency 4
```

### Arguments

| Argument | Short | Default | Description |
|----------|-------|---------|-------------|
| `--input` | `-i` | *(required)* | Path to questions file (JSON or CSV) |
| `--output` | `-o` | `<input_dir>/evaluation_trace_results` | Output base path (no extension) |
| `--format` | `-f` | `both` | `json`, `csv`, or `both` |
| `--concurrency` | `-c` | `1` | Number of questions to run in parallel |

---

## Output Files

```
evaluation_trace_results.json   # full structured data, one object per question
evaluation_trace_results.csv    # same data as a flat table (trace_steps serialized as JSON string)
```
