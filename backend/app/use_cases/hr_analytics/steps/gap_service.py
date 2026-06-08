from __future__ import annotations

import asyncio
import hashlib
import json
import os
import re
import time
from collections.abc import Mapping, Sequence
from dataclasses import asdict, dataclass, field, is_dataclass
from datetime import UTC, datetime
from pathlib import Path
from threading import Lock
from typing import Any

from app.infrastructure.metadata.service import get_metadata_service

"""
gap_service.py
--------------
Gap Manager for HR BI Assistant Phase 2 / Controlled SQL-based MVP.


Purpose:
    - Register Data Gap / Knowledge Gap / Business Rule Gap cases in a stable shape.
    - Return a safe DATA_GAP response payload for llm_orchestrator.py and response_builder.py.
    - Keep gap creation idempotent so repeated user questions do not create noisy duplicates.
    - Work with or without a database in the MVP by supporting a JSONL registry file.

Typical calls from llm_orchestrator.py:
    await gap_service.arun(gap=gap_payload, context=context, metadata=metadata_service)

Supported public methods:
    create_gap(...)
    register(...)
    run(...)
    arun(...)
    __call__(...)

Design principles:
    - Never fabricate an answer for a gap question.
    - Explain what is missing and what is needed next.
    - Do not store or return sensitive employee-level data.
    - Prefer deterministic gap_id for duplicate detection.
"""

JsonDict = dict[str, Any]


ROUTE_GAP = "GAP"
ROUTE_REJECT = "REJECT"
STATUS_DATA_GAP = "DATA_GAP"
STATUS_KNOWLEDGE_GAP = "KNOWLEDGE_GAP"
STATUS_BUSINESS_RULE_GAP = "BUSINESS_RULE_GAP"
STATUS_ACCESS_DENIED = "ACCESS_DENIED"
STATUS_OUT_OF_SCOPE = "OUT_OF_SCOPE"
STATUS_NEEDS_CLARIFICATION = "NEEDS_CLARIFICATION"

GAP_TYPE_DATA = "DATA_GAP"
GAP_TYPE_KNOWLEDGE = "KNOWLEDGE_GAP"
GAP_TYPE_BUSINESS_RULE = "BUSINESS_RULE_GAP"
GAP_TYPE_DEFINITION = "DEFINITION_GAP"
GAP_TYPE_POLICY = "POLICY_GAP"
GAP_TYPE_UNSUPPORTED_ANALYTICS = "UNSUPPORTED_ANALYTICS_GAP"

DEFAULT_STATUS_SQL = "SELECT 'DATA_GAP' AS status;"

SENSITIVE_TERMS = {
    "کد ملی",
    "شماره ملی",
    "شماره پرسنلی",
    "نام و نام خانوادگی",
    "نام کارکنان",
    "اسامی کارکنان",
    "حقوق هر فرد",
    "شماره تماس",
    "موبایل",
    "آدرس",
    "حساب بانکی",
    "national_id",
    "personnel_number",
    "first_name",
    "last_name",
    "phone_number",
    "address",
    "bank_account",
    "insurance_number",
}

OUT_OF_SCOPE_TERMS = {
    "فروش",
    "درآمد",
    "سود",
    "زیان",
    "مشتری",
    "بازاریابی",
    "انبار",
    "تولید",
    "حسابداری",
    "مالیات",
}

