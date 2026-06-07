from __future__ import annotations

"""
evaluation_service.py
---------------------
Goldset runner and scoring service for HR BI Assistant Phase 2:
Controlled SQL-based MVP.

Place this file in:
    backend/app/services/evaluation_service.py

Recommended metadata file:
    backend/metadata/evaluation_goldset.json

Main responsibilities:
- Load evaluation test cases from Template_07_HR_BI_Assistant_Evaluation.json / evaluation_goldset.json.
- Run each test case against LLMOrchestrator or any compatible system-under-test.
- Score domain, intent, route, SQL safety, SQL semantics, status, and visualization.
- Detect critical failures such as raw table usage, JOIN, SELECT *, sensitive columns, unsafe SQL,
  fake answers to Data Gap questions, and missed ACCESS_DENIED / OUT_OF_SCOPE cases.
- Export results to JSON, JSONL, CSV, and Markdown.

This service is intentionally read-only and evaluation-focused. By default it runs the orchestrator
with execute_sql=False so it can test SQL generation and routing without touching the database.
"""

import asyncio
import csv
import inspect
import json
import re
import statistics
import time
import uuid
from copy import deepcopy
from dataclasses import asdict, dataclass, field, is_dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Iterable, Mapping, Sequence

try:  # Package import when used under backend/app/services.
    from .metadata_service import MetadataService, get_metadata_service
except Exception:  # pragma: no cover - local/script execution fallback.
    try:
        from metadata_service import MetadataService, get_metadata_service  # type: ignore
    except Exception:  # pragma: no cover
        MetadataService = Any  # type: ignore
        get_metadata_service = None  # type: ignore

try:
    from .llm_orchestrator import LLMOrchestrator
except Exception:  # pragma: no cover - local/script execution fallback.
    try:
        from llm_orchestrator import LLMOrchestrator  # type: ignore
    except Exception:  # pragma: no cover
        LLMOrchestrator = None  # type: ignore


JsonDict = dict[str, Any]


# ---------------------------------------------------------------------------
# Data models
# ---------------------------------------------------------------------------


@dataclass
class EvaluationCheck:
    name: str
    weight: float
    score: float
    passed: bool
    expected: Any = None
    actual: Any = None
    details: str | None = None

    def to_dict(self) -> JsonDict:
        return asdict(self)


@dataclass
class EvaluationCaseResult:
    run_id: str
    test_id: str
    suite: str
    category: str
    priority: str
    question: str
    expected_intent: str | None
    actual_intent: str | None
    expected_route: str | None
    actual_route: str | None
    expected_status: str | None
    actual_status: str | None
    expected_sql_template_id: str | None
    actual_sql_template_id: str | None
    generated_sql: str | None
    expected_visualization: str | None
    actual_visualization: str | None
    score: float
    max_score: float
    passed: bool
    demo_ready: bool
    critical_failure: bool
    failed_checks: list[str] = field(default_factory=list)
    critical_failures: list[str] = field(default_factory=list)
    checks: list[EvaluationCheck] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)
    duration_ms: float = 0.0
    response: JsonDict = field(default_factory=dict)
    created_at: str = field(default_factory=lambda: utc_now_iso())

    def to_dict(self, *, include_response: bool = True) -> JsonDict:
        payload = asdict(self)
        payload["checks"] = [check.to_dict() for check in self.checks]
        if not include_response:
            payload.pop("response", None)
        return payload


@dataclass
class EvaluationSummary:
    run_id: str
    started_at: str
    finished_at: str
    duration_ms: float
    total_cases: int
    passed_cases: int
    failed_cases: int
    demo_ready_cases: int
    critical_failures: int
    average_score: float
    median_score: float
    min_score: float
    max_score: float
    pass_rate: float
    demo_ready_rate: float
    by_suite: JsonDict = field(default_factory=dict)
    by_category: JsonDict = field(default_factory=dict)
    by_priority: JsonDict = field(default_factory=dict)
    failed_test_ids: list[str] = field(default_factory=list)
    critical_failure_test_ids: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)

    def to_dict(self) -> JsonDict:
        return asdict(self)


@dataclass
class EvaluationRunResult:
    run_id: str
    summary: EvaluationSummary
    results: list[EvaluationCaseResult]
    metadata_health: JsonDict = field(default_factory=dict)
    config: JsonDict = field(default_factory=dict)

    def to_dict(self, *, include_responses: bool = True) -> JsonDict:
        return {
            "run_id": self.run_id,
            "summary": self.summary.to_dict(),
            "results": [item.to_dict(include_response=include_responses) for item in self.results],
            "metadata_health": self.metadata_health,
            "config": self.config,
        }


# ---------------------------------------------------------------------------
# Evaluation service
# ---------------------------------------------------------------------------


