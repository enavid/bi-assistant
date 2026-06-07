from __future__ import annotations
import math
from copy import deepcopy
from dataclasses import asdict, dataclass, field, is_dataclass
from datetime import date, datetime
from decimal import Decimal
from pathlib import Path
from typing import Any, Mapping, Sequence

"""
chart_builder.py
----------------
Frontend-ready visualization builder for HR BI Assistant Phase 2: Controlled SQL-based MVP.

Place this file in:
    backend/app/services/chart_builder.py

Responsibility:
    - Convert a validated query result into a stable visualization payload.
    - Read visualization preferences from visualization_rules.yaml through metadata_service.py.
    - Choose a safe visual type for HR BI outputs: KPI card, table, bar, horizontal bar,
      line, pie, stacked bar, or status message.
    - Build a compact chart spec that the frontend can render with a chart library such as Recharts.

Design rules:
    - Never fabricate rows or metrics.
    - Never build charts for GAP / REJECT / error statuses.
    - Never expose sensitive identifiers.
    - Prefer simple, readable visuals over decorative charts.
    - Keep this module deterministic and rule-based for the Controlled SQL-based MVP.
"""

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
    "ACCESS_BLOCKED",
}

SUCCESS_STATUSES = {STATUS_SUCCESS, STATUS_VALID,
                    STATUS_SUPPORTED, "OK", "DONE", "VALIDATED"}

VIS_KPI_CARD = "kpi_card"
VIS_KPI_CARD_GROUP = "kpi_card_group"
VIS_TABLE = "table"
VIS_BAR = "bar_chart"
VIS_HORIZONTAL_BAR = "horizontal_bar_chart"
VIS_STACKED_BAR = "stacked_bar_chart"
VIS_LINE = "line_chart"
VIS_PIE = "pie_chart"
VIS_STATUS = "status_message"

RECHARTS_TYPE_BY_VISUAL = {
    VIS_BAR: "bar",
    VIS_HORIZONTAL_BAR: "bar",
    VIS_STACKED_BAR: "bar",
    VIS_LINE: "line",
    VIS_PIE: "pie",
}

DEFAULT_SOURCE_VIEW = "hr_mvp.vw_hr_employee_analytics"
DEFAULT_ALIAS = "v"

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
    "birth_date",
    "hire_date",
    "contract_start_date",
    "contract_end_date",
}

DEFAULT_IDENTIFIER_COLUMNS = {
    "employee_id",
    "department_id",
    "location_id",
    "position_id",
    "parent_department_id",
    "department_code",
    "position_code",
}

DEFAULT_DIMENSIONS = {
    "gender",
    "marital_status",
    "age_group_title",
    "education_title",
    "education_category",
    "employment_type",
    "contract_type",
    "is_contractor",
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
    "status",
}

DEFAULT_METRICS = {
    "employee_count",
    "count",
    "total_count",
    "actual_headcount",
    "approved_headcount",
    "department_approved_headcount",
    "headcount_gap",
    "percentage",
    "share_percentage",
    "female_percentage",
    "male_percentage",
    "contractor_count",
    "contractor_percentage",
    "average_age",
    "avg_age",
    "average_service_years",
    "avg_service_years",
    "hire_count",
    "hiring_count",
    "without_service_count",
    "below_required_education_count",
}

DEFAULT_FA_LABELS = {
    "employee_count": "تعداد کارکنان",
    "count": "تعداد",
    "total_count": "تعداد کل",
    "actual_headcount": "نیروی موجود",
    "approved_headcount": "چارت مصوب",
    "department_approved_headcount": "چارت مصوب",
    "headcount_gap": "اختلاف نیرو",
    "percentage": "درصد",
    "share_percentage": "درصد سهم",
    "female_percentage": "درصد زنان",
    "male_percentage": "درصد مردان",
    "contractor_count": "تعداد نیروهای پیمانکاری",
    "contractor_percentage": "درصد پیمانکاری",
    "average_age": "میانگین سن",
    "avg_age": "میانگین سن",
    "average_service_years": "میانگین سابقه",
    "avg_service_years": "میانگین سابقه",
    "hire_count": "تعداد جذب",
    "hiring_count": "تعداد جذب",
    "without_service_count": "تعداد بدون سابقه",
    "below_required_education_count": "کمتر از مدرک موردنیاز",
    "gender": "جنسیت",
    "marital_status": "وضعیت تأهل",
    "age_group_title": "گروه سنی",
    "education_title": "مدرک تحصیلی",
    "education_category": "گروه تحصیلی",
    "employment_type": "نوع استخدام",
    "contract_type": "نوع قرارداد",
    "is_contractor": "وضعیت پیمانکاری",
    "service_domain": "حوزه خدمت",
    "department_name": "واحد / دپارتمان",
    "department_level": "سطح دپارتمان",
    "province": "استان",
    "site_name": "محل خدمت",
    "location_type": "نوع محل خدمت",
    "position_title": "عنوان پست",
    "position_level": "سطح پست",
    "job_family": "خانواده شغلی",
    "hire_year": "سال جذب",
    "criticality_level": "سطح حساسیت",
    "status": "وضعیت",
}

DEFAULT_STATUS_TEMPLATES = {
    STATUS_DATA_GAP: {
        "title_fa": "داده کافی نیست",
        "message_fa": "این سؤال مرتبط با منابع انسانی است، اما در نسخه فعلی داده، قانون یا سند کافی برای پاسخ دقیق وجود ندارد.",
        "severity": "warning",
    },
    STATUS_ACCESS_DENIED: {
        "title_fa": "امکان نمایش اطلاعات وجود ندارد",
        "message_fa": "درخواست شامل اطلاعات فردی یا حساس کارکنان است و طبق سیاست محرمانگی قابل نمایش نیست.",
        "severity": "error",
    },
    STATUS_OUT_OF_SCOPE: {
        "title_fa": "خارج از دامنه منابع انسانی",
        "message_fa": "این سؤال در دامنه HR BI Assistant نیست.",
        "severity": "info",
    },
    STATUS_NEEDS_CLARIFICATION: {
        "title_fa": "نیاز به شفاف‌سازی سؤال",
        "message_fa": "برای انتخاب شاخص یا سطح تحلیل، سؤال نیاز به توضیح بیشتر دارد.",
        "severity": "info",
    },
    STATUS_SQL_VALIDATION_FAILED: {
        "title_fa": "SQL معتبر نیست",
        "message_fa": "کوئری تولیدشده با قوانین امنیتی یا ساختاری فاز دوم سازگار نیست.",
        "severity": "error",
    },
    STATUS_EXECUTION_FAILED: {
        "title_fa": "خطا در اجرای کوئری",
        "message_fa": "هنگام اجرای کوئری روی دیتابیس خطا رخ داد.",
        "severity": "error",
    },
    STATUS_NO_DATA: {
        "title_fa": "داده‌ای یافت نشد",
        "message_fa": "برای فیلترهای انتخاب‌شده، رکورد قابل نمایش وجود ندارد.",
        "severity": "info",
    },
    STATUS_NOT_EXECUTED: {
        "title_fa": "کوئری اجرا نشد",
        "message_fa": "کوئری اجرا نشده است.",
        "severity": "warning",
    },
}


