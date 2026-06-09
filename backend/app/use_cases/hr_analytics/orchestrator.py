from __future__ import annotations

import asyncio
import inspect
import logging
import re
import time
import uuid
from collections.abc import Callable, Mapping
from copy import deepcopy
from dataclasses import asdict, dataclass, field, is_dataclass
from datetime import UTC, datetime
from enum import StrEnum
from pathlib import Path
from typing import Any, Protocol

from app.infrastructure.metadata.service import MetadataService, get_metadata_service

"""
llm_orchestrator.py
-------------------
Central orchestration layer for HR BI Assistant, Controlled SQL-based MVP.


Recommended surrounding modules:
    backend/app/services/metadata_service.py
    backend/app/services/domain_classifier.py
    backend/app/services/question_validator.py
    backend/app/services/intent_parser.py
    backend/app/services/semantic_mapper.py
    backend/app/services/router.py
    backend/app/services/sql_template_engine.py
    backend/app/services/sql_generator.py
    backend/app/services/sql_validator.py
    backend/app/services/query_executor.py
    backend/app/services/gap_service.py
    backend/app/services/response_builder.py

This orchestrator is intentionally dependency-injected:
- If real modules are provided, it calls them.
- If a module is not provided yet, it uses conservative fallback logic based on metadata.

The goal is to keep controlled:
- SQL route uses only hr_mvp.vw_hr_employee_analytics v.
- GAP route is used when data/definition is not available.
- REJECT route is used for non-HR, unsafe, or individual employee questions.
"""


JsonDict = dict[str, Any]
logger = logging.getLogger(__name__)


class OrchestratorError(RuntimeError):
    """Base exception for orchestration errors."""


class Route(StrEnum):
    SQL = "SQL"
    GAP = "GAP"
    REJECT = "REJECT"
    NEEDS_CLARIFICATION = "NEEDS_CLARIFICATION"


class ValidationStatus(StrEnum):
    VALID = "VALID"
    DATA_GAP = "DATA_GAP"
    ANALYTICAL_GAP = "ANALYTICAL_GAP"
    ACCESS_DENIED = "ACCESS_DENIED"
    OUT_OF_SCOPE = "OUT_OF_SCOPE"
    NEEDS_CLARIFICATION = "NEEDS_CLARIFICATION"
    SQL_VALIDATION_FAILED = "SQL_VALIDATION_FAILED"
    METADATA_ERROR = "METADATA_ERROR"
    EXECUTION_FAILED = "EXECUTION_FAILED"
    SUCCESS = "SUCCESS"
    NOT_EXECUTED = "NOT_EXECUTED"


@dataclass
class StepTrace:
    step: str
    status: str
    started_at: str
    duration_ms: float
    details: JsonDict = field(default_factory=dict)


@dataclass
class RequestContext:
    request_id: str
    question: str
    user_id: str | None = None
    user_role: str = "demo_user"
    locale: str = "fa-IR"
    execute_sql: bool = True
    runtime_params: JsonDict = field(default_factory=dict)

    started_at: str = field(default_factory=lambda: utc_now_iso())
    normalized_question: str | None = None

    metadata_health: JsonDict = field(default_factory=dict)
    domain_result: JsonDict = field(default_factory=dict)
    validation_result: JsonDict = field(default_factory=dict)
    semantic_result: JsonDict = field(default_factory=dict)
    intent_result: JsonDict = field(default_factory=dict)
    route_result: JsonDict = field(default_factory=dict)
    sql_plan: JsonDict = field(default_factory=dict)
    sql_validation: JsonDict = field(default_factory=dict)
    query_result: JsonDict = field(default_factory=dict)
    visualization_plan: JsonDict = field(default_factory=dict)
    gap_result: JsonDict = field(default_factory=dict)
    final_response: JsonDict = field(default_factory=dict)

    warnings: list[str] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)
    traces: list[StepTrace] = field(default_factory=list)

    def add_trace(self, step: str, status: str, started: float, details: JsonDict | None = None) -> None:
        self.traces.append(
            StepTrace(
                step=step,
                status=status,
                started_at=utc_now_iso(),
                duration_ms=round((time.perf_counter() - started) * 1000, 3),
                details=details or {},
            )
        )

    def to_dict(self) -> JsonDict:
        return asdict(self)


@dataclass
class OrchestratorResponse:
    request_id: str
    route: str
    status: str
    message_fa: str
    detected_intent: str | None = None
    generated_sql: str | None = None
    data: Any = None
    visualization: JsonDict | None = None
    warnings: list[str] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)
    context: JsonDict | None = None

    def to_dict(self) -> JsonDict:
        return asdict(self)


class AsyncCallableComponent(Protocol):
    async def __call__(self, *args: Any, **kwargs: Any) -> Any: ...


# ---------------------------------------------------------------------------
# Orchestrator
# ---------------------------------------------------------------------------


