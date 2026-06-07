from __future__ import annotations
import re
import time
from copy import deepcopy
from pathlib import Path
from dataclasses import dataclass, field
from typing import Any, Iterable, Mapping

from app.infrastructure.metadata.service import MetadataService, get_metadata_service

"""
semantic_mapper.py
------------------
Semantic mapper for HR BI Assistant Phase 2 / Controlled SQL-based MVP.

Place this file in:
    backend/app/services/semantic_mapper.py

Purpose:
    Convert a Persian HR question into metadata-grounded semantic signals:
    - detected concepts and terms
    - mapped View columns and metrics
    - candidate filters and group_by fields
    - candidate intents and routes
    - early DATA_GAP / ACCESS_DENIED / OUT_OF_SCOPE hints

This module is intentionally rule + metadata based. It should not query raw HR
records and should not generate SQL directly. SQL generation remains the job of
sql_template_engine.py / sql_generator.py, and SQL safety remains the job of
sql_validator.py.

Expected metadata source:
    metadata_service.py reading semantic_layer.yaml, data_dictionary.yaml,
    intent_catalog.yaml, access_policies.yaml and related metadata files.
"""


JsonDict = dict[str, Any]


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

ROUTE_SQL = "SQL"
ROUTE_GAP = "GAP"
ROUTE_REJECT = "REJECT"
ROUTE_CLARIFICATION = "NEEDS_CLARIFICATION"

STATUS_OK = "OK"
STATUS_DATA_GAP = "DATA_GAP"
STATUS_ACCESS_DENIED = "ACCESS_DENIED"
STATUS_OUT_OF_SCOPE = "OUT_OF_SCOPE"
STATUS_NEEDS_CLARIFICATION = "NEEDS_CLARIFICATION"


@dataclass
class TermMatch:
    term: str
    normalized_term: str
    concept_id: str | None = None
    category: str | None = None
    route: str | None = None
    source: str = "semantic_concept"
    score: float = 0.0
    start: int = -1
    end: int = -1
    metadata: JsonDict = field(default_factory=dict)

    def to_dict(self) -> JsonDict:
        return {
            "term": self.term,
            "normalized_term": self.normalized_term,
            "concept_id": self.concept_id,
            "category": self.category,
            "route": self.route,
            "source": self.source,
            "score": round(self.score, 4),
            "span": [self.start, self.end] if self.start >= 0 else None,
            "metadata": deepcopy(self.metadata),
        }


@dataclass
class SemanticMapperConfig:
    max_matches: int = 30
    min_term_length: int = 2
    min_confidence_for_sql_route: float = 0.35
    include_intent_scoring: bool = True
    include_example_overlap: bool = True
    strict_value_matching: bool = False