@dataclass
class ChartBuilderConfig:
    """Runtime configuration for ChartBuilder."""

    source_name: str = "chart_builder"
    locale: str = "fa-IR"
    direction: str = "rtl"
    source_view: str = DEFAULT_SOURCE_VIEW
    max_table_rows: int = 50
    max_chart_rows: int = 20
    max_pie_slices: int = 6
    horizontal_bar_threshold: int = 6
    max_label_length_for_vertical_bar: int = 18
    min_group_size_default: int = 5
    # response_builder normally applies this earlier.
    suppress_small_groups: bool = False
    suppress_label_fa: str = "غیرقابل نمایش"
    include_chart_spec: bool = True
    include_data_in_visualization: bool = True
    default_title_fa: str = "نتیجه تحلیل منابع انسانی"


@dataclass
class ChartPayload:
    """Standard output shape consumed by response_builder.py or the frontend."""

    visualization_type: str
    title_fa: str
    subtitle_fa: str | None = None
    dimension_columns: list[str] = field(default_factory=list)
    metric_columns: list[str] = field(default_factory=list)
    x_axis: str | None = None
    y_axis: str | None = None
    series: list[str] = field(default_factory=list)
    sort: str | None = None
    top_n: int | None = None
    show_percentage: bool = False
    show_total: bool = False
    formatting: JsonDict = field(default_factory=dict)
    data_limitations: list[str] = field(default_factory=list)
    source: str = DEFAULT_SOURCE_VIEW
    fallback_visualization_type: str | None = None
    data: list[JsonDict] = field(default_factory=list)
    chart_spec: JsonDict | None = None
    kpi_cards: list[JsonDict] = field(default_factory=list)
    table: JsonDict | None = None
    status_message: JsonDict | None = None
    warnings: list[str] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)
    metadata: JsonDict = field(default_factory=dict)

    def to_dict(self) -> JsonDict:
        return asdict(self)


