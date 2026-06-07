from __future__ import annotations

"""
explanation_generator.py
------------------------
Safe, deterministic explanation generator for HR BI Assistant Phase 2:
Controlled SQL-based MVP.

Place this file in:
    backend/app/services/explanation_generator.py

Responsibility:
    - Convert validated SQL/GAP/REJECT outputs into a short, safe Persian explanation.
    - Add a light managerial interpretation only when it is supported by returned data.
    - Never fabricate data, thresholds, policies, or individual employee information.
    - Keep analytical caveats explicit, especially for Data Gap and missing business rules.

Design notes:
    - This module is intentionally rule-based for Phase 2. It does not require an LLM.
    - If an LLM is added later, keep this module as the safety envelope/post-processor.
    - The public API mirrors the other service modules in this project:
      generate / build / run / arun / __call__.
"""

import asyncio
import math
import re
from copy import deepcopy
from dataclasses import asdict, dataclass, field, is_dataclass
from datetime import date, datetime
from decimal import Decimal
from pathlib import Path
from typing import Any, Mapping, Sequence

try:  # package import when copied into backend/app/services
    from .metadata_service import MetadataService, get_metadata_service
except Exception:  # pragma: no cover - local/script execution fallback
    try:
        from metadata_service import MetadataService, get_metadata_service  # type: ignore
    except Exception:  # pragma: no cover
        MetadataService = Any  # type: ignore
        get_metadata_service = None  # type: ignore


JsonDict = dict[str, Any]

ROUTE_SQL = "SQL"
ROUTE_GAP = "GAP"
ROUTE_REJECT = "REJECT"
ROUTE_NEEDS_CLARIFICATION = "NEEDS_CLARIFICATION"

STATUS_SUCCESS = "SUCCESS"
STATUS_VALID = "VALID"
STATUS_SUPPORTED = "SUPPORTED"
STATUS_DATA_GAP = "DATA_GAP"
STATUS_ACCESS_DENIED = "ACCESS_DENIED"
STATUS_OUT_OF_SCOPE = "OUT_OF_SCOPE"
STATUS_NEEDS_CLARIFICATION = "NEEDS_CLARIFICATION"
STATUS_SQL_VALIDATION_FAILED = "SQL_VALIDATION_FAILED"
STATUS_EXECUTION_FAILED = "EXECUTION_FAILED"
STATUS_NO_DATA = "NO_DATA"
STATUS_NOT_EXECUTED = "NOT_EXECUTED"

SUCCESS_STATUSES = {STATUS_SUCCESS, STATUS_VALID, STATUS_SUPPORTED, "OK", "DONE"}
NON_DATA_STATUSES = {
    STATUS_DATA_GAP,
    STATUS_ACCESS_DENIED,
    STATUS_OUT_OF_SCOPE,
    STATUS_NEEDS_CLARIFICATION,
    STATUS_SQL_VALIDATION_FAILED,
    STATUS_EXECUTION_FAILED,
    STATUS_NO_DATA,
    STATUS_NOT_EXECUTED,
    "METADATA_ERROR",
    "REJECTED",
}

DEFAULT_STATUS_MESSAGES: dict[str, JsonDict] = {
    STATUS_DATA_GAP: {
        "title_fa": "داده کافی نیست",
        "summary_fa": "این سؤال به منابع انسانی مربوط است، اما در نسخه فعلی داده، قانون یا سند کافی برای پاسخ دقیق وجود ندارد.",
        "managerial_note_fa": "بهتر است این مورد به‌عنوان Data Gap یا Knowledge Gap ثبت شود تا در فاز بعدی با داده یا تعریف رسمی کامل شود.",
        "next_step_fa": "داده یا قانون موردنیاز را مشخص کنید و بعد از تکمیل Metadata دوباره تست بگیرید.",
    },
    STATUS_ACCESS_DENIED: {
        "title_fa": "امکان نمایش اطلاعات وجود ندارد",
        "summary_fa": "درخواست شامل اطلاعات فردی یا حساس کارکنان است و طبق سیاست محرمانگی قابل نمایش نیست.",
        "managerial_note_fa": "برای حفظ حریم خصوصی، پاسخ فقط باید در سطح تجمیعی و آماری ارائه شود.",
        "next_step_fa": "سؤال را به شکل تجمیعی بازنویسی کنید؛ مثلاً تعداد یا درصد کارکنان در یک گروه را بپرسید.",
    },
    STATUS_OUT_OF_SCOPE: {
        "title_fa": "خارج از دامنه منابع انسانی",
        "summary_fa": "این سؤال در محدوده HR BI Assistant نیست و نباید برای آن از دیتابیس منابع انسانی پاسخ ساخته شود.",
        "managerial_note_fa": "در فاز دوم، سیستم فقط سؤال‌های منابع انسانی، کارکنان، قرارداد، جذب، تحصیلات، سن و ساختار سازمانی را پوشش می‌دهد.",
        "next_step_fa": "سؤال را در حوزه منابع انسانی بازنویسی کنید.",
    },
    STATUS_NEEDS_CLARIFICATION: {
        "title_fa": "نیاز به شفاف‌سازی سؤال",
        "summary_fa": "سؤال قابل بررسی است، اما برای انتخاب شاخص، سطح تحلیل یا بازه زمانی نیاز به توضیح بیشتری دارد.",
        "managerial_note_fa": "شفاف‌سازی سؤال باعث می‌شود مسیر SQL، Gap یا Reject درست‌تر انتخاب شود.",
        "next_step_fa": "شاخص، سطح تحلیل یا بازه زمانی موردنظر را مشخص کنید.",
    },
    STATUS_SQL_VALIDATION_FAILED: {
        "title_fa": "SQL معتبر نیست",
        "summary_fa": "کوئری تولیدشده با قوانین امنیتی یا ساختاری فاز دوم سازگار نیست و اجرا نمی‌شود.",
        "managerial_note_fa": "در این MVP، اجرای SQL فقط وقتی مجاز است که کوئری SELECT-only، View-based و بدون جدول خام باشد.",
        "next_step_fa": "SQL تولیدشده را لاگ و بر اساس قواعد Validator اصلاح کنید.",
    },
    STATUS_EXECUTION_FAILED: {
        "title_fa": "خطا در اجرای کوئری",
        "summary_fa": "کوئری از مرحله اعتبارسنجی عبور کرده، اما هنگام اجرا روی دیتابیس خطا رخ داده است.",
        "managerial_note_fa": "این خطا بیشتر عملیاتی است و باید از مسیر لاگ دیتابیس، اتصال و schema بررسی شود.",
        "next_step_fa": "اتصال دیتابیس، نام View و لاگ اجرای Query Executor را بررسی کنید.",
    },
    STATUS_NO_DATA: {
        "title_fa": "داده‌ای یافت نشد",
        "summary_fa": "برای فیلترها یا سطح تحلیل انتخاب‌شده، داده قابل نمایش وجود ندارد.",
        "managerial_note_fa": "نبود داده در خروجی الزاماً به معنی نبود پدیده در سازمان نیست؛ ممکن است به فیلتر یا کیفیت داده مربوط باشد.",
        "next_step_fa": "فیلتر، سطح تحلیل یا بازه زمانی را بازبینی کنید.",
    },
    STATUS_NOT_EXECUTED: {
        "title_fa": "کوئری اجرا نشد",
        "summary_fa": "به دلیل وضعیت فعلی درخواست یا تنظیمات اجرا، کوئری روی دیتابیس اجرا نشده است.",
        "managerial_note_fa": "برای پاسخ عددی نهایی، اجرای Query Executor لازم است.",
        "next_step_fa": "در صورت مجاز بودن، اجرای SQL را فعال کنید و دوباره تست بگیرید.",
    },
}

