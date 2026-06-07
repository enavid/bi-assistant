from __future__ import annotations
import math
from copy import deepcopy
from dataclasses import asdict, dataclass, field, is_dataclass
from datetime import date, datetime, timezone
from decimal import Decimal
from pathlib import Path
from typing import Any, Mapping, Sequence


from app.infrastructure.metadata.service import get_metadata_service

"""
response_builder.py
-------------------
Final response builder for HR BI Assistant Phase 2: Controlled SQL-based MVP.


Responsibility:
    - Convert SQL / GAP / REJECT / validation outputs into a stable final answer payload.
    - Select a safe visualization plan using visualization_rules.yaml and runtime result shape.
    - Apply presentation-time privacy controls such as hiding sensitive columns and suppressing
      very small groups.
    - Return a frontend-friendly object while staying compatible with llm_orchestrator.py.

Design rules:
    - Never fabricate data.
    - Never expose individual employee-level data.
    - Never display sensitive identifiers.
    - For GAP / REJECT / errors, return a status message instead of a chart/table.
    - For SQL success, return sanitized data + visualization plan.
"""



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

SAFE_SUCCESS_STATUSES = {STATUS_SUCCESS,
                         STATUS_VALID, STATUS_SUPPORTED, "OK", "DONE"}

DEFAULT_STATUS_TEMPLATES: dict[str, JsonDict] = {
    STATUS_DATA_GAP: {
        "title_fa": "داده کافی نیست",
        "message_fa": "این سؤال مرتبط با منابع انسانی است، اما در نسخه فعلی داده، قانون یا سند کافی برای پاسخ دقیق وجود ندارد.",
        "severity": "warning",
        "recommended_action_fa": "این مورد باید به‌عنوان Data Gap یا Knowledge Gap ثبت شود.",
    },
    STATUS_ACCESS_DENIED: {
        "title_fa": "امکان نمایش اطلاعات وجود ندارد",
        "message_fa": "درخواست شامل اطلاعات فردی یا حساس کارکنان است و طبق سیاست محرمانگی قابل نمایش نیست.",
        "severity": "error",
        "recommended_action_fa": "می‌توان سؤال را به شکل تجمیعی و آماری بازنویسی کرد.",
    },
    STATUS_OUT_OF_SCOPE: {
        "title_fa": "خارج از دامنه منابع انسانی",
        "message_fa": "این سؤال در دامنه HR BI Assistant نیست و نباید برای آن SQL منابع انسانی تولید شود.",
        "severity": "info",
        "recommended_action_fa": "سؤال باید به حوزه منابع انسانی، کارکنان، استخدام، قرارداد، تحصیلات، سن، جذب یا ساختار سازمانی مربوط باشد.",
    },
    STATUS_NEEDS_CLARIFICATION: {
        "title_fa": "نیاز به شفاف‌سازی سؤال",
        "message_fa": "سؤال قابل بررسی است، اما برای انتخاب شاخص، بازه یا سطح تحلیل نیاز به توضیح بیشتر دارد.",
        "severity": "info",
        "recommended_action_fa": "لطفاً سؤال را کمی دقیق‌تر بپرسید؛ مثلاً سطح تحلیل، بازه زمانی یا شاخص موردنظر را مشخص کنید.",
    },
    STATUS_SQL_VALIDATION_FAILED: {
        "title_fa": "SQL معتبر نیست",
        "message_fa": "کوئری تولیدشده با قوانین امنیتی یا ساختاری فاز دوم سازگار نیست و اجرا نمی‌شود.",
        "severity": "error",
        "recommended_action_fa": "کوئری باید لاگ و اصلاح شود و فقط از View امن استفاده کند.",
    },
    STATUS_EXECUTION_FAILED: {
        "title_fa": "خطا در اجرای کوئری",
        "message_fa": "کوئری معتبر بود، اما هنگام اجرا روی دیتابیس خطا رخ داد.",
        "severity": "error",
        "recommended_action_fa": "لاگ دیتابیس و اتصال سرویس بررسی شود.",
    },
    STATUS_NO_DATA: {
        "title_fa": "داده‌ای یافت نشد",
        "message_fa": "برای فیلترهای انتخاب‌شده، رکورد قابل نمایش وجود ندارد.",
        "severity": "info",
        "recommended_action_fa": "می‌توان بازه یا فیلتر سؤال را تغییر داد.",
    },
    STATUS_NOT_EXECUTED: {
        "title_fa": "کوئری اجرا نشد",
        "message_fa": "به دلیل تنظیمات اجرا یا وضعیت اعتبارسنجی، کوئری روی دیتابیس اجرا نشد.",
        "severity": "warning",
        "recommended_action_fa": "در صورت نیاز، اجرای SQL را فعال و اتصال دیتابیس را بررسی کنید.",
    },
}

DEFAULT_SENSITIVE_COLUMNS = {
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
    "personal_identifier",
    "salary",
    "wage",
    "birth_date",  # should not be exposed at row level
    "hire_date",  # should not be exposed at row level
    "contract_start_date",
    "contract_end_date",
}

IDENTIFIER_COLUMNS = {
    "employee_id",
    "department_id",
    "location_id",
    "position_id",
    "parent_department_id",
}

COMMON_METRIC_NAMES = {
    "employee_count",
    "count",
    "total_count",
    "total_employees",
    "actual_headcount",
    "approved_headcount",
    "department_approved_headcount",
    "headcount_gap",
    "percentage",
    "share_percentage",
    "contractor_percentage",
    "contractor_count",
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
    "average_age": "میانگین سن",
    "average_service_years": "میانگین سابقه",
    "hire_count": "تعداد جذب",
    "hiring_count": "تعداد جذب",
    "gender": "جنسیت",
    "marital_status": "وضعیت تأهل",
    "age_group_title": "گروه سنی",
    "education_title": "مدرک تحصیلی",
    "education_category": "گروه تحصیلی",
    "employment_type": "نوع استخدام",
    "contract_type": "نوع قرارداد",
    "is_contractor": "وضعیت پیمانکاری",
    "service_domain": "حوزه خدمت",
    "department_name": "واحد/دپارتمان",
    "province": "استان",
    "site_name": "محل خدمت",
    "position_title": "پست",
    "position_level": "سطح پست",
    "job_family": "خانواده شغلی",
    "hire_year": "سال جذب",
    "status": "وضعیت",
}