KNOWN_GAP_RULES: list[JsonDict] = [
    {
        "gap_code": "GAP_CITY_LEVEL_ANALYSIS",
        "gap_type": GAP_TYPE_DATA,
        "intent": "city_level_analysis",
        "terms": ["شهر", "شهری", "سطح شهر", "هر شهر"],
        "reason_fa": "در داده MVP فعلی، اطلاعات شهر قابل اتکا نیست.",
        "missing_data": ["city معتبر و تکمیل‌شده", "تعریف سطح مکانی قابل اعتماد"],
        "required_action": "تکمیل و اعتبارسنجی داده شهر در جدول محل خدمت یا View تحلیلی.",
        "severity": "medium",
    },
    {
        "gap_code": "GAP_NEAR_RETIREMENT_RULE",
        "gap_type": GAP_TYPE_BUSINESS_RULE,
        "intent": "near_retirement_analysis",
        "terms": ["بازنشستگی", "آستانه بازنشستگی", "نزدیک بازنشستگی", "ریسک بازنشستگی"],
        "reason_fa": "قانون رسمی بازنشستگی برای MVP فعلی تعریف نشده است.",
        "missing_data": ["قانون سن بازنشستگی", "قانون سابقه بازنشستگی", "استثناهای جنسیت/نوع استخدام/سازمان"],
        "required_action": "تعریف رسمی بازنشستگی توسط HR و تبدیل آن به Rule یا Metadata.",
        "severity": "high",
    },
    {
        "gap_code": "GAP_CONTRACTOR_PRODUCTIVITY",
        "gap_type": GAP_TYPE_DATA,
        "intent": "contractor_productivity_analysis",
        "terms": ["بهره وری پیمانکار", "بهره‌وری پیمانکار", "عملکرد پیمانکار", "کیفیت پیمانکار"],
        "reason_fa": "داده بهره‌وری یا شاخص عملکرد پیمانکارها در MVP فعلی وجود ندارد.",
        "missing_data": ["شاخص عملکرد پیمانکار", "خروجی کار", "کیفیت خدمت", "هزینه یا SLA"],
        "required_action": "تعریف KPI بهره‌وری پیمانکار و اتصال داده عملکرد/هزینه/SLA.",
        "severity": "medium",
    },
    {
        "gap_code": "GAP_MONTHLY_HIRING",
        "gap_type": GAP_TYPE_DATA,
        "intent": "monthly_hiring_trend",
        "terms": ["جذب ماهانه", "هر ماه", "ماهانه", "روند ماه"],
        "reason_fa": "تحلیل ماهانه جذب در MVP فعلی به تقویم/ماه شمسی معتبر نیاز دارد.",
        "missing_data": ["ماه شمسی جذب", "تقویم شمسی تکمیل‌شده", "استانداردسازی hire_date"],
        "required_action": "تکمیل hr_calendar یا افزودن ستون‌های سال/ماه شمسی قابل اعتماد به View.",
        "severity": "medium",
    },
    {
        "gap_code": "GAP_WORKLOAD_ALIGNMENT",
        "gap_type": GAP_TYPE_DATA,
        "intent": "hiring_workload_alignment",
        "terms": ["افزایش کار", "حجم کار", "رشد کار", "هماهنگ بوده", "نیاز کاری"],
        "reason_fa": "داده حجم کار یا شاخص تقاضای نیروی انسانی در MVP فعلی وجود ندارد.",
        "missing_data": ["حجم کار", "تعداد پروژه/تراکنش/خدمت", "شاخص تقاضای نیرو", "هدف جذب"],
        "required_action": "تعریف منبع داده حجم کار و KPI تطابق جذب با تقاضا.",
        "severity": "medium",
    },
    {
        "gap_code": "GAP_TRAINING_NEED_ANALYSIS",
        "gap_type": GAP_TYPE_BUSINESS_RULE,
        "intent": "training_need_analysis",
        "terms": ["نیاز آموزشی", "دوره تخصصی", "آموزش", "کمبود تخصص"],
        "reason_fa": "تحلیل نیاز آموزشی به تعریف مهارت، شغل هدف و شکاف مهارتی نیاز دارد.",
        "missing_data": ["مهارت‌های موردنیاز هر شغل", "دوره‌های آموزشی", "سوابق آموزشی", "تعریف شکاف مهارتی"],
        "required_action": "تعریف چارچوب مهارت و اتصال سوابق آموزشی/مهارتی کارکنان.",
        "severity": "medium",
    },
    {
        "gap_code": "GAP_AGING_STRUCTURE_ANALYSIS",
        "gap_type": GAP_TYPE_BUSINESS_RULE,
        "intent": "workforce_aging_analysis",
        "terms": ["سالخوردگی", "پیر شدن", "ساختار سنی", "به سمت سالخوردگی"],
        "reason_fa": "تحلیل سالخوردگی نیروی انسانی به آستانه‌ها و شاخص رسمی ریسک سنی نیاز دارد.",
        "missing_data": ["تعریف رسمی ریسک سالخوردگی", "آستانه‌های سن/سابقه", "روند چندساله قابل مقایسه"],
        "required_action": "تعریف KPI ریسک سنی و آستانه‌های هشدار توسط HR.",
        "severity": "medium",
    },
    {
        "gap_code": "GAP_ADVANCED_HEADCOUNT_BALANCE",
        "gap_type": GAP_TYPE_BUSINESS_RULE,
        "intent": "workforce_balance_analysis",
        "terms": ["تعادل نیروی انسانی", "متوازن", "توازن", "بالانس", "چارت سازمانی و واقعیت"],
        "reason_fa": "تحلیل مدیریتی تعادل نیروی انسانی به تعریف شاخص تعادل و آستانه تصمیم‌گیری نیاز دارد.",
        "missing_data": ["تعریف شاخص تعادل", "ظرفیت مصوب معتبر", "وزن اهمیت واحدها", "آستانه کمبود/مازاد"],
        "required_action": "تعریف رسمی شاخص تعادل و قواعد محاسبه کمبود/مازاد در Metadata.",
        "severity": "medium",
    },
]


@dataclass
class GapServiceConfig:
    """Runtime configuration for GapService."""

    project: str = "HR BI Assistant"
    phase: str = "Controlled SQL-based MVP"
    source_name: str = "gap_service"
    default_gap_status: str = STATUS_DATA_GAP
    default_route: str = ROUTE_GAP
    default_registry_filename: str = "gap_registry.jsonl"
    default_metadata_dir: str | None = None
    persist_to_jsonl: bool = True
    allow_duplicate_records: bool = False
    duplicate_window_seconds: int = 86_400
    max_question_length: int = 500
    max_registry_records_read: int = 10_000
    include_status_sql: bool = True
    redact_sensitive_terms: bool = True
    default_created_by: str = "llm_orchestrator"


@dataclass
class GapRecord:
    """A normalized gap registry record."""

    gap_id: str
    status: str
    route: str
    gap_type: str
    gap_code: str | None
    question: str
    normalized_question: str
    intent: str | None = None
    report_id: str | None = None
    kpi_id: str | None = None
    reason: str | None = None
    reason_fa: str | None = None
    missing_data: list[str] = field(default_factory=list)
    required_action: str | None = None
    suggested_next_step: str | None = None
    severity: str = "medium"
    priority: str = "medium"
    user_role: str | None = None
    created_by: str = "llm_orchestrator"
    created_at: str = field(default_factory=lambda: utc_now_iso())
    occurrence_count: int = 1
    last_seen_at: str | None = None
    source: str = "gap_service"
    sql: str | None = DEFAULT_STATUS_SQL
    metadata: JsonDict = field(default_factory=dict)

    def to_dict(self) -> JsonDict:
        return asdict(self)


