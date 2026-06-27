"""AST-based structural SQL guard (defense in depth).

The primary SQL safety layer in :mod:`validator` is regex/string based, which the
metadata itself (``sql_validator_rules.yaml``) flags as fragile against
subqueries, CTEs and dollar-quoting. This module adds a second, independent gate
that parses the statement with ``sqlglot`` and enforces the same structural
invariants on the *parse tree* rather than on text:

- exactly one statement (no stacked ``;`` payloads);
- the statement is a single ``SELECT`` (no DML/DDL, no set operations);
- no bare ``SELECT *`` (``COUNT(*)`` is fine);
- every relation is the allowed analytics view or a CTE defined in the query
  (so ``information_schema``/``pg_catalog``/raw tables are rejected even when
  reached through a subquery).

It is deliberately *additive*: the regex validator still runs. If the parser
cannot make sense of the SQL, the guard fails safe (reports a violation) rather
than letting unparseable input through. This module performs no escaping and
does not rewrite SQL; it only inspects and reports.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field

import sqlglot
from sqlglot import exp

logger = logging.getLogger(__name__)

# Nodes that represent a write/DDL/administrative operation. Their mere presence
# anywhere in the tree is disqualifying for a read-only analytics query.
_FORBIDDEN_NODES: tuple[type[exp.Expression], ...] = (
    exp.Insert,
    exp.Update,
    exp.Delete,
    exp.Merge,
    exp.Drop,
    exp.Create,
    exp.Alter,
    exp.TruncateTable,
    exp.Command,  # SET / GRANT / COPY / VACUUM / CALL ... anything sqlglot leaves unmodeled
)

_SET_OPERATIONS: tuple[type[exp.Expression], ...] = (exp.Union, exp.Intersect, exp.Except)


@dataclass(frozen=True)
class AstViolation:
    rule_id: str
    message: str


@dataclass
class AstGuardResult:
    ok: bool
    statement_type: str | None = None
    violations: list[AstViolation] = field(default_factory=list)


def _relation_names(table: exp.Table) -> tuple[str, str]:
    """Return (basename, fully-qualified-name) for a table node, lowercased."""
    name = (table.name or "").lower()
    parts = [p for p in (table.catalog, table.db, table.name) if p]
    full = ".".join(str(p).lower() for p in parts)
    return name, full


def analyze_sql(
    sql: str, *, allowed_view: str, allowed_schema: str | None = None
) -> AstGuardResult:
    """Parse ``sql`` and check the structural invariants of a read-only analytic SELECT."""
    allowed_view = (allowed_view or "").lower()
    allowed_basename = allowed_view.split(".")[-1]
    allowed_schema = (allowed_schema or "").lower() or None

    try:
        statements = [s for s in sqlglot.parse(sql, read="postgres") if s is not None]
    except Exception as exc:
        # Unparseable SQL is treated as unsafe (fail-safe), and logged for audit.
        logger.warning("AST guard could not parse SQL: %s", exc)
        return AstGuardResult(
            ok=False,
            violations=[AstViolation("SQL_AST_PARSE_FAILED", f"SQL could not be parsed: {exc}")],
        )

    if not statements:
        return AstGuardResult(
            ok=False,
            violations=[AstViolation("SQL_AST_EMPTY", "No parseable SQL statement was found.")],
        )

    violations: list[AstViolation] = []
    if len(statements) > 1:
        violations.append(
            AstViolation(
                "SQL_AST_MULTIPLE_STATEMENTS",
                f"Only one statement is allowed; found {len(statements)} (possible stacked injection).",
            )
        )

    root = statements[0]
    statement_type = type(root).__name__.upper()

    if not isinstance(root, exp.Select):
        violations.append(
            AstViolation(
                "SQL_AST_NOT_SELECT",
                f"Top-level statement is {statement_type}; only a single SELECT is allowed.",
            )
        )
        return AstGuardResult(ok=False, statement_type=statement_type, violations=violations)

    # Forbidden write/DDL/admin operations anywhere in the tree.
    if any(isinstance(node, _FORBIDDEN_NODES) for node in root.walk()):
        violations.append(
            AstViolation(
                "SQL_AST_FORBIDDEN_OPERATION", "Write/DDL/administrative operation is not allowed."
            )
        )

    # Set operations (UNION/INTERSECT/EXCEPT) — a classic data-exfiltration vector.
    if any(root.find(op) for op in _SET_OPERATIONS):
        violations.append(
            AstViolation(
                "SQL_AST_SET_OPERATION", "Set operations (UNION/INTERSECT/EXCEPT) are not allowed."
            )
        )

    # Bare SELECT * (COUNT(*) is a function call, not a projection star, so it is fine).
    for select in root.find_all(exp.Select):
        for projection in select.expressions:
            target = projection.this if isinstance(projection, exp.Alias) else projection
            if isinstance(target, exp.Star) or (
                isinstance(target, exp.Column) and isinstance(target.this, exp.Star)
            ):
                violations.append(
                    AstViolation(
                        "SQL_AST_SELECT_STAR", "SELECT * is not allowed; columns must be explicit."
                    )
                )
                break

    # Every relation must be the allowed view or a CTE defined within this query.
    cte_names = {(cte.alias or "").lower() for cte in root.find_all(exp.CTE)}
    for table in root.find_all(exp.Table):
        basename, full = _relation_names(table)
        if basename in cte_names:
            continue
        if full == allowed_view:
            continue
        if basename == allowed_basename and (
            not table.db or (allowed_schema is not None and table.db.lower() == allowed_schema)
        ):
            continue
        violations.append(
            AstViolation(
                "SQL_AST_FORBIDDEN_RELATION",
                f"Relation '{full or basename}' is not the allowed analytics view.",
            )
        )

    return AstGuardResult(ok=not violations, statement_type=statement_type, violations=violations)
