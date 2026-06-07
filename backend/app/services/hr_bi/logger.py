"""
logger.py

Structured logging and audit service for HR BI Assistant - Phase 2
Controlled SQL-based MVP.

Responsibilities:
- Write safe JSONL logs for requests, orchestration steps, SQL generation,
  SQL validation, query execution, response building, gaps, rejects, security
  events, errors, and evaluation runs.
- Redact sensitive HR/personal values before persistence.
- Avoid storing raw employee-level data or sensitive identifiers.
- Provide lightweight helpers for reading/searching logs during pilot review.

Place this file in:
    backend/app/services/logger.py

The module is dependency-light and uses only Python standard library.
It is intentionally compatible with the other Phase 2 services built in this
project, including llm_orchestrator.py, sql_validator.py, query_executor.py,
gap_service.py, response_builder.py, evaluation_service.py, and
metrics_collector.py.
"""

from __future__ import annotations

import csv
import hashlib
import json
import logging
import os
import re
import sys
import time
import traceback
import uuid
from contextlib import contextmanager
from dataclasses import asdict, dataclass, field, is_dataclass
from datetime import date, datetime, timezone
from decimal import Decimal
from enum import Enum
from pathlib import Path
from typing import Any, Dict, Iterator, List, Mapping, Optional, Sequence, Union


JsonDict = Dict[str, Any]
JsonLike = Union[JsonDict, List[Any], str, int, float, bool, None]


# -----------------------------------------------------------------------------
# Constants and redaction patterns
# -----------------------------------------------------------------------------

DEFAULT_LOG_DIR = "logs"

SENSITIVE_KEY_PATTERNS = [
    r"national[_\s-]?id",
    r"personnel[_\s-]?number",
    r"employee[_\s-]?number",
    r"first[_\s-]?name",
    r"last[_\s-]?name",
    r"full[_\s-]?name",
    r"father[_\s-]?name",
    r"birth[_\s-]?certificate",
    r"phone",
    r"mobile",
    r"email",
    r"address",
    r"postal[_\s-]?code",
    r"bank",
    r"iban",
    r"card[_\s-]?number",
    r"insurance",
    r"salary",
    r"wage",
    r"payroll",
    r"password",
    r"token",
    r"secret",
    r"api[_\s-]?key",
    r"authorization",
    r"cookie",
]

SENSITIVE_FA_KEYWORDS = [
    "کد ملی",
    "شماره ملی",
    "شماره پرسنلی",
    "نام خانوادگی",
    "نام و نام خانوادگی",
    "شماره تماس",
    "موبایل",
    "تلفن",
    "آدرس",
    "حساب بانکی",
    "شماره حساب",
    "شماره کارت",
    "حقوق",
    "دستمزد",
    "بیمه",
]

SENSITIVE_TEXT_PATTERNS = [
    # Iranian national-id-like 10 digit values. Conservative, but enough for logging.
    re.compile(r"(?<!\d)\d{10}(?!\d)"),
    # Iranian mobile-like values.
    re.compile(r"(?<!\d)(?:\+?98|0)?9\d{9}(?!\d)"),
    # Bearer/API tokens.
    re.compile(r"(?i)bearer\s+[a-z0-9._\-]+"),
    re.compile(r"(?i)(api[_\-]?key|token|secret|password)\s*[:=]\s*[^\s,;]+"),
]

RAW_TABLE_PATTERNS = [
    r"hr_mvp\.hr_employees",
    r"hr_mvp\.hr_contracts",
    r"hr_mvp\.hr_employee_education",
    r"hr_mvp\.hr_education_levels",
    r"hr_mvp\.hr_departments",
    r"hr_mvp\.hr_positions",
    r"hr_mvp\.hr_locations",
    r"hr_mvp\.hr_age_groups",
]

SAFE_STATUS_SQL_VALUES = {
    "DATA_GAP",
    "ACCESS_DENIED",
    "OUT_OF_SCOPE",
    "NEEDS_CLARIFICATION",
    "SQL_VALIDATION_FAILED",
    "NO_DATA",
}


# -----------------------------------------------------------------------------
# Data models
# -----------------------------------------------------------------------------

class LogLevel(str, Enum):
    DEBUG = "DEBUG"
    INFO = "INFO"
    WARNING = "WARNING"
    ERROR = "ERROR"
    CRITICAL = "CRITICAL"


class LogCategory(str, Enum):
    REQUEST = "request"
    STEP = "step"
    DECISION = "decision"
    SQL = "sql"
    QUERY = "query"
    RESPONSE = "response"
    GAP = "gap"
    REJECT = "reject"
    SECURITY = "security"
    AUDIT = "audit"
    ERROR = "error"
    EVALUATION = "evaluation"
    SYSTEM = "system"


@dataclass
class LogEvent:
    """A single structured log event persisted as JSONL."""

    event_id: str
    timestamp: str
    level: str
    category: str
    message: str
    request_id: Optional[str] = None
    conversation_id: Optional[str] = None
    user_id_hash: Optional[str] = None
    user_role: Optional[str] = None
    session_id: Optional[str] = None
    module: Optional[str] = None
    route: Optional[str] = None
    status: Optional[str] = None
    intent_id: Optional[str] = None
    report_id: Optional[str] = None
    sql_template_id: Optional[str] = None
    duration_ms: Optional[float] = None
    row_count: Optional[int] = None
    risk_level: Optional[str] = None
    question_hash: Optional[str] = None
    sql_hash: Optional[str] = None
    error_type: Optional[str] = None
    error_message: Optional[str] = None
    details: JsonDict = field(default_factory=dict)