class LLMOrchestrator:
    """
    Runs the controlled flow:

        question
          -> domain classifier
          -> question validator
          -> semantic mapper
          -> intent parser
          -> router
          -> SQL / Gap / Reject
          -> response builder

    Real modules can be injected gradually. Until then, the fallback logic lets the
    backend run a deterministic MVP using only metadata.
    """

    def __init__(
        self,
        *,
        metadata_service: MetadataService | None = None,
        metadata_dir: str | Path | None = None,
        domain_classifier: Any | None = None,
        question_validator: Any | None = None,
        intent_parser: Any | None = None,
        semantic_mapper: Any | None = None,
        router: Any | None = None,
        sql_template_engine: Any | None = None,
        sql_generator: Any | None = None,
        sql_validator: Any | None = None,
        query_executor: Any | None = None,
        gap_service: Any | None = None,
        response_builder: Any | None = None,
        default_user_role: str = "demo_user",
        default_execute_sql: bool = True,
        current_shamsi_year: int = 1404,
        strict_metadata: bool = True,
    ) -> None:
        if metadata_service is not None:
            self.metadata = metadata_service
        elif get_metadata_service is not None:
            self.metadata = get_metadata_service(
                metadata_dir=metadata_dir, strict=strict_metadata)
        else:  # pragma: no cover
            raise OrchestratorError("MetadataService is not available.")

        self.domain_classifier = domain_classifier
        self.question_validator = question_validator
        self.intent_parser = intent_parser
        self.semantic_mapper = semantic_mapper
        self.router = router
        self.sql_template_engine = sql_template_engine
        self.sql_generator = sql_generator
        self.sql_validator = sql_validator
        self.query_executor = query_executor
        self.gap_service = gap_service
        self.response_builder = response_builder

        self.default_user_role = default_user_role
        self.default_execute_sql = default_execute_sql
        self.current_shamsi_year = current_shamsi_year

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def run(
        self,
        question: str,
        *,
        user_id: str | None = None,
        user_role: str | None = None,
        execute_sql: bool | None = None,
        runtime_params: Mapping[str, Any] | None = None,
    ) -> OrchestratorResponse:
        """
        Synchronous wrapper. In FastAPI async routes, prefer `await orchestrator.arun(...)`.
        """
        return asyncio.run(
            self.arun(
                question,
                user_id=user_id,
                user_role=user_role,
                execute_sql=execute_sql,
                runtime_params=runtime_params,
            )
        )

    async def arun(
        self,
        question: str,
        *,
        user_id: str | None = None,
        user_role: str | None = None,
        execute_sql: bool | None = None,
        runtime_params: Mapping[str, Any] | None = None,
    ) -> OrchestratorResponse:
        context = RequestContext(
            request_id=str(uuid.uuid4()),
            question=question,
            user_id=user_id,
            user_role=user_role or self.default_user_role,
            execute_sql=self.default_execute_sql if execute_sql is None else execute_sql,
            runtime_params={
                "current_shamsi_year": self.current_shamsi_year,
                **dict(runtime_params or {}),
            },
        )
        _started = time.perf_counter()
        logger.info(
            "pipeline start request_id=%s role=%s execute_sql=%s q_chars=%d",
            context.request_id, context.user_role, context.execute_sql, len(question),
        )

        try:
            await self._load_metadata_health(context)
            await self._normalize_question(context)
            await self._classify_domain(context)
            if self._is_terminal(context.domain_result):
                logger.info(
                    "pipeline early-exit step=domain_classifier request_id=%s status=%s",
                    context.request_id, context.domain_result.get("status"),
                )
                return await self._finalize(context, context.domain_result)

            await self._validate_question(context)
            if self._is_terminal(context.validation_result):
                logger.info(
                    "pipeline early-exit step=question_validator request_id=%s status=%s",
                    context.request_id, context.validation_result.get("status"),
                )
                return await self._finalize(context, context.validation_result)

            await self._map_semantics(context)
            await self._parse_intent(context)
            await self._route(context)

            route = str(context.route_result.get("route") or "").upper()
            logger.debug(
                "pipeline routed request_id=%s route=%s intent=%s",
                context.request_id, route,
                context.intent_result.get("intent") or context.intent_result.get("intent_id"),
            )

            if route == Route.GAP.value:
                await self._handle_gap(context)
                return await self._finalize(context, context.gap_result or context.route_result)

            if route in {Route.REJECT.value, Route.NEEDS_CLARIFICATION.value}:
                return await self._finalize(context, context.route_result)

            if route == Route.SQL.value:
                await self._plan_sql(context)
                await self._validate_sql(context)
                if self._is_terminal(context.sql_validation):
                    logger.warning(
                        "pipeline sql-validation-failed request_id=%s status=%s",
                        context.request_id, context.sql_validation.get("status"),
                    )
                    return await self._finalize(context, context.sql_validation)
                await self._execute_sql(context)
                await self._select_visualization(context)
                return await self._finalize(context, context.query_result or context.sql_validation)

            context.warnings.append(f"Unknown route selected: {route}")
            return await self._finalize(
                context,
                {
                    "route": Route.REJECT.value,
                    "status": ValidationStatus.NEEDS_CLARIFICATION.value,
                    "reason": "Router did not return a known route.",
                },
            )
        except Exception as exc:  # Defensive: the API should return a structured response.
            logger.error(
                "pipeline exception request_id=%s: %s",
                context.request_id, exc, exc_info=True,
            )
            context.errors.append(str(exc))
            return await self._finalize(
                context,
                {
                    "route": Route.REJECT.value,
                    "status": ValidationStatus.METADATA_ERROR.value,
                    "reason": str(exc),
                },
            )
        finally:
            logger.info(
                "pipeline done request_id=%s duration_ms=%.0f",
                context.request_id, (time.perf_counter() - _started) * 1000,
            )

    # ------------------------------------------------------------------
    # Pipeline steps
    # ------------------------------------------------------------------

    async def _load_metadata_health(self, context: RequestContext) -> None:
        started = time.perf_counter()
        health = self.metadata.health_check()
        context.metadata_health = health.to_dict() if hasattr(
            health, "to_dict") else to_plain_dict(health)
        if not context.metadata_health.get("ok", False):
            context.warnings.extend(
                context.metadata_health.get("warnings", []) or [])
            context.errors.extend(
                context.metadata_health.get("errors", []) or [])
        context.add_trace("metadata_health", "ok" if context.metadata_health.get(
            "ok", False) else "warning", started, {"decision_by": "rule"})

    async def _normalize_question(self, context: RequestContext) -> None:
        started = time.perf_counter()
        context.normalized_question = self.metadata.normalize_question(
            context.question)
        context.add_trace("normalize_question", "ok", started, {
            "normalized_question": context.normalized_question, "decision_by": "rule"})

    async def _classify_domain(self, context: RequestContext) -> None:
        started = time.perf_counter()
        if self.domain_classifier is not None:
            result = await call_component(
                self.domain_classifier,
                ["classify", "run", "arun", "__call__"],
                question=context.normalized_question,
                context=context,
                metadata=self.metadata,
            )
        else:
            result = self._fallback_domain_classifier(context)
        context.domain_result = normalize_result(result)
        context.add_trace("domain_classifier", context.domain_result.get("status", "ok"), started, {
            **context.domain_result, "decision_by": "component" if self.domain_classifier is not None else "rule"})

    async def _validate_question(self, context: RequestContext) -> None:
        started = time.perf_counter()
        if self.question_validator is not None:
            result = await call_component(
                self.question_validator,
                ["validate", "run", "arun", "__call__"],
                question=context.normalized_question,
                context=context,
                metadata=self.metadata,
            )
        else:
            result = self._fallback_question_validator(context)
        context.validation_result = normalize_result(result)
        context.add_trace("question_validator", context.validation_result.get("status", "ok"), started, {
            **context.validation_result, "decision_by": "component" if self.question_validator is not None else "rule"})

    async def _map_semantics(self, context: RequestContext) -> None:
        started = time.perf_counter()
        if self.semantic_mapper is not None:
            result = await call_component(
                self.semantic_mapper,
                ["map", "map_question", "run", "arun", "__call__"],
                question=context.normalized_question,
                context=context,
                metadata=self.metadata,
            )
        else:
            result = self._fallback_semantic_mapper(context)
        context.semantic_result = normalize_result(result)
        context.add_trace("semantic_mapper", context.semantic_result.get("status", "ok"), started, {
            **context.semantic_result, "decision_by": "component" if self.semantic_mapper is not None else "rule"})

    async def _parse_intent(self, context: RequestContext) -> None:
        started = time.perf_counter()
        if self.intent_parser is not None:
            result = await call_component(
                self.intent_parser,
                ["parse", "parse_intent", "run", "arun", "__call__"],
                question=context.normalized_question,
                context=context,
                metadata=self.metadata,
            )
        else:
            result = self._fallback_intent_parser(context)
        context.intent_result = normalize_result(result)
        context.add_trace("intent_parser", context.intent_result.get("status", "ok"), started, {
            **context.intent_result, "decision_by": "component" if self.intent_parser is not None else "rule"})

    async def _route(self, context: RequestContext) -> None:
        started = time.perf_counter()
        if self.router is not None:
            result = await call_component(
                self.router,
                ["route", "run", "arun", "__call__"],
                question=context.normalized_question,
                context=context,
                metadata=self.metadata,
            )
        else:
            result = self._fallback_router(context)
        context.route_result = normalize_result(result)
        _route_status = str(context.route_result.get("status") or "")
        _router_decision = (
            "policy" if _route_status in {"ACCESS_DENIED", "OUT_OF_SCOPE"}
            else "component" if self.router is not None
            else "rule"
        )
        context.add_trace("router", context.route_result.get("route", "unknown"), started, {
            **context.route_result, "decision_by": _router_decision})

    async def _plan_sql(self, context: RequestContext) -> None:
        started = time.perf_counter()
        if self.sql_template_engine is not None:
            result = await call_component(
                self.sql_template_engine,
                ["build", "plan", "render", "run", "arun", "__call__"],
                context=context,
                metadata=self.metadata,
            )
        else:
            result = self._fallback_sql_template_engine(context)

        plan = normalize_result(result)

        # Phase-2 quality gate: a template can be found but still not satisfy
        # the full shape requested by the user. Example: user asked by
        # province + gender, but the template groups only by gender. In that
        # case we bypass the partial template and force dynamic generation.
        if self._template_plan_is_incomplete(context, plan):
            original_plan = deepcopy(plan)
            plan = {
                "status": "TEMPLATE_INCOMPLETE",
                "route": Route.SQL.value,
                "source": "template_coverage_checker",
                "can_execute_sql": False,
                "reason": "Resolved SQL template does not cover all requested group_by/filter columns.",
                "warnings": ["Template was bypassed because it did not match the full semantic request."],
                "metadata": {"original_template_plan": redact_sql_for_trace(original_plan)},
            }

        should_generate = (
            not plan.get("sql")
            or str(plan.get("status") or "").upper() in {"NO_TEMPLATE", "TEMPLATE_INCOMPLETE", "TEMPLATE_RENDER_FAILED", "PARAMETER_VALIDATION_FAILED"}
            or (not bool(plan.get("can_execute_sql", False)) and str(plan.get("route") or "").upper() == Route.SQL.value)
        )

        if should_generate and self.sql_generator is not None:
            generated = await call_component(
                self.sql_generator,
                ["generate", "run", "arun", "__call__"],
                question=context.normalized_question,
                schema_context=self.metadata.build_schema_context_for_prompt(),
                context=context,
                metadata=self.metadata,
            )
            generated_plan = normalize_result(generated)
            if generated_plan.get("sql"):
                generated_plan.setdefault(
                    "previous_plan_status", plan.get("status"))
                generated_plan.setdefault(
                    "previous_plan_reason", plan.get("reason"))
                plan = generated_plan
            else:
                generated_plan.setdefault("previous_plan", plan)
                plan = generated_plan
            plan.setdefault("source", "sql_generator")

        context.sql_plan = plan
        _plan_source = str(plan.get("source") or "").lower()
        _sql_decision = (
            "template" if "template" in _plan_source
            else "llm" if any(x in _plan_source for x in ("generator", "llm"))
            else "rule"
        )
        context.add_trace("sql_planner", plan.get("status", "ok"), started, {
            **redact_sql_for_trace(plan), "decision_by": _sql_decision})

    def _template_plan_is_incomplete(self, context: RequestContext, plan: JsonDict) -> bool:
        sql = str(plan.get("sql") or "")
        if not sql or str(plan.get("source") or "").lower() not in {"sql_template", "sql_template_engine"}:
            return False
        requested_group_by = self._requested_group_by_columns(context)
        if not requested_group_by:
            return False
        grouped_in_sql = self._group_by_columns_in_sql(sql)
        if not grouped_in_sql:
            return True
        missing = [col for col in requested_group_by if col not in grouped_in_sql]
        if missing:
            context.warnings.append(
                f"Template coverage mismatch. Missing requested group_by columns: {missing}")
            return True
        return False

    def _requested_group_by_columns(self, context: RequestContext) -> list[str]:
        cols: list[str] = []
        # IntentParser is the canonical source because it already combines the
        # Semantic Mapper output into a clean list of column names.
        for source in (context.intent_result, context.route_result, context.semantic_result):
            value = source.get("group_by") if isinstance(
                source, dict) else None
            if not isinstance(value, list):
                continue
            for item in value:
                if isinstance(item, str):
                    col = self._normalize_column_name(item)
                elif isinstance(item, dict):
                    col = self._normalize_column_name(
                        item.get("column") or item.get("name") or item.get("field"))
                else:
                    col = None
                if col and col not in cols:
                    cols.append(col)
            # Once the canonical intent_result has group_by values, do not add
            # noisy/raw semantic debug objects.
            if cols and source is context.intent_result:
                break
        return cols

    def _group_by_columns_in_sql(self, sql: str) -> list[str]:
        m = re.search(r"\bGROUP\s+BY\s+(.*?)(?:\bORDER\s+BY\b|\bLIMIT\b|;|$)",
                      sql, flags=re.IGNORECASE | re.DOTALL)
        if not m:
            return []
        section = m.group(1)
        cols: list[str] = []
        for part in section.split(','):
            col = self._normalize_column_name(part)
            if col and col not in cols:
                cols.append(col)
        return cols

    @staticmethod
    def _normalize_column_name(value: Any) -> str | None:
        if value is None:
            return None
        text = str(value).strip()
        text = re.sub(r"\bv\.", "", text, flags=re.IGNORECASE)
        text = re.sub(r"[^A-Za-z0-9_]+", "", text)
        return text or None

    async def _validate_sql(self, context: RequestContext) -> None:
        started = time.perf_counter()
        sql = str(context.sql_plan.get("sql") or "").strip()
        if self.sql_validator is not None:
            result = await call_component(
                self.sql_validator,
                ["validate", "run", "arun", "__call__"],
                sql=sql,
                context=context,
                metadata=self.metadata,
            )
        else:
            result = self._fallback_sql_validator(sql)
        context.sql_validation = normalize_result(result)
        context.add_trace("sql_validator", context.sql_validation.get("status", "unknown"), started, {
            **context.sql_validation, "decision_by": "rule"})

    async def _execute_sql(self, context: RequestContext) -> None:
        started = time.perf_counter()
        sql = str(context.sql_plan.get("sql") or "").strip()

        if not context.execute_sql:
            context.query_result = {
                "status": ValidationStatus.NOT_EXECUTED.value,
                "execution_status": "NOT_EXECUTED",
                "reason": "execute_sql=False",
                "sql": sql,
                "rows": [],
            }
            context.add_trace("query_executor", "not_executed", started, {"decision_by": "rule"})
            return

        if self.query_executor is None:
            context.query_result = {
                "status": ValidationStatus.NOT_EXECUTED.value,
                "execution_status": "NOT_EXECUTED",
                "reason": "query_executor is not configured yet.",
                "sql": sql,
                "rows": [],
            }
            context.add_trace("query_executor", "not_configured", started, {"decision_by": "rule"})
            return

        logger.debug(
            "executing sql request_id=%s sql_chars=%d",
            context.request_id, len(sql),
        )
        try:
            result = await call_component(
                self.query_executor,
                ["execute", "run", "arun", "__call__"],
                sql=sql,
                context=context,
                metadata=self.metadata,
            )
            context.query_result = normalize_result(result)
            context.query_result.setdefault(
                "status", ValidationStatus.SUCCESS.value)
            context.query_result.setdefault("execution_status", "SUCCESS")
            logger.debug(
                "sql executed request_id=%s rows=%s",
                context.request_id,
                len(context.query_result.get("rows") or []),
            )
        except Exception as exc:
            logger.error(
                "sql execution failed request_id=%s: %s",
                context.request_id, exc, exc_info=True,
            )
            context.query_result = {
                "status": ValidationStatus.EXECUTION_FAILED.value,
                "execution_status": "FAILED",
                "error": str(exc),
                "sql": sql,
                "rows": [],
            }
            context.errors.append(str(exc))
        context.add_trace("query_executor", context.query_result.get(
            "execution_status", "unknown"), started, {"decision_by": "db"})

    async def _select_visualization(self, context: RequestContext) -> None:
        started = time.perf_counter()
        intent_id = context.intent_result.get(
            "intent") or context.intent_result.get("intent_id")
        report_id = context.intent_result.get("report_id")
        visual = None
        if intent_id:
            visual = self.metadata.get_visualization_for_intent(str(intent_id))
        if not visual and report_id:
            visual = self.metadata.get_visualization_for_report(str(report_id))
        if not visual:
            visual = {
                "primary_visualization": context.intent_result.get("recommended_visualization") or "table",
                "fallback_visualization": "table",
            }
        context.visualization_plan = visual
        context.add_trace("visualization_selector", "ok", started, {**visual, "decision_by": "rule"})

    async def _handle_gap(self, context: RequestContext) -> None:
        started = time.perf_counter()
        gap_payload = {
            "question": context.question,
            "normalized_question": context.normalized_question,
            "intent": context.intent_result.get("intent") or context.intent_result.get("intent_id"),
            "reason": context.route_result.get("reason") or context.intent_result.get("reason"),
            "missing_data": context.route_result.get("missing_data") or context.intent_result.get("missing_data"),
            "created_by": "llm_orchestrator",
        }
        if self.gap_service is not None:
            try:
                result = await call_component(
                    self.gap_service,
                    ["create_gap", "register", "run", "arun", "__call__"],
                    gap=gap_payload,
                    context=context,
                    metadata=self.metadata,
                )
                context.gap_result = normalize_result(result)
                context.gap_result.setdefault("route", Route.GAP.value)
                context.gap_result.setdefault(
                    "status", ValidationStatus.DATA_GAP.value)
            except Exception as exc:
                context.gap_result = {
                    "route": Route.GAP.value,
                    "status": ValidationStatus.DATA_GAP.value,
                    "gap_logged": False,
                    "reason": str(exc),
                    **gap_payload,
                }
        else:
            prior_status = str(context.route_result.get("status") or "").upper()
            gap_status = (
                ValidationStatus.ANALYTICAL_GAP.value
                if prior_status == ValidationStatus.ANALYTICAL_GAP.value
                else ValidationStatus.DATA_GAP.value
            )
            context.gap_result = {
                "route": Route.GAP.value,
                "status": gap_status,
                "gap_logged": False,
                "reason": gap_payload.get("reason") or "Required data or business rule is not available in the current MVP.",
                **gap_payload,
            }
        context.add_trace("gap_service", context.gap_result.get("status", "DATA_GAP"), started, {
            **context.gap_result, "decision_by": "component" if self.gap_service is not None else "rule"})

    async def _finalize(self, context: RequestContext, status_payload: JsonDict) -> OrchestratorResponse:  # noqa: PLR0912
        started = time.perf_counter()
        if self.response_builder is not None:
            try:
                result = await call_component(
                    self.response_builder,
                    ["build", "build_response", "run", "arun", "__call__"],
                    context=context,
                    status_payload=status_payload,
                    metadata=self.metadata,
                )
                response_dict = normalize_result(result)
                if response_dict:
                    return OrchestratorResponse(
                        request_id=context.request_id,
                        route=str(response_dict.get("route") or status_payload.get(
                            "route") or context.route_result.get("route") or Route.REJECT.value),
                        status=str(response_dict.get("status") or status_payload.get(
                            "status") or ValidationStatus.SUCCESS.value),
                        message_fa=str(response_dict.get("message_fa") or response_dict.get(
                            "message") or "پاسخ آماده شد."),
                        detected_intent=(
                            response_dict.get("detected_intent")
                            or context.intent_result.get("intent")
                            or context.intent_result.get("intent_id")
                            or (context.validation_result.get("gap_candidates") or [None])[0]
                            or context.route_result.get("intent")
                            or context.route_result.get("intent_id")
                        ),
                        generated_sql=response_dict.get(
                            "generated_sql") or context.sql_plan.get("sql"),
                        data=response_dict.get(
                            "data") if "data" in response_dict else self._extract_rows(context),
                        visualization=response_dict.get(
                            "visualization") or context.visualization_plan,
                        warnings=context.warnings,
                        errors=context.errors,
                        context=context.to_dict(),
                    )
            except Exception as exc:
                context.warnings.append(
                    f"response_builder failed, fallback response used: {exc}")

        response = self._fallback_response_builder(context, status_payload)
        context.final_response = response.to_dict()
        context.add_trace("response_builder", response.status, started, {"decision_by": "rule"})
        response.context = context.to_dict()
        logger.info(
            "pipeline finalized request_id=%s route=%s status=%s warnings=%d errors=%d",
            context.request_id, response.route, response.status,
            len(context.warnings), len(context.errors),
        )
        return response

    # ------------------------------------------------------------------
    # Fallback components
    # ------------------------------------------------------------------

    def _fallback_domain_classifier(self, context: RequestContext) -> JsonDict:
        question = context.normalized_question or ""
        if not question:
            return {
                "route": Route.NEEDS_CLARIFICATION.value,
                "status": ValidationStatus.NEEDS_CLARIFICATION.value,
                "is_hr": False,
                "confidence": 1.0,
                "reason": "Question is empty.",
            }

        out_of_scope_terms = [
            "فروش", "درآمد", "سود", "زیان", "مارکتینگ", "بازاریابی", "مشتری", "فاکتور", "انبار", "تولید کالا",
            "sales", "revenue", "marketing", "invoice", "inventory",
        ]
        if any(term in question for term in out_of_scope_terms):
            # If it also contains strong HR terms, let later stages decide. Otherwise reject early.
            hr_matches = self.metadata.find_semantic_matches(
                question, max_matches=5)
            if not hr_matches:
                return {
                    "route": Route.REJECT.value,
                    "status": ValidationStatus.OUT_OF_SCOPE.value,
                    "is_hr": False,
                    "confidence": 0.9,
                    "reason": "Question is outside HR BI scope.",
                }

        matches = self.metadata.find_semantic_matches(question, max_matches=10)
        if matches:
            return {
                "route": None,
                "status": "OK",
                "is_hr": True,
                "confidence": min(0.95, 0.55 + len(matches) * 0.06),
                "matched_concepts": matches[:5],
            }

        weak_hr_terms = ["کارمند", "کارکنان", "پرسنل", "نیرو",
                         "منابع انسانی", "استخدام", "قرارداد", "جذب", "مدرک", "سابقه"]
        if any(term in question for term in weak_hr_terms):
            return {"route": None, "status": "OK", "is_hr": True, "confidence": 0.65, "matched_concepts": []}

        return {
            "route": Route.REJECT.value,
            "status": ValidationStatus.OUT_OF_SCOPE.value,
            "is_hr": False,
            "confidence": 0.7,
            "reason": "No HR concept was detected.",
        }

    def _fallback_question_validator(self, context: RequestContext) -> JsonDict:
        question = context.normalized_question or ""
        if len(question.strip()) < 3:
            return {
                "route": Route.NEEDS_CLARIFICATION.value,
                "status": ValidationStatus.NEEDS_CLARIFICATION.value,
                "is_valid": False,
                "reason": "Question is too short or unclear.",
            }

        prompt_injection_terms = [
            "ignore previous", "ignore all", "system prompt", "developer message", "دستور قبلی", "پرامپت قبلی",
            "جدول خام", "drop table", "delete from", "truncate", "alter table", "insert into", "update ",
        ]
        if any(term.lower() in question.lower() for term in prompt_injection_terms):
            return {
                "route": Route.REJECT.value,
                "status": ValidationStatus.ACCESS_DENIED.value,
                "is_valid": False,
                "reason": "Unsafe or prompt-injection-like request.",
            }

        individual_terms = [
            "نام کارکنان", "نام و مشخصات", "کد ملی", "شماره پرسنلی", "شماره ملی", "شماره تماس", "آدرس",
            "مشخصات فردی", "لیست افراد", "فهرست افراد", "اسامی کارکنان", "حقوق هر فرد", "اطلاعات شخصی",
            "first_name", "last_name", "national_id", "personnel_number",
        ]
        if any(term in question for term in individual_terms):
            return {
                "route": Route.REJECT.value,
                "status": ValidationStatus.ACCESS_DENIED.value,
                "is_valid": False,
                "reason": "Individual employee information is not allowed.",
            }

        return {"route": None, "status": "OK", "is_valid": True, "reason": None}

    def _fallback_semantic_mapper(self, context: RequestContext) -> JsonDict:
        question = context.normalized_question or ""
        matches = self.metadata.find_semantic_matches(question, max_matches=25)
        columns: list[str] = []
        metrics: list[str] = []
        related_intents: list[str] = []
        routes: list[str] = []
        data_statuses: list[str] = []

        for match in matches:
            maps_to = match.get("maps_to", {}) if isinstance(
                match.get("maps_to"), dict) else {}
            if maps_to.get("column"):
                columns.append(str(maps_to["column"]))
            if maps_to.get("metric"):
                metrics.append(str(maps_to["metric"]))
            if maps_to.get("route"):
                routes.append(str(maps_to["route"]))
            if match.get("data_status"):
                data_statuses.append(str(match["data_status"]))
            for intent in maps_to.get("related_intents", []) or []:
                related_intents.append(str(intent))

        return {
            "status": "OK",
            "semantic_matches": matches,
            "mapped_columns": sorted(set(columns)),
            "mapped_metrics": sorted(set(metrics)),
            "candidate_intents": list(dict.fromkeys(related_intents)),
            "candidate_routes": list(dict.fromkeys(routes)),
            "data_statuses": list(dict.fromkeys(data_statuses)),
        }

    def _fallback_intent_parser(self, context: RequestContext) -> JsonDict:
        question = context.normalized_question or ""

        # Hard GAP / REJECT detection before scoring supported SQL intents.
        early = self._detect_gap_or_reject_intent(question)
        if early:
            return early

        candidates: list[tuple[float, JsonDict, list[str]]] = []
        semantic_candidates = set(
            context.semantic_result.get("candidate_intents", []) or [])

        for intent in self.metadata.list_intents():
            score = 0.0
            reasons: list[str] = []

            intent_id = str(intent.get("intent_id", ""))
            if intent_id in semantic_candidates:
                score += 4.0
                reasons.append("semantic_related_intent")

            for term in intent.get("trigger_terms_fa", []) or []:
                if isinstance(term, str) and term and term in question:
                    score += 5.0 + min(len(term), 20) / 20
                    reasons.append(f"trigger:{term}")

            for example in intent.get("user_examples", []) or []:
                if not isinstance(example, str):
                    continue
                overlap = token_overlap(
                    question, self.metadata.normalize_question(example))
                if overlap >= 0.5:
                    score += 2.0 * overlap
                    reasons.append("example_overlap")

            # General keywords for common ambiguous intents.
            score += self._intent_keyword_bonus(intent_id, question, context)

            if score > 0:
                candidates.append((score, intent, reasons))

        candidates.sort(key=lambda item: item[0], reverse=True)
        if not candidates:
            return {
                "route": Route.NEEDS_CLARIFICATION.value,
                "status": ValidationStatus.NEEDS_CLARIFICATION.value,
                "intent": "unknown",
                "confidence": 0.0,
                "reason": "No supported intent matched the question.",
            }

        best_score, best_intent, reasons = candidates[0]
        confidence = min(0.98, max(0.35, best_score / 12))
        extracted_params = self._extract_template_params(question, best_intent)

        return {
            "route": best_intent.get("route", Route.SQL.value),
            "status": best_intent.get("status", "supported"),
            "intent": best_intent.get("intent_id"),
            "intent_id": best_intent.get("intent_id"),
            "confidence": round(confidence, 3),
            "reason": ", ".join(reasons[:5]),
            "report_id": best_intent.get("report_id"),
            "sql_template_id": best_intent.get("sql_template_id"),
            "required_columns": best_intent.get("required_columns", []),
            "metrics": best_intent.get("metrics", []),
            "group_by": best_intent.get("group_by", []),
            "filters": extracted_params.get("filters", []),
            "params": extracted_params.get("params", {}),
            "recommended_visualization": best_intent.get("recommended_visualization"),
            "candidate_intents": [
                {"intent": item[1].get("intent_id"), "score": round(item[0], 3)} for item in candidates[:5]
            ],
        }

    def _fallback_router(self, context: RequestContext) -> JsonDict:
        # Validation/domain terminal statuses win.
        for payload in (context.validation_result, context.domain_result):
            if self._is_terminal(payload):
                return {
                    "route": payload.get("route") or route_for_status(str(payload.get("status"))),
                    "status": payload.get("status"),
                    "reason": payload.get("reason"),
                }

        intent_route = str(context.intent_result.get("route") or "").upper()
        intent_status = str(context.intent_result.get("status") or "").upper()

        if intent_route in {Route.GAP.value, Route.REJECT.value, Route.NEEDS_CLARIFICATION.value}:
            return {
                "route": intent_route,
                "status": status_for_route(intent_route, fallback=intent_status),
                "reason": context.intent_result.get("reason"),
            }
        if intent_status in {"DATA_GAP", "ANALYTICAL_GAP", "ACCESS_DENIED", "OUT_OF_SCOPE", "NEEDS_CLARIFICATION"}:
            return {
                "route": route_for_status(intent_status),
                "status": intent_status,
                "reason": context.intent_result.get("reason"),
            }
        if intent_route == Route.SQL.value or context.intent_result.get("sql_template_id"):
            return {
                "route": Route.SQL.value,
                "status": ValidationStatus.VALID.value,
                "reason": "Supported SQL intent.",
            }
        return {
            "route": Route.NEEDS_CLARIFICATION.value,
            "status": ValidationStatus.NEEDS_CLARIFICATION.value,
            "reason": "Intent is not clear enough to choose a route.",
        }

    def _fallback_sql_template_engine(self, context: RequestContext) -> JsonDict:
        intent_id = context.intent_result.get(
            "intent") or context.intent_result.get("intent_id")
        metadata_context = self.metadata.build_metadata_context_for_intent(
            str(intent_id)) if intent_id else {}
        template = metadata_context.get("sql_template") or {}
        template_id = context.intent_result.get(
            "sql_template_id") or template.get("template_id")

        if not template and template_id:
            template = self.metadata.get_sql_template(str(template_id)) or {}

        # Some intents intentionally do not carry sql_template_id in early metadata
        # drafts. In that case, find a ready template by its intent field.
        if not template and intent_id:
            for candidate in self.metadata.list_sql_templates():
                if str(candidate.get("intent")) == str(intent_id):
                    template = candidate
                    template_id = candidate.get("template_id")
                    break

        if not template:
            return {
                "status": "NO_TEMPLATE",
                "route": Route.SQL.value,
                "intent": intent_id,
                "sql": None,
                "reason": "No SQL template was found for the detected intent.",
            }

        params = {
            "current_shamsi_year": context.runtime_params.get("current_shamsi_year", self.current_shamsi_year),
            **(context.intent_result.get("params", {}) or {}),
            **context.runtime_params,
        }
        sql = self._render_sql_template_text(
            str(template.get("sql", "")), params)
        return {
            "status": "OK",
            "route": Route.SQL.value,
            "source": "sql_template",
            "intent": intent_id,
            "template_id": template.get("template_id") or template_id,
            "params": params,
            "sql": sql,
            "result_columns": template.get("result_columns", []),
            "output_type": template.get("output_type"),
        }

    def _fallback_sql_validator(self, sql: str) -> JsonDict:
        normalized = normalize_sql(sql)
        errors: list[str] = []
        warnings: list[str] = []

        if not sql:
            errors.append("SQL is empty.")
        if "{" in sql or "}" in sql:
            errors.append("SQL contains unresolved template placeholders.")
        if not re.match(r"^\s*(SELECT|WITH)\b", sql, flags=re.IGNORECASE):
            errors.append("SQL must start with SELECT or WITH.")
        if count_sql_statements(sql) != 1:
            errors.append("SQL must contain exactly one statement.")
        if re.search(r"\b(INSERT|UPDATE|DELETE|DROP|ALTER|CREATE|TRUNCATE|GRANT|REVOKE|COPY|EXECUTE)\b", sql, flags=re.IGNORECASE):
            errors.append("SQL contains a blocked command.")
        if re.search(r"\bJOIN\b", sql, flags=re.IGNORECASE):
            errors.append("JOIN is not allowed in generated SQL for Phase 2.")
        if re.search(r"SELECT\s+\*", sql, flags=re.IGNORECASE):
            errors.append("SELECT * is not allowed.")

        allowed_view_pattern = r"hr_mvp\.vw_hr_employee_analytics\s+v"
        if not re.search(allowed_view_pattern, normalized, flags=re.IGNORECASE):
            # Status SQLs like SELECT 'DATA_GAP' AS status; are allowed.
            status_sql_pattern = r"^SELECT\s+'(DATA_GAP|ANALYTICAL_GAP|ACCESS_DENIED|OUT_OF_SCOPE|NEEDS_CLARIFICATION|SQL_VALIDATION_FAILED)'\s+AS\s+status\s*;?$"
            if not re.match(status_sql_pattern, normalized, flags=re.IGNORECASE):
                errors.append(
                    "SQL must use only hr_mvp.vw_hr_employee_analytics v, or a valid status SELECT.")

        raw_tables = [
            "hr_mvp.hr_employees",
            "hr_mvp.hr_contracts",
            "hr_mvp.hr_employee_education",
            "hr_mvp.hr_education_levels",
            "hr_mvp.hr_departments",
            "hr_mvp.hr_positions",
            "hr_mvp.hr_locations",
            "hr_mvp.hr_age_groups",
            "information_schema",
            "pg_catalog",
        ]
        for table in raw_tables:
            if table.lower() in normalized.lower():
                errors.append(f"Raw or system table is not allowed: {table}")

        sensitive_columns = self.metadata.get_sensitive_columns()
        for column in sensitive_columns:
            if re.search(rf"\b{re.escape(column)}\b", sql, flags=re.IGNORECASE):
                errors.append(f"Sensitive column is not allowed: {column}")

        if re.search(r"\bv\.employee_id\b", sql, flags=re.IGNORECASE) and not re.search(r"COUNT\s*\(\s*v\.employee_id\s*\)", sql, flags=re.IGNORECASE):
            warnings.append(
                "v.employee_id should only be used inside COUNT for aggregated output.")

        if errors:
            return {
                "status": ValidationStatus.SQL_VALIDATION_FAILED.value,
                "is_valid": False,
                "errors": errors,
                "warnings": warnings,
            }
        return {
            "status": ValidationStatus.VALID.value,
            "is_valid": True,
            "errors": [],
            "warnings": warnings,
        }

    def _fallback_response_builder(self, context: RequestContext, status_payload: JsonDict) -> OrchestratorResponse:
        status = str(status_payload.get("status") or context.query_result.get(
            "status") or ValidationStatus.SUCCESS.value).upper()
        route = str(status_payload.get("route") or context.route_result.get(
            "route") or route_for_status(status)).upper()
        intent = context.intent_result.get(
            "intent") or context.intent_result.get("intent_id")
        sql = context.sql_plan.get("sql")

        message = self._message_for_status(status, context, status_payload)
        data = self._extract_rows(context)
        return OrchestratorResponse(
            request_id=context.request_id,
            route=route,
            status=status,
            message_fa=message,
            detected_intent=str(intent) if intent else None,
            generated_sql=str(sql) if sql else None,
            data=data,
            visualization=context.visualization_plan or None,
            warnings=list(dict.fromkeys(context.warnings +
                          (context.sql_validation.get("warnings", []) or []))),
            errors=list(dict.fromkeys(context.errors +
                        (context.sql_validation.get("errors", []) or []))),
            context=None,
        )

    # ------------------------------------------------------------------
    # Fallback helper rules
    # ------------------------------------------------------------------

    def _detect_gap_or_reject_intent(self, question: str) -> JsonDict | None:
        # (intent_id, terms, reason, is_analytical_gap)
        gap_rules = [
            ("city_level_analysis", ["شهر", "شهری", "هر شهر"],
             "در MVP فعلی داده شهر قابل اتکا نیست.", False),
            ("near_retirement_analysis", [
             "بازنشستگی", "بازنشسته", "آستانه بازنشستگی"], "قانون رسمی بازنشستگی هنوز تعریف نشده است.", False),
            ("contractor_productivity_analysis", [
             "بهره وری پیمانکار", "بهره‌وری پیمانکار", "عملکرد پیمانکار"], "داده بهره‌وری پیمانکارها در MVP فعلی وجود ندارد.", True),
            ("training_need_analysis", ["نیاز آموزشی", "آموزش", "دوره تخصصی"],
             "تعریف رسمی نیاز آموزشی و داده دوره‌ها در MVP فعلی کامل نیست.", True),
            ("workload_hiring_alignment", [
             "افزایش کار", "حجم کار", "بار کاری"], "داده حجم کار سازمان برای مقایسه با جذب وجود ندارد.", True),
            ("monthly_hiring_trend", [
             "ماهانه", "ماه جذب", "در هر ماه"], "تحلیل ماهانه جذب در MVP فعلی آماده نیست.", False),
            ("aging_workforce_analysis", ["سالخوردگی", "پیر شدن", "ساختار سنی"],
             "برای تحلیل سالخوردگی باید آستانه و قاعده تحلیلی تعریف شود.", True),
        ]
        for intent_id, terms, reason, is_analytical in gap_rules:
            if any(term in question for term in terms):
                status = ValidationStatus.ANALYTICAL_GAP.value if is_analytical else ValidationStatus.DATA_GAP.value
                return {
                    "route": Route.GAP.value,
                    "status": status,
                    "intent": intent_id,
                    "intent_id": intent_id,
                    "confidence": 0.9,
                    "reason": reason,
                }

        if any(term in question for term in ["فروش", "درآمد", "سود", "زیان", "مشتری"]):
            return {
                "route": Route.REJECT.value,
                "status": ValidationStatus.OUT_OF_SCOPE.value,
                "intent": "out_of_scope",
                "intent_id": "out_of_scope",
                "confidence": 0.9,
                "reason": "سؤال خارج از دامنه منابع انسانی است.",
            }
        return None

    def _intent_keyword_bonus(self, intent_id: str, question: str, context: RequestContext) -> float:
        bonus = 0.0
        q = question
        if intent_id == "gender_percentage" and ("درصد" in q or "سهم" in q) and ("زن" in q or "مرد" in q):
            bonus += 6
        if intent_id == "employee_count_by_gender" and ("زن و مرد" in q or "جنسیت" in q):
            bonus += 5
        if intent_id == "average_age" and "میانگین" in q and "سن" in q:
            bonus += 6
        if intent_id == "employee_count_by_age_filter" and ("زیر" in q or "بالای" in q or "به بالا" in q) and "سال" in q:
            bonus += 7
        if intent_id == "employee_count_by_education" and any(t in q for t in ["مدرک", "تحصیل", "کارشناسی", "دیپلم", "کاردانی", "دکترا"]):
            bonus += 5
        if intent_id == "low_education_in_expert_roles" and any(t in q for t in ["نیاز پست", "پایین تر از نیاز", "کمتر از نیاز", "پست کارشناسی", "پایین‌تر از نیاز"]):
            bonus += 8
        if intent_id == "most_common_education" and ("بیشترین" in q or "بیشترین سهم" in q or "رایج‌ترین" in q or "رایج ترین" in q) and "مدرک" in q:
            bonus += 7
        if intent_id == "least_common_education" and "کمترین" in q and "مدرک" in q:
            bonus += 7
        if intent_id == "employee_count_by_employment_type" and "نوع استخدام" in q:
            bonus += 7
        if intent_id == "employee_count_by_contract_type" and "نوع قرارداد" in q:
            bonus += 7
        if intent_id == "contractor_share" and "پیمانکاری" in q and not any(t in q for t in ["حوزه", "واحد", "بخش"]):
            bonus += 5
        if intent_id == "contractor_share_by_service_domain" and "پیمانکاری" in q and "حوزه" in q:
            bonus += 8
        if intent_id == "employee_count_by_service_domain" and "حوزه" in q:
            bonus += 5
        if intent_id == "employee_count_by_department" and any(t in q for t in ["بخش", "واحد", "اداره", "دپارتمان"]):
            bonus += 5
        if intent_id == "employee_count_by_province" and "استان" in q:
            bonus += 6
        if intent_id == "hiring_trend_annual" and "روند" in q and "جذب" in q:
            bonus += 7
        if intent_id == "hiring_last_15_years" and ("۱۵" in q or "15" in q or "پانزده" in q) and "جذب" in q:
            bonus += 8
        if intent_id == "most_or_least_hiring_year" and "جذب" in q and ("بیشترین" in q or "کمترین" in q):
            bonus += 7
        if intent_id == "average_service_years" and "میانگین" in q and "سابقه" in q:
            bonus += 7
        if intent_id == "headcount_gap_by_department" and any(t in q for t in ["کمبود نیرو", "چارت مصوب", "اختلاف"]):
            bonus += 7
        return bonus

    def _extract_template_params(self, question: str, intent: JsonDict) -> JsonDict:
        intent_id = str(intent.get("intent_id", ""))
        params: JsonDict = {}
        filters: list[JsonDict] = []

        if "زن" in question and ("درصد" in question or intent_id == "gender_percentage"):
            params["gender_value"] = "زن"
            filters.append(
                {"column": "gender", "operator": "=", "value": "زن"})
        elif "مرد" in question and ("درصد" in question or intent_id == "gender_percentage"):
            params["gender_value"] = "مرد"
            filters.append(
                {"column": "gender", "operator": "=", "value": "مرد"})

        age_number = extract_first_int(question)
        if intent_id == "employee_count_by_age_filter":
            if "زیر" in question or "کمتر از" in question:
                params.update(
                    {"age_min": None, "age_max_exclusive": age_number or 30, "age_max_inclusive": None})
                filters.append(
                    {"column": "age", "operator": "<", "value": age_number or 30})
            elif "به بالا" in question or "بالای" in question or "بیشتر از" in question:
                params.update({"age_min": age_number or 60,
                              "age_max_exclusive": None, "age_max_inclusive": None})
                filters.append(
                    {"column": "age", "operator": ">=", "value": age_number or 60})
            else:
                params.update(
                    {"age_min": None, "age_max_exclusive": None, "age_max_inclusive": None})

        education_values = [
            "کمتر از سیکل", "زیر دیپلم", "دیپلم", "کاردانی", "کارشناسی ارشد", "کارشناسی", "دکترای تخصصی / حرفه‌ای", "دکترا",
        ]
        for value in education_values:
            if value in question:
                normalized_value = "دکترای تخصصی / حرفه‌ای" if value == "دکترا" else value
                params["education_title"] = normalized_value
                filters.append({"column": "education_title",
                               "operator": "=", "value": normalized_value})
                break

        employment_values = ["رسمی - آزمایشی", "رسمی _ بیمه ای دائم",
                             "شاغل در پیمانکاری", "قراردادی", "پیمانی", "رسمی"]
        if "نوع قرارداد" not in question:
            for value in employment_values:
                if value in question:
                    params["employment_type"] = value
                    filters.append({"column": "employment_type",
                                   "operator": "=", "value": value})
                    break

        contract_values = [
            "امور پشتیبانی اداری",
            "امور پشتیبانی خدماتی",
            "حراست",
            "نگهداری تاسیسات - تهران",
            "نگهداری تاسیسات استانها",
            "نگهداری شبکه",
            "رسمی - آزمایشی",
            "رسمی _ بیمه ای دائم",
            "قراردادی",
            "پیمانی",
            "رسمی",
        ]
        if "نوع قرارداد" in question:
            for value in contract_values:
                if value in question:
                    params["contract_type"] = value
                    filters.append({"column": "contract_type",
                                   "operator": "=", "value": value})
                    break

        return {"params": params, "filters": filters}

    def _render_sql_template_text(self, template_sql: str, params: Mapping[str, Any]) -> str:
        """
        Render template placeholders safely.

        The metadata templates may contain both {param} and quoted '{param}' forms.
        This renderer replaces quoted placeholders as a whole to avoid producing
        invalid SQL like ''زن''.
        """
        rendered = template_sql.strip()
        for key, value in params.items():
            if not re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*", str(key)):
                raise ValueError(f"Unsafe SQL template parameter name: {key}")
            literal = sql_literal(value)
            placeholder = "{" + str(key) + "}"
            rendered = rendered.replace("'" + placeholder + "'", literal)
            rendered = rendered.replace(placeholder, literal)
        return rendered

    def _message_for_status(self, status: str, context: RequestContext, payload: JsonDict) -> str:
        status = status.upper()
        if status in {ValidationStatus.SUCCESS.value, ValidationStatus.VALID.value}:
            if context.query_result.get("execution_status") == "SUCCESS":
                return "پاسخ بر اساس داده‌های فعلی منابع انسانی آماده شد."
            if context.query_result.get("execution_status") == "NOT_EXECUTED":
                return "SQL امن تولید و اعتبارسنجی شد، اما اجرای کوئری در این مرحله انجام نشد."
            return "SQL امن تولید و آماده اجرا شد."
        if status == ValidationStatus.NOT_EXECUTED.value:
            return "SQL امن تولید شد، ولی اجرای کوئری هنوز به Query Executor وصل نشده است."
        if status == ValidationStatus.DATA_GAP.value:
            reason = payload.get("reason") or context.intent_result.get(
                "reason") or "داده یا قانون کسب‌وکاری لازم در MVP فعلی موجود نیست."
            return f"این سؤال مرتبط با منابع انسانی است، اما در نسخه فعلی داده/تعریف کافی برای پاسخ دقیق وجود ندارد. دلیل: {reason}"
        if status == ValidationStatus.ANALYTICAL_GAP.value:
            reason = payload.get("reason") or context.intent_result.get(
                "reason") or "شاخص یا سند تحلیلی لازم در MVP فعلی موجود نیست."
            return f"سؤال مرتبط با منابع انسانی است، ولی داده، شاخص یا سند کافی برای تحلیل قابل اتکا فعلاً نداریم. دلیل: {reason}"
        if status == ValidationStatus.ACCESS_DENIED.value:
            return "امکان پاسخ‌گویی به این سؤال وجود ندارد، چون درخواست شامل اطلاعات فردی یا حساس کارکنان است."
        if status == ValidationStatus.OUT_OF_SCOPE.value:
            return "این سؤال خارج از دامنه دستیار BI منابع انسانی است."
        if status == ValidationStatus.NEEDS_CLARIFICATION.value:
            return "سؤال برای سیستم کافی شفاف نیست. لطفاً دقیق‌تر بگویید چه شاخص، بازه یا تفکیکی مدنظر است."
        if status == ValidationStatus.SQL_VALIDATION_FAILED.value:
            return "SQL تولیدشده توسط قوانین امنیتی و اعتبارسنجی رد شد و اجرا نمی‌شود."
        if status == ValidationStatus.EXECUTION_FAILED.value:
            return "SQL معتبر بود، اما هنگام اجرای کوئری خطا رخ داد."
        if status == ValidationStatus.METADATA_ERROR.value:
            return "در بارگذاری یا استفاده از Metadata خطا رخ داد."
        return "پاسخ آماده شد."

    def _extract_rows(self, context: RequestContext) -> Any:
        for key in ("rows", "data", "result", "records"):
            if key in context.query_result:
                return context.query_result[key]
        return None

    @staticmethod
    def _is_terminal(payload: JsonDict) -> bool:
        route = str(payload.get("route") or "").upper()
        status = str(payload.get("status") or "").upper()
        return route in {Route.GAP.value, Route.REJECT.value, Route.NEEDS_CLARIFICATION.value} or status in {
            ValidationStatus.DATA_GAP.value,
            ValidationStatus.ANALYTICAL_GAP.value,
            ValidationStatus.ACCESS_DENIED.value,
            ValidationStatus.OUT_OF_SCOPE.value,
            ValidationStatus.NEEDS_CLARIFICATION.value,
            ValidationStatus.SQL_VALIDATION_FAILED.value,
            ValidationStatus.METADATA_ERROR.value,
        }


