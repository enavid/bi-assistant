from __future__ import annotations

import asyncio
import os
import re
import textwrap
import time
from collections.abc import Iterable, Mapping
from copy import deepcopy
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any

from app.infrastructure.metadata.service import get_metadata_service
from app.use_cases.hr_analytics.sql.llm_fallback import LLMSQLFallback

"""
sql_generator.py
----------------
Controlled dynamic SQL generator for HR BI Assistant Phase 2.


Responsibility:
    - Build a safe fallback SQL statement when sql_template_engine.py cannot
      resolve a template.
    - Use only structured metadata/intent/semantic outputs.
    - Generate SELECT-only SQL against the single analytics View.

Important:
    This module is intentionally NOT a free-form Text-to-SQL agent.
    It does not query raw tables, does not create JOINs, and does not execute SQL.
    Every generated query must still pass sql_validator.py before execution.
"""


JsonDict = dict[str, Any]

ROUTE_SQL = "SQL"
ROUTE_GAP = "GAP"
ROUTE_REJECT = "REJECT"
ROUTE_CLARIFICATION = "NEEDS_CLARIFICATION"

STATUS_OK = "OK"
STATUS_VALID = "VALID"
STATUS_SUPPORTED = "supported"
STATUS_DATA_GAP = "DATA_GAP"
STATUS_ACCESS_DENIED = "ACCESS_DENIED"
STATUS_OUT_OF_SCOPE = "OUT_OF_SCOPE"
STATUS_NEEDS_CLARIFICATION = "NEEDS_CLARIFICATION"
STATUS_SQL_VALIDATION_FAILED = "SQL_VALIDATION_FAILED"

DEFAULT_MAIN_VIEW = "hr_mvp.vw_hr_employee_analytics"
DEFAULT_ALIAS = "v"

PERSIAN_DIGITS = "۰۱۲۳۴۵۶۷۸۹"
ARABIC_DIGITS = "٠١٢٣٤٥٦٧٨٩"
EN_DIGITS = "0123456789"
DIGIT_TRANSLATION = str.maketrans(
    {
        **{p: e for p, e in zip(PERSIAN_DIGITS, EN_DIGITS)},
        **{a: e for a, e in zip(ARABIC_DIGITS, EN_DIGITS)},
    }
)

SAFE_COLUMN_RE = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")
SAFE_ALIAS_RE = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")
SAFE_ARITHMETIC_EXPRESSION_RE = re.compile(
    r"^\s*\d{1,4}\s*(?:[+\-]\s*\d{1,4})?\s*$")

TERMINAL_STATUSES = {
    STATUS_DATA_GAP,
    STATUS_ACCESS_DENIED,
    STATUS_OUT_OF_SCOPE,
    STATUS_NEEDS_CLARIFICATION,
    STATUS_SQL_VALIDATION_FAILED,
}

DANGEROUS_SQL_TOKENS = {
    "insert",
    "update",
    "delete",
    "drop",
    "alter",
    "create",
    "truncate",
    "grant",
    "revoke",
    "copy",
    "execute",
    "call",
    "merge",
}

SENSITIVE_COLUMNS = {
    "national_id",
    "personnel_number",
    "first_name",
    "last_name",
    "full_name",
    "phone_number",
    "mobile",
    "address",
    "bank_account",
    "insurance_number",
    "salary",
    "wage",
    "personal_identifier",
}

# Conservative mapping used only when upstream intent/semantic results do not
# provide explicit group_by columns.
DEFAULT_GROUP_BY_BY_INTENT: dict[str, list[str]] = {
    "employee_count_by_gender": ["gender"],
    "employee_count_by_age_group": ["age_group_title"],
    "employee_count_by_education": ["education_title"],
    "employee_count_by_employment_type": ["employment_type"],
    "employee_count_by_contract_type": ["contract_type"],
    "employee_count_by_service_domain": ["service_domain"],
    "employee_count_by_department": ["department_name"],
    "employee_count_by_province": ["province"],
    "employee_count_by_work_location": ["site_name"],
    "employee_count_by_marital_status": ["marital_status"],
    "contractor_share_by_service_domain": ["service_domain"],
    "hiring_trend_annual": ["hire_year"],
    "hiring_last_15_years": ["hire_year"],
    "most_or_least_hiring_year": ["hire_year"],
    "hiring_by_contract_type_recent_year": ["contract_type"],
    "headcount_gap_by_department": ["department_id", "department_name"],
}

STATUS_SQL_FALLBACKS: dict[str, str] = {
    STATUS_DATA_GAP: "SELECT 'DATA_GAP' AS status;",
    STATUS_ACCESS_DENIED: "SELECT 'ACCESS_DENIED' AS status;",
    STATUS_OUT_OF_SCOPE: "SELECT 'OUT_OF_SCOPE' AS status;",
    STATUS_NEEDS_CLARIFICATION: "SELECT 'NEEDS_CLARIFICATION' AS status;",
    STATUS_SQL_VALIDATION_FAILED: "SELECT 'SQL_VALIDATION_FAILED' AS status;",
}


class SQLGeneratorError(RuntimeError):
    """Base exception for controlled SQL generation failures."""


@dataclass
class SQLGeneratorConfig:
    """Runtime configuration for SQLGenerator."""

    current_shamsi_year: int = 1404
    main_view: str = DEFAULT_MAIN_VIEW
    alias: str = DEFAULT_ALIAS
    source_name: str = "sql_generator"
    max_grouped_limit: int = 100
    max_table_limit: int = 200
    allow_dynamic_generation: bool = True
    include_default_active_filter: bool = True
    reject_unknown_columns: bool = True
    allow_select_birth_or_date_columns: bool = False
    # This generator deliberately stays rule-based in Phase 2.
    allow_llm_freeform_sql: bool = field(default_factory=lambda: os.getenv(
        "ENABLE_LLM_SQL_FALLBACK", "true").strip().lower() in {"1", "true", "yes", "on"})


@dataclass
class SQLGenerationResult:
    status: str
    route: str
    source: str
    sql: str | None = None
    can_execute_sql: bool = False
    generation_mode: str = "none"
    intent: str | None = None
    intent_id: str | None = None
    detected_intent: str | None = None
    report_id: str | None = None
    template_id: str | None = None
    output_type: str | None = None
    visualization_hint: str | None = None
    result_columns: list[JsonDict] = field(default_factory=list)
    params: JsonDict = field(default_factory=dict)
    reason: str | None = None
    confidence: float | None = None
    warnings: list[str] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)
    metadata: JsonDict = field(default_factory=dict)
    duration_ms: float | None = None

    def to_dict(self) -> JsonDict:
        return asdict(self)