class GapServiceError(RuntimeError):
    """Base exception for gap service failures."""


class GapStorageError(GapServiceError):
    """Raised when gap persistence fails."""


class GapService:
    """
    Register and shape DATA_GAP / KNOWLEDGE_GAP outcomes.

    The class intentionally has no hard database dependency. In the MVP, it can
    persist to JSONL, and later the same output can be inserted into a PostgreSQL
    gap_registry table by wrapping `create_gap` or replacing `_save_record`.
    """

    def __init__(
        self,
        *,
        metadata_service: Any | None = None,
        metadata_dir: str | Path | None = None,
        registry_path: str | Path | None = None,
        persist_to_jsonl: bool = True,
        allow_duplicate_records: bool = False,
        duplicate_window_seconds: int = 86_400,
    ) -> None:
        if metadata_service is not None:
            self.metadata = metadata_service
        elif get_metadata_service is not None:
            try:
                self.metadata = get_metadata_service(
                    metadata_dir=metadata_dir, strict=False)
            except Exception:
                self.metadata = None
        else:
            self.metadata = None

        self.config = GapServiceConfig(
            default_metadata_dir=str(
                metadata_dir) if metadata_dir is not None else None,
            persist_to_jsonl=bool(persist_to_jsonl),
            allow_duplicate_records=bool(allow_duplicate_records),
            duplicate_window_seconds=int(duplicate_window_seconds),
        )

        self.registry_path = Path(
            registry_path) if registry_path else self._default_registry_path(metadata_dir)
        self._lock = Lock()
        self._cache_by_id: dict[str, GapRecord] = {}
        self._loaded = False

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def create_gap(
        self,
        gap: Mapping[str, Any] | None = None,
        *,
        question: str | None = None,
        normalized_question: str | None = None,
        intent: str | None = None,
        reason: str | None = None,
        missing_data: Sequence[Any] | str | None = None,
        context: Any | None = None,
        metadata: Any | None = None,
        user_role: str | None = None,
        created_by: str | None = None,
        **kwargs: Any,
    ) -> JsonDict:
        """Create or update a gap record and return a normalized DATA_GAP payload."""
        started = time.perf_counter()
        payload = dict(gap or {})
        payload.update({k: v for k, v in kwargs.items() if v is not None})
        if question is not None:
            payload["question"] = question
        if normalized_question is not None:
            payload["normalized_question"] = normalized_question
        if intent is not None:
            payload["intent"] = intent
        if reason is not None:
            payload["reason"] = reason
        if missing_data is not None:
            payload["missing_data"] = missing_data
        if user_role is not None:
            payload["user_role"] = user_role
        if created_by is not None:
            payload["created_by"] = created_by

        context_dict = object_to_dict(context)
        metadata_service = metadata or self.metadata

        # Fill from context if the orchestrator passed RequestContext.
        payload = self._merge_context_payload(payload, context_dict)

        question_text = str(payload.get("question") or "").strip()
        if not question_text and context_dict.get("question"):
            question_text = str(context_dict["question"]).strip()
        normalized = str(payload.get("normalized_question")
                         or normalize_persian_text(question_text)).strip()

        rule_match = self._match_known_gap_rule(normalized, payload)
        metadata_match = self._match_metadata_gap(
            normalized, payload, metadata_service)
        effective_rule = {**rule_match, **
                          metadata_match} if rule_match or metadata_match else {}

        gap_type = str(payload.get("gap_type") or effective_rule.get(
            "gap_type") or self._infer_gap_type(normalized, payload))
        status = self._status_for_gap_type(gap_type)
        gap_code = payload.get("gap_code") or effective_rule.get(
            "gap_code") or self._build_gap_code(gap_type, payload.get("intent"))

        missing_items = normalize_list(
            payload.get("missing_data")
            or payload.get("missing_fields")
            or payload.get("required_data")
            or effective_rule.get("missing_data")
        )
        reason_fa = first_non_empty(
            payload.get("reason_fa"),
            effective_rule.get("reason_fa"),
            payload.get("reason"),
            self._default_reason_fa(gap_type),
        )
        reason_text = first_non_empty(payload.get(
            "reason"), reason_fa, self._default_reason_en(gap_type))
        required_action = first_non_empty(
            payload.get("required_action"),
            effective_rule.get("required_action"),
            self._default_required_action(gap_type, missing_items),
        )
        suggested_next_step = first_non_empty(
            payload.get("suggested_next_step"),
            self._build_suggested_next_step(
                gap_type, missing_items, required_action),
        )

        clean_question = redact_sensitive_text(
            question_text) if self.config.redact_sensitive_terms else question_text
        clean_normalized = redact_sensitive_text(
            normalized) if self.config.redact_sensitive_terms else normalized

        record = GapRecord(
            gap_id=self._make_gap_id(
                clean_normalized, payload.get("intent"), gap_code),
            status=status,
            route=ROUTE_GAP,
            gap_type=gap_type,
            gap_code=str(gap_code) if gap_code else None,
            question=truncate(clean_question, self.config.max_question_length),
            normalized_question=truncate(
                clean_normalized, self.config.max_question_length),
            intent=as_optional_str(payload.get(
                "intent") or payload.get("intent_id")),
            report_id=as_optional_str(payload.get("report_id")),
            kpi_id=as_optional_str(payload.get("kpi_id")),
            reason=as_optional_str(reason_text),
            reason_fa=as_optional_str(reason_fa),
            missing_data=missing_items,
            required_action=as_optional_str(required_action),
            suggested_next_step=as_optional_str(suggested_next_step),
            severity=str(payload.get("severity") or effective_rule.get(
                "severity") or self._infer_severity(gap_type, normalized)),
            priority=str(payload.get("priority") or effective_rule.get(
                "priority") or self._infer_priority(gap_type, payload)),
            user_role=as_optional_str(payload.get(
                "user_role") or context_dict.get("user_role")),
            created_by=str(payload.get("created_by")
                           or self.config.default_created_by),
            source=self.config.source_name,
            sql=DEFAULT_STATUS_SQL if self.config.include_status_sql else None,
            metadata={
                "project": self.config.project,
                "phase": self.config.phase,
                "matched_rule": effective_rule.get("gap_code"),
                "matched_terms": effective_rule.get("matched_terms", []),
                "route_source": payload.get("route_source") or payload.get("decision_source"),
                "raw_status": payload.get("status"),
            },
        )

        duplicate_of: str | None = None
        gap_logged = False
        try:
            saved_record, duplicate_of = self._save_record(record)
            record = saved_record
            gap_logged = True
        except Exception as exc:
            # The orchestrator should continue safely even when registry persistence fails.
            return self._response_payload(
                record=record,
                gap_logged=False,
                duplicate_of=None,
                duration_ms=elapsed_ms(started),
                warnings=[],
                errors=[f"gap_registry_write_failed: {exc}"],
            )

        return self._response_payload(
            record=record,
            gap_logged=gap_logged,
            duplicate_of=duplicate_of,
            duration_ms=elapsed_ms(started),
            warnings=[],
            errors=[],
        )

    def register(self, *args: Any, **kwargs: Any) -> JsonDict:
        """Alias for create_gap."""
        return self.create_gap(*args, **kwargs)

    def run(self, *args: Any, **kwargs: Any) -> JsonDict:
        """Alias for orchestrator compatibility."""
        return self.create_gap(*args, **kwargs)

    async def arun(self, *args: Any, **kwargs: Any) -> JsonDict:
        """Async wrapper for orchestrator compatibility."""
        return await asyncio.to_thread(self.create_gap, *args, **kwargs)

    def __call__(self, *args: Any, **kwargs: Any) -> JsonDict:
        return self.create_gap(*args, **kwargs)

    def list_gaps(
        self,
        *,
        status: str | None = None,
        gap_type: str | None = None,
        intent: str | None = None,
        limit: int = 100,
    ) -> list[JsonDict]:
        """Return recent gap records from cache/registry."""
        self._ensure_loaded()
        records = list(self._cache_by_id.values())
        records.sort(
            key=lambda r: r.last_seen_at or r.created_at, reverse=True)
        filtered: list[GapRecord] = []
        for record in records:
            if status and record.status != status:
                continue
            if gap_type and record.gap_type != gap_type:
                continue
            if intent and record.intent != intent:
                continue
            filtered.append(record)
            if len(filtered) >= limit:
                break
        return [r.to_dict() for r in filtered]

    def search_gaps(self, query: str, *, limit: int = 20) -> list[JsonDict]:
        """Simple local search over question/reason/missing_data."""
        self._ensure_loaded()
        q = normalize_persian_text(query)
        scored: list[tuple[int, GapRecord]] = []
        for record in self._cache_by_id.values():
            text = normalize_persian_text(
                " ".join(
                    [
                        record.question,
                        record.normalized_question,
                        record.reason or "",
                        record.reason_fa or "",
                        " ".join(record.missing_data),
                        record.intent or "",
                    ]
                )
            )
            score = sum(1 for token in q.split() if token and token in text)
            if q in text:
                score += 5
            if score:
                scored.append((score, record))
        scored.sort(key=lambda item: (
            item[0], item[1].last_seen_at or item[1].created_at), reverse=True)
        return [record.to_dict() for _, record in scored[:limit]]

    def health_check(self) -> JsonDict:
        """Lightweight operational check for gap registry."""
        try:
            self._ensure_loaded()
            writable = True
            if self.config.persist_to_jsonl:
                self.registry_path.parent.mkdir(parents=True, exist_ok=True)
                writable = os.access(self.registry_path.parent, os.W_OK)
            return {
                "ok": True,
                "service": self.config.source_name,
                "persist_to_jsonl": self.config.persist_to_jsonl,
                "registry_path": str(self.registry_path),
                "records_loaded": len(self._cache_by_id),
                "writable": writable,
            }
        except Exception as exc:
            return {
                "ok": False,
                "service": self.config.source_name,
                "registry_path": str(self.registry_path),
                "error": str(exc),
            }

    # ------------------------------------------------------------------
    # Matching and shaping
    # ------------------------------------------------------------------

    def _merge_context_payload(self, payload: JsonDict, context_dict: JsonDict) -> JsonDict:
        merged = dict(payload)
        if not context_dict:
            return merged

        for key in ["question", "normalized_question"]:
            if not merged.get(key) and context_dict.get(key):
                merged[key] = context_dict[key]

        route_result = to_mapping(context_dict.get("route_result"))
        intent_result = to_mapping(context_dict.get("intent_result"))
        validation_result = to_mapping(context_dict.get("validation_result"))
        semantic_result = to_mapping(context_dict.get("semantic_result"))

        for source in (route_result, intent_result, validation_result, semantic_result):
            if not source:
                continue
            for key in [
                "intent",
                "intent_id",
                "report_id",
                "kpi_id",
                "reason",
                "reason_fa",
                "missing_data",
                "gap_type",
                "gap_code",
                "severity",
                "priority",
                "status",
                "route_source",
                "decision_source",
            ]:
                if not merged.get(key) and source.get(key):
                    merged[key] = source[key]

        return merged

    def _match_known_gap_rule(self, normalized_question: str, payload: Mapping[str, Any]) -> JsonDict:
        intent = str(payload.get("intent") or payload.get("intent_id") or "")
        best: JsonDict = {}
        best_score = 0
        for rule in KNOWN_GAP_RULES:
            score = 0
            matched_terms: list[str] = []
            if intent and rule.get("intent") == intent:
                score += 5
            for term in rule.get("terms", []) or []:
                t = normalize_persian_text(str(term))
                if t and t in normalized_question:
                    score += 2
                    matched_terms.append(str(term))
            if score > best_score:
                best_score = score
                best = {**rule, "matched_terms": matched_terms,
                        "match_score": score}
        return best if best_score > 0 else {}

    def _match_metadata_gap(self, normalized_question: str, payload: Mapping[str, Any], metadata_service: Any | None) -> JsonDict:
        """Try to enrich with semantic_layer/access_policies gaps when metadata is available."""
        if metadata_service is None:
            return {}

        matches: list[JsonDict] = []

        # MetadataService in this project exposes .bundle or individual dictionaries depending on usage.
        try:
            semantic = getattr(metadata_service, "semantic_layer", None) or getattr(
                getattr(metadata_service, "bundle", None), "semantic_layer", None)
            if not semantic and hasattr(metadata_service, "get_bundle"):
                semantic = metadata_service.get_bundle().semantic_layer
            for item in (semantic or {}).get("data_gap_semantics", []) or []:
                item_terms = item.get("terms") or item.get(
                    "aliases") or item.get("trigger_terms") or []
                score = 0
                matched_terms = []
                for term in item_terms:
                    t = normalize_persian_text(str(term))
                    if t and t in normalized_question:
                        score += 2
                        matched_terms.append(str(term))
                if payload.get("intent") and item.get("intent") == payload.get("intent"):
                    score += 5
                if score:
                    matches.append(
                        {**item, "matched_terms": matched_terms, "match_score": score})
        except Exception:
            pass

        try:
            access = getattr(metadata_service, "access_policies", None) or getattr(
                getattr(metadata_service, "bundle", None), "access_policies", None)
            if not access and hasattr(metadata_service, "get_bundle"):
                access = metadata_service.get_bundle().access_policies
            known_gaps = ((access or {}).get("data_gap_policy")
                          or {}).get("known_data_gaps", []) or []
            for item in known_gaps:
                item_terms = item.get("terms") or item.get(
                    "triggers") or item.get("questions") or []
                score = 0
                matched_terms = []
                for term in item_terms:
                    t = normalize_persian_text(str(term))
                    if t and t in normalized_question:
                        score += 2
                        matched_terms.append(str(term))
                if payload.get("intent") and item.get("intent") == payload.get("intent"):
                    score += 5
                if score:
                    matches.append(
                        {**item, "matched_terms": matched_terms, "match_score": score})
        except Exception:
            pass

        if not matches:
            return {}
        matches.sort(key=lambda m: int(
            m.get("match_score") or 0), reverse=True)
        top = matches[0]

        # Normalize likely key names from metadata files.
        normalized: JsonDict = {
            "gap_code": top.get("gap_code") or top.get("id") or top.get("name"),
            "gap_type": top.get("gap_type") or top.get("type") or GAP_TYPE_DATA,
            "reason_fa": top.get("reason_fa") or top.get("gap_reason") or top.get("reason") or top.get("description_fa"),
            "missing_data": top.get("missing_data") or top.get("required_data") or top.get("needed_data") or top.get("missing_fields"),
            "required_action": top.get("required_action") or top.get("next_step") or top.get("recommendation"),
            "matched_terms": top.get("matched_terms", []),
            "severity": top.get("severity"),
            "priority": top.get("priority"),
        }
        return {k: v for k, v in normalized.items() if v not in (None, "", [])}

    def _infer_gap_type(self, normalized_question: str, payload: Mapping[str, Any]) -> str:
        text = " ".join([normalized_question, str(payload.get(
            "reason") or ""), str(payload.get("intent") or "")])
        if any(term in text for term in ["قانون", "قاعده", "آستانه", "تعریف", "تعادل", "سالخوردگی", "ریسک"]):
            return GAP_TYPE_BUSINESS_RULE
        if any(term in text for term in ["سیاست", "آیین نامه", "آیین‌نامه", "دستورالعمل"]):
            return GAP_TYPE_POLICY
        if any(term in text for term in ["سند", "تعریف شاخص", "راهنما", "دانش"]):
            return GAP_TYPE_KNOWLEDGE
        if any(term in text for term in ["بهره وری", "بهره‌وری", "تحلیل", "مناسب است", "هماهنگ بوده"]):
            return GAP_TYPE_UNSUPPORTED_ANALYTICS
        return GAP_TYPE_DATA

    def _status_for_gap_type(self, gap_type: str) -> str:
        if gap_type in {GAP_TYPE_KNOWLEDGE, GAP_TYPE_POLICY, GAP_TYPE_DEFINITION}:
            return STATUS_KNOWLEDGE_GAP
        if gap_type == GAP_TYPE_BUSINESS_RULE:
            return STATUS_BUSINESS_RULE_GAP
        return STATUS_DATA_GAP

    def _build_gap_code(self, gap_type: str, intent: Any) -> str:
        cleaned_intent = re.sub(
            r"[^A-Za-z0-9_]+", "_", str(intent or "unknown_intent")).strip("_").upper()
        return f"{gap_type}_{cleaned_intent}"

    def _default_reason_fa(self, gap_type: str) -> str:
        if gap_type == GAP_TYPE_BUSINESS_RULE:
            return "سؤال مرتبط است، اما قانون یا تعریف کسب‌وکاری لازم برای پاسخ دقیق در Metadata فعلی وجود ندارد."
        if gap_type in {GAP_TYPE_KNOWLEDGE, GAP_TYPE_POLICY, GAP_TYPE_DEFINITION}:
            return "سؤال مرتبط است، اما سند یا تعریف قابل استناد برای پاسخ در نسخه فعلی در دسترس نیست."
        if gap_type == GAP_TYPE_UNSUPPORTED_ANALYTICS:
            return "سؤال مرتبط است، اما شاخص‌ها یا داده‌های تحلیلی لازم برای این تحلیل در MVP فعلی وجود ندارد."
        return "سؤال مرتبط است، اما داده لازم برای پاسخ دقیق در نسخه فعلی موجود یا قابل اتکا نیست."

    def _default_reason_en(self, gap_type: str) -> str:
        if gap_type == GAP_TYPE_BUSINESS_RULE:
            return "Required business rule is not defined in current metadata."
        if gap_type in {GAP_TYPE_KNOWLEDGE, GAP_TYPE_POLICY, GAP_TYPE_DEFINITION}:
            return "Required document or knowledge source is not available in current MVP."
        if gap_type == GAP_TYPE_UNSUPPORTED_ANALYTICS:
            return "Required analytical KPI or evidence is not available in current MVP."
        return "Required data is not available or reliable in current MVP."

    def _default_required_action(self, gap_type: str, missing_items: Sequence[str]) -> str:
        if missing_items:
            return "تکمیل/تعریف این موارد: " + "، ".join(str(x) for x in missing_items[:6])
        if gap_type == GAP_TYPE_BUSINESS_RULE:
            return "تعریف Rule رسمی توسط منابع انسانی و افزودن آن به Metadata."
        if gap_type in {GAP_TYPE_KNOWLEDGE, GAP_TYPE_POLICY, GAP_TYPE_DEFINITION}:
            return "افزودن سند معتبر به RAG/Knowledge Base و تعریف منبع پاسخ."
        return "افزودن یا اعتبارسنجی داده موردنیاز در دیتابیس تحلیلی یا View."

    def _build_suggested_next_step(self, gap_type: str, missing_items: Sequence[str], required_action: str | None) -> str:
        if required_action:
            return required_action
        if gap_type == GAP_TYPE_BUSINESS_RULE:
            return "ابتدا تعریف رسمی شاخص/قانون را از HR بگیرید، سپس آن را در Metadata ثبت کنید."
        if gap_type in {GAP_TYPE_KNOWLEDGE, GAP_TYPE_POLICY, GAP_TYPE_DEFINITION}:
            return "سند یا آیین‌نامه مرتبط را به پایگاه دانش اضافه کنید."
        if missing_items:
            return "داده‌های لازم را تکمیل کنید و بعد سؤال را دوباره در Goldset تست کنید."
        return "این مورد در Gap Registry ثبت شود و به بک‌لاگ فاز بعد برود."

    def _infer_severity(self, gap_type: str, normalized_question: str) -> str:
        if gap_type == GAP_TYPE_BUSINESS_RULE and any(term in normalized_question for term in ["بازنشستگی", "ریسک", "چارت"]):
            return "high"
        if gap_type == GAP_TYPE_DATA and any(term in normalized_question for term in ["شهر", "ماهانه"]):
            return "medium"
        return "medium"

    def _infer_priority(self, gap_type: str, payload: Mapping[str, Any]) -> str:
        intent = str(payload.get("intent") or "")
        if intent in {"near_retirement_analysis", "headcount_gap_by_department", "workforce_balance_analysis"}:
            return "high"
        if gap_type == GAP_TYPE_UNSUPPORTED_ANALYTICS:
            return "medium"
        return "medium"

    def _response_payload(
        self,
        *,
        record: GapRecord,
        gap_logged: bool,
        duplicate_of: str | None,
        duration_ms: float,
        warnings: list[str],
        errors: list[str],
    ) -> JsonDict:
        message_fa = self._build_user_message(record)
        payload = record.to_dict()
        payload.update(
            {
                "route": ROUTE_GAP,
                "status": STATUS_DATA_GAP,
                "gap_status": record.status,
                "gap_logged": gap_logged,
                "duplicate_of": duplicate_of,
                "can_execute_sql": False,
                "expected_sql": DEFAULT_STATUS_SQL,
                "sql": DEFAULT_STATUS_SQL,
                "user_message_fa": message_fa,
                "message": message_fa,
                "response_type": "status_message",
                "visualization": "status_message",
                "duration_ms": duration_ms,
                "warnings": warnings,
                "errors": errors,
            }
        )
        return payload

    def _build_user_message(self, record: GapRecord) -> str:
        reason = record.reason_fa or record.reason or self._default_reason_fa(
            record.gap_type)
        missing = ""
        if record.missing_data:
            missing = " داده/تعریف موردنیاز: " + \
                "، ".join(record.missing_data[:5]) + "."
        next_step = f" پیشنهاد: {record.suggested_next_step}" if record.suggested_next_step else ""
        return f"این سؤال مرتبط است، اما در نسخه فعلی داده یا تعریف کافی برای پاسخ دقیق وجود ندارد. {reason}.{missing}{next_step}".replace("..", ".")

    # ------------------------------------------------------------------
    # Persistence
    # ------------------------------------------------------------------

    def _default_registry_path(self, metadata_dir: str | Path | None) -> Path:
        if metadata_dir:
            return Path(metadata_dir) / self.config.default_registry_filename
        env_path = os.getenv("GAP_REGISTRY_PATH")
        if env_path:
            return Path(env_path)
        return Path.cwd() / self.config.default_registry_filename

    def _ensure_loaded(self) -> None:
        if self._loaded:
            return
        with self._lock:
            if self._loaded:
                return
            self._cache_by_id = {}
            if self.registry_path.exists():
                with self.registry_path.open("r", encoding="utf-8") as fh:
                    for i, line in enumerate(fh):
                        if i >= self.config.max_registry_records_read:
                            break
                        line = line.strip()
                        if not line:
                            continue
                        try:
                            data = json.loads(line)
                            record = GapRecord(
                                **filter_gap_record_fields(data))
                            self._cache_by_id[record.gap_id] = record
                        except Exception:
                            continue
            self._loaded = True

    def _save_record(self, record: GapRecord) -> tuple[GapRecord, str | None]:
        self._ensure_loaded()
        with self._lock:
            existing = self._cache_by_id.get(record.gap_id)
            if existing and not self.config.allow_duplicate_records:
                duplicate_of = existing.gap_id
                existing.occurrence_count += 1
                existing.last_seen_at = utc_now_iso()
                # Keep the richest known content.
                if not existing.missing_data and record.missing_data:
                    existing.missing_data = record.missing_data
                if not existing.required_action and record.required_action:
                    existing.required_action = record.required_action
                if not existing.suggested_next_step and record.suggested_next_step:
                    existing.suggested_next_step = record.suggested_next_step
                saved = existing
            else:
                duplicate_of = None
                record.last_seen_at = record.created_at
                saved = record
                self._cache_by_id[record.gap_id] = saved

            if self.config.persist_to_jsonl:
                self.registry_path.parent.mkdir(parents=True, exist_ok=True)
                with self.registry_path.open("a", encoding="utf-8") as fh:
                    fh.write(json.dumps(saved.to_dict(),
                             ensure_ascii=False, sort_keys=True) + "\n")
            return saved, duplicate_of

    def _make_gap_id(self, normalized_question: str, intent: Any, gap_code: Any) -> str:
        base = "|".join([
            normalize_persian_text(str(normalized_question or "")),
            str(intent or ""),
            str(gap_code or ""),
        ])
        digest = hashlib.sha256(base.encode("utf-8")).hexdigest()[:16]
        prefix = re.sub(r"[^A-Za-z0-9_]+", "_",
                        str(gap_code or "GAP")).strip("_").upper()[:32]
        return f"{prefix}_{digest}"