@dataclass
class LogConfig:
    """Configuration for StructuredLogger."""

    log_dir: Union[str, Path] = DEFAULT_LOG_DIR
    app_log_file: str = "app_events.jsonl"
    request_log_file: str = "request_logs.jsonl"
    sql_log_file: str = "query_logs.jsonl"
    audit_log_file: str = "audit_events.jsonl"
    security_log_file: str = "security_events.jsonl"
    error_log_file: str = "error_logs.jsonl"
    evaluation_log_file: str = "evaluation_logs.jsonl"
    plain_text_log_file: str = "app.log"
    enable_console: bool = False
    enable_plain_text_log: bool = True
    min_level: str = "INFO"
    redact_sensitive: bool = True
    store_question_text: bool = False
    store_sql_text: bool = True
    max_detail_chars: int = 20_000
    max_log_file_bytes: int = 50 * 1024 * 1024
    rotate_keep: int = 5


# -----------------------------------------------------------------------------
# Main logger service
# -----------------------------------------------------------------------------

class StructuredLogger:
    """
    Structured JSONL logger for the HR BI Assistant.

    Typical usage:

        logger = StructuredLogger()
        logger.log_request_started(question="تعداد کل کارکنان چند نفر است؟")
        logger.log_step(module="intent_parser", status="SUCCESS", duration_ms=12.4)
        logger.log_sql_validation(status="VALID", sql=generated_sql)
        logger.log_response(status="SUCCESS", route="SQL")

    This class intentionally avoids storing raw employee-level data. Question text
    is hashed by default. SQL text can be stored because the Phase 2 SQL path is
    aggregate-only and validator-controlled, but it is still redacted.
    """

    def __init__(
        self,
        config: Optional[LogConfig] = None,
        log_dir: Optional[Union[str, Path]] = None,
        service_name: str = "hr_bi_assistant",
        environment: Optional[str] = None,
    ) -> None:
        self.config = config or LogConfig(log_dir=log_dir or os.getenv("HR_BI_LOG_DIR", DEFAULT_LOG_DIR))
        if log_dir is not None:
            self.config.log_dir = log_dir

        self.service_name = service_name
        self.environment = environment or os.getenv("APP_ENV", "development")

        self.log_dir = Path(self.config.log_dir)
        self.log_dir.mkdir(parents=True, exist_ok=True)

        self.paths = {
            "app": self.log_dir / self.config.app_log_file,
            "request": self.log_dir / self.config.request_log_file,
            "sql": self.log_dir / self.config.sql_log_file,
            "audit": self.log_dir / self.config.audit_log_file,
            "security": self.log_dir / self.config.security_log_file,
            "error": self.log_dir / self.config.error_log_file,
            "evaluation": self.log_dir / self.config.evaluation_log_file,
            "plain": self.log_dir / self.config.plain_text_log_file,
        }

        self._plain_logger = self._build_plain_logger()

    # ------------------------------------------------------------------
    # Public logging methods
    # ------------------------------------------------------------------

    def log(
        self,
        message: str,
        *,
        level: Union[str, LogLevel] = LogLevel.INFO,
        category: Union[str, LogCategory] = LogCategory.SYSTEM,
        request_id: Optional[str] = None,
        conversation_id: Optional[str] = None,
        user_id: Optional[str] = None,
        user_role: Optional[str] = None,
        session_id: Optional[str] = None,
        module: Optional[str] = None,
        route: Optional[str] = None,
        status: Optional[str] = None,
        intent_id: Optional[str] = None,
        report_id: Optional[str] = None,
        sql_template_id: Optional[str] = None,
        duration_ms: Optional[float] = None,
        row_count: Optional[int] = None,
        risk_level: Optional[str] = None,
        question: Optional[str] = None,
        sql: Optional[str] = None,
        error: Optional[BaseException] = None,
        details: Optional[JsonDict] = None,
    ) -> JsonDict:
        """Write a generic structured log event and return the persisted event."""
        level_str = self._level_value(level)
        category_str = self._category_value(category)

        safe_details = self._sanitize_details(details or {})
        if question:
            safe_details["question_hash"] = self.hash_text(question)
            if self.config.store_question_text:
                safe_details["question_redacted"] = self.redact_text(question)
        if sql:
            safe_details["sql_hash"] = self.hash_text(sql)
            if self.config.store_sql_text:
                safe_details["sql_redacted"] = self.redact_sql(sql)
            safe_details["sql_flags"] = self.inspect_sql(sql)

        error_type = None
        error_message = None
        if error is not None:
            error_type = type(error).__name__
            error_message = self.redact_text(str(error))
            safe_details.setdefault("traceback", self._safe_traceback(error))

        event = LogEvent(
            event_id=self._new_id("evt"),
            timestamp=self.utc_now_iso(),
            level=level_str,
            category=category_str,
            message=self.redact_text(message) if self.config.redact_sensitive else message,
            request_id=request_id,
            conversation_id=conversation_id,
            user_id_hash=self.hash_text(user_id) if user_id else None,
            user_role=user_role,
            session_id=session_id,
            module=module,
            route=route,
            status=status,
            intent_id=intent_id,
            report_id=report_id,
            sql_template_id=sql_template_id,
            duration_ms=round(float(duration_ms), 3) if duration_ms is not None else None,
            row_count=row_count,
            risk_level=risk_level,
            question_hash=self.hash_text(question) if question else None,
            sql_hash=self.hash_text(sql) if sql else None,
            error_type=error_type,
            error_message=error_message,
            details=safe_details,
        )

        event_dict = self._to_jsonable(asdict(event))
        self._write_event(event_dict)
        self._write_plain(event_dict)
        return event_dict

    def log_request_started(
        self,
        *,
        question: Optional[str] = None,
        request_id: Optional[str] = None,
        conversation_id: Optional[str] = None,
        user_id: Optional[str] = None,
        user_role: Optional[str] = None,
        session_id: Optional[str] = None,
        runtime_params: Optional[JsonDict] = None,
        model_name: Optional[str] = None,
        prompt_version: Optional[str] = None,
    ) -> JsonDict:
        """Log the beginning of a user request."""
        return self.log(
            "Request started",
            level=LogLevel.INFO,
            category=LogCategory.REQUEST,
            request_id=request_id,
            conversation_id=conversation_id,
            user_id=user_id,
            user_role=user_role,
            session_id=session_id,
            question=question,
            details={
                "runtime_params": runtime_params or {},
                "model_name": model_name,
                "prompt_version": prompt_version,
            },
        )

    def log_request_finished(
        self,
        *,
        request_id: Optional[str] = None,
        conversation_id: Optional[str] = None,
        user_id: Optional[str] = None,
        user_role: Optional[str] = None,
        route: Optional[str] = None,
        status: Optional[str] = None,
        intent_id: Optional[str] = None,
        report_id: Optional[str] = None,
        duration_ms: Optional[float] = None,
        warnings: Optional[Sequence[str]] = None,
        errors: Optional[Sequence[str]] = None,
        details: Optional[JsonDict] = None,
    ) -> JsonDict:
        """Log the end of a user request."""
        level = LogLevel.ERROR if errors else LogLevel.INFO
        return self.log(
            "Request finished",
            level=level,
            category=LogCategory.REQUEST,
            request_id=request_id,
            conversation_id=conversation_id,
            user_id=user_id,
            user_role=user_role,
            route=route,
            status=status,
            intent_id=intent_id,
            report_id=report_id,
            duration_ms=duration_ms,
            details={
                "warnings": list(warnings or []),
                "errors": list(errors or []),
                **(details or {}),
            },
        )

    def log_step(
        self,
        *,
        module: str,
        status: str,
        request_id: Optional[str] = None,
        duration_ms: Optional[float] = None,
        route: Optional[str] = None,
        intent_id: Optional[str] = None,
        details: Optional[JsonDict] = None,
        level: Union[str, LogLevel] = LogLevel.INFO,
    ) -> JsonDict:
        """Log an orchestration module step."""
        return self.log(
            f"Step finished: {module}",
            level=level,
            category=LogCategory.STEP,
            request_id=request_id,
            module=module,
            route=route,
            status=status,
            intent_id=intent_id,
            duration_ms=duration_ms,
            details=details or {},
        )

    def log_decision(
        self,
        *,
        request_id: Optional[str] = None,
        module: str = "router",
        route: Optional[str] = None,
        status: Optional[str] = None,
        reason: Optional[str] = None,
        intent_id: Optional[str] = None,
        report_id: Optional[str] = None,
        sql_template_id: Optional[str] = None,
        details: Optional[JsonDict] = None,
    ) -> JsonDict:
        """Log a routing or policy decision."""
        return self.log(
            "Decision made",
            level=LogLevel.INFO,
            category=LogCategory.DECISION,
            request_id=request_id,
            module=module,
            route=route,
            status=status,
            intent_id=intent_id,
            report_id=report_id,
            sql_template_id=sql_template_id,
            details={"reason": reason, **(details or {})},
        )

    def log_sql_generated(
        self,
        *,
        sql: str,
        request_id: Optional[str] = None,
        intent_id: Optional[str] = None,
        report_id: Optional[str] = None,
        sql_template_id: Optional[str] = None,
        status: str = "GENERATED",
        details: Optional[JsonDict] = None,
    ) -> JsonDict:
        """Log generated SQL from template engine / SQL generator."""
        return self.log(
            "SQL generated",
            level=LogLevel.INFO,
            category=LogCategory.SQL,
            request_id=request_id,
            module="sql_template_engine",
            route="SQL",
            status=status,
            intent_id=intent_id,
            report_id=report_id,
            sql_template_id=sql_template_id,
            sql=sql,
            details=details or {},
        )

    def log_sql_validation(
        self,
        *,
        status: str,
        is_valid: Optional[bool] = None,
        sql: Optional[str] = None,
        request_id: Optional[str] = None,
        duration_ms: Optional[float] = None,
        violations: Optional[Sequence[Any]] = None,
        warnings: Optional[Sequence[str]] = None,
        details: Optional[JsonDict] = None,
    ) -> JsonDict:
        """Log SQL validation result."""
        level = LogLevel.INFO if is_valid or status == "VALID" else LogLevel.WARNING
        return self.log(
            "SQL validation finished",
            level=level,
            category=LogCategory.SQL,
            request_id=request_id,
            module="sql_validator",
            route="SQL",
            status=status,
            duration_ms=duration_ms,
            sql=sql,
            details={
                "is_valid": is_valid,
                "violations": list(violations or []),
                "warnings": list(warnings or []),
                **(details or {}),
            },
        )

    def log_query_execution(
        self,
        *,
        status: str,
        request_id: Optional[str] = None,
        sql: Optional[str] = None,
        duration_ms: Optional[float] = None,
        row_count: Optional[int] = None,
        columns: Optional[Sequence[str]] = None,
        error: Optional[BaseException] = None,
        details: Optional[JsonDict] = None,
    ) -> JsonDict:
        """Log query execution without persisting result rows."""
        level = LogLevel.ERROR if error or status.upper() in {"FAILED", "EXECUTION_FAILED"} else LogLevel.INFO
        return self.log(
            "Query execution finished",
            level=level,
            category=LogCategory.QUERY,
            request_id=request_id,
            module="query_executor",
            route="SQL",
            status=status,
            duration_ms=duration_ms,
            row_count=row_count,
            sql=sql,
            error=error,
            details={
                "columns": list(columns or []),
                "result_rows_logged": False,
                **(details or {}),
            },
        )

    def log_response(
        self,
        *,
        status: str,
        route: Optional[str] = None,
        request_id: Optional[str] = None,
        intent_id: Optional[str] = None,
        visualization_type: Optional[str] = None,
        row_count: Optional[int] = None,
        duration_ms: Optional[float] = None,
        details: Optional[JsonDict] = None,
    ) -> JsonDict:
        """Log response building result without storing final sensitive payload."""
        return self.log(
            "Response built",
            level=LogLevel.INFO,
            category=LogCategory.RESPONSE,
            request_id=request_id,
            module="response_builder",
            route=route,
            status=status,
            intent_id=intent_id,
            duration_ms=duration_ms,
            row_count=row_count,
            details={
                "visualization_type": visualization_type,
                **(details or {}),
            },
        )

    def log_gap(
        self,
        *,
        gap_code: Optional[str] = None,
        gap_type: Optional[str] = None,
        request_id: Optional[str] = None,
        question: Optional[str] = None,
        reason_fa: Optional[str] = None,
        missing_data: Optional[Sequence[str]] = None,
        details: Optional[JsonDict] = None,
    ) -> JsonDict:
        """Log a Data Gap / Knowledge Gap / Business Rule Gap."""
        return self.log(
            "Gap registered",
            level=LogLevel.INFO,
            category=LogCategory.GAP,
            request_id=request_id,
            module="gap_service",
            route="GAP",
            status="DATA_GAP",
            question=question,
            details={
                "gap_code": gap_code,
                "gap_type": gap_type,
                "reason_fa": reason_fa,
                "missing_data": list(missing_data or []),
                **(details or {}),
            },
        )

    def log_reject(
        self,
        *,
        status: str,
        reason: Optional[str] = None,
        request_id: Optional[str] = None,
        question: Optional[str] = None,
        risk_level: Optional[str] = None,
        details: Optional[JsonDict] = None,
    ) -> JsonDict:
        """Log rejected requests such as ACCESS_DENIED or OUT_OF_SCOPE."""
        category = LogCategory.SECURITY if status == "ACCESS_DENIED" else LogCategory.REJECT
        level = LogLevel.WARNING if status == "ACCESS_DENIED" else LogLevel.INFO
        return self.log(
            "Request rejected",
            level=level,
            category=category,
            request_id=request_id,
            module="question_validator",
            route="REJECT",
            status=status,
            risk_level=risk_level,
            question=question,
            details={"reason": reason, **(details or {})},
        )

    def log_security_event(
        self,
        *,
        event_type: str,
        request_id: Optional[str] = None,
        user_id: Optional[str] = None,
        user_role: Optional[str] = None,
        question: Optional[str] = None,
        risk_level: str = "high",
        reason: Optional[str] = None,
        details: Optional[JsonDict] = None,
    ) -> JsonDict:
        """Log security events such as prompt injection or unsafe data request."""
        return self.log(
            f"Security event: {event_type}",
            level=LogLevel.WARNING,
            category=LogCategory.SECURITY,
            request_id=request_id,
            user_id=user_id,
            user_role=user_role,
            route="REJECT",
            status="SECURITY_EVENT",
            risk_level=risk_level,
            question=question,
            details={"event_type": event_type, "reason": reason, **(details or {})},
        )

    def log_audit(
        self,
        *,
        action: str,
        actor_id: Optional[str] = None,
        actor_role: Optional[str] = None,
        request_id: Optional[str] = None,
        resource: Optional[str] = None,
        outcome: str = "SUCCESS",
        details: Optional[JsonDict] = None,
    ) -> JsonDict:
        """Log audit event for governance, access and admin-level changes."""
        return self.log(
            f"Audit action: {action}",
            level=LogLevel.INFO,
            category=LogCategory.AUDIT,
            request_id=request_id,
            user_id=actor_id,
            user_role=actor_role,
            status=outcome,
            details={"action": action, "resource": resource, **(details or {})},
        )

    def log_error(
        self,
        *,
        error: BaseException,
        request_id: Optional[str] = None,
        module: Optional[str] = None,
        route: Optional[str] = None,
        status: str = "ERROR",
        details: Optional[JsonDict] = None,
    ) -> JsonDict:
        """Log an exception with a redacted traceback."""
        return self.log(
            "Error occurred",
            level=LogLevel.ERROR,
            category=LogCategory.ERROR,
            request_id=request_id,
            module=module,
            route=route,
            status=status,
            error=error,
            details=details or {},
        )

    def log_evaluation_result(
        self,
        *,
        test_id: Optional[str] = None,
        score: Optional[float] = None,
        passed: Optional[bool] = None,
        critical_failure: bool = False,
        request_id: Optional[str] = None,
        model_name: Optional[str] = None,
        prompt_version: Optional[str] = None,
        failed_checks: Optional[Sequence[str]] = None,
        details: Optional[JsonDict] = None,
    ) -> JsonDict:
        """Log one evaluation test result."""
        level = LogLevel.ERROR if critical_failure else (LogLevel.WARNING if passed is False else LogLevel.INFO)
        return self.log(
            "Evaluation test finished",
            level=level,
            category=LogCategory.EVALUATION,
            request_id=request_id,
            status="PASSED" if passed else "FAILED",
            details={
                "test_id": test_id,
                "score": score,
                "passed": passed,
                "critical_failure": critical_failure,
                "model_name": model_name,
                "prompt_version": prompt_version,
                "failed_checks": list(failed_checks or []),
                **(details or {}),
            },
        )

    @contextmanager
    def span(
        self,
        module: str,
        *,
        request_id: Optional[str] = None,
        route: Optional[str] = None,
        intent_id: Optional[str] = None,
        details: Optional[JsonDict] = None,
    ) -> Iterator[None]:
        """Context manager for timing an orchestration module."""
        started = time.perf_counter()
        try:
            yield
            duration_ms = (time.perf_counter() - started) * 1000.0
            self.log_step(
                module=module,
                status="SUCCESS",
                request_id=request_id,
                route=route,
                intent_id=intent_id,
                duration_ms=duration_ms,
                details=details or {},
            )
        except Exception as exc:
            duration_ms = (time.perf_counter() - started) * 1000.0
            self.log_step(
                module=module,
                status="FAILED",
                request_id=request_id,
                route=route,
                intent_id=intent_id,
                duration_ms=duration_ms,
                level=LogLevel.ERROR,
                details={"error_type": type(exc).__name__, **(details or {})},
            )
            self.log_error(error=exc, request_id=request_id, module=module, route=route)
            raise

    # ------------------------------------------------------------------
    # Helpers for RequestContext / dict-based integrations
    # ------------------------------------------------------------------

    def log_context_summary(self, context: Any, *, include_sql: bool = True) -> JsonDict:
        """
        Log a safe summary from llm_orchestrator.RequestContext or equivalent dict.
        Does not persist query result rows or final response data.
        """
        ctx = self._object_to_dict(context)
        request_id = ctx.get("request_id")
        question = ctx.get("question")
        route_result = ctx.get("route_result") or {}
        intent_result = ctx.get("intent_result") or {}
        sql_plan = ctx.get("sql_plan") or {}
        sql_validation = ctx.get("sql_validation") or {}
        query_result = ctx.get("query_result") or {}
        final_response = ctx.get("final_response") or {}

        details = {
            "metadata_health": self._compact(ctx.get("metadata_health")),
            "domain_status": self._extract_status(ctx.get("domain_result")),
            "validation_status": self._extract_status(ctx.get("validation_result")),
            "semantic_status": self._extract_status(ctx.get("semantic_result")),
            "route_result": self._compact(route_result),
            "sql_validation_status": self._extract_status(sql_validation),
            "execution_status": query_result.get("execution_status") or query_result.get("status"),
            "row_count": query_result.get("row_count"),
            "final_status": final_response.get("status"),
            "warnings": ctx.get("warnings", []),
            "errors": ctx.get("errors", []),
        }
        if include_sql and sql_plan.get("sql"):
            details["sql_hash"] = self.hash_text(sql_plan.get("sql"))
            if self.config.store_sql_text:
                details["sql_redacted"] = self.redact_sql(sql_plan.get("sql"))

        return self.log(
            "Request context summary",
            level=LogLevel.INFO if not ctx.get("errors") else LogLevel.ERROR,
            category=LogCategory.REQUEST,
            request_id=request_id,
            user_role=ctx.get("user_role"),
            route=route_result.get("route") or ctx.get("route"),
            status=final_response.get("status") or route_result.get("status"),
            intent_id=intent_result.get("intent") or intent_result.get("intent_id"),
            report_id=intent_result.get("report_id"),
            sql_template_id=sql_plan.get("template_id") or intent_result.get("sql_template_id"),
            question=question,
            row_count=query_result.get("row_count"),
            details=details,
        )

    # ------------------------------------------------------------------
    # Read/search/summarize logs
    # ------------------------------------------------------------------

    def read_events(
        self,
        *,
        category: Optional[Union[str, LogCategory]] = None,
        limit: int = 100,
        reverse: bool = True,
        file_key: Optional[str] = None,
    ) -> List[JsonDict]:
        """Read recent log events from one JSONL file."""
        path = self._path_for_category(category, file_key=file_key)
        rows = self._read_jsonl(path)
        if category and file_key is None:
            cat = self._category_value(category)
            rows = [r for r in rows if r.get("category") == cat]
        if reverse:
            rows = list(reversed(rows))
        return rows[: max(0, int(limit))]

    def search_events(
        self,
        *,
        query: Optional[str] = None,
        category: Optional[Union[str, LogCategory]] = None,
        request_id: Optional[str] = None,
        status: Optional[str] = None,
        route: Optional[str] = None,
        level: Optional[str] = None,
        limit: int = 100,
    ) -> List[JsonDict]:
        """Search events by simple filters."""
        rows = self._read_jsonl(self.paths["app"])
        q = query.lower() if query else None
        cat = self._category_value(category) if category else None
        out: List[JsonDict] = []
        for row in rows:
            if cat and row.get("category") != cat:
                continue
            if request_id and row.get("request_id") != request_id:
                continue
            if status and row.get("status") != status:
                continue
            if route and row.get("route") != route:
                continue
            if level and row.get("level") != level:
                continue
            if q:
                blob = json.dumps(row, ensure_ascii=False).lower()
                if q not in blob:
                    continue
            out.append(row)
        return list(reversed(out))[: max(0, int(limit))]

    def summarize_events(
        self,
        *,
        file_key: str = "app",
        last_n: Optional[int] = None,
    ) -> JsonDict:
        """Return a compact summary of log counts by category/status/route/level."""
        rows = self._read_jsonl(self.paths.get(file_key, self.paths["app"]))
        if last_n is not None:
            rows = rows[-int(last_n):]

        summary: JsonDict = {
            "file_key": file_key,
            "event_count": len(rows),
            "by_level": {},
            "by_category": {},
            "by_status": {},
            "by_route": {},
            "errors": 0,
            "security_events": 0,
            "latest_timestamp": rows[-1].get("timestamp") if rows else None,
        }
        for row in rows:
            self._inc(summary["by_level"], row.get("level") or "UNKNOWN")
            self._inc(summary["by_category"], row.get("category") or "UNKNOWN")
            self._inc(summary["by_status"], row.get("status") or "UNKNOWN")
            self._inc(summary["by_route"], row.get("route") or "UNKNOWN")
            if row.get("category") == "error" or row.get("level") in {"ERROR", "CRITICAL"}:
                summary["errors"] += 1
            if row.get("category") == "security":
                summary["security_events"] += 1
        return summary

    def export_events_csv(
        self,
        output_path: Union[str, Path],
        *,
        file_key: str = "app",
        limit: Optional[int] = None,
    ) -> str:
        """Export selected JSONL events to CSV for quick review."""
        rows = self._read_jsonl(self.paths.get(file_key, self.paths["app"]))
        if limit is not None:
            rows = rows[-int(limit):]
        output = Path(output_path)
        output.parent.mkdir(parents=True, exist_ok=True)
        fields = [
            "timestamp",
            "level",
            "category",
            "message",
            "request_id",
            "module",
            "route",
            "status",
            "intent_id",
            "report_id",
            "sql_template_id",
            "duration_ms",
            "row_count",
            "risk_level",
            "error_type",
            "error_message",
        ]
        with output.open("w", encoding="utf-8-sig", newline="") as f:
            writer = csv.DictWriter(f, fieldnames=fields)
            writer.writeheader()
            for row in rows:
                writer.writerow({k: row.get(k) for k in fields})
        return str(output)

    def health_check(self) -> JsonDict:
        """Check logger file paths and writability."""
        checks: JsonDict = {
            "service": "StructuredLogger",
            "status": "OK",
            "log_dir": str(self.log_dir),
            "files": {},
            "redaction_enabled": self.config.redact_sensitive,
            "store_question_text": self.config.store_question_text,
            "store_sql_text": self.config.store_sql_text,
        }
        for key, path in self.paths.items():
            try:
                path.parent.mkdir(parents=True, exist_ok=True)
                if not path.exists():
                    path.touch()
                checks["files"][key] = {
                    "path": str(path),
                    "exists": path.exists(),
                    "size_bytes": path.stat().st_size if path.exists() else None,
                    "writable": os.access(path, os.W_OK),
                }
            except Exception as exc:
                checks["status"] = "ERROR"
                checks["files"][key] = {"path": str(path), "error": str(exc)}
        return checks

    # ------------------------------------------------------------------
    # Redaction and safety helpers
    # ------------------------------------------------------------------

    @staticmethod
    def utc_now_iso() -> str:
        return datetime.now(timezone.utc).isoformat()

    @staticmethod
    def hash_text(text: Optional[str]) -> Optional[str]:
        if text is None:
            return None
        return hashlib.sha256(str(text).encode("utf-8")).hexdigest()

    def redact_text(self, value: Any) -> str:
        """Redact sensitive substrings from a scalar text value."""
        text = str(value)
        if not self.config.redact_sensitive:
            return text
        for pattern in SENSITIVE_TEXT_PATTERNS:
            text = pattern.sub("[REDACTED]", text)
        for fa in SENSITIVE_FA_KEYWORDS:
            # Keep the label but make explicit that sensitive content was redacted.
            if fa in text:
                text = text.replace(fa, f"{fa} [REDACTED_FIELD]")
        return text

    def redact_sql(self, sql: str) -> str:
        """Redact SQL while preserving enough structure for debugging."""
        redacted = self.redact_text(sql)
        # Remove obvious string-literal sensitive values if the SQL ever includes them.
        redacted = re.sub(
            r"(?i)(national_id|personnel_number|first_name|last_name|phone_number|address)\s*=\s*'[^']*'",
            r"\1 = '[REDACTED]'",
            redacted,
        )
        return redacted

    def sanitize(self, value: Any, *, depth: int = 0) -> Any:
        """Recursively sanitize a Python object for safe logging."""
        if depth > 8:
            return "[MAX_DEPTH]"
        if value is None or isinstance(value, (bool, int, float)):
            return value
        if isinstance(value, Decimal):
            return float(value)
        if isinstance(value, (datetime, date)):
            return value.isoformat()
        if isinstance(value, Enum):
            return value.value
        if is_dataclass(value):
            return self.sanitize(asdict(value), depth=depth + 1)
        if isinstance(value, Mapping):
            safe: JsonDict = {}
            for key, val in value.items():
                k = str(key)
                if self._is_sensitive_key(k):
                    safe[k] = "[REDACTED]"
                elif k.lower() in {"rows", "data", "result_rows"} and isinstance(val, list):
                    # Do not persist actual query result rows by default.
                    safe[k] = f"[NOT_LOGGED:{len(val)} rows]"
                elif k.lower() in {"question"} and not self.config.store_question_text:
                    safe["question_hash"] = self.hash_text(str(val))
                    safe[k] = "[NOT_LOGGED]"
                elif k.lower() in {"sql", "generated_sql", "query"}:
                    safe[f"{k}_hash"] = self.hash_text(str(val))
                    safe[k] = self.redact_sql(str(val)) if self.config.store_sql_text else "[NOT_LOGGED]"
                else:
                    safe[k] = self.sanitize(val, depth=depth + 1)
            return safe
        if isinstance(value, (list, tuple, set)):
            values = list(value)
            if len(values) > 200:
                return [self.sanitize(v, depth=depth + 1) for v in values[:200]] + [f"[TRUNCATED:{len(values)-200} items]"]
            return [self.sanitize(v, depth=depth + 1) for v in values]
        if isinstance(value, bytes):
            return f"[BYTES:{len(value)}]"
        text = self.redact_text(value)
        if len(text) > self.config.max_detail_chars:
            return text[: self.config.max_detail_chars] + "...[TRUNCATED]"
        return text

    def inspect_sql(self, sql: str) -> JsonDict:
        """Return lightweight flags for SQL observability without executing it."""
        sql_norm = re.sub(r"\s+", " ", sql.strip()).lower()
        flags = {
            "contains_raw_table": any(re.search(p, sql_norm, re.I) for p in RAW_TABLE_PATTERNS),
            "contains_join": bool(re.search(r"\bjoin\b", sql_norm, re.I)),
            "contains_select_star": bool(re.search(r"select\s+\*", sql_norm, re.I)),
            "contains_dangerous_command": bool(
                re.search(r"\b(insert|update|delete|drop|alter|create|truncate|grant|revoke)\b", sql_norm, re.I)
            ),
            "uses_main_view": "hr_mvp.vw_hr_employee_analytics" in sql_norm,
            "statement_count_estimate": len([s for s in sql.split(";") if s.strip()]),
            "is_status_sql": bool(re.fullmatch(r"\s*select\s+'[A-Z_]+'\s+as\s+status\s*;?\s*", sql.strip(), re.I)),
        }
        return flags

    # ------------------------------------------------------------------
    # Internal methods
    # ------------------------------------------------------------------

    def _write_event(self, event: JsonDict) -> None:
        self._rotate_if_needed(self.paths["app"])
        self._append_jsonl(self.paths["app"], event)

        category = event.get("category")
        if category in {"request", "step", "decision", "response", "gap", "reject"}:
            self._rotate_if_needed(self.paths["request"])
            self._append_jsonl(self.paths["request"], event)
        if category in {"sql", "query"}:
            self._rotate_if_needed(self.paths["sql"])
            self._append_jsonl(self.paths["sql"], event)
        if category == "audit":
            self._rotate_if_needed(self.paths["audit"])
            self._append_jsonl(self.paths["audit"], event)
        if category == "security":
            self._rotate_if_needed(self.paths["security"])
            self._append_jsonl(self.paths["security"], event)
        if category == "error" or event.get("level") in {"ERROR", "CRITICAL"}:
            self._rotate_if_needed(self.paths["error"])
            self._append_jsonl(self.paths["error"], event)
        if category == "evaluation":
            self._rotate_if_needed(self.paths["evaluation"])
            self._append_jsonl(self.paths["evaluation"], event)

    def _append_jsonl(self, path: Path, event: JsonDict) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("a", encoding="utf-8") as f:
            f.write(json.dumps(event, ensure_ascii=False, default=str) + "\n")

    def _read_jsonl(self, path: Path) -> List[JsonDict]:
        if not path.exists():
            return []
        rows: List[JsonDict] = []
        with path.open("r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    rows.append(json.loads(line))
                except json.JSONDecodeError:
                    rows.append({"raw_line": line, "parse_error": True})
        return rows

    def _rotate_if_needed(self, path: Path) -> None:
        max_bytes = int(self.config.max_log_file_bytes or 0)
        if max_bytes <= 0 or not path.exists() or path.stat().st_size < max_bytes:
            return
        keep = max(1, int(self.config.rotate_keep))
        for i in range(keep - 1, 0, -1):
            src = path.with_suffix(path.suffix + f".{i}")
            dst = path.with_suffix(path.suffix + f".{i + 1}")
            if src.exists():
                if i + 1 > keep:
                    src.unlink(missing_ok=True)
                else:
                    src.rename(dst)
        rotated = path.with_suffix(path.suffix + ".1")
        path.rename(rotated)
        path.touch()

    def _build_plain_logger(self) -> logging.Logger:
        logger = logging.getLogger(f"{self.service_name}.structured")
        logger.setLevel(getattr(logging, self.config.min_level.upper(), logging.INFO))
        logger.propagate = False
        logger.handlers.clear()

        formatter = logging.Formatter(
            fmt="%(asctime)s %(levelname)s %(name)s - %(message)s",
            datefmt="%Y-%m-%dT%H:%M:%S%z",
        )

        if self.config.enable_plain_text_log:
            self.paths["plain"].parent.mkdir(parents=True, exist_ok=True)
            file_handler = logging.FileHandler(self.paths["plain"], encoding="utf-8")
            file_handler.setFormatter(formatter)
            logger.addHandler(file_handler)

        if self.config.enable_console:
            stream_handler = logging.StreamHandler(sys.stdout)
            stream_handler.setFormatter(formatter)
            logger.addHandler(stream_handler)

        return logger

    def _write_plain(self, event: JsonDict) -> None:
        if not self.config.enable_plain_text_log and not self.config.enable_console:
            return
        level = event.get("level", "INFO")
        message = (
            f"category={event.get('category')} request_id={event.get('request_id')} "
            f"module={event.get('module')} route={event.get('route')} "
            f"status={event.get('status')} message={event.get('message')}"
        )
        self._plain_logger.log(getattr(logging, level, logging.INFO), message)

    def _sanitize_details(self, details: JsonDict) -> JsonDict:
        sanitized = self.sanitize(details)
        if not isinstance(sanitized, dict):
            return {"value": sanitized}
        return sanitized

    def _safe_traceback(self, error: BaseException) -> str:
        tb = "".join(traceback.format_exception(type(error), error, error.__traceback__))
        return self.redact_text(tb)

    def _is_sensitive_key(self, key: str) -> bool:
        key_norm = key.lower().strip()
        for pattern in SENSITIVE_KEY_PATTERNS:
            if re.search(pattern, key_norm, re.I):
                return True
        for keyword in SENSITIVE_FA_KEYWORDS:
            if keyword in key:
                return True
        return False

    def _level_value(self, level: Union[str, LogLevel]) -> str:
        if isinstance(level, LogLevel):
            return level.value
        return str(level).upper()

    def _category_value(self, category: Optional[Union[str, LogCategory]]) -> str:
        if category is None:
            return LogCategory.SYSTEM.value
        if isinstance(category, LogCategory):
            return category.value
        return str(category).lower()

    def _path_for_category(
        self,
        category: Optional[Union[str, LogCategory]],
        *,
        file_key: Optional[str] = None,
    ) -> Path:
        if file_key:
            return self.paths.get(file_key, self.paths["app"])
        cat = self._category_value(category) if category else None
        if cat in {"sql", "query"}:
            return self.paths["sql"]
        if cat == "audit":
            return self.paths["audit"]
        if cat == "security":
            return self.paths["security"]
        if cat == "error":
            return self.paths["error"]
        if cat == "evaluation":
            return self.paths["evaluation"]
        if cat in {"request", "step", "decision", "response", "gap", "reject"}:
            return self.paths["request"]
        return self.paths["app"]

    def _to_jsonable(self, value: Any) -> Any:
        return self.sanitize(value)

    def _object_to_dict(self, obj: Any) -> JsonDict:
        if obj is None:
            return {}
        if isinstance(obj, Mapping):
            return dict(obj)
        if is_dataclass(obj):
            return asdict(obj)
        data: JsonDict = {}
        for name in dir(obj):
            if name.startswith("_"):
                continue
            try:
                val = getattr(obj, name)
            except Exception:
                continue
            if callable(val):
                continue
            data[name] = val
        return data

    def _compact(self, value: Any) -> Any:
        value = self.sanitize(value)
        if isinstance(value, dict):
            compact: JsonDict = {}
            for k, v in value.items():
                if k in {"rows", "data", "final_response", "query_result"}:
                    compact[k] = "[COMPACTED]"
                elif isinstance(v, (dict, list)):
                    compact[k] = self._compact(v)
                else:
                    compact[k] = v
            return compact
        if isinstance(value, list):
            if len(value) > 20:
                return [self._compact(v) for v in value[:20]] + [f"[TRUNCATED:{len(value)-20} items]"]
            return [self._compact(v) for v in value]
        return value

    @staticmethod
    def _extract_status(value: Any) -> Optional[str]:
        if isinstance(value, Mapping):
            return value.get("status") or value.get("validation_status") or value.get("execution_status")
        return None

    @staticmethod
    def _new_id(prefix: str) -> str:
        return f"{prefix}_{uuid.uuid4().hex[:16]}"

    @staticmethod
    def _inc(counter: JsonDict, key: str) -> None:
        counter[key] = int(counter.get(key, 0)) + 1


# -----------------------------------------------------------------------------
# Module-level singleton helpers
# -----------------------------------------------------------------------------

_default_logger: Optional[StructuredLogger] = None


def get_structured_logger(
    log_dir: Optional[Union[str, Path]] = None,
    *,
    reset: bool = False,
    **kwargs: Any,
) -> StructuredLogger:
    """Return a module-level StructuredLogger singleton."""
    global _default_logger
    if reset or _default_logger is None:
        _default_logger = StructuredLogger(log_dir=log_dir, **kwargs)
    return _default_logger


def get_logger(*args: Any, **kwargs: Any) -> StructuredLogger:
    """Backward-compatible alias for get_structured_logger."""
    return get_structured_logger(*args, **kwargs)


# Convenient module-level functions for simple imports.
def log_event(message: str, **kwargs: Any) -> JsonDict:
    return get_structured_logger().log(message, **kwargs)


def log_error(error: BaseException, **kwargs: Any) -> JsonDict:
    return get_structured_logger().log_error(error=error, **kwargs)


def log_sql_validation(**kwargs: Any) -> JsonDict:
    return get_structured_logger().log_sql_validation(**kwargs)


# -----------------------------------------------------------------------------
# Smoke test
# -----------------------------------------------------------------------------

if __name__ == "__main__":  # pragma: no cover
    logger = StructuredLogger(log_dir="/tmp/hr_bi_logs", environment="local")
    event = logger.log_request_started(
        request_id="req_demo",
        question="تعداد کل کارکنان چند نفر است؟",
        user_role="demo_user",
    )
    logger.log_step(module="domain_classifier", request_id="req_demo", status="SUCCESS", duration_ms=3.2)
    logger.log_sql_generated(
        request_id="req_demo",
        intent_id="total_employee_count",
        sql_template_id="TPL_TOTAL_EMPLOYEE_COUNT",
        sql="SELECT COUNT(v.employee_id) AS employee_count FROM hr_mvp.vw_hr_employee_analytics v WHERE v.is_active = TRUE;",
    )
    logger.log_sql_validation(request_id="req_demo", status="VALID", is_valid=True, duration_ms=1.4)
    logger.log_query_execution(request_id="req_demo", status="SUCCESS", row_count=1, duration_ms=8.7)
    logger.log_response(request_id="req_demo", status="SUCCESS", route="SQL", visualization_type="kpi_card")
    logger.log_request_finished(request_id="req_demo", status="SUCCESS", route="SQL", duration_ms=32.1)
    print(json.dumps({"event": event, "health": logger.health_check()}, ensure_ascii=False, indent=2))