class ChartBuilder:
    """
    Build visualization metadata and chart specs from query rows.

    Public methods mirror the project service pattern:
        build(...)
        build_chart(...)
        run(...)
        arun(...)
        __call__(...)
    """

    def __init__(
        self,
        *,
        metadata_service: Any | None = None,
        metadata_dir: str | Path | None = None,
        max_table_rows: int = 50,
        max_chart_rows: int = 20,
        max_pie_slices: int = 6,
        suppress_small_groups: bool = False,
        include_chart_spec: bool = True,
        include_data_in_visualization: bool = True,
    ) -> None:
        if metadata_service is not None:
            self.metadata = metadata_service
        elif get_metadata_service is not None:
            self.metadata = get_metadata_service(
                metadata_dir=metadata_dir, strict=False)
        else:
            self.metadata = None

        min_group_size = ChartBuilderConfig.min_group_size_default
        with _suppress_exceptions():
            if self.metadata is not None and hasattr(self.metadata, "get_min_group_size"):
                min_group_size = int(
                    self.metadata.get_min_group_size(default=min_group_size))

        self.config = ChartBuilderConfig(
            max_table_rows=int(max_table_rows),
            max_chart_rows=int(max_chart_rows),
            max_pie_slices=int(max_pie_slices),
            min_group_size_default=int(min_group_size),
            suppress_small_groups=bool(suppress_small_groups),
            include_chart_spec=bool(include_chart_spec),
            include_data_in_visualization=bool(include_data_in_visualization),
        )
        self.visualization_rules = self._load_visualization_rules()
        self.column_roles = self._load_column_roles()
        self.intent_visualization_index = self._build_intent_visualization_index()
        self.report_visualization_index = self._build_report_visualization_index()
        self.status_templates = self._load_status_templates()

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def build(
        self,
        *,
        rows: Sequence[Mapping[str, Any]] | None = None,
        query_result: Mapping[str, Any] | None = None,
        context: Any | None = None,
        status_payload: Mapping[str, Any] | None = None,
        route: str | None = None,
        status: str | None = None,
        intent_id: str | None = None,
        report_id: str | None = None,
        visualization_hint: str | None = None,
        title_fa: str | None = None,
        **_: Any,
    ) -> JsonDict:
        """Build a frontend-ready visualization payload."""
        ctx = _to_mapping(context)
        status_payload_dict = dict(status_payload or {})
        resolved_route = self._resolve_route(
            route=route, context=ctx, status_payload=status_payload_dict)
        resolved_status = self._resolve_status(
            status=status, context=ctx, status_payload=status_payload_dict)
        resolved_intent = self._first_non_empty(intent_id, _get_nested(ctx, "intent_result", "intent"), _get_nested(
            ctx, "intent_result", "intent_id"), ctx.get("detected_intent"))
        resolved_report = self._first_non_empty(report_id, _get_nested(
            ctx, "route_result", "report_id"), _get_nested(ctx, "intent_result", "report_id"), ctx.get("report_id"))

        if query_result is None:
            query_result = _as_dict(ctx.get("query_result"))
        all_rows = self._extract_rows(rows=rows, query_result=query_result)
        embedded_status = self._extract_embedded_status(all_rows)
        if embedded_status:
            resolved_status = embedded_status
            resolved_route = _route_for_status(embedded_status)

        if resolved_route != ROUTE_SQL or resolved_status in NON_DATA_STATUSES:
            payload = self._build_status_payload(
                route=resolved_route,
                status=resolved_status,
                status_payload=status_payload_dict,
                intent_id=resolved_intent,
                report_id=resolved_report,
                title_fa=title_fa,
            )
            return payload.to_dict()

        if resolved_status in SUCCESS_STATUSES:
            resolved_status = STATUS_SUCCESS

        if not all_rows:
            payload = self._build_status_payload(
                route=ROUTE_SQL,
                status=STATUS_NO_DATA,
                status_payload=status_payload_dict,
                intent_id=resolved_intent,
                report_id=resolved_report,
                title_fa=title_fa,
            )
            return payload.to_dict()

        sanitized_rows, privacy_warnings = self._sanitize_rows(all_rows)
        if not sanitized_rows:
            payload = self._build_status_payload(
                route=ROUTE_REJECT,
                status=STATUS_ACCESS_DENIED,
                status_payload={
                    **status_payload_dict, "reason": "All output columns were blocked by chart privacy rules."},
                intent_id=resolved_intent,
                report_id=resolved_report,
                title_fa=title_fa,
            )
            return payload.to_dict()

        columns = list(sanitized_rows[0].keys())
        dimension_columns, metric_columns = self._classify_columns(
            columns=columns, rows=sanitized_rows)
        safe_rows, suppression_warnings = self._apply_optional_small_group_suppression(
            rows=sanitized_rows,
            dimension_columns=dimension_columns,
            metric_columns=metric_columns,
        )

        if not safe_rows:
            payload = self._build_status_payload(
                route=ROUTE_SQL,
                status=STATUS_NO_DATA,
                status_payload=status_payload_dict,
                intent_id=resolved_intent,
                report_id=resolved_report,
                title_fa=title_fa,
            )
            payload.warnings.extend(privacy_warnings + suppression_warnings)
            return payload.to_dict()

        visual_type, visual_warnings = self._choose_visualization_type(
            rows=safe_rows,
            dimension_columns=dimension_columns,
            metric_columns=metric_columns,
            intent_id=resolved_intent,
            report_id=resolved_report,
            visualization_hint=visualization_hint,
        )
        title = self._resolve_title_fa(
            explicit_title=title_fa,
            intent_id=resolved_intent,
            report_id=resolved_report,
            visual_type=visual_type,
        )
        fallback = self._resolve_fallback_visualization(
            intent_id=resolved_intent, report_id=resolved_report, visual_type=visual_type)

        prepared_rows = self._prepare_rows_for_visualization(
            rows=safe_rows,
            visualization_type=visual_type,
            metric_columns=metric_columns,
            dimension_columns=dimension_columns,
        )
        x_axis = self._choose_x_axis(
            visual_type=visual_type, dimension_columns=dimension_columns, metric_columns=metric_columns, rows=prepared_rows)
        y_axis = self._choose_y_axis(
            metric_columns=metric_columns, rows=prepared_rows)
        series = self._choose_series(
            visual_type=visual_type, metric_columns=metric_columns, rows=prepared_rows)
        show_percentage = any("percentage" in col for col in metric_columns)
        show_total = visual_type in {
            VIS_KPI_CARD, VIS_KPI_CARD_GROUP, VIS_PIE} or "employee_count" in metric_columns
        formatting = self._build_formatting(
            metric_columns=metric_columns, dimension_columns=dimension_columns, visualization_type=visual_type)

        chart_spec: JsonDict | None = None
        kpi_cards: list[JsonDict] = []
        table: JsonDict | None = None
        extra_warnings: list[str] = []

        if visual_type in {VIS_BAR, VIS_HORIZONTAL_BAR, VIS_LINE, VIS_PIE}:
            chart_spec, spec_warnings = self._build_chart_spec(
                visualization_type=visual_type,
                title_fa=title,
                rows=prepared_rows,
                x_axis=x_axis,
                y_axis=y_axis,
                series=series,
                dimension_columns=dimension_columns,
                metric_columns=metric_columns,
            )
            extra_warnings.extend(spec_warnings)
        elif visual_type in {VIS_KPI_CARD, VIS_KPI_CARD_GROUP}:
            kpi_cards = self._build_kpi_cards(
                rows=prepared_rows, metric_columns=metric_columns)
        elif visual_type == VIS_TABLE:
            table = self._build_table(
                rows=prepared_rows, dimension_columns=dimension_columns, metric_columns=metric_columns)
        elif visual_type == VIS_STACKED_BAR:
            # Stacked bar is kept as a declared type, but for MVP it falls back to a normal bar
            # unless the data contains multiple comparable count series.
            chart_spec, spec_warnings = self._build_chart_spec(
                visualization_type=VIS_BAR,
                title_fa=title,
                rows=prepared_rows,
                x_axis=x_axis,
                y_axis=y_axis,
                series=series,
                dimension_columns=dimension_columns,
                metric_columns=metric_columns,
            )
            extra_warnings.extend(
                ["stacked_bar_chart فعلاً به bar_chart استاندارد تبدیل شد."] + spec_warnings)

        payload = ChartPayload(
            visualization_type=visual_type,
            title_fa=title,
            subtitle_fa=self._build_subtitle(
                visual_type=visual_type, rows=prepared_rows),
            dimension_columns=dimension_columns,
            metric_columns=metric_columns,
            x_axis=x_axis,
            y_axis=y_axis,
            series=series,
            sort=self._infer_sort(
                visualization_type=visual_type, x_axis=x_axis),
            top_n=self._infer_top_n(
                visualization_type=visual_type, rows=prepared_rows),
            show_percentage=show_percentage,
            show_total=show_total,
            formatting=formatting,
            data_limitations=self._build_data_limitations(
                visualization_type=visual_type, dimension_columns=dimension_columns, rows=prepared_rows),
            source=self.config.source_view,
            fallback_visualization_type=fallback,
            data=prepared_rows if self.config.include_data_in_visualization else [],
            chart_spec=chart_spec if self.config.include_chart_spec else None,
            kpi_cards=kpi_cards,
            table=table,
            warnings=_dedupe(
                privacy_warnings + suppression_warnings + visual_warnings + extra_warnings),
            errors=[],
            metadata={
                "source_module": self.config.source_name,
                "intent_id": resolved_intent,
                "report_id": resolved_report,
                "row_count": len(prepared_rows),
                "original_row_count": len(all_rows),
                "column_count": len(columns),
                "route": resolved_route,
                "status": resolved_status,
            },
        )
        return payload.to_dict()

    def build_chart(self, **kwargs: Any) -> JsonDict:
        return self.build(**kwargs)

    def run(self, **kwargs: Any) -> JsonDict:
        return self.build(**kwargs)

    async def arun(self, **kwargs: Any) -> JsonDict:
        return self.build(**kwargs)

    def __call__(self, **kwargs: Any) -> JsonDict:
        return self.build(**kwargs)

    # ------------------------------------------------------------------
    # Metadata loading
    # ------------------------------------------------------------------

    def _load_visualization_rules(self) -> JsonDict:
        if self.metadata is None:
            return {}
        candidates = [
            "visualization_rules",
            "visualization_rules.yaml",
            "Template_06_visualization_rules.yaml",
        ]
        for attr in ("visualization_rules", "visualization", "visualization_config"):
            value = getattr(self.metadata, attr, None)
            if isinstance(value, Mapping):
                return dict(value)
        # MetadataService used in this project exposes get_document/get_all rather than a
        # dedicated get_visualization_rules method, so support both styles.
        for method_name in ("get_visualization_rules", "get_metadata", "get", "get_document"):
            method = getattr(self.metadata, method_name, None)
            if not callable(method):
                continue
            for candidate in candidates:
                with _suppress_exceptions():
                    result = method(candidate)
                    if isinstance(result, Mapping):
                        return dict(result)
        method = getattr(self.metadata, "get_all", None)
        if callable(method):
            with _suppress_exceptions():
                result = method()
                if isinstance(result, Mapping) and isinstance(result.get("visualization_rules"), Mapping):
                    return dict(result["visualization_rules"])
        return {}

    def _load_column_roles(self) -> JsonDict:
        mapping = _as_dict(self.visualization_rules.get("column_role_mapping"))
        if mapping:
            return mapping
        return {
            "dimension_columns": {col: {"label_fa": DEFAULT_FA_LABELS.get(col, col)} for col in DEFAULT_DIMENSIONS},
            "metric_columns": {col: {"label_fa": DEFAULT_FA_LABELS.get(col, col), "format": _default_format_for_metric(col)} for col in DEFAULT_METRICS},
            "status_columns": {"status": {"label_fa": "وضعیت", "format": "status_code"}},
        }

    def _build_intent_visualization_index(self) -> dict[str, JsonDict]:
        rows = self.visualization_rules.get("intent_visualization_map") or self.visualization_rules.get(
            "intent_visualization_mapping") or []
        index: dict[str, JsonDict] = {}
        if isinstance(rows, Sequence) and not isinstance(rows, (str, bytes, bytearray)):
            for item in rows:
                if isinstance(item, Mapping) and item.get("intent"):
                    index[str(item["intent"])] = dict(item)
        return index

    def _build_report_visualization_index(self) -> dict[str, JsonDict]:
        rows = self.visualization_rules.get("report_visualization_map") or self.visualization_rules.get(
            "report_visualization_mapping") or []
        index: dict[str, JsonDict] = {}
        if isinstance(rows, Sequence) and not isinstance(rows, (str, bytes, bytearray)):
            for item in rows:
                if isinstance(item, Mapping) and item.get("report_id"):
                    index[str(item["report_id"])] = dict(item)
        return index

    def _load_status_templates(self) -> dict[str, JsonDict]:
        templates = _as_dict(self.visualization_rules.get(
            "status_message_templates"))
        merged = deepcopy(DEFAULT_STATUS_TEMPLATES)
        for key, value in templates.items():
            if isinstance(value, Mapping):
                merged[str(key).upper()] = {
                    **merged.get(str(key).upper(), {}), **dict(value)}
        return merged

    # ------------------------------------------------------------------
    # Status payloads
    # ------------------------------------------------------------------

    def _build_status_payload(
        self,
        *,
        route: str,
        status: str,
        status_payload: JsonDict,
        intent_id: str | None,
        report_id: str | None,
        title_fa: str | None,
    ) -> ChartPayload:
        normalized_status = (status or STATUS_SQL_VALIDATION_FAILED).upper()
        normalized_route = (route or _route_for_status(
            normalized_status)).upper()
        template = self.status_templates.get(
            normalized_status, DEFAULT_STATUS_TEMPLATES.get(normalized_status, {}))
        title = self._first_non_empty(title_fa, status_payload.get(
            "title_fa"), template.get("title_fa"), "وضعیت پاسخ")
        message = self._first_non_empty(status_payload.get("message_fa"), status_payload.get(
            "reason_fa"), template.get("message_fa"), "خروجی قابل نمایش نیست.")
        severity = self._first_non_empty(status_payload.get(
            "severity"), template.get("severity"), "info")
        status_message = {
            "status": normalized_status,
            "route": normalized_route,
            "title_fa": title,
            "message_fa": message,
            "severity": severity,
            "recommended_action_fa": self._first_non_empty(status_payload.get("recommended_action_fa"), template.get("recommended_action_fa")),
        }
        return ChartPayload(
            visualization_type=VIS_STATUS,
            title_fa=title,
            subtitle_fa=message,
            source=self.config.source_view,
            status_message=status_message,
            warnings=_to_string_list(status_payload.get("warnings")),
            errors=_to_string_list(status_payload.get("errors")),
            metadata={
                "source_module": self.config.source_name,
                "route": normalized_route,
                "status": normalized_status,
                "intent_id": intent_id,
                "report_id": report_id,
                "row_count": 0,
            },
        )

    # ------------------------------------------------------------------
    # Row extraction and sanitization
    # ------------------------------------------------------------------

    def _extract_rows(self, *, rows: Sequence[Mapping[str, Any]] | None, query_result: Mapping[str, Any] | None) -> list[JsonDict]:
        if rows is not None:
            return [_json_safe_dict(row) for row in rows if isinstance(row, Mapping)]
        qr = _as_dict(query_result)
        candidate = qr.get("rows") or qr.get(
            "data") or qr.get("result") or qr.get("records")
        if isinstance(candidate, Sequence) and not isinstance(candidate, (str, bytes, bytearray)):
            result: list[JsonDict] = []
            columns = qr.get("columns") if isinstance(
                qr.get("columns"), Sequence) else None
            for item in candidate:
                if isinstance(item, Mapping):
                    result.append(_json_safe_dict(item))
                elif isinstance(item, Sequence) and columns and not isinstance(item, (str, bytes, bytearray)):
                    result.append(_json_safe_dict(
                        dict(zip([str(c) for c in columns], item))))
            return result
        return []

    def _sanitize_rows(self, rows: list[JsonDict]) -> tuple[list[JsonDict], list[str]]:
        warnings: list[str] = []
        if not rows:
            return [], warnings
        blocked = self._blocked_output_columns()
        sanitized: list[JsonDict] = []
        removed_columns: set[str] = set()
        for row in rows:
            clean: JsonDict = {}
            for key, value in row.items():
                normalized_key = _normalize_column_name(key)
                if normalized_key in blocked:
                    removed_columns.add(key)
                    continue
                clean[key] = _json_safe(value)
            if clean:
                sanitized.append(clean)
        if removed_columns:
            warnings.append(
                "برخی ستون‌های حساس یا داخلی از خروجی نمودار حذف شدند: " + ", ".join(sorted(removed_columns)))
        return sanitized, warnings

    def _blocked_output_columns(self) -> set[str]:
        blocked = {c.lower() for c in DEFAULT_SENSITIVE_COLUMNS |
                   DEFAULT_IDENTIFIER_COLUMNS}
        # employee_id can be visible only if it appears as a metric alias like employee_count,
        # not as the raw employee_id column.
        blocked.add("employee_id")
        if self.metadata is not None:
            with _suppress_exceptions():
                if hasattr(self.metadata, "get_sensitive_columns"):
                    blocked.update(str(c).lower()
                                   for c in self.metadata.get_sensitive_columns())
        return blocked

    def _apply_optional_small_group_suppression(
        self,
        *,
        rows: list[JsonDict],
        dimension_columns: list[str],
        metric_columns: list[str],
    ) -> tuple[list[JsonDict], list[str]]:
        if not self.config.suppress_small_groups or not rows or not dimension_columns:
            return rows, []
        count_col = self._find_count_metric(metric_columns)
        if not count_col:
            return rows, []
        min_size = self.config.min_group_size_default
        safe_rows: list[JsonDict] = []
        suppressed = 0
        for row in rows:
            value = _to_number(row.get(count_col))
            if value is not None and value < min_size:
                suppressed += 1
                continue
            safe_rows.append(row)
        warnings: list[str] = []
        if suppressed:
            warnings.append(
                f"{suppressed} گروه به دلیل کمتر بودن از حداقل تعداد مجاز نمایش داده نشدند.")
        return safe_rows, warnings

    # ------------------------------------------------------------------
    # Column classification
    # ------------------------------------------------------------------

    def _classify_columns(self, *, columns: list[str], rows: list[JsonDict]) -> tuple[list[str], list[str]]:
        role_dimensions = set(_as_dict(self.column_roles.get(
            "dimension_columns")).keys()) or DEFAULT_DIMENSIONS
        role_metrics = set(_as_dict(self.column_roles.get(
            "metric_columns")).keys()) or DEFAULT_METRICS
        dimensions: list[str] = []
        metrics: list[str] = []
        for col in columns:
            normalized = _normalize_column_name(col)
            if normalized in {"status", "reason"}:
                dimensions.append(col)
            elif normalized in role_metrics or normalized in DEFAULT_METRICS or self._looks_like_metric(col, rows):
                metrics.append(col)
            elif normalized in role_dimensions or normalized in DEFAULT_DIMENSIONS:
                dimensions.append(col)
            elif self._looks_like_dimension(col, rows):
                dimensions.append(col)
            else:
                # Unknown numeric columns are usually metrics; unknown textual columns are dimensions.
                if _column_is_numeric(col, rows):
                    metrics.append(col)
                else:
                    dimensions.append(col)
        if not metrics and rows:
            # If all columns were classified as dimensions but one numeric column exists, treat it as metric.
            for col in columns:
                if _column_is_numeric(col, rows):
                    if col in dimensions:
                        dimensions.remove(col)
                    metrics.append(col)
                    break
        return dimensions, metrics

    def _looks_like_metric(self, col: str, rows: list[JsonDict]) -> bool:
        key = _normalize_column_name(col)
        if any(token in key for token in ("count", "total", "percentage", "percent", "avg", "average", "gap", "share", "headcount")):
            return True
        return _column_is_numeric(col, rows) and key not in DEFAULT_DIMENSIONS

    def _looks_like_dimension(self, col: str, rows: list[JsonDict]) -> bool:
        key = _normalize_column_name(col)
        if any(token in key for token in ("title", "type", "gender", "status", "domain", "name", "province", "year", "level", "family")):
            return True
        values = [row.get(col) for row in rows]
        non_null = [v for v in values if v is not None]
        if not non_null:
            return False
        return not all(_is_number(v) for v in non_null)

    # ------------------------------------------------------------------
    # Visualization selection
    # ------------------------------------------------------------------

    def _choose_visualization_type(
        self,
        *,
        rows: list[JsonDict],
        dimension_columns: list[str],
        metric_columns: list[str],
        intent_id: str | None,
        report_id: str | None,
        visualization_hint: str | None,
    ) -> tuple[str, list[str]]:
        warnings: list[str] = []
        if visualization_hint:
            normalized_hint = _normalize_visualization_type(visualization_hint)
            if normalized_hint:
                return self._ensure_visual_fits_data(normalized_hint, rows, dimension_columns, metric_columns)

        mapped = self._mapped_visualization(
            intent_id=intent_id, report_id=report_id)
        if mapped:
            visual, fit_warnings = self._ensure_visual_fits_data(
                mapped, rows, dimension_columns, metric_columns)
            if visual != mapped:
                warnings.extend(fit_warnings)
            return visual, warnings

        row_count = len(rows)
        metric_count = len(metric_columns)

        if row_count == 1 and metric_count == 1:
            return VIS_KPI_CARD, warnings
        if row_count == 1 and metric_count > 1:
            return VIS_KPI_CARD_GROUP, warnings
        if not metric_columns:
            return VIS_TABLE, warnings
        if not dimension_columns:
            return VIS_KPI_CARD_GROUP if metric_count > 1 else VIS_KPI_CARD, warnings

        primary_dimension = dimension_columns[0]
        normalized_dim = _normalize_column_name(primary_dimension)
        if normalized_dim == "hire_year":
            return VIS_LINE, warnings
        if metric_count >= 3:
            return VIS_TABLE, warnings
        if normalized_dim in {"gender", "is_contractor", "marital_status"} and row_count <= self.config.max_pie_slices:
            return VIS_PIE, warnings
        if row_count >= self.config.horizontal_bar_threshold or self._dimension_values_are_long(rows, primary_dimension):
            return VIS_HORIZONTAL_BAR, warnings
        return VIS_BAR, warnings

    def _mapped_visualization(self, *, intent_id: str | None, report_id: str | None) -> str | None:
        if report_id and report_id in self.report_visualization_index:
            item = self.report_visualization_index[report_id]
            visual = item.get("primary_visualization") or item.get(
                "visualization")
            if visual:
                return _normalize_visualization_type(str(visual))
        if intent_id and intent_id in self.intent_visualization_index:
            item = self.intent_visualization_index[intent_id]
            visual = item.get("primary_visualization") or item.get(
                "visualization")
            if visual:
                return _normalize_visualization_type(str(visual))
        return None

    def _ensure_visual_fits_data(
        self,
        visual_type: str,
        rows: list[JsonDict],
        dimension_columns: list[str],
        metric_columns: list[str],
    ) -> tuple[str, list[str]]:
        warnings: list[str] = []
        row_count = len(rows)
        metric_count = len(metric_columns)
        if visual_type == VIS_STATUS:
            return visual_type, warnings
        if not rows:
            return VIS_STATUS, ["برای داده خالی، status_message انتخاب شد."]
        if visual_type in {VIS_BAR, VIS_HORIZONTAL_BAR, VIS_LINE, VIS_PIE, VIS_STACKED_BAR} and not metric_columns:
            return VIS_TABLE, ["به دلیل نبود ستون عددی، table انتخاب شد."]
        if visual_type in {VIS_BAR, VIS_HORIZONTAL_BAR, VIS_LINE, VIS_PIE} and not dimension_columns:
            if row_count == 1:
                return (VIS_KPI_CARD_GROUP if metric_count > 1 else VIS_KPI_CARD), ["به دلیل نبود بعد تحلیلی، KPI انتخاب شد."]
            return VIS_TABLE, ["به دلیل نبود بعد تحلیلی، table انتخاب شد."]
        if visual_type == VIS_PIE and row_count > self.config.max_pie_slices:
            return VIS_HORIZONTAL_BAR, ["به دلیل زیاد بودن تعداد دسته‌ها، pie_chart به horizontal_bar_chart تبدیل شد."]
        if visual_type == VIS_KPI_CARD and (row_count > 1 or metric_count > 1):
            if row_count == 1:
                return VIS_KPI_CARD_GROUP, ["به دلیل چندشاخصی بودن خروجی، kpi_card_group انتخاب شد."]
            return VIS_TABLE if metric_count > 2 else VIS_BAR, ["به دلیل چندردیفی بودن خروجی، KPI به نمودار/جدول تبدیل شد."]
        return visual_type, warnings

    def _resolve_fallback_visualization(self, *, intent_id: str | None, report_id: str | None, visual_type: str) -> str | None:
        for item in (
            self.report_visualization_index.get(report_id or ""),
            self.intent_visualization_index.get(intent_id or ""),
        ):
            if isinstance(item, Mapping):
                fallback = item.get("fallback_visualization") or item.get(
                    "fallback_visual")
                if fallback:
                    normalized = _normalize_visualization_type(str(fallback))
                    if normalized and normalized != visual_type:
                        return normalized
        return VIS_TABLE if visual_type not in {VIS_TABLE, VIS_STATUS} else None

    # ------------------------------------------------------------------
    # Row preparation and output shapes
    # ------------------------------------------------------------------

    def _prepare_rows_for_visualization(
        self,
        *,
        rows: list[JsonDict],
        visualization_type: str,
        metric_columns: list[str],
        dimension_columns: list[str],
    ) -> list[JsonDict]:
        prepared = [_json_safe_dict(row) for row in rows]
        if visualization_type in {VIS_BAR, VIS_HORIZONTAL_BAR, VIS_LINE, VIS_PIE}:
            prepared = prepared[: self.config.max_chart_rows]
        elif visualization_type == VIS_TABLE:
            prepared = prepared[: self.config.max_table_rows]

        # Convert boolean contractor dimension to readable values for charts.
        for row in prepared:
            if "is_contractor" in row and isinstance(row.get("is_contractor"), bool):
                row["is_contractor"] = "پیمانکاری" if row["is_contractor"] else "غیرپیمانکاری"
            for col in metric_columns:
                if col in row:
                    number = _to_number(row[col])
                    if number is not None:
                        row[col] = number
        return prepared

    def _choose_x_axis(self, *, visual_type: str, dimension_columns: list[str], metric_columns: list[str], rows: list[JsonDict]) -> str | None:
        if visual_type == VIS_PIE:
            return dimension_columns[0] if dimension_columns else None
        if visual_type in {VIS_BAR, VIS_HORIZONTAL_BAR, VIS_LINE, VIS_STACKED_BAR}:
            return dimension_columns[0] if dimension_columns else None
        return None

    def _choose_y_axis(self, *, metric_columns: list[str], rows: list[JsonDict]) -> str | None:
        if not metric_columns:
            return None
        preferred_order = [
            "employee_count",
            "hiring_count",
            "hire_count",
            "actual_headcount",
            "contractor_count",
            "percentage",
            "contractor_percentage",
            "average_age",
            "average_service_years",
            "headcount_gap",
        ]
        normalized_to_original = {_normalize_column_name(
            col): col for col in metric_columns}
        for item in preferred_order:
            if item in normalized_to_original:
                return normalized_to_original[item]
        return metric_columns[0]

    def _choose_series(self, *, visual_type: str, metric_columns: list[str], rows: list[JsonDict]) -> list[str]:
        if not metric_columns:
            return []
        if visual_type == VIS_PIE:
            y = self._choose_y_axis(metric_columns=metric_columns, rows=rows)
            return [y] if y else []
        if visual_type in {VIS_BAR, VIS_HORIZONTAL_BAR, VIS_LINE}:
            # Prefer one clean series. Keep two when one is count and one is percentage only for tables/KPI,
            # not for chart axis mixing.
            y = self._choose_y_axis(metric_columns=metric_columns, rows=rows)
            return [y] if y else []
        if visual_type == VIS_STACKED_BAR:
            return metric_columns[:3]
        return metric_columns

    def _build_chart_spec(
        self,
        *,
        visualization_type: str,
        title_fa: str,
        rows: list[JsonDict],
        x_axis: str | None,
        y_axis: str | None,
        series: list[str],
        dimension_columns: list[str],
        metric_columns: list[str],
    ) -> tuple[JsonDict | None, list[str]]:
        warnings: list[str] = []
        if not rows or not x_axis or not series:
            return None, ["اطلاعات لازم برای ساخت chart_spec کامل نبود."]
        chart_type = RECHARTS_TYPE_BY_VISUAL.get(visualization_type, "bar")
        description = self._build_chart_description(
            visualization_type=visualization_type, x_axis=x_axis, series=series)
        if chart_type == "pie":
            value_key = series[0]
            spec: JsonDict = {
                "chartType": "pie",
                "meta": {"title": title_fa, "description": description},
                "nameKey": x_axis,
                "valueKey": value_key,
                "series": [self._series_spec(value_key)],
                "data": rows,
            }
            return spec, warnings
        spec = {
            "chartType": chart_type,
            "meta": {"title": title_fa, "description": description},
            "xKey": x_axis,
            "xAxisLabel": self._label_for_column(x_axis),
            "series": [self._series_spec(col) for col in series],
            "data": rows,
        }
        if visualization_type == VIS_HORIZONTAL_BAR:
            spec["layout"] = "vertical"
        return spec, warnings

    def _series_spec(self, col: str) -> JsonDict:
        fmt = self._format_for_column(col)
        spec: JsonDict = {
            "dataKey": col,
            "label": self._label_for_column(col),
            "valueFormat": _chart_value_format(fmt),
        }
        if "percentage" in _normalize_column_name(col) or fmt.startswith("percentage"):
            spec["valueSuffix"] = "%"
            spec["axisLabel"] = "درصد"
        elif "age" in _normalize_column_name(col) or "service_years" in _normalize_column_name(col):
            spec["valueFormat"] = "raw"
            spec["axisLabel"] = self._label_for_column(col)
        else:
            spec["axisLabel"] = self._label_for_column(col)
        return spec

    def _build_kpi_cards(self, *, rows: list[JsonDict], metric_columns: list[str]) -> list[JsonDict]:
        if not rows:
            return []
        row = rows[0]
        cards: list[JsonDict] = []
        for col in metric_columns:
            if col not in row:
                continue
            cards.append({
                "key": col,
                "title_fa": self._label_for_column(col),
                "value": row.get(col),
                "formatted_value": self._format_value(row.get(col), col),
                "format": self._format_for_column(col),
            })
        return cards

    def _build_table(self, *, rows: list[JsonDict], dimension_columns: list[str], metric_columns: list[str]) -> JsonDict:
        columns = list(rows[0].keys()) if rows else []
        return {
            "columns": [
                {
                    "key": col,
                    "label_fa": self._label_for_column(col),
                    "role": "metric" if col in metric_columns else "dimension",
                    "format": self._format_for_column(col),
                }
                for col in columns
            ],
            "rows": rows,
            "row_count": len(rows),
            "direction": self.config.direction,
            "show_row_number": True,
        }

    # ------------------------------------------------------------------
    # Titles and labels
    # ------------------------------------------------------------------

    def _resolve_title_fa(self, *, explicit_title: str | None, intent_id: str | None, report_id: str | None, visual_type: str) -> str:
        if explicit_title:
            return explicit_title
        if report_id and report_id in self.report_visualization_index:
            item = self.report_visualization_index[report_id]
            if item.get("default_title_fa"):
                return str(item["default_title_fa"])
        if intent_id and intent_id in self.intent_visualization_index:
            item = self.intent_visualization_index[intent_id]
            if item.get("default_title_fa"):
                return str(item["default_title_fa"])
        # Try report catalog from metadata_service.
        if self.metadata is not None and report_id:
            with _suppress_exceptions():
                if hasattr(self.metadata, "get_report"):
                    report = self.metadata.get_report(report_id)
                    if isinstance(report, Mapping) and report.get("title_fa"):
                        return str(report["title_fa"])
        return self.config.default_title_fa

    def _label_for_column(self, col: str | None) -> str:
        if not col:
            return ""
        normalized = _normalize_column_name(col)
        for role_key in ("metric_columns", "dimension_columns", "status_columns"):
            role_map = _as_dict(self.column_roles.get(role_key))
            item = role_map.get(col) or role_map.get(normalized)
            if isinstance(item, Mapping):
                label = item.get("label_fa") or item.get(
                    "title_fa") or item.get("label")
                if label:
                    return str(label)
        return DEFAULT_FA_LABELS.get(normalized, col)

    def _format_for_column(self, col: str) -> str:
        normalized = _normalize_column_name(col)
        for role_key in ("metric_columns", "dimension_columns", "status_columns"):
            role_map = _as_dict(self.column_roles.get(role_key))
            item = role_map.get(col) or role_map.get(normalized)
            if isinstance(item, Mapping) and item.get("format"):
                return str(item["format"])
        return _default_format_for_metric(normalized)

    def _format_value(self, value: Any, col: str) -> str:
        fmt = self._format_for_column(col)
        if value is None:
            return "-"
        number = _to_number(value)
        if number is None:
            return str(value)
        if fmt in {"integer", "integer_with_sign"}:
            sign = "+" if fmt == "integer_with_sign" and number > 0 else ""
            return f"{sign}{int(round(number)):,}"
        if fmt.startswith("percentage") or "percentage" in _normalize_column_name(col):
            return f"{number:.2f}%"
        if fmt in {"decimal_2", "number_2"}:
            return f"{number:.2f}"
        return str(value)

    def _build_formatting(self, *, metric_columns: list[str], dimension_columns: list[str], visualization_type: str) -> JsonDict:
        return {
            "locale": self.config.locale,
            "direction": self.config.direction,
            "visualization_type": visualization_type,
            "dimensions": {col: {"label_fa": self._label_for_column(col), "format": self._format_for_column(col)} for col in dimension_columns},
            "metrics": {col: {"label_fa": self._label_for_column(col), "format": self._format_for_column(col)} for col in metric_columns},
        }

    def _build_subtitle(self, *, visual_type: str, rows: list[JsonDict]) -> str | None:
        count = len(rows)
        if visual_type == VIS_STATUS:
            return None
        if count == 1:
            return "خروجی بر اساس View تحلیلی منابع انسانی محاسبه شده است."
        return f"{count} ردیف قابل نمایش بر اساس View تحلیلی منابع انسانی."

    def _build_chart_description(self, *, visualization_type: str, x_axis: str, series: list[str]) -> str:
        x_label = self._label_for_column(x_axis)
        y_label = self._label_for_column(series[0]) if series else "شاخص"
        if visualization_type == VIS_LINE:
            return f"روند {y_label} بر اساس {x_label}."
        if visualization_type == VIS_PIE:
            return f"سهم {y_label} به تفکیک {x_label}."
        return f"مقایسه {y_label} به تفکیک {x_label}."

    def _build_data_limitations(self, *, visualization_type: str, dimension_columns: list[str], rows: list[JsonDict]) -> list[str]:
        notes: list[str] = []
        if len(rows) >= self.config.max_chart_rows and visualization_type in {VIS_BAR, VIS_HORIZONTAL_BAR, VIS_LINE, VIS_PIE}:
            notes.append(
                f"برای خوانایی نمودار، حداکثر {self.config.max_chart_rows} ردیف نمایش داده شده است.")
        if any(_normalize_column_name(col) == "city" for col in dimension_columns):
            notes.append("تحلیل سطح شهر در MVP فعلی Data Gap محسوب می‌شود.")
        return notes

    def _infer_sort(self, *, visualization_type: str, x_axis: str | None) -> str | None:
        if visualization_type == VIS_LINE or _normalize_column_name(x_axis or "") == "hire_year":
            return "x_axis_asc"
        if visualization_type in {VIS_BAR, VIS_HORIZONTAL_BAR, VIS_PIE}:
            return "metric_desc_or_sql_order"
        return None

    def _infer_top_n(self, *, visualization_type: str, rows: list[JsonDict]) -> int | None:
        if visualization_type in {VIS_BAR, VIS_HORIZONTAL_BAR, VIS_LINE, VIS_PIE}:
            return len(rows)
        return None

    # ------------------------------------------------------------------
    # Utility internals
    # ------------------------------------------------------------------

    def _resolve_route(self, *, route: str | None, context: JsonDict, status_payload: JsonDict) -> str:
        value = self._first_non_empty(
            route,
            status_payload.get("route"),
            context.get("route"),
            _get_nested(context, "route_result", "route"),
            _get_nested(context, "intent_result", "route"),
        )
        return str(value or ROUTE_SQL).upper()

    def _resolve_status(self, *, status: str | None, context: JsonDict, status_payload: JsonDict) -> str:
        value = self._first_non_empty(
            status,
            status_payload.get("status"),
            status_payload.get("validation_status"),
            status_payload.get("execution_status"),
            context.get("status"),
            _get_nested(context, "query_result", "status"),
            _get_nested(context, "sql_validation", "status"),
            _get_nested(context, "validation_result", "status"),
        )
        value = str(value or STATUS_SUCCESS).upper()
        if value in {STATUS_VALID, STATUS_SUPPORTED, "OK", "DONE"}:
            return STATUS_SUCCESS
        return value

    def _extract_embedded_status(self, rows: list[JsonDict]) -> str | None:
        if len(rows) != 1:
            return None
        row = rows[0]
        status = row.get("status") or row.get("STATUS")
        if isinstance(status, str) and status.upper() in NON_DATA_STATUSES:
            return status.upper()
        return None

    def _dimension_values_are_long(self, rows: list[JsonDict], col: str) -> bool:
        values = [str(row.get(col, "")) for row in rows]
        values = [v for v in values if v]
        if not values:
            return False
        avg_len = sum(len(v) for v in values) / len(values)
        return avg_len >= self.config.max_label_length_for_vertical_bar

    def _find_count_metric(self, metric_columns: list[str]) -> str | None:
        for col in metric_columns:
            if _normalize_column_name(col) in {"employee_count", "count", "actual_headcount", "hiring_count", "hire_count", "contractor_count"}:
                return col
        for col in metric_columns:
            if "count" in _normalize_column_name(col):
                return col
        return None

    def _first_non_empty(self, *values: Any) -> Any:
        for value in values:
            if value is not None and value != "":
                return value
        return None


