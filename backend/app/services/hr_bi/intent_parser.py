from __future__ import annotations
import re
import time
from copy import deepcopy
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Iterable, Mapping

"""
intent_parser.py
----------------
Intent Parser for HR BI Assistant Phase 2 / Controlled SQL-based MVP.

Place this file in:
    backend/app/services/intent_parser.py

Purpose:
    Convert a validated Persian HR question into a structured, metadata-grounded
    intent payload that can be consumed by router.py, sql_template_engine.py and
    llm_orchestrator.py.

Design principles for Phase 2:
    - Rule + metadata based; no model training required.
    - Uses the existing Metadata Layer, especially intent_catalog.yaml,
      semantic_layer.yaml, sql_templates.yaml and data_dictionary.yaml.
    - Does not generate or execute SQL directly.
    - Does not access raw HR tables.
    - Produces a safe route: SQL, GAP, REJECT or NEEDS_CLARIFICATION.
"""

JsonDict = dict[str, Any]

try:  # Works when copied beside metadata_service.py.
    from metadata_service import MetadataService, get_metadata_service  # type: ignore
except Exception:  # pragma: no cover - package-relative import fallback.
    try:
        from .metadata_service import MetadataService, get_metadata_service  # type: ignore
    except Exception:  # pragma: no cover - tests can inject metadata explicitly.
        MetadataService = Any  # type: ignore
        get_metadata_service = None  # type: ignore


ROUTE_SQL = "SQL"
ROUTE_GAP = "GAP"
ROUTE_REJECT = "REJECT"
ROUTE_CLARIFICATION = "NEEDS_CLARIFICATION"

STATUS_SUPPORTED = "supported"
STATUS_VALID = "VALID"
STATUS_DATA_GAP = "DATA_GAP"
STATUS_ACCESS_DENIED = "ACCESS_DENIED"
STATUS_OUT_OF_SCOPE = "OUT_OF_SCOPE"
STATUS_NEEDS_CLARIFICATION = "NEEDS_CLARIFICATION"
STATUS_OK = "OK"

PERSIAN_DIGITS = "۰۱۲۳۴۵۶۷۸۹"
ARABIC_DIGITS = "٠١٢٣٤٥٦٧٨٩"
EN_DIGITS = "0123456789"
DIGIT_TRANSLATION = str.maketrans({
    **{p: e for p, e in zip(PERSIAN_DIGITS, EN_DIGITS)},
    **{a: e for a, e in zip(ARABIC_DIGITS, EN_DIGITS)},
})

PERSIAN_NUMBER_WORDS: dict[str, int] = {
    "صفر": 0,
    "یک": 1,
    "يه": 1,
    "دو": 2,
    "سه": 3,
    "چهار": 4,
    "پنج": 5,
    "شش": 6,
    "شیش": 6,
    "هفت": 7,
    "هشت": 8,
    "نه": 9,
    "ده": 10,
    "یازده": 11,
    "دوازده": 12,
    "سیزده": 13,
    "چهارده": 14,
    "پانزده": 15,
    "شانزده": 16,
    "هفده": 17,
    "هجده": 18,
    "نوزده": 19,
    "بیست": 20,
    "سی": 30,
    "چهل": 40,
    "پنجاه": 50,
    "شصت": 60,
    "هفتاد": 70,
}

# Intent-to-template defaults used when intent_catalog does not directly define
# sql_template_id. These IDs match Template_04_sql_templates.yaml.
DEFAULT_TEMPLATE_BY_INTENT: dict[str, str] = {
    "gender_percentage": "TPL_GENDER_PERCENTAGE",
    "employee_count_by_age_filter": "TPL_EMPLOYEE_COUNT_BY_AGE_FILTER",
    "employee_count_by_age_group": "TPL_EMPLOYEE_COUNT_BY_AGE_GROUP",
    "employee_count_by_gender_age_filter": "TPL_GENDER_BY_AGE_GROUP",
    "most_common_education": "TPL_MOST_COMMON_EDUCATION",
    "least_common_education": "TPL_LEAST_COMMON_EDUCATION",
    "low_education_in_expert_roles": "TPL_LOW_EDUCATION_IN_EXPERT_ROLES",
    "employee_count_by_department": "TPL_EMPLOYEE_COUNT_BY_DEPARTMENT",
    "employee_count_by_work_location": "TPL_EMPLOYEE_COUNT_BY_WORK_LOCATION",
    "hiring_by_contract_type_recent_year": "TPL_HIRING_BY_CONTRACT_TYPE_RECENT_YEAR",
    "average_service_years": "TPL_AVERAGE_SERVICE_YEARS",
    "employee_count_without_service_years": "TPL_EMPLOYEE_COUNT_WITHOUT_SERVICE_YEARS",
    "employee_count_by_marital_status": "TPL_EMPLOYEE_COUNT_BY_MARITAL_STATUS",
}

TERMINAL_STATUS_TO_INTENT: dict[str, tuple[str, str, str]] = {
    STATUS_ACCESS_DENIED: ("individual_employee_info", ROUTE_REJECT, STATUS_ACCESS_DENIED),
    STATUS_OUT_OF_SCOPE: ("out_of_scope", ROUTE_REJECT, STATUS_OUT_OF_SCOPE),
    STATUS_NEEDS_CLARIFICATION: ("ambiguous_hr_question", ROUTE_CLARIFICATION, STATUS_NEEDS_CLARIFICATION),
}

DATA_GAP_INTENT_KEYWORDS: list[tuple[str, list[str]]] = [
    ("city_level_analysis", ["شهر", "شهری", "هر شهر"]),
    ("near_retirement_analysis", ["بازنشستگی",
     "آستانه بازنشستگی", "نزدیک بازنشستگی"]),
    ("contractor_productivity_analysis", [
     "بهره وری پیمانکار", "بهره وری پیمانکاری", "عملکرد پیمانکار"]),
    ("hiring_business_growth_alignment", [
     "افزایش کار", "رشد کار", "حجم کار", "هماهنگ بوده"]),
    ("education_training_need_analysis", [
     "نیاز آموزشی", "دوره تخصصی", "آموزش", "کمبود تخصص"]),
    ("workforce_aging_trend_analysis", [
     "سالخوردگی", "پیر شدن", "ساختار سنی", "به سمت سالخوردگی"]),
    ("department_balance_analysis", [
     "تعادل", "متوازن", "چارت سازمانی و واقعیت", "واقعیت نیروی انسانی"]),
    ("employment_stability_impact_analysis", [
     "ثبات سازمان", "تاثیر می گذارد", "اثر می گذارد"]),
]


@dataclass
class IntentParserConfig:
    current_shamsi_year: int = 1404
    min_confidence_for_sql: float = 0.38
    max_candidate_intents: int = 7
    prefer_semantic_mapper_candidates: bool = True
    use_catalog_examples: bool = True
    use_catalog_triggers: bool = True
    allow_gap_from_semantic_mapper: bool = True
    allow_reject_from_semantic_mapper: bool = True


@dataclass
class IntentCandidate:
    intent_id: str
    score: float
    reasons: list[str] = field(default_factory=list)

    def to_dict(self) -> JsonDict:
        return {
            "intent": self.intent_id,
            "intent_id": self.intent_id,
            "score": round(self.score, 4),
            "reasons": self.reasons[:8],
        }