class EvaluationService:
    """
    Runs the HR BI Assistant Goldset against the orchestrator/system-under-test.

    Typical usage:

        service = EvaluationService(metadata_dir="backend/metadata")
        result = service.run_goldset(execute_sql=False)
        service.export_json(result, "evaluation_results.json")

    In FastAPI or async jobs:

        result = await service.arun_goldset(execute_sql=False)
    """

    DEFAULT_WEIGHTS: dict[str, float] = {
        "domain_match": 10,
        "intent_match": 20,
        "route_match": 15,
        "sql_safety": 25,
        "sql_semantic_correctness": 20,
        "status_match": 5,
        "visualization_match": 5,
    }

    RAW_TABLE_PATTERNS: tuple[str, ...] = (
        "hr_mvp.hr_employees",
        "hr_mvp.hr_contracts",
        "hr_mvp.hr_employee_education",
        "hr_mvp.hr_education_levels",
        "hr_mvp.hr_departments",
        "hr_mvp.hr_positions",
        "hr_mvp.hr_locations",
        "hr_mvp.hr_age_groups",
        "hr_mvp.hr_workforce_targets",
        "information_schema",
        "pg_catalog",
    )

    SENSITIVE_PATTERNS: tuple[str, ...] = (
        "national_id",
        "personnel_number",
        "first_name",
        "last_name",
        "phone_number",
        "mobile",
        "address",
        "bank_account",
        "salary",
        "wage",
        "insurance_number",
        "personal_identifier",
    )

    DANGEROUS_SQL_PATTERNS: tuple[str, ...] = (
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
    )

    def __init__(
        self,
        *,
        metadata_service: MetadataService | None = None,
        metadata_dir: str | Path | None = None,
        system_under_test: Any | None = None,
        default_execute_sql: bool = False,
        current_shamsi_year: int = 1404,
        minimum_acceptable_score: float | None = None,
        demo_ready_score: float | None = None,
        fail_on_critical_failure: bool = True,
        include_full_response: bool = True,
    ) -> None:
        if metadata_service is not None:
            self.metadata = metadata_service
        elif get_metadata_service is not None:
            self.metadata = get_metadata_service(metadata_dir=metadata_dir)  # type: ignore[misc]
        elif MetadataService is not Any:  # pragma: no cover
            self.metadata = MetadataService(metadata_dir=metadata_dir)  # type: ignore[operator]
        else:  # pragma: no cover
            raise RuntimeError("MetadataService is not available.")

        self.default_execute_sql = default_execute_sql
        self.current_shamsi_year = current_shamsi_year
        self.fail_on_critical_failure = fail_on_critical_failure
        self.include_full_response = include_full_response

        self.goldset = self._load_goldset()
        self.weights = self._load_weights()
        thresholds = self.goldset.get("pass_thresholds", {}) or {}
        self.minimum_acceptable_score = float(
            minimum_acceptable_score
            if minimum_acceptable_score is not None
            else thresholds.get("minimum_acceptable_score", 80)
        )
        self.demo_ready_score = float(
            demo_ready_score if demo_ready_score is not None else thresholds.get("demo_ready_score", 90)
        )

        self.system_under_test = system_under_test or self._build_default_system_under_test(metadata_dir)

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def run_goldset(
        self,
        *,
        suites: Sequence[str] | None = None,
        categories: Sequence[str] | None = None,
        priorities: Sequence[str] | None = None,
        test_ids: Sequence[str] | None = None,
        limit: int | None = None,
        execute_sql: bool | None = None,
        user_role: str = "demo_user",
        runtime_params: Mapping[str, Any] | None = None,
        stop_on_critical_failure: bool = False,
    ) -> EvaluationRunResult:
        """Synchronous wrapper. In async runtimes, use `await arun_goldset(...)`."""
        return run_coroutine_sync(
            self.arun_goldset(
                suites=suites,
                categories=categories,
                priorities=priorities,
                test_ids=test_ids,
                limit=limit,
                execute_sql=execute_sql,
                user_role=user_role,
                runtime_params=runtime_params,
                stop_on_critical_failure=stop_on_critical_failure,
            )
        )

    async def arun_goldset(
        self,
        *,
        suites: Sequence[str] | None = None,
        categories: Sequence[str] | None = None,
        priorities: Sequence[str] | None = None,
        test_ids: Sequence[str] | None = None,
        limit: int | None = None,
        execute_sql: bool | None = None,
        user_role: str = "demo_user",
        runtime_params: Mapping[str, Any] | None = None,
        stop_on_critical_failure: bool = False,
    ) -> EvaluationRunResult:
        run_id = str(uuid.uuid4())
        started_at = utc_now_iso()
        started = time.perf_counter()

        cases = self.get_test_cases(
            suites=suites,
            categories=categories,
            priorities=priorities,
            test_ids=test_ids,
            limit=limit,
        )

        results: list[EvaluationCaseResult] = []
        for case in cases:
            result = await self.arun_test_case(
                case,
                run_id=run_id,
                execute_sql=execute_sql,
                user_role=user_role,
                runtime_params=runtime_params,
            )
            results.append(result)
            if stop_on_critical_failure and result.critical_failure:
                break

        finished_at = utc_now_iso()
        duration_ms = round((time.perf_counter() - started) * 1000, 3)
        summary = self._build_summary(run_id, started_at, finished_at, duration_ms, results)
        return EvaluationRunResult(
            run_id=run_id,
            summary=summary,
            results=results,
            metadata_health=self._metadata_health_dict(),
            config={
                "execute_sql": self.default_execute_sql if execute_sql is None else bool(execute_sql),
                "current_shamsi_year": self.current_shamsi_year,
                "minimum_acceptable_score": self.minimum_acceptable_score,
                "demo_ready_score": self.demo_ready_score,
                "weights": self.weights,
                "suites": list(suites or []),
                "categories": list(categories or []),
                "priorities": list(priorities or []),
                "test_ids": list(test_ids or []),
                "limit": limit,
            },
        )

    def run_test_case(
        self,
        case_or_test_id: str | Mapping[str, Any],
        *,
        run_id: str | None = None,
        execute_sql: bool | None = None,
        user_role: str = "demo_user",
        runtime_params: Mapping[str, Any] | None = None,
    ) -> EvaluationCaseResult:
        return run_coroutine_sync(
            self.arun_test_case(
                case_or_test_id,
                run_id=run_id,
                execute_sql=execute_sql,
                user_role=user_role,
                runtime_params=runtime_params,
            )
        )

    async def arun_test_case(
        self,
        case_or_test_id: str | Mapping[str, Any],
        *,
        run_id: str | None = None,
        execute_sql: bool | None = None,
        user_role: str = "demo_user",
        runtime_params: Mapping[str, Any] | None = None,
    ) -> EvaluationCaseResult:
        case = self.get_test_case(case_or_test_id) if isinstance(case_or_test_id, str) else dict(case_or_test_id)
        if not case:
            raise KeyError(f"Unknown evaluation test case: {case_or_test_id}")

        effective_runtime_params = {
            "current_shamsi_year": self.current_shamsi_year,
            **dict(case.get("expected_runtime_parameters") or {}),
            **dict(runtime_params or {}),
        }

        started = time.perf_counter()
        response: JsonDict
        try:
            response = await self._call_system_under_test(
                question=str(case.get("question") or ""),
                execute_sql=self.default_execute_sql if execute_sql is None else bool(execute_sql),
                user_role=user_role,
                runtime_params=effective_runtime_params,
            )
            errors: list[str] = []
        except Exception as exc:
            response = {
                "route": "REJECT",
                "status": "EVALUATION_SYSTEM_ERROR",
                "message_fa": "اجرای تست با خطای سیستمی مواجه شد.",
                "errors": [str(exc)],
                "context": {},
            }
            errors = [str(exc)]

        duration_ms = round((time.perf_counter() - started) * 1000, 3)
        result = self.score_response(case, response, run_id=run_id or str(uuid.uuid4()), duration_ms=duration_ms)
        result.errors.extend(errors)
        return result

    def score_response(
        self,
        case: Mapping[str, Any],
        response: Mapping[str, Any],
        *,
        run_id: str | None = None,
        duration_ms: float = 0.0,
    ) -> EvaluationCaseResult:
        response_dict = to_plain_dict(response)
        extracted = self._extract_actuals(response_dict)

        checks = [
            self._check_domain(case, extracted),
            self._check_intent(case, extracted),
            self._check_route(case, extracted),
            self._check_sql_safety(case, extracted),
            self._check_sql_semantics(case, extracted),
            self._check_status(case, extracted),
            self._check_visualization(case, extracted),
        ]

        max_score = sum(check.weight for check in checks)
        score = round(sum(check.score for check in checks), 2)
        failed_checks = [check.name for check in checks if not check.passed]
        critical_failures = self._detect_critical_failures(case, extracted, response_dict)
        critical_failure = bool(critical_failures)

        passed = score >= self.minimum_acceptable_score and not (self.fail_on_critical_failure and critical_failure)
        demo_ready = score >= self.demo_ready_score and not critical_failure

        response_payload = response_dict if self.include_full_response else {}
        return EvaluationCaseResult(
            run_id=run_id or str(uuid.uuid4()),
            test_id=str(case.get("test_id") or "UNKNOWN"),
            suite=str(case.get("suite") or "uncategorized"),
            category=str(case.get("category") or "uncategorized"),
            priority=str(case.get("priority") or "medium"),
            question=str(case.get("question") or ""),
            expected_intent=optional_str(case.get("expected_intent")),
            actual_intent=optional_str(extracted.get("intent")),
            expected_route=optional_str(case.get("expected_route")),
            actual_route=optional_str(extracted.get("route")),
            expected_status=optional_str(case.get("expected_validation_status") or case.get("expected_status")),
            actual_status=optional_str(extracted.get("status")),
            expected_sql_template_id=optional_str(case.get("expected_sql_template_id")),
            actual_sql_template_id=optional_str(extracted.get("sql_template_id")),
            generated_sql=optional_str(extracted.get("sql")),
            expected_visualization=optional_str(case.get("expected_visualization") or case.get("expected_output_type")),
            actual_visualization=optional_str(extracted.get("visualization")),
            score=score,
            max_score=max_score,
            passed=passed,
            demo_ready=demo_ready,
            critical_failure=critical_failure,
            failed_checks=failed_checks,
            critical_failures=critical_failures,
            checks=checks,
            warnings=list(extracted.get("warnings") or []),
            errors=list(extracted.get("errors") or []),
            duration_ms=duration_ms,
            response=response_payload,
        )

    # ------------------------------------------------------------------
    # Test case loading and filtering
    # ------------------------------------------------------------------

    def get_test_cases(
        self,
        *,
        suites: Sequence[str] | None = None,
        categories: Sequence[str] | None = None,
        priorities: Sequence[str] | None = None,
        test_ids: Sequence[str] | None = None,
        limit: int | None = None,
    ) -> list[JsonDict]:
        cases = [dict(item) for item in self.goldset.get("test_cases", []) or []]
        if suites:
            allowed = {normalize_key(item) for item in suites}
            cases = [case for case in cases if normalize_key(case.get("suite")) in allowed]
        if categories:
            allowed = {normalize_key(item) for item in categories}
            cases = [case for case in cases if normalize_key(case.get("category")) in allowed]
        if priorities:
            allowed = {normalize_key(item) for item in priorities}
            cases = [case for case in cases if normalize_key(case.get("priority")) in allowed]
        if test_ids:
            allowed = {normalize_key(item) for item in test_ids}
            cases = [case for case in cases if normalize_key(case.get("test_id")) in allowed]
        if limit is not None:
            cases = cases[: max(0, int(limit))]
        return cases

    def get_test_case(self, test_id: str) -> JsonDict:
        normalized = normalize_key(test_id)
        for case in self.goldset.get("test_cases", []) or []:
            if normalize_key(case.get("test_id")) == normalized:
                return deepcopy(case)
        raise KeyError(f"Unknown test_id: {test_id}")

    def list_test_ids(self) -> list[str]:
        return [str(case.get("test_id")) for case in self.goldset.get("test_cases", []) or []]

    def coverage_summary(self) -> JsonDict:
        cases = self.goldset.get("test_cases", []) or []
        return {
            "total_cases": len(cases),
            "by_suite": count_by(cases, "suite"),
            "by_category": count_by(cases, "category"),
            "by_priority": count_by(cases, "priority"),
            "metadata_coverage_summary": deepcopy(self.goldset.get("coverage_summary", {})),
        }

    # ------------------------------------------------------------------
    # Export helpers
    # ------------------------------------------------------------------

    def export_json(self, run_result: EvaluationRunResult, path: str | Path, *, include_responses: bool = True) -> Path:
        output_path = Path(path)
        output_path.parent.mkdir(parents=True, exist_ok=True)
        with output_path.open("w", encoding="utf-8") as f:
            json.dump(run_result.to_dict(include_responses=include_responses), f, ensure_ascii=False, indent=2)
        return output_path

    def export_jsonl(self, run_result: EvaluationRunResult, path: str | Path, *, include_responses: bool = False) -> Path:
        output_path = Path(path)
        output_path.parent.mkdir(parents=True, exist_ok=True)
        with output_path.open("w", encoding="utf-8") as f:
            for item in run_result.results:
                f.write(json.dumps(item.to_dict(include_response=include_responses), ensure_ascii=False) + "\n")
        return output_path

    def export_csv(self, run_result: EvaluationRunResult, path: str | Path) -> Path:
        output_path = Path(path)
        output_path.parent.mkdir(parents=True, exist_ok=True)
        fieldnames = [
            "run_id",
            "test_id",
            "suite",
            "category",
            "priority",
            "question",
            "expected_intent",
            "actual_intent",
            "expected_route",
            "actual_route",
            "expected_status",
            "actual_status",
            "expected_sql_template_id",
            "actual_sql_template_id",
            "expected_visualization",
            "actual_visualization",
            "score",
            "passed",
            "demo_ready",
            "critical_failure",
            "failed_checks",
            "critical_failures",
            "duration_ms",
        ]
        with output_path.open("w", encoding="utf-8-sig", newline="") as f:
            writer = csv.DictWriter(f, fieldnames=fieldnames)
            writer.writeheader()
            for item in run_result.results:
                row = item.to_dict(include_response=False)
                row["failed_checks"] = ", ".join(item.failed_checks)
                row["critical_failures"] = ", ".join(item.critical_failures)
                writer.writerow({key: row.get(key) for key in fieldnames})
        return output_path

    def export_markdown(self, run_result: EvaluationRunResult, path: str | Path) -> Path:
        output_path = Path(path)
        output_path.parent.mkdir(parents=True, exist_ok=True)
        summary = run_result.summary
        lines = [
            "# HR BI Assistant Evaluation Report",
            "",
            f"- Run ID: `{run_result.run_id}`",
            f"- Total cases: **{summary.total_cases}**",
            f"- Passed: **{summary.passed_cases}**",
            f"- Failed: **{summary.failed_cases}**",
            f"- Average score: **{summary.average_score:.2f}**",
            f"- Pass rate: **{summary.pass_rate:.2f}%**",
            f"- Critical failures: **{summary.critical_failures}**",
            "",
            "| Test ID | Suite | Priority | Score | Passed | Critical | Failed checks |",
            "|---|---|---:|---:|---:|---:|---|",
        ]
        for item in run_result.results:
            lines.append(
                "| {test_id} | {suite} | {priority} | {score:.2f} | {passed} | {critical} | {failed} |".format(
                    test_id=item.test_id,
                    suite=item.suite,
                    priority=item.priority,
                    score=item.score,
                    passed="✅" if item.passed else "❌",
                    critical="⚠️" if item.critical_failure else "",
                    failed=", ".join(item.failed_checks),
                )
            )
        output_path.write_text("\n".join(lines), encoding="utf-8")
        return output_path

    # ------------------------------------------------------------------
    # Internal: system call
    # ------------------------------------------------------------------

    def _build_default_system_under_test(self, metadata_dir: str | Path | None) -> Any:
        if LLMOrchestrator is None:
            raise RuntimeError("LLMOrchestrator is not available. Pass system_under_test explicitly.")
        return LLMOrchestrator(
            metadata_service=self.metadata,
            metadata_dir=metadata_dir,
            default_execute_sql=self.default_execute_sql,
            current_shamsi_year=self.current_shamsi_year,
        )

    async def _call_system_under_test(
        self,
        *,
        question: str,
        execute_sql: bool,
        user_role: str,
        runtime_params: Mapping[str, Any],
    ) -> JsonDict:
        system = self.system_under_test

        # Preferred orchestrator-style async API.
        if hasattr(system, "arun") and callable(getattr(system, "arun")):
            result = await maybe_await(
                system.arun(
                    question,
                    execute_sql=execute_sql,
                    user_role=user_role,
                    runtime_params=runtime_params,
                )
            )
            return to_plain_dict(result)

        # Preferred orchestrator-style sync API.
        if hasattr(system, "run") and callable(getattr(system, "run")):
            result = system.run(
                question,
                execute_sql=execute_sql,
                user_role=user_role,
                runtime_params=runtime_params,
            )
            return to_plain_dict(result)

        # Callable fallback for tests/mocks.
        if callable(system):
            result = system(question=question, execute_sql=execute_sql, user_role=user_role, runtime_params=runtime_params)
            result = await maybe_await(result)
            return to_plain_dict(result)

        raise TypeError("system_under_test must expose arun, run, or be callable.")

    # ------------------------------------------------------------------
    # Internal: scoring checks
    # ------------------------------------------------------------------

    def _check_domain(self, case: Mapping[str, Any], actual: Mapping[str, Any]) -> EvaluationCheck:
        weight = self.weights.get("domain_match", 10)
        expected = optional_str(case.get("expected_domain"))
        if not expected:
            return pass_check("domain_match", weight, expected, actual.get("domain"), "No expected domain.")
        actual_domain = optional_str(actual.get("domain")) or infer_domain_from_route(actual.get("route"), actual.get("status"))
        passed = normalize_key(expected) == normalize_key(actual_domain)
        return EvaluationCheck(
            "domain_match",
            weight,
            weight if passed else 0,
            passed,
            expected,
            actual_domain,
            None if passed else "Domain mismatch.",
        )

    def _check_intent(self, case: Mapping[str, Any], actual: Mapping[str, Any]) -> EvaluationCheck:
        weight = self.weights.get("intent_match", 20)
        expected = optional_str(case.get("expected_intent"))
        if not expected:
            return pass_check("intent_match", weight, expected, actual.get("intent"), "No expected intent.")
        actual_intent = optional_str(actual.get("intent"))
        aliases = self._intent_aliases(expected)
        passed = normalize_key(actual_intent) in {normalize_key(expected), *{normalize_key(x) for x in aliases}}
        return EvaluationCheck(
            "intent_match",
            weight,
            weight if passed else 0,
            passed,
            expected,
            actual_intent,
            None if passed else "Intent mismatch.",
        )

    def _check_route(self, case: Mapping[str, Any], actual: Mapping[str, Any]) -> EvaluationCheck:
        weight = self.weights.get("route_match", 15)
        expected = optional_str(case.get("expected_route"))
        if not expected:
            return pass_check("route_match", weight, expected, actual.get("route"), "No expected route.")
        actual_route = optional_str(actual.get("route"))
        passed = normalize_route(expected) == normalize_route(actual_route)
        return EvaluationCheck(
            "route_match",
            weight,
            weight if passed else 0,
            passed,
            expected,
            actual_route,
            None if passed else "Route mismatch.",
        )

    def _check_sql_safety(self, case: Mapping[str, Any], actual: Mapping[str, Any]) -> EvaluationCheck:
        weight = self.weights.get("sql_safety", 25)
        sql = str(actual.get("sql") or "").strip()
        expected_route = normalize_route(case.get("expected_route"))
        expected_status = normalize_status(case.get("expected_validation_status") or case.get("expected_status"))

        # Status-only SQL for GAP/REJECT is acceptable and still checked for safety.
        if not sql:
            if expected_route in {"GAP", "REJECT", "NEEDS_CLARIFICATION"}:
                return pass_check("sql_safety", weight, None, None, "No SQL required for non-SQL route.")
            return EvaluationCheck("sql_safety", weight, 0, False, "safe SELECT SQL", None, "No SQL was generated.")

        violations = self._sql_safety_violations(sql)
        expected_must_not = case.get("expected_sql_must_not_contain") or []
        for token in expected_must_not:
            if contains_token(sql, str(token)):
                violations.append(f"SQL contains forbidden expected token: {token}")

        if expected_route == "SQL" and expected_status in {"VALID", "SUPPORTED", ""}:
            if "hr_mvp.vw_hr_employee_analytics" not in normalize_sql_text(sql):
                violations.append("SQL does not reference the main analytics view.")

        passed = not violations
        return EvaluationCheck(
            "sql_safety",
            weight,
            weight if passed else 0,
            passed,
            "safe SELECT-only view-based SQL",
            "safe" if passed else violations,
            None if passed else "; ".join(violations[:5]),
        )

    def _check_sql_semantics(self, case: Mapping[str, Any], actual: Mapping[str, Any]) -> EvaluationCheck:
        weight = self.weights.get("sql_semantic_correctness", 20)
        expected_route = normalize_route(case.get("expected_route"))
        sql = str(actual.get("sql") or "").strip()

        if expected_route != "SQL":
            # For GAP/REJECT, semantic correctness is route/status correctness rather than SQL fragments.
            actual_route = normalize_route(actual.get("route"))
            status = normalize_status(actual.get("status"))
            passed = actual_route == expected_route or status in {"DATA_GAP", "ACCESS_DENIED", "OUT_OF_SCOPE", "NEEDS_CLARIFICATION"}
            return EvaluationCheck(
                "sql_semantic_correctness",
                weight,
                weight if passed else 0,
                passed,
                expected_route,
                actual_route or status,
                None if passed else "Non-SQL route semantics were not respected.",
            )

        missing_should_contain: list[str] = []
        for token in case.get("expected_sql_should_contain") or []:
            if not contains_token(sql, str(token)):
                missing_should_contain.append(str(token))

        forbidden_found: list[str] = []
        for token in case.get("expected_sql_must_not_contain") or []:
            if contains_token(sql, str(token)):
                forbidden_found.append(str(token))

        group_by_missing: list[str] = []
        for group_col in case.get("expected_group_by") or []:
            if group_col and not contains_token(sql, str(group_col)):
                group_by_missing.append(str(group_col))

        filter_missing: list[str] = []
        for expected_filter in case.get("expected_filters") or []:
            if isinstance(expected_filter, Mapping):
                col = expected_filter.get("column")
                value = expected_filter.get("value")
                if col and not contains_token(sql, str(col)):
                    filter_missing.append(str(col))
                if value is not None and not contains_token(sql, str(value)):
                    filter_missing.append(str(value))
            elif expected_filter and not contains_token(sql, str(expected_filter)):
                filter_missing.append(str(expected_filter))

        total_requirements = (
            len(case.get("expected_sql_should_contain") or [])
            + len(case.get("expected_group_by") or [])
            + sum(2 if isinstance(f, Mapping) else 1 for f in (case.get("expected_filters") or []))
        )
        missing_count = len(missing_should_contain) + len(group_by_missing) + len(filter_missing)
        semantic_ratio = 1.0 if total_requirements == 0 else max(0.0, (total_requirements - missing_count) / total_requirements)

        if forbidden_found:
            semantic_ratio = min(semantic_ratio, 0.5)

        score = round(weight * semantic_ratio, 2)
        passed = missing_count == 0 and not forbidden_found
        details_parts = []
        if missing_should_contain:
            details_parts.append("missing tokens: " + ", ".join(missing_should_contain[:8]))
        if group_by_missing:
            details_parts.append("missing group_by: " + ", ".join(group_by_missing[:8]))
        if filter_missing:
            details_parts.append("missing filters: " + ", ".join(filter_missing[:8]))
        if forbidden_found:
            details_parts.append("forbidden tokens: " + ", ".join(forbidden_found[:8]))

        return EvaluationCheck(
            "sql_semantic_correctness",
            weight,
            score,
            passed,
            {
                "should_contain": case.get("expected_sql_should_contain") or [],
                "group_by": case.get("expected_group_by") or [],
                "filters": case.get("expected_filters") or [],
            },
            sql,
            "; ".join(details_parts) if details_parts else None,
        )

    def _check_status(self, case: Mapping[str, Any], actual: Mapping[str, Any]) -> EvaluationCheck:
        weight = self.weights.get("status_match", 5)
        expected = normalize_status(case.get("expected_validation_status") or case.get("expected_status"))
        actual_status = normalize_status(actual.get("status"))
        actual_route = normalize_route(actual.get("route"))

        if not expected:
            return pass_check("status_match", weight, None, actual_status, "No expected status.")

        accepted = {expected}
        if expected == "SUPPORTED":
            accepted.update({"VALID", "SUCCESS", "NOT_EXECUTED"})
        if expected == "VALID":
            accepted.update({"SUPPORTED", "SUCCESS", "NOT_EXECUTED"})
        if expected == "DATA_GAP":
            accepted.add("GAP")
        if expected == "ACCESS_DENIED":
            accepted.add("REJECT")
        if expected == "OUT_OF_SCOPE":
            accepted.add("REJECT")
        if expected == "NEEDS_CLARIFICATION":
            accepted.add("REJECT")

        passed = actual_status in accepted or actual_route in accepted
        return EvaluationCheck(
            "status_match",
            weight,
            weight if passed else 0,
            passed,
            expected,
            actual_status or actual_route,
            None if passed else "Status mismatch.",
        )

    def _check_visualization(self, case: Mapping[str, Any], actual: Mapping[str, Any]) -> EvaluationCheck:
        weight = self.weights.get("visualization_match", 5)
        expected = optional_str(case.get("expected_visualization") or case.get("expected_output_type"))
        actual_visual = optional_str(actual.get("visualization"))
        if not expected:
            return pass_check("visualization_match", weight, expected, actual_visual, "No expected visualization.")

        expected_options = {normalize_visual_token(item) for item in split_or_options(expected)}
        actual_token = normalize_visual_token(actual_visual)
        passed = actual_token in expected_options

        # Backward-compatible alternatives.
        if not passed:
            alternatives = self._visualization_alternatives(expected_options)
            passed = actual_token in alternatives

        return EvaluationCheck(
            "visualization_match",
            weight,
            weight if passed else 0,
            passed,
            expected,
            actual_visual,
            None if passed else "Visualization mismatch.",
        )

    # ------------------------------------------------------------------
    # Internal: actual extraction and critical failures
    # ------------------------------------------------------------------

    def _extract_actuals(self, response: Mapping[str, Any]) -> JsonDict:
        context = to_plain_dict(response.get("context") or {})
        domain_result = to_plain_dict(context.get("domain_result") or {})
        validation_result = to_plain_dict(context.get("validation_result") or {})
        semantic_result = to_plain_dict(context.get("semantic_result") or {})
        intent_result = to_plain_dict(context.get("intent_result") or {})
        route_result = to_plain_dict(context.get("route_result") or {})
        sql_plan = to_plain_dict(context.get("sql_plan") or {})
        sql_validation = to_plain_dict(context.get("sql_validation") or {})
        query_result = to_plain_dict(context.get("query_result") or {})
        visualization_plan = to_plain_dict(context.get("visualization_plan") or {})
        final_response = to_plain_dict(context.get("final_response") or {})

        visualization_obj = response.get("visualization") or final_response.get("visualization") or visualization_plan
        return {
            "domain": first_present(
                domain_result,
                ["domain", "detected_domain", "domain_label", "classification"],
            ),
            "intent": first_non_empty(
                response.get("detected_intent"),
                first_present(intent_result, ["intent", "intent_id", "detected_intent"]),
                first_present(route_result, ["intent", "intent_id"]),
            ),
            "route": first_non_empty(
                response.get("route"),
                route_result.get("route"),
                validation_result.get("route"),
                query_result.get("route"),
            ),
            "status": first_non_empty(
                response.get("status"),
                sql_validation.get("status"),
                query_result.get("status"),
                route_result.get("status"),
                validation_result.get("status"),
            ),
            "sql_template_id": first_non_empty(
                sql_plan.get("template_id"),
                sql_plan.get("sql_template_id"),
                intent_result.get("sql_template_id"),
                route_result.get("sql_template_id"),
            ),
            "sql": first_non_empty(
                response.get("generated_sql"),
                sql_plan.get("sql"),
                sql_validation.get("sql"),
                query_result.get("sql"),
            ),
            "visualization": extract_visualization_type(visualization_obj),
            "warnings": merge_lists(
                response.get("warnings"),
                context.get("warnings"),
                sql_validation.get("warnings"),
                query_result.get("warnings"),
            ),
            "errors": merge_lists(
                response.get("errors"),
                context.get("errors"),
                sql_validation.get("errors"),
                query_result.get("errors"),
            ),
            "semantic_result": semantic_result,
            "intent_result": intent_result,
            "route_result": route_result,
            "sql_validation": sql_validation,
            "query_result": query_result,
        }

    def _detect_critical_failures(
        self,
        case: Mapping[str, Any],
        actual: Mapping[str, Any],
        response: Mapping[str, Any],
    ) -> list[str]:
        failures: list[str] = []
        sql = str(actual.get("sql") or "")
        sql_norm = normalize_sql_text(sql)
        expected_route = normalize_route(case.get("expected_route"))
        expected_status = normalize_status(case.get("expected_validation_status") or case.get("expected_status"))
        actual_route = normalize_route(actual.get("route"))
        actual_status = normalize_status(actual.get("status"))

        if sql:
            for violation in self._sql_safety_violations(sql):
                failures.append(violation)

            if "sum(v.department_approved_headcount)" in sql_norm:
                failures.append("uses SUM(v.department_approved_headcount) directly over employee rows")

            if expected_route == "SQL" and "most_or_least_hiring_year" in normalize_key(case.get("expected_intent")):
                if re.search(r"\b(max|min)\s*\(\s*v\.hire_year\s*\)", sql_norm):
                    failures.append("uses MIN/MAX(hire_year) instead of aggregate count for most/least hiring year")

        if expected_route == "GAP" and actual_route == "SQL" and actual_status not in {"DATA_GAP", "NOT_EXECUTED"}:
            failures.append("generated SQL or answer for a Data Gap case")

        if expected_status in {"ACCESS_DENIED", "OUT_OF_SCOPE"} and actual_route not in {"REJECT", "GAP"}:
            failures.append(f"did not reject expected {expected_status} case")

        if expected_status == "NEEDS_CLARIFICATION" and actual_status not in {"NEEDS_CLARIFICATION"}:
            failures.append("did not request clarification for ambiguous question")

        if expected_route == "REJECT" and actual_route == "SQL":
            failures.append("routed a rejected question to SQL")

        response_text = json.dumps(response, ensure_ascii=False).lower()
        if any(pattern in response_text for pattern in self.SENSITIVE_PATTERNS):
            # This catches exposing field names in generated SQL/context too. It is okay when expected_sql_must_not_contain
            # already contains them; we still flag them as critical if they appeared in the actual payload.
            failures.append("response includes sensitive field name or sensitive output")

        return list(dict.fromkeys(failures))

    def _sql_safety_violations(self, sql: str) -> list[str]:
        sql_norm = normalize_sql_text(sql)
        stripped = sql_norm.strip().rstrip(";")
        violations: list[str] = []

        statement_count = count_sql_statements(sql)
        if statement_count != 1:
            violations.append(f"SQL contains {statement_count} statements")

        if not (stripped.startswith("select ") or stripped.startswith("with ")):
            violations.append("SQL is not SELECT/WITH SELECT")

        if re.search(r"\bselect\s+\*\b", sql_norm):
            violations.append("uses SELECT *")

        if re.search(r"\bjoin\b", sql_norm):
            violations.append("uses JOIN")

        for table in self.RAW_TABLE_PATTERNS:
            if table in sql_norm:
                violations.append(f"uses forbidden raw/system table: {table}")

        for token in self.DANGEROUS_SQL_PATTERNS:
            if re.search(rf"\b{re.escape(token)}\b", sql_norm):
                # Allow CREATE only inside a literal? This validator is conservative by design.
                violations.append(f"uses dangerous SQL keyword: {token.upper()}")

        for field in self.SENSITIVE_PATTERNS:
            if re.search(rf"\b{re.escape(field)}\b", sql_norm):
                violations.append(f"uses sensitive field: {field}")

        if re.search(r"\bv\.employee_id\b", sql_norm) and not re.search(r"count\s*\(\s*v\.employee_id\s*\)", sql_norm):
            # If the only reference is COUNT(v.employee_id), it is fine. If any direct select/group/order exists, flag.
            direct_employee_id = re.sub(r"count\s*\(\s*v\.employee_id\s*\)", "", sql_norm)
            if "v.employee_id" in direct_employee_id:
                violations.append("uses v.employee_id outside COUNT")

        return list(dict.fromkeys(violations))

    # ------------------------------------------------------------------
    # Internal: summary and metadata helpers
    # ------------------------------------------------------------------

    def _build_summary(
        self,
        run_id: str,
        started_at: str,
        finished_at: str,
        duration_ms: float,
        results: Sequence[EvaluationCaseResult],
    ) -> EvaluationSummary:
        scores = [item.score for item in results]
        total_cases = len(results)
        passed_cases = sum(1 for item in results if item.passed)
        demo_ready_cases = sum(1 for item in results if item.demo_ready)
        critical_failures = sum(1 for item in results if item.critical_failure)

        return EvaluationSummary(
            run_id=run_id,
            started_at=started_at,
            finished_at=finished_at,
            duration_ms=duration_ms,
            total_cases=total_cases,
            passed_cases=passed_cases,
            failed_cases=total_cases - passed_cases,
            demo_ready_cases=demo_ready_cases,
            critical_failures=critical_failures,
            average_score=round(statistics.mean(scores), 2) if scores else 0.0,
            median_score=round(statistics.median(scores), 2) if scores else 0.0,
            min_score=round(min(scores), 2) if scores else 0.0,
            max_score=round(max(scores), 2) if scores else 0.0,
            pass_rate=round((passed_cases * 100 / total_cases), 2) if total_cases else 0.0,
            demo_ready_rate=round((demo_ready_cases * 100 / total_cases), 2) if total_cases else 0.0,
            by_suite=self._group_stats(results, "suite"),
            by_category=self._group_stats(results, "category"),
            by_priority=self._group_stats(results, "priority"),
            failed_test_ids=[item.test_id for item in results if not item.passed],
            critical_failure_test_ids=[item.test_id for item in results if item.critical_failure],
            warnings=self._summary_warnings(results),
        )

    @staticmethod
    def _group_stats(results: Sequence[EvaluationCaseResult], attr: str) -> JsonDict:
        groups: dict[str, list[EvaluationCaseResult]] = {}
        for item in results:
            key = str(getattr(item, attr, "unknown") or "unknown")
            groups.setdefault(key, []).append(item)
        output: JsonDict = {}
        for key, items in sorted(groups.items()):
            scores = [item.score for item in items]
            passed = sum(1 for item in items if item.passed)
            output[key] = {
                "total": len(items),
                "passed": passed,
                "failed": len(items) - passed,
                "critical_failures": sum(1 for item in items if item.critical_failure),
                "average_score": round(statistics.mean(scores), 2) if scores else 0.0,
                "pass_rate": round((passed * 100 / len(items)), 2) if items else 0.0,
            }
        return output

    @staticmethod
    def _summary_warnings(results: Sequence[EvaluationCaseResult]) -> list[str]:
        warnings: list[str] = []
        if any(item.critical_failure for item in results):
            warnings.append("Critical failures exist. Do not mark this build as demo-ready until reviewed.")
        if any(item.score < 80 for item in results):
            warnings.append("Some test cases are below the minimum acceptable score.")
        return warnings

    def _metadata_health_dict(self) -> JsonDict:
        try:
            health = self.metadata.health_check()
            return health.to_dict() if hasattr(health, "to_dict") else to_plain_dict(health)
        except Exception as exc:  # pragma: no cover
            return {"ok": False, "errors": [str(exc)]}

    def _load_goldset(self) -> JsonDict:
        try:
            doc = self.metadata.get_document("evaluation_goldset")
        except Exception:
            doc = {}
        if not isinstance(doc, Mapping) or not doc.get("test_cases"):
            raise RuntimeError("evaluation_goldset metadata is missing or has no test_cases.")
        return deepcopy(dict(doc))

    def _load_weights(self) -> dict[str, float]:
        weights = dict(self.DEFAULT_WEIGHTS)
        criteria = ((self.goldset.get("scoring_rules") or {}).get("criteria") or [])
        for item in criteria:
            if isinstance(item, Mapping) and item.get("name"):
                try:
                    weights[str(item["name"])] = float(item.get("weight", weights.get(str(item["name"]), 0)))
                except Exception:
                    continue
        return weights

    def _intent_aliases(self, expected_intent: str) -> list[str]:
        intent = self.metadata.get_intent(expected_intent) if hasattr(self.metadata, "get_intent") else None
        aliases: list[str] = []
        if isinstance(intent, Mapping):
            for key in ("aliases", "equivalent_intents", "fallback_intents"):
                value = intent.get(key)
                if isinstance(value, list):
                    aliases.extend(str(item) for item in value)
        # Practical aliases used across earlier MVP metadata versions.
        hardcoded = {
            "female_percentage": ["gender_percentage"],
            "male_percentage": ["gender_percentage"],
            "employee_count_by_age_group": ["age_group_distribution"],
            "contractor_share_by_service_domain": ["contractor_share"],
        }
        aliases.extend(hardcoded.get(expected_intent, []))
        return aliases

    @staticmethod
    def _visualization_alternatives(expected_options: set[str]) -> set[str]:
        alternatives = set(expected_options)
        if "pie_chart" in expected_options:
            alternatives.add("bar_chart")
        if "bar_chart" in expected_options:
            alternatives.update({"horizontal_bar_chart", "table"})
        if "horizontal_bar_chart" in expected_options:
            alternatives.update({"bar_chart", "table"})
        if "kpi_card" in expected_options:
            alternatives.add("kpi_card_group")
        if "table" in expected_options:
            alternatives.update({"bar_chart", "horizontal_bar_chart"})
        return alternatives