# ----------------------------------------------------------------------
# Module-level factory
# ----------------------------------------------------------------------

_chart_builder_singleton: ChartBuilder | None = None


def get_chart_builder(*, metadata_dir: str | Path | None = None, metadata_service: Any | None = None, reset: bool = False) -> ChartBuilder:
    """Return a reusable ChartBuilder instance."""
    global _chart_builder_singleton
    if reset or _chart_builder_singleton is None or metadata_service is not None:
        _chart_builder_singleton = ChartBuilder(
            metadata_dir=metadata_dir, metadata_service=metadata_service)
    return _chart_builder_singleton


# ----------------------------------------------------------------------
# Generic helpers
# ----------------------------------------------------------------------

class _suppress_exceptions:
    def __enter__(self) -> None:
        return None

    def __exit__(self, exc_type: Any, exc: Any, tb: Any) -> bool:
        return True


def _to_mapping(obj: Any) -> JsonDict:
    if obj is None:
        return {}
    if isinstance(obj, Mapping):
        return dict(obj)
    if is_dataclass(obj):
        return asdict(obj)
    if hasattr(obj, "to_dict") and callable(obj.to_dict):
        with _suppress_exceptions():
            result = obj.to_dict()
            if isinstance(result, Mapping):
                return dict(result)
    if hasattr(obj, "__dict__"):
        return dict(obj.__dict__)
    return {}