# ----------------------------------------------------------------------
# Helpers
# ----------------------------------------------------------------------


def utc_now_iso() -> str:
    return datetime.now(UTC).replace(microsecond=0).isoformat()


def elapsed_ms(started: float) -> float:
    return round((time.perf_counter() - started) * 1000, 3)


def normalize_persian_text(text: str | None) -> str:
    if not text:
        return ""
    value = str(text)
    value = value.replace("ي", "ی").replace("ك", "ک")
    value = value.replace("ۀ", "ه").replace("ة", "ه")
    value = value.replace("ؤ", "و")
    value = value.replace("أ", "ا").replace("إ", "ا").replace("آ", "ا")
    value = value.replace("‌", " ")
    trans = str.maketrans("۰۱۲۳۴۵۶۷۸۹٠١٢٣٤٥٦٧٨٩", "01234567890123456789")
    value = value.translate(trans)
    value = re.sub(r"\s+", " ", value).strip()
    return value


def redact_sensitive_text(text: str) -> str:
    value = str(text or "")
    for term in sorted(SENSITIVE_TERMS, key=len, reverse=True):
        value = re.sub(re.escape(term),
                       "[REDACTED]", value, flags=re.IGNORECASE)
    # Redact long digit sequences that could be national/personnel identifiers.
    value = re.sub(r"\b\d{8,12}\b", "[REDACTED_NUMBER]", value)
    return value