# ---------------------------------------------------------------------------
# Generic helpers
# ---------------------------------------------------------------------------


def utc_now_iso() -> str:
    return datetime.now(UTC).isoformat()


async def call_component(component: Any, method_names: list[str], **kwargs: Any) -> Any:
    """Call an injected component with a flexible method name and filtered kwargs."""
    callable_obj: Callable[..., Any] | None = None

    for name in method_names:
        if name == "__call__" and callable(component):
            callable_obj = component
            break
        if hasattr(component, name):
            candidate = getattr(component, name)
            if callable(candidate):
                callable_obj = candidate
                break

    if callable_obj is None:
        raise OrchestratorError(
            f"Component {component!r} does not expose any of: {method_names}")

    filtered_kwargs = filter_kwargs_for_callable(callable_obj, kwargs)
    result = callable_obj(**filtered_kwargs)
    if inspect.isawaitable(result):
        return await result
    return result


def filter_kwargs_for_callable(func: Callable[..., Any], kwargs: Mapping[str, Any]) -> JsonDict:
    try:
        signature = inspect.signature(func)
    except (TypeError, ValueError):
        return dict(kwargs)
    if any(param.kind == inspect.Parameter.VAR_KEYWORD for param in signature.parameters.values()):
        return dict(kwargs)
    allowed = set(signature.parameters)
    return {key: value for key, value in kwargs.items() if key in allowed}