@dataclass
class ResponseBuilderConfig:
    """Configuration for ResponseBuilder."""

    source_name: str = "response_builder"
    locale: str = "fa-IR"
    direction: str = "rtl"
    min_group_size_default: int = 5
    suppress_small_groups: bool = True
    suppress_label_fa: str = "غیرقابل نمایش"
    no_data_status: str = STATUS_NO_DATA
    max_table_rows: int = 50
    max_chart_rows: int = 20
    include_sql: bool = True
    include_debug_metadata: bool = False
    default_title_fa: str = "نتیجه تحلیل منابع انسانی"


@dataclass
class ResponsePayload:
    """Standard output shape consumed by llm_orchestrator.py."""

    route: str
    status: str
    message_fa: str
    detected_intent: str | None = None
    generated_sql: str | None = None
    data: list[JsonDict] = field(default_factory=list)
    visualization: JsonDict = field(default_factory=dict)
    title_fa: str | None = None
    subtitle_fa: str | None = None
    notes_fa: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)
    metadata: JsonDict = field(default_factory=dict)

    def to_dict(self) -> JsonDict:
        return asdict(self)


class ResponseBuilder:
    """
    Build a final answer from orchestrator context and status payload.

    Public methods intentionally mirror the rest of the Phase 2 services:
        build(...)
        build_response(...)
        run(...)
        arun(...)
        __call__(...)
    """

    def __init__(
        self,
        *,
        metadata_service: Any | None = None,
        metadata_dir: str | Path | None = None,
        min_group_size: int | None = None,
        max_table_rows: int = 50,
        max_chart_rows: int = 20,
        suppress_small_groups: bool = True,
        include_sql: bool = True,
        include_debug_metadata: bool = False,
    ) -> None:
        if metadata_service is not None:
            self.metadata = metadata_service
        elif get_metadata_service is not None:
            self.metadata = get_metadata_service(
                metadata_dir=metadata_dir, strict=False)
        else:
            self.metadata = None

        configured_min_group_size = min_group_size
        if configured_min_group_size is None and self.metadata is not None:
            with _suppress_exceptions():
                configured_min_group_size = int(self.metadata.get_min_group_size(
                    default=ResponseBuilderConfig.min_group_size_default))

        self.config = ResponseBuilderConfig(
            min_group_size_default=int(
                configured_min_group_size or ResponseBuilderConfig.min_group_size_default),
            max_table_rows=int(max_table_rows),
            max_chart_rows=int(max_chart_rows),
            suppress_small_groups=bool(suppress_small_groups),
            include_sql=bool(include_sql),
            include_debug_metadata=bool(include_debug_metadata),
        )

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def build(
        self,
        *,
        context: Any | None = None,
        status_payload: Mapping[str, Any] | None = None,
        metadata: Any | None = None,
        query_result: Mapping[str, Any] | None = None,
        **kwargs: Any,
    ) -> JsonDict:
        """Build final response synchronously."""
        md = metadata or self.metadata
        ctx = _to_mapping(context)
        status_payload_dict = dict(status_payload or {})
        if query_result is not None:
            ctx.setdefault("query_result", dict(query_result))

        return self._build_response(context=ctx, status_payload=status_payload_dict, metadata=md, **kwargs).to_dict()

    def build_response(self, **kwargs: Any) -> JsonDict:
        return self.build(**kwargs)

    def run(self, **kwargs: Any) -> JsonDict:
        return self.build(**kwargs)

    async def arun(self, **kwargs: Any) -> JsonDict:
        return self.build(**kwargs)

    def __call__(self, **kwargs: Any) -> JsonDict:
        return self.build(**kwargs)

    # ------------------------------------------------------------------
    # Core builder
    # ------------------------------------------------------------------

    def _build_response(self, *, context: JsonDict, status_payload: JsonDict, metadata: Any | None, **_: Any) -> ResponsePayload:
        route = self._resolve_route(context, status_payload)
        status = self._resolve_status(context, status_payload)
        intent_id = self._resolve_intent_id(context, status_payload)
        report_id = self._resolve_report_id(context, status_payload)
        generated_sql = self._resolve_sql(context, status_payload)

        query_result = _as_dict(context.get("query_result"))
        rows = self._extract_rows(query_result)

        # Status SQL such as SELECT 'DATA_GAP' AS status; may show up as a normal row.
        embedded_status = self._extract_embedded_status(rows)
        if embedded_status in NON_DATA_STATUSES:
            status = embedded_status
            route = _route_for_status(status)

        if status in {STATUS_VALID, STATUS_SUPPORTED, "OK", "DONE"} and route == ROUTE_SQL:
            status = STATUS_SUCCESS

        if route != ROUTE_SQL or status in NON_DATA_STATUSES:
            return self._build_status_response(
                status=status,
                route=route,
                context=context,
                status_payload=status_payload,
                metadata=metadata,
                intent_id=intent_id,
                report_id=report_id,
                generated_sql=generated_sql,
            )

        if not rows:
            return self._build_status_response(
                status=STATUS_NO_DATA,
                route=ROUTE_SQL,
                context=context,
                status_payload=status_payload,
                metadata=metadata,
                intent_id=intent_id,
                report_id=report_id,
                generated_sql=generated_sql,
            )

        sanitized_rows, privacy_warnings = self._sanitize_rows(
            rows, metadata=metadata)
        if not sanitized_rows:
            return self._build_status_response(
                status=STATUS_ACCESS_DENIED,
                route=ROUTE_REJECT,
                context=context,
                status_payload={
                    **status_payload, "reason": "All result columns were blocked by output privacy rules."},
                metadata=metadata,
                intent_id=intent_id,
                report_id=report_id,
                generated_sql=generated_sql,
            )

        columns = list(sanitized_rows[0].keys()) if sanitized_rows else []
        dimension_columns, metric_columns = self._classify_columns(
            columns, sanitized_rows, metadata=metadata)
        safe_rows, suppression_warnings = self._apply_small_group_suppression(
            sanitized_rows,
            dimension_columns=dimension_columns,
            metric_columns=metric_columns,
        )

        if not safe_rows:
            return self._build_status_response(
                status=STATUS_NO_DATA,
                route=ROUTE_SQL,
                context=context,
                status_payload=status_payload,
                metadata=metadata,
                intent_id=intent_id,
                report_id=report_id,
                generated_sql=generated_sql,
            )

        title_fa = self._resolve_title_fa(
            intent_id=intent_id, report_id=report_id, metadata=metadata)
        visualization = self._build_visualization_plan(
            rows=safe_rows,
            dimension_columns=dimension_columns,
            metric_columns=metric_columns,
            intent_id=intent_id,
            report_id=report_id,
            title_fa=title_fa,
            context=context,
            metadata=metadata,
        )

        message_fa = self._build_success_message(
            rows=safe_rows,
            visualization=visualization,
            title_fa=title_fa,
            dimension_columns=dimension_columns,
            metric_columns=metric_columns,
        )

        notes = self._build_notes(context=context, status_payload=status_payload,
                                  visualization=visualization, metadata=metadata)
        warnings = self._collect_warnings(
            context, status_payload, query_result)
        warnings.extend(privacy_warnings)
        warnings.extend(suppression_warnings)

        return ResponsePayload(
            route=ROUTE_SQL,
            status=STATUS_SUCCESS,
            message_fa=message_fa,
            detected_intent=intent_id,
            generated_sql=generated_sql if self.config.include_sql else None,
            data=safe_rows,
            visualization=visualization,
            title_fa=title_fa,
            subtitle_fa=visualization.get("subtitle_fa"),
            notes_fa=notes,
            warnings=_dedupe(warnings),
            errors=self._collect_errors(context, status_payload, query_result),
            metadata=self._response_metadata(
                context=context,
                intent_id=intent_id,
                report_id=report_id,
                rows=safe_rows,
                dimension_columns=dimension_columns,
                metric_columns=metric_columns,
                visualization=visualization,
            ),
        )

    # ------------------------------------------------------------------
    # Status responses
    # ------------------------------------------------------------------

    def _build_status_response(
        self,
        *,
        status: str,
        route: str,
        context: JsonDict,
        status_payload: JsonDict,
        metadata: Any | None,
        intent_id: str | None,
        report_id: str | None,
        generated_sql: str | None,
    ) -> ResponsePayload:
        normalized_status = (status or STATUS_SQL_VALIDATION_FAILED).upper()
        normalized_route = (route or _route_for_status(
            normalized_status)).upper()
        template = self._get_status_template(
            normalized_status, metadata=metadata)

        title = self._first_non_empty(
            status_payload.get("title_fa"),
            _get_nested(context, "gap_result", "title_fa"),
            template.get("title_fa"),
            DEFAULT_STATUS_TEMPLATES.get(
                normalized_status, {}).get("title_fa"),
            "وضعیت پاسخ",
        )
        reason = self._first_non_empty(
            status_payload.get("reason_fa"),
            status_payload.get("reason"),
            status_payload.get("message_fa"),
            _get_nested(context, "gap_result", "reason_fa"),
            _get_nested(context, "gap_result", "reason"),
            _get_nested(context, "validation_result", "reason_fa"),
            _get_nested(context, "validation_result", "reason"),
            _get_nested(context, "route_result", "reason_fa"),
            _get_nested(context, "route_result", "reason"),
            template.get("message_fa"),
            DEFAULT_STATUS_TEMPLATES.get(
                normalized_status, {}).get("message_fa"),
            "پاسخ امن تولید شد.",
        )
        recommended_action = self._first_non_empty(
            status_payload.get("recommended_action_fa"),
            _get_nested(context, "gap_result", "required_action"),
            _get_nested(context, "gap_result", "suggested_next_step"),
            template.get("recommended_action_fa"),
            DEFAULT_STATUS_TEMPLATES.get(
                normalized_status, {}).get("recommended_action_fa"),
        )

        fa_template_message = DEFAULT_STATUS_TEMPLATES.get(
            normalized_status, {}).get("message_fa", "")
        message = fa_template_message or str(reason)
        if recommended_action and normalized_status in {STATUS_DATA_GAP, STATUS_ACCESS_DENIED, STATUS_OUT_OF_SCOPE, STATUS_NEEDS_CLARIFICATION}:
            message = f"{message} {recommended_action}" if not fa_template_message else message

        visualization = {
            "visualization_type": "status_message",
            "type": "status_message",
            "title_fa": str(title),
            "subtitle_fa": None,
            "status": normalized_status,
            "route": normalized_route,
            "severity": template.get("severity") or DEFAULT_STATUS_TEMPLATES.get(normalized_status, {}).get("severity", "info"),
            "message_fa": DEFAULT_STATUS_TEMPLATES.get(normalized_status, {}).get("message_fa") or str(reason),
            "recommended_action_fa": str(recommended_action) if recommended_action else None,
            "dimension_columns": [],
            "metric_columns": [],
            "data": [],
        }

        notes = []
        if normalized_status == STATUS_DATA_GAP:
            missing_data = _get_nested(
                context, "gap_result", "missing_data") or status_payload.get("missing_data")
            if isinstance(missing_data, list) and missing_data:
                notes.append("داده/تعریف موردنیاز: " + "، ".join(str(x)
                             for x in missing_data[:5]))
        if normalized_status == STATUS_ACCESS_DENIED:
            notes.append(
                "خروجی فردی یا شناسه‌های حساس کارکنان نمایش داده نمی‌شود.")

        return ResponsePayload(
            route=normalized_route,
            status=normalized_status,
            message_fa=message,
            detected_intent=intent_id,
            generated_sql=generated_sql if self.config.include_sql else None,
            data=[],
            visualization=visualization,
            title_fa=str(title),
            subtitle_fa=None,
            notes_fa=notes,
            warnings=self._collect_warnings(
                context, status_payload, _as_dict(context.get("query_result"))),
            errors=self._collect_errors(
                context, status_payload, _as_dict(context.get("query_result"))),
            metadata=self._response_metadata(
                context=context,
                intent_id=intent_id,
                report_id=report_id,
                rows=[],
                dimension_columns=[],
                metric_columns=[],
                visualization=visualization,
            ),
        )

    def _get_status_template(self, status: str, *, metadata: Any | None) -> JsonDict:
        status = status.upper()
        if metadata is not None:
            with _suppress_exceptions():
                rules = metadata.get_document("visualization_rules")
                templates = rules.get("status_message_templates", {}) if isinstance(
                    rules, Mapping) else {}
                template = templates.get(status)
                if isinstance(template, Mapping):
                    return dict(template)
        return deepcopy(DEFAULT_STATUS_TEMPLATES.get(status, DEFAULT_STATUS_TEMPLATES[STATUS_SQL_VALIDATION_FAILED]))

    # ------------------------------------------------------------------
    # Visualization plan
    # ------------------------------------------------------------------

    def _build_visualization_plan(
        self,
        *,
        rows: list[JsonDict],
        dimension_columns: list[str],
        metric_columns: list[str],
        intent_id: str | None,
        report_id: str | None,
        title_fa: str,
        context: JsonDict,
        metadata: Any | None,
    ) -> JsonDict:
        metadata_visual = self._get_metadata_visualization(
            intent_id=intent_id, report_id=report_id, metadata=metadata)
        requested_type = self._first_non_empty(
            _get_nested(context, "visualization_plan", "visualization_type"),
            _get_nested(context, "visualization_plan", "type"),
            metadata_visual.get("primary_visualization"),
            metadata_visual.get("visualization_type"),
            metadata_visual.get("type"),
        )

        visual_type = self._select_visualization_type(
            requested_type=str(requested_type) if requested_type else None,
            rows=rows,
            dimension_columns=dimension_columns,
            metric_columns=metric_columns,
            metadata_visual=metadata_visual,
        )

        max_rows = self.config.max_chart_rows if visual_type not in {
            "table", "kpi_card", "kpi_card_group"} else self.config.max_table_rows
        visible_rows = rows[:max_rows]
        truncated = len(rows) > len(visible_rows)

        x_axis = dimension_columns[0] if dimension_columns else None
        y_axis = metric_columns[0] if metric_columns else None
        series = metric_columns[:]

        if visual_type in {"kpi_card", "kpi_card_group"}:
            cards = self._build_kpi_cards(visible_rows, metric_columns)
        else:
            cards = []

        return {
            "visualization_type": visual_type,
            "type": visual_type,
            "title_fa": title_fa,
            "subtitle_fa": self._visualization_subtitle(visual_type, rows, dimension_columns),
            "dimension_columns": dimension_columns,
            "metric_columns": metric_columns,
            "x_axis": x_axis,
            "y_axis": y_axis,
            "series": series,
            "data": visible_rows,
            "cards": cards,
            "row_count": len(rows),
            "visible_row_count": len(visible_rows),
            "truncated": truncated,
            "formatting": self._formatting_for_columns(metric_columns),
            "labels_fa": {col: self._label_for_column(col, metadata=metadata) for col in [*dimension_columns, *metric_columns]},
            "options": {
                "rtl": True,
                "locale": self.config.locale,
                "max_rows": max_rows,
                "show_sql": False,
                "suppress_small_groups": self.config.suppress_small_groups,
            },
        }

    def _get_metadata_visualization(self, *, intent_id: str | None, report_id: str | None, metadata: Any | None) -> JsonDict:
        if metadata is None:
            return {}
        if report_id:
            with _suppress_exceptions():
                visual = metadata.get_visualization_for_report(report_id)
                if isinstance(visual, Mapping) and visual:
                    return dict(visual)
        if intent_id:
            with _suppress_exceptions():
                visual = metadata.get_visualization_for_intent(intent_id)
                if isinstance(visual, Mapping) and visual:
                    return dict(visual)
        return {}

    def _select_visualization_type(
        self,
        *,
        requested_type: str | None,
        rows: list[JsonDict],
        dimension_columns: list[str],
        metric_columns: list[str],
        metadata_visual: JsonDict,
    ) -> str:
        requested = _normalize_visual_type(requested_type)
        row_count = len(rows)
        dimension_count = len(dimension_columns)
        metric_count = len(metric_columns)

        # Shape-first safeguards.
        if row_count == 0:
            return "status_message"
        if row_count == 1 and dimension_count == 0 and metric_count <= 1:
            return "kpi_card"
        if row_count == 1 and metric_count > 1:
            return "kpi_card_group"
        if not metric_columns:
            return "table"

        if requested in {"kpi_card", "kpi_card_group"} and row_count > 1:
            requested = metadata_visual.get(
                "fallback_visualization") or "table"
            requested = _normalize_visual_type(str(requested))

        if requested in {"pie_chart", "bar_chart", "horizontal_bar_chart", "line_chart", "stacked_bar_chart", "table"}:
            if requested == "pie_chart" and (row_count > 8 or not dimension_columns):
                return "bar_chart" if row_count <= 5 else "horizontal_bar_chart"
            if requested in {"bar_chart", "pie_chart"} and row_count >= 6:
                return "horizontal_bar_chart"
            return requested

        # Automatic selection.
        if dimension_columns:
            first_dim = dimension_columns[0]
            if first_dim == "hire_year":
                return "line_chart"
            if row_count <= 5 and any(m in metric_columns for m in ["percentage", "share_percentage"]):
                return "pie_chart"
            if row_count >= 6:
                return "horizontal_bar_chart"
            return "bar_chart"

        return "table"

    def _build_kpi_cards(self, rows: list[JsonDict], metric_columns: list[str]) -> list[JsonDict]:
        if not rows:
            return []
        row = rows[0]
        cards: list[JsonDict] = []
        for column in metric_columns:
            if column not in row:
                continue
            cards.append(
                {
                    "key": column,
                    "title_fa": self._label_for_column(column, metadata=None),
                    "value": row.get(column),
                    "formatted_value": self._format_value(column, row.get(column)),
                    "format": self._format_name_for_column(column),
                }
            )
        return cards

    def _visualization_subtitle(self, visual_type: str, rows: list[JsonDict], dimension_columns: list[str]) -> str | None:
        if visual_type == "kpi_card":
            return "محاسبه‌شده بر اساس View تحلیلی کارکنان فعال"
        if visual_type in {"bar_chart", "horizontal_bar_chart", "pie_chart", "line_chart", "stacked_bar_chart"} and dimension_columns:
            return f"نمایش بر اساس {FA_LABELS.get(dimension_columns[0], dimension_columns[0])}"
        if visual_type == "table":
            return f"{len(rows)} ردیف قابل نمایش"
        return None

    # ------------------------------------------------------------------
    # Data shaping and privacy
    # ------------------------------------------------------------------

    def _sanitize_rows(self, rows: list[JsonDict], *, metadata: Any | None) -> tuple[list[JsonDict], list[str]]:
        sensitive = set(DEFAULT_SENSITIVE_COLUMNS)
        if metadata is not None:
            with _suppress_exceptions():
                sensitive.update(str(col)
                                 for col in metadata.get_sensitive_columns())

        allowed_output_columns: set[str] | None = None
        if metadata is not None:
            with _suppress_exceptions():
                allowed_output_columns = set(
                    str(col) for col in metadata.get_allowed_output_columns())

        warnings: list[str] = []
        sanitized: list[JsonDict] = []
        dropped_columns: set[str] = set()

        for row in rows:
            clean_row: JsonDict = {}
            for key, value in row.items():
                col = str(key)
                lower_col = col.lower()
                if lower_col in sensitive:
                    dropped_columns.add(col)
                    continue
                if lower_col in IDENTIFIER_COLUMNS and lower_col != "hire_year":
                    # employee_id/department_id are useful internally but should not be rendered.
                    dropped_columns.add(col)
                    continue
                if allowed_output_columns is not None and col not in allowed_output_columns and not self._is_metric_column_name(col):
                    # Keep calculated metrics even if they are not in data_dictionary.
                    if lower_col not in DIMENSION_HINTS:
                        dropped_columns.add(col)
                        continue
                clean_row[col] = _json_safe(value)
            if clean_row:
                sanitized.append(clean_row)

        if dropped_columns:
            warnings.append(
                "Some restricted or internal columns were removed from the response: " + ", ".join(sorted(dropped_columns)))
        return sanitized, warnings

    def _apply_small_group_suppression(
        self,
        rows: list[JsonDict],
        *,
        dimension_columns: list[str],
        metric_columns: list[str],
    ) -> tuple[list[JsonDict], list[str]]:
        if not self.config.suppress_small_groups:
            return rows, []

        count_column = self._find_count_column(metric_columns, rows)
        if not count_column:
            return rows, []

        min_group_size = self.config.min_group_size_default
        suppressed = 0
        result: list[JsonDict] = []
        for row in rows:
            count_value = _to_number(row.get(count_column))
            if count_value is not None and 0 < count_value < min_group_size:
                new_row = dict(row)
                for dim in dimension_columns:
                    if dim in new_row:
                        new_row[dim] = self.config.suppress_label_fa
                for metric in metric_columns:
                    if metric in new_row:
                        new_row[metric] = None
                new_row["suppressed"] = True
                new_row[
                    "suppression_reason_fa"] = f"تعداد این گروه کمتر از حداقل مجاز نمایش ({min_group_size}) است."
                suppressed += 1
                result.append(new_row)
            else:
                result.append(row)

        warnings = []
        if suppressed:
            warnings.append(
                f"{suppressed} row(s) suppressed because group size was below {min_group_size}.")
        return result, warnings

    def _find_count_column(self, metric_columns: list[str], rows: list[JsonDict]) -> str | None:
        for preferred in ["employee_count", "actual_headcount", "contractor_count", "hire_count", "hiring_count", "count"]:
            if preferred in metric_columns:
                return preferred
        for column in metric_columns:
            if "count" in column.lower() or "headcount" in column.lower():
                return column
        return None

    def _classify_columns(self, columns: list[str], rows: list[JsonDict], *, metadata: Any | None) -> tuple[list[str], list[str]]:
        dimension_columns: list[str] = []
        metric_columns: list[str] = []

        for col in columns:
            lower_col = col.lower()
            if lower_col in {"suppressed", "suppression_reason_fa"}:
                continue
            if self._is_metric_column_name(col):
                metric_columns.append(col)
                continue
            if lower_col in DIMENSION_HINTS:
                dimension_columns.append(col)
                continue
            values = [row.get(col) for row in rows if row.get(col) is not None]
            if values and all(_is_number_like(v) for v in values):
                # hire_year and ranks can be dimensions despite being numeric.
                if lower_col in {"hire_year", "education_rank", "department_level"}:
                    dimension_columns.append(col)
                else:
                    metric_columns.append(col)
            else:
                dimension_columns.append(col)

        # If all numeric columns were dimensions by hint and no metric exists, choose last numeric column as metric.
        if not metric_columns and columns:
            for col in reversed(columns):
                values = [row.get(col)
                          for row in rows if row.get(col) is not None]
                if values and all(_is_number_like(v) for v in values) and col not in {"hire_year", "education_rank", "department_level"}:
                    metric_columns.append(col)
                    if col in dimension_columns:
                        dimension_columns.remove(col)
                    break

        return dimension_columns, metric_columns

    def _is_metric_column_name(self, column: str) -> bool:
        lower = column.lower()
        if lower in COMMON_METRIC_NAMES:
            return True
        return any(token in lower for token in ["count", "percentage", "avg", "average", "gap", "share", "total", "ratio"])

    # ------------------------------------------------------------------
    # Message and metadata
    # ------------------------------------------------------------------

    def _build_success_message(
        self,
        *,
        rows: list[JsonDict],
        visualization: JsonDict,
        title_fa: str,
        dimension_columns: list[str],
        metric_columns: list[str],
    ) -> str:
        visual_type = visualization.get("visualization_type")
        if visual_type in {"kpi_card", "kpi_card_group"} and rows:
            row = rows[0]
            parts: list[str] = []
            for metric in metric_columns[:3]:
                if metric in row:
                    parts.append(
                        f"{self._label_for_column(metric, metadata=None)}: {self._format_value(metric, row.get(metric))}")
            if parts:
                return f"{title_fa} محاسبه شد؛ " + "، ".join(parts) + "."
            return f"{title_fa} محاسبه شد."
        if visual_type == "line_chart":
            return f"{title_fa} آماده شد و روند بر اساس داده‌های کارکنان فعال قابل مشاهده است."
        if visual_type in {"bar_chart", "horizontal_bar_chart", "pie_chart", "stacked_bar_chart"}:
            if dimension_columns:
                dimension_label = self._label_for_column(
                    dimension_columns[0], metadata=None)
                if dimension_label and dimension_label in title_fa:
                    return f"{title_fa} آماده شد."
                return f"{title_fa} به تفکیک {dimension_label} آماده شد."
            return f"{title_fa} آماده شد."
        if visual_type == "table":
            return f"{title_fa} در قالب جدول آماده شد."
        return "نتیجه بر اساس داده‌های کارکنان فعال آماده شد."

    def _build_notes(self, *, context: JsonDict, status_payload: JsonDict, visualization: JsonDict, metadata: Any | None) -> list[str]:
        notes: list[str] = []
        default_filter_note = None
        if metadata is not None:
            with _suppress_exceptions():
                rules = metadata.get_document("visualization_rules")
                default_filter_note = _get_nested(
                    rules, "global_rules", "default_filter_note_fa")
        if default_filter_note:
            notes.append(str(default_filter_note))
        else:
            notes.append(
                "خروجی بر اساس View تحلیلی کارکنان فعال محاسبه شده است.")

        if visualization.get("truncated"):
            notes.append(
                f"برای خوانایی، فقط {visualization.get('visible_row_count')} ردیف اول نمایش داده شده است.")
        if _get_nested(context, "query_result", "truncated"):
            notes.append(
                "نتیجه دیتابیس به دلیل محدودیت تعداد ردیف کوتاه شده است.")
        return _dedupe(notes)

    def _response_metadata(
        self,
        *,
        context: JsonDict,
        intent_id: str | None,
        report_id: str | None,
        rows: list[JsonDict],
        dimension_columns: list[str],
        metric_columns: list[str],
        visualization: JsonDict,
    ) -> JsonDict:
        metadata = {
            "source": self.config.source_name,
            "intent_id": intent_id,
            "report_id": report_id,
            "row_count": len(rows),
            "dimension_columns": dimension_columns,
            "metric_columns": metric_columns,
            "visualization_type": visualization.get("visualization_type"),
            "built_at": _utc_now_iso(),
        }
        if self.config.include_debug_metadata:
            metadata["debug_context_keys"] = sorted(context.keys())
        return metadata

    # ------------------------------------------------------------------
    # Resolvers
    # ------------------------------------------------------------------

    def _resolve_route(self, context: JsonDict, status_payload: JsonDict) -> str:
        route = self._first_non_empty(
            status_payload.get("route"),
            _get_nested(context, "route_result", "route"),
            _get_nested(context, "intent_result", "route"),
            _get_nested(context, "validation_result", "route"),
            _get_nested(context, "query_result", "route"),
        )
        status = str(status_payload.get("status") or _get_nested(
            context, "query_result", "status") or "").upper()
        if not route and status:
            return _route_for_status(status)
        return str(route or ROUTE_SQL).upper()

    def _resolve_status(self, context: JsonDict, status_payload: JsonDict) -> str:
        status = self._first_non_empty(
            status_payload.get("status"),
            status_payload.get("validation_status"),
            _get_nested(context, "query_result", "status"),
            _get_nested(context, "query_result", "execution_status"),
            _get_nested(context, "sql_validation", "status"),
            _get_nested(context, "validation_result", "status"),
            _get_nested(context, "route_result", "status"),
        )
        normalized = str(status or STATUS_SUCCESS).upper()
        if normalized == STATUS_VALID:
            query_status = str(_get_nested(
                context, "query_result", "status") or "").upper()
            if query_status == STATUS_SUCCESS:
                return STATUS_SUCCESS
        if normalized == "FAILED":
            return STATUS_EXECUTION_FAILED
        return normalized

    def _resolve_intent_id(self, context: JsonDict, status_payload: JsonDict) -> str | None:
        value = self._first_non_empty(
            status_payload.get("intent"),
            status_payload.get("intent_id"),
            status_payload.get("detected_intent"),
            _get_nested(context, "intent_result", "intent"),
            _get_nested(context, "intent_result", "intent_id"),
            _get_nested(context, "route_result", "intent"),
            _get_nested(context, "route_result", "intent_id"),
            _get_nested(context, "semantic_result", "intent"),
            _get_nested(context, "gap_result", "intent"),
        )
        return str(value) if value else None

    def _resolve_report_id(self, context: JsonDict, status_payload: JsonDict) -> str | None:
        value = self._first_non_empty(
            status_payload.get("report_id"),
            _get_nested(context, "route_result", "report_id"),
            _get_nested(context, "intent_result", "report_id"),
            _get_nested(context, "sql_plan", "report_id"),
        )
        return str(value) if value else None

    def _resolve_sql(self, context: JsonDict, status_payload: JsonDict) -> str | None:
        value = self._first_non_empty(
            status_payload.get("generated_sql"),
            status_payload.get("sql"),
            _get_nested(context, "sql_plan", "sql"),
            _get_nested(context, "query_result", "sql"),
        )
        return str(value) if value else None

    def _resolve_title_fa(self, *, intent_id: str | None, report_id: str | None, metadata: Any | None) -> str:
        if metadata is not None and report_id:
            with _suppress_exceptions():
                report = metadata.get_report(report_id)
                if isinstance(report, Mapping) and report.get("title_fa"):
                    return str(report["title_fa"])
        if metadata is not None and intent_id:
            with _suppress_exceptions():
                visual = metadata.get_visualization_for_intent(intent_id)
                if isinstance(visual, Mapping) and visual.get("default_title_fa"):
                    return str(visual["default_title_fa"])
            with _suppress_exceptions():
                intent = metadata.get_intent(intent_id)
                if isinstance(intent, Mapping):
                    for key in ["title_fa", "name_fa", "description_fa"]:
                        if intent.get(key):
                            return str(intent[key])
        return self.config.default_title_fa

    # ------------------------------------------------------------------
    # Formatting helpers
    # ------------------------------------------------------------------

    def _formatting_for_columns(self, metric_columns: list[str]) -> JsonDict:
        return {column: self._format_name_for_column(column) for column in metric_columns}

    def _format_name_for_column(self, column: str) -> str:
        lower = column.lower()
        if "percentage" in lower or "percent" in lower or lower in {"share"}:
            return "percentage_2_decimals"
        if "average" in lower or lower.startswith("avg"):
            return "decimal_2"
        if "gap" in lower:
            return "integer_with_sign"
        return "integer" if any(token in lower for token in ["count", "headcount", "total"]) else "raw"

    def _format_value(self, column: str, value: Any) -> str:
        if value is None:
            return "غیرقابل نمایش"
        fmt = self._format_name_for_column(column)
        number = _to_number(value)
        if number is None:
            return str(value)
        if fmt == "percentage_2_decimals":
            return f"{number:,.2f}%"
        if fmt == "decimal_2":
            return f"{number:,.2f}"
        if fmt == "integer_with_sign":
            sign = "+" if number > 0 else ""
            return f"{sign}{number:,.0f}"
        if fmt == "integer":
            return f"{number:,.0f}"
        return str(value)

    def _label_for_column(self, column: str, *, metadata: Any | None) -> str:
        if column in FA_LABELS:
            return FA_LABELS[column]
        if metadata is not None:
            with _suppress_exceptions():
                col = metadata.get_column(column)
                if isinstance(col, Mapping):
                    return str(col.get("title_fa") or col.get("description_fa") or column)
        # Convert snake case to a readable fallback.
        return column.replace("_", " ")

    # ------------------------------------------------------------------
    # Extraction helpers
    # ------------------------------------------------------------------

    def _extract_rows(self, query_result: JsonDict) -> list[JsonDict]:
        rows = query_result.get("rows")
        if rows is None:
            rows = query_result.get("data")
        if rows is None and "result" in query_result:
            result = query_result.get("result")
            if isinstance(result, Mapping):
                rows = result.get("rows") or result.get("data")
        if not isinstance(rows, Sequence) or isinstance(rows, (str, bytes)):
            return []
        output: list[JsonDict] = []
        for row in rows:
            if isinstance(row, Mapping):
                output.append({str(k): _json_safe(v) for k, v in row.items()})
            elif is_dataclass(row):
                output.append({str(k): _json_safe(v)
                              for k, v in asdict(row).items()})
        return output

    def _extract_embedded_status(self, rows: list[JsonDict]) -> str | None:
        if len(rows) == 1 and set(rows[0].keys()) == {"status"}:
            status = str(rows[0].get("status") or "").upper()
            if status:
                return status
        return None

    def _collect_warnings(self, context: JsonDict, status_payload: JsonDict, query_result: JsonDict) -> list[str]:
        warnings: list[str] = []
        for source in [
            context.get("warnings"),
            status_payload.get("warnings"),
            query_result.get("warnings"),
            _get_nested(context, "sql_validation", "warnings"),
            _get_nested(context, "sql_plan", "warnings"),
            _get_nested(context, "route_result", "warnings"),
            _get_nested(context, "gap_result", "warnings"),
        ]:
            warnings.extend(_as_string_list(source))
        return _dedupe(warnings)

    def _collect_errors(self, context: JsonDict, status_payload: JsonDict, query_result: JsonDict) -> list[str]:
        errors: list[str] = []
        for source in [
            context.get("errors"),
            status_payload.get("errors"),
            query_result.get("errors"),
            _get_nested(context, "sql_validation", "errors"),
            _get_nested(context, "sql_plan", "errors"),
            _get_nested(context, "route_result", "errors"),
            _get_nested(context, "gap_result", "errors"),
        ]:
            errors.extend(_as_string_list(source))
        return _dedupe(errors)

    @staticmethod
    def _first_non_empty(*values: Any) -> Any:
        for value in values:
            if value is None:
                continue
            if isinstance(value, str) and not value.strip():
                continue
            return value
        return None