def truncate(text: str, max_len: int) -> str:
    if len(text) <= max_len:
        return text
    return text[: max_len - 1] + "…"


def as_optional_str(value: Any) -> str | None:
    if value is None:
        return None
    if isinstance(value, str) and not value.strip():
        return None
    return str(value)


def first_non_empty(*values: Any) -> str | None:
    for value in values:
        if value is None:
            continue
        if isinstance(value, str):
            if value.strip():
                return value.strip()
        elif isinstance(value, Sequence) and not isinstance(value, (bytes, bytearray, str)):
            if len(value) > 0:
                return ", ".join(str(x) for x in value)
        else:
            return str(value)
    return None


def normalize_list(value: Sequence[Any] | str | Any | None) -> list[str]:
    if value is None:
        return []
    if isinstance(value, str):
        parts = re.split(r"[,،;؛\n]+", value)
        return [p.strip() for p in parts if p.strip()]
    if isinstance(value, Mapping):
        return [f"{k}: {v}" for k, v in value.items() if v not in (None, "", [])]
    if isinstance(value, Sequence) and not isinstance(value, (bytes, bytearray)):
        out: list[str] = []
        for item in value:
            if item is None:
                continue
            if isinstance(item, str):
                if item.strip():
                    out.append(item.strip())
            elif isinstance(item, Mapping):
                label = item.get("name") or item.get("field") or item.get(
                    "column") or item.get("title") or item.get("description")
                if label:
                    out.append(str(label))
            else:
                out.append(str(item))
        return list(dict.fromkeys(out))
    return [str(value)]