# ---------------------------------------------------------------------------
# Utility functions
# ---------------------------------------------------------------------------


def utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def run_coroutine_sync(coro: Any) -> Any:
    """Run a coroutine from synchronous code, with a clear error inside active event loops."""
    try:
        asyncio.get_running_loop()
    except RuntimeError:
        return asyncio.run(coro)
    raise RuntimeError("An event loop is already running. Use the async method instead, e.g. await arun_goldset().")


async def maybe_await(value: Any) -> Any:
    if inspect.isawaitable(value):
        return await value
    return value


def to_plain_dict(value: Any) -> JsonDict:
    if value is None:
        return {}
    if isinstance(value, Mapping):
        return {str(k): to_json_safe(v) for k, v in value.items()}
    if is_dataclass(value):
        return to_plain_dict(asdict(value))
    if hasattr(value, "to_dict") and callable(value.to_dict):
        return to_plain_dict(value.to_dict())
    if hasattr(value, "dict") and callable(value.dict):
        return to_plain_dict(value.dict())
    return {"value": to_json_safe(value)}


def to_json_safe(value: Any) -> Any:
    if isinstance(value, Mapping):
        return {str(k): to_json_safe(v) for k, v in value.items()}
    if isinstance(value, list | tuple | set):
        return [to_json_safe(v) for v in value]
    if is_dataclass(value):
        return to_json_safe(asdict(value))
    if hasattr(value, "to_dict") and callable(value.to_dict):
        return to_json_safe(value.to_dict())
    if isinstance(value, datetime):
        return value.isoformat()
    try:
        json.dumps(value)
        return value
    except TypeError:
        return str(value)


