from __future__ import annotations
import math
import re
import unicodedata
from dataclasses import asdict, dataclass, field
from typing import Any, Mapping

"""
domain_classifier.py
--------------------
Domain classifier for HR BI Assistant Phase 2: Controlled SQL-based MVP.


Purpose:
    Decide whether a user question belongs to the HR BI Assistant domain before
    the system continues to validation, semantic mapping, intent parsing and SQL
    routing.

Design principles:
    - Deterministic and rule-based for the MVP.
    - Metadata-aware when MetadataService is available.
    - Conservative: reject clearly non-HR questions, ask clarification for very
      ambiguous questions, and pass HR-looking questions to later layers.
    - Privacy/sensitive requests are detected as flags, but final ACCESS_DENIED
      is normally handled by question_validator.py so responsibilities stay clean.

Expected orchestrator contract:
    classifier.classify(question=..., context=..., metadata=...) -> dict

Returned dict examples:
    HR question:
        {
            "route": None,
            "status": "OK",
            "domain": "HR",
            "is_hr": True,
            "confidence": 0.91,
            ...
        }

    Non-HR question:
        {
            "route": "REJECT",
            "status": "OUT_OF_SCOPE",
            "domain": "NON_HR",
            "is_hr": False,
            ...
        }

    Ambiguous question:
        {
            "route": "NEEDS_CLARIFICATION",
            "status": "NEEDS_CLARIFICATION",
            "domain": "UNKNOWN",
            "is_hr": False,
            ...
        }
"""

JsonDict = dict[str, Any]


# ---------------------------------------------------------------------------
# Constants aligned with llm_orchestrator.py, but kept local to avoid imports.
# ---------------------------------------------------------------------------

ROUTE_REJECT = "REJECT"
ROUTE_NEEDS_CLARIFICATION = "NEEDS_CLARIFICATION"
STATUS_OK = "OK"
STATUS_OUT_OF_SCOPE = "OUT_OF_SCOPE"
STATUS_NEEDS_CLARIFICATION = "NEEDS_CLARIFICATION"

DOMAIN_HR = "HR"
DOMAIN_NON_HR = "NON_HR"
DOMAIN_UNKNOWN = "UNKNOWN"


@dataclass(frozen=True)
class WeightedTerm:
    term: str
    weight: float
    category: str


@dataclass
class DomainClassificationResult:
    route: str | None
    status: str
    domain: str
    is_hr: bool
    confidence: float
    reason: str | None = None
    scores: JsonDict = field(default_factory=dict)
    matched_hr_terms: list[str] = field(default_factory=list)
    matched_non_hr_terms: list[str] = field(default_factory=list)
    matched_metadata_concepts: list[JsonDict] = field(default_factory=list)
    safety_flags: list[str] = field(default_factory=list)
    suggested_next_step: str | None = None

    def to_dict(self) -> JsonDict:
        return asdict(self)