FA_LABELS = {
    "employee_count": "تعداد کارکنان",
    "count": "تعداد",
    "total_count": "تعداد کل",
    "actual_headcount": "نیروی موجود",
    "approved_headcount": "چارت مصوب",
    "department_approved_headcount": "چارت مصوب",
    "headcount_gap": "اختلاف نیرو",
    "percentage": "درصد",
    "share_percentage": "درصد سهم",
    "contractor_count": "تعداد پیمانکاری",
    "contractor_percentage": "درصد پیمانکاری",
    "female_count": "تعداد زنان",
    "male_count": "تعداد مردان",
    "female_percentage": "درصد زنان",
    "male_percentage": "درصد مردان",
    "average_age": "میانگین سن",
    "avg_age": "میانگین سن",
    "average_service_years": "میانگین سابقه",
    "avg_service_years": "میانگین سابقه",
    "hire_count": "تعداد جذب",
    "hiring_count": "تعداد جذب",
    "without_service_count": "تعداد بدون سابقه",
    "below_required_education_count": "تعداد پایین‌تر از حداقل مدرک پست",
    "gender": "جنسیت",
    "marital_status": "وضعیت تأهل",
    "age_group_title": "گروه سنی",
    "education_title": "مدرک تحصیلی",
    "education_category": "گروه تحصیلی",
    "employment_type": "نوع استخدام",
    "contract_type": "نوع قرارداد",
    "service_domain": "حوزه خدمت",
    "department_name": "واحد/بخش",
    "province": "استان",
    "site_name": "محل خدمت",
    "position_title": "پست",
    "position_level": "سطح پست",
    "job_family": "خانواده شغلی",
    "hire_year": "سال جذب",
    "is_contractor": "وضعیت پیمانکاری",
}

DIMENSION_HINTS = {
    "gender",
    "marital_status",
    "age_group_title",
    "education_title",
    "education_category",
    "employment_type",
    "contract_type",
    "service_domain",
    "department_name",
    "department_level",
    "province",
    "site_name",
    "location_type",
    "position_title",
    "position_level",
    "job_family",
    "hire_year",
    "criticality_level",
    "is_contractor",
}

METRIC_HINTS = {
    "employee_count",
    "count",
    "total_count",
    "actual_headcount",
    "approved_headcount",
    "department_approved_headcount",
    "headcount_gap",
    "percentage",
    "share_percentage",
    "contractor_count",
    "contractor_percentage",
    "female_count",
    "male_count",
    "female_percentage",
    "male_percentage",
    "average_age",
    "avg_age",
    "average_service_years",
    "avg_service_years",
    "hire_count",
    "hiring_count",
    "without_service_count",
    "below_required_education_count",
}

SENSITIVE_COLUMN_PATTERNS = [
    r"national[_\s-]?id",
    r"personnel[_\s-]?number",
    r"first[_\s-]?name",
    r"last[_\s-]?name",
    r"full[_\s-]?name",
    r"phone",
    r"mobile",
    r"address",
    r"bank",
    r"insurance",
    r"salary",
    r"wage",
]


@dataclass
class ExplanationGeneratorConfig:
    max_rows_to_analyze: int = 100
    max_items_in_sentence: int = 3
    max_followups: int = 3
    include_technical_note: bool = False
    include_data_limitations: bool = True
    include_followups: bool = True
    include_sql_reference: bool = False
    safe_managerial_interpretation: bool = True
    default_title_fa: str = "نتیجه تحلیل منابع انسانی"


@dataclass
class ExplanationPayload:
    route: str
    status: str
    title_fa: str
    summary_fa: str
    managerial_note_fa: str | None = None
    key_findings: list[str] = field(default_factory=list)
    limitations: list[str] = field(default_factory=list)
    next_steps: list[str] = field(default_factory=list)
    follow_up_questions: list[str] = field(default_factory=list)
    technical_note: str | None = None
    confidence: str = "medium"
    warnings: list[str] = field(default_factory=list)
    metadata: JsonDict = field(default_factory=dict)

    def to_dict(self) -> JsonDict:
        return asdict(self)