# ---------------------------------------------------------------------------
# Helper functions
# ---------------------------------------------------------------------------


def _route_for_status(status: str) -> str:
    normalized = (status or "").upper()
    if normalized == STATUS_DATA_GAP:
        return ROUTE_GAP
    if normalized in {STATUS_ACCESS_DENIED, STATUS_OUT_OF_SCOPE, STATUS_SQL_VALIDATION_FAILED, "REJECTED"}:
        return ROUTE_REJECT
    if normalized == STATUS_NEEDS_CLARIFICATION:
        return ROUTE_NEEDS_CLARIFICATION
    return ROUTE_SQL


def _normalize_visual_type(value: str | None) -> str | None:
    if not value:
        return None
    normalized = str(value).strip().lower()
    aliases = {
        "kpi": "kpi_card",
        "card": "kpi_card",
        "kpi_card_or_bar_chart": "kpi_card",
        "bar": "bar_chart",
        "bar_chart_or_table": "bar_chart",
        "horizontal_bar": "horizontal_bar_chart",
        "horizontal_bar_chart_or_table": "horizontal_bar_chart",
        "line": "line_chart",
        "line_chart_or_table": "line_chart",
        "pie": "pie_chart",
        "pie_chart_or_bar_chart": "pie_chart",
        "status": "status_message",
    }
    return aliases.get(normalized, normalized)