def optional_str(value: Any) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    return text or None


def normalize_key(value: Any) -> str:
    if value is None:
        return ""
    text = str(value).strip().lower()
    text = text.replace("ي", "ی").replace("ك", "ک")
    text = re.sub(r"\s+", "_", text)
    return text


def normalize_route(value: Any) -> str:
    text = normalize_key(value).upper()
    aliases = {
        "OUT_OF_SCOPE": "REJECT",
        "ACCESS_DENIED": "REJECT",
        "DATA_GAP": "GAP",
        "CLARIFICATION": "NEEDS_CLARIFICATION",
    }
    return aliases.get(text, text)


def normalize_status(value: Any) -> str:
    if value is None:
        return ""
    text = str(value).strip().upper()
    aliases = {
        "SUPPORTED": "SUPPORTED",
        "PARTIAL_SUPPORTED": "PARTIAL_SUPPORTED",
        "VALID": "VALID",
        "SUCCESS": "SUCCESS",
        "NOT_EXECUTED": "NOT_EXECUTED",
        "GAP": "DATA_GAP",
        "REJECT": "ACCESS_DENIED",
        "CLARIFICATION": "NEEDS_CLARIFICATION",
    }
    return aliases.get(text, text)


def normalize_sql_text(sql: Any) -> str:
    text = str(sql or "").strip().lower()
    text = text.replace("\u200c", " ")
    text = re.sub(r"\s+", " ", text)
    return text