class ExplanationGenerator:
    """
    Builds short, safe Persian explanations from query results or status payloads.

    Public methods:
        generate(...)
        build(...)
        run(...)
        arun(...)
        __call__(...)
    """

    def __init__(
        self,
        *,
        metadata_service: Any | None = None,
        metadata_dir: str | Path | None = None,
        max_rows_to_analyze: int = 100,
        include_technical_note: bool = False,
        include_data_limitations: bool = True,
        include_followups: bool = True,
        include_sql_reference: bool = False,
        safe_managerial_interpretation: bool = True,
    ) -> None:
        if metadata_service is not None:
            self.metadata = metadata_service
        elif get_metadata_service is not None:
            self.metadata = get_metadata_service(metadata_dir=metadata_dir, strict=False)
        else:
            self.metadata = None

        self.config = ExplanationGeneratorConfig(
            max_rows_to_analyze=int(max_rows_to_analyze),
            include_technical_note=bool(include_technical_note),
            include_data_limitations=bool(include_data_limitations),
            include_followups=bool(include_followups),
            include_sql_reference=bool(include_sql_reference),
            safe_managerial_interpretation=bool(safe_managerial_interpretation),
        )

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def generate(
        self,
        *,
        question: str | None = None,
        context: Any | None = None,
        query_result: Mapping[str, Any] | None = None,
        rows: Sequence[Mapping[str, Any]] | None = None,
        response_payload: Mapping[str, Any] | None = None,
        chart_payload: Mapping[str, Any] | None = None,
        status_payload: Mapping[str, Any] | None = None,
        route: str | None = None,
        status: str | None = None,
        intent_id: str | None = None,
        report_id: str | None = None,
        generated_sql: str | None = None,
        explanation_level: str = "managerial",
        **kwargs: Any,
    ) -> JsonDict:
        ctx = _to_mapping(context)
        status_payload_dict = dict(status_payload or {})
        response_payload_dict = dict(response_payload or {})
        chart_payload_dict = dict(chart_payload or {})

        resolved_question = question or str(ctx.get("question") or response_payload_dict.get("question") or "").strip()
        resolved_route = self._resolve_route(route=route, context=ctx, response_payload=response_payload_dict, status_payload=status_payload_dict)
        resolved_status = self._resolve_status(status=status, context=ctx, response_payload=response_payload_dict, status_payload=status_payload_dict)
        resolved_intent = self._first_non_empty(
            intent_id,
            response_payload_dict.get("detected_intent"),
            response_payload_dict.get("intent_id"),
            _get_nested(ctx, "intent_result", "intent"),
            _get_nested(ctx, "intent_result", "intent_id"),
            _get_nested(ctx, "route_result", "intent_id"),
            ctx.get("detected_intent"),
            ctx.get("intent_id"),
        )
        resolved_report = self._first_non_empty(
            report_id,
            response_payload_dict.get("report_id"),
            _get_nested(ctx, "intent_result", "report_id"),
            _get_nested(ctx, "route_result", "report_id"),
            ctx.get("report_id"),
        )
        resolved_sql = self._first_non_empty(
            generated_sql,
            response_payload_dict.get("generated_sql"),
            _get_nested(ctx, "sql_plan", "sql"),
            _get_nested(ctx, "sql_validation", "sql"),
            ctx.get("generated_sql"),
        )

        extracted_rows = self._extract_rows(rows=rows, query_result=query_result, context=ctx, response_payload=response_payload_dict)
        embedded_status = self._extract_embedded_status(extracted_rows)
        if embedded_status in NON_DATA_STATUSES:
            resolved_status = embedded_status
            resolved_route = _route_for_status(embedded_status)

        if resolved_status in SUCCESS_STATUSES and resolved_route == ROUTE_SQL:
            resolved_status = STATUS_SUCCESS

        title_fa = self._resolve_title_fa(intent_id=resolved_intent, report_id=resolved_report, response_payload=response_payload_dict)
        if resolved_route != ROUTE_SQL or resolved_status in NON_DATA_STATUSES:
            payload = self._build_status_explanation(
                route=resolved_route,
                status=resolved_status,
                title_fa=title_fa,
                question=resolved_question,
                status_payload=status_payload_dict or response_payload_dict,
                intent_id=resolved_intent,
                report_id=resolved_report,
            )
            return payload.to_dict()

        if not extracted_rows:
            payload = self._build_status_explanation(
                route=ROUTE_SQL,
                status=STATUS_NO_DATA,
                title_fa=title_fa,
                question=resolved_question,
                status_payload=status_payload_dict or response_payload_dict,
                intent_id=resolved_intent,
                report_id=resolved_report,
            )
            return payload.to_dict()

        safe_rows, safety_warnings = self._sanitize_rows(extracted_rows)
        if not safe_rows:
            payload = self._build_status_explanation(
                route=ROUTE_REJECT,
                status=STATUS_ACCESS_DENIED,
                title_fa="امکان نمایش اطلاعات وجود ندارد",
                question=resolved_question,
                status_payload={"reason": "All result columns were blocked by explanation safety rules."},
                intent_id=resolved_intent,
                report_id=resolved_report,
            )
            payload.warnings.extend(safety_warnings)
            return payload.to_dict()

        payload = self._build_sql_explanation(
            question=resolved_question,
            rows=safe_rows,
            intent_id=resolved_intent,
            report_id=resolved_report,
            generated_sql=resolved_sql,
            title_fa=title_fa,
            chart_payload=chart_payload_dict,
            response_payload=response_payload_dict,
            explanation_level=explanation_level,
            extra_warnings=safety_warnings + _as_list(response_payload_dict.get("warnings")) + _as_list(chart_payload_dict.get("warnings")),
            **kwargs,
        )
        return payload.to_dict()

    def build(self, **kwargs: Any) -> JsonDict:
        return self.generate(**kwargs)

    def build_explanation(self, **kwargs: Any) -> JsonDict:
        return self.generate(**kwargs)

    def run(self, **kwargs: Any) -> JsonDict:
        return self.generate(**kwargs)

    async def arun(self, **kwargs: Any) -> JsonDict:
        return self.generate(**kwargs)

    def __call__(self, **kwargs: Any) -> JsonDict:
        return self.generate(**kwargs)

    # ------------------------------------------------------------------
    # Status route explanation
    # ------------------------------------------------------------------

    def _build_status_explanation(
        self,
        *,
        route: str,
        status: str,
        title_fa: str,
        question: str,
        status_payload: Mapping[str, Any],
        intent_id: str | None,
        report_id: str | None,
    ) -> ExplanationPayload:
        template = deepcopy(DEFAULT_STATUS_MESSAGES.get(status, DEFAULT_STATUS_MESSAGES[STATUS_NEEDS_CLARIFICATION]))
        title = _clean_text(str(status_payload.get("title_fa") or template.get("title_fa") or title_fa))
        summary = _clean_text(str(status_payload.get("message_fa") or status_payload.get("summary_fa") or template.get("summary_fa") or "وضعیت درخواست مشخص نیست."))
        managerial_note = _clean_text(str(status_payload.get("managerial_note_fa") or template.get("managerial_note_fa") or "")) or None
        next_step = _clean_text(str(status_payload.get("recommended_action_fa") or status_payload.get("next_step_fa") or template.get("next_step_fa") or ""))

        reason = _clean_text(str(status_payload.get("reason_fa") or status_payload.get("reason") or ""))
        gap_code = _clean_text(str(status_payload.get("gap_code") or ""))
        missing_data = _as_list(status_payload.get("missing_data"))

        findings: list[str] = []
        limitations: list[str] = []
        next_steps: list[str] = []

        if reason and reason not in summary:
            limitations.append(f"دلیل: {reason}")
        if gap_code:
            limitations.append(f"کد شکاف ثبت‌شده: {gap_code}")
        if missing_data:
            readable_missing = "، ".join(str(x) for x in missing_data[:4])
            limitations.append(f"داده/تعریف موردنیاز: {readable_missing}")
        if next_step:
            next_steps.append(next_step)

        followups = self._suggest_followups(intent_id=intent_id, report_id=report_id, status=status, question=question)

        return ExplanationPayload(
            route=route,
            status=status,
            title_fa=title,
            summary_fa=summary,
            managerial_note_fa=managerial_note,
            key_findings=findings,
            limitations=limitations,
            next_steps=next_steps,
            follow_up_questions=followups if self.config.include_followups else [],
            technical_note=None,
            confidence="high" if status in {STATUS_ACCESS_DENIED, STATUS_OUT_OF_SCOPE, STATUS_NEEDS_CLARIFICATION} else "medium",
            warnings=_as_list(status_payload.get("warnings")),
            metadata={
                "intent_id": intent_id,
                "report_id": report_id,
                "question": question,
                "is_data_response": False,
            },
        )

    # ------------------------------------------------------------------
    # SQL success explanation
    # ------------------------------------------------------------------

    def _build_sql_explanation(
        self,
        *,
        question: str,
        rows: list[JsonDict],
        intent_id: str | None,
        report_id: str | None,
        generated_sql: str | None,
        title_fa: str,
        chart_payload: Mapping[str, Any],
        response_payload: Mapping[str, Any],
        explanation_level: str,
        extra_warnings: list[str],
        **_: Any,
    ) -> ExplanationPayload:
        analyzed_rows = rows[: self.config.max_rows_to_analyze]
        columns = list(analyzed_rows[0].keys()) if analyzed_rows else []
        dimension_columns, metric_columns = self._classify_columns(columns, analyzed_rows)

        summary = self._build_summary_sentence(
            rows=analyzed_rows,
            title_fa=title_fa,
            dimension_columns=dimension_columns,
            metric_columns=metric_columns,
            intent_id=intent_id,
        )
        key_findings = self._build_key_findings(
            rows=analyzed_rows,
            dimension_columns=dimension_columns,
            metric_columns=metric_columns,
            intent_id=intent_id,
        )
        managerial_note = self._build_managerial_note(
            rows=analyzed_rows,
            dimension_columns=dimension_columns,
            metric_columns=metric_columns,
            intent_id=intent_id,
            title_fa=title_fa,
            question=question,
        )
        limitations = self._build_limitations(
            rows=analyzed_rows,
            intent_id=intent_id,
            report_id=report_id,
            response_payload=response_payload,
            extra_warnings=extra_warnings,
        )
        next_steps = self._build_next_steps(
            intent_id=intent_id,
            rows=analyzed_rows,
            dimension_columns=dimension_columns,
            metric_columns=metric_columns,
        )
        followups = self._suggest_followups(intent_id=intent_id, report_id=report_id, status=STATUS_SUCCESS, question=question)

        if explanation_level == "short":
            key_findings = key_findings[:2]
            limitations = limitations[:1]
            next_steps = next_steps[:1]
        elif explanation_level == "technical":
            self.config.include_technical_note = True

        technical_note = None
        if self.config.include_technical_note:
            technical_parts = ["پاسخ بر اساس View تحلیلی امن منابع انسانی ساخته شده است."]
            if generated_sql and self.config.include_sql_reference:
                technical_parts.append(f"SQL: {generated_sql}")
            if chart_payload:
                chart_type = chart_payload.get("visualization_type") or chart_payload.get("type")
                if chart_type:
                    technical_parts.append(f"نوع نمایش پیشنهادی: {chart_type}")
            technical_note = " ".join(technical_parts)

        return ExplanationPayload(
            route=ROUTE_SQL,
            status=STATUS_SUCCESS,
            title_fa=title_fa,
            summary_fa=summary,
            managerial_note_fa=managerial_note,
            key_findings=key_findings,
            limitations=limitations if self.config.include_data_limitations else [],
            next_steps=next_steps,
            follow_up_questions=followups if self.config.include_followups else [],
            technical_note=technical_note,
            confidence="high" if key_findings else "medium",
            warnings=_dedupe([x for x in extra_warnings if x]),
            metadata={
                "intent_id": intent_id,
                "report_id": report_id,
                "question": question,
                "row_count_analyzed": len(analyzed_rows),
                "dimension_columns": dimension_columns,
                "metric_columns": metric_columns,
                "is_data_response": True,
            },
        )

    def _build_summary_sentence(
        self,
        *,
        rows: list[JsonDict],
        title_fa: str,
        dimension_columns: list[str],
        metric_columns: list[str],
        intent_id: str | None,
    ) -> str:
        if not rows:
            return "برای این سؤال داده قابل نمایش پیدا نشد."

        if len(rows) == 1:
            row = rows[0]
            metric = self._select_primary_metric(metric_columns, row)
            if metric:
                return f"بر اساس داده فعلی، {title_fa} برابر با {self._format_value(row.get(metric), metric)} است."
            return f"بر اساس داده فعلی، نتیجه {title_fa} محاسبه شد."

        metric = self._select_primary_metric(metric_columns, rows[0])
        dimension = self._select_primary_dimension(dimension_columns)
        if metric and dimension:
            top_row = self._max_row(rows, metric)
            top_name = self._format_dimension_value(top_row.get(dimension), dimension) if top_row else "نامشخص"
            top_value = self._format_value(top_row.get(metric), metric) if top_row else "نامشخص"
            return f"بر اساس داده فعلی، {title_fa} در {len(rows)} گروه محاسبه شد و بیشترین مقدار مربوط به «{top_name}» با مقدار {top_value} است."

        if metric:
            values = [self._to_number(row.get(metric)) for row in rows if self._to_number(row.get(metric)) is not None]
            if values:
                return f"بر اساس داده فعلی، {title_fa} برای {len(values)} ردیف محاسبه شد."

        return f"بر اساس داده فعلی، خروجی {title_fa} آماده شد."

    def _build_key_findings(
        self,
        *,
        rows: list[JsonDict],
        dimension_columns: list[str],
        metric_columns: list[str],
        intent_id: str | None,
    ) -> list[str]:
        findings: list[str] = []
        if not rows:
            return findings

        metric = self._select_primary_metric(metric_columns, rows[0])
        dimension = self._select_primary_dimension(dimension_columns)

        if len(rows) == 1 and metric:
            findings.append(f"{self._label(metric)}: {self._format_value(rows[0].get(metric), metric)}")
            # Add secondary metrics if present, e.g., count + percentage.
            for secondary in metric_columns:
                if secondary != metric and secondary in rows[0]:
                    findings.append(f"{self._label(secondary)}: {self._format_value(rows[0].get(secondary), secondary)}")
                    if len(findings) >= 3:
                        break
            return findings

        if metric and dimension:
            top_row = self._max_row(rows, metric)
            bottom_row = self._min_row(rows, metric)
            if top_row:
                findings.append(
                    f"بیشترین {self._label(metric)} مربوط به «{self._format_dimension_value(top_row.get(dimension), dimension)}» است: {self._format_value(top_row.get(metric), metric)}."
                )
            if bottom_row and top_row and bottom_row is not top_row:
                findings.append(
                    f"کمترین {self._label(metric)} مربوط به «{self._format_dimension_value(bottom_row.get(dimension), dimension)}» است: {self._format_value(bottom_row.get(metric), metric)}."
                )

            if self._is_time_dimension(dimension):
                trend = self._trend_sentence(rows=rows, x_col=dimension, y_col=metric)
                if trend:
                    findings.insert(0, trend)

            percentage_metric = self._find_percentage_metric(metric_columns)
            if percentage_metric and percentage_metric != metric:
                top_pct_row = self._max_row(rows, percentage_metric)
                if top_pct_row:
                    findings.append(
                        f"بالاترین سهم مربوط به «{self._format_dimension_value(top_pct_row.get(dimension), dimension)}» است: {self._format_value(top_pct_row.get(percentage_metric), percentage_metric)}."
                    )

        # Headcount gap special handling.
        if "headcount_gap" in metric_columns and dimension:
            shortage_rows = [r for r in rows if (self._to_number(r.get("headcount_gap")) or 0) > 0]
            surplus_rows = [r for r in rows if (self._to_number(r.get("headcount_gap")) or 0) < 0]
            if shortage_rows:
                top_shortage = self._max_row(shortage_rows, "headcount_gap")
                if top_shortage:
                    findings.append(
                        f"بیشترین کمبود نیرو در «{self._format_dimension_value(top_shortage.get(dimension), dimension)}» دیده می‌شود: {self._format_value(top_shortage.get('headcount_gap'), 'headcount_gap')}."
                    )
            if surplus_rows:
                findings.append("برخی واحدها مقدار اختلاف منفی دارند؛ یعنی نیروی موجود از چارت مصوب بیشتر گزارش شده است.")

        return _dedupe(findings)[:4]

    def _build_managerial_note(
        self,
        *,
        rows: list[JsonDict],
        dimension_columns: list[str],
        metric_columns: list[str],
        intent_id: str | None,
        title_fa: str,
        question: str,
    ) -> str | None:
        if not self.config.safe_managerial_interpretation:
            return None

        intent = intent_id or ""
        metric = self._select_primary_metric(metric_columns, rows[0] if rows else {})
        dimension = self._select_primary_dimension(dimension_columns)

        # All notes below are deliberately cautious and avoid unsupported thresholds.
        if "contractor" in intent or "pیمان" in question or "پیمان" in question:
            return "این خروجی برای پایش وابستگی سازمان به نیروهای پیمانکاری مفید است؛ تفسیر ریسک یا مطلوب‌بودن سهم پیمانکاری نیاز به آستانه رسمی سازمان دارد."
        if "hiring" in intent or dimension == "hire_year":
            return "این خروجی روند جذب را نشان می‌دهد؛ برای تحلیل کفایت جذب باید آن را کنار نیاز واحدها، چارت مصوب و حجم کار سازمان بررسی کرد."
        if "education" in intent:
            return "این خروجی ترکیب تحصیلات را نشان می‌دهد؛ نتیجه‌گیری درباره نیاز آموزشی یا کمبود تخصص فقط با تعریف شایستگی‌ها و نیاز هر پست قابل دفاع است."
        if "age" in intent:
            return "این خروجی برای پایش ساختار سنی مفید است؛ تحلیل ریسک بازنشستگی یا سالخوردگی نیاز به قانون رسمی و آستانه‌های سازمانی دارد."
        if "gender" in intent:
            return "این خروجی تصویر ترکیب جنسیتی را نشان می‌دهد؛ قضاوت درباره تعادل جنسیتی باید با سیاست‌های سازمانی و سطح شغل/واحد همراه شود."
        if "headcount_gap" in intent or "approved_headcount" in metric_columns or "headcount_gap" in metric_columns:
            return "این خروجی اختلاف نیروی موجود با چارت مصوب را نشان می‌دهد؛ برای تصمیم مدیریتی بهتر است در کنار اولویت واحد، حساسیت نقش و برنامه جذب بررسی شود."
        if "employment" in intent or "contract" in intent:
            return "این خروجی ترکیب نوع استخدام یا قرارداد را نشان می‌دهد؛ اثر آن بر ثبات سازمان باید با سیاست جذب، بودجه و ریسک عملیاتی تفسیر شود."
        if dimension in {"service_domain", "department_name", "province", "site_name"}:
            return "این خروجی توزیع نیروی انسانی را در سطح سازمانی/مکانی نشان می‌دهد؛ برای تشخیص عدم‌تعادل، باید ظرفیت مصوب یا نیاز عملیاتی هر بخش هم وارد تحلیل شود."

        return "این نتیجه یک خروجی آماری از داده فعلی است و برای تحلیل مدیریتی قطعی باید در کنار تعریف شاخص، آستانه تصمیم‌گیری و محدودیت داده تفسیر شود."

    def _build_limitations(
        self,
        *,
        rows: list[JsonDict],
        intent_id: str | None,
        report_id: str | None,
        response_payload: Mapping[str, Any],
        extra_warnings: list[str],
    ) -> list[str]:
        limitations: list[str] = []
        limitations.append("این پاسخ فقط بر اساس View تحلیلی امن و داده کارکنان فعال ساخته شده است.")

        intent = intent_id or ""
        if "city" in intent:
            limitations.append("داده شهر در MVP فعلی قابل اتکا نیست و تحلیل شهری باید Data Gap شود.")
        if "retirement" in intent:
            limitations.append("قانون رسمی آستانه بازنشستگی در Metadata فعلی تعریف نشده است.")
        if "headcount_gap" in intent:
            limitations.append("اختلاف چارت مصوب با نیروی موجود یک شاخص اولیه است و جایگزین تحلیل ظرفیت واقعی واحدها نیست.")
        if "hiring" in intent:
            limitations.append("سال جذب بر اساس سال شمسی موجود در View تحلیل شده است؛ تحلیل ماهانه در MVP فعلی پوشش داده نشده است.")

        for warning in extra_warnings:
            warning_text = _clean_text(str(warning))
            if warning_text:
                limitations.append(warning_text)

        for warning in _as_list(response_payload.get("warnings")):
            warning_text = _clean_text(str(warning))
            if warning_text:
                limitations.append(warning_text)

        return _dedupe(limitations)[:5]

    def _build_next_steps(
        self,
        *,
        intent_id: str | None,
        rows: list[JsonDict],
        dimension_columns: list[str],
        metric_columns: list[str],
    ) -> list[str]:
        intent = intent_id or ""
        steps: list[str] = []

        if "headcount_gap" in intent:
            steps.append("واحدهای دارای بیشترین اختلاف را با چارت مصوب، اولویت عملیاتی و حساسیت نقش بازبینی کنید.")
        elif "contractor" in intent:
            steps.append("در صورت نیاز، سهم پیمانکاری را به تفکیک حوزه، واحد و نوع قرارداد بررسی کنید.")
        elif "hiring" in intent:
            steps.append("روند جذب را کنار کمبود نیرو و برنامه جذب سالانه قرار دهید تا تحلیل کامل‌تر شود.")
        elif "education" in intent:
            steps.append("برای تحلیل تخصص، خروجی تحصیلات را با حداقل مدرک موردنیاز پست‌ها مقایسه کنید.")
        elif "age" in intent:
            steps.append("برای تحلیل ریسک سنی، آستانه رسمی بازنشستگی و گروه‌های بحرانی را در Metadata تعریف کنید.")
        elif "gender" in intent:
            steps.append("ترکیب جنسیتی را در سطح حوزه، واحد یا گروه سنی هم بررسی کنید.")
        else:
            steps.append("در صورت نیاز، همین شاخص را به تفکیک حوزه، واحد یا استان بررسی کنید.")

        return steps[:3]

    def _suggest_followups(self, *, intent_id: str | None, report_id: str | None, status: str, question: str) -> list[str]:
        if not self.config.include_followups:
            return []
        intent = intent_id or ""
        if status == STATUS_ACCESS_DENIED:
            return ["تعداد کارکنان به تفکیک جنسیت چقدر است؟", "تعداد کارکنان به تفکیک واحد چقدر است؟"]
        if status == STATUS_DATA_GAP:
            return ["چه داده‌ای برای پاسخ به این سؤال لازم است؟", "کدام سؤال‌های مشابه در MVP قابل پاسخ هستند؟"]
        if status == STATUS_OUT_OF_SCOPE:
            return ["تعداد کل کارکنان چند نفر است؟", "روند جذب سالانه چطور بوده؟"]
        if status == STATUS_NEEDS_CLARIFICATION:
            return ["تعداد کارکنان به تفکیک حوزه خدمت چقدر است؟", "میانگین سن کارکنان به تفکیک جنسیت چقدر است؟"]

        if "gender" in intent:
            return ["میانگین سن کارکنان زن و مرد چقدر است؟", "توزیع جنسیت در هر حوزه چگونه است؟"]
        if "education" in intent:
            return ["کدام مدرک تحصیلی بیشترین سهم را دارد؟", "چند نفر مدرک کارشناسی دارند؟"]
        if "contractor" in intent:
            return ["سهم پیمانکاری در هر حوزه چند درصد است؟", "تعداد کارکنان بر اساس نوع قرارداد چقدر است؟"]
        if "hiring" in intent:
            return ["سال بیشترین جذب کدام است؟", "جذب ۱۵ سال اخیر چه روندی داشته؟"]
        if "age" in intent:
            return ["کدام گروه سنی بیشترین نیروی انسانی را دارد؟", "تعداد کارکنان ۶۰ سال به بالا چقدر است؟"]
        if "headcount_gap" in intent:
            return ["کدام واحد بیشترین کمبود نیرو را دارد؟", "تعداد کارکنان به تفکیک حوزه خدمت چقدر است؟"]
        return ["تعداد کل کارکنان چند نفر است؟", "تعداد کارکنان بر اساس نوع استخدام چقدر است؟"][: self.config.max_followups]

    # ------------------------------------------------------------------
    # Resolution helpers
    # ------------------------------------------------------------------

    def _resolve_route(self, *, route: str | None, context: JsonDict, response_payload: JsonDict, status_payload: JsonDict) -> str:
        value = self._first_non_empty(
            route,
            response_payload.get("route"),
            status_payload.get("route"),
            _get_nested(context, "route_result", "route"),
            _get_nested(context, "validation_result", "route"),
            context.get("route"),
        )
        return _normalize_route(value or ROUTE_SQL)

    def _resolve_status(self, *, status: str | None, context: JsonDict, response_payload: JsonDict, status_payload: JsonDict) -> str:
        value = self._first_non_empty(
            status,
            response_payload.get("status"),
            status_payload.get("status"),
            _get_nested(context, "final_response", "status"),
            _get_nested(context, "query_result", "status"),
            _get_nested(context, "sql_validation", "status"),
            _get_nested(context, "validation_result", "status"),
            context.get("status"),
        )
        normalized = _normalize_status(value or STATUS_SUCCESS)
        return normalized

    def _resolve_title_fa(self, *, intent_id: str | None, report_id: str | None, response_payload: Mapping[str, Any]) -> str:
        explicit_title = self._first_non_empty(
            response_payload.get("title_fa"),
            _get_nested(response_payload, "visualization", "title_fa"),
            _get_nested(response_payload, "visualization", "title"),
        )
        if explicit_title:
            return _clean_text(str(explicit_title))

        if self.metadata is not None and report_id:
            with _suppress_exceptions():
                report = self.metadata.get_report(report_id)
                if report:
                    return str(report.get("title_fa") or report.get("title") or self.config.default_title_fa)
        if self.metadata is not None and intent_id:
            with _suppress_exceptions():
                intent = self.metadata.get_intent(intent_id)
                if intent:
                    return str(intent.get("title_fa") or intent.get("title") or intent.get("description_fa") or self._intent_title(intent_id))
        return self._intent_title(intent_id) if intent_id else self.config.default_title_fa

    def _intent_title(self, intent_id: str | None) -> str:
        titles = {
            "total_employee_count": "تعداد کل کارکنان فعال",
            "employee_count_by_gender": "تعداد کارکنان به تفکیک جنسیت",
            "gender_percentage": "درصد کارکنان به تفکیک جنسیت",
            "average_age": "میانگین سن کارکنان",
            "employee_count_by_age_filter": "تعداد کارکنان بر اساس فیلتر سنی",
            "employee_count_by_age_group": "تعداد کارکنان به تفکیک گروه سنی",
            "employee_count_by_education": "تعداد کارکنان به تفکیک مدرک تحصیلی",
            "most_common_education": "بیشترین مدرک تحصیلی",
            "employee_count_by_employment_type": "تعداد کارکنان به تفکیک نوع استخدام",
            "employee_count_by_contract_type": "تعداد کارکنان به تفکیک نوع قرارداد",
            "contractor_share": "سهم نیروهای پیمانکاری",
            "contractor_share_by_service_domain": "سهم پیمانکاری در هر حوزه",
            "employee_count_by_service_domain": "تعداد کارکنان به تفکیک حوزه خدمت",
            "employee_count_by_department": "تعداد کارکنان به تفکیک واحد/بخش",
            "employee_count_by_province": "تعداد کارکنان به تفکیک استان",
            "hiring_trend_annual": "روند جذب سالانه",
            "hiring_last_15_years": "جذب ۱۵ سال اخیر",
            "most_or_least_hiring_year": "سال بیشترین یا کمترین جذب",
            "headcount_gap_by_department": "اختلاف نیروی موجود با چارت مصوب",
            "average_service_years": "میانگین سابقه کارکنان",
        }
        return titles.get(intent_id or "", self.config.default_title_fa)

    @staticmethod
    def _first_non_empty(*values: Any) -> Any | None:
        for value in values:
            if value is not None and value != "":
                return value
        return None

    # ------------------------------------------------------------------
    # Data extraction and classification
    # ------------------------------------------------------------------

    def _extract_rows(
        self,
        *,
        rows: Sequence[Mapping[str, Any]] | None,
        query_result: Mapping[str, Any] | None,
        context: JsonDict,
        response_payload: JsonDict,
    ) -> list[JsonDict]:
        if rows is not None:
            return [_json_safe_dict(r) for r in rows if isinstance(r, Mapping)]

        for source in [query_result, context.get("query_result"), response_payload, _get_nested(context, "final_response")]:
            source_dict = _as_dict(source)
            if not source_dict:
                continue
            candidate = source_dict.get("rows")
            if isinstance(candidate, list):
                return [_json_safe_dict(r) for r in candidate if isinstance(r, Mapping)]
            candidate = source_dict.get("data")
            if isinstance(candidate, list):
                return [_json_safe_dict(r) for r in candidate if isinstance(r, Mapping)]
            if isinstance(candidate, Mapping) and isinstance(candidate.get("rows"), list):
                return [_json_safe_dict(r) for r in candidate.get("rows") if isinstance(r, Mapping)]
        return []

    def _extract_embedded_status(self, rows: list[JsonDict]) -> str | None:
        if len(rows) == 1 and "status" in rows[0]:
            return _normalize_status(rows[0].get("status"))
        return None

    def _sanitize_rows(self, rows: list[JsonDict]) -> tuple[list[JsonDict], list[str]]:
        safe_rows: list[JsonDict] = []
        warnings: list[str] = []
        for row in rows:
            safe_row: JsonDict = {}
            for key, value in row.items():
                if self._is_sensitive_column(key):
                    warnings.append(f"ستون {key} به دلیل حساسیت از توضیح حذف شد.")
                    continue
                # employee_id may be safe as aggregate count only, but not as visible output.
                if key == "employee_id":
                    warnings.append("ستون employee_id از توضیح خروجی حذف شد.")
                    continue
                safe_row[key] = _json_safe(value)
            if safe_row:
                safe_rows.append(safe_row)
        return safe_rows, _dedupe(warnings)

    def _is_sensitive_column(self, column: str) -> bool:
        lower = str(column).lower()
        for pattern in SENSITIVE_COLUMN_PATTERNS:
            if re.search(pattern, lower):
                return True
        return False

    def _classify_columns(self, columns: list[str], rows: list[JsonDict]) -> tuple[list[str], list[str]]:
        dimension_columns: list[str] = []
        metric_columns: list[str] = []
        for col in columns:
            lower = col.lower()
            if lower in DIMENSION_HINTS:
                dimension_columns.append(col)
                continue
            if lower in METRIC_HINTS or self._looks_numeric_column(rows, col):
                metric_columns.append(col)
                continue
            # Low-cardinality strings are usually dimensions.
            values = [r.get(col) for r in rows if r.get(col) is not None]
            if values and all(not _is_number_like(v) for v in values):
                dimension_columns.append(col)
            elif values:
                metric_columns.append(col)
        return dimension_columns, metric_columns

    def _looks_numeric_column(self, rows: list[JsonDict], col: str) -> bool:
        values = [r.get(col) for r in rows if r.get(col) is not None]
        if not values:
            return False
        return sum(1 for v in values if _is_number_like(v)) >= max(1, int(len(values) * 0.8))

    def _select_primary_metric(self, metric_columns: list[str], row: Mapping[str, Any]) -> str | None:
        priority = [
            "employee_count",
            "actual_headcount",
            "headcount_gap",
            "contractor_percentage",
            "percentage",
            "average_age",
            "average_service_years",
            "hire_count",
            "hiring_count",
            "count",
        ]
        for key in priority:
            if key in metric_columns and key in row:
                return key
        return metric_columns[0] if metric_columns else None

    def _select_primary_dimension(self, dimension_columns: list[str]) -> str | None:
        priority = [
            "hire_year",
            "service_domain",
            "department_name",
            "province",
            "gender",
            "age_group_title",
            "education_title",
            "employment_type",
            "contract_type",
            "site_name",
        ]
        for key in priority:
            if key in dimension_columns:
                return key
        return dimension_columns[0] if dimension_columns else None

    def _find_percentage_metric(self, metric_columns: list[str]) -> str | None:
        for col in metric_columns:
            if "percentage" in col.lower() or col.lower() in {"percent", "share"}:
                return col
        return None

    # ------------------------------------------------------------------
    # Row comparison helpers
    # ------------------------------------------------------------------

    def _max_row(self, rows: list[JsonDict], metric: str) -> JsonDict | None:
        candidates = [(self._to_number(row.get(metric)), row) for row in rows]
        candidates = [(num, row) for num, row in candidates if num is not None]
        if not candidates:
            return None
        return max(candidates, key=lambda x: x[0])[1]

    def _min_row(self, rows: list[JsonDict], metric: str) -> JsonDict | None:
        candidates = [(self._to_number(row.get(metric)), row) for row in rows]
        candidates = [(num, row) for num, row in candidates if num is not None]
        if not candidates:
            return None
        return min(candidates, key=lambda x: x[0])[1]

    def _trend_sentence(self, *, rows: list[JsonDict], x_col: str, y_col: str) -> str | None:
        sorted_rows = sorted(rows, key=lambda row: self._sort_key(row.get(x_col)))
        if len(sorted_rows) < 2:
            return None
        first = self._to_number(sorted_rows[0].get(y_col))
        last = self._to_number(sorted_rows[-1].get(y_col))
        if first is None or last is None:
            return None
        first_x = self._format_dimension_value(sorted_rows[0].get(x_col), x_col)
        last_x = self._format_dimension_value(sorted_rows[-1].get(x_col), x_col)
        if last > first:
            direction = "افزایش"
        elif last < first:
            direction = "کاهش"
        else:
            direction = "ثبات نسبی"
        return f"از {first_x} تا {last_x} مقدار {self._label(y_col)} از {self._format_value(first, y_col)} به {self._format_value(last, y_col)} رسیده و الگوی کلی آن {direction} است."

    def _sort_key(self, value: Any) -> tuple[int, Any]:
        num = self._to_number(value)
        if num is not None:
            return (0, num)
        return (1, str(value))

    def _is_time_dimension(self, col: str) -> bool:
        return col in {"hire_year", "year", "month", "date"} or col.endswith("_year")

    # ------------------------------------------------------------------
    # Formatting
    # ------------------------------------------------------------------

    def _label(self, column: str) -> str:
        return FA_LABELS.get(column, column)

    def _format_value(self, value: Any, column: str | None = None) -> str:
        if value is None:
            return "نامشخص"
        if isinstance(value, bool):
            return "بله" if value else "خیر"
        num = self._to_number(value)
        col = (column or "").lower()
        if num is not None:
            if "percentage" in col or col in {"percent", "share"}:
                return f"{_format_number(num)}٪"
            if "average" in col or "avg" in col:
                return _format_number(num, decimals=2)
            return _format_number(num, decimals=0 if float(num).is_integer() else 2)
        return str(value)

    def _format_dimension_value(self, value: Any, column: str | None = None) -> str:
        if value is None or value == "":
            return "نامشخص"
        if isinstance(value, bool):
            if column == "is_contractor":
                return "پیمانکاری" if value else "غیرپیمانکاری"
            return "بله" if value else "خیر"
        return str(value)

    def _to_number(self, value: Any) -> float | None:
        if value is None or isinstance(value, bool):
            return None
        if isinstance(value, (int, float)) and not isinstance(value, bool):
            if math.isnan(value) or math.isinf(value):
                return None
            return float(value)
        if isinstance(value, Decimal):
            return float(value)
        if isinstance(value, str):
            text = _normalize_digits(value).replace(",", "").strip()
            try:
                return float(text)
            except Exception:
                return None
        return None


