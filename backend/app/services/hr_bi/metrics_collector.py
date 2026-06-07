"""
metrics_collector.py

Lightweight metrics collection service for HR BI Assistant - Phase 2
Controlled SQL-based MVP.

Responsibilities:
- Track request latency and module-level timings.
- Track SQL validation / query execution / response building durations.
- Capture basic system resource metrics when available.
- Persist operational metrics to JSONL files for later evaluation and monitoring.
- Provide summaries for evaluation reports and pilot monitoring.

This module is intentionally dependency-light. If optional packages such as psutil
or pynvml are installed, it uses them; otherwise it continues gracefully.
"""

from __future__ import annotations

import csv
import json
import os
import platform
import re
import statistics
import time
import traceback
import uuid
from contextlib import contextmanager
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Tuple, Union


try:  # Optional dependency
    import psutil  # type: ignore
except Exception:  # pragma: no cover - optional dependency fallback
    psutil = None  # type: ignore

try:  # Optional dependency
    import pynvml  # type: ignore
except Exception:  # pragma: no cover - optional dependency fallback
    pynvml = None  # type: ignore


JsonDict = Dict[str, Any]


SENSITIVE_KEY_PATTERNS = [
    r"national[_\s-]?id",
    r"personnel[_\s-]?number",
    r"first[_\s-]?name",
    r"last[_\s-]?name",
    r"full[_\s-]?name",
    r"phone",
    r"mobile",
    r"address",
    r"bank",
    r"iban",
    r"insurance",
    r"password",
    r"token",
    r"secret",
    r"api[_\s-]?key",
]

SENSITIVE_TEXT_PATTERNS = [
    # Iranian national id-like 10 digit values. Kept conservative.
    re.compile(r"(?<!\d)\d{10}(?!\d)"),
    # Very simple phone-like values.
    re.compile(r"(?<!\d)(?:\+?98|0)?9\d{9}(?!\d)"),
]


@dataclass
class MetricEvent:
    """Single metric event persisted as one JSONL row."""

    event_id: str
    event_type: str
    timestamp: str
    request_id: Optional[str] = None
    conversation_id: Optional[str] = None
    user_role: Optional[str] = None
    module: Optional[str] = None
    route: Optional[str] = None
    status: Optional[str] = None
    intent_id: Optional[str] = None
    report_id: Optional[str] = None
    sql_template_id: Optional[str] = None
    model_name: Optional[str] = None
    prompt_version: Optional[str] = None
    duration_ms: Optional[float] = None
    row_count: Optional[int] = None
    score: Optional[float] = None
    error_type: Optional[str] = None
    error_message: Optional[str] = None
    warnings: List[str] = field(default_factory=list)
    details: JsonDict = field(default_factory=dict)


@dataclass
class RequestMetrics:
    """Aggregated metrics for a single user request."""

    request_id: str
    started_at: str
    ended_at: Optional[str] = None
    question_hash: Optional[str] = None
    conversation_id: Optional[str] = None
    user_role: Optional[str] = None
    route: Optional[str] = None
    status: Optional[str] = None
    intent_id: Optional[str] = None
    report_id: Optional[str] = None
    sql_template_id: Optional[str] = None
    model_name: Optional[str] = None
    prompt_version: Optional[str] = None
    total_duration_ms: Optional[float] = None
    module_durations_ms: Dict[str, float] = field(default_factory=dict)
    sql_validation_status: Optional[str] = None
    execution_status: Optional[str] = None
    row_count: Optional[int] = None
    visualization_type: Optional[str] = None
    score: Optional[float] = None
    critical_failure: bool = False
    errors: List[str] = field(default_factory=list)
    warnings: List[str] = field(default_factory=list)
    system_snapshot: JsonDict = field(default_factory=dict)