class DomainClassifier:
    """
    Deterministic domain classifier for HR BI questions.

    Usage:
        classifier = DomainClassifier()
        result = classifier.classify("تعداد کارکنان زن چند نفر است؟", metadata=metadata_service)

    The classifier is intentionally lightweight and dependency-free. It can work
    with or without MetadataService. If metadata is provided, it uses:
        - metadata.normalize_question(...)
        - metadata.find_semantic_matches(...)
    when those methods exist.
    """

    def __init__(
        self,
        *,
        hr_threshold: float = 2.0,
        non_hr_threshold: float = 2.8,
        strong_hr_anchor_threshold: float = 3.5,
        ambiguity_margin: float = 0.8,
        max_metadata_matches: int = 10,
    ) -> None:
        self.hr_threshold = hr_threshold
        self.non_hr_threshold = non_hr_threshold
        self.strong_hr_anchor_threshold = strong_hr_anchor_threshold
        self.ambiguity_margin = ambiguity_margin
        self.max_metadata_matches = max_metadata_matches

        self.hr_terms = _build_hr_terms()
        self.non_hr_terms = _build_non_hr_terms()
        self.generic_ambiguous_terms = {
            "آمار",
            "گزارش",
            "داشبورد",
            "نمودار",
            "جدول",
            "تحلیل",
            "روند",
            "وضعیت",
            "چقدر",
            "چندتا",
            "چند نفر",
        }
        self.sensitive_terms = {
            "نام",
            "نام خانوادگی",
            "کد ملی",
            "شماره ملی",
            "شماره پرسنلی",
            "شماره تماس",
            "آدرس",
            "حقوق هر فرد",
            "اطلاعات فردی",
            "مشخصات کارکنان",
            "لیست اسامی",
            "national_id",
            "personnel_number",
            "first_name",
            "last_name",
        }
        self.prompt_injection_terms = {
            "ignore previous",
            "ignore all",
            "system prompt",
            "developer message",
            "دستور قبلی",
            "پرامپت قبلی",
            "قوانین قبلی را نادیده بگیر",
            "جدول خام",
            "drop table",
            "delete from",
            "truncate",
            "alter table",
        }

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def classify(
        self,
        question: str | None = None,
        *,
        context: Any | None = None,
        metadata: Any | None = None,
    ) -> JsonDict:
        """Classify whether the question is in HR BI domain."""
        raw_question = question or _get_context_question(context) or ""
        normalized_question = self._normalize_question(
            raw_question, metadata=metadata)

        if not normalized_question or len(normalized_question.strip()) < 3:
            return DomainClassificationResult(
                route=ROUTE_NEEDS_CLARIFICATION,
                status=STATUS_NEEDS_CLARIFICATION,
                domain=DOMAIN_UNKNOWN,
                is_hr=False,
                confidence=1.0,
                reason="Question is empty or too short.",
                suggested_next_step="Ask the user to provide a clearer HR question.",
            ).to_dict()

        matched_hr_terms, hr_score_from_terms = self._score_terms(
            normalized_question, self.hr_terms)
        matched_non_hr_terms, non_hr_score = self._score_terms(
            normalized_question, self.non_hr_terms)
        metadata_matches, hr_score_from_metadata = self._score_metadata_matches(
            normalized_question, metadata)
        safety_flags = self._detect_safety_flags(normalized_question)

        hr_score = hr_score_from_terms + hr_score_from_metadata
        strong_hr_anchor = self._has_strong_hr_anchor(
            matched_hr_terms, metadata_matches)
        clear_non_hr = non_hr_score >= self.non_hr_threshold and not strong_hr_anchor and hr_score < self.hr_threshold
        clearly_hr = hr_score >= self.hr_threshold and (
            strong_hr_anchor
            or hr_score >= non_hr_score
            or (hr_score - non_hr_score) >= self.ambiguity_margin
        )

        scores = {
            "hr_score": round(hr_score, 3),
            "hr_score_from_terms": round(hr_score_from_terms, 3),
            "hr_score_from_metadata": round(hr_score_from_metadata, 3),
            "non_hr_score": round(non_hr_score, 3),
            "strong_hr_anchor": strong_hr_anchor,
        }

        if clearly_hr:
            confidence = self._confidence(hr_score, non_hr_score, minimum=0.62)
            reason = "HR concepts detected."
            if matched_non_hr_terms:
                reason = "HR concepts detected; non-HR terms appear only as contextual words."
            return DomainClassificationResult(
                route=None,
                status=STATUS_OK,
                domain=DOMAIN_HR,
                is_hr=True,
                confidence=confidence,
                reason=reason,
                scores=scores,
                matched_hr_terms=matched_hr_terms,
                matched_non_hr_terms=matched_non_hr_terms,
                matched_metadata_concepts=metadata_matches,
                safety_flags=safety_flags,
                suggested_next_step="Continue to question_validator and intent_parser.",
            ).to_dict()

        if clear_non_hr:
            confidence = self._confidence(non_hr_score, hr_score, minimum=0.70)
            return DomainClassificationResult(
                route=ROUTE_REJECT,
                status=STATUS_OUT_OF_SCOPE,
                domain=DOMAIN_NON_HR,
                is_hr=False,
                confidence=confidence,
                reason="Question is outside HR BI scope.",
                scores=scores,
                matched_hr_terms=matched_hr_terms,
                matched_non_hr_terms=matched_non_hr_terms,
                matched_metadata_concepts=metadata_matches,
                safety_flags=safety_flags,
                suggested_next_step="Return OUT_OF_SCOPE response.",
            ).to_dict()

        # If the question has BI-like terms but no HR anchor, asking clarification is
        # better than rejecting. Example: "give me the trend report".
        if self._looks_like_generic_bi_question(normalized_question):
            return DomainClassificationResult(
                route=ROUTE_NEEDS_CLARIFICATION,
                status=STATUS_NEEDS_CLARIFICATION,
                domain=DOMAIN_UNKNOWN,
                is_hr=False,
                confidence=0.62,
                reason="The question is BI-like but no clear HR concept was detected.",
                scores=scores,
                matched_hr_terms=matched_hr_terms,
                matched_non_hr_terms=matched_non_hr_terms,
                matched_metadata_concepts=metadata_matches,
                safety_flags=safety_flags,
                suggested_next_step="Ask the user which HR metric, dimension or report they mean.",
            ).to_dict()

        # Default: no HR evidence. If non-HR evidence exists, reject; otherwise ask for clarification.
        if non_hr_score > 0:
            return DomainClassificationResult(
                route=ROUTE_REJECT,
                status=STATUS_OUT_OF_SCOPE,
                domain=DOMAIN_NON_HR,
                is_hr=False,
                confidence=self._confidence(
                    non_hr_score, hr_score, minimum=0.58),
                reason="No reliable HR concept was detected and non-HR terms were found.",
                scores=scores,
                matched_hr_terms=matched_hr_terms,
                matched_non_hr_terms=matched_non_hr_terms,
                matched_metadata_concepts=metadata_matches,
                safety_flags=safety_flags,
                suggested_next_step="Return OUT_OF_SCOPE response.",
            ).to_dict()

        return DomainClassificationResult(
            route=ROUTE_REJECT,
            status=STATUS_OUT_OF_SCOPE,
            domain=DOMAIN_NON_HR,
            is_hr=False,
            confidence=0.55,
            reason="No HR concept was detected.",
            scores=scores,
            matched_hr_terms=matched_hr_terms,
            matched_non_hr_terms=matched_non_hr_terms,
            matched_metadata_concepts=metadata_matches,
            safety_flags=safety_flags,
            suggested_next_step="Return OUT_OF_SCOPE response or ask a clarifying HR question in UI.",
        ).to_dict()

    def run(self, question: str | None = None, *, context: Any | None = None, metadata: Any | None = None) -> JsonDict:
        return self.classify(question=question, context=context, metadata=metadata)

    def __call__(self, question: str | None = None, *, context: Any | None = None, metadata: Any | None = None) -> JsonDict:
        return self.classify(question=question, context=context, metadata=metadata)

    async def arun(self, question: str | None = None, *, context: Any | None = None, metadata: Any | None = None) -> JsonDict:
        return self.classify(question=question, context=context, metadata=metadata)

    # ------------------------------------------------------------------
    # Scoring helpers
    # ------------------------------------------------------------------

    def _normalize_question(self, question: str, *, metadata: Any | None) -> str:
        if metadata is not None and hasattr(metadata, "normalize_question"):
            try:
                return str(metadata.normalize_question(question)).strip()
            except Exception:
                pass
        return normalize_fa_text(question)

    def _score_terms(self, question: str, terms: list[WeightedTerm]) -> tuple[list[str], float]:
        matched: list[str] = []
        score = 0.0
        for item in terms:
            if _contains_term(question, item.term):
                matched.append(item.term)
                score += item.weight
        # Prevent repeated synonyms from over-inflating too much.
        unique_matched = list(dict.fromkeys(matched))
        return unique_matched, min(score, 15.0)

    def _score_metadata_matches(self, question: str, metadata: Any | None) -> tuple[list[JsonDict], float]:
        if metadata is None or not hasattr(metadata, "find_semantic_matches"):
            return [], 0.0
        try:
            raw_matches = metadata.find_semantic_matches(
                question, max_matches=self.max_metadata_matches)
        except Exception:
            return [], 0.0

        matches: list[JsonDict] = []
        score = 0.0
        for raw in raw_matches or []:
            if not isinstance(raw, Mapping):
                continue
            match = dict(raw)
            route = str(match.get("route") or "").upper()
            concept_id = str(match.get("concept_id") or match.get("id") or "")
            term = str(match.get("term") or "")
            category = str(match.get("category") or "")

            matches.append({
                "term": term,
                "concept_id": concept_id,
                "category": category,
                "route": route or None,
            })

            if route in {"SQL", "GAP", "REJECT"} or concept_id or category:
                score += 1.25
            if route == "SQL":
                score += 0.7
            if category in {"headcount", "gender", "age", "education", "employment", "contractor", "organization", "location", "hiring"}:
                score += 0.35

        return matches[: self.max_metadata_matches], min(score, 7.0)

    def _has_strong_hr_anchor(self, matched_hr_terms: list[str], metadata_matches: list[JsonDict]) -> bool:
        if not matched_hr_terms and not metadata_matches:
            return False
        strong_terms = {
            "منابع انسانی",
            "کارکنان",
            "کارمند",
            "پرسنل",
            "نیروی انسانی",
            "استخدام",
            "نوع استخدام",
            "نوع قرارداد",
            "پیمانکاری",
            "جذب",
            "مدرک تحصیلی",
            "تحصیلات",
            "سابقه",
            "بازنشستگی",
            "چارت مصوب",
        }
        if any(term in strong_terms for term in matched_hr_terms):
            return True
        strong_categories = {
            "headcount",
            "gender",
            "age",
            "education",
            "employment",
            "contractor",
            "organization",
            "hiring",
            "service_years",
            "retirement",
        }
        return any(str(match.get("category")) in strong_categories for match in metadata_matches)

    def _looks_like_generic_bi_question(self, question: str) -> bool:
        return any(_contains_term(question, term) for term in self.generic_ambiguous_terms)

    def _detect_safety_flags(self, question: str) -> list[str]:
        flags: list[str] = []
        if any(_contains_term(question, term) for term in self.sensitive_terms):
            flags.append("sensitive_or_individual_info_requested")
        q_lower = question.lower()
        if any(term.lower() in q_lower for term in self.prompt_injection_terms):
            flags.append("prompt_injection_or_raw_sql_request")
        return flags

    @staticmethod
    def _confidence(primary_score: float, secondary_score: float, *, minimum: float = 0.55) -> float:
        margin = primary_score - secondary_score
        # Smooth confidence; capped so a rule-based classifier does not overclaim.
        conf = minimum + (1.0 - minimum) * (1 / (1 + math.exp(-0.55 * margin)))
        return round(max(minimum, min(conf, 0.96)), 3)