def normalize_result(result: Any) -> JsonDict:
    if result is None:
        return {}
    if isinstance(result, dict):
        return deepcopy(result)
    if is_dataclass(result):
        return asdict(result)
    if hasattr(result, "model_dump"):
        return result.model_dump()  # pydantic v2
    if hasattr(result, "dict"):
        return result.dict()  # pydantic v1
    if hasattr(result, "to_dict"):
        return result.to_dict()
    return {"value": result}


def to_plain_dict(value: Any) -> JsonDict:
    if isinstance(value, dict):
        return deepcopy(value)
    if is_dataclass(value):
        return asdict(value)
    if hasattr(value, "to_dict"):
        return value.to_dict()
    return {"value": value}


def route_for_status(status: str) -> str:
    status = status.upper()
    if status in {ValidationStatus.DATA_GAP.value, ValidationStatus.ANALYTICAL_GAP.value}:
        return Route.GAP.value
    if status == ValidationStatus.NEEDS_CLARIFICATION.value:
        return Route.NEEDS_CLARIFICATION.value
    return Route.REJECT.value


def status_for_route(route: str, *, fallback: str | None = None) -> str:
    route = route.upper()
    fallback = (fallback or "").upper()
    if fallback in {
        ValidationStatus.DATA_GAP.value,
        ValidationStatus.ANALYTICAL_GAP.value,
        ValidationStatus.ACCESS_DENIED.value,
        ValidationStatus.OUT_OF_SCOPE.value,
        ValidationStatus.NEEDS_CLARIFICATION.value,
    }:
        return fallback
    if route == Route.GAP.value:
        return ValidationStatus.DATA_GAP.value
    if route == Route.NEEDS_CLARIFICATION.value:
        return ValidationStatus.NEEDS_CLARIFICATION.value
    if route == Route.REJECT.value:
        return ValidationStatus.ACCESS_DENIED.value
    return ValidationStatus.VALID.value