def _to_mapping(obj: Any) -> JsonDict:
    if obj is None:
        return {}
    if isinstance(obj, Mapping):
        return {str(k): _json_safe(v) for k, v in obj.items()}
    if is_dataclass(obj):
        return _to_mapping(asdict(obj))
    if hasattr(obj, "to_dict") and callable(obj.to_dict):
        with _suppress_exceptions():
            return _to_mapping(obj.to_dict())
    data: JsonDict = {}
    for key in dir(obj):
        if key.startswith("_"):
            continue
        with _suppress_exceptions():
            value = getattr(obj, key)
            if callable(value):
                continue
            data[key] = _json_safe(value)
    return data


def _as_dict(value: Any) -> JsonDict:
    if isinstance(value, Mapping):
        return {str(k): _json_safe(v) for k, v in value.items()}
    if is_dataclass(value):
        return _as_dict(asdict(value))
    return {}


def _json_safe(value: Any) -> Any:
    if isinstance(value, Mapping):
        return {str(k): _json_safe(v) for k, v in value.items()}
    if isinstance(value, list | tuple | set):
        return [_json_safe(v) for v in value]
    if isinstance(value, Decimal):
        if value == value.to_integral_value():
            return int(value)
        return float(value)
    if isinstance(value, datetime):
        return value.isoformat()
    if isinstance(value, date):
        return value.isoformat()
    if isinstance(value, float):
        if math.isnan(value) or math.isinf(value):
            return None
    return value


