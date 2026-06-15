"""
Controlled Dynamic: patches an existing template SQL with missing WHERE-clause
filters extracted from intent_result. Runs between Template Engine and LLM
Fallback. Only handles known filter columns with safe scalar values.
"""

from __future__ import annotations

from typing import Any

JsonDict = dict[str, Any]

# Maps intent filter column names → SQL column references in the HR view
_COLUMN_MAP: dict[str, str] = {
    "gender": "v.gender",
    "is_contractor": "v.is_contractor",
    "service_years": "v.service_years",
    "age": "v.age",
    "province_name": "v.province_name",
    "education_title": "v.education_title",
    "employment_type": "v.employment_type",
    "contract_type": "v.contract_type",
    "marital_status": "v.marital_status",
    "hire_year": "v.hire_year",
    "department_name": "v.department_name",
}

_SAFE_OPS: frozenset[str] = frozenset({"=", "!=", "<", "<=", ">", ">="})
_SKIP_SOURCES: frozenset[str] = frozenset({"default_rule"})


def _col_in_sql(col: str, sql: str) -> bool:
    return col.upper() in sql.upper()


def _build_clause(f: dict) -> str | None:
    """Return a single SQL AND clause for filter f, or None if not buildable."""
    col = str(f.get("column") or "")
    op = str(f.get("operator") or "=")
    val = f.get("value")
    source = str(f.get("source") or "")

    if not col or val is None:
        return None
    if col not in _COLUMN_MAP:
        return None
    if source in _SKIP_SOURCES:
        return None
    if op not in _SAFE_OPS:
        return None

    db_col = _COLUMN_MAP[col]

    if isinstance(val, bool):
        return f"{db_col} = {'TRUE' if val else 'FALSE'}"
    if isinstance(val, str):
        safe_val = val.replace("'", "''")
        return f"{db_col} {op} '{safe_val}'"
    if isinstance(val, (int, float)):
        return f"{db_col} {op} {val}"

    return None


def _inject_into_where(sql: str, clauses: list[str]) -> str | None:
    """Inject AND clauses before GROUP BY / ORDER BY / LIMIT, after WHERE."""
    sql_up = sql.upper()
    if "WHERE" not in sql_up:
        return None

    inject_pos = len(sql)
    for kw in ("GROUP BY", "ORDER BY", "LIMIT"):
        pos = sql_up.find(kw)
        if 0 < pos < inject_pos:
            inject_pos = pos

    and_block = "\n  AND ".join(clauses)
    return sql[:inject_pos].rstrip() + f"\n  AND {and_block}\n" + sql[inject_pos:]


def apply_controlled_dynamic(
    base_sql: str,
    intent_result: JsonDict,
    missing: list[str] | None = None,
) -> JsonDict:
    """
    Patch base_sql with missing filter clauses from intent_result.

    Args:
        base_sql: The SQL produced by the template engine.
        intent_result: Intent parser output containing filters list.
        missing: Optional coverage-validator missing list. If provided and
                 contains group_by:* or metric:* items, immediately returns
                 CONTROLLED_DYNAMIC_FAILED so the LLM can handle it.

    Returns:
        {"status": "OK", "sql": ..., "source": "controlled_dynamic",
         "patches_applied": [...], "can_execute_sql": True}
        or
        {"status": "CONTROLLED_DYNAMIC_FAILED", "reason": ...,
         "source": "controlled_dynamic"}
    """
    if not base_sql or not base_sql.strip():
        return {
            "status": "CONTROLLED_DYNAMIC_FAILED",
            "source": "controlled_dynamic",
            "reason": "No base SQL provided",
        }

    # If coverage validator told us what's missing, check for non-filter gaps
    if missing is not None:
        non_filter = [m for m in missing if not m.startswith("filter:")]
        if non_filter:
            return {
                "status": "CONTROLLED_DYNAMIC_FAILED",
                "source": "controlled_dynamic",
                "reason": f"Missing non-filter items cannot be patched by CD: {non_filter}",
            }

    filters = intent_result.get("filters") or []
    missing_clauses: list[str] = []

    for f in filters:
        col = str(f.get("column") or "")
        if not col:
            continue
        if _col_in_sql(col, base_sql):
            continue

        source = str(f.get("source") or "")
        if source in _SKIP_SOURCES:
            continue

        clause = _build_clause(f)
        if clause is not None:
            missing_clauses.append(clause)
        else:
            # Unknown or unsupported column that isn't a default_rule — unsafe to skip
            return {
                "status": "CONTROLLED_DYNAMIC_FAILED",
                "source": "controlled_dynamic",
                "reason": (
                    f"Cannot build safe clause for column '{col}' "
                    f"(op={f.get('operator')!r}) — deferring to LLM"
                ),
            }

    if not missing_clauses:
        return {
            "status": "OK",
            "sql": base_sql,
            "source": "controlled_dynamic",
            "patches_applied": [],
            "can_execute_sql": True,
        }

    patched = _inject_into_where(base_sql, missing_clauses)
    if patched is None:
        return {
            "status": "CONTROLLED_DYNAMIC_FAILED",
            "source": "controlled_dynamic",
            "reason": "SQL has no WHERE clause — cannot safely inject filters",
        }

    return {
        "status": "OK",
        "sql": patched,
        "source": "controlled_dynamic",
        "patches_applied": missing_clauses,
        "can_execute_sql": True,
    }