def normalize_sql(sql: str) -> str:
    sql = sql.strip()
    sql = re.sub(r"\s+", " ", sql)
    return sql


def count_sql_statements(sql: str) -> int:
    """Count statements using semicolons outside simple quoted strings."""
    in_quote = False
    escaped = False
    count_semicolons = 0
    content_seen = bool(sql.strip())
    for char in sql:
        if char == "'" and not escaped:
            in_quote = not in_quote
        if char == ";" and not in_quote:
            count_semicolons += 1
        escaped = char == "\\" and not escaped
    if not content_seen:
        return 0
    # One trailing semicolon is fine. More than one means multi-statement or malformed.
    stripped = sql.strip()
    if count_semicolons == 0:
        return 1
    if count_semicolons == 1 and stripped.endswith(";"):
        return 1
    return max(2, count_semicolons)


def sql_literal(value: Any) -> str:
    if value is None:
        return "NULL"
    if isinstance(value, bool):
        return "TRUE" if value else "FALSE"
    if isinstance(value, int | float):
        return str(value)
    text = str(value).replace("'", "''")
    return f"'{text}'"


def token_overlap(a: str, b: str) -> float:
    tokens_a = set(re.findall(r"[\w\u0600-\u06FF]+", a.lower()))
    tokens_b = set(re.findall(r"[\w\u0600-\u06FF]+", b.lower()))
    if not tokens_a or not tokens_b:
        return 0.0
    return len(tokens_a & tokens_b) / max(1, min(len(tokens_a), len(tokens_b)))