def _as_dict(obj: Any) -> JsonDict:
    return dict(obj) if isinstance(obj, Mapping) else {}


def _get_nested(obj: Mapping[str, Any], *keys: str) -> Any:
    current: Any = obj
    for key in keys:
        if not isinstance(current, Mapping):
            return None
        current = current.get(key)
    return current


def _json_safe(value: Any) -> Any:
    if isinstance(value, Decimal):
        return float(value)
    if isinstance(value, (datetime, date)):
        return value.isoformat()
    if isinstance(value, bytes):
        return value.decode("utf-8", errors="replace")
    if isinstance(value, Mapping):
        return {str(k): _json_safe(v) for k, v in value.items()}
    if isinstance(value, Sequence) and not isinstance(value, (str, bytes, bytearray)):
        return [_json_safe(v) for v in value]
    if isinstance(value, float) and (math.isnan(value) or math.isinf(value)):
        return None
    return value


def _json_safe_dict(row: Mapping[str, Any]) -> JsonDict:
    return {str(k): _json_safe(v) for k, v in row.items()}


def _normalize_column_name(value: str | None) -> str:
    if not value:
        return ""
    return str(value).strip().replace("\u200c", "_").replace(" ", "_").lower()


def _normalize_visualization_type(value: str | None) -> str | None:
    if not value:
        return None
    normalized = str(value).strip().lower().replace("-", "_").replace(" ", "_")
    aliases = {
        "kpi": VIS_KPI_CARD,
        "card": VIS_KPI_CARD,
        "metric_card": VIS_KPI_CARD,
        "cards": VIS_KPI_CARD_GROUP,
        "kpi_group": VIS_KPI_CARD_GROUP,
        "kpi_card_group": VIS_KPI_CARD_GROUP,
        "table": VIS_TABLE,
        "bar": VIS_BAR,
        "bar_chart": VIS_BAR,
        "horizontal_bar": VIS_HORIZONTAL_BAR,
        "horizontal_bar_chart": VIS_HORIZONTAL_BAR,
        "line": VIS_LINE,
        "line_chart": VIS_LINE,
        "pie": VIS_PIE,
        "pie_chart": VIS_PIE,
        "stacked_bar": VIS_STACKED_BAR,
        "stacked_bar_chart": VIS_STACKED_BAR,
        "status": VIS_STATUS,
        "status_message": VIS_STATUS,
    }
    return aliases.get(normalized)