class IntentParser:
    """
    Metadata-driven intent parser for Persian HR BI questions.

    Public API:
        parser.parse(question, context=None, metadata=None)
        parser.parse_intent(...)
        parser.run(...)
        await parser.arun(...)
        parser(...)

    Output is a dictionary designed to be stored as RequestContext.intent_result.
    """

    def __init__(self, metadata_service: Any | None = None, config: IntentParserConfig | None = None) -> None:
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
                    if (local_dir / "Template_01_intent_catalog.yaml").exists() or (local_dir / "intent_catalog.yaml").exists():
                        self.metadata = MetadataService(
                            # type: ignore[operator]
                            metadata_dir=local_dir, strict=False)
            except Exception:
                pass
        else:
            self.metadata = None
        self.config = config or IntentParserConfig()

    # ------------------------------------------------------------------
    # Public entry points
    # ------------------------------------------------------------------

    def __call__(self, question: str, context: Any | None = None, metadata: Any | None = None, **kwargs: Any) -> JsonDict:
        return self.parse(question=question, context=context, metadata=metadata, **kwargs)

    def run(self, question: str, context: Any | None = None, metadata: Any | None = None, **kwargs: Any) -> JsonDict:
        return self.parse(question=question, context=context, metadata=metadata, **kwargs)

    def parse_intent(self, question: str, context: Any | None = None, metadata: Any | None = None, **kwargs: Any) -> JsonDict:
        return self.parse(question=question, context=context, metadata=metadata, **kwargs)

    async def arun(self, question: str, context: Any | None = None, metadata: Any | None = None, **kwargs: Any) -> JsonDict:
        return self.parse(question=question, context=context, metadata=metadata, **kwargs)

    def parse(self, question: str, context: Any | None = None, metadata: Any | None = None, **kwargs: Any) -> JsonDict:
        started = time.perf_counter()
        service = metadata or self.metadata
        raw_question = question or ""
        normalized_question = self.normalize_text(raw_question)
        runtime_params = self._get_runtime_params(context, kwargs)
        current_shamsi_year = int(runtime_params.get(
            "current_shamsi_year", self.config.current_shamsi_year))

        if not normalized_question:
            return self._terminal_result(
                intent_id="ambiguous_hr_question",
                route=ROUTE_CLARIFICATION,
                status=STATUS_NEEDS_CLARIFICATION,
                question=raw_question,
                normalized_question=normalized_question,
                started=started,
                reason="Question is empty or unclear.",
            )

        terminal = self._terminal_from_context(
            context, normalized_question, service)
        if terminal:
            terminal.update({"duration_ms": round(
                (time.perf_counter() - started) * 1000, 3)})
            return terminal

        intent_catalog = self._get_document(service, "intent_catalog")
        semantic_result = self._context_dict(context, "semantic_result")
        semantic_signals = self._collect_semantic_signals(semantic_result)
        query_features = self._detect_query_features(
            normalized_question, semantic_result)

        candidates = self._score_intents(
            question=normalized_question,
            service=service,
            intent_catalog=intent_catalog,
            semantic_signals=semantic_signals,
            query_features=query_features,
        )

        if not candidates:
            return self._terminal_result(
                intent_id="ambiguous_hr_question",
                route=ROUTE_CLARIFICATION,
                status=STATUS_NEEDS_CLARIFICATION,
                question=raw_question,
                normalized_question=normalized_question,
                started=started,
                reason="No supported intent matched the question.",
                confidence=0.0,
            )

        best = candidates[0]
        intent = self._get_intent(service, best.intent_id) or {}

        # If confidence is too low, ask for clarification instead of guessing.
        confidence = self._score_to_confidence(best.score, candidates)
        if intent.get("route") == ROUTE_SQL and confidence < self.config.min_confidence_for_sql:
            return self._terminal_result(
                intent_id="ambiguous_hr_question",
                route=ROUTE_CLARIFICATION,
                status=STATUS_NEEDS_CLARIFICATION,
                question=raw_question,
                normalized_question=normalized_question,
                started=started,
                reason="Intent confidence is too low for a safe SQL route.",
                confidence=round(confidence, 3),
                candidate_intents=[
                    item.to_dict() for item in candidates[: self.config.max_candidate_intents]],
            )

        extraction = self._extract_structured_payload(
            question=normalized_question,
            intent=intent,
            best_intent_id=best.intent_id,
            semantic_result=semantic_result,
            query_features=query_features,
            current_shamsi_year=current_shamsi_year,
            service=service,
        )

        route = str(intent.get("route")
                    or extraction.get("route") or ROUTE_SQL)
        status = self._status_for_route_and_intent(route, intent)
        sql_template_id = self._choose_sql_template_id(
            best.intent_id, intent, extraction, service)
        report_id = intent.get("report_id") or extraction.get("report_id")

        # GAP / REJECT intents should not accidentally carry SQL templates.
        if route in {ROUTE_GAP, ROUTE_REJECT, ROUTE_CLARIFICATION}:
            sql_template_id = None

        result: JsonDict = {
            "status": status,
            "route": route,
            "intent": best.intent_id,
            "intent_id": best.intent_id,
            "detected_intent": best.intent_id,
            "confidence": round(confidence, 3),
            "reason": "; ".join(best.reasons[:8]) or "Best matching metadata intent.",
            "question": raw_question,
            "normalized_question": normalized_question,
            "question_type": intent.get("question_type"),
            "priority": intent.get("priority"),
            "supported_in_phase2": intent.get("supported_in_phase2", route == ROUTE_SQL),
            "demo_ready": intent.get("demo_ready", False),
            "report_id": report_id,
            "sql_template_id": sql_template_id,
            "required_columns": self._merge_lists(intent.get("required_columns", []), extraction.get("required_columns", [])),
            "metrics": extraction.get("metrics") or deepcopy(intent.get("metrics", [])) or [],
            "filters": extraction.get("filters", []),
            "group_by": extraction.get("group_by", []),
            "order_by": extraction.get("order_by", []),
            "params": extraction.get("params", {}),
            "entities": extraction.get("entities", {}),
            "output_type": extraction.get("output_type") or intent.get("output_type"),
            "recommended_visualization": extraction.get("recommended_visualization") or intent.get("recommended_visualization"),
            "query_features": query_features,
            "semantic_summary": semantic_signals,
            "candidate_intents": [item.to_dict() for item in candidates[: self.config.max_candidate_intents]],
            "warnings": extraction.get("warnings", []),
            "duration_ms": round((time.perf_counter() - started) * 1000, 3),
        }

        if route == ROUTE_GAP:
            result["gap_reason"] = intent.get("gap_reason") or intent.get(
                "reject_reason") or extraction.get("gap_reason")
            result["expected_status_sql"] = intent.get(
                "expected_status_sql") or "SELECT 'DATA_GAP' AS status;"
        elif route in {ROUTE_REJECT, ROUTE_CLARIFICATION}:
            result["reject_reason"] = intent.get(
                "reject_reason") or extraction.get("reject_reason")
            result["expected_status_sql"] = intent.get(
                "expected_status_sql") or self._status_sql_for_route(route, status)

        return result

    # ------------------------------------------------------------------
    # Normalization
    # ------------------------------------------------------------------

    @staticmethod
    def normalize_text(text: str) -> str:
        text = str(text or "")
        replacements = {
            "ي": "ی",
            "ى": "ی",
            "ك": "ک",
            "ۀ": "ه",
            "ة": "ه",
            "ؤ": "و",
            "إ": "ا",
            "أ": "ا",
            "ٱ": "ا",
            "‌": " ",
            "–": "-",
            "—": "-",
            "“": '"',
            "”": '"',
            "‘": "'",
            "’": "'",
        }
        for src, dst in replacements.items():
            text = text.replace(src, dst)
        text = text.translate(DIGIT_TRANSLATION)
        for word, value in sorted(PERSIAN_NUMBER_WORDS.items(), key=lambda item: -len(item[0])):
            text = re.sub(
                rf"(?<!\S){re.escape(word)}(?=\s*(?:سال|تا|و|$))", str(value), text)
        text = re.sub(r"[\t\r\n]+", " ", text)
        text = re.sub(r"[؟?؛;،,]+", " ", text)
        text = re.sub(r"\s+", " ", text)
        return text.strip()

    # ------------------------------------------------------------------
    # Context and metadata helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _context_dict(context: Any | None, attr: str) -> JsonDict:
        if context is None:
            return {}
        if isinstance(context, Mapping):
            value = context.get(attr, {})
        else:
            value = getattr(context, attr, {})
        return deepcopy(value) if isinstance(value, dict) else {}

    @staticmethod
    def _get_runtime_params(context: Any | None, kwargs: Mapping[str, Any]) -> JsonDict:
        params: JsonDict = {}
        if context is not None:
            if isinstance(context, Mapping):
                value = context.get("runtime_params", {})
            else:
                value = getattr(context, "runtime_params", {})
            if isinstance(value, Mapping):
                params.update(dict(value))
        params.update({k: v for k, v in kwargs.items() if k not in {
                      "question", "metadata", "context"}})
        return params

    @staticmethod
    def _get_document(service: Any, key: str) -> JsonDict:
        if service is None:
            return {}
        if isinstance(service, Mapping):
            doc = service.get(key, {})
            return deepcopy(doc) if isinstance(doc, dict) else {}
        if hasattr(service, "get_document"):
            try:
                doc = service.get_document(key)
                return doc if isinstance(doc, dict) else {}
            except Exception:
                return {}
        if hasattr(service, key):
            doc = getattr(service, key)
            return deepcopy(doc) if isinstance(doc, dict) else {}
        return {}

    @staticmethod
    def _list_intents(service: Any, intent_catalog: JsonDict) -> list[JsonDict]:
        if service is not None and hasattr(service, "list_intents"):
            try:
                items = service.list_intents()
                return items if isinstance(items, list) else []
            except Exception:
                pass
        items = intent_catalog.get("intents", []) or []
        return [item for item in items if isinstance(item, dict)]

    @staticmethod
    def _get_intent(service: Any, intent_id: str) -> JsonDict | None:
        if service is not None and hasattr(service, "get_intent"):
            try:
                item = service.get_intent(intent_id)
                return item if isinstance(item, dict) else None
            except Exception:
                return None
        intent_catalog = IntentParser._get_document(service, "intent_catalog")
        for item in intent_catalog.get("intents", []) or []:
            if isinstance(item, dict) and item.get("intent_id") == intent_id:
                return deepcopy(item)
        return None

    @staticmethod
    def _get_column(service: Any, column_name: str) -> JsonDict | None:
        if service is not None and hasattr(service, "get_column"):
            try:
                item = service.get_column(column_name)
                return item if isinstance(item, dict) else None
            except Exception:
                return None
        data_dictionary = IntentParser._get_document(
            service, "data_dictionary")
        for item in data_dictionary.get("columns", []) or []:
            if isinstance(item, dict) and item.get("name") == column_name:
                return deepcopy(item)
        return None

    @staticmethod
    def _template_exists(service: Any, template_id: str | None) -> bool:
        if not template_id:
            return False
        if service is not None and hasattr(service, "get_sql_template"):
            try:
                return bool(service.get_sql_template(template_id))
            except Exception:
                return False
        sql_templates = IntentParser._get_document(service, "sql_templates")
        for key in ("templates", "sql_templates"):
            for item in sql_templates.get(key, []) or []:
                if isinstance(item, dict) and item.get("template_id") == template_id:
                    return True
        return False

    # ------------------------------------------------------------------
    # Terminal status handling
    # ------------------------------------------------------------------

    def _terminal_from_context(self, context: Any | None, question: str, service: Any) -> JsonDict | None:
        # Domain and validation terminal statuses win before intent scoring.
        for attr in ("domain_result", "validation_result"):
            payload = self._context_dict(context, attr)
            terminal = self._terminal_from_payload(payload, question, service)
            if terminal:
                return terminal

        semantic_payload = self._context_dict(context, "semantic_result")
        if semantic_payload:
            status = str(semantic_payload.get("status", "")).upper()
            route = str(semantic_payload.get("route", "")).upper()
            if status in {STATUS_ACCESS_DENIED, STATUS_OUT_OF_SCOPE, STATUS_NEEDS_CLARIFICATION}:
                return self._terminal_from_payload(semantic_payload, question, service)
            if status == STATUS_DATA_GAP and self.config.allow_gap_from_semantic_mapper:
                intent_id = self._guess_gap_intent(question, semantic_payload)
                return self._terminal_result(
                    intent_id=intent_id,
                    route=ROUTE_GAP,
                    status=STATUS_DATA_GAP,
                    question=question,
                    normalized_question=question,
                    reason=semantic_payload.get(
                        "reason") or "Semantic mapper detected Data Gap.",
                    confidence=float(semantic_payload.get(
                        "confidence", 0.9) or 0.9),
                    started=time.perf_counter(),
                    semantic_summary=self._collect_semantic_signals(
                        semantic_payload),
                )
            if route == ROUTE_REJECT and self.config.allow_reject_from_semantic_mapper:
                return self._terminal_from_payload(semantic_payload, question, service)
        return None

    def _terminal_from_payload(self, payload: JsonDict, question: str, service: Any) -> JsonDict | None:
        if not payload:
            return None
        status = str(payload.get("status", "")).upper()
        route = str(payload.get("route", "")).upper()

        if status in TERMINAL_STATUS_TO_INTENT:
            intent_id, mapped_route, mapped_status = TERMINAL_STATUS_TO_INTENT[status]
            return self._terminal_result(
                intent_id=intent_id,
                route=mapped_route,
                status=mapped_status,
                question=question,
                normalized_question=question,
                reason=payload.get(
                    "reason") or f"Terminal status from previous step: {status}",
                confidence=float(payload.get("confidence", 1.0) or 1.0),
                started=time.perf_counter(),
            )

        if status == STATUS_DATA_GAP or route == ROUTE_GAP:
            intent_id = self._guess_gap_intent(question, payload)
            return self._terminal_result(
                intent_id=intent_id,
                route=ROUTE_GAP,
                status=STATUS_DATA_GAP,
                question=question,
                normalized_question=question,
                reason=payload.get(
                    "reason") or "Previous step detected Data Gap.",
                confidence=float(payload.get("confidence", 0.95) or 0.95),
                started=time.perf_counter(),
            )
        return None

    def _terminal_result(
        self,
        *,
        intent_id: str,
        route: str,
        status: str,
        question: str,
        normalized_question: str,
        started: float,
        reason: str,
        confidence: float = 1.0,
        candidate_intents: list[JsonDict] | None = None,
        semantic_summary: JsonDict | None = None,
    ) -> JsonDict:
        return {
            "status": status,
            "route": route,
            "intent": intent_id,
            "intent_id": intent_id,
            "detected_intent": intent_id,
            "confidence": round(float(confidence), 3),
            "reason": reason,
            "question": question,
            "normalized_question": normalized_question,
            "sql_template_id": None,
            "report_id": None,
            "required_columns": [],
            "metrics": [],
            "filters": [],
            "group_by": [],
            "params": {},
            "entities": {},
            "output_type": "status_message",
            "recommended_visualization": "status_message",
            "candidate_intents": candidate_intents or [{"intent": intent_id, "intent_id": intent_id, "score": 999.0, "reasons": [reason]}],
            "semantic_summary": semantic_summary or {},
            "expected_status_sql": self._status_sql_for_route(route, status),
            "duration_ms": round((time.perf_counter() - started) * 1000, 3),
        }

    @staticmethod
    def _status_sql_for_route(route: str, status: str) -> str:
        if status == STATUS_DATA_GAP or route == ROUTE_GAP:
            return "SELECT 'DATA_GAP' AS status;"
        if status == STATUS_ACCESS_DENIED:
            return "SELECT 'ACCESS_DENIED' AS status;"
        if status == STATUS_OUT_OF_SCOPE:
            return "SELECT 'OUT_OF_SCOPE' AS status;"
        if status == STATUS_NEEDS_CLARIFICATION or route == ROUTE_CLARIFICATION:
            return "SELECT 'NEEDS_CLARIFICATION' AS status;"
        return "SELECT 'DATA_GAP' AS status;"

    def _guess_gap_intent(self, question: str, payload: JsonDict | None = None) -> str:
        payload = payload or {}
        for key in ("intent", "intent_id", "detected_intent"):
            value = payload.get(key)
            if isinstance(value, str) and value and value not in {"unknown", "DATA_GAP"}:
                return value
        hits = payload.get("data_gap_hits", []) or payload.get(
            "gap_candidates", []) or []
        if isinstance(hits, list):
            for hit in hits:
                if isinstance(hit, dict):
                    concept = str(hit.get("concept_id")
                                  or hit.get("rule_id") or "")
                    if "city" in concept:
                        return "city_level_analysis"
                    if "retirement" in concept or "بازنشست" in concept:
                        return "near_retirement_analysis"
                    if "productivity" in concept:
                        return "contractor_productivity_analysis"
        for intent_id, keywords in DATA_GAP_INTENT_KEYWORDS:
            if any(term in question for term in keywords):
                return intent_id
        return "department_balance_analysis" if any(t in question for t in ["تعادل", "متوازن", "کمبود نیرو"]) else "city_level_analysis"

    # ------------------------------------------------------------------
    # Semantic signal collection and features
    # ------------------------------------------------------------------

    def _collect_semantic_signals(self, semantic_result: JsonDict) -> JsonDict:
        return {
            "detected_intent": semantic_result.get("detected_intent"),
            "candidate_intents": semantic_result.get("candidate_intents", []) or [],
            "candidate_intent_scores": semantic_result.get("candidate_intent_scores", []) or [],
            "mapped_columns": semantic_result.get("mapped_columns", []) or [],
            "mapped_metrics": semantic_result.get("mapped_metrics", []) or [],
            "filters": semantic_result.get("filters", []) or [],
            "group_by": semantic_result.get("group_by", []) or [],
            "query_features": semantic_result.get("query_features", {}) or {},
            "status": semantic_result.get("status"),
            "route": semantic_result.get("route"),
        }

    def _detect_query_features(self, question: str, semantic_result: JsonDict) -> JsonDict:
        semantic_features = semantic_result.get("query_features", {}) if isinstance(
            semantic_result.get("query_features"), dict) else {}
        features: JsonDict = deepcopy(semantic_features)

        features.update({
            "asks_count": self._has_any(question, ["تعداد", "چند نفر", "چقدر", "چند تا", "نیرو داریم"]),
            "asks_percentage": self._has_any(question, ["درصد", "سهم", "نسبت", "چه مقدار", "چند درصد"]),
            "asks_average": self._has_any(question, ["میانگین", "متوسط", "اختلاف میانگین"]),
            "asks_distribution": self._has_any(question, ["تفکیک", "بر اساس", "به تفکیک", "توزیع", "سهم هر", "در هر"]),
            "asks_most": self._has_any(question, ["بیشترین", "بالاترین", "حداکثر", "کدام بیشتر", "بیشترين"]),
            "asks_least": self._has_any(question, ["کمترین", "پایین ترین", "حداقل", "کدام کمتر"]),
            "asks_trend": self._has_any(question, ["روند", "سالانه", "ماهانه", "طی", "در هر سال", "در هر ماه", "۱۵ سال", "15 سال"]),
            "explicit_monthly": self._has_any(question, ["ماهانه", "هر ماه", "در هر ماه", "ماه شمسی", "روند ماهانه"]),
            "asks_gap_or_shortage": self._has_any(question, ["کمبود نیرو", "اختلاف", "چارت مصوب", "نیروی موجود", "تعادل", "متوازن"]),
            "explicit_contract_type": "نوع قرارداد" in question,
            "explicit_employment_type": "نوع استخدام" in question or "وضعیت استخدام" in question,
            "explicit_contractor": "پیمانکاری" in question or "پیمانکار" in question,
            "explicit_service_domain": "حوزه" in question,
            "explicit_department": self._has_any(question, ["بخش", "واحد", "اداره", "دپارتمان"]),
            "explicit_province": "استان" in question,
            "explicit_city": "شهر" in question,
            "explicit_work_location": "محل خدمت" in question or "سایت" in question,
            "explicit_gender": self._has_any(question, ["جنسیت", "زن", "مرد", "خانم", "آقا"]),
            "explicit_age": self._has_any(question, ["سن", "سنی", "سال به بالا", "زیر", "بالای"]),
            "explicit_education": self._has_any(question, ["مدرک", "تحصیلات", "دیپلم", "کاردانی", "کارشناسی", "ارشد", "دکترا"]),
            "explicit_hiring": self._has_any(question, ["جذب", "استخدام سال", "سال جذب"]),
            "explicit_service_years": self._has_any(question, ["سابقه", "سنوات", "بدون سابقه"]),
            "explicit_marital": self._has_any(question, ["تاهل", "تأهل", "مجرد", "متاهل", "متأهل"]),
            "asks_recent_year": self._has_any(question, ["سال اخیر", "سال جاری", "امسال"]),
            "asks_last_15_years": self._has_any(question, ["۱۵ سال اخیر", "15 سال اخیر", "پانزده سال اخیر"]),
            "asks_zero_service": self._has_any(question, ["بدون سابقه", "سابقه صفر", "0 سال سابقه"]),
            "asks_individual": self._has_any(question, ["نام", "کد ملی", "شماره پرسنلی", "مشخصات", "لیست کارکنان", "افراد را نمایش"]),
        })
        features["age_filter"] = self._extract_age_filter(question)
        features["comparison_dimension"] = self._infer_comparison_dimension(
            question, features)
        return features

    @staticmethod
    def _has_any(text: str, terms: Iterable[str]) -> bool:
        return any(term in text for term in terms)

    # ------------------------------------------------------------------
    # Intent scoring
    # ------------------------------------------------------------------

    def _score_intents(
        self,
        *,
        question: str,
        service: Any,
        intent_catalog: JsonDict,
        semantic_signals: JsonDict,
        query_features: JsonDict,
    ) -> list[IntentCandidate]:
        scores: dict[str, IntentCandidate] = {}

        def add(intent_id: str, points: float, reason: str) -> None:
            if not intent_id:
                return
            item = scores.setdefault(intent_id, IntentCandidate(
                intent_id=intent_id, score=0.0))
            item.score += points
            item.reasons.append(reason)

        # Manual high-precision rules first.
        for intent_id, points, reason in self._manual_intent_rules(question, query_features):
            add(intent_id, points, reason)

        # Semantic mapper candidates.
        if self.config.prefer_semantic_mapper_candidates:
            for index, intent_id in enumerate(semantic_signals.get("candidate_intents", []) or []):
                if isinstance(intent_id, str):
                    add(intent_id, max(1.0, 5.0 - index),
                        "semantic_mapper_candidate")
            for item in semantic_signals.get("candidate_intent_scores", []) or []:
                if isinstance(item, dict):
                    intent_id = str(item.get("intent_id")
                                    or item.get("intent") or "")
                    score = float(item.get("score", 0.0) or 0.0)
                    if intent_id:
                        add(intent_id, min(6.0, 1.0 + score / 3),
                            "semantic_mapper_score")

        # Catalog triggers and examples.
        intents = self._list_intents(service, intent_catalog)
        for intent in intents:
            intent_id = str(intent.get("intent_id", ""))
            if not intent_id:
                continue
            if self.config.use_catalog_triggers:
                for term in intent.get("trigger_terms_fa", []) or []:
                    norm = self.normalize_text(str(term))
                    if norm and self._term_in_question(question, norm):
                        add(intent_id, 4.5 + min(len(norm), 30) /
                            20, f"trigger:{term}")
            if self.config.use_catalog_examples:
                for example in intent.get("user_examples", []) or []:
                    norm_example = self.normalize_text(str(example))
                    overlap = token_overlap(question, norm_example)
                    if overlap >= 0.42:
                        add(intent_id, 2.0 * overlap, "example_overlap")
            # Tiny bonus for demo-supported SQL intents if mapped columns align.
            if intent.get("route") == ROUTE_SQL and intent.get("demo_ready"):
                required = set(intent.get("required_columns", []) or [])
                mapped = set(semantic_signals.get("mapped_columns", []) or [])
                if required and mapped and required.intersection(mapped):
                    add(intent_id, 0.75, "required_column_overlap")

        # Remove contradictory weak candidates for common ambiguous words.
        self._apply_candidate_cleanup(scores, question, query_features)

        candidates = [item for item in scores.values() if item.score > 0]
        candidates.sort(key=lambda item: (-item.score, item.intent_id))
        return candidates

    def _manual_intent_rules(self, question: str, f: JsonDict) -> list[tuple[str, float, str]]:
        rules: list[tuple[str, float, str]] = []
        add = rules.append

        if f.get("asks_individual"):
            add(("individual_employee_info", 100, "sensitive_or_individual_request"))

        if f.get("explicit_city"):
            add(("city_level_analysis", 90, "city_level_data_gap"))
        if self._has_any(question, ["بازنشستگی", "نزدیک بازنشستگی", "آستانه بازنشستگی"]):
            add(("near_retirement_analysis", 90, "retirement_rule_gap"))
        if self._has_any(question, ["بهره وری پیمانکار", "بهره وری پیمانکاری", "عملکرد پیمانکار"]):
            add(("contractor_productivity_analysis",
                90, "contractor_productivity_gap"))
        if self._has_any(question, ["افزایش کار", "رشد کار", "حجم کار"]):
            add(("hiring_business_growth_alignment", 80, "business_growth_data_gap"))
        if self._has_any(question, ["سالخوردگی", "پیر شدن", "به سمت سالخوردگی"]):
            add(("workforce_aging_trend_analysis", 80, "aging_analysis_gap"))
        if self._has_any(question, ["نیاز آموزشی", "دوره تخصصی", "کمبود تخصص"]):
            add(("education_training_need_analysis", 80, "training_need_gap"))

        # Very common HR statistical intents.
        if self._has_any(question, ["تعداد کل کارکنان", "کل کارکنان", "کل پرسنل", "چند نفر نیرو داریم", "تعداد پرسنل فعال"]):
            add(("total_employee_count", 60, "total_headcount_phrase"))

        if f.get("explicit_gender"):
            if f.get("asks_percentage") and not self._has_any(question, ["زن و مرد", "تفکیک جنسیت"]):
                add(("gender_percentage", 65, "gender_percentage_phrase"))
            elif f.get("explicit_age") and f.get("age_filter"):
                add(("employee_count_by_gender_age_filter", 55, "gender_age_filter"))
            else:
                add(("employee_count_by_gender", 45, "gender_distribution"))

        if f.get("asks_average") and f.get("explicit_age"):
            add(("average_age", 70, "average_age"))
        if f.get("explicit_age") and f.get("age_filter"):
            add(("employee_count_by_age_filter", 60, "age_filter"))
        if f.get("explicit_age") and self._has_any(question, ["گروه سنی", "کدام گروه سنی", "بازه سنی"]):
            add(("employee_count_by_age_group", 60, "age_group"))

        if f.get("explicit_education"):
            if f.get("explicit_service_domain"):
                add(("education_distribution_by_service_domain",
                    82, "education_by_service_domain"))
            elif f.get("asks_most"):
                add(("most_common_education", 70, "most_common_education"))
            elif f.get("asks_least"):
                add(("least_common_education", 70, "least_common_education"))
            elif self._has_any(question, ["پست کارشناسی", "تحصیلات پایین", "پایین تر", "حداقل مدرک"]):
                add(("low_education_in_expert_roles",
                    60, "low_education_expert_roles"))
            else:
                add(("employee_count_by_education", 55,
                    "education_distribution_or_filter"))

        if f.get("explicit_employment_type"):
            add(("employee_count_by_employment_type", 70, "employment_type"))
        if f.get("explicit_contract_type"):
            if f.get("explicit_hiring") or f.get("asks_recent_year"):
                add(("hiring_by_contract_type_recent_year",
                    70, "recent_hiring_contract_type"))
            else:
                add(("employee_count_by_contract_type", 70, "contract_type"))
        if self._has_any(question, ["رسمی", "قراردادی", "پیمانی", "شاغل در پیمانکاری"]):
            if f.get("explicit_contract_type"):
                add(("employee_count_by_contract_type", 35, "contract_type_value"))
            else:
                add(("employee_count_by_employment_type", 35, "employment_type_value"))

        if f.get("explicit_contractor"):
            if f.get("explicit_department") or self._has_any(question, ["در هر بخش", "در هر واحد", "به تفکیک بخش", "به تفکیک واحد", "به تفکیک دپارتمان"]):
                add(("contractor_share_by_department",
                    84, "contractor_by_department"))
            elif f.get("explicit_service_domain") or "در هر حوزه" in question:
                add(("contractor_share_by_service_domain",
                    80, "contractor_by_service_domain"))
            else:
                add(("contractor_share", 75, "contractor_share"))

        if f.get("explicit_service_domain") and not f.get("explicit_contractor") and not f.get("explicit_education"):
            if f.get("asks_gap_or_shortage"):
                add(("headcount_gap_by_service_domain",
                    82, "headcount_gap_service_domain"))
            else:
                add(("employee_count_by_service_domain",
                    60, "service_domain_distribution"))
        if f.get("explicit_department"):
            if f.get("asks_gap_or_shortage"):
                add(("headcount_gap_by_department", 75, "headcount_gap_department"))
            else:
                add(("employee_count_by_department", 55, "department_distribution"))
        if f.get("explicit_province"):
            add(("employee_count_by_province", 60, "province_distribution"))
        if f.get("explicit_work_location"):
            add(("employee_count_by_work_location",
                55, "work_location_distribution"))

        if f.get("explicit_hiring"):
            if f.get("explicit_monthly"):
                add(("monthly_hiring_trend", 92, "monthly_hiring_data_gap"))
            elif f.get("asks_last_15_years"):
                add(("hiring_last_15_years", 85, "last_15_years_hiring"))
            elif f.get("asks_most") or f.get("asks_least"):
                add(("most_or_least_hiring_year", 75, "most_or_least_hiring_year"))
            elif f.get("explicit_contract_type") or f.get("asks_recent_year"):
                add(("hiring_by_contract_type_recent_year",
                    70, "recent_hiring_by_contract_type"))
            else:
                add(("hiring_trend_annual", 70, "annual_hiring_trend"))

        if f.get("explicit_service_years"):
            if f.get("asks_zero_service"):
                add(("employee_count_without_service_years",
                    65, "without_service_years"))
            elif f.get("asks_average"):
                add(("average_service_years", 65, "average_service_years"))
            else:
                add(("average_service_years", 25, "service_years_default"))

        if f.get("explicit_marital"):
            add(("employee_count_by_marital_status", 60, "marital_status"))

        if f.get("asks_gap_or_shortage") and not f.get("explicit_department"):
            add(("headcount_gap_by_department", 35, "general_headcount_gap"))

        return rules

    @staticmethod
    def _term_in_question(question: str, term: str) -> bool:
        if not term:
            return False
        if " " not in term and len(term) <= 3 and not term.isdigit():
            return bool(re.search(rf"(?<!\S){re.escape(term)}(?!\S)", question))
        return term in question

    def _apply_candidate_cleanup(self, scores: dict[str, IntentCandidate], question: str, f: JsonDict) -> None:
        # Explicit contract vs employment wording should dominate.
        if f.get("explicit_contract_type"):
            self._penalize(scores, "employee_count_by_employment_type",
                           10, "explicit_contract_type_penalty")
        if f.get("explicit_employment_type") and not f.get("explicit_contract_type"):
            self._penalize(scores, "employee_count_by_contract_type",
                           10, "explicit_employment_type_penalty")

        # Last 15 years should not become generic annual trend.
        if f.get("asks_last_15_years"):
            self._penalize(scores, "hiring_trend_annual",
                           12, "last_15_years_specificity")

        # Percentage of women/men is not a gender distribution if no group distribution phrase exists.
        if f.get("asks_percentage") and self._has_any(question, ["زن", "مرد"]) and not self._has_any(question, ["زن و مرد", "تفکیک جنسیت"]):
            self._penalize(scores, "employee_count_by_gender",
                           8, "gender_percentage_specificity")

        # City is a hard data gap in current MVP.
        if f.get("explicit_city"):
            for intent_id in list(scores):
                if intent_id != "city_level_analysis":
                    self._penalize(scores, intent_id, 999,
                                   "city_data_gap_wins")

    @staticmethod
    def _penalize(scores: dict[str, IntentCandidate], intent_id: str, points: float, reason: str) -> None:
        item = scores.get(intent_id)
        if item:
            item.score -= points
            item.reasons.append(reason)

    @staticmethod
    def _score_to_confidence(best_score: float, candidates: list[IntentCandidate]) -> float:
        if best_score >= 80:
            return 0.99
        if best_score >= 60:
            return 0.96
        if best_score >= 35:
            return 0.9
        if best_score >= 20:
            return 0.78
        if best_score >= 10:
            return 0.62
        if not candidates:
            return 0.0
        return max(0.35, min(0.6, best_score / 18))

    # ------------------------------------------------------------------
    # Structured extraction
    # ------------------------------------------------------------------

    def _extract_structured_payload(
        self,
        *,
        question: str,
        intent: JsonDict,
        best_intent_id: str,
        semantic_result: JsonDict,
        query_features: JsonDict,
        current_shamsi_year: int,
        service: Any,
    ) -> JsonDict:
        semantic_filters = semantic_result.get("filters", []) if isinstance(
            semantic_result.get("filters"), list) else []
        semantic_group_by = semantic_result.get("group_by", []) if isinstance(
            semantic_result.get("group_by"), list) else []
        filters = self._normalize_filter_list(semantic_filters)
        group_by = self._normalize_group_by_list(semantic_group_by)
        params: JsonDict = {}
        entities: JsonDict = {}
        warnings: list[str] = []
        order_by: list[str] = []
        required_columns: list[str] = []

        # Dimension extraction from wording.
        gender_value = self._extract_gender_value(question)
        education_value = self._extract_allowed_value(
            question, service, "education_title")
        employment_value = self._extract_employment_value(
            question, service, explicit_contract=False)
        contract_value = self._extract_contract_value(question, service)
        age_filter = query_features.get(
            "age_filter") or self._extract_age_filter(question)

        if gender_value:
            entities["gender"] = gender_value
        if education_value:
            entities["education_title"] = education_value
        if employment_value:
            entities["employment_type"] = employment_value
        if contract_value:
            entities["contract_type"] = contract_value
        if age_filter:
            entities["age_filter"] = age_filter

        # Intent-specific structured output.
        if best_intent_id == "gender_percentage":
            params["gender_value"] = gender_value or (
                "زن" if "زن" in question else "مرد" if "مرد" in question else None)
            if params["gender_value"]:
                filters.append(
                    {"column": "gender", "operator": "=", "value": params["gender_value"]})
                required_columns.extend(["gender", "employee_id", "is_active"])
            else:
                warnings.append(
                    "gender_percentage requires gender_value; fallback clarification may be needed.")

        elif best_intent_id == "employee_count_by_age_filter":
            age_params = self._age_filter_to_params(age_filter)
            params.update(age_params)
            for key, value in age_params.items():
                if value is not None:
                    pass
            if age_filter:
                filters.append(age_filter)
            required_columns.extend(["age", "employee_id", "is_active"])

        elif best_intent_id == "employee_count_by_gender_age_filter":
            if age_filter:
                filters.append(age_filter)
            group_by = self._ensure_group_by(group_by, "gender")
            required_columns.extend(
                ["gender", "age", "employee_id", "is_active"])

        elif best_intent_id == "employee_count_by_age_group":
            group_by = self._ensure_group_by(group_by, "age_group_title")
            required_columns.extend(
                ["age_group_title", "employee_id", "is_active"])

        elif best_intent_id == "average_age":
            if "زن و مرد" in question or "تفکیک جنسیت" in question:
                group_by = self._ensure_group_by(group_by, "gender")
            elif "هر حوزه" in question or "به تفکیک حوزه" in question:
                group_by = self._ensure_group_by(group_by, "service_domain")
            required_columns.extend(
                ["age", "employee_id", "is_active", *group_by])

        elif best_intent_id == "employee_count_by_education":
            if education_value:
                params["education_title"] = education_value
                filters.append({"column": "education_title",
                               "operator": "=", "value": education_value})
            else:
                group_by = self._ensure_group_by(group_by, "education_title")
            required_columns.extend(
                ["education_title", "employee_id", "is_active"])

        elif best_intent_id in {"most_common_education", "least_common_education"}:
            group_by = ["education_title"]
            order_by = ["employee_count DESC" if best_intent_id ==
                        "most_common_education" else "employee_count ASC"]
            required_columns.extend(
                ["education_title", "employee_id", "is_active"])

        elif best_intent_id == "low_education_in_expert_roles":
            filters.append({"column": "education_rank",
                           "operator": "<", "value_column": "min_education_rank"})
            required_columns.extend(
                ["education_rank", "min_education_rank", "is_expert_role", "employee_id", "is_active"])

        elif best_intent_id == "employee_count_by_employment_type":
            if employment_value:
                params["employment_type"] = employment_value
                filters.append({"column": "employment_type",
                               "operator": "=", "value": employment_value})
            else:
                group_by = self._ensure_group_by(group_by, "employment_type")
            required_columns.extend(
                ["employment_type", "employee_id", "is_active"])

        elif best_intent_id == "employee_count_by_contract_type":
            if contract_value:
                params["contract_type"] = contract_value
                filters.append({"column": "contract_type",
                               "operator": "=", "value": contract_value})
            else:
                group_by = self._ensure_group_by(group_by, "contract_type")
            required_columns.extend(
                ["contract_type", "employee_id", "is_active"])

        elif best_intent_id == "contractor_share":
            filters.append({"column": "is_contractor",
                           "operator": "=", "value": True, "scope": "numerator"})
            required_columns.extend(
                ["is_contractor", "employee_id", "is_active"])

        elif best_intent_id == "contractor_share_by_service_domain":
            filters.append({"column": "is_contractor",
                           "operator": "=", "value": True, "scope": "numerator"})
            group_by = self._ensure_group_by(group_by, "service_domain")
            required_columns.extend(
                ["is_contractor", "service_domain", "employee_id", "is_active"])

        elif best_intent_id == "contractor_share_by_department":
            filters.append({"column": "is_contractor",
                           "operator": "=", "value": True, "scope": "numerator"})
            group_by = self._ensure_group_by(group_by, "department_name")
            required_columns.extend(
                ["is_contractor", "department_name", "employee_id", "is_active"])

        elif best_intent_id in {"education_distribution_by_service_domain", "education_by_service_domain"}:
            group_by = ["service_domain", "education_title"]
            required_columns.extend(
                ["service_domain", "education_title", "education_rank", "employee_id", "is_active"])

        elif best_intent_id == "employee_count_by_service_domain":
            group_by = self._ensure_group_by(group_by, "service_domain")
            required_columns.extend(
                ["service_domain", "employee_id", "is_active"])

        elif best_intent_id == "employee_count_by_department":
            group_by = self._ensure_group_by(group_by, "department_name")
            required_columns.extend(
                ["department_name", "employee_id", "is_active"])

        elif best_intent_id == "headcount_gap_by_department":
            group_by = ["department_id", "department_name"]
            required_columns.extend(["department_id", "department_name",
                                    "department_approved_headcount", "employee_id", "is_active"])

        elif best_intent_id == "headcount_gap_by_service_domain":
            group_by = ["service_domain"]
            required_columns.extend(["department_id", "department_name", "service_domain",
                                    "department_approved_headcount", "employee_id", "is_active"])

        elif best_intent_id == "monthly_hiring_trend":
            required_columns.extend(
                ["hire_date", "hire_year", "employee_id", "is_active"])

        elif best_intent_id == "employee_count_by_province":
            group_by = self._ensure_group_by(group_by, "province")
            required_columns.extend(["province", "employee_id", "is_active"])

        elif best_intent_id == "employee_count_by_work_location":
            group_by = self._ensure_group_by(group_by, "site_name")
            required_columns.extend(
                ["site_name", "province", "employee_id", "is_active"])

        elif best_intent_id == "hiring_trend_annual":
            group_by = ["hire_year"]
            order_by = ["hire_year ASC"]
            required_columns.extend(["hire_year", "employee_id", "is_active"])

        elif best_intent_id == "hiring_last_15_years":
            params["current_shamsi_year"] = current_shamsi_year
            filters.append({"column": "hire_year", "operator": ">=",
                           "value_expression": f"{current_shamsi_year} - 15"})
            group_by = ["hire_year"]
            order_by = ["hire_year ASC"]
            required_columns.extend(["hire_year", "employee_id", "is_active"])

        elif best_intent_id == "most_or_least_hiring_year":
            group_by = ["hire_year"]
            order_by = ["employee_count ASC" if query_features.get(
                "asks_least") else "employee_count DESC"]
            required_columns.extend(["hire_year", "employee_id", "is_active"])

        elif best_intent_id == "hiring_by_contract_type_recent_year":
            params["current_shamsi_year"] = current_shamsi_year
            filters.append(
                {"column": "hire_year", "operator": "=", "value": current_shamsi_year})
            group_by = ["contract_type"]
            required_columns.extend(
                ["contract_type", "hire_year", "employee_id", "is_active"])

        elif best_intent_id == "average_service_years":
            required_columns.extend(
                ["service_years", "employee_id", "is_active"])

        elif best_intent_id == "employee_count_without_service_years":
            filters.append({"column": "service_years",
                           "operator": "=", "value": 0})
            required_columns.extend(
                ["service_years", "employee_id", "is_active"])

        elif best_intent_id == "employee_count_by_marital_status":
            group_by = self._ensure_group_by(group_by, "marital_status")
            required_columns.extend(
                ["marital_status", "employee_id", "is_active"])

        # Always include default active filter as a logical signal. SQL templates
        # already include it, so downstream engines should avoid duplicating it.
        if not any(item.get("column") == "is_active" for item in filters if isinstance(item, dict)):
            filters.insert(0, {"column": "is_active", "operator": "=",
                           "value": True, "source": "default_rule"})

        metrics = self._infer_metrics(best_intent_id, intent, query_features)
        output_type = self._infer_output_type(
            best_intent_id, intent, group_by, query_features)
        recommended_visualization = self._infer_visualization(
            best_intent_id, intent, output_type, group_by, query_features)

        return {
            "filters": self._dedupe_filters(filters),
            "group_by": self._dedupe_list(group_by),
            "order_by": self._dedupe_list(order_by),
            "params": {k: v for k, v in params.items() if v is not None},
            "entities": entities,
            "required_columns": self._dedupe_list(required_columns),
            "metrics": metrics,
            "output_type": output_type,
            "recommended_visualization": recommended_visualization,
            "warnings": warnings,
        }

    def _choose_sql_template_id(self, intent_id: str, intent: JsonDict, extraction: JsonDict, service: Any) -> str | None:
        # Value-specific variants should use value templates.
        if intent_id == "average_age":
            group_by = set(extraction.get("group_by", []) or [])
            if "gender" in group_by and self._template_exists(service, "TPL_AVERAGE_AGE_BY_GENDER"):
                return "TPL_AVERAGE_AGE_BY_GENDER"
            if "service_domain" in group_by and self._template_exists(service, "TPL_AVERAGE_AGE_BY_SERVICE_DOMAIN"):
                return "TPL_AVERAGE_AGE_BY_SERVICE_DOMAIN"

        if intent_id == "employee_count_by_age_filter":
            params = extraction.get("params", {}) or {}
            if params.get("age_min") == 60 and self._template_exists(service, "TPL_EMPLOYEES_AGE_60_PLUS"):
                return "TPL_EMPLOYEES_AGE_60_PLUS"
            if params.get("age_max_exclusive") == 30 and self._template_exists(service, "TPL_EMPLOYEES_UNDER_30"):
                return "TPL_EMPLOYEES_UNDER_30"

        if intent_id == "employee_count_by_education" and extraction.get("params", {}).get("education_title"):
            if self._template_exists(service, "TPL_EMPLOYEE_COUNT_BY_EDUCATION_VALUE"):
                return "TPL_EMPLOYEE_COUNT_BY_EDUCATION_VALUE"

        if intent_id == "employee_count_by_employment_type" and extraction.get("params", {}).get("employment_type"):
            if self._template_exists(service, "TPL_EMPLOYEE_COUNT_BY_EMPLOYMENT_TYPE_VALUE"):
                return "TPL_EMPLOYEE_COUNT_BY_EMPLOYMENT_TYPE_VALUE"

        if intent_id == "employee_count_by_contract_type" and extraction.get("params", {}).get("contract_type"):
            if self._template_exists(service, "TPL_EMPLOYEE_COUNT_BY_CONTRACT_TYPE_VALUE"):
                return "TPL_EMPLOYEE_COUNT_BY_CONTRACT_TYPE_VALUE"

        if intent_id == "most_or_least_hiring_year":
            order_by = " ".join(extraction.get("order_by", []) or [])
            if "ASC" in order_by and self._template_exists(service, "TPL_LEAST_HIRING_YEAR"):
                return "TPL_LEAST_HIRING_YEAR"
            if self._template_exists(service, "TPL_MOST_HIRING_YEAR"):
                return "TPL_MOST_HIRING_YEAR"

        catalog_template = intent.get("sql_template_id")
        if catalog_template and self._template_exists(service, str(catalog_template)):
            return str(catalog_template)

        default_template = DEFAULT_TEMPLATE_BY_INTENT.get(intent_id)
        if self._template_exists(service, default_template):
            return default_template

        return str(catalog_template) if catalog_template else default_template

    # ------------------------------------------------------------------
    # Entity extraction helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _extract_gender_value(question: str) -> str | None:
        # Avoid returning a single gender for "زن و مرد" distribution questions.
        if "زن و مرد" in question or "مرد و زن" in question:
            return None
        if re.search(r"(?<!\S)(زن|زنان|خانم|خانم ها)(?!\S)", question):
            return "زن"
        if re.search(r"(?<!\S)(مرد|مردان|آقا|آقایان)(?!\S)", question):
            return "مرد"
        return None

    def _extract_allowed_value(self, question: str, service: Any, column_name: str) -> str | None:
        column = self._get_column(service, column_name) or {}
        values = column.get("allowed_values", []) or []
        for value in sorted([str(v) for v in values], key=len, reverse=True):
            if value and value in question:
                return value

        # Common aliases for education titles.
        if column_name == "education_title":
            alias_map = {
                "لیسانس": "کارشناسی",
                "فوق دیپلم": "کاردانی",
                "فوق‌دیپلم": "کاردانی",
                "فوق لیسانس": "کارشناسی ارشد",
                "فوق‌لیسانس": "کارشناسی ارشد",
                "ارشد": "کارشناسی ارشد",
                "دکتری": "دکترای تخصصی / حرفه‌ای",
                "دکترا": "دکترای تخصصی / حرفه‌ای",
            }
            for alias, canonical in alias_map.items():
                if alias in question:
                    return canonical
        return None

    def _extract_employment_value(self, question: str, service: Any, *, explicit_contract: bool = False) -> str | None:
        if explicit_contract or "نوع قرارداد" in question:
            return None
        return self._extract_allowed_value(question, service, "employment_type")

    def _extract_contract_value(self, question: str, service: Any) -> str | None:
        if "نوع قرارداد" not in question and not any(term in question for term in ["قراردادهای", "قرارداد جاری"]):
            return None
        return self._extract_allowed_value(question, service, "contract_type")

    def _extract_age_filter(self, question: str) -> JsonDict | None:
        # 60 سال به بالا / بالای 60
        m = re.search(
            r"(?:بالای|بالاتر از|بیشتر از)\s*(\d{1,3})\s*سال?", question)
        if m:
            return {"column": "age", "operator": ">=", "value": int(m.group(1))}
        m = re.search(
            r"(\d{1,3})\s*سال\s*(?:به بالا|و بالاتر|بیشتر)", question)
        if m:
            return {"column": "age", "operator": ">=", "value": int(m.group(1))}
        # زیر 30 / کمتر از 30
        m = re.search(
            r"(?:زیر|کمتر از|پایین تر از)\s*(\d{1,3})\s*سال?", question)
        if m:
            return {"column": "age", "operator": "<", "value": int(m.group(1))}
        # بین 30 تا 40
        m = re.search(
            r"(?:بین|از)\s*(\d{1,3})\s*(?:تا|الی)\s*(\d{1,3})", question)
        if m:
            a, b = int(m.group(1)), int(m.group(2))
            return {"column": "age", "operator": "BETWEEN", "value": [min(a, b), max(a, b)]}
        return None

    @staticmethod
    def _age_filter_to_params(age_filter: JsonDict | None) -> JsonDict:
        params: JsonDict = {"age_min": None,
                            "age_max_exclusive": None, "age_max_inclusive": None}
        if not age_filter:
            return params
        op = age_filter.get("operator")
        value = age_filter.get("value")
        if op == ">=":
            params["age_min"] = int(value)
        elif op == ">":
            params["age_min"] = int(value) + 1
        elif op == "<":
            params["age_max_exclusive"] = int(value)
        elif op == "<=":
            params["age_max_inclusive"] = int(value)
        elif op == "BETWEEN" and isinstance(value, list) and len(value) == 2:
            params["age_min"] = int(value[0])
            params["age_max_inclusive"] = int(value[1])
        return params

    @staticmethod
    def _infer_comparison_dimension(question: str, features: JsonDict) -> str | None:
        if features.get("explicit_gender"):
            return "gender"
        if features.get("explicit_education"):
            return "education_title"
        if features.get("explicit_service_domain"):
            return "service_domain"
        if features.get("explicit_department"):
            return "department_name"
        if features.get("explicit_province"):
            return "province"
        if features.get("explicit_contract_type"):
            return "contract_type"
        if features.get("explicit_employment_type"):
            return "employment_type"
        if features.get("explicit_age") and "گروه" in question:
            return "age_group_title"
        return None

    # ------------------------------------------------------------------
    # Output inference
    # ------------------------------------------------------------------

    def _infer_metrics(self, intent_id: str, intent: JsonDict, f: JsonDict) -> list[JsonDict]:
        catalog_metrics = deepcopy(intent.get("metrics", [])) if isinstance(
            intent.get("metrics"), list) else []
        if catalog_metrics:
            return catalog_metrics
        if "percentage" in intent_id or f.get("asks_percentage") or "share" in intent_id:
            return [
                {"name": "employee_count",
                    "expression": "COUNT(v.employee_id)", "title_fa": "تعداد کارکنان"},
                {"name": "percentage",
                    "expression": "ROUND(... / NULLIF(...), 2)", "title_fa": "درصد"},
            ]
        if intent_id == "average_age":
            return [{"name": "average_age", "expression": "ROUND(AVG(v.age), 2)", "title_fa": "میانگین سن"}]
        if intent_id == "average_service_years":
            return [{"name": "average_service_years", "expression": "ROUND(AVG(v.service_years), 2)", "title_fa": "میانگین سابقه"}]
        if "headcount_gap" in intent_id:
            return [
                {"name": "actual_headcount",
                    "expression": "COUNT(v.employee_id)", "title_fa": "نیروی موجود"},
                {"name": "approved_headcount",
                    "expression": "MAX(v.department_approved_headcount)", "title_fa": "چارت مصوب"},
                {"name": "headcount_gap",
                    "expression": "MAX(v.department_approved_headcount) - COUNT(v.employee_id)", "title_fa": "اختلاف نیرو"},
            ]
        return [{"name": "employee_count", "expression": "COUNT(v.employee_id)", "title_fa": "تعداد کارکنان"}]

    @staticmethod
    def _infer_output_type(intent_id: str, intent: JsonDict, group_by: list[str], f: JsonDict) -> str:
        if intent.get("output_type"):
            return str(intent.get("output_type"))
        if intent_id in {"total_employee_count", "gender_percentage", "employee_count_by_age_filter", "average_age", "average_service_years", "employee_count_without_service_years"} and not group_by:
            return "single_metric"
        if "trend" in intent_id or "hiring_last_15_years" == intent_id:
            return "time_series"
        if "headcount_gap" in intent_id:
            return "table"
        if group_by:
            return "grouped_metric"
        return "single_metric"

    @staticmethod
    def _infer_visualization(intent_id: str, intent: JsonDict, output_type: str, group_by: list[str], f: JsonDict) -> str:
        if intent.get("recommended_visualization"):
            return str(intent.get("recommended_visualization"))
        if output_type == "single_metric":
            return "kpi_card"
        if output_type == "time_series" or "hire_year" in group_by:
            return "line_chart"
        if output_type == "table" or "headcount_gap" in intent_id:
            return "table"
        if "gender" in group_by and len(group_by) == 1:
            return "pie_chart"
        if group_by:
            return "bar_chart"
        return "table"

    @staticmethod
    def _status_for_route_and_intent(route: str, intent: JsonDict) -> str:
        status = str(intent.get("status", "") or "").upper()
        if route == ROUTE_SQL:
            return STATUS_SUPPORTED if status in {"SUPPORTED", ""} else intent.get("status", STATUS_SUPPORTED)
        if route == ROUTE_GAP:
            return STATUS_DATA_GAP
        if route == ROUTE_REJECT:
            if "OUT" in status:
                return STATUS_OUT_OF_SCOPE
            if "CLAR" in status:
                return STATUS_NEEDS_CLARIFICATION
            return STATUS_ACCESS_DENIED
        if route == ROUTE_CLARIFICATION:
            return STATUS_NEEDS_CLARIFICATION
        return intent.get("status", STATUS_SUPPORTED)

    # ------------------------------------------------------------------
    # List / filter utilities
    # ------------------------------------------------------------------

    @staticmethod
    def _normalize_filter_list(filters: Any) -> list[JsonDict]:
        if not isinstance(filters, list):
            return []
        normalized: list[JsonDict] = []
        for item in filters:
            if isinstance(item, dict) and item.get("column"):
                normalized.append(deepcopy(item))
            elif isinstance(item, str):
                normalized.append({"raw": item})
        return normalized

    @staticmethod
    def _normalize_group_by_list(group_by: Any) -> list[str]:
        if not isinstance(group_by, list):
            return []
        result: list[str] = []
        for item in group_by:
            if isinstance(item, str):
                result.append(item)
            elif isinstance(item, dict) and item.get("column"):
                result.append(str(item.get("column")))
        return result

    @staticmethod
    def _ensure_group_by(group_by: list[str], column: str) -> list[str]:
        return group_by if column in group_by else [*group_by, column]

    @staticmethod
    def _dedupe_list(items: Iterable[Any]) -> list[Any]:
        result: list[Any] = []
        seen: set[str] = set()
        for item in items:
            key = repr(item)
            if key not in seen:
                seen.add(key)
                result.append(item)
        return result

    @staticmethod
    def _dedupe_filters(filters: list[JsonDict]) -> list[JsonDict]:
        result: list[JsonDict] = []
        seen: set[str] = set()
        for item in filters:
            if not isinstance(item, dict):
                continue
            key = f"{item.get('column')}|{item.get('operator')}|{item.get('value')}|{item.get('value_expression')}|{item.get('scope')}"
            if key not in seen:
                seen.add(key)
                result.append(item)
        return result

    @staticmethod
    def _merge_lists(*lists: Any) -> list[Any]:
        merged: list[Any] = []
        for items in lists:
            if isinstance(items, list):
                merged.extend(items)
        return IntentParser._dedupe_list(merged)