class SemanticMapper:
    """
    Metadata-driven semantic mapper for Persian HR BI questions.

    Public API intentionally mirrors the other Phase 2 modules:
        mapper.map(question, context=None, metadata=None)
        mapper.map_question(...)
        mapper.run(...)
        await mapper.arun(...)
        mapper(...)

    The output is a dictionary designed to be stored as RequestContext.semantic_result.
    """

    def __init__(self, metadata_service: Any | None = None, config: SemanticMapperConfig | None = None) -> None:
        if metadata_service is not None:
            self.metadata = metadata_service
        elif get_metadata_service is not None:
            # strict=False keeps local/dev runs resilient while still returning warnings.
            self.metadata = get_metadata_service(
                strict=False)  # type: ignore[misc]
            # Local smoke tests often keep metadata files beside this module rather than
            # in backend/metadata. If the singleton did not load metadata, try that folder.
            try:
                health = self.metadata.health_check().to_dict() if hasattr(
                    self.metadata, "health_check") else {}
                # type: ignore[comparison-overlap]
                if not health.get("ok") and MetadataService is not Any:
                    local_dir = Path(__file__).resolve().parent
                    if (local_dir / "Template_03_semantic_layer.yaml").exists() or (local_dir / "semantic_layer.yaml").exists():
                        self.metadata = MetadataService(
                            # type: ignore[operator]
                            metadata_dir=local_dir, strict=False)
            except Exception:
                pass
        else:
            self.metadata = None
        self.config = config or SemanticMapperConfig()

    # ------------------------------------------------------------------
    # Public entry points
    # ------------------------------------------------------------------

    def __call__(self, question: str, context: Any | None = None, metadata: Any | None = None, **kwargs: Any) -> JsonDict:
        return self.map(question=question, context=context, metadata=metadata, **kwargs)

    def run(self, question: str, context: Any | None = None, metadata: Any | None = None, **kwargs: Any) -> JsonDict:
        return self.map(question=question, context=context, metadata=metadata, **kwargs)

    def map_question(self, question: str, context: Any | None = None, metadata: Any | None = None, **kwargs: Any) -> JsonDict:
        return self.map(question=question, context=context, metadata=metadata, **kwargs)

    async def arun(self, question: str, context: Any | None = None, metadata: Any | None = None, **kwargs: Any) -> JsonDict:
        return self.map(question=question, context=context, metadata=metadata, **kwargs)

    def map(self, question: str, context: Any | None = None, metadata: Any | None = None, **_: Any) -> JsonDict:
        started = time.perf_counter()
        service = metadata or self.metadata
        raw_question = question or ""
        normalized_question = self.normalize_text(raw_question)

        if not normalized_question:
            return self._base_result(
                question=raw_question,
                normalized_question=normalized_question,
                route=ROUTE_CLARIFICATION,
                status=STATUS_NEEDS_CLARIFICATION,
                confidence=1.0,
                started=started,
                reason="Question is empty or unclear.",
            )

        semantic_layer = self._get_document(service, "semantic_layer")
        data_dictionary = self._get_document(service, "data_dictionary")
        intent_catalog = self._get_document(service, "intent_catalog")

        reject_hits = self._detect_reject_semantics(
            normalized_question, semantic_layer)
        gap_hits = self._detect_data_gap_semantics(
            normalized_question, semantic_layer)

        concept_matches = self._match_semantic_concepts(
            normalized_question, semantic_layer)
        index_matches = self._match_term_index(
            normalized_question, semantic_layer)
        term_matches = self._merge_matches([*concept_matches, *index_matches])

        mapped_concepts = self._build_mapped_concepts(
            term_matches, semantic_layer)
        mapped_concepts = self._cleanup_mapped_concepts_for_context(
            mapped_concepts, normalized_question)
        detected_terms = [match.to_dict()
                          for match in term_matches[: self.config.max_matches]]

        metric_matches = self._match_metrics(
            normalized_question, semantic_layer)
        value_filters = self._detect_value_filters(
            normalized_question, semantic_layer)
        numeric_filters = self._detect_numeric_filters(normalized_question)
        filters = self._dedupe_filters([*value_filters, *numeric_filters])

        group_by = self._detect_group_by(
            normalized_question, semantic_layer, filters, mapped_concepts)
        query_features = self._detect_query_features(normalized_question)
        filters = self._cleanup_filters_for_context(
            filters, group_by, query_features, normalized_question)
        disambiguation_notes = self._apply_disambiguation(
            normalized_question, filters, group_by, mapped_concepts)

        mapped_columns = self._collect_columns(
            mapped_concepts, filters, group_by)
        mapped_metrics = self._collect_metrics(
            mapped_concepts, metric_matches, query_features)
        candidate_intents = self._rank_candidate_intents(
            normalized_question=normalized_question,
            semantic_layer=semantic_layer,
            intent_catalog=intent_catalog,
            mapped_concepts=mapped_concepts,
            metric_matches=metric_matches,
            filters=filters,
            group_by=group_by,
            query_features=query_features,
        )
        candidate_routes = self._collect_routes(
            mapped_concepts, reject_hits, gap_hits)
        data_statuses = self._collect_data_statuses(mapped_concepts, gap_hits)

        status, route, reason = self._decide_status_and_route(
            reject_hits=reject_hits,
            gap_hits=gap_hits,
            mapped_concepts=mapped_concepts,
            candidate_routes=candidate_routes,
            candidate_intents=candidate_intents,
            normalized_question=normalized_question,
        )

        confidence = self._calculate_confidence(
            term_matches=term_matches,
            metric_matches=metric_matches,
            filters=filters,
            group_by=group_by,
            candidate_intents=candidate_intents,
            route=route,
            status=status,
        )

        warnings = self._build_warnings(
            normalized_question=normalized_question,
            filters=filters,
            group_by=group_by,
            mapped_columns=mapped_columns,
            data_dictionary=data_dictionary,
            disambiguation_notes=disambiguation_notes,
        )

        return {
            "status": status,
            "route": route,
            "reason": reason,
            "confidence": confidence,
            "question": raw_question,
            "normalized_question": normalized_question,
            "detected_terms": detected_terms,
            "semantic_matches": self._to_orchestrator_semantic_matches(mapped_concepts),
            "mapped_concepts": mapped_concepts,
            "mapped_columns": mapped_columns,
            "mapped_metrics": mapped_metrics,
            "filters": filters,
            "group_by": group_by,
            "metric_matches": metric_matches,
            "candidate_intents": [item["intent_id"] for item in candidate_intents],
            "candidate_intent_scores": candidate_intents,
            "detected_intent": candidate_intents[0]["intent_id"] if candidate_intents else None,
            "candidate_routes": candidate_routes,
            "data_statuses": data_statuses,
            "query_features": query_features,
            "data_gap_hits": gap_hits,
            "reject_hits": reject_hits,
            "disambiguation_notes": disambiguation_notes,
            "warnings": warnings,
            "duration_ms": round((time.perf_counter() - started) * 1000, 3),
        }

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
            "‌": " ",  # zero-width non-joiner
            "–": "-",
            "—": "-",
            "“": "\"",
            "”": "\"",
            "‘": "'",
            "’": "'",
        }
        for src, dst in replacements.items():
            text = text.replace(src, dst)
        text = text.translate(DIGIT_TRANSLATION)
        # Normalize common Persian number words that matter for this MVP.
        for word, value in sorted(PERSIAN_NUMBER_WORDS.items(), key=lambda item: -len(item[0])):
            text = re.sub(
                rf"(?<!\S){re.escape(word)}(?=\s*(?:سال|تا|و|$))", str(value), text)
        text = re.sub(r"[\t\r\n]+", " ", text)
        text = re.sub(r"[؟?؛;،,]+", " ", text)
        text = re.sub(r"\s+", " ", text)
        return text.strip()

    def _normalize_term(self, term: Any) -> str:
        return self.normalize_text(str(term or ""))

    # ------------------------------------------------------------------
    # Metadata helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _get_document(service: Any, key: str) -> JsonDict:
        if service is None:
            return {}
        if isinstance(service, Mapping):
            return deepcopy(service.get(key, {})) if isinstance(service.get(key, {}), dict) else {}
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
    def _concepts_by_id(semantic_layer: JsonDict) -> dict[str, JsonDict]:
        concepts = semantic_layer.get("semantic_concepts", []) or []
        return {
            str(item.get("concept_id")): item
            for item in concepts
            if isinstance(item, dict) and item.get("concept_id")
        }

    # ------------------------------------------------------------------
    # Term and concept matching
    # ------------------------------------------------------------------

    def _match_semantic_concepts(self, normalized_question: str, semantic_layer: JsonDict) -> list[TermMatch]:
        matches: list[TermMatch] = []
        concepts = semantic_layer.get("semantic_concepts", []) or []
        for concept in concepts:
            if not isinstance(concept, dict):
                continue
            concept_id = str(concept.get("concept_id", ""))
            category = concept.get("category")
            route = self._safe_maps_to(concept).get("route")
            priority = str(concept.get("priority", "medium"))
            priority_bonus = {"high": 2.0, "medium": 1.0,
                              "low": 0.3}.get(priority, 0.5)
            for term in concept.get("user_terms_fa", []) or []:
                normalized_term = self._normalize_term(term)
                if len(normalized_term) < self.config.min_term_length:
                    continue
                start = self._find_term(normalized_question, normalized_term)
                if start < 0:
                    continue
                matches.append(
                    TermMatch(
                        term=str(term),
                        normalized_term=normalized_term,
                        concept_id=concept_id,
                        category=str(category) if category else None,
                        route=str(route) if route else None,
                        source="semantic_concept",
                        score=self._term_score(
                            normalized_term, priority_bonus),
                        start=start,
                        end=start + len(normalized_term),
                        metadata={"priority": priority,
                                  "title_fa": concept.get("title_fa")},
                    )
                )
        return matches

    def _match_term_index(self, normalized_question: str, semantic_layer: JsonDict) -> list[TermMatch]:
        matches: list[TermMatch] = []
        term_index = semantic_layer.get(
            "term_index_for_semantic_mapper", []) or []
        if isinstance(term_index, dict):
            iterable: Iterable[Any] = [
                {"term": term, **(value if isinstance(value, dict)
                                  else {"concept_id": value})}
                for term, value in term_index.items()
            ]
        else:
            iterable = term_index
        for item in iterable:
            if not isinstance(item, dict):
                continue
            term = item.get("term")
            normalized_term = self._normalize_term(term)
            if len(normalized_term) < self.config.min_term_length:
                continue
            start = self._find_term(normalized_question, normalized_term)
            if start < 0:
                continue
            matches.append(
                TermMatch(
                    term=str(term),
                    normalized_term=normalized_term,
                    concept_id=str(item.get("concept_id")) if item.get(
                        "concept_id") else None,
                    category=str(item.get("category")) if item.get(
                        "category") else None,
                    route=str(item.get("route")) if item.get(
                        "route") else None,
                    source="term_index",
                    score=self._term_score(normalized_term, 0.6),
                    start=start,
                    end=start + len(normalized_term),
                    metadata={k: v for k, v in item.items() if k not in {
                        "term", "concept_id", "category", "route"}},
                )
            )
        return matches

    def _find_term(self, normalized_question: str, normalized_term: str) -> int:
        # Substring matching is intentional for Persian expressions, but short terms
        # like short terms must not match inside longer compound words.
        if not normalized_term or len(normalized_term) < self.config.min_term_length:
            return -1
        if " " not in normalized_term and len(normalized_term) <= 3 and not normalized_term.isdigit():
            pattern = rf"(?<!\S){re.escape(normalized_term)}(?!\S)"
            match = re.search(pattern, normalized_question)
            return match.start() if match else -1
        return normalized_question.find(normalized_term)

    @staticmethod
    def _term_score(normalized_term: str, priority_bonus: float = 0.0) -> float:
        token_count = len(normalized_term.split())
        return min(10.0, priority_bonus + token_count * 1.2 + min(len(normalized_term), 40) / 10)

    def _merge_matches(self, matches: list[TermMatch]) -> list[TermMatch]:
        best_by_key: dict[tuple[str | None, str], TermMatch] = {}
        for match in matches:
            key = (match.concept_id, match.normalized_term)
            current = best_by_key.get(key)
            if current is None or match.score > current.score:
                best_by_key[key] = match
        merged = list(best_by_key.values())
        merged.sort(key=lambda m: (-m.score, m.start, -(m.end - m.start)))
        return merged[: self.config.max_matches]

    def _build_mapped_concepts(self, term_matches: list[TermMatch], semantic_layer: JsonDict) -> list[JsonDict]:
        concepts_by_id = self._concepts_by_id(semantic_layer)
        grouped: dict[str, JsonDict] = {}
        for match in term_matches:
            if not match.concept_id:
                continue
            concept = concepts_by_id.get(match.concept_id, {})
            maps_to = self._safe_maps_to(concept)
            item = grouped.setdefault(
                match.concept_id,
                {
                    "concept_id": match.concept_id,
                    "title_fa": concept.get("title_fa") or match.concept_id,
                    "category": concept.get("category") or match.category,
                    "priority": concept.get("priority", "medium"),
                    "data_status": concept.get("data_status", "unknown"),
                    "maps_to": maps_to,
                    "matched_terms": [],
                    "score": 0.0,
                },
            )
            item["matched_terms"].append(match.term)
            item["score"] = max(float(item.get("score", 0.0)), match.score)
        mapped = list(grouped.values())
        mapped.sort(key=lambda item: (-float(item.get("score", 0.0)),
                    str(item.get("concept_id"))))
        for item in mapped:
            item["matched_terms"] = list(
                dict.fromkeys(item.get("matched_terms", [])))[:8]
            item["score"] = round(float(item.get("score", 0.0)), 4)
        return mapped

    @staticmethod
    def _cleanup_mapped_concepts_for_context(mapped_concepts: list[JsonDict], normalized_question: str) -> list[JsonDict]:
        """Remove concepts caused by ambiguous words when a clearer phrase exists."""
        cleaned = list(mapped_concepts)
        if "نوع استخدام" in normalized_question and not any(term in normalized_question for term in ["جذب", "سال جذب", "روند جذب", "اخیر"]):
            cleaned = [item for item in cleaned if item.get(
                "concept_id") not in {"hiring", "hiring_trend_annual", "hiring_last_15_years"}]
        if "نوع قرارداد" in normalized_question or "قرارداد" in normalized_question:
            # Employment status terms can be values, but explicit contract context wins.
            # We keep contract_type concepts and let filter disambiguation map values to contract_type.
            pass
        return cleaned

    @staticmethod
    def _safe_maps_to(concept: JsonDict) -> JsonDict:
        maps_to = concept.get("maps_to") if isinstance(concept, dict) else {}
        return maps_to if isinstance(maps_to, dict) else {}

    # ------------------------------------------------------------------
    # Metrics, values, numeric filters, grouping
    # ------------------------------------------------------------------

    def _match_metrics(self, normalized_question: str, semantic_layer: JsonDict) -> list[JsonDict]:
        matches: list[JsonDict] = []
        for metric in semantic_layer.get("metric_mappings", []) or []:
            if not isinstance(metric, dict):
                continue
            matched_terms = []
            for term in metric.get("user_terms_fa", []) or []:
                normalized_term = self._normalize_term(term)
                if normalized_term and self._find_term(normalized_question, normalized_term) >= 0:
                    matched_terms.append(str(term))
            if matched_terms:
                matches.append(
                    {
                        "metric_id": metric.get("metric_id"),
                        "title_fa": metric.get("title_fa"),
                        "expression": metric.get("expression") or metric.get("expression_patterns"),
                        "default_alias": metric.get("default_alias"),
                        "output_type": metric.get("output_type"),
                        "matched_terms": matched_terms,
                    }
                )
        # Query features can imply metrics even without exact metric words.
        if not matches and any(term in normalized_question for term in ["چند نفر", "تعداد", "کل کارکنان", "نیرو داریم"]):
            matches.append(
                {
                    "metric_id": "employee_count",
                    "title_fa": "تعداد کارکنان",
                    "expression": "COUNT(v.employee_id)",
                    "default_alias": "employee_count",
                    "output_type": "integer",
                    "matched_terms": ["implicit_count"],
                }
            )
        return matches

    def _detect_value_filters(self, normalized_question: str, semantic_layer: JsonDict) -> list[JsonDict]:
        filters: list[JsonDict] = []
        value_aliases = semantic_layer.get("value_aliases", {}) or {}
        if not isinstance(value_aliases, dict):
            return filters

        question_mentions_contract_type = any(term in normalized_question for term in [
                                              "نوع قرارداد", "قراردادهای", "قرارداد ", " قرارداد"])
        question_mentions_position_expert = any(term in normalized_question for term in [
                                                "پست کارشناسی", "نقش کارشناسی", "پست کارشناس", "عنوان پست کارشناسی"])

        for column, entries in value_aliases.items():
            if not isinstance(entries, list):
                continue
            for entry in entries:
                if not isinstance(entry, dict):
                    continue
                canonical = entry.get("canonical_value")
                aliases = entry.get("aliases_fa", []) or []
                matched_aliases = []
                for alias in aliases:
                    normalized_alias = self._normalize_term(alias)
                    if normalized_alias and self._find_term(normalized_question, normalized_alias) >= 0:
                        matched_aliases.append(str(alias))
                if not matched_aliases:
                    continue

                mapped_column = str(column)
                operator = "="
                value: Any = canonical
                filter_sql = entry.get("filter_sql")
                confidence = 0.72 + \
                    min(len(max(matched_aliases, key=len)), 20) / 100

                # Disambiguation: contractor term maps to is_contractor for shares/counts.
                if mapped_column == "employment_type" and str(canonical) == "شاغل در پیمانکاری":
                    mapped_column = "is_contractor"
                    value = True
                    filter_sql = "v.is_contractor = TRUE"
                    confidence += 0.12

                # Disambiguation: employment status terms with explicit contract context map to contract_type.
                if mapped_column == "employment_type" and question_mentions_contract_type and str(canonical) in {"رسمی", "قراردادی", "پیمانی", "رسمی - آزمایشی", "رسمی _ بیمه ای دائم"}:
                    mapped_column = "contract_type"
                    filter_sql = f"v.contract_type = '{str(canonical).replace(chr(39), chr(39)*2)}'"
                    confidence += 0.08

                # Disambiguation: "karshenas" in position context maps to expert role, not education title.
                if mapped_column == "education_title" and str(canonical) == "کارشناسی" and question_mentions_position_expert:
                    mapped_column = "is_expert_role"
                    value = True
                    filter_sql = "v.is_expert_role = TRUE"
                    confidence += 0.1

                filters.append(
                    {
                        "column": mapped_column,
                        "operator": operator,
                        "value": value,
                        "filter_sql": filter_sql,
                        "source": "value_aliases",
                        "matched_terms": matched_aliases[:5],
                        "confidence": round(min(confidence, 0.98), 4),
                    }
                )
        return filters

    def _detect_numeric_filters(self, normalized_question: str) -> list[JsonDict]:
        filters: list[JsonDict] = []

        # Age: below N years (under / less than N)
        for pattern in [r"(?:زیر|کمتر از|پایین تر از)\s+(\d{1,3})\s*(?:سال)?", r"(\d{1,3})\s*سال\s*(?:به پایین|کمتر)"]:
            for match in re.finditer(pattern, normalized_question):
                value = int(match.group(1))
                if 0 < value < 100:
                    filters.append(self._numeric_filter(
                        "age", "<", value, match.group(0), f"v.age < {value}"))

        # Age: above N years (over / more than / N and above)
        for pattern in [r"(?:بالای|بالاتر از|بیشتر از|بیش از)\s+(\d{1,3})\s*(?:سال)?", r"(\d{1,3})\s*(?:سال)?\s*به بالا"]:
            for match in re.finditer(pattern, normalized_question):
                value = int(match.group(1))
                if 0 < value < 100:
                    # Prompt contract uses >= for "above/senior" age buckets in MVP.
                    filters.append(self._numeric_filter(
                        "age", ">=", value, match.group(0), f"v.age >= {value}"))

        # Age range: between A and B years
        for pattern in [r"بین\s+(\d{1,3})\s*(?:و|تا)\s*(\d{1,3})\s*(?:سال)?", r"(\d{1,3})\s*تا\s*(\d{1,3})\s*سال"]:
            for match in re.finditer(pattern, normalized_question):
                a, b = int(match.group(1)), int(match.group(2))
                if 0 < a <= b < 100:
                    filters.append(
                        {
                            "column": "age",
                            "operator": "BETWEEN",
                            "value": [a, b],
                            "filter_sql": f"v.age BETWEEN {a} AND {b}",
                            "source": "numeric_age_range",
                            "matched_terms": [match.group(0)],
                            "confidence": 0.9,
                        }
                    )

        # Service years: zero service years
        if any(term in normalized_question for term in ["بدون سابقه", "سابقه صفر", "صفر سابقه"]):
            filters.append(self._numeric_filter(
                "service_years", "=", 0, "بدون سابقه", "COALESCE(v.service_years, 0) = 0"))

        # Last N years of hiring.
        last_years_match = re.search(
            r"(\d{1,2})\s*سال\s*اخیر", normalized_question)
        if last_years_match and any(term in normalized_question for term in ["جذب", "استخدام"]):
            n = int(last_years_match.group(1))
            if 1 <= n <= 50:
                filters.append(
                    {
                        "column": "hire_year",
                        "operator": ">=",
                        "value": f"{{current_shamsi_year}} - {n}",
                        "filter_sql": f"v.hire_year >= {{current_shamsi_year}} - {n}",
                        "source": "relative_hiring_year",
                        "matched_terms": [last_years_match.group(0)],
                        "requires_runtime_param": "current_shamsi_year",
                        "confidence": 0.88,
                    }
                )

        return filters

    @staticmethod
    def _numeric_filter(column: str, operator: str, value: int | float, term: str, sql: str) -> JsonDict:
        return {
            "column": column,
            "operator": operator,
            "value": value,
            "filter_sql": sql,
            "source": "numeric_pattern",
            "matched_terms": [term],
            "confidence": 0.88,
        }

    def _detect_group_by(
        self,
        normalized_question: str,
        semantic_layer: JsonDict,
        filters: list[JsonDict],
        mapped_concepts: list[JsonDict],
    ) -> list[JsonDict]:
        group_by: list[JsonDict] = []
        filter_columns = {str(item.get("column")) for item in filters}

        # Explicit metadata group_by phrases.
        for mapping in semantic_layer.get("group_by_mappings", []) or []:
            if not isinstance(mapping, dict):
                continue
            phrase = self._normalize_term(mapping.get("user_phrase", ""))
            column = str(mapping.get("column", ""))
            if phrase and self._find_term(normalized_question, phrase) >= 0:
                group_by.append(
                    {
                        "column": column,
                        "expression": f"v.{column}",
                        "source": "group_by_mappings",
                        "matched_terms": [mapping.get("user_phrase")],
                        "preferred_visualization": mapping.get("preferred_visualization"),
                        "confidence": 0.94,
                    }
                )

        # Generic grouping cues + known dimensions.
        grouping_cues = ["به تفکیک", "بر اساس", "براساس",
                         "در هر", "برای هر", "سهم هر", "توزیع", "نسبت", "روند"]
        has_grouping_cue = any(
            cue in normalized_question for cue in grouping_cues)
        dimension_columns = {
            "gender", "marital_status", "age_group_title", "education_title", "education_category",
            "employment_type", "contract_type", "service_domain", "department_name", "province", "city",
            "site_name", "position_title", "position_level", "job_family", "hire_year", "criticality_level",
        }

        # Special case: "female and male" means group by gender, not two separate filters.
        if any(term in normalized_question for term in ["زن و مرد", "مرد و زن", "زنان و مردان", "تعداد زن و مرد"]):
            group_by.append(self._group_item(
                "gender", "gender_pair_expression", ["زن و مرد"], 0.96))

        # Special case: trend / hiring trend => group by hire_year.
        if "روند" in normalized_question and any(term in normalized_question for term in ["جذب", "استخدام"]):
            group_by.append(self._group_item("hire_year", "trend_hiring", [
                            "روند جذب"], 0.95, preferred_visualization="line_chart"))

        if any(term in normalized_question for term in ["بیشترین جذب", "کمترین جذب", "سال بیشترین جذب", "سال کمترین جذب"]):
            group_by.append(self._group_item("hire_year", "most_or_least_hiring_year", [
                            "بیشترین/کمترین جذب"], 0.93, preferred_visualization="table"))

        # If grouping cues exist, concepts can imply group_by dimensions.
        if has_grouping_cue:
            for concept in mapped_concepts:
                maps_to = concept.get("maps_to", {}) if isinstance(
                    concept.get("maps_to"), dict) else {}
                column = maps_to.get("column")
                if column in dimension_columns and column not in filter_columns:
                    # "employment type" contains the hiring root word but is not a hiring-year grouping request.
                    if column == "hire_year" and "نوع استخدام" in normalized_question:
                        continue
                    if column == "hire_year" and not any(term in normalized_question for term in ["جذب", "سال جذب", "روند جذب", "استخدام سالانه"]):
                        continue
                    if column == "city":
                        group_by.append(self._group_item("city", "city_data_gap_dimension", concept.get(
                            "matched_terms", []), 0.89, sql="DATA_GAP"))
                    else:
                        group_by.append(self._group_item(
                            str(column), "concept_dimension", concept.get("matched_terms", []), 0.84))

        # Phrases without an explicit breakdown marker can still imply grouping.
        implicit_group_patterns: list[tuple[list[str], str, str]] = [
            (["گروه سنی"], "age_group_title", "implicit_age_group"),
            (["مدرک تحصیلی", "تحصیلات مختلف", "بر اساس مدرک"],
             "education_title", "implicit_education"),
            (["نوع استخدام"], "employment_type", "implicit_employment_type"),
            (["نوع قرارداد"], "contract_type", "implicit_contract_type"),
            (["حوزه خدمت", "هر حوزه", "حوزه"],
             "service_domain", "implicit_service_domain"),
            (["هر بخش", "هر واحد", "بخش", "واحد", "اداره", "دپارتمان"],
             "department_name", "implicit_department"),
            (["هر استان", "استان"], "province", "implicit_province"),
            (["سال جذب", "جذب سالانه"], "hire_year", "implicit_hire_year"),
        ]
        for terms, column, source in implicit_group_patterns:
            if any(term in normalized_question for term in terms) and column not in filter_columns:
                # Avoid grouping on education when exact education value is being filtered.
                if column == "education_title" and any(f.get("column") == "education_title" for f in filters) and not has_grouping_cue:
                    continue
                # Avoid grouping on employment/contract if exact value is filtered and no grouping cue.
                if column in {"employment_type", "contract_type"} and any(f.get("column") == column for f in filters) and not has_grouping_cue:
                    continue
                group_by.append(self._group_item(column, source, terms, 0.78))

        return self._dedupe_group_by(group_by)

    @staticmethod
    def _group_item(column: str, source: str, matched_terms: Any, confidence: float, *, preferred_visualization: str | None = None, sql: str | None = None) -> JsonDict:
        return {
            "column": column,
            "expression": f"v.{column}" if column != "city" else "v.city",
            "source": source,
            "matched_terms": matched_terms if isinstance(matched_terms, list) else [matched_terms],
            "preferred_visualization": preferred_visualization,
            "sql": sql or f"GROUP BY v.{column}",
            "confidence": round(confidence, 4),
        }

    @staticmethod
    def _dedupe_group_by(items: list[JsonDict]) -> list[JsonDict]:
        best: dict[str, JsonDict] = {}
        for item in items:
            column = str(item.get("column", ""))
            if not column:
                continue
            current = best.get(column)
            if current is None or float(item.get("confidence", 0)) > float(current.get("confidence", 0)):
                best[column] = item
        return sorted(best.values(), key=lambda item: -float(item.get("confidence", 0)))

    def _cleanup_filters_for_context(
        self,
        filters: list[JsonDict],
        group_by: list[JsonDict],
        query_features: JsonDict,
        normalized_question: str,
    ) -> list[JsonDict]:
        """Remove or annotate filters that would be semantically unsafe downstream."""
        group_columns = {str(item.get("column")) for item in group_by}
        cleaned: list[JsonDict] = []

        has_gender_pair = bool(query_features.get("mentions_gender_pair")) or any(
            term in normalized_question for term in ["زن و مرد", "مرد و زن", "زنان و مردان"]
        )
        has_numeric_age_filter = any(
            item.get("column") == "age" for item in filters)

        for item in filters:
            item = deepcopy(item)
            column = item.get("column")

            # "female and male" is a grouping request. Keeping two gender WHERE filters would be wrong.
            if has_gender_pair and column == "gender" and "gender" in group_columns:
                continue

            # Prefer numeric age rules for expressions like "age 60 and above" over age_group_title aliases.
            if has_numeric_age_filter and column == "age_group_title":
                continue

            # In percentage/share questions, value filters often describe the numerator condition,
            # not a WHERE clause. Mark them so the SQL planner/template engine can use them safely.
            if query_features.get("asks_percentage") and column in {"gender", "is_contractor", "employment_type", "contract_type"}:
                item["usage"] = "condition_numerator"
            else:
                item.setdefault("usage", "where_filter")

            cleaned.append(item)

        return self._dedupe_filters(cleaned)

    @staticmethod
    def _dedupe_filters(items: list[JsonDict]) -> list[JsonDict]:
        best: dict[tuple[str, str, str], JsonDict] = {}
        for item in items:
            column = str(item.get("column", ""))
            operator = str(item.get("operator", ""))
            value = item.get("value")
            key = (column, operator, repr(value))
            current = best.get(key)
            if current is None or float(item.get("confidence", 0)) > float(current.get("confidence", 0)):
                best[key] = item
        # Remove gender value filters when group_by gender was inferred from a combined gender term. Handled downstream if needed.
        return sorted(best.values(), key=lambda item: -float(item.get("confidence", 0)))

    # ------------------------------------------------------------------
    # Disambiguation and query features
    # ------------------------------------------------------------------

    def _apply_disambiguation(
        self,
        normalized_question: str,
        filters: list[JsonDict],
        group_by: list[JsonDict],
        mapped_concepts: list[JsonDict],
    ) -> list[JsonDict]:
        notes: list[JsonDict] = []

        if any(term in normalized_question for term in ["نوع استخدام", "استخدام"]):
            notes.append({"rule_id": "DISAMBIG_001", "applied": True,
                         "mapping": "employment_type", "reason": "User mentioned نوع استخدام/استخدام."})
        if any(term in normalized_question for term in ["نوع قرارداد", "قرارداد"]):
            notes.append({"rule_id": "DISAMBIG_001", "applied": True,
                         "mapping": "contract_type", "reason": "User mentioned نوع قرارداد/قرارداد."})

        if "پیمانکاری" in normalized_question:
            notes.append({"rule_id": "DISAMBIG_002", "applied": True, "mapping": "is_contractor = TRUE",
                         "reason": "Contractor concepts use is_contractor for shares/counts."})
            # Prefer is_contractor and suppress duplicate employment_type contractor filters.
            has_contractor_bool = any(
                f.get("column") == "is_contractor" for f in filters)
            if has_contractor_bool:
                filters[:] = [f for f in filters if not (
                    f.get("column") == "employment_type" and f.get("value") == "شاغل در پیمانکاری")]

        if any(term in normalized_question for term in ["پست کارشناسی", "نقش کارشناسی", "پست کارشناس"]):
            notes.append({"rule_id": "DISAMBIG_003", "applied": True,
                         "mapping": "is_expert_role", "reason": "کارشناسی appears in position context."})

        if any(term in normalized_question for term in ["شهر", "هر شهر", "تحلیل شهری"]):
            notes.append({"rule_id": "DISAMBIG_008", "applied": True, "mapping": "DATA_GAP",
                         "reason": "City-level data is not reliable in MVP."})

        if any(term in normalized_question for term in ["آستانه بازنشستگی", "نزدیک بازنشستگی"]):
            notes.append({"rule_id": "DISAMBIG_007", "applied": True,
                         "mapping": "DATA_GAP", "reason": "No formal retirement rule is defined."})

        return notes

    def _detect_query_features(self, normalized_question: str) -> JsonDict:
        features = {
            "asks_count": any(term in normalized_question for term in ["تعداد", "چند نفر", "چندتا", "کل کارکنان", "هدکانت"]),
            "asks_percentage": any(term in normalized_question for term in ["درصد", "سهم", "نسبت", "چند درصد"]),
            "asks_average": any(term in normalized_question for term in ["میانگین", "متوسط"]),
            "asks_trend": any(term in normalized_question for term in ["روند", "سالانه", "طی", "15 سال اخیر"]),
            "asks_most": any(term in normalized_question for term in ["بیشترین", "بالاترین", "حداکثر", "کدام بیشتر"]),
            "asks_least": any(term in normalized_question for term in ["کمترین", "پایین ترین", "حداقل", "کدام کمتر"]),
            "asks_gap": any(term in normalized_question for term in ["کمبود", "اختلاف", "مازاد", "چارت مصوب", "تعادل"]),
            "asks_by_dimension": any(term in normalized_question for term in ["به تفکیک", "بر اساس", "براساس", "در هر", "برای هر", "توزیع"]),
            "mentions_hiring": any(term in normalized_question for term in ["جذب", "استخدام"]),
            "mentions_contractors": "پیمانکاری" in normalized_question or "پیمانکار" in normalized_question,
            "mentions_gender_pair": any(term in normalized_question for term in ["زن و مرد", "مرد و زن", "زنان و مردان"]),
        }
        return features

    # ------------------------------------------------------------------
    # GAP / reject semantics
    # ------------------------------------------------------------------

    def _detect_data_gap_semantics(self, normalized_question: str, semantic_layer: JsonDict) -> list[JsonDict]:
        hits: list[JsonDict] = []
        for item in semantic_layer.get("data_gap_semantics", []) or []:
            if not isinstance(item, dict):
                continue
            matched_terms = [
                str(term)
                for term in item.get("trigger_terms_fa", []) or []
                if self._normalize_term(term) and self._find_term(normalized_question, self._normalize_term(term)) >= 0
            ]
            if matched_terms:
                hits.append(
                    {
                        "gap_id": item.get("gap_id"),
                        "concept": item.get("concept"),
                        "status": item.get("response_status", STATUS_DATA_GAP),
                        "reason_fa": item.get("reason_fa"),
                        "matched_terms": matched_terms,
                    }
                )
        return hits

    def _detect_reject_semantics(self, normalized_question: str, semantic_layer: JsonDict) -> list[JsonDict]:
        hits: list[JsonDict] = []
        for item in semantic_layer.get("reject_semantics", []) or []:
            if not isinstance(item, dict):
                continue
            matched_terms = []
            for term in item.get("trigger_terms_fa", []) or []:
                normalized_term = self._normalize_term(term)
                if normalized_term and self._find_term(normalized_question, normalized_term) >= 0:
                    # Avoid rejecting ordinary aggregate terms inside unrelated compound words; keep full phrase preference.
                    if normalized_term == "نام" and not any(t in normalized_question for t in ["نام کارکنان", "نام و", "نام خانوادگی", "اسامی"]):
                        continue
                    matched_terms.append(str(term))
            if matched_terms:
                status = item.get("response_status")
                if status == "CLARIFICATION_NEEDED":
                    status = STATUS_NEEDS_CLARIFICATION
                hits.append(
                    {
                        "reject_id": item.get("reject_id"),
                        "status": status,
                        "reason_fa": item.get("reason_fa"),
                        "matched_terms": matched_terms,
                    }
                )
        return hits

    # ------------------------------------------------------------------
    # Candidate intent scoring
    # ------------------------------------------------------------------

    def _rank_candidate_intents(
        self,
        *,
        normalized_question: str,
        semantic_layer: JsonDict,
        intent_catalog: JsonDict,
        mapped_concepts: list[JsonDict],
        metric_matches: list[JsonDict],
        filters: list[JsonDict],
        group_by: list[JsonDict],
        query_features: JsonDict,
    ) -> list[JsonDict]:
        if not self.config.include_intent_scoring:
            return []

        scores: dict[str, JsonDict] = {}

        def add_score(intent_id: str, score: float, reason: str) -> None:
            if not intent_id:
                return
            item = scores.setdefault(
                intent_id, {"intent_id": intent_id, "score": 0.0, "reasons": []})
            item["score"] += score
            item["reasons"].append(reason)

        # Semantic concepts can point directly to related intents.
        for concept in mapped_concepts:
            maps_to = concept.get("maps_to", {}) if isinstance(
                concept.get("maps_to"), dict) else {}
            for intent_id in maps_to.get("related_intents", []) or []:
                add_score(str(intent_id), 5.0 + float(concept.get("score", 0)
                                                      ) / 2, f"semantic:{concept.get('concept_id')}")

        # Intent trigger terms and examples.
        for intent in intent_catalog.get("intents", []) or []:
            if not isinstance(intent, dict):
                continue
            intent_id = str(intent.get("intent_id", ""))
            for term in intent.get("trigger_terms_fa", []) or []:
                normalized_term = self._normalize_term(term)
                if normalized_term and self._find_term(normalized_question, normalized_term) >= 0:
                    add_score(
                        intent_id, 4.5 + min(len(normalized_term), 25) / 10, f"trigger:{term}")
            if self.config.include_example_overlap:
                for example in intent.get("user_examples", []) or []:
                    overlap = self._token_overlap(
                        normalized_question, self._normalize_term(example))
                    if overlap >= 0.45:
                        add_score(intent_id, 2.2 * overlap, "example_overlap")

        # Heuristic intent boosts for common HR BI questions.
        group_columns = {str(item.get("column")) for item in group_by}
        metric_ids = {str(item.get("metric_id")) for item in metric_matches}

        if query_features.get("asks_average") and (
            "سن" in normalized_question or
            "age" in {m.get("maps_to", {}).get("column") for m in mapped_concepts if isinstance(m.get("maps_to"), dict)} or
            "average_age" in metric_ids
        ):
            add_score("average_age", 10.0, "heuristic_average_age")
        if (query_features.get("asks_average") and "سابقه" in normalized_question) or "average_service_years" in metric_ids:
            add_score("average_service_years", 7.0,
                      "heuristic_average_service_years")
        if "gender" in group_columns:
            add_score("employee_count_by_gender",
                      5.5, "heuristic_group_gender")
        if "education_title" in group_columns:
            add_score("employee_count_by_education",
                      5.0, "heuristic_group_education")
        if "employment_type" in group_columns:
            add_score("employee_count_by_employment_type",
                      5.0, "heuristic_group_employment_type")
        if "contract_type" in group_columns:
            add_score("employee_count_by_contract_type",
                      5.0, "heuristic_group_contract_type")
        if "service_domain" in group_columns and query_features.get("mentions_contractors"):
            add_score("contractor_share_by_service_domain",
                      6.0, "heuristic_contractor_by_domain")
        elif "service_domain" in group_columns:
            add_score("employee_count_by_service_domain",
                      4.5, "heuristic_group_service_domain")
        if "province" in group_columns:
            add_score("employee_count_by_province",
                      4.5, "heuristic_group_province")
        if "department_name" in group_columns and query_features.get("asks_gap"):
            add_score("headcount_gap_by_department", 6.0,
                      "heuristic_headcount_gap_department")
        elif "department_name" in group_columns:
            add_score("employee_count_by_department",
                      4.5, "heuristic_group_department")
        if "hire_year" in group_columns and (query_features.get("asks_trend") or query_features.get("mentions_hiring")):
            add_score("hiring_trend_annual", 5.5, "heuristic_hiring_trend")
        if any(f.get("column") == "hire_year" and "current_shamsi_year" in str(f.get("value")) for f in filters):
            add_score("hiring_last_15_years", 6.0, "heuristic_last_n_hiring")
        if query_features.get("asks_most") and query_features.get("mentions_hiring"):
            add_score("most_or_least_hiring_year",
                      5.0, "heuristic_most_hiring")
        if query_features.get("asks_least") and query_features.get("mentions_hiring"):
            add_score("most_or_least_hiring_year",
                      5.0, "heuristic_least_hiring")
        if query_features.get("mentions_contractors") and query_features.get("asks_percentage") and "service_domain" not in group_columns:
            add_score("contractor_share", 5.5, "heuristic_contractor_share")
        if query_features.get("asks_count") and not group_by and not filters and not scores:
            add_score("total_employee_count", 4.0, "heuristic_total_count")
        if any(f.get("column") == "age" for f in filters):
            add_score("employee_count_by_age_filter",
                      5.0, "heuristic_age_filter")
        if any(f.get("column") == "gender" for f in filters) and query_features.get("asks_percentage"):
            add_score("gender_percentage", 5.5, "heuristic_gender_percentage")
        if any(f.get("column") == "contract_type" for f in filters) and query_features.get("asks_count"):
            add_score("employee_count_by_contract_type",
                      16.0, "heuristic_contract_type_filter")
        if any(f.get("column") == "employment_type" for f in filters) and query_features.get("asks_count"):
            add_score("employee_count_by_employment_type",
                      8.0, "heuristic_employment_type_filter")

        ranked = list(scores.values())
        ranked.sort(key=lambda item: (-float(item.get("score", 0.0)),
                    str(item.get("intent_id"))))
        for item in ranked:
            item["score"] = round(float(item.get("score", 0.0)), 4)
            item["reasons"] = list(dict.fromkeys(item.get("reasons", [])))[:8]
        return ranked[:10]

    @staticmethod
    def _token_overlap(a: str, b: str) -> float:
        tokens_a = {t for t in re.split(r"\s+", a) if len(t) > 1}
        tokens_b = {t for t in re.split(r"\s+", b) if len(t) > 1}
        if not tokens_a or not tokens_b:
            return 0.0
        return len(tokens_a & tokens_b) / max(1, min(len(tokens_a), len(tokens_b)))

    # ------------------------------------------------------------------
    # Collectors / route decision
    # ------------------------------------------------------------------

    def _collect_columns(self, mapped_concepts: list[JsonDict], filters: list[JsonDict], group_by: list[JsonDict]) -> list[str]:
        columns: list[str] = []
        for concept in mapped_concepts:
            maps_to = concept.get("maps_to", {}) if isinstance(
                concept.get("maps_to"), dict) else {}
            column = maps_to.get("column")
            if column:
                columns.append(str(column))
        columns.extend(str(f.get("column"))
                       for f in filters if f.get("column"))
        columns.extend(str(g.get("column"))
                       for g in group_by if g.get("column"))
        return sorted(set(c for c in columns if c and c != "None"))

    def _collect_metrics(self, mapped_concepts: list[JsonDict], metric_matches: list[JsonDict], query_features: JsonDict) -> list[str]:
        metrics: list[str] = []
        for concept in mapped_concepts:
            maps_to = concept.get("maps_to", {}) if isinstance(
                concept.get("maps_to"), dict) else {}
            metric = maps_to.get("metric")
            if metric:
                metrics.append(str(metric))
        for metric in metric_matches:
            metric_id = metric.get("metric_id")
            if metric_id:
                metrics.append(str(metric_id))
        if query_features.get("asks_count"):
            metrics.append("employee_count")
        if query_features.get("asks_percentage"):
            metrics.append("percentage")
        if query_features.get("asks_average") and not any("average" in m for m in metrics):
            metrics.append("average")
        return list(dict.fromkeys(metrics))

    @staticmethod
    def _collect_routes(mapped_concepts: list[JsonDict], reject_hits: list[JsonDict], gap_hits: list[JsonDict]) -> list[str]:
        routes: list[str] = []
        if reject_hits:
            routes.append(ROUTE_REJECT)
        if gap_hits:
            routes.append(ROUTE_GAP)
        for concept in mapped_concepts:
            maps_to = concept.get("maps_to", {}) if isinstance(
                concept.get("maps_to"), dict) else {}
            route = maps_to.get("route")
            if route:
                routes.append(str(route))
        return list(dict.fromkeys(routes))

    @staticmethod
    def _collect_data_statuses(mapped_concepts: list[JsonDict], gap_hits: list[JsonDict]) -> list[str]:
        statuses: list[str] = []
        if gap_hits:
            statuses.append("data_gap")
        for concept in mapped_concepts:
            if concept.get("data_status"):
                statuses.append(str(concept.get("data_status")))
        return list(dict.fromkeys(statuses))

    def _decide_status_and_route(
        self,
        *,
        reject_hits: list[JsonDict],
        gap_hits: list[JsonDict],
        mapped_concepts: list[JsonDict],
        candidate_routes: list[str],
        candidate_intents: list[JsonDict],
        normalized_question: str,
    ) -> tuple[str, str | None, str | None]:
        if reject_hits:
            first = reject_hits[0]
            status = str(first.get("status") or STATUS_ACCESS_DENIED)
            if status == STATUS_OUT_OF_SCOPE:
                return STATUS_OUT_OF_SCOPE, ROUTE_REJECT, first.get("reason_fa")
            if status == STATUS_NEEDS_CLARIFICATION:
                return STATUS_NEEDS_CLARIFICATION, ROUTE_CLARIFICATION, first.get("reason_fa")
            return STATUS_ACCESS_DENIED, ROUTE_REJECT, first.get("reason_fa")

        if gap_hits:
            first = gap_hits[0]
            return STATUS_DATA_GAP, ROUTE_GAP, first.get("reason_fa")

        if any(route == ROUTE_SQL for route in candidate_routes) or candidate_intents:
            return STATUS_OK, ROUTE_SQL, None

        if mapped_concepts:
            return STATUS_OK, None, None

        if len(normalized_question.split()) <= 2 or normalized_question in {"گزارش بده", "تحلیل کن", "وضعیت را بگو"}:
            return STATUS_NEEDS_CLARIFICATION, ROUTE_CLARIFICATION, "Question is too ambiguous for semantic mapping."

        return STATUS_OK, None, "No strong semantic mapping was detected."

    @staticmethod
    def _calculate_confidence(
        *,
        term_matches: list[TermMatch],
        metric_matches: list[JsonDict],
        filters: list[JsonDict],
        group_by: list[JsonDict],
        candidate_intents: list[JsonDict],
        route: str | None,
        status: str,
    ) -> float:
        if status in {STATUS_DATA_GAP, STATUS_ACCESS_DENIED, STATUS_OUT_OF_SCOPE, STATUS_NEEDS_CLARIFICATION}:
            return 0.95
        score = 0.15
        if term_matches:
            score += min(0.35, len(term_matches) * 0.045 +
                         max(m.score for m in term_matches) / 60)
        if metric_matches:
            score += 0.12
        if filters:
            score += min(0.16, len(filters) * 0.06)
        if group_by:
            score += min(0.16, len(group_by) * 0.06)
        if candidate_intents:
            score += min(0.2, float(candidate_intents[0].get("score", 0)) / 60)
        if route == ROUTE_SQL:
            score += 0.04
        return round(max(0.0, min(score, 0.98)), 4)

    def _build_warnings(
        self,
        *,
        normalized_question: str,
        filters: list[JsonDict],
        group_by: list[JsonDict],
        mapped_columns: list[str],
        data_dictionary: JsonDict,
        disambiguation_notes: list[JsonDict],
    ) -> list[str]:
        warnings: list[str] = []
        columns = {str(col.get("name")) for col in data_dictionary.get(
            "columns", []) or [] if isinstance(col, dict)}
        missing = [
            col for col in mapped_columns if columns and col not in columns]
        if missing:
            warnings.append(
                "Mapped columns not found in data_dictionary: " + ", ".join(sorted(set(missing))))
        if any(item.get("column") == "city" for item in group_by) or "شهر" in normalized_question:
            warnings.append(
                "City-level questions should be handled as DATA_GAP in the current MVP.")
        if any(item.get("column") == "department_approved_headcount" for item in filters) or any("چارت مصوب" in str(item) for item in disambiguation_notes):
            warnings.append(
                "For approved headcount, do not SUM department_approved_headcount over employee rows.")
        return list(dict.fromkeys(warnings))

    # ------------------------------------------------------------------
    # Output helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _to_orchestrator_semantic_matches(mapped_concepts: list[JsonDict]) -> list[JsonDict]:
        matches: list[JsonDict] = []
        for concept in mapped_concepts:
            matches.append(
                {
                    "concept_id": concept.get("concept_id"),
                    "title_fa": concept.get("title_fa"),
                    "category": concept.get("category"),
                    "matched_terms": concept.get("matched_terms", []),
                    "maps_to": concept.get("maps_to", {}),
                    "priority": concept.get("priority", "medium"),
                    "data_status": concept.get("data_status", "unknown"),
                    "score": concept.get("score", 0),
                }
            )
        return matches

    @staticmethod
    def _base_result(
        *,
        question: str,
        normalized_question: str,
        route: str | None,
        status: str,
        confidence: float,
        started: float,
        reason: str | None = None,
    ) -> JsonDict:
        return {
            "status": status,
            "route": route,
            "reason": reason,
            "confidence": confidence,
            "question": question,
            "normalized_question": normalized_question,
            "detected_terms": [],
            "semantic_matches": [],
            "mapped_concepts": [],
            "mapped_columns": [],
            "mapped_metrics": [],
            "filters": [],
            "group_by": [],
            "metric_matches": [],
            "candidate_intents": [],
            "candidate_intent_scores": [],
            "detected_intent": None,
            "candidate_routes": [route] if route else [],
            "data_statuses": [],
            "query_features": {},
            "data_gap_hits": [],
            "reject_hits": [],
            "disambiguation_notes": [],
            "warnings": [],
            "duration_ms": round((time.perf_counter() - started) * 1000, 3),
        }