# ---------------------------------------------------------------------------
# Generic helpers
# ---------------------------------------------------------------------------


def _to_mapping(obj: Any) -> JsonDict:
    if obj is None:
        return {}
    if isinstance(obj, Mapping):
        return dict(obj)
    if is_dataclass(obj):
        return asdict(obj)
    if hasattr(obj, "to_dict"):
        with _suppress_exceptions():
            result = obj.to_dict()
            if isinstance(result, Mapping):
                return dict(result)
    if hasattr(obj, "__dict__"):
        return dict(vars(obj))
    return {}


def _as_dict(value: Any) -> JsonDict:
    if isinstance(value, Mapping):
        return dict(value)
    return _to_mapping(value)


def _as_list(value: Any) -> list[Any]:
    if value is None:
        return []
    if isinstance(value, list):
        return value
    if isinstance(value, tuple):
        return list(value)
    if isinstance(value, set):
        return list(value)
    return [value]


def _get_nested(obj: Any, *keys: str) -> Any:
    cur = obj
    for key in keys:
        if cur is None:
            return None
        if is_dataclass(cur):
            cur = asdict(cur)
        if isinstance(cur, Mapping):
            cur = cur.get(key)
        else:
            cur = getattr(cur, key, None)
    return cur


def _json_safe(value: Any) -> Any:
    if isinstance(value, Decimal):
        return float(value)
    if isinstance(value, (datetime, date)):
        return value.isoformat()
    if isinstance(value, Mapping):
        return {str(k): _json_safe(v) for k, v in value.items()}
    if isinstance(value, (list, tuple, set)):
        return [_json_safe(v) for v in value]
    return value