# ---------------------------------------------------------------------------
# Text normalization
# ---------------------------------------------------------------------------


def normalize_fa_text(text: str) -> str:
    """Normalize Persian/Arabic text and digits for deterministic matching."""
    if text is None:
        return ""
    value = unicodedata.normalize("NFKC", str(text))
    replacements = {
        "ي": "ی",
        "ى": "ی",
        "ك": "ک",
        "ۀ": "ه",
        "ة": "ه",
        "ؤ": "و",
        "أ": "ا",
        "إ": "ا",
        "آ": "آ",
        "‌": " ",  # zero-width non-joiner to ordinary space for matching
        "ـ": "",
    }
    for src, dst in replacements.items():
        value = value.replace(src, dst)
    value = translate_digits_to_ascii(value)
    value = re.sub(r"[\t\r\n]+", " ", value)
    value = re.sub(r"\s+", " ", value).strip()
    return value


def translate_digits_to_ascii(text: str) -> str:
    persian = "۰۱۲۳۴۵۶۷۸۹"
    arabic = "٠١٢٣٤٥٦٧٨٩"
    trans = {ord(ch): str(index) for index, ch in enumerate(persian)}
    trans.update({ord(ch): str(index) for index, ch in enumerate(arabic)})
    return text.translate(trans)


