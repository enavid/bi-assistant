# SQL Security Model & Escaping Decision

Status: **accepted** · Last reviewed: 2026-06-27 (Phase 3.5)

This note records the deliberate decision about how user-influenced values reach
the HR database, why the current approach is safe, and what would change it. It
exists because `metadata/sql_validator_rules.yaml` declares
`bind_parameters_required_for_user_values: true`, which the implementation does
**not** literally satisfy — that flag is an aspiration, and this document is the
explicit reconciliation the code review asked for.

## How SQL is produced

All analytic SQL is machine-generated, never hand-assembled from raw request
strings:

- **Identifiers** (columns, the view, aliases) are never taken from user text.
  They are resolved against metadata whitelists (`allowed_columns`, the single
  `hr_mvp.vw_hr_employee_analytics` view) and matched with `SAFE_COLUMN_RE`.
  Anything unknown is rejected, not escaped.
- **Values** (filter literals such as a department name or a year) are rendered
  through a single choke point — `SQLGenerator._sql_literal` /
  `template_engine` / `controlled_dynamic` — which:
  - emits numbers/booleans/`NULL` as bare tokens (no quoting needed);
  - emits every string as a single-quoted literal with embedded quotes doubled
    (`'` → `''`).

## Why manual escaping is safe here

1. **`standard_conforming_strings = on`** (PostgreSQL default since 9.1). With
   it on, backslashes are literal, so quote-doubling is a *complete* escape for
   string literals — there is no backslash-escape path to break out of the
   literal.
2. **Identifiers are whitelisted, not escaped.** The classic injection vector
   (user-controlled identifiers) does not exist: an identifier that is not in
   the metadata whitelist is rejected outright.
3. **Defense in depth.** Two independent gates run on every statement before
   execution, and again before the executor will run it:
   - the regex/string `SQLValidator` (statement type, blocked patterns,
     relation/column/sensitivity/`is_active`/LIMIT rules);
   - the **AST guard** (`ast_guard.analyze_sql`, Phase 3.5): an independent
     `sqlglot` parse-tree check enforcing single-SELECT, allowed-view-only, no
     stacked statements, no set operations, no `SELECT *`. This is what closes
     the regex layer's known blind spots (subqueries, CTEs, dollar-quoting).
   - the executor refuses anything not marked valid and runs it read-only and
     row-bounded.

The Phase-0/1 review specifically found **no open SQL-injection path**: every
value is quote-doubled and every identifier is whitelisted.

## Why not bind parameters (yet)

Bind parameters would be the textbook approach, but adopting them is an XL,
cross-cutting change: the generator, template engine, validator and both
executors all pass SQL as a single rendered string today. Threading a
`(sql, params)` pair through the entire pipeline — including the validator,
which inspects the literal text — is a large refactor with its own regression
surface, for a layer where no injection path currently exists.

**Decision:** keep centralized quote-doubling escaping, and rely on the
whitelist + the two structural gates (regex + AST) for safety. Revisit bind
parameters if/when the value-rendering choke points are consolidated further, or
if a code path ever needs to accept a value type the escaper cannot prove safe.

## Invariants any future change must preserve

- Values rendered in exactly one place; never string-concatenate request text
  into SQL elsewhere.
- Identifiers always whitelisted, never escaped-and-trusted.
- Both the regex validator and the AST guard stay enabled
  (`SQLValidatorConfig.enable_ast_guard = True`) on every execution path.
