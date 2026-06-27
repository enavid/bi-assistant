from __future__ import annotations

import re
from dataclasses import dataclass, field

_AGGREGATE_FUNCS = re.compile(r"\b(AVG|MAX|MIN|STDDEV|SUM)\b", re.IGNORECASE)

_SKIP_COLUMNS = {"is_active"}
_SKIP_SOURCES = {"default_rule"}

_COUNT_FUNCS = {"COUNT"}


def _column_present(col: str, sql_upper: str) -> bool:
    """True only when `col` appears as a standalone token in the SQL.

    A plain substring check counted `age` as present inside `age_group_title`
    or `province` inside `province_name`, so coverage reported COMPLETE for SQL
    that silently dropped the user's real filter. Word boundaries fix that.
    """
    return re.search(rf"\b{re.escape(col)}\b", sql_upper, flags=re.IGNORECASE) is not None


@dataclass
class CoverageResult:
    is_complete: bool
    missing: list[str]
    status: str
    unused_params: list[str] = field(default_factory=list)


def validate_coverage(intent_result: dict, sql: str) -> CoverageResult:
    """Check that every user-requested constraint appears in the generated SQL.

    Skips is_active and any filter injected by the pipeline (source=default_rule),
    since those are guaranteed by the template and are not user-requested filters.
    Returns CoverageResult with a list of missing items and a status string.
    """
    missing: list[str] = []
    sql_upper = sql.upper()

    # --- filters ---
    for f in intent_result.get("filters", []):
        if not isinstance(f, dict):
            continue
        col = f.get("column", "")
        if not col:
            continue
        if col in _SKIP_COLUMNS:
            continue
        if f.get("source") in _SKIP_SOURCES:
            continue
        if not _column_present(col, sql_upper):
            missing.append(f"filter:{col}")

    # --- group_by ---
    for g in intent_result.get("group_by", []):
        col = g if isinstance(g, str) else (g.get("column", "") if isinstance(g, dict) else "")
        if not col:
            continue
        if not _column_present(col, sql_upper):
            missing.append(f"group_by:{col}")

    # --- metrics — only non-COUNT aggregate functions ---
    for metric in intent_result.get("metrics", []):
        if not isinstance(metric, dict):
            continue
        expression = metric.get("expression", "")
        funcs = _AGGREGATE_FUNCS.findall(expression)
        for func in funcs:
            if func.upper() in _COUNT_FUNCS:
                continue
            if func.upper() not in sql_upper:
                missing.append(f"metric:{func.upper()}")

    # --- superlative / result_limit ---
    params = intent_result.get("params", {})
    if params.get("result_limit") == 1:
        if "LIMIT" not in sql_upper:
            missing.append("LIMIT")

    is_complete = len(missing) == 0
    return CoverageResult(
        is_complete=is_complete,
        missing=missing,
        status="COMPLETE" if is_complete else "COVERAGE_INCOMPLETE",
    )