def extract_first_int(text: str) -> int | None:
    normalized = (
        text.replace("۰", "0")
        .replace("۱", "1")
        .replace("۲", "2")
        .replace("۳", "3")
        .replace("۴", "4")
        .replace("۵", "5")
        .replace("۶", "6")
        .replace("۷", "7")
        .replace("۸", "8")
        .replace("۹", "9")
    )
    match = re.search(r"\d+", normalized)
    return int(match.group(0)) if match else None


def redact_sql_for_trace(plan: JsonDict) -> JsonDict:
    # SQL is not sensitive here, but traces should stay compact.
    output = deepcopy(plan)
    sql = output.get("sql")
    if isinstance(sql, str) and len(sql) > 1200:
        output["sql"] = sql[:1200] + "..."
    return output


# ---------------------------------------------------------------------------
# Module-level singleton helper
# ---------------------------------------------------------------------------

_orchestrator: LLMOrchestrator | None = None


def get_llm_orchestrator(
    *,
    reload: bool = False,
    metadata_dir: str | Path | None = None,
    **kwargs: Any,
) -> LLMOrchestrator:
    """Return a process-wide orchestrator singleton."""
    global _orchestrator
    if reload or _orchestrator is None or kwargs:
        _orchestrator = LLMOrchestrator(metadata_dir=metadata_dir, **kwargs)
    return _orchestrator


# ---------------------------------------------------------------------------
# Local smoke test
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    orchestrator = LLMOrchestrator(metadata_dir=Path(
        __file__).parent, default_execute_sql=False, strict_metadata=False)
    sample_questions = [
        "تعداد کل کارکنان چند نفر است؟",
        "چند درصد کارکنان زن هستند؟",
        "تعداد کارکنان ۶۰ سال به بالا چقدر است؟",
        "تعداد کارکنان هر شهر چقدر است؟",
        "نام و مشخصات کارکنان را نمایش بده",
        "فروش ماه گذشته شرکت چقدر بوده؟",
    ]
    for q in sample_questions:
        response = orchestrator.run(q, execute_sql=False)
        print("\nQUESTION:", q)
        print("STATUS:", response.status, "ROUTE:",
              response.route, "INTENT:", response.detected_intent)
        print("MESSAGE:", response.message_fa)
        if response.generated_sql:
            print("SQL:", response.generated_sql)
