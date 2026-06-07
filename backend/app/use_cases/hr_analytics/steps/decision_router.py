from __future__ import annotations
import re
import time
from copy import deepcopy
from dataclasses import asdict, dataclass, field, is_dataclass
from pathlib import Path
from typing import Any, Mapping

from app.infrastructure.metadata.service import MetadataService, get_metadata_service

"""
router.py
---------
Decision Router for HR BI Assistant Phase 2 / Controlled SQL-based MVP.


Purpose:
    Decide the final execution path after domain classification, question validation,
    semantic mapping and intent parsing.

Main routes:
    - SQL: supported aggregated HR analytics question; can be answered from
      hr_mvp.vw_hr_employee_analytics through a controlled SQL template.
    - GAP: HR-related question, but required data, KPI definition, business rule or
      document support is not available in the current MVP.
    - REJECT: non-HR, unsafe, privacy-violating or forbidden request.
    - NEEDS_CLARIFICATION: HR-related but too ambiguous to route safely.

Design principles:
    - Conservative by default.
    - Earlier safety decisions win over later SQL decisions.
    - No SQL is generated here; this module only chooses the route and adds routing
      metadata for sql_template_engine.py, gap_service.py and response_builder.py.
    - The router is metadata-aware but works even if metadata is partially missing.
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
STATUS_METADATA_ERROR = "METADATA_ERROR"

TERMINAL_STATUS_TO_ROUTE: dict[str, str] = {
    STATUS_DATA_GAP: ROUTE_GAP,
    STATUS_ACCESS_DENIED: ROUTE_REJECT,
    STATUS_OUT_OF_SCOPE: ROUTE_REJECT,
    STATUS_NEEDS_CLARIFICATION: ROUTE_CLARIFICATION,
    STATUS_SQL_VALIDATION_FAILED: ROUTE_REJECT,
    STATUS_METADATA_ERROR: ROUTE_REJECT,
}

ROUTE_TO_DEFAULT_STATUS: dict[str, str] = {
    ROUTE_SQL: STATUS_VALID,
    ROUTE_GAP: STATUS_DATA_GAP,
    ROUTE_REJECT: STATUS_ACCESS_DENIED,
    ROUTE_CLARIFICATION: STATUS_NEEDS_CLARIFICATION,
}

STATUS_SQL_BY_STATUS: dict[str, str] = {
    STATUS_DATA_GAP: "SELECT 'DATA_GAP' AS status;",
    STATUS_ACCESS_DENIED: "SELECT 'ACCESS_DENIED' AS status;",
    STATUS_OUT_OF_SCOPE: "SELECT 'OUT_OF_SCOPE' AS status;",
    STATUS_NEEDS_CLARIFICATION: "SELECT 'NEEDS_CLARIFICATION' AS status;",
    STATUS_SQL_VALIDATION_FAILED: "SELECT 'SQL_VALIDATION_FAILED' AS status;",
}


@dataclass
class RouterConfig:
    """Runtime behavior flags for controlled MVP routing."""

    min_sql_confidence: float = 0.35
    require_template_for_sql: bool = True
    allow_dynamic_sql_fallback: bool = False
    allow_partial_reports: bool = True
    enforce_phase2_support: bool = True
    default_user_role: str = "demo_user"
    phase_name: str = "Controlled SQL-based MVP"
    main_view: str = "hr_mvp.vw_hr_employee_analytics"
    main_alias: str = "v"
    max_warnings: int = 20


@dataclass
class RouteDecision:
    route: str
    status: str
    reason: str
    intent: str | None = None
    intent_id: str | None = None
    report_id: str | None = None
    sql_template_id: str | None = None
    confidence: float | None = None
    decision_source: str = "router"
    execution_mode: str | None = None
    can_execute_sql: bool = False
    expected_status_sql: str | None = None
    output_type: str | None = None
    recommended_visualization: str | None = None
    required_columns: list[str] = field(default_factory=list)
    missing_columns: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    policy_hints: JsonDict = field(default_factory=dict)
    metadata: JsonDict = field(default_factory=dict)
    duration_ms: float | None = None

    def to_dict(self) -> JsonDict:
        return asdict(self)


class DecisionRouter:
    """
    Metadata-aware conservative router.

    Public API:
        router.route(question, context=None, metadata=None)
        router.run(...)
        await router.arun(...)
        router(...)

    The return value is a plain dictionary so it can be stored directly in
    RequestContext.route_result by llm_orchestrator.py.
    """

    def __init__(self, metadata_service: Any | None = None, config: RouterConfig | None = None) -> None:
        if metadata_service is not None:
            self.metadata = metadata_service
        elif get_metadata_service is not None:
            self.metadata = get_metadata_service(
                strict=False)  # type: ignore[misc]
            try:
                health = self.metadata.health_check().to_dict() if hasattr(
                    self.metadata, "health_check") else {}
                # type: ignore[comparison-overlap]
                if not health.get("ok") and MetadataService is not Any:
                    local_dir = Path(__file__).resolve().parent
                    if (local_dir / "Template_00_data_dictionary.yaml").exists() or (local_dir / "data_dictionary.yaml").exists():
                        self.metadata = MetadataService(
                            # type: ignore[operator]
                            metadata_dir=local_dir, strict=False)
            except Exception:
                pass
        else:
            self.metadata = None
        self.config = config or RouterConfig()

    # ------------------------------------------------------------------
    # Public entry points
    # ------------------------------------------------------------------

    def __call__(self, question: str, context: Any | None = None, metadata: Any | None = None, **kwargs: Any) -> JsonDict:
        return self.route(question=question, context=context, metadata=metadata, **kwargs)

    def run(self, question: str, context: Any | None = None, metadata: Any | None = None, **kwargs: Any) -> JsonDict:
        return self.route(question=question, context=context, metadata=metadata, **kwargs)

    async def arun(self, question: str, context: Any | None = None, metadata: Any | None = None, **kwargs: Any) -> JsonDict:
        return self.route(question=question, context=context, metadata=metadata, **kwargs)

    def route(self, question: str, context: Any | None = None, metadata: Any | None = None, **kwargs: Any) -> JsonDict:
        started = time.perf_counter()
        service = metadata or self.metadata
        normalized_question = self._normalize_question(question, service)
        user_role = self._get_user_role(context, kwargs)
        warnings: list[str] = []

        if not normalized_question:
            return self._decision(
                route=ROUTE_CLARIFICATION,
                status=STATUS_NEEDS_CLARIFICATION,
                reason="Question is empty or unclear.",
                decision_source="router.empty_question",
                started=started,
                service=service,
                user_role=user_role,
            )

        metadata_health = self._metadata_health(service)
        if metadata_health and metadata_health.get("errors"):
            warnings.extend(str(item)
                            for item in metadata_health.get("errors", [])[:5])

        # 1) Previous terminal results win. This preserves privacy and safety.
        terminal = self._terminal_from_previous_steps(context, service)
        if terminal:
            terminal["warnings"] = list(dict.fromkeys(
                (terminal.get("warnings") or []) + warnings))[: self.config.max_warnings]
            terminal["duration_ms"] = self._elapsed_ms(started)
            return terminal

        # 2) Intent result is the main routing signal after validation.
        intent_result = self._context_dict(context, "intent_result")
        semantic_result = self._context_dict(context, "semantic_result")
        validation_result = self._context_dict(context, "validation_result")
        domain_result = self._context_dict(context, "domain_result")

        if not intent_result:
            # If semantic mapper already knows it is a Data Gap / Reject, use that.
            semantic_terminal = self._terminal_from_payload(
                semantic_result,
                source="semantic_mapper",
                service=service,
                user_role=user_role,
                started=started,
            )
            if semantic_terminal:
                semantic_terminal["warnings"] = list(dict.fromkeys(
                    (semantic_terminal.get("warnings") or []) + warnings))[: self.config.max_warnings]
                semantic_terminal["duration_ms"] = self._elapsed_ms(started)
                return semantic_terminal

            return self._decision(
                route=ROUTE_CLARIFICATION,
                status=STATUS_NEEDS_CLARIFICATION,
                reason="No intent result was available for routing.",
                decision_source="router.no_intent",
                started=started,
                service=service,
                user_role=user_role,
                warnings=warnings,
            )

        intent_id = self._first_present(
            intent_result, "intent_id", "intent", "detected_intent")
        confidence = self._safe_float(intent_result.get("confidence"))
        intent_route = str(intent_result.get("route") or "").upper().strip()
        intent_status = str(intent_result.get("status") or "").upper().strip()

        # 3) Terminal route/status from intent parser wins, but normalized.
        if intent_route in {ROUTE_GAP, ROUTE_REJECT, ROUTE_CLARIFICATION} or intent_status in TERMINAL_STATUS_TO_ROUTE:
            status = self._status_for_terminal(intent_route, intent_status)
            route = self._route_for_status_or_route(
                status=status, route=intent_route)
            return self._decision(
                route=route,
                status=status,
                reason=str(intent_result.get("reason") or intent_result.get(
                    "gap_reason") or intent_result.get("reject_reason") or "Terminal intent decision."),
                decision_source="intent_parser.terminal",
                intent_id=str(intent_id) if intent_id else None,
                report_id=self._str_or_none(intent_result.get("report_id")),
                confidence=confidence,
                output_type=self._str_or_none(
                    intent_result.get("output_type")) or "status_message",
                recommended_visualization=self._str_or_none(
                    intent_result.get("recommended_visualization")) or "status_message",
                expected_status_sql=self._status_sql(status, service),
                started=started,
                service=service,
                user_role=user_role,
                warnings=warnings,
                extra_metadata={
                    "intent_result_status": intent_result.get("status"),
                    "intent_result_route": intent_result.get("route"),
                    "domain_status": domain_result.get("status"),
                    "validation_status": validation_result.get("status"),
                },
            )

        # 4) Low confidence should never enter SQL execution.
        if confidence is not None and confidence < self.config.min_sql_confidence:
            return self._decision(
                route=ROUTE_CLARIFICATION,
                status=STATUS_NEEDS_CLARIFICATION,
                reason=f"Intent confidence is too low for safe routing: {confidence:.3f}.",
                decision_source="router.low_confidence",
                intent_id=str(intent_id) if intent_id else None,
                confidence=confidence,
                output_type="status_message",
                recommended_visualization="status_message",
                expected_status_sql=self._status_sql(
                    STATUS_NEEDS_CLARIFICATION, service),
                started=started,
                service=service,
                user_role=user_role,
                warnings=warnings,
            )

        # 5) Metadata context check for SQL intents.
        intent_meta = self._get_intent(
            service, str(intent_id)) if intent_id else None
        if not intent_meta and intent_id:
            warnings.append(
                f"Intent '{intent_id}' was not found in intent_catalog metadata.")

        catalog_route = str((intent_meta or {}).get(
            "route") or "").upper().strip()
        if catalog_route in {ROUTE_GAP, ROUTE_REJECT, ROUTE_CLARIFICATION}:
            status = self._status_for_terminal(
                catalog_route, str((intent_meta or {}).get("status") or ""))
            return self._decision(
                route=self._route_for_status_or_route(
                    status=status, route=catalog_route),
                status=status,
                reason=str((intent_meta or {}).get("gap_reason") or (intent_meta or {}).get(
                    "reject_reason") or "Metadata catalog routes this intent away from SQL."),
                decision_source="intent_catalog.terminal",
                intent_id=str(intent_id) if intent_id else None,
                report_id=self._str_or_none(intent_result.get(
                    "report_id") or (intent_meta or {}).get("report_id")),
                confidence=confidence,
                output_type="status_message",
                recommended_visualization="status_message",
                expected_status_sql=self._status_sql(status, service),
                started=started,
                service=service,
                user_role=user_role,
                warnings=warnings,
            )

        # 6) Phase-2 support check.
        supported = intent_result.get("supported_in_phase2")
        if supported is None and intent_meta:
            supported = intent_meta.get("supported_in_phase2")
        if self.config.enforce_phase2_support and supported is False:
            return self._decision(
                route=ROUTE_GAP,
                status=STATUS_DATA_GAP,
                reason="This HR intent is not supported in the current Controlled SQL-based MVP.",
                decision_source="router.unsupported_phase2",
                intent_id=str(intent_id) if intent_id else None,
                report_id=self._str_or_none(intent_result.get(
                    "report_id") or (intent_meta or {}).get("report_id")),
                confidence=confidence,
                output_type="status_message",
                recommended_visualization="status_message",
                expected_status_sql=self._status_sql(STATUS_DATA_GAP, service),
                started=started,
                service=service,
                user_role=user_role,
                warnings=warnings,
            )

        # 7) Ensure required columns exist and are allowed for aggregated analytics.
        required_columns = self._merge_lists(intent_result.get(
            "required_columns"), (intent_meta or {}).get("required_columns"))
        missing_columns = self._missing_columns(required_columns, service)
        if missing_columns:
            warnings.append(
                "Some required columns are missing from data_dictionary: " + ", ".join(missing_columns))
            return self._decision(
                route=ROUTE_GAP,
                status=STATUS_DATA_GAP,
                reason="The detected intent needs columns that are not available in the current analytics View metadata.",
                decision_source="router.missing_columns",
                intent_id=str(intent_id) if intent_id else None,
                report_id=self._str_or_none(intent_result.get(
                    "report_id") or (intent_meta or {}).get("report_id")),
                confidence=confidence,
                required_columns=required_columns,
                missing_columns=missing_columns,
                output_type="status_message",
                recommended_visualization="status_message",
                expected_status_sql=self._status_sql(STATUS_DATA_GAP, service),
                started=started,
                service=service,
                user_role=user_role,
                warnings=warnings,
            )

        # 8) Resolve report and SQL template for supported SQL route.
        report_id = self._str_or_none(intent_result.get(
            "report_id") or (intent_meta or {}).get("report_id"))
        report_meta = self._get_report(
            service, report_id) if report_id else None
        report_status = str((report_meta or {}).get("status") or "").lower()
        if report_status in {"data_gap", "unsupported", "not_ready"}:
            return self._decision(
                route=ROUTE_GAP,
                status=STATUS_DATA_GAP,
                reason=str((report_meta or {}).get(
                    "gap_reason") or "The related report is marked as Data Gap / not ready."),
                decision_source="report_catalog.data_gap",
                intent_id=str(intent_id) if intent_id else None,
                report_id=report_id,
                confidence=confidence,
                output_type="status_message",
                recommended_visualization="status_message",
                expected_status_sql=self._status_sql(STATUS_DATA_GAP, service),
                started=started,
                service=service,
                user_role=user_role,
                warnings=warnings,
            )
        if report_status == "partial_for_demo" and not self.config.allow_partial_reports:
            return self._decision(
                route=ROUTE_GAP,
                status=STATUS_DATA_GAP,
                reason="The related report is only partially supported and partial reports are disabled.",
                decision_source="report_catalog.partial_disabled",
                intent_id=str(intent_id) if intent_id else None,
                report_id=report_id,
                confidence=confidence,
                output_type="status_message",
                recommended_visualization="status_message",
                expected_status_sql=self._status_sql(STATUS_DATA_GAP, service),
                started=started,
                service=service,
                user_role=user_role,
                warnings=warnings,
            )
        if report_status == "partial_for_demo":
            warnings.append(
                "The related report is marked as partial_for_demo; output should show a limitation note.")

        sql_template_id = self._resolve_template_id(
            intent_result, intent_meta, report_meta, service)
        sql_template = self._get_sql_template(
            service, sql_template_id) if sql_template_id else None
        if sql_template_id and not sql_template:
            warnings.append(
                f"SQL template '{sql_template_id}' was referenced but not found.")

        if self.config.require_template_for_sql and not sql_template:
            if self.config.allow_dynamic_sql_fallback:
                warnings.append(
                    "No SQL template found; dynamic SQL generator fallback is allowed by config.")
                execution_mode = "dynamic_sql_generator"
            else:
                return self._decision(
                    route=ROUTE_CLARIFICATION,
                    status=STATUS_NEEDS_CLARIFICATION,
                    reason="No safe SQL template was found for the detected SQL intent.",
                    decision_source="router.no_sql_template",
                    intent_id=str(intent_id) if intent_id else None,
                    report_id=report_id,
                    sql_template_id=sql_template_id,
                    confidence=confidence,
                    required_columns=required_columns,
                    output_type="status_message",
                    recommended_visualization="status_message",
                    expected_status_sql=self._status_sql(
                        STATUS_NEEDS_CLARIFICATION, service),
                    started=started,
                    service=service,
                    user_role=user_role,
                    warnings=warnings,
                )
        else:
            execution_mode = "sql_template" if sql_template else "dynamic_sql_generator"

        # 9) Role and policy hints. Detailed enforcement remains in access_policy_engine/sql_validator.
        policy_hints = self._build_policy_hints(
            user_role=user_role, intent_result=intent_result, service=service)
        if policy_hints.get("deny_sql"):
            return self._decision(
                route=ROUTE_REJECT,
                status=STATUS_ACCESS_DENIED,
                reason=str(policy_hints.get("reason")
                           or "User role is not allowed to run this request."),
                decision_source="router.access_policy_hint",
                intent_id=str(intent_id) if intent_id else None,
                report_id=report_id,
                sql_template_id=sql_template_id,
                confidence=confidence,
                required_columns=required_columns,
                output_type="status_message",
                recommended_visualization="status_message",
                expected_status_sql=self._status_sql(
                    STATUS_ACCESS_DENIED, service),
                started=started,
                service=service,
                user_role=user_role,
                warnings=warnings,
                policy_hints=policy_hints,
            )

        output_type = self._str_or_none(intent_result.get(
            "output_type") or (sql_template or {}).get("output_type"))
        recommended_visualization = self._str_or_none(
            intent_result.get("recommended_visualization")
            or (report_meta or {}).get("recommended_visualization")
            or self._visualization_for_intent(service, str(intent_id) if intent_id else None)
        )

        # Final SQL route.
        return self._decision(
            route=ROUTE_SQL,
            status=STATUS_VALID,
            reason="Supported SQL intent with controlled metadata route.",
            decision_source="router.sql_ready",
            intent_id=str(intent_id) if intent_id else None,
            report_id=report_id,
            sql_template_id=sql_template_id,
            confidence=confidence,
            required_columns=required_columns,
            output_type=output_type,
            recommended_visualization=recommended_visualization,
            execution_mode=execution_mode,
            can_execute_sql=True,
            started=started,
            service=service,
            user_role=user_role,
            warnings=warnings,
            policy_hints=policy_hints,
            extra_metadata={
                "phase": self.config.phase_name,
                "main_view": self.config.main_view,
                "main_alias": self.config.main_alias,
                "report_status": report_status or None,
                "template_found": bool(sql_template),
                "semantic_route_candidates": semantic_result.get("candidate_routes") or [],
            },
        )

    # ------------------------------------------------------------------
    # Previous-step terminal handling
    # ------------------------------------------------------------------

    def _terminal_from_previous_steps(self, context: Any, service: Any) -> JsonDict | None:
        # The order matters: domain -> validation -> semantic -> intent. Earlier
        # safety decisions must not be overwritten by later weaker matches.
        for step_name in ("domain_result", "validation_result", "semantic_result", "intent_result"):
            payload = self._context_dict(context, step_name)
            decision = self._terminal_from_payload(
                payload,
                source=step_name,
                service=service,
                user_role=self._get_user_role(context, {}),
                started=None,
            )
            if decision:
                return decision
        return None

    def _terminal_from_payload(
        self,
        payload: JsonDict,
        *,
        source: str,
        service: Any,
        user_role: str,
        started: float | None,
    ) -> JsonDict | None:
        if not payload:
            return None

        raw_status = str(payload.get("status") or "").upper().strip()
        raw_route = str(payload.get("route") or "").upper().strip()
        # status=supported is not terminal.
        if raw_status in {"", STATUS_OK, STATUS_VALID, STATUS_SUPPORTED.upper(), "SUPPORTED"} and raw_route not in {
            ROUTE_GAP,
            ROUTE_REJECT,
            ROUTE_CLARIFICATION,
        }:
            return None

        if raw_status in TERMINAL_STATUS_TO_ROUTE or raw_route in {ROUTE_GAP, ROUTE_REJECT, ROUTE_CLARIFICATION}:
            status = self._status_for_terminal(raw_route, raw_status)
            route = self._route_for_status_or_route(
                status=status, route=raw_route)
            intent_id = self._first_present(
                payload, "intent_id", "intent", "detected_intent")
            return self._decision(
                route=route,
                status=status,
                reason=str(payload.get("reason") or payload.get("gap_reason") or payload.get(
                    "reject_reason") or f"Terminal decision from {source}."),
                decision_source=source,
                intent_id=str(intent_id) if intent_id else None,
                report_id=self._str_or_none(payload.get("report_id")),
                sql_template_id=None,
                confidence=self._safe_float(payload.get("confidence")),
                output_type=self._str_or_none(
                    payload.get("output_type")) or "status_message",
                recommended_visualization=self._str_or_none(
                    payload.get("recommended_visualization")) or "status_message",
                expected_status_sql=self._status_sql(status, service),
                started=started,
                service=service,
                user_role=user_role,
                warnings=self._as_str_list(payload.get("warnings")),
                extra_metadata={"source_payload_status": raw_status,
                                "source_payload_route": raw_route},
            )
        return None

    # ------------------------------------------------------------------
    # Decision builder
    # ------------------------------------------------------------------

    def _decision(
        self,
        *,
        route: str,
        status: str,
        reason: str,
        decision_source: str,
        started: float | None,
        service: Any,
        user_role: str,
        intent_id: str | None = None,
        report_id: str | None = None,
        sql_template_id: str | None = None,
        confidence: float | None = None,
        execution_mode: str | None = None,
        can_execute_sql: bool | None = None,
        expected_status_sql: str | None = None,
        output_type: str | None = None,
        recommended_visualization: str | None = None,
        required_columns: list[str] | None = None,
        missing_columns: list[str] | None = None,
        warnings: list[str] | None = None,
        policy_hints: JsonDict | None = None,
        extra_metadata: JsonDict | None = None,
    ) -> JsonDict:
        normalized_route = route.upper().strip()
        normalized_status = self._normalize_status(status, normalized_route)
        if can_execute_sql is None:
            can_execute_sql = normalized_route == ROUTE_SQL and normalized_status == STATUS_VALID
        if expected_status_sql is None and normalized_route != ROUTE_SQL:
            expected_status_sql = self._status_sql(normalized_status, service)

        decision = RouteDecision(
            route=normalized_route,
            status=normalized_status,
            reason=reason,
            intent=intent_id,
            intent_id=intent_id,
            report_id=report_id,
            sql_template_id=sql_template_id,
            confidence=confidence,
            decision_source=decision_source,
            execution_mode=execution_mode,
            can_execute_sql=bool(can_execute_sql),
            expected_status_sql=expected_status_sql,
            output_type=output_type,
            recommended_visualization=recommended_visualization,
            required_columns=required_columns or [],
            missing_columns=missing_columns or [],
            warnings=list(dict.fromkeys((warnings or [])
                          [: self.config.max_warnings])),
            policy_hints=policy_hints or self._build_policy_hints(
                user_role=user_role, intent_result={}, service=service),
            metadata={
                "phase": self.config.phase_name,
                "main_view": self.config.main_view,
                "main_alias": self.config.main_alias,
                "user_role": user_role,
                **(extra_metadata or {}),
            },
            duration_ms=self._elapsed_ms(started) if started else None,
        )
        return decision.to_dict()

    # ------------------------------------------------------------------
    # Metadata helpers
    # ------------------------------------------------------------------

    def _get_intent(self, service: Any, intent_id: str | None) -> JsonDict | None:
        if not service or not intent_id:
            return None
        try:
            if hasattr(service, "get_intent"):
                item = service.get_intent(intent_id)
                return deepcopy(item) if item else None
        except Exception:
            return None
        return None

    def _get_report(self, service: Any, report_id: str | None) -> JsonDict | None:
        if not service or not report_id:
            return None
        try:
            if hasattr(service, "get_report"):
                item = service.get_report(report_id)
                return deepcopy(item) if item else None
        except Exception:
            return None
        return None

    def _get_sql_template(self, service: Any, template_id: str | None) -> JsonDict | None:
        if not service or not template_id:
            return None
        try:
            if hasattr(service, "get_sql_template"):
                item = service.get_sql_template(template_id)
                return deepcopy(item) if item else None
        except Exception:
            return None
        return None

    def _resolve_template_id(self, intent_result: JsonDict, intent_meta: JsonDict | None, report_meta: JsonDict | None, service: Any) -> str | None:
        # Priority: parsed intent -> catalog intent -> related report -> template with matching intent.
        for value in (
            intent_result.get("sql_template_id"),
            (intent_meta or {}).get("sql_template_id"),
            (report_meta or {}).get("sql_template_id"),
        ):
            value = self._str_or_none(value)
            if value:
                try:
                    if service and hasattr(service, "resolve_sql_template_id"):
                        return str(service.resolve_sql_template_id(value))
                except Exception:
                    pass
                return value

        intent_id = self._first_present(
            intent_result, "intent_id", "intent", "detected_intent")
        if service and intent_id:
            try:
                if hasattr(service, "list_sql_templates"):
                    for template in service.list_sql_templates():
                        if str(template.get("intent") or "") == str(intent_id):
                            return self._str_or_none(template.get("template_id"))
            except Exception:
                pass
        return None

    def _visualization_for_intent(self, service: Any, intent_id: str | None) -> str | None:
        if not service or not intent_id:
            return None
        try:
            if hasattr(service, "get_visualization_for_intent"):
                visual = service.get_visualization_for_intent(intent_id) or {}
                return self._str_or_none(
                    visual.get("primary_visualization")
                    or visual.get("recommended_visualization")
                    or visual.get("visualization")
                )
        except Exception:
            return None
        return None

    def _missing_columns(self, columns: list[str], service: Any) -> list[str]:
        if not columns or not service or not hasattr(service, "get_column"):
            return []
        missing: list[str] = []
        for column in columns:
            # Some entries can be formulas or aliases; validate only simple column identifiers.
            if not re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*", str(column)):
                continue
            try:
                if service.get_column(str(column)) is None:
                    missing.append(str(column))
            except Exception:
                continue
        return sorted(set(missing))

    def _metadata_health(self, service: Any) -> JsonDict:
        if not service or not hasattr(service, "health_check"):
            return {}
        try:
            health = service.health_check()
            return self._to_plain_dict(health)
        except Exception as exc:
            return {"ok": False, "errors": [str(exc)]}

    def _status_sql(self, status: str, service: Any) -> str | None:
        normalized = self._normalize_status(status, route=None)
        if service and hasattr(service, "get_status_sql"):
            try:
                sql = service.get_status_sql(normalized)
                if sql:
                    return str(sql).strip()
            except Exception:
                pass
        return STATUS_SQL_BY_STATUS.get(normalized)

    def _build_policy_hints(self, *, user_role: str, intent_result: JsonDict, service: Any) -> JsonDict:
        min_group_size = 5
        try:
            if service and hasattr(service, "get_min_group_size"):
                min_group_size = int(service.get_min_group_size(default=5))
        except Exception:
            min_group_size = 5

        route = str(intent_result.get("route") or "").upper()
        output_type = str(intent_result.get("output_type") or "")
        return {
            "user_role": user_role or self.config.default_user_role,
            "deny_sql": False,
            "reason": None,
            "aggregated_output_only": True,
            "minimum_group_size": min_group_size,
            "suppress_small_groups": True,
            "employee_level_output_allowed": False,
            "visible_employee_id_allowed": False,
            "status_output": route in {ROUTE_GAP, ROUTE_REJECT, ROUTE_CLARIFICATION} or output_type == "status_message",
        }

    # ------------------------------------------------------------------
    # Normalization helpers
    # ------------------------------------------------------------------

    def _normalize_question(self, question: str, service: Any) -> str:
        if service and hasattr(service, "normalize_question"):
            try:
                return str(service.normalize_question(question or ""))
            except Exception:
                pass
        text = str(question or "").strip()
        replacements = {"ي": "ی", "ك": "ک", "ة": "ه", "ۀ": "ه"}
        for src, dst in replacements.items():
            text = text.replace(src, dst)
        return re.sub(r"\s+", " ", text)

    def _status_for_terminal(self, route: str, status: str) -> str:
        route = str(route or "").upper().strip()
        status = str(status or "").upper().strip()
        if status in TERMINAL_STATUS_TO_ROUTE:
            return status
        if route == ROUTE_GAP:
            return STATUS_DATA_GAP
        if route == ROUTE_CLARIFICATION:
            return STATUS_NEEDS_CLARIFICATION
        if route == ROUTE_REJECT:
            if status == STATUS_OUT_OF_SCOPE:
                return STATUS_OUT_OF_SCOPE
            return STATUS_ACCESS_DENIED
        if route == ROUTE_SQL:
            return STATUS_VALID
        return status or ROUTE_TO_DEFAULT_STATUS.get(route, STATUS_NEEDS_CLARIFICATION)

    def _route_for_status_or_route(self, *, status: str, route: str) -> str:
        route = str(route or "").upper().strip()
        status = str(status or "").upper().strip()
        if route in {ROUTE_SQL, ROUTE_GAP, ROUTE_REJECT, ROUTE_CLARIFICATION}:
            # ACCESS_DENIED and OUT_OF_SCOPE must remain REJECT even if source route is absent.
            if status in {STATUS_ACCESS_DENIED, STATUS_OUT_OF_SCOPE}:
                return ROUTE_REJECT
            return route
        return TERMINAL_STATUS_TO_ROUTE.get(status, ROUTE_CLARIFICATION)

    def _normalize_status(self, status: str, route: str | None) -> str:
        status = str(status or "").upper().strip()
        route = str(route or "").upper().strip()
        if status in {"", STATUS_OK, "SUPPORTED", STATUS_SUPPORTED.upper()}:
            return ROUTE_TO_DEFAULT_STATUS.get(route, STATUS_VALID if route == ROUTE_SQL else STATUS_NEEDS_CLARIFICATION)
        if status == "VALIDATED":
            return STATUS_VALID
        return status

    def _get_user_role(self, context: Any | None, kwargs: Mapping[str, Any]) -> str:
        for value in (
            kwargs.get("user_role"),
            self._get_context_value(context, "user_role"),
            self._get_context_dict_value(
                context, "runtime_params", "user_role"),
        ):
            if value:
                return str(value)
        return self.config.default_user_role

    def _context_dict(self, context: Any | None, key: str) -> JsonDict:
        if context is None:
            return {}
        if isinstance(context, Mapping):
            value = context.get(key, {})
        else:
            value = getattr(context, key, {})
        return self._to_plain_dict(value)

    def _get_context_value(self, context: Any | None, key: str) -> Any:
        if context is None:
            return None
        if isinstance(context, Mapping):
            return context.get(key)
        return getattr(context, key, None)

    def _get_context_dict_value(self, context: Any | None, dict_key: str, value_key: str) -> Any:
        payload = self._context_dict(context, dict_key)
        return payload.get(value_key)

    @staticmethod
    def _to_plain_dict(value: Any) -> JsonDict:
        if value is None:
            return {}
        if isinstance(value, dict):
            return deepcopy(value)
        if is_dataclass(value):
            return asdict(value)
        if hasattr(value, "to_dict"):
            try:
                result = value.to_dict()
                return deepcopy(result) if isinstance(result, dict) else {}
            except Exception:
                return {}
        return {}

    @staticmethod
    def _first_present(payload: Mapping[str, Any], *keys: str) -> Any:
        for key in keys:
            value = payload.get(key)
            if value not in (None, "", []):
                return value
        return None

    @staticmethod
    def _str_or_none(value: Any) -> str | None:
        if value in (None, "", []):
            return None
        return str(value)

    @staticmethod
    def _safe_float(value: Any) -> float | None:
        if value in (None, ""):
            return None
        try:
            return float(value)
        except Exception:
            return None

    @staticmethod
    def _as_str_list(value: Any) -> list[str]:
        if value is None:
            return []
        if isinstance(value, str):
            return [value]
        if isinstance(value, list | tuple | set):
            return [str(item) for item in value if item not in (None, "")]
        return [str(value)]

    def _merge_lists(self, *values: Any) -> list[str]:
        items: list[str] = []
        for value in values:
            if isinstance(value, str):
                items.append(value)
            elif isinstance(value, list | tuple | set):
                items.extend(str(item)
                             for item in value if item not in (None, ""))
        return list(dict.fromkeys(items))

    @staticmethod
    def _elapsed_ms(started: float | None) -> float | None:
        if started is None:
            return None
        return round((time.perf_counter() - started) * 1000, 3)


# Backward-compatible alias. llm_orchestrator.py can receive either class.
Router = DecisionRouter


_ROUTER_SINGLETON: DecisionRouter | None = None


def get_router(*, reload: bool = False, metadata_service: Any | None = None, config: RouterConfig | None = None) -> DecisionRouter:
    global _ROUTER_SINGLETON
    if reload or _ROUTER_SINGLETON is None or metadata_service is not None or config is not None:
        _ROUTER_SINGLETON = DecisionRouter(
            metadata_service=metadata_service, config=config)
    return _ROUTER_SINGLETON


if __name__ == "__main__":  # pragma: no cover - manual smoke test
    class Ctx:
        def __init__(self, intent_result: JsonDict):
            self.domain_result = {"status": "OK", "is_hr": True}
            self.validation_result = {"status": "OK", "is_valid": True}
            self.semantic_result = {"status": "OK"}
            self.intent_result = intent_result
            self.user_role = "demo_user"

    samples = [
        {
            "intent_id": "total_employee_count",
            "route": "SQL",
            "status": "supported",
            "confidence": 0.91,
            "sql_template_id": "TPL_TOTAL_EMPLOYEE_COUNT",
            "required_columns": ["employee_id", "is_active"],
            "recommended_visualization": "kpi_card",
        },
        {
            "intent_id": "city_level_analysis",
            "route": "GAP",
            "status": "DATA_GAP",
            "confidence": 0.95,
            "reason": "City data is not reliable in the current MVP.",
        },
        {
            "intent_id": "individual_employee_info",
            "route": "REJECT",
            "status": "ACCESS_DENIED",
            "confidence": 0.99,
            "reason": "Individual employee information is not allowed.",
        },
    ]

    router = DecisionRouter()
    for sample in samples:
        decision = router.route("تست", context=Ctx(sample))
        print(sample["intent_id"], "=>", decision["route"],
              decision["status"], decision.get("sql_template_id"))