def _json_safe_dict(row: Mapping[str, Any]) -> JsonDict:
    return {str(k): _json_safe(v) for k, v in row.items()}


def _normalize_route(route: Any) -> str:
    value = str(route or "").strip().upper()
    if value in {ROUTE_SQL, ROUTE_GAP, ROUTE_REJECT, ROUTE_NEEDS_CLARIFICATION}:
        return value
    if value in {STATUS_DATA_GAP}:
        return ROUTE_GAP
    if value in {STATUS_ACCESS_DENIED, STATUS_OUT_OF_SCOPE, "REJECTED"}:
        return ROUTE_REJECT
    if value in {STATUS_NEEDS_CLARIFICATION, "CLARIFY"}:
        return ROUTE_NEEDS_CLARIFICATION
    return ROUTE_SQL


def _normalize_status(status: Any) -> str:
    value = str(status or "").strip().upper()
    aliases = {
        "SUPPORTED": STATUS_SUCCESS,
        "VALID": STATUS_SUCCESS,
        "OK": STATUS_SUCCESS,
        "DONE": STATUS_SUCCESS,
        "FAILED": STATUS_EXECUTION_FAILED,
        "ERROR": STATUS_EXECUTION_FAILED,
        "REJECTED": STATUS_ACCESS_DENIED,
        "CLARIFICATION": STATUS_NEEDS_CLARIFICATION,
        "CLARIFY": STATUS_NEEDS_CLARIFICATION,
    }
    return aliases.get(value, value or STATUS_SUCCESS)