def _route_for_status(status: str) -> str:
    status = (status or "").upper()
    if status == STATUS_DATA_GAP:
        return ROUTE_GAP
    if status in {STATUS_ACCESS_DENIED, STATUS_OUT_OF_SCOPE, STATUS_SQL_VALIDATION_FAILED, "REJECTED"}:
        return ROUTE_REJECT
    if status == STATUS_NEEDS_CLARIFICATION:
        return ROUTE_NEEDS_CLARIFICATION
    return ROUTE_SQL


def _dedupe(values: Sequence[str]) -> list[str]:
    seen: set[str] = set()
    out: list[str] = []
    for value in values:
        if not value:
            continue
        text = str(value)
        if text not in seen:
            out.append(text)
            seen.add(text)
    return out


def _to_string_list(value: Any) -> list[str]:
    if value is None:
        return []
    if isinstance(value, str):
        return [value]
    if isinstance(value, Sequence) and not isinstance(value, (str, bytes, bytearray)):
        return [str(v) for v in value if v is not None]
    return [str(value)]


def _is_number(value: Any) -> bool:
    if isinstance(value, bool):
        return False
    if isinstance(value, (int, float, Decimal)):
        return not (isinstance(value, float) and (math.isnan(value) or math.isinf(value)))
    if isinstance(value, str):
        try:
            float(value.replace(",", ""))
            return True
        except Exception:
            return False
    return False