def _get_nested(obj: Any, *keys: str) -> Any:
    cur = obj
    for key in keys:
        if cur is None:
            return None
        if isinstance(cur, Mapping):
            cur = cur.get(key)
            continue
        if is_dataclass(cur):
            cur = asdict(cur).get(key)
            continue
        cur = getattr(cur, key, None)
    return cur


def _as_string_list(value: Any) -> list[str]:
    if value is None:
        return []
    if isinstance(value, str):
        return [value] if value else []
    if isinstance(value, Sequence) and not isinstance(value, (str, bytes)):
        return [str(v) for v in value if v is not None and str(v)]
    return [str(value)]


def _dedupe(items: Sequence[str]) -> list[str]:
    seen: set[str] = set()
    output: list[str] = []
    for item in items:
        text = str(item).strip()
        if not text or text in seen:
            continue
        seen.add(text)
        output.append(text)
    return output


def _to_number(value: Any) -> float | None:
    if value is None or value == "":
        return None
    if isinstance(value, bool):
        return 1.0 if value else 0.0
    if isinstance(value, int | float | Decimal):
        try:
            number = float(value)
            if math.isnan(number) or math.isinf(number):
                return None
            return number
        except Exception:
            return None
    text = str(value).replace(",", "").strip()
    try:
        return float(text)
    except Exception:
        return None