# ---------------------------------------------------------------------------
# Standalone helpers
# ---------------------------------------------------------------------------


def token_overlap(a: str, b: str) -> float:
    stopwords = {
        "از", "به", "در", "را", "و", "یا", "که", "برای", "چقدر", "چند", "نفر",
        "است", "هست", "هستند", "داریم", "کند", "کن", "نمایش", "بده", "نشان",
    }
    ta = {t for t in re.split(r"\s+", a.strip())
          if len(t) > 1 and t not in stopwords}
    tb = {t for t in re.split(r"\s+", b.strip())
          if len(t) > 1 and t not in stopwords}
    if not ta or not tb:
        return 0.0
    return len(ta & tb) / max(1, min(len(ta), len(tb)))


# Convenience factory for FastAPI dependency injection or simple scripts.

def get_intent_parser(metadata_service: Any | None = None, config: IntentParserConfig | None = None) -> IntentParser:
    return IntentParser(metadata_service=metadata_service, config=config)


if __name__ == "__main__":  # pragma: no cover - local smoke test.
    parser = IntentParser()
    samples = [
        "تعداد کل کارکنان چند نفر است؟",
        "چند درصد کارکنان زن هستند؟",
        "تعداد کارکنان ۶۰ سال به بالا چقدر است؟",
        "تعداد کارکنان بر اساس مدرک تحصیلی چقدر است؟",
        "چند نفر کارشناسی دارند؟",
        "تعداد کارکنان بر اساس نوع قرارداد چقدر است؟",
        "سهم پیمانکاری در هر حوزه چند درصد است؟",
        "روند جذب ۱۵ سال اخیر را نشان بده",
        "سال کمترین جذب کدام است؟",
        "تعداد کارکنان هر شهر چقدر است؟",
        "نام و کد ملی کارکنان را بده",
    ]
    for sample in samples:
        result = parser.parse(sample)
        print(sample, "=>", result.get("intent_id"), result.get("route"),
              result.get("sql_template_id"), result.get("params"))