class SQLGenerator:
    """
    Controlled SQL generator for the HR BI Assistant.

    Public API supported by llm_orchestrator.py:
        generator.generate(question=..., context=..., metadata=...)
        generator.run(...)
        await generator.arun(...)
        generator(...)

    The generator uses only:
        - RequestContext.intent_result
        - RequestContext.semantic_result
        - RequestContext.route_result
        - MetadataService column allowlist

    It returns a plan dictionary. It never executes SQL.
    """

    def __init__(
        self,
        metadata_service: Any | None = None,
        *,
        metadata_dir: str | Path | None = None,
        current_shamsi_year: int | None = None,
        config: SQLGeneratorConfig | None = None,
        llm_sql_fallback: Any | None = None,
    ) -> None:
        if metadata_service is not None:
            self.metadata = metadata_service
        elif get_metadata_service is not None:
            self.metadata = get_metadata_service(
                metadata_dir=metadata_dir, strict=False)
        else:
            self.metadata = None

        self.config = config or SQLGeneratorConfig()
        self.llm_sql_fallback = llm_sql_fallback
        if current_shamsi_year is not None:
            self.config.current_shamsi_year = int(current_shamsi_year)

        main_view = self._read_main_view(self.metadata)
        if main_view:
            self.config.main_view = main_view.get("name") or main_view.get(
                "relation") or self.config.main_view
            self.config.alias = main_view.get("alias") or self.config.alias

        if self.llm_sql_fallback is None and LLMSQLFallback is not None and self.config.allow_llm_freeform_sql:
            try:
                self.llm_sql_fallback = LLMSQLFallback(
                    metadata_service=self.metadata)
            except Exception:
                self.llm_sql_fallback = None

        detected_year = self._read_default_current_shamsi_year(self.metadata)
        if current_shamsi_year is None and detected_year:
            self.config.current_shamsi_year = detected_year

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def generate(
        self,
        *,
        question: str | None = None,
        schema_context: str | None = None,
        context: Any | None = None,
        metadata: Any | None = None,
        intent_result: Mapping[str, Any] | None = None,
        semantic_result: Mapping[str, Any] | None = None,
        route_result: Mapping[str, Any] | None = None,
        validation_result: Mapping[str, Any] | None = None,
        runtime_params: Mapping[str, Any] | None = None,
        **kwargs: Any,
    ) -> JsonDict:
        started = time.perf_counter()
        service = metadata or self.metadata

        if not self.config.allow_dynamic_generation:
            return self._result(
                status="DISABLED",
                route=ROUTE_REJECT,
                sql=None,
                can_execute_sql=False,
                reason="Dynamic SQL generation is disabled.",
                errors=["SQLGenerator is disabled by configuration."],
                started=started,
            ).to_dict()

        if service is None:
            return self._result(
                status="METADATA_ERROR",
                route=ROUTE_REJECT,
                sql=None,
                can_execute_sql=False,
                reason="Metadata service is not available.",
                errors=["Metadata service is not available."],
                started=started,
            ).to_dict()

        intent_payload = self._payload_from(
            context, "intent_result", intent_result)
        semantic_payload = self._payload_from(
            context, "semantic_result", semantic_result)
        route_payload = self._payload_from(
            context, "route_result", route_result)
        validation_payload = self._payload_from(
            context, "validation_result", validation_result)
        runtime_payload = self._runtime_params_from(
            context, runtime_params, kwargs)

        raw_question = (
            question
            or self._get_context_value(context, "normalized_question")
            or self._get_context_value(context, "question")
            or intent_payload.get("normalized_question")
            or intent_payload.get("question")
            or ""
        )
        normalized_question = self.normalize_text(str(raw_question))

        terminal = self._terminal_plan_if_needed(
            service=service,
            route_payload=route_payload,
            intent_payload=intent_payload,
            validation_payload=validation_payload,
            started=started,
        )
        if terminal is not None:
            return terminal.to_dict()

        route = self._first_non_empty(route_payload.get(
            "route"), intent_payload.get("route"), ROUTE_SQL)
        if str(route).upper() != ROUTE_SQL:
            return self._status_result(
                service,
                status=STATUS_DATA_GAP if str(route).upper(
                ) == ROUTE_GAP else STATUS_NEEDS_CLARIFICATION,
                route=str(route).upper(),
                reason="Non-SQL route was selected before SQL generation.",
                started=started,
            ).to_dict()

        intent_id = self._first_non_empty(
            intent_payload.get("intent_id"),
            intent_payload.get("intent"),
            route_payload.get("intent_id"),
            route_payload.get("intent"),
            route_payload.get("detected_intent"),
        )
        intent_id = str(intent_id) if intent_id else None

        if not intent_id:
            return self._status_result(
                service,
                status=STATUS_NEEDS_CLARIFICATION,
                route=ROUTE_CLARIFICATION,
                reason="No intent_id was available for controlled SQL generation.",
                started=started,
            ).to_dict()

        allowed_columns = self._allowed_column_map(service)
        params = self._merge_params(
            intent_payload, semantic_payload, route_payload, runtime_payload)
        filters = self._collect_filters(
            intent_payload, semantic_payload, runtime_payload)
        group_by = self._collect_group_by(
            intent_id, intent_payload, semantic_payload)
        order_by = self._normalize_order_by(intent_payload.get(
            "order_by") or route_payload.get("order_by") or [])

        # Runtime/year placeholders must be resolved outside the LLM. If upstream
        # did not provide one, use config default.
        params.setdefault("current_shamsi_year",
                          self.config.current_shamsi_year)

        try:
            sql, result_columns, output_type = self._build_sql_for_intent(
                intent_id=intent_id,
                question=normalized_question,
                service=service,
                allowed_columns=allowed_columns,
                filters=filters,
                group_by=group_by,
                order_by=order_by,
                params=params,
            )
        except SQLGeneratorError as exc:
            if self._should_try_llm_fallback(
                service=service,
                intent_payload=intent_payload,
                route_payload=route_payload,
                validation_payload=validation_payload,
                allowed_columns=allowed_columns,
            ):
                return self._call_llm_sql_fallback(
                    question=normalized_question,
                    schema_context=schema_context,
                    context=context,
                    metadata=service,
                    started=started,
                    reason=str(exc),
                )
            return self._status_result(
                service,
                status=STATUS_DATA_GAP,
                route=ROUTE_GAP,
                reason=str(exc),
                started=started,
                warnings=[
                    "Controlled SQL generator could not safely build a query and LLM fallback was not allowed."],
            ).to_dict()
        except Exception as exc:  # pragma: no cover - defensive runtime safety
            return self._result(
                status="GENERATION_FAILED",
                route=ROUTE_REJECT,
                sql=None,
                can_execute_sql=False,
                reason="SQL generation failed unexpectedly.",
                errors=[str(exc)],
                started=started,
            ).to_dict()

        warnings = self._light_sql_safety_warnings(sql)
        if warnings:
            return self._result(
                status=STATUS_SQL_VALIDATION_FAILED,
                route=ROUTE_REJECT,
                sql=STATUS_SQL_FALLBACKS[STATUS_SQL_VALIDATION_FAILED],
                can_execute_sql=False,
                intent=intent_id,
                intent_id=intent_id,
                detected_intent=intent_id,
                reason="Generated SQL failed lightweight generator safety checks.",
                warnings=warnings,
                generation_mode="controlled_dynamic",
                started=started,
            ).to_dict()

        visualization_hint = (
            intent_payload.get("recommended_visualization")
            or intent_payload.get("visualization_hint")
            or intent_payload.get("output_type")
        )
        report_id = self._first_non_empty(intent_payload.get(
            "report_id"), route_payload.get("report_id"))
        template_id = self._first_non_empty(intent_payload.get(
            "sql_template_id"), route_payload.get("sql_template_id"))

        return self._result(
            status=STATUS_OK,
            route=ROUTE_SQL,
            sql=sql,
            can_execute_sql=True,
            intent=intent_id,
            intent_id=intent_id,
            detected_intent=intent_id,
            report_id=str(report_id) if report_id else None,
            template_id=str(template_id) if template_id else None,
            output_type=output_type or self._infer_output_type(
                intent_id, group_by),
            visualization_hint=str(
                visualization_hint) if visualization_hint else None,
            result_columns=result_columns,
            params=params,
            reason="SQL was generated by controlled metadata-based fallback rules.",
            generation_mode="controlled_dynamic",
            confidence=float(intent_payload.get("confidence")) if self._is_number(
                intent_payload.get("confidence")) else None,
            metadata={
                "question": normalized_question,
                "schema_context_supplied": bool(schema_context),
                "group_by": group_by,
                "filters": filters,
                "order_by": order_by,
                "main_view": self.config.main_view,
                "alias": self.config.alias,
            },
            warnings=[],
            started=started,
        ).to_dict()

    def run(self, **kwargs: Any) -> JsonDict:
        return self.generate(**kwargs)

    async def arun(self, **kwargs: Any) -> JsonDict:
        return await asyncio.to_thread(self.generate, **kwargs)

    def __call__(self, **kwargs: Any) -> JsonDict:
        return self.generate(**kwargs)

    def _should_try_llm_fallback(
        self,
        *,
        service: Any,
        intent_payload: Mapping[str, Any],
        route_payload: Mapping[str, Any],
        validation_payload: Mapping[str, Any],
        allowed_columns: dict[str, JsonDict],
    ) -> bool:
        if not self.config.allow_llm_freeform_sql or self.llm_sql_fallback is None:
            return False
        route = str(route_payload.get("route")
                    or intent_payload.get("route") or "SQL").upper()
        status = str(validation_payload.get("status")
                     or intent_payload.get("status") or "VALID").upper()
        if route != ROUTE_SQL:
            return False
        if status in TERMINAL_STATUSES and status != STATUS_VALID:
            return False
        required_columns = intent_payload.get(
            "required_columns") or route_payload.get("required_columns") or []
        for col in required_columns:
            if isinstance(col, str) and col and col not in allowed_columns:
                return False
        return True

    def _call_llm_sql_fallback(
        self,
        *,
        question: str,
        schema_context: str | None,
        context: Any,
        metadata: Any,
        started: float,
        reason: str,
    ) -> JsonDict:
        if self.llm_sql_fallback is None:
            return self._result(
                status="NEEDS_LLM_SQL_FALLBACK",
                route=ROUTE_SQL,
                sql=None,
                can_execute_sql=False,
                reason=f"Controlled generator could not build SQL and LLM fallback is not configured: {reason}",
                generation_mode="llm_fallback_required",
                warnings=[
                    "Configure ENABLE_LLM_SQL_FALLBACK and LLM_PROVIDER to enable model fallback."],
                started=started,
            ).to_dict()
        try:
            result = self.llm_sql_fallback.generate(
                question=question,
                context=context,
                metadata=metadata,
                schema_context=schema_context,
            )
            out = dict(result or {})
            out.setdefault("route", ROUTE_SQL)
            out.setdefault("source", "llm_sql_fallback")
            out.setdefault("generation_mode", "llm_fallback")
            out.setdefault(
                "reason", f"Controlled generator fallback was used because: {reason}")
            out.setdefault("duration_ms", round(
                (time.perf_counter() - started) * 1000, 3))
            return out
        except Exception as exc:
            return self._result(
                status="LLM_FALLBACK_FAILED",
                route=ROUTE_REJECT,
                sql=None,
                can_execute_sql=False,
                reason="LLM SQL fallback failed.",
                generation_mode="llm_fallback_failed",
                errors=[f"{type(exc).__name__}: {exc}"],
                started=started,
            ).to_dict()

    # ------------------------------------------------------------------
    # SQL builders by intent
    # ------------------------------------------------------------------

    def _build_sql_for_intent(
        self,
        *,
        intent_id: str,
        question: str,
        service: Any,
        allowed_columns: dict[str, JsonDict],
        filters: list[JsonDict],
        group_by: list[str],
        order_by: list[str],
        params: JsonDict,
    ) -> tuple[str, list[JsonDict], str | None]:
        if intent_id in {
            "total_employee_count",
            "employee_count_by_age_filter",
            "employee_count_without_service_years",
        }:
            effective_filters = filters
            if intent_id == "employee_count_without_service_years":
                effective_filters = self._ensure_filter(
                    filters, "service_years", "=", 0)
            sql = self._count_sql(filters=effective_filters,
                                  allowed_columns=allowed_columns)
            return sql, [{"name": "employee_count", "data_type": "integer"}], "kpi_card"

        if intent_id in {
            "employee_count_by_gender",
            "employee_count_by_age_group",
            "employee_count_by_education",
            "employee_count_by_employment_type",
            "employee_count_by_contract_type",
            "employee_count_by_service_domain",
            "employee_count_by_department",
            "employee_count_by_province",
            "employee_count_by_work_location",
            "employee_count_by_marital_status",
            "employee_count_by_gender_age_filter",
        }:
            # If a specific value is filtered (e.g. "how many employees have a bachelor's degree?"),
            # return a KPI count. Otherwise return grouped count.
            if not group_by or self._has_specific_filter_for_group(group_by, filters):
                group_by = self._group_by_if_no_specific_filter(
                    intent_id, group_by, filters)
            if not group_by:
                sql = self._count_sql(
                    filters=filters, allowed_columns=allowed_columns)
                return sql, [{"name": "employee_count", "data_type": "integer"}], "kpi_card"
            return self._grouped_count_sql(
                group_by=group_by,
                filters=filters,
                allowed_columns=allowed_columns,
                order_by=order_by or ["employee_count DESC"],
                maybe_limit=self._maybe_extreme_limit(question),
                include_percentage=True,
            ), self._columns_for_grouped_count(group_by), self._visual_for_grouped_count(group_by)

        if intent_id == "gender_percentage":
            gender_value = params.get(
                "gender_value") or self._extract_filter_value(filters, "gender")
            if gender_value not in {"زن", "مرد"}:
                raise SQLGeneratorError(
                    "gender_percentage requires a safe gender_value of 'زن' or 'مرد'.")
            sql = self._percentage_sql(
                numerator_condition=self._condition(
                    "gender", "=", gender_value, allowed_columns),
                count_alias="matched_employee_count",
                percentage_alias="percentage",
                filters=self._drop_filter(filters, "gender"),
                allowed_columns=allowed_columns,
            )
            return sql, [
                {"name": "matched_employee_count", "data_type": "integer"},
                {"name": "total_employee_count", "data_type": "integer"},
                {"name": "percentage", "data_type": "numeric"},
            ], "kpi_card"

        if intent_id == "average_age":
            return self._average_sql(
                metric_column="age",
                alias="average_age",
                group_by=group_by,
                filters=filters,
                allowed_columns=allowed_columns,
            ), self._columns_for_average(group_by, "average_age"), self._visual_for_average(group_by)

        if intent_id == "average_service_years":
            return self._average_sql(
                metric_column="service_years",
                alias="average_service_years",
                group_by=group_by,
                filters=filters,
                allowed_columns=allowed_columns,
            ), self._columns_for_average(group_by, "average_service_years"), self._visual_for_average(group_by)

        if intent_id in {"most_common_education", "least_common_education"}:
            direction = "ASC" if intent_id == "least_common_education" else "DESC"
            sql = self._grouped_count_sql(
                group_by=["education_title"],
                filters=filters,
                allowed_columns=allowed_columns,
                order_by=[f"employee_count {direction}"],
                limit=1,
                include_percentage=False,
            )
            return sql, self._columns_for_grouped_count(["education_title"], include_percentage=False), "kpi_card_or_table"

        if intent_id == "low_education_in_expert_roles":
            effective_filters = self._ensure_filter(
                filters, "education_rank", "<", None, value_column="min_education_rank")
            effective_filters = self._ensure_filter(
                effective_filters, "is_expert_role", "=", True)
            sql = self._count_sql(filters=effective_filters,
                                  allowed_columns=allowed_columns)
            return sql, [{"name": "employee_count", "data_type": "integer"}], "kpi_card"

        if intent_id == "contractor_share":
            sql = self._percentage_sql(
                numerator_condition=self._condition(
                    "is_contractor", "=", True, allowed_columns),
                count_alias="contractor_count",
                percentage_alias="contractor_percentage",
                filters=self._drop_filter(filters, "is_contractor"),
                allowed_columns=allowed_columns,
            )
            return sql, [
                {"name": "contractor_count", "data_type": "integer"},
                {"name": "total_employee_count", "data_type": "integer"},
                {"name": "contractor_percentage", "data_type": "numeric"},
            ], "kpi_card"

        if intent_id == "contractor_share_by_service_domain":
            effective_group_by = group_by or ["service_domain"]
            sql = self._grouped_percentage_sql(
                group_by=effective_group_by,
                numerator_condition=self._condition(
                    "is_contractor", "=", True, allowed_columns),
                count_alias="contractor_count",
                percentage_alias="contractor_percentage",
                filters=self._drop_filter(filters, "is_contractor"),
                allowed_columns=allowed_columns,
                order_by=["contractor_percentage DESC"],
            )
            return sql, [
                *[{"name": col, "data_type": self._column_type(
                    col, allowed_columns)} for col in effective_group_by],
                {"name": "contractor_count", "data_type": "integer"},
                {"name": "total_employee_count", "data_type": "integer"},
                {"name": "contractor_percentage", "data_type": "numeric"},
            ], "bar_chart_or_table"

        if intent_id == "hiring_trend_annual":
            sql = self._grouped_count_sql(
                group_by=["hire_year"],
                filters=filters,
                allowed_columns=allowed_columns,
                order_by=["v.hire_year ASC"],
                include_percentage=False,
            )
            return sql, self._columns_for_grouped_count(["hire_year"], include_percentage=False), "line_chart"

        if intent_id == "hiring_last_15_years":
            year = int(params.get("current_shamsi_year")
                       or self.config.current_shamsi_year)
            effective_filters = self._ensure_filter(
                filters, "hire_year", ">=", None, value_expression=f"{year} - 15")
            sql = self._grouped_count_sql(
                group_by=["hire_year"],
                filters=effective_filters,
                allowed_columns=allowed_columns,
                order_by=["v.hire_year ASC"],
                include_percentage=False,
            )
            return sql, self._columns_for_grouped_count(["hire_year"], include_percentage=False), "line_chart_or_table"

        if intent_id == "most_or_least_hiring_year":
            direction = "ASC" if self._asks_least(
                question, order_by) else "DESC"
            sql = self._grouped_count_sql(
                group_by=["hire_year"],
                filters=filters,
                allowed_columns=allowed_columns,
                order_by=[f"employee_count {direction}"],
                limit=1,
                include_percentage=False,
            )
            return sql, self._columns_for_grouped_count(["hire_year"], include_percentage=False), "kpi_card_or_table"

        if intent_id == "hiring_by_contract_type_recent_year":
            year = int(params.get("current_shamsi_year")
                       or self.config.current_shamsi_year)
            effective_filters = self._ensure_filter(
                filters, "hire_year", "=", year)
            sql = self._grouped_count_sql(
                group_by=["contract_type"],
                filters=effective_filters,
                allowed_columns=allowed_columns,
                order_by=["employee_count DESC"],
                include_percentage=True,
            )
            return sql, self._columns_for_grouped_count(["contract_type"]), "horizontal_bar_chart_or_table"

        if intent_id == "headcount_gap_by_department":
            sql = self._headcount_gap_sql(
                filters=filters, allowed_columns=allowed_columns, question=question)
            return sql, [
                {"name": "department_id", "data_type": self._column_type(
                    "department_id", allowed_columns)},
                {"name": "department_name", "data_type": self._column_type(
                    "department_name", allowed_columns)},
                {"name": "actual_headcount", "data_type": "integer"},
                {"name": "approved_headcount", "data_type": "integer"},
                {"name": "headcount_gap", "data_type": "integer"},
            ], "table"

        if intent_id in {
            "city_level_analysis",
            "near_retirement_analysis",
            "contractor_productivity_analysis",
            "hiring_business_growth_alignment",
            "education_training_need_analysis",
            "workforce_aging_trend_analysis",
            "department_balance_analysis",
        }:
            raise SQLGeneratorError(
                f"Intent '{intent_id}' is a Data Gap intent, not a SQL intent.")

        # Last safe fallback: if upstream provided a valid group_by, generate a
        # grouped count. Otherwise, do not guess.
        if group_by:
            sql = self._grouped_count_sql(
                group_by=group_by,
                filters=filters,
                allowed_columns=allowed_columns,
                order_by=order_by or ["employee_count DESC"],
                maybe_limit=self._maybe_extreme_limit(question),
                include_percentage=True,
            )
            return sql, self._columns_for_grouped_count(group_by), self._visual_for_grouped_count(group_by)

        raise SQLGeneratorError(
            f"No controlled dynamic SQL rule exists for intent '{intent_id}'.")

    # ------------------------------------------------------------------
    # SQL fragments
    # ------------------------------------------------------------------

    def _count_sql(self, *, filters: list[JsonDict], allowed_columns: dict[str, JsonDict]) -> str:
        where_sql = self._where_clause(filters, allowed_columns)
        return self._format_sql(
            f"""
            SELECT
                COUNT(v.employee_id) AS employee_count
            FROM {self.config.main_view} {self.config.alias}
            {where_sql};
            """
        )

    def _grouped_count_sql(
        self,
        *,
        group_by: list[str],
        filters: list[JsonDict],
        allowed_columns: dict[str, JsonDict],
        order_by: list[str] | None = None,
        limit: int | None = None,
        maybe_limit: int | None = None,
        include_percentage: bool = True,
    ) -> str:
        safe_group_by = self._safe_columns(group_by, allowed_columns)
        if not safe_group_by:
            raise SQLGeneratorError(
                "Grouped count requires at least one safe group_by column.")

        select_group = ",\n    ".join(f"v.{col}" for col in safe_group_by)
        group_by_sql = ", ".join(f"v.{col}" for col in safe_group_by)
        where_sql = self._where_clause(filters, allowed_columns)
        percentage_sql = ""
        if include_percentage:
            percentage_sql = ",\n    ROUND(COUNT(v.employee_id) * 100.0 / NULLIF(SUM(COUNT(v.employee_id)) OVER (), 0), 2) AS percentage"
        order_sql = self._order_by_clause(order_by, safe_group_by=safe_group_by, allowed_aliases={
                                          "employee_count", "percentage"})
        effective_limit = limit if limit is not None else maybe_limit
        limit_sql = self._limit_clause(effective_limit)
        return self._format_sql(
            f"""
            SELECT
                {select_group},
                COUNT(v.employee_id) AS employee_count{percentage_sql}
            FROM {self.config.main_view} {self.config.alias}
            {where_sql}
            GROUP BY {group_by_sql}
            {order_sql}
            {limit_sql};
            """
        )

    def _average_sql(
        self,
        *,
        metric_column: str,
        alias: str,
        group_by: list[str],
        filters: list[JsonDict],
        allowed_columns: dict[str, JsonDict],
    ) -> str:
        self._assert_safe_column(metric_column, allowed_columns)
        self._assert_safe_alias(alias)
        where_sql = self._where_clause(filters, allowed_columns)
        safe_group_by = self._safe_columns(group_by, allowed_columns)
        if safe_group_by:
            select_group = ",\n    ".join(f"v.{col}" for col in safe_group_by)
            group_by_sql = ", ".join(f"v.{col}" for col in safe_group_by)
            return self._format_sql(
                f"""
                SELECT
                    {select_group},
                    ROUND(AVG(v.{metric_column}), 2) AS {alias}
                FROM {self.config.main_view} {self.config.alias}
                {where_sql}
                GROUP BY {group_by_sql}
                ORDER BY {alias} DESC;
                """
            )
        return self._format_sql(
            f"""
            SELECT
                ROUND(AVG(v.{metric_column}), 2) AS {alias}
            FROM {self.config.main_view} {self.config.alias}
            {where_sql};
            """
        )

    def _percentage_sql(
        self,
        *,
        numerator_condition: str,
        count_alias: str,
        percentage_alias: str,
        filters: list[JsonDict],
        allowed_columns: dict[str, JsonDict],
    ) -> str:
        self._assert_safe_alias(count_alias)
        self._assert_safe_alias(percentage_alias)
        where_sql = self._where_clause(filters, allowed_columns)
        return self._format_sql(
            f"""
            SELECT
                SUM(CASE WHEN {numerator_condition} THEN 1 ELSE 0 END) AS {count_alias},
                COUNT(v.employee_id) AS total_employee_count,
                ROUND(
                    SUM(CASE WHEN {numerator_condition} THEN 1 ELSE 0 END) * 100.0
                    / NULLIF(COUNT(v.employee_id), 0),
                    2
                ) AS {percentage_alias}
            FROM {self.config.main_view} {self.config.alias}
            {where_sql};
            """
        )

    def _grouped_percentage_sql(
        self,
        *,
        group_by: list[str],
        numerator_condition: str,
        count_alias: str,
        percentage_alias: str,
        filters: list[JsonDict],
        allowed_columns: dict[str, JsonDict],
        order_by: list[str] | None = None,
    ) -> str:
        safe_group_by = self._safe_columns(group_by, allowed_columns)
        if not safe_group_by:
            raise SQLGeneratorError(
                "Grouped percentage requires at least one safe group_by column.")
        select_group = ",\n    ".join(f"v.{col}" for col in safe_group_by)
        group_by_sql = ", ".join(f"v.{col}" for col in safe_group_by)
        where_sql = self._where_clause(filters, allowed_columns)
        order_sql = self._order_by_clause(
            order_by or [f"{percentage_alias} DESC"],
            safe_group_by=safe_group_by,
            allowed_aliases={count_alias,
                             "total_employee_count", percentage_alias},
        )
        return self._format_sql(
            f"""
            SELECT
                {select_group},
                SUM(CASE WHEN {numerator_condition} THEN 1 ELSE 0 END) AS {count_alias},
                COUNT(v.employee_id) AS total_employee_count,
                ROUND(
                    SUM(CASE WHEN {numerator_condition} THEN 1 ELSE 0 END) * 100.0
                    / NULLIF(COUNT(v.employee_id), 0),
                    2
                ) AS {percentage_alias}
            FROM {self.config.main_view} {self.config.alias}
            {where_sql}
            GROUP BY {group_by_sql}
            {order_sql};
            """
        )

    def _headcount_gap_sql(self, *, filters: list[JsonDict], allowed_columns: dict[str, JsonDict], question: str) -> str:
        for col in ["department_id", "department_name", "department_approved_headcount"]:
            self._assert_safe_column(col, allowed_columns)
        where_sql = self._where_clause(filters, allowed_columns)
        having = ""
        if any(term in question for term in ["کمبود", "کمبود نیرو", "کمتر از چارت"]):
            having = "HAVING MAX(v.department_approved_headcount) > COUNT(v.employee_id)"
        return self._format_sql(
            f"""
            SELECT
                v.department_id,
                v.department_name,
                COUNT(v.employee_id) AS actual_headcount,
                MAX(v.department_approved_headcount) AS approved_headcount,
                MAX(v.department_approved_headcount) - COUNT(v.employee_id) AS headcount_gap
            FROM {self.config.main_view} {self.config.alias}
            {where_sql}
            GROUP BY v.department_id, v.department_name
            {having}
            ORDER BY headcount_gap DESC;
            """
        )

    # ------------------------------------------------------------------
    # WHERE / conditions / rendering
    # ------------------------------------------------------------------

    def _where_clause(self, filters: list[JsonDict], allowed_columns: dict[str, JsonDict]) -> str:
        conditions: list[str] = []

        if self.config.include_default_active_filter and "is_active" in allowed_columns:
            conditions.append("v.is_active = TRUE")

        for item in filters:
            if not isinstance(item, dict):
                continue
            if item.get("scope") == "numerator":
                continue
            column = item.get("column")
            if column == "is_active":
                # Avoid duplicate active filters; default already added.
                continue
            if not column:
                continue
            condition = self._render_filter(item, allowed_columns)
            if condition and condition not in conditions:
                conditions.append(condition)

        if not conditions:
            return ""
        return "WHERE " + "\n  AND ".join(conditions)

    def _render_filter(self, item: Mapping[str, Any], allowed_columns: dict[str, JsonDict]) -> str | None:
        column = str(item.get("column") or "").strip()
        if not column:
            return None
        operator = str(item.get("operator") or "=").strip().upper()
        return self._condition(
            column,
            operator,
            item.get("value"),
            allowed_columns,
            value_column=item.get("value_column"),
            value_expression=item.get("value_expression"),
        )

    def _condition(
        self,
        column: str,
        operator: str,
        value: Any,
        allowed_columns: dict[str, JsonDict],
        *,
        value_column: Any | None = None,
        value_expression: Any | None = None,
    ) -> str:
        self._assert_safe_column(column, allowed_columns)
        op = self._normalize_operator(operator)

        if op in {"IS NULL", "IS NOT NULL"}:
            return f"v.{column} {op}"

        if value_column is not None:
            other_column = str(value_column)
            self._assert_safe_column(other_column, allowed_columns)
            return f"v.{column} {op} v.{other_column}"

        if value_expression is not None:
            expression = str(value_expression).translate(
                DIGIT_TRANSLATION).strip()
            if not SAFE_ARITHMETIC_EXPRESSION_RE.fullmatch(expression):
                raise SQLGeneratorError(
                    f"Unsafe value_expression for filter on {column}: {expression}")
            return f"v.{column} {op} ({expression})"

        if op == "BETWEEN":
            values = value if isinstance(value, list | tuple) else None
            if not values or len(values) != 2:
                raise SQLGeneratorError(
                    f"BETWEEN filter for {column} requires exactly two values.")
            return f"v.{column} BETWEEN {self._sql_literal(values[0])} AND {self._sql_literal(values[1])}"

        if op == "IN":
            if not isinstance(value, list | tuple | set):
                raise SQLGeneratorError(
                    f"IN filter for {column} requires a list of values.")
            rendered = ", ".join(self._sql_literal(v) for v in value)
            return f"v.{column} IN ({rendered})"

        if value is None:
            raise SQLGeneratorError(
                f"Filter for {column} requires a value, value_column or value_expression.")

        self._validate_allowed_value(column, value, allowed_columns)
        return f"v.{column} {op} {self._sql_literal(value)}"

    @staticmethod
    def _normalize_operator(operator: str) -> str:
        op = str(operator or "=").strip().upper()
        aliases = {
            "==": "=",
            "EQ": "=",
            "NE": "!=",
            "<>": "!=",
            "GT": ">",
            "GTE": ">=",
            "GE": ">=",
            "LT": "<",
            "LTE": "<=",
            "LE": "<=",
        }
        op = aliases.get(op, op)
        allowed = {"=", "!=", ">", ">=", "<", "<=",
                   "BETWEEN", "IN", "IS NULL", "IS NOT NULL"}
        if op not in allowed:
            raise SQLGeneratorError(f"Unsupported filter operator: {operator}")
        return op

    def _validate_allowed_value(self, column: str, value: Any, allowed_columns: dict[str, JsonDict]) -> None:
        column_meta = allowed_columns.get(column) or {}
        allowed_values = column_meta.get("allowed_values")
        if not allowed_values:
            return
        values_to_check = list(value) if isinstance(
            value, list | tuple | set) else [value]
        allowed_as_text = {str(v) for v in allowed_values}
        for item in values_to_check:
            if isinstance(item, bool | int | float):
                continue
            if str(item) not in allowed_as_text:
                raise SQLGeneratorError(
                    f"Value '{item}' is not allowed for column '{column}'.")

    @staticmethod
    def _sql_literal(value: Any) -> str:
        if value is None:
            return "NULL"
        if isinstance(value, bool):
            return "TRUE" if value else "FALSE"
        if isinstance(value, int | float) and not isinstance(value, bool):
            return str(value)
        text = str(value).translate(DIGIT_TRANSLATION).strip()
        text = text.replace("'", "''")
        return f"'{text}'"

    # ------------------------------------------------------------------
    # Safe column/order helpers
    # ------------------------------------------------------------------

    def _safe_columns(self, columns: Iterable[Any], allowed_columns: dict[str, JsonDict]) -> list[str]:
        safe: list[str] = []
        for item in columns or []:
            column = str(item.get("column") if isinstance(
                item, dict) else item).strip()
            if not column:
                continue
            self._assert_safe_column(column, allowed_columns)
            if column not in safe:
                safe.append(column)
        return safe

    def _assert_safe_column(self, column: str, allowed_columns: dict[str, JsonDict]) -> None:
        if not SAFE_COLUMN_RE.fullmatch(column):
            raise SQLGeneratorError(f"Unsafe column name: {column}")
        if column in SENSITIVE_COLUMNS:
            raise SQLGeneratorError(
                f"Sensitive column is not allowed in SQL output: {column}")
        if self.config.reject_unknown_columns and column not in allowed_columns:
            raise SQLGeneratorError(
                f"Unknown or unavailable View column: {column}")
        if column in {"birth_date", "hire_date", "contract_start_date", "contract_end_date"} and not self.config.allow_select_birth_or_date_columns:
            # These can be used as filters only if explicitly allowed elsewhere;
            # the controlled generator avoids selecting/grouping by them.
            return

    @staticmethod
    def _assert_safe_alias(alias: str) -> None:
        if not SAFE_ALIAS_RE.fullmatch(alias):
            raise SQLGeneratorError(f"Unsafe SQL alias: {alias}")

    def _order_by_clause(
        self,
        order_by: list[str] | None,
        *,
        safe_group_by: list[str],
        allowed_aliases: set[str],
    ) -> str:
        if not order_by:
            return ""
        clauses: list[str] = []
        allowed_terms = {*(f"v.{col}" for col in safe_group_by),
                         *safe_group_by, *allowed_aliases}
        for item in order_by:
            raw = str(item or "").strip()
            if not raw:
                continue
            parts = raw.split()
            term = parts[0]
            direction = parts[1].upper() if len(parts) > 1 else "ASC"
            if direction not in {"ASC", "DESC"}:
                direction = "ASC"
            if term not in allowed_terms:
                # Common safe functions used for ordering age groups.
                if re.fullmatch(r"MIN\(v\.[A-Za-z_][A-Za-z0-9_]*\)", term):
                    col = term[6:-1].replace("v.", "")
                    if col not in safe_group_by and col not in {"age"}:
                        continue
                    clauses.append(f"{term} {direction}")
                continue
            clauses.append(f"{term} {direction}")
        if not clauses:
            return ""
        return "ORDER BY " + ", ".join(clauses)

    def _limit_clause(self, limit: int | None) -> str:
        if limit is None:
            return ""
        safe_limit = max(1, min(int(limit), self.config.max_grouped_limit))
        return f"LIMIT {safe_limit}"

    # ------------------------------------------------------------------
    # Payload normalization
    # ------------------------------------------------------------------

    @staticmethod
    def _payload_from(context: Any, attr: str, explicit: Mapping[str, Any] | None = None) -> JsonDict:
        if explicit is not None:
            return deepcopy(dict(explicit))
        if context is None:
            return {}
        if isinstance(context, Mapping):
            value = context.get(attr)
        else:
            value = getattr(context, attr, None)
        if isinstance(value, Mapping):
            return deepcopy(dict(value))
        if hasattr(value, "to_dict"):
            try:
                result = value.to_dict()
                return deepcopy(dict(result)) if isinstance(result, Mapping) else {}
            except Exception:
                return {}
        return {}

    @staticmethod
    def _get_context_value(context: Any, attr: str) -> Any:
        if context is None:
            return None
        if isinstance(context, Mapping):
            return context.get(attr)
        return getattr(context, attr, None)

    @staticmethod
    def _runtime_params_from(context: Any, runtime_params: Mapping[str, Any] | None, kwargs: Mapping[str, Any]) -> JsonDict:
        params: JsonDict = {}
        if isinstance(runtime_params, Mapping):
            params.update(deepcopy(dict(runtime_params)))
        if context is not None:
            for attr in ["runtime_params", "params"]:
                value = context.get(attr) if isinstance(
                    context, Mapping) else getattr(context, attr, None)
                if isinstance(value, Mapping):
                    params.update(deepcopy(dict(value)))
        for key in ["current_shamsi_year", "user_role", "locale"]:
            if key in kwargs and kwargs[key] is not None:
                params[key] = kwargs[key]
        return params

    @staticmethod
    def _merge_params(*payloads: Mapping[str, Any]) -> JsonDict:
        result: JsonDict = {}
        for payload in payloads:
            if not isinstance(payload, Mapping):
                continue
            nested = payload.get("params")
            if isinstance(nested, Mapping):
                result.update(deepcopy(dict(nested)))
            for key in [
                "gender_value",
                "education_title",
                "employment_type",
                "contract_type",
                "age_min",
                "age_max",
                "age_max_exclusive",
                "current_shamsi_year",
            ]:
                if payload.get(key) is not None:
                    result[key] = payload[key]
        return result

    def _collect_filters(self, *payloads: Mapping[str, Any]) -> list[JsonDict]:
        result: list[JsonDict] = []
        for payload in payloads:
            if not isinstance(payload, Mapping):
                continue
            filters = payload.get("filters")
            if isinstance(filters, list):
                for item in filters:
                    if isinstance(item, Mapping):
                        result.append(deepcopy(dict(item)))
        return self._dedupe_filters(result)

    def _collect_group_by(self, intent_id: str, *payloads: Mapping[str, Any]) -> list[str]:
        result: list[str] = []
        for payload in payloads:
            if not isinstance(payload, Mapping):
                continue
            group_by = payload.get("group_by")
            if isinstance(group_by, list):
                for item in group_by:
                    if isinstance(item, str):
                        result.append(item)
                    elif isinstance(item, Mapping) and item.get("column"):
                        result.append(str(item["column"]))
        if not result:
            result.extend(DEFAULT_GROUP_BY_BY_INTENT.get(intent_id, []))
        return self._dedupe_list([str(item).strip() for item in result if str(item).strip()])

    @staticmethod
    def _normalize_order_by(order_by: Any) -> list[str]:
        if not isinstance(order_by, list):
            return []
        result: list[str] = []
        for item in order_by:
            if isinstance(item, str) and item.strip():
                result.append(item.strip())
            elif isinstance(item, Mapping) and item.get("column"):
                direction = str(item.get("direction") or "ASC").upper()
                result.append(f"{item['column']} {direction}")
        return result

    @staticmethod
    def _dedupe_filters(filters: list[JsonDict]) -> list[JsonDict]:
        result: list[JsonDict] = []
        seen: set[str] = set()
        for item in filters:
            key = repr(sorted(item.items()))
            if key not in seen:
                seen.add(key)
                result.append(item)
        return result

    @staticmethod
    def _dedupe_list(items: Iterable[Any]) -> list[Any]:
        result: list[Any] = []
        seen: set[str] = set()
        for item in items:
            key = str(item)
            if key and key not in seen:
                seen.add(key)
                result.append(item)
        return result

    @staticmethod
    def _ensure_filter(
        filters: list[JsonDict],
        column: str,
        operator: str,
        value: Any,
        *,
        value_column: str | None = None,
        value_expression: str | None = None,
    ) -> list[JsonDict]:
        for item in filters:
            if item.get("column") == column and str(item.get("operator") or "=").upper() == operator.upper():
                return filters
        new_item: JsonDict = {"column": column, "operator": operator}
        if value_column is not None:
            new_item["value_column"] = value_column
        elif value_expression is not None:
            new_item["value_expression"] = value_expression
        else:
            new_item["value"] = value
        return [*filters, new_item]

    @staticmethod
    def _drop_filter(filters: list[JsonDict], column: str) -> list[JsonDict]:
        return [item for item in filters if item.get("column") != column]

    @staticmethod
    def _extract_filter_value(filters: list[JsonDict], column: str) -> Any:
        for item in filters:
            if item.get("column") == column and item.get("value") is not None:
                return item.get("value")
        return None

    @staticmethod
    def _has_specific_filter_for_group(group_by: list[str], filters: list[JsonDict]) -> bool:
        if not group_by:
            return False
        group_cols = set(group_by)
        for item in filters:
            if item.get("column") in group_cols and item.get("operator", "=") in {"=", "=="} and item.get("value") is not None:
                return True
        return False

    @staticmethod
    def _group_by_if_no_specific_filter(intent_id: str, group_by: list[str], filters: list[JsonDict]) -> list[str]:
        defaults = DEFAULT_GROUP_BY_BY_INTENT.get(intent_id, [])
        if not defaults:
            return group_by
        for default_col in defaults:
            if any(item.get("column") == default_col and item.get("value") is not None for item in filters):
                return []
        return group_by or defaults

    # ------------------------------------------------------------------
    # Terminal/status handling
    # ------------------------------------------------------------------

    def _terminal_plan_if_needed(
        self,
        *,
        service: Any,
        route_payload: JsonDict,
        intent_payload: JsonDict,
        validation_payload: JsonDict,
        started: float,
    ) -> SQLGenerationResult | None:
        for payload in [validation_payload, route_payload, intent_payload]:
            if not isinstance(payload, Mapping):
                continue
            route = str(payload.get("route") or "").upper()
            status = str(payload.get("status") or payload.get(
                "validation_status") or "").upper()
            if status in TERMINAL_STATUSES:
                return self._status_result(
                    service,
                    status=status,
                    route=route or self._route_for_status(status),
                    reason=str(payload.get("reason") or payload.get("reject_reason") or payload.get(
                        "gap_reason") or "Terminal status from previous module."),
                    started=started,
                )
            if route == ROUTE_GAP:
                return self._status_result(service, status=STATUS_DATA_GAP, route=ROUTE_GAP, reason="GAP route selected.", started=started)
            if route == ROUTE_REJECT:
                fallback_status = STATUS_ACCESS_DENIED if payload.get(
                    "safety_flags") else STATUS_OUT_OF_SCOPE
                return self._status_result(service, status=fallback_status, route=ROUTE_REJECT, reason="REJECT route selected.", started=started)
            if route == ROUTE_CLARIFICATION:
                return self._status_result(service, status=STATUS_NEEDS_CLARIFICATION, route=ROUTE_CLARIFICATION, reason="Clarification route selected.", started=started)
        return None

    def _status_result(
        self,
        service: Any,
        *,
        status: str,
        route: str,
        reason: str,
        started: float,
        warnings: list[str] | None = None,
    ) -> SQLGenerationResult:
        sql = self._status_sql(service, status)
        return self._result(
            status=status,
            route=route,
            sql=sql,
            can_execute_sql=False,
            generation_mode="status_sql",
            reason=reason,
            warnings=warnings or [],
            started=started,
        )

    def _status_sql(self, service: Any, status: str) -> str:
        if service is not None and hasattr(service, "get_status_sql"):
            try:
                value = service.get_status_sql(status)
                if isinstance(value, str) and value.strip():
                    return value.strip()
            except Exception:
                pass
        return STATUS_SQL_FALLBACKS.get(status.upper(), STATUS_SQL_FALLBACKS[STATUS_DATA_GAP])

    @staticmethod
    def _route_for_status(status: str) -> str:
        status = status.upper()
        if status == STATUS_DATA_GAP:
            return ROUTE_GAP
        if status == STATUS_NEEDS_CLARIFICATION:
            return ROUTE_CLARIFICATION
        return ROUTE_REJECT

    def _result(
        self,
        *,
        status: str,
        route: str,
        sql: str | None,
        can_execute_sql: bool,
        started: float,
        generation_mode: str = "none",
        intent: str | None = None,
        intent_id: str | None = None,
        detected_intent: str | None = None,
        report_id: str | None = None,
        template_id: str | None = None,
        output_type: str | None = None,
        visualization_hint: str | None = None,
        result_columns: list[JsonDict] | None = None,
        params: JsonDict | None = None,
        reason: str | None = None,
        confidence: float | None = None,
        warnings: list[str] | None = None,
        errors: list[str] | None = None,
        metadata: JsonDict | None = None,
    ) -> SQLGenerationResult:
        return SQLGenerationResult(
            status=status,
            route=route,
            source=self.config.source_name,
            sql=sql,
            can_execute_sql=can_execute_sql,
            generation_mode=generation_mode,
            intent=intent,
            intent_id=intent_id,
            detected_intent=detected_intent,
            report_id=report_id,
            template_id=template_id,
            output_type=output_type,
            visualization_hint=visualization_hint,
            result_columns=result_columns or [],
            params=params or {},
            reason=reason,
            confidence=confidence,
            warnings=warnings or [],
            errors=errors or [],
            metadata=metadata or {},
            duration_ms=round((time.perf_counter() - started) * 1000, 3),
        )

    # ------------------------------------------------------------------
    # Metadata helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _read_main_view(service: Any) -> JsonDict | None:
        if service is None:
            return None
        if hasattr(service, "get_main_view"):
            try:
                value = service.get_main_view()
                return value if isinstance(value, dict) else None
            except Exception:
                return None
        raw = getattr(service, "_raw", {}) if service is not None else {}
        for key in ["data_dictionary", "report_catalog", "sql_templates"]:
            view = raw.get(key, {}).get(
                "main_view") if isinstance(raw, Mapping) else None
            if isinstance(view, dict):
                return deepcopy(view)
        return None

    @staticmethod
    def _read_default_current_shamsi_year(service: Any) -> int | None:
        if service is None:
            return None
        raw = getattr(service, "_raw", {})
        candidates: list[Any] = []
        if isinstance(raw, Mapping):
            candidates.extend(
                [
                    raw.get("data_dictionary", {}).get(
                        "runtime_defaults", {}).get("current_shamsi_year"),
                    raw.get("sql_templates", {}).get(
                        "runtime_defaults", {}).get("current_shamsi_year"),
                    raw.get("semantic_layer", {}).get(
                        "runtime_defaults", {}).get("current_shamsi_year"),
                ]
            )
            # Fallback from schema context note in generated metadata.
            candidates.append(raw.get("data_dictionary", {}
                                      ).get("current_shamsi_year"))
        for item in candidates:
            try:
                if item is not None:
                    return int(item)
            except Exception:
                continue
        return None

    def _allowed_column_map(self, service: Any) -> dict[str, JsonDict]:
        columns: list[JsonDict] = []
        if hasattr(service, "get_columns"):
            try:
                columns = service.get_columns(include_restricted=True)
            except TypeError:
                columns = service.get_columns()
            except Exception:
                columns = []
        if not columns:
            raw = getattr(service, "_raw", {})
            if isinstance(raw, Mapping):
                columns = raw.get("data_dictionary", {}).get(
                    "columns", []) or []
        result: dict[str, JsonDict] = {}
        for column in columns:
            if isinstance(column, Mapping) and column.get("name"):
                name = str(column["name"])
                if SAFE_COLUMN_RE.fullmatch(name) and name not in SENSITIVE_COLUMNS:
                    result[name] = deepcopy(dict(column))
        # employee_id is required for COUNT; allow it even if marked restricted.
        result.setdefault(
            "employee_id", {"name": "employee_id", "data_type": "integer"})
        result.setdefault(
            "is_active", {"name": "is_active", "data_type": "boolean"})
        return result

    @staticmethod
    def _column_type(column: str, allowed_columns: dict[str, JsonDict]) -> str:
        return str((allowed_columns.get(column) or {}).get("data_type") or "unknown")

    # ------------------------------------------------------------------
    # Output metadata helpers
    # ------------------------------------------------------------------

    def _columns_for_grouped_count(self, group_by: list[str], include_percentage: bool = True) -> list[JsonDict]:
        columns = [{"name": col, "data_type": "dimension"} for col in group_by]
        columns.append({"name": "employee_count", "data_type": "integer"})
        if include_percentage:
            columns.append({"name": "percentage", "data_type": "numeric"})
        return columns

    @staticmethod
    def _columns_for_average(group_by: list[str], average_alias: str) -> list[JsonDict]:
        return [*[{"name": col, "data_type": "dimension"} for col in group_by], {"name": average_alias, "data_type": "numeric"}]

    @staticmethod
    def _visual_for_grouped_count(group_by: list[str]) -> str:
        if group_by == ["gender"]:
            return "pie_chart"
        if group_by == ["hire_year"]:
            return "line_chart"
        if len(group_by) == 1 and group_by[0] in {"department_name", "province", "site_name", "contract_type"}:
            return "horizontal_bar_chart_or_table"
        return "bar_chart_or_table"

    @staticmethod
    def _visual_for_average(group_by: list[str]) -> str:
        return "bar_chart_or_table" if group_by else "kpi_card"

    @staticmethod
    def _infer_output_type(intent_id: str, group_by: list[str]) -> str:
        if intent_id in {"total_employee_count", "gender_percentage", "average_age", "average_service_years", "contractor_share"} and not group_by:
            return "kpi_card"
        if intent_id.startswith("hiring_") or group_by == ["hire_year"]:
            return "line_chart_or_table"
        if group_by:
            return "bar_chart_or_table"
        return "table"

    # ------------------------------------------------------------------
    # Question features
    # ------------------------------------------------------------------

    @staticmethod
    def normalize_text(text: str) -> str:
        text = str(text or "").strip().translate(DIGIT_TRANSLATION)
        replacements = {
            "ي": "ی",
            "ك": "ک",
            "ة": "ه",
            "ۀ": "ه",
            "أ": "ا",
            "إ": "ا",
        }
        for src, dst in replacements.items():
            text = text.replace(src, dst)
        text = re.sub(r"\s+", " ", text)
        return text

    @staticmethod
    def _asks_least(question: str, order_by: list[str]) -> bool:
        if any("ASC" in item.upper() for item in order_by):
            return True
        return any(term in question for term in ["کمترین", "حداقل", "کمترين", "پایین ترین", "پایین‌ترین"])

    @staticmethod
    def _maybe_extreme_limit(question: str) -> int | None:
        if "کدام" in question and any(term in question for term in ["بیشترین", "بیشترين", "کمترین", "حداکثر", "حداقل"]):
            return 1
        return None

    # ------------------------------------------------------------------
    # Safety checks
    # ------------------------------------------------------------------

    def _light_sql_safety_warnings(self, sql: str) -> list[str]:
        warnings: list[str] = []
        normalized = re.sub(r"\s+", " ", sql.strip()).lower()
        if not (normalized.startswith("select ") or normalized.startswith("with ")):
            warnings.append("Generated SQL is not SELECT/WITH.")
        if normalized.count(";") > 1:
            warnings.append("Generated SQL contains multiple statements.")
        if self.config.main_view.lower() not in normalized:
            warnings.append(
                "Generated SQL does not use the configured main View.")
        if " join " in normalized:
            warnings.append("Generated SQL contains JOIN.")
        if "select *" in normalized:
            warnings.append("Generated SQL contains SELECT *.")
        for token in DANGEROUS_SQL_TOKENS:
            if re.search(rf"\b{re.escape(token)}\b", normalized):
                warnings.append(
                    f"Generated SQL contains blocked token: {token}")
        for table_name in [
            "hr_employees",
            "hr_contracts",
            "hr_employee_education",
            "hr_education_levels",
            "hr_departments",
            "hr_positions",
            "hr_locations",
            "hr_age_groups",
        ]:
            if table_name in normalized and self.config.main_view.lower() not in table_name:
                # main_view contains employee_analytics, so this is a true raw table reference.
                warnings.append(
                    f"Generated SQL appears to reference raw table: {table_name}")
        for column in SENSITIVE_COLUMNS:
            if re.search(rf"\b{re.escape(column.lower())}\b", normalized):
                warnings.append(
                    f"Generated SQL references sensitive column: {column}")
        return warnings

    # ------------------------------------------------------------------
    # Generic helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _format_sql(sql: str) -> str:
        normalized = textwrap.dedent(sql).strip()
        normalized = re.sub(r"\n{3,}", "\n\n", normalized)
        normalized = re.sub(r"\n\s*\n", "\n", normalized)
        # Clean lines without collapsing intentional multi-line expressions.
        return "\n".join(line.rstrip() for line in normalized.splitlines())

    @staticmethod
    def _first_non_empty(*values: Any) -> Any:
        for value in values:
            if value is not None and value != "":
                return value
        return None

    @staticmethod
    def _is_number(value: Any) -> bool:
        try:
            float(value)
            return True
        except Exception:
            return False


# Convenience factory ---------------------------------------------------------


def get_sql_generator(metadata_service: Any | None = None, **kwargs: Any) -> SQLGenerator:
    return SQLGenerator(metadata_service=metadata_service, **kwargs)


if __name__ == "__main__":  # pragma: no cover - manual smoke test
    generator = SQLGenerator(metadata_dir=Path(__file__).resolve().parent)
    sample_context = {
        "intent_result": {
            "intent_id": "contractor_share_by_service_domain",
            "route": "SQL",
            "filters": [{"column": "is_active", "operator": "=", "value": True}],
            "group_by": ["service_domain"],
        },
        "route_result": {"route": "SQL"},
    }
    print(generator.generate(
        question="سهم پیمانکاری در هر حوزه چند درصد است؟", context=sample_context)["sql"])