def _is_number_like(value: Any) -> bool:
    return _to_number(value) is not None


def _utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


class _suppress_exceptions:
    """Tiny context manager to keep optional metadata probing non-fatal."""

    def __enter__(self) -> None:
        return None

    def __exit__(self, exc_type: Any, exc: Any, tb: Any) -> bool:
        return True


# ---------------------------------------------------------------------------
# Convenience factory
# ---------------------------------------------------------------------------


def get_response_builder(
    *,
    metadata_service: Any | None = None,
    metadata_dir: str | Path | None = None,
    **kwargs: Any,
) -> ResponseBuilder:
    return ResponseBuilder(metadata_service=metadata_service, metadata_dir=metadata_dir, **kwargs)


# ---------------------------------------------------------------------------
# Local smoke test
# ---------------------------------------------------------------------------

if __name__ == "__main__":  # pragma: no cover
    builder = ResponseBuilder(metadata_dir=Path(
        __file__).resolve().parent, include_debug_metadata=True)
    context = {
        "request_id": "demo",
        "question": "تعداد زن و مرد چند نفر است؟",
        "intent_result": {"intent": "employee_count_by_gender", "route": "SQL"},
        "route_result": {"route": "SQL", "status": "VALID"},
        "sql_plan": {"sql": "SELECT v.gender, COUNT(v.employee_id) AS employee_count FROM hr_mvp.vw_hr_employee_analytics v WHERE v.is_active = TRUE GROUP BY v.gender;"},
        "query_result": {
            "status": "SUCCESS",
            "execution_status": "SUCCESS",
            "rows": [
                {"gender": "مرد", "employee_count": 645, "percentage": 86.0},
                {"gender": "زن", "employee_count": 105, "percentage": 14.0},
            ],
        },
    }
    import json

    print(json.dumps(builder.build(context=context, status_payload={
          "status": "SUCCESS", "route": "SQL"}), ensure_ascii=False, indent=2))