def _to_number(value: Any) -> float | None:
    if isinstance(value, bool):
        return None
    if isinstance(value, Decimal):
        return float(value)
    if isinstance(value, (int, float)):
        if isinstance(value, float) and (math.isnan(value) or math.isinf(value)):
            return None
        return float(value)
    if isinstance(value, str):
        try:
            return float(value.replace(",", ""))
        except Exception:
            return None
    return None


def _column_is_numeric(col: str, rows: list[JsonDict]) -> bool:
    values = [row.get(col) for row in rows if row.get(col) is not None]
    if not values:
        return False
    sample = values[:20]
    return all(_is_number(v) for v in sample)


def _default_format_for_metric(col: str) -> str:
    key = _normalize_column_name(col)
    if "percentage" in key or "percent" in key:
        return "percentage_2_decimals"
    if "avg" in key or "average" in key or "age" in key or "service_years" in key:
        return "decimal_2"
    if "gap" in key:
        return "integer_with_sign"
    if "count" in key or "headcount" in key or "total" in key:
        return "integer"
    return "raw"


def _chart_value_format(fmt: str) -> str:
    if fmt in {"integer", "integer_with_sign"}:
        return "integer"
    if fmt.startswith("percentage"):
        return "raw"
    if fmt.startswith("decimal") or fmt.startswith("number"):
        return "raw"
    return "raw"


if __name__ == "__main__":  # pragma: no cover - manual smoke test
    builder = ChartBuilder(metadata_dir=Path(__file__).resolve().parent)
    sample = [
        {"gender": "زن", "employee_count": 105, "percentage": 14.0},
        {"gender": "مرد", "employee_count": 645, "percentage": 86.0},
    ]
    print(builder.build(rows=sample, intent_id="employee_count_by_gender",
          route="SQL", status="SUCCESS"))