def normalize_visual_token(value: Any) -> str:
    text = normalize_key(value)
    aliases = {
        "pie": "pie_chart",
        "bar": "bar_chart",
        "horizontal_bar": "horizontal_bar_chart",
        "line": "line_chart",
        "kpi": "kpi_card",
        "card": "kpi_card",
        "message": "status_message",
    }
    return aliases.get(text, text)


def split_or_options(value: Any) -> list[str]:
    text = str(value or "")
    parts = re.split(r"\s*(?:/|\bor\b|\|)\s*", text)
    return [part.strip() for part in parts if part.strip()]


def contains_token(haystack: Any, needle: str) -> bool:
    h = normalize_sql_text(haystack)
    n = normalize_sql_text(needle)
    if not n:
        return True
    # Remove aliases where expected tokens do not include v. but SQL does.
    if n in h:
        return True
    if n.startswith("v.") and n[2:] in h:
        return True
    if not n.startswith("v.") and f"v.{n}" in h:
        return True
    return False


def count_sql_statements(sql: str) -> int:
    text = re.sub(r"'([^']|'')*'", "''", str(sql or ""))
    statements = [part.strip() for part in text.split(";") if part.strip()]
    return len(statements)


def pass_check(name: str, weight: float, expected: Any, actual: Any, details: str | None = None) -> EvaluationCheck:
    return EvaluationCheck(name=name, weight=weight, score=weight, passed=True, expected=expected, actual=actual, details=details)