# ---------------------------------------------------------------------------
# Module-level convenience functions
# ---------------------------------------------------------------------------

_default_mapper: SemanticMapper | None = None


def get_semantic_mapper(*, reload: bool = False, metadata_service: Any | None = None) -> SemanticMapper:
    global _default_mapper
    if reload or _default_mapper is None or metadata_service is not None:
        _default_mapper = SemanticMapper(metadata_service=metadata_service)
    return _default_mapper


def map_question(question: str, context: Any | None = None, metadata: Any | None = None) -> JsonDict:
    return get_semantic_mapper(metadata_service=metadata).map(question=question, context=context, metadata=metadata)


if __name__ == "__main__":  # pragma: no cover - local smoke test.
    mapper = SemanticMapper()
    sample_questions = [
        "تعداد کل کارکنان چند نفر است؟",
        "تعداد زن و مرد چند نفر است؟",
        "چند درصد کارکنان زن هستند؟",
        "سهم پیمانکاری در هر حوزه چند درصد است؟",
        "تعداد کارکنان ۶۰ سال به بالا چقدر است؟",
        "تعداد کارکنان هر شهر چقدر است؟",
        "نام و کد ملی کارکنان را نمایش بده",
        "روند جذب ۱۵ سال اخیر را نشان بده",
    ]
    for q in sample_questions:
        result = mapper.map(q)
        print("\nQUESTION:", q)
        print("STATUS:", result["status"], "ROUTE:",
              result["route"], "INTENT:", result["detected_intent"])
        print("COLUMNS:", result["mapped_columns"])
        print("FILTERS:", result["filters"])
        print("GROUP_BY:", result["group_by"])