def object_to_dict(obj: Any) -> JsonDict:
    if obj is None:
        return {}
    if isinstance(obj, Mapping):
        return dict(obj)
    if is_dataclass(obj):
        return asdict(obj)
    out: JsonDict = {}
    for key in [
        "question",
        "normalized_question",
        "domain_result",
        "validation_result",
        "semantic_result",
        "intent_result",
        "route_result",
        "user_role",
    ]:
        if hasattr(obj, key):
            try:
                out[key] = getattr(obj, key)
            except Exception:
                pass
    return out


def to_mapping(value: Any) -> JsonDict:
    if value is None:
        return {}
    if isinstance(value, Mapping):
        return dict(value)
    if is_dataclass(value):
        return asdict(value)
    if hasattr(value, "to_dict"):
        try:
            result = value.to_dict()
            return dict(result) if isinstance(result, Mapping) else {}
        except Exception:
            return {}
    return {}


def filter_gap_record_fields(data: Mapping[str, Any]) -> JsonDict:
    allowed = set(GapRecord.__dataclass_fields__.keys())
    filtered = {k: v for k, v in data.items() if k in allowed}
    # Dataclass compatibility defaults for older registry lines.
    filtered.setdefault("gap_id", str(data.get("gap_id") or data.get("id") or hashlib.sha256(
        json.dumps(data, ensure_ascii=False).encode("utf-8")).hexdigest()[:16]))
    filtered.setdefault("status", str(data.get("status") or STATUS_DATA_GAP))
    filtered.setdefault("route", str(data.get("route") or ROUTE_GAP))
    filtered.setdefault("gap_type", str(data.get("gap_type") or GAP_TYPE_DATA))
    filtered.setdefault("gap_code", data.get("gap_code"))
    filtered.setdefault("question", str(data.get("question") or ""))
    filtered.setdefault("normalized_question", str(data.get(
        "normalized_question") or normalize_persian_text(data.get("question") or "")))
    filtered.setdefault(
        "missing_data", normalize_list(data.get("missing_data")))
    filtered.setdefault("created_at", str(
        data.get("created_at") or utc_now_iso()))
    filtered.setdefault("occurrence_count", int(
        data.get("occurrence_count") or 1))
    filtered.setdefault("metadata", dict(data.get("metadata") or {}))
    return filtered


# Backward-compatible factory for FastAPI dependency injection or tests.
_default_gap_service: GapService | None = None


def get_gap_service(
    *,
    metadata_service: Any | None = None,
    metadata_dir: str | Path | None = None,
    registry_path: str | Path | None = None,
    persist_to_jsonl: bool = True,
    reset: bool = False,
) -> GapService:
    global _default_gap_service
    if reset or _default_gap_service is None:
        _default_gap_service = GapService(
            metadata_service=metadata_service,
            metadata_dir=metadata_dir,
            registry_path=registry_path,
            persist_to_jsonl=persist_to_jsonl,
        )
    return _default_gap_service


if __name__ == "__main__":  # pragma: no cover - manual smoke test
    service = GapService(metadata_dir=Path(__file__).parent,
                         registry_path=Path("/tmp/hr_bi_gap_registry.jsonl"))
    samples = [
        "تعداد کارکنان هر شهر چقدر است؟",
        "چند نفر در آستانه بازنشستگی هستند؟",
        "آیا بهره‌وری پیمانکارها مناسب است؟",
    ]
    for q in samples:
        print(json.dumps(service.create_gap(question=q,
              created_by="smoke_test"), ensure_ascii=False, indent=2))