def _route_for_status(status: str) -> str:
    status = _normalize_status(status)
    if status == STATUS_DATA_GAP:
        return ROUTE_GAP
    if status in {STATUS_ACCESS_DENIED, STATUS_OUT_OF_SCOPE}:
        return ROUTE_REJECT
    if status == STATUS_NEEDS_CLARIFICATION:
        return ROUTE_NEEDS_CLARIFICATION
    return ROUTE_SQL


def _is_number_like(value: Any) -> bool:
    if value is None or isinstance(value, bool):
        return False
    if isinstance(value, (int, float, Decimal)):
        return not (isinstance(value, float) and (math.isnan(value) or math.isinf(value)))
    if isinstance(value, str):
        try:
            float(_normalize_digits(value).replace(",", "").strip())
            return True
        except Exception:
            return False
    return False


def _format_number(value: float | int, *, decimals: int = 2) -> str:
    try:
        num = float(value)
    except Exception:
        return str(value)
    if decimals == 0:
        return f"{int(round(num)):,}"
    formatted = f"{num:,.{decimals}f}"
    if "." in formatted:
        formatted = formatted.rstrip("0").rstrip(".")
    return formatted


def _normalize_digits(text: str) -> str:
    return str(text).translate(str.maketrans("۰۱۲۳۴۵۶۷۸۹٠١٢٣٤٥٦٧٨٩", "01234567890123456789"))