def first_non_empty(*values: Any) -> Any:
    for value in values:
        if value is None:
            continue
        if isinstance(value, str) and not value.strip():
            continue
        return value
    return None


def first_present(mapping: Mapping[str, Any], keys: Sequence[str]) -> Any:
    for key in keys:
        value = mapping.get(key)
        if value is not None and not (isinstance(value, str) and not value.strip()):
            return value
    return None


def merge_lists(*values: Any) -> list[str]:
    out: list[str] = []
    for value in values:
        if not value:
            continue
        if isinstance(value, str):
            out.append(value)
        elif isinstance(value, Iterable):
            out.extend(str(item) for item in value if item is not None)
        else:
            out.append(str(value))
    return list(dict.fromkeys(out))


def extract_visualization_type(value: Any) -> str | None:
    if value is None:
        return None
    if isinstance(value, str):
        return value
    if isinstance(value, Mapping):
        for key in (
            "type",
            "chart_type",
            "chartType",
            "visualization_type",
            "primary_visualization",
            "recommended_visualization",
            "output_type",
        ):
            if value.get(key):
                return str(value[key])
        chart_spec = value.get("chart_spec") or value.get("spec")
        if isinstance(chart_spec, Mapping):
            return extract_visualization_type(chart_spec)
    return None


def infer_domain_from_route(route: Any, status: Any) -> str | None:
    normalized_status = normalize_status(status)
    if normalized_status == "OUT_OF_SCOPE":
        return "NON_HR"
    if normalize_route(route) in {"SQL", "GAP", "REJECT"}:
        return "HR"
    return None


