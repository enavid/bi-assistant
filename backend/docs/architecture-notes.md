# Architecture Notes — HR BI Assistant Pipeline

## Why the current architecture is fragile

Every routing decision (which template? go to LLM? which intent?) is gated by hardcoded if/else on Persian strings inside `intent_parser.py`, `semantic_mapper.py`, and `orchestrator.py`. A single phrasing variation breaks routing. Every new feedback round adds more conditions across multiple files.

## What the pipeline is supposed to be (but isn't yet)

The modular flow (Template → Coverage → LLM Fallback → SQL Validator) is the right shape. The mistake is that each transition is controlled by string-match rules instead of a lightweight classifier.

## Post-demo refactor roadmap

| Layer | Now (fragile) | After refactor (correct) |
|-------|---------------|--------------------------|
| Intent classification | if/else on Persian strings | LLM call → structured JSON |
| Term mapping | hardcoded lists per module | metadata-driven (intent_catalog) |
| Normalization | called multiple times in different steps | single central pass |
| SQL generation | template + controlled_dynamic | same |
| Security / validation | deterministic rules | stays deterministic |

Security, access policy, SQL validation, and Trace must remain deterministic regardless of refactor.

## Key invariants that must survive any refactor

- `SQL_VALIDATION_FAILED` is always a real failure — never treat it as pass
- `v.is_active = TRUE` must be present in every HR query — auto-injected by SQLValidator
- `employee_id` must never be exposed as an individual row — only inside COUNT
- All queries must go through `hr_mvp.vw_hr_employee_analytics v` — no raw tables, no JOINs

## Routing eval baseline

- Baseline after MVP hardening: 3 failures from 1059 cases, 28 xfail (known intent-classifier limits)
- The 3 remaining failures (cross-180v2/v3, emp-077v3) are age+employment_type ambiguity — identical question structure with contradictory expected intents. Unresolvable without an LLM-based classifier.
- Before/after regression check: `git stash && make eval` → count → `git stash pop` → count