def _clean_text(text: str) -> str:
    return re.sub(r"\s+", " ", str(text or "")).strip()


def _dedupe(items: Sequence[Any]) -> list[Any]:
    seen: set[str] = set()
    result: list[Any] = []
    for item in items:
        key = str(item)
        if key in seen:
            continue
        seen.add(key)
        result.append(item)
    return result


class _suppress_exceptions:
    def __enter__(self) -> None:
        return None

    def __exit__(self, exc_type: Any, exc: Any, tb: Any) -> bool:
        return True


# Convenience singleton, similar to other project services.
_DEFAULT_GENERATOR: ExplanationGenerator | None = None


def get_explanation_generator(
    *,
    reload: bool = False,
    metadata_service: Any | None = None,
    metadata_dir: str | Path | None = None,
    **kwargs: Any,
) -> ExplanationGenerator:
    global _DEFAULT_GENERATOR
    if reload or _DEFAULT_GENERATOR is None or metadata_service is not None or metadata_dir is not None or kwargs:
        _DEFAULT_GENERATOR = ExplanationGenerator(
            metadata_service=metadata_service,
            metadata_dir=metadata_dir,
            **kwargs,
        )
    return _DEFAULT_GENERATOR


if __name__ == "__main__":  # pragma: no cover - local smoke test
    generator = ExplanationGenerator(metadata_dir=Path(__file__).resolve().parent)
    sample = generator.generate(
        question="تعداد زن و مرد چند نفر است؟",
        intent_id="employee_count_by_gender",
        rows=[
            {"gender": "مرد", "employee_count": 645, "percentage": 86.0},
            {"gender": "زن", "employee_count": 105, "percentage": 14.0},
        ],
    )
    import json

    print(json.dumps(sample, ensure_ascii=False, indent=2))