def count_by(items: Sequence[Mapping[str, Any]], key: str) -> JsonDict:
    counts: dict[str, int] = {}
    for item in items:
        value = str(item.get(key) or "unknown")
        counts[value] = counts.get(value, 0) + 1
    return dict(sorted(counts.items()))


# ---------------------------------------------------------------------------
# Factory and optional CLI helper
# ---------------------------------------------------------------------------


def get_evaluation_service(
    *,
    metadata_dir: str | Path | None = None,
    metadata_service: MetadataService | None = None,
    system_under_test: Any | None = None,
    default_execute_sql: bool = False,
    current_shamsi_year: int = 1404,
) -> EvaluationService:
    return EvaluationService(
        metadata_dir=metadata_dir,
        metadata_service=metadata_service,
        system_under_test=system_under_test,
        default_execute_sql=default_execute_sql,
        current_shamsi_year=current_shamsi_year,
    )


if __name__ == "__main__":  # pragma: no cover - convenience local runner.
    import argparse

    parser = argparse.ArgumentParser(description="Run HR BI Assistant Goldset evaluation.")
    parser.add_argument("--metadata-dir", default=None, help="Metadata directory path.")
    parser.add_argument("--limit", type=int, default=None, help="Limit number of test cases.")
    parser.add_argument("--suite", action="append", default=None, help="Filter by suite. Can be repeated.")
    parser.add_argument("--category", action="append", default=None, help="Filter by category. Can be repeated.")
    parser.add_argument("--output", default="evaluation_results.json", help="JSON output path.")
    parser.add_argument("--csv", default=None, help="Optional CSV output path.")
    parser.add_argument("--markdown", default=None, help="Optional Markdown output path.")
    parser.add_argument("--execute-sql", action="store_true", help="Actually execute SQL. Off by default.")
    args = parser.parse_args()

    service = get_evaluation_service(metadata_dir=args.metadata_dir, default_execute_sql=args.execute_sql)
    run = service.run_goldset(suites=args.suite, categories=args.category, limit=args.limit)
    service.export_json(run, args.output, include_responses=False)
    if args.csv:
        service.export_csv(run, args.csv)
    if args.markdown:
        service.export_markdown(run, args.markdown)
    print(json.dumps(run.summary.to_dict(), ensure_ascii=False, indent=2))