def _contains_term(question: str, term: str) -> bool:
    term = normalize_fa_text(term)
    if not term:
        return False
    # For Persian multi-word phrases, substring matching is more robust.
    if " " in term or any("\u0600" <= ch <= "\u06FF" for ch in term):
        return term in question
    return re.search(rf"\b{re.escape(term)}\b", question, flags=re.IGNORECASE) is not None


def _get_context_question(context: Any | None) -> str | None:
    if context is None:
        return None
    for attr in ("normalized_question", "question"):
        value = getattr(context, attr, None)
        if value:
            return str(value)
    if isinstance(context, Mapping):
        return str(context.get("normalized_question") or context.get("question") or "")
    return None


# ---------------------------------------------------------------------------
# Default term dictionaries
# ---------------------------------------------------------------------------


def _build_hr_terms() -> list[WeightedTerm]:
    # Strong HR anchors.
    strong = [
        "منابع انسانی",
        "کارکنان",
        "کارمند",
        "پرسنل",
        "نیروی انسانی",
        "نیروهای انسانی",
        "نیروها",
        "تعداد کارکنان",
        "تعداد پرسنل",
        "هدکانت",
        "headcount",
        "استخدام",
        "نوع استخدام",
        "قرارداد کارکنان",
        "نوع قرارداد",
        "پیمانکاری",
        "شاغل در پیمانکاری",
        "جذب نیرو",
        "جذب سالانه",
        "سال جذب",
        "سابقه کارکنان",
        "سابقه خدمت",
        "مدرک تحصیلی",
        "تحصیلات",
        "رشته تحصیلی",
        "گروه سنی",
        "سن کارکنان",
        "میانگین سن",
        "جنسیت",
        "زن و مرد",
        "وضعیت تاهل",
        "وضعیت تأهل",
        "بازنشستگی",
        "چارت مصوب",
        "کمبود نیرو",
        "نیروی موجود",
        "حوزه خدمت",
        "محل خدمت",
        "دپارتمان",
        "واحد سازمانی",
        "پست سازمانی",
        "پست کارشناسی",
    ]

    # Weaker HR/context terms. These can be ambiguous alone, so their weights are lower.
    weak = [
        "نیرو",
        "حوزه",
        "بخش",
        "واحد",
        "اداره",
        "استان",
        "شهر",
        "محل",
        "پست",
        "سن",
        "مدرک",
        "رسمی",
        "قراردادی",
        "پیمانی",
        "دیپلم",
        "کاردانی",
        "کارشناسی",
        "کارشناسی ارشد",
        "دکترا",
        "زیر 30",
        "60 سال به بالا",
        "میانگین سابقه",
        "سال بیشترین جذب",
        "سال کمترین جذب",
    ]

    terms: list[WeightedTerm] = []
    terms.extend(WeightedTerm(term=t, weight=2.2, category="hr_anchor")
                 for t in strong)
    terms.extend(WeightedTerm(term=t, weight=0.75, category="hr_context")
                 for t in weak)
    return terms