class MetricsCollector:
    """
    Collects and persists operational metrics for the HR BI Assistant.

    Typical usage:

        metrics = MetricsCollector()
        request_id = metrics.start_request(question="تعداد کل کارکنان چند نفر است؟")

        with metrics.track_module(request_id, "intent_parser"):
            ...

        metrics.record_sql_validation(request_id, status="VALID", duration_ms=4.2)
        metrics.end_request(request_id, status="SUCCESS", route="SQL")

    The class does not require a database. It writes JSONL files by default and can
    later be replaced or wrapped by a DB-backed implementation.
    """

    def __init__(
        self,
        log_dir: Union[str, Path, None] = None,
        metrics_file: Union[str, Path, None] = None,
        request_metrics_file: Union[str, Path, None] = None,
        enable_system_metrics: bool = True,
        enable_gpu_metrics: bool = True,
        redact_sensitive: bool = True,
        max_detail_chars: int = 10_000,
    ) -> None:
        base_dir = Path(log_dir or os.getenv("HR_BI_LOG_DIR", "logs"))
        self.log_dir = base_dir
        self.log_dir.mkdir(parents=True, exist_ok=True)

        self.metrics_file = Path(metrics_file or self.log_dir / "metrics_events.jsonl")
        self.request_metrics_file = Path(
            request_metrics_file or self.log_dir / "request_metrics.jsonl"
        )

        self.enable_system_metrics = enable_system_metrics
        self.enable_gpu_metrics = enable_gpu_metrics
        self.redact_sensitive = redact_sensitive
        self.max_detail_chars = max_detail_chars

        self._active_requests: Dict[str, Tuple[float, RequestMetrics]] = {}
        self._module_start_times: Dict[Tuple[str, str], float] = {}
        self._nvml_initialized = False

    # ---------------------------------------------------------------------
    # Request lifecycle
    # ---------------------------------------------------------------------

    def start_request(
        self,
        question: Optional[str] = None,
        request_id: Optional[str] = None,
        conversation_id: Optional[str] = None,
        user_role: Optional[str] = None,
        model_name: Optional[str] = None,
        prompt_version: Optional[str] = None,
        details: Optional[JsonDict] = None,
    ) -> str:
        """Start tracking a request and return its request_id."""
        rid = request_id or self._new_id("req")
        now = self._now_iso()
        question_hash = self._hash_text(question) if question else None

        request_metrics = RequestMetrics(
            request_id=rid,
            started_at=now,
            question_hash=question_hash,
            conversation_id=conversation_id,
            user_role=user_role,
            model_name=model_name,
            prompt_version=prompt_version,
            system_snapshot=self.snapshot_system_metrics(),
        )
        self._active_requests[rid] = (time.perf_counter(), request_metrics)

        self.record_event(
            event_type="request_started",
            request_id=rid,
            conversation_id=conversation_id,
            user_role=user_role,
            model_name=model_name,
            prompt_version=prompt_version,
            details={"question_hash": question_hash, **(details or {})},
        )
        return rid

    def end_request(
        self,
        request_id: str,
        route: Optional[str] = None,
        status: Optional[str] = None,
        intent_id: Optional[str] = None,
        report_id: Optional[str] = None,
        sql_template_id: Optional[str] = None,
        row_count: Optional[int] = None,
        visualization_type: Optional[str] = None,
        score: Optional[float] = None,
        critical_failure: Optional[bool] = None,
        warnings: Optional[Iterable[str]] = None,
        errors: Optional[Iterable[str]] = None,
        details: Optional[JsonDict] = None,
    ) -> RequestMetrics:
        """Finish a tracked request and persist aggregated metrics."""
        start = self._active_requests.pop(request_id, None)
        if start is None:
            # Gracefully create a minimal record if end_request is called without start.
            start_time = time.perf_counter()
            request_metrics = RequestMetrics(
                request_id=request_id,
                started_at=self._now_iso(),
                system_snapshot=self.snapshot_system_metrics(),
            )
        else:
            start_time, request_metrics = start

        duration_ms = self._elapsed_ms(start_time)
        request_metrics.ended_at = self._now_iso()
        request_metrics.total_duration_ms = duration_ms
        request_metrics.route = route or request_metrics.route
        request_metrics.status = status or request_metrics.status
        request_metrics.intent_id = intent_id or request_metrics.intent_id
        request_metrics.report_id = report_id or request_metrics.report_id
        request_metrics.sql_template_id = sql_template_id or request_metrics.sql_template_id
        request_metrics.row_count = row_count if row_count is not None else request_metrics.row_count
        request_metrics.visualization_type = visualization_type or request_metrics.visualization_type
        request_metrics.score = score if score is not None else request_metrics.score
        if critical_failure is not None:
            request_metrics.critical_failure = critical_failure
        if warnings:
            request_metrics.warnings.extend([str(w) for w in warnings])
        if errors:
            request_metrics.errors.extend([str(e) for e in errors])

        self._append_jsonl(self.request_metrics_file, asdict(request_metrics))
        self.record_event(
            event_type="request_completed",
            request_id=request_id,
            route=request_metrics.route,
            status=request_metrics.status,
            intent_id=request_metrics.intent_id,
            report_id=request_metrics.report_id,
            sql_template_id=request_metrics.sql_template_id,
            duration_ms=duration_ms,
            row_count=request_metrics.row_count,
            score=request_metrics.score,
            warnings=request_metrics.warnings,
            details=details or {},
        )
        return request_metrics

    # ---------------------------------------------------------------------
    # Module timing
    # ---------------------------------------------------------------------

    def start_module(self, request_id: str, module: str, details: Optional[JsonDict] = None) -> None:
        """Start timing a module for a request."""
        self._module_start_times[(request_id, module)] = time.perf_counter()
        self.record_event(
            event_type="module_started",
            request_id=request_id,
            module=module,
            details=details or {},
        )

    def end_module(
        self,
        request_id: str,
        module: str,
        status: Optional[str] = None,
        warnings: Optional[Iterable[str]] = None,
        details: Optional[JsonDict] = None,
    ) -> float:
        """End timing a module and return duration in milliseconds."""
        key = (request_id, module)
        start_time = self._module_start_times.pop(key, None)
        duration_ms = self._elapsed_ms(start_time) if start_time else None

        active = self._active_requests.get(request_id)
        if active and duration_ms is not None:
            active[1].module_durations_ms[module] = duration_ms

        self.record_event(
            event_type="module_completed",
            request_id=request_id,
            module=module,
            status=status,
            duration_ms=duration_ms,
            warnings=list(warnings or []),
            details=details or {},
        )
        return float(duration_ms or 0.0)

    @contextmanager
    def track_module(
        self,
        request_id: str,
        module: str,
        details: Optional[JsonDict] = None,
    ):
        """Context manager for module timing."""
        self.start_module(request_id, module, details=details)
        try:
            yield
            self.end_module(request_id, module, status="SUCCESS")
        except Exception as exc:
            self.record_error(
                request_id=request_id,
                module=module,
                error=exc,
                include_traceback=True,
            )
            self.end_module(request_id, module, status="FAILED")
            raise

    # ---------------------------------------------------------------------
    # Specialized metric events
    # ---------------------------------------------------------------------

    def record_domain_result(self, request_id: str, status: str, duration_ms: Optional[float] = None, **details: Any) -> None:
        self.record_event(
            event_type="domain_classification",
            request_id=request_id,
            module="domain_classifier",
            status=status,
            duration_ms=duration_ms,
            details=details,
        )

    def record_intent_result(
        self,
        request_id: str,
        intent_id: Optional[str],
        route: Optional[str] = None,
        status: Optional[str] = None,
        duration_ms: Optional[float] = None,
        **details: Any,
    ) -> None:
        active = self._active_requests.get(request_id)
        if active:
            active[1].intent_id = intent_id or active[1].intent_id
            active[1].route = route or active[1].route
            active[1].status = status or active[1].status
        self.record_event(
            event_type="intent_parsed",
            request_id=request_id,
            module="intent_parser",
            intent_id=intent_id,
            route=route,
            status=status,
            duration_ms=duration_ms,
            details=details,
        )

    def record_route_decision(
        self,
        request_id: str,
        route: str,
        status: Optional[str] = None,
        intent_id: Optional[str] = None,
        report_id: Optional[str] = None,
        sql_template_id: Optional[str] = None,
        duration_ms: Optional[float] = None,
        **details: Any,
    ) -> None:
        active = self._active_requests.get(request_id)
        if active:
            active[1].route = route
            active[1].status = status or active[1].status
            active[1].intent_id = intent_id or active[1].intent_id
            active[1].report_id = report_id or active[1].report_id
            active[1].sql_template_id = sql_template_id or active[1].sql_template_id
        self.record_event(
            event_type="route_decision",
            request_id=request_id,
            module="router",
            route=route,
            status=status,
            intent_id=intent_id,
            report_id=report_id,
            sql_template_id=sql_template_id,
            duration_ms=duration_ms,
            details=details,
        )

    def record_sql_validation(
        self,
        request_id: str,
        status: str,
        is_valid: Optional[bool] = None,
        duration_ms: Optional[float] = None,
        violations: Optional[Iterable[str]] = None,
        warnings: Optional[Iterable[str]] = None,
        **details: Any,
    ) -> None:
        active = self._active_requests.get(request_id)
        if active:
            active[1].sql_validation_status = status
            if warnings:
                active[1].warnings.extend(str(w) for w in warnings)
            if violations:
                active[1].errors.extend(str(v) for v in violations)
        self.record_event(
            event_type="sql_validation",
            request_id=request_id,
            module="sql_validator",
            status=status,
            duration_ms=duration_ms,
            warnings=list(warnings or []),
            details={
                "is_valid": is_valid,
                "violations": list(violations or []),
                **details,
            },
        )

    def record_query_execution(
        self,
        request_id: str,
        execution_status: str,
        duration_ms: Optional[float] = None,
        row_count: Optional[int] = None,
        warnings: Optional[Iterable[str]] = None,
        **details: Any,
    ) -> None:
        active = self._active_requests.get(request_id)
        if active:
            active[1].execution_status = execution_status
            active[1].row_count = row_count if row_count is not None else active[1].row_count
            if warnings:
                active[1].warnings.extend(str(w) for w in warnings)
        self.record_event(
            event_type="query_execution",
            request_id=request_id,
            module="query_executor",
            status=execution_status,
            duration_ms=duration_ms,
            row_count=row_count,
            warnings=list(warnings or []),
            details=details,
        )

    def record_visualization(
        self,
        request_id: str,
        visualization_type: Optional[str],
        status: str = "SUCCESS",
        duration_ms: Optional[float] = None,
        **details: Any,
    ) -> None:
        active = self._active_requests.get(request_id)
        if active:
            active[1].visualization_type = visualization_type
        self.record_event(
            event_type="visualization_built",
            request_id=request_id,
            module="chart_builder",
            status=status,
            duration_ms=duration_ms,
            details={"visualization_type": visualization_type, **details},
        )

    def record_evaluation_result(
        self,
        request_id: Optional[str],
        test_id: str,
        score: float,
        status: str,
        critical_failure: bool = False,
        failed_checks: Optional[Iterable[str]] = None,
        **details: Any,
    ) -> None:
        if request_id and request_id in self._active_requests:
            self._active_requests[request_id][1].score = score
            self._active_requests[request_id][1].critical_failure = critical_failure
        self.record_event(
            event_type="evaluation_result",
            request_id=request_id,
            module="evaluation_service",
            status=status,
            score=score,
            details={
                "test_id": test_id,
                "critical_failure": critical_failure,
                "failed_checks": list(failed_checks or []),
                **details,
            },
        )

    def record_llm_call(
        self,
        request_id: str,
        module: str,
        model_name: Optional[str] = None,
        prompt_version: Optional[str] = None,
        duration_ms: Optional[float] = None,
        input_tokens: Optional[int] = None,
        output_tokens: Optional[int] = None,
        status: str = "SUCCESS",
        **details: Any,
    ) -> None:
        self.record_event(
            event_type="llm_call",
            request_id=request_id,
            module=module,
            model_name=model_name,
            prompt_version=prompt_version,
            status=status,
            duration_ms=duration_ms,
            details={
                "input_tokens": input_tokens,
                "output_tokens": output_tokens,
                "total_tokens": (input_tokens or 0) + (output_tokens or 0)
                if input_tokens is not None or output_tokens is not None
                else None,
                **details,
            },
        )

    def record_error(
        self,
        request_id: Optional[str],
        module: Optional[str],
        error: Union[BaseException, str],
        error_type: Optional[str] = None,
        include_traceback: bool = False,
        details: Optional[JsonDict] = None,
    ) -> None:
        if isinstance(error, BaseException):
            err_type = error_type or error.__class__.__name__
            err_msg = str(error)
            tb = traceback.format_exc() if include_traceback else None
        else:
            err_type = error_type or "Error"
            err_msg = str(error)
            tb = None

        if request_id and request_id in self._active_requests:
            self._active_requests[request_id][1].errors.append(f"{module or 'unknown'}: {err_msg}")

        self.record_event(
            event_type="error",
            request_id=request_id,
            module=module,
            status="FAILED",
            error_type=err_type,
            error_message=err_msg,
            details={**(details or {}), "traceback": tb},
        )

    # ---------------------------------------------------------------------
    # Generic event and summaries
    # ---------------------------------------------------------------------

    def record_event(
        self,
        event_type: str,
        request_id: Optional[str] = None,
        conversation_id: Optional[str] = None,
        user_role: Optional[str] = None,
        module: Optional[str] = None,
        route: Optional[str] = None,
        status: Optional[str] = None,
        intent_id: Optional[str] = None,
        report_id: Optional[str] = None,
        sql_template_id: Optional[str] = None,
        model_name: Optional[str] = None,
        prompt_version: Optional[str] = None,
        duration_ms: Optional[float] = None,
        row_count: Optional[int] = None,
        score: Optional[float] = None,
        error_type: Optional[str] = None,
        error_message: Optional[str] = None,
        warnings: Optional[Iterable[str]] = None,
        details: Optional[JsonDict] = None,
    ) -> MetricEvent:
        event = MetricEvent(
            event_id=self._new_id("evt"),
            event_type=event_type,
            timestamp=self._now_iso(),
            request_id=request_id,
            conversation_id=conversation_id,
            user_role=user_role,
            module=module,
            route=route,
            status=status,
            intent_id=intent_id,
            report_id=report_id,
            sql_template_id=sql_template_id,
            model_name=model_name,
            prompt_version=prompt_version,
            duration_ms=round(float(duration_ms), 3) if duration_ms is not None else None,
            row_count=row_count,
            score=score,
            error_type=error_type,
            error_message=error_message,
            warnings=[str(w) for w in (warnings or [])],
            details=details or {},
        )
        safe_payload = self._sanitize(asdict(event))
        self._append_jsonl(self.metrics_file, safe_payload)
        return event

    def summarize_requests(
        self,
        limit: Optional[int] = None,
        status: Optional[str] = None,
        route: Optional[str] = None,
    ) -> JsonDict:
        """Build a simple operational summary from request_metrics.jsonl."""
        rows = list(self._read_jsonl(self.request_metrics_file))
        if status:
            rows = [r for r in rows if r.get("status") == status]
        if route:
            rows = [r for r in rows if r.get("route") == route]
        if limit is not None:
            rows = rows[-limit:]

        durations = [self._to_float(r.get("total_duration_ms")) for r in rows]
        durations = [d for d in durations if d is not None]
        scores = [self._to_float(r.get("score")) for r in rows]
        scores = [s for s in scores if s is not None]

        by_route = self._count_by(rows, "route")
        by_status = self._count_by(rows, "status")
        by_intent = self._count_by(rows, "intent_id")

        return {
            "total_requests": len(rows),
            "by_route": by_route,
            "by_status": by_status,
            "top_intents": dict(sorted(by_intent.items(), key=lambda item: item[1], reverse=True)[:20]),
            "latency_ms": self._stats(durations),
            "score": self._stats(scores),
            "critical_failures": sum(1 for r in rows if r.get("critical_failure") is True),
            "error_count": sum(1 for r in rows if r.get("errors")),
            "warning_count": sum(1 for r in rows if r.get("warnings")),
        }

    def summarize_events(self, limit: Optional[int] = None) -> JsonDict:
        """Build summary from metrics_events.jsonl."""
        rows = list(self._read_jsonl(self.metrics_file))
        if limit is not None:
            rows = rows[-limit:]

        durations = [self._to_float(r.get("duration_ms")) for r in rows]
        durations = [d for d in durations if d is not None]

        return {
            "total_events": len(rows),
            "by_event_type": self._count_by(rows, "event_type"),
            "by_module": self._count_by(rows, "module"),
            "by_status": self._count_by(rows, "status"),
            "event_duration_ms": self._stats(durations),
            "error_count": sum(1 for r in rows if r.get("event_type") == "error"),
        }

    def export_requests_csv(self, output_path: Union[str, Path]) -> Path:
        """Export request_metrics.jsonl to CSV."""
        rows = list(self._read_jsonl(self.request_metrics_file))
        output = Path(output_path)
        output.parent.mkdir(parents=True, exist_ok=True)
        fieldnames = [
            "request_id",
            "started_at",
            "ended_at",
            "route",
            "status",
            "intent_id",
            "report_id",
            "sql_template_id",
            "model_name",
            "prompt_version",
            "total_duration_ms",
            "sql_validation_status",
            "execution_status",
            "row_count",
            "visualization_type",
            "score",
            "critical_failure",
        ]
        with output.open("w", encoding="utf-8", newline="") as f:
            writer = csv.DictWriter(f, fieldnames=fieldnames)
            writer.writeheader()
            for row in rows:
                writer.writerow({key: row.get(key) for key in fieldnames})
        return output

    # ---------------------------------------------------------------------
    # System metrics
    # ---------------------------------------------------------------------

    def snapshot_system_metrics(self) -> JsonDict:
        """Capture CPU, memory, disk, process and GPU metrics when available."""
        if not self.enable_system_metrics:
            return {}

        snapshot: JsonDict = {
            "timestamp": self._now_iso(),
            "platform": platform.platform(),
            "python_version": platform.python_version(),
        }

        if psutil is not None:
            try:
                process = psutil.Process(os.getpid())
                mem = psutil.virtual_memory()
                disk = psutil.disk_usage(str(self.log_dir.resolve().anchor or "/"))
                snapshot.update(
                    {
                        "cpu_percent": psutil.cpu_percent(interval=None),
                        "cpu_count_logical": psutil.cpu_count(logical=True),
                        "memory_total_mb": round(mem.total / 1024 / 1024, 2),
                        "memory_available_mb": round(mem.available / 1024 / 1024, 2),
                        "memory_percent": mem.percent,
                        "process_memory_rss_mb": round(process.memory_info().rss / 1024 / 1024, 2),
                        "process_cpu_percent": process.cpu_percent(interval=None),
                        "disk_total_gb": round(disk.total / 1024 / 1024 / 1024, 2),
                        "disk_free_gb": round(disk.free / 1024 / 1024 / 1024, 2),
                        "disk_percent": disk.percent,
                    }
                )
            except Exception as exc:  # pragma: no cover - platform-dependent
                snapshot["system_metrics_error"] = str(exc)

        if self.enable_gpu_metrics:
            snapshot["gpu"] = self._snapshot_gpu_metrics()

        return snapshot

    def _snapshot_gpu_metrics(self) -> List[JsonDict]:
        if pynvml is None:
            return []
        try:
            if not self._nvml_initialized:
                pynvml.nvmlInit()
                self._nvml_initialized = True
            count = pynvml.nvmlDeviceGetCount()
            gpu_rows: List[JsonDict] = []
            for idx in range(count):
                handle = pynvml.nvmlDeviceGetHandleByIndex(idx)
                name = pynvml.nvmlDeviceGetName(handle)
                if isinstance(name, bytes):
                    name = name.decode("utf-8", errors="replace")
                mem = pynvml.nvmlDeviceGetMemoryInfo(handle)
                util = pynvml.nvmlDeviceGetUtilizationRates(handle)
                gpu_rows.append(
                    {
                        "index": idx,
                        "name": name,
                        "memory_total_mb": round(mem.total / 1024 / 1024, 2),
                        "memory_used_mb": round(mem.used / 1024 / 1024, 2),
                        "memory_free_mb": round(mem.free / 1024 / 1024, 2),
                        "gpu_util_percent": util.gpu,
                        "memory_util_percent": util.memory,
                    }
                )
            return gpu_rows
        except Exception:
            return []

    # ---------------------------------------------------------------------
    # Compatibility helpers for orchestrator-style calls
    # ---------------------------------------------------------------------

    def collect(self, *args: Any, **kwargs: Any) -> JsonDict:
        """General collect method for compatibility with service pipelines."""
        event_type = kwargs.pop("event_type", "custom_metric")
        event = self.record_event(event_type=event_type, details={"args": args, **kwargs})
        return asdict(event)

    def run(self, *args: Any, **kwargs: Any) -> JsonDict:
        return self.collect(*args, **kwargs)

    async def arun(self, *args: Any, **kwargs: Any) -> JsonDict:
        return self.collect(*args, **kwargs)

    def __call__(self, *args: Any, **kwargs: Any) -> JsonDict:
        return self.collect(*args, **kwargs)

    def health_check(self) -> JsonDict:
        return {
            "service": "metrics_collector",
            "status": "ok",
            "log_dir": str(self.log_dir),
            "metrics_file": str(self.metrics_file),
            "request_metrics_file": str(self.request_metrics_file),
            "psutil_available": psutil is not None,
            "gpu_metrics_available": pynvml is not None,
            "active_requests": len(self._active_requests),
        }

    # ---------------------------------------------------------------------
    # Internal utilities
    # ---------------------------------------------------------------------

    @staticmethod
    def _now_iso() -> str:
        return datetime.now(timezone.utc).isoformat()

    @staticmethod
    def _new_id(prefix: str) -> str:
        return f"{prefix}_{uuid.uuid4().hex[:16]}"

    @staticmethod
    def _elapsed_ms(start_time: Optional[float]) -> float:
        if start_time is None:
            return 0.0
        return round((time.perf_counter() - start_time) * 1000, 3)

    @staticmethod
    def _hash_text(text: Optional[str]) -> Optional[str]:
        if text is None:
            return None
        # Avoid importing hashlib globally in case the service never hashes text.
        import hashlib

        normalized = " ".join(str(text).strip().split())
        return hashlib.sha256(normalized.encode("utf-8")).hexdigest()[:24]

    def _append_jsonl(self, path: Path, payload: JsonDict) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        safe_payload = self._sanitize(payload)
        with path.open("a", encoding="utf-8") as f:
            f.write(json.dumps(safe_payload, ensure_ascii=False, default=str) + "\n")

    @staticmethod
    def _read_jsonl(path: Path) -> Iterable[JsonDict]:
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
                    continue
        return rows

    def _sanitize(self, value: Any) -> Any:
        if not self.redact_sensitive:
            return self._truncate(value)
        return self._truncate(self._redact(value))

    def _redact(self, value: Any, parent_key: Optional[str] = None) -> Any:
        if isinstance(value, dict):
            out: JsonDict = {}
            for key, item in value.items():
                key_str = str(key)
                if self._is_sensitive_key(key_str):
                    out[key_str] = "[REDACTED]"
                else:
                    out[key_str] = self._redact(item, key_str)
            return out
        if isinstance(value, list):
            return [self._redact(item, parent_key) for item in value]
        if isinstance(value, tuple):
            return [self._redact(item, parent_key) for item in value]
        if isinstance(value, str):
            text = value
            for pattern in SENSITIVE_TEXT_PATTERNS:
                text = pattern.sub("[REDACTED]", text)
            return text
        return value

    @staticmethod
    def _is_sensitive_key(key: str) -> bool:
        key_lower = key.lower()
        return any(re.search(pattern, key_lower) for pattern in SENSITIVE_KEY_PATTERNS)

    def _truncate(self, value: Any) -> Any:
        try:
            text = json.dumps(value, ensure_ascii=False, default=str)
            if len(text) <= self.max_detail_chars:
                return value
            return {
                "truncated": True,
                "preview": text[: self.max_detail_chars],
                "original_length": len(text),
            }
        except Exception:
            return str(value)[: self.max_detail_chars]

    @staticmethod
    def _to_float(value: Any) -> Optional[float]:
        try:
            if value is None:
                return None
            return float(value)
        except Exception:
            return None

    @staticmethod
    def _count_by(rows: Iterable[JsonDict], key: str) -> Dict[str, int]:
        counts: Dict[str, int] = {}
        for row in rows:
            value = row.get(key)
            if value is None or value == "":
                value = "UNKNOWN"
            value = str(value)
            counts[value] = counts.get(value, 0) + 1
        return counts

    @staticmethod
    def _stats(values: List[float]) -> JsonDict:
        if not values:
            return {
                "count": 0,
                "min": None,
                "max": None,
                "avg": None,
                "median": None,
                "p95": None,
            }
        sorted_values = sorted(values)
        p95_index = min(len(sorted_values) - 1, int(round((len(sorted_values) - 1) * 0.95)))
        return {
            "count": len(values),
            "min": round(min(values), 3),
            "max": round(max(values), 3),
            "avg": round(statistics.mean(values), 3),
            "median": round(statistics.median(values), 3),
            "p95": round(sorted_values[p95_index], 3),
        }


# Backward-friendly aliases that can be used by app code.
MetricsService = MetricsCollector


if __name__ == "__main__":
    collector = MetricsCollector(log_dir="/tmp/hr_bi_metrics_test")
    rid = collector.start_request(
        question="تعداد کل کارکنان چند نفر است؟",
        user_role="demo_user",
        model_name="local-llm",
        prompt_version="v3",
    )
    with collector.track_module(rid, "intent_parser"):
        time.sleep(0.01)
    collector.record_route_decision(
        rid,
        route="SQL",
        status="SUPPORTED",
        intent_id="total_employee_count",
        sql_template_id="TPL_TOTAL_EMPLOYEE_COUNT",
    )
    collector.record_sql_validation(rid, status="VALID", is_valid=True, duration_ms=2.1)
    collector.record_query_execution(rid, execution_status="SUCCESS", duration_ms=12.5, row_count=1)
    collector.end_request(rid, route="SQL", status="SUCCESS", intent_id="total_employee_count")
    print(json.dumps(collector.health_check(), ensure_ascii=False, indent=2))
    print(json.dumps(collector.summarize_requests(), ensure_ascii=False, indent=2))