def _build_non_hr_terms() -> list[WeightedTerm]:
    # Clear non-HR business domains. Some terms (e.g. "financial") are intentionally
    # excluded because they can be department names in HR reporting.
    terms = [
        ("فروش ماه گذشته", 3.8),
        ("فروش", 2.4),
        ("درآمد", 2.8),
        ("سود", 2.8),
        ("زیان", 2.8),
        ("حاشیه سود", 3.0),
        ("ترازنامه", 3.0),
        ("صورت سود و زیان", 3.2),
        ("فاکتور", 2.8),
        ("صورتحساب", 2.8),
        ("مشتری", 2.6),
        ("مشتریان", 2.6),
        ("بازاریابی", 2.6),
        ("مارکتینگ", 2.6),
        ("کمپین", 2.5),
        ("تبلیغات", 2.4),
        ("انبار", 2.6),
        ("موجودی کالا", 3.0),
        ("کالا", 2.2),
        ("محصول", 2.2),
        ("تولید کالا", 3.0),
        ("خرید کالا", 2.8),
        ("سفارش مشتری", 3.0),
        ("ارسال کالا", 2.8),
        ("حمل و نقل", 2.3),
        ("قبض", 2.4),
        ("پرداخت مشتری", 2.8),
        ("sales", 2.8),
        ("revenue", 2.8),
        ("profit", 2.8),
        ("invoice", 2.8),
        ("customer", 2.6),
        ("inventory", 2.8),
        ("marketing", 2.6),
    ]
    return [WeightedTerm(term=term, weight=weight, category="non_hr") for term, weight in terms]


# ---------------------------------------------------------------------------
# Convenience module-level API
# ---------------------------------------------------------------------------

_DEFAULT_CLASSIFIER = DomainClassifier()


def classify_domain(question: str, *, context: Any | None = None, metadata: Any | None = None) -> JsonDict:
    """Convenience function for callers that do not instantiate the class."""
    return _DEFAULT_CLASSIFIER.classify(question=question, context=context, metadata=metadata)


async def aclassify_domain(question: str, *, context: Any | None = None, metadata: Any | None = None) -> JsonDict:
    return _DEFAULT_CLASSIFIER.classify(question=question, context=context, metadata=metadata)


if __name__ == "__main__":  # Lightweight manual smoke test.
    samples = [
        "تعداد کل کارکنان چند نفر است؟",
        "سهم پیمانکاری در هر حوزه چند درصد است؟",
        "فروش ماه گذشته شرکت چقدر بوده؟",
        "گزارش روند را بده",
        "نام و کد ملی کارکنان را بده",
    ]
    classifier = DomainClassifier()
    for sample in samples:
        print(sample)
        print(classifier.classify(sample))
        print("-" * 80)
