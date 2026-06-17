from __future__ import annotations

import re
import unicodedata
from collections.abc import Iterable, Mapping
from dataclasses import asdict, dataclass, field
from typing import Any

"""
question_validator.py
---------------------
Question validator for HR BI Assistant Phase 2: Controlled SQL-based MVP.


Purpose:
    Validate a normalized user question after domain classification and before
    semantic mapping / intent parsing.

Responsibilities:
    - Reject unsafe or privacy-violating questions.
    - Detect clearly ambiguous questions that need clarification.
    - Detect known MVP data gaps early.
    - Keep valid aggregated HR analytics questions moving through the pipeline.

Design principles:
    - Rule-based and deterministic for Phase 2.
    - Metadata-aware, but able to run without MetadataService.
    - Conservative about privacy: employee-level outputs are denied.
    - Conservative about missing data: do not allow the model to guess.

Expected orchestrator contract:
    validator.validate(question=..., context=..., metadata=...) -> dict

Returned dict examples:

    Valid aggregate HR question:
        {
            "route": null,
            "status": "OK",
            "is_valid": true,
            "reason": null,
            ...
        }

    Sensitive employee-level request:
        {
            "route": "REJECT",
            "status": "ACCESS_DENIED",
            "is_valid": false,
            "reason": "Individual employee information is not allowed.",
            ...
        }

    Known data gap:
        {
            "route": "GAP",
            "status": "DATA_GAP",
            "is_valid": false,
            "reason": "City-level data is not reliable in the current MVP.",
            ...
        }
"""

JsonDict = dict[str, Any]


# ---------------------------------------------------------------------------
# Local constants kept dependency-free to avoid import cycles.
# ---------------------------------------------------------------------------

ROUTE_SQL = "SQL"
ROUTE_GAP = "GAP"
ROUTE_REJECT = "REJECT"
ROUTE_NEEDS_CLARIFICATION = "NEEDS_CLARIFICATION"

STATUS_OK = "OK"
STATUS_VALID = "VALID"
STATUS_DATA_GAP = "DATA_GAP"
STATUS_ANALYTICAL_GAP = "ANALYTICAL_GAP"
STATUS_KNOWLEDGE_GAP = "KNOWLEDGE_GAP"
STATUS_ACCESS_DENIED = "ACCESS_DENIED"
STATUS_OUT_OF_SCOPE = "OUT_OF_SCOPE"
STATUS_NEEDS_CLARIFICATION = "NEEDS_CLARIFICATION"
STATUS_POLICY_VIOLATION = "POLICY_VIOLATION"

DOMAIN_HR = "HR"
DOMAIN_NON_HR = "NON_HR"
DOMAIN_UNKNOWN = "UNKNOWN"


@dataclass(frozen=True)
class ValidationRuleMatch:
    rule_id: str
    category: str
    severity: str
    matched_terms: list[str] = field(default_factory=list)
    message_fa: str | None = None
    message_en: str | None = None
    route: str | None = None
    status: str | None = None

    def to_dict(self) -> JsonDict:
        return asdict(self)


@dataclass
class QuestionValidationResult:
    route: str | None
    status: str
    is_valid: bool
    reason: str | None = None
    confidence: float = 1.0
    normalized_question: str | None = None
    detected_output_level: str | None = None
    detected_question_type: str | None = None
    matched_rules: list[JsonDict] = field(default_factory=list)
    violations: list[str] = field(default_factory=list)
    safety_flags: list[str] = field(default_factory=list)
    gap_candidates: list[str] = field(default_factory=list)
    policy_hints: JsonDict = field(default_factory=dict)
    suggested_next_step: str | None = None
    details: JsonDict = field(default_factory=dict)

    def to_dict(self) -> JsonDict:
        return asdict(self)


class QuestionValidator:
    """
    Validate HR BI Assistant user questions before intent parsing.

    The validator should not generate SQL. It only returns a decision:
        - continue pipeline: route=None, status=OK, is_valid=True
        - reject: route=REJECT, status=ACCESS_DENIED / OUT_OF_SCOPE / NEEDS_CLARIFICATION
        - gap: route=GAP, status=DATA_GAP

    Public methods supported for orchestrator compatibility:
        validate(...)
        run(...)
        arun(...)
        __call__(...)
    """

    def __init__(
        self,
        *,
        min_question_chars: int = 3,
        min_group_size: int = 5,
        allow_direct_sql_from_user: bool = False,
        use_context_domain_result: bool = True,
    ) -> None:
        self.min_question_chars = min_question_chars
        self.min_group_size = min_group_size
        self.allow_direct_sql_from_user = allow_direct_sql_from_user
        self.use_context_domain_result = use_context_domain_result

        self.aggregate_terms = _build_aggregate_terms()
        self.hr_anchor_terms = _build_hr_anchor_terms()
        self.generic_ambiguous_terms = _build_generic_ambiguous_terms()
        self.sensitive_terms = _build_sensitive_terms()
        self.employee_level_terms = _build_employee_level_terms()
        self.prompt_injection_terms = _build_prompt_injection_terms()
        self.dangerous_sql_terms = _build_dangerous_sql_terms()
        self.raw_table_terms = _build_raw_table_terms()
        self.data_gap_rules = _build_data_gap_rules()
        self.out_of_scope_terms = _build_out_of_scope_terms()

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def validate(
        self,
        question: str | None = None,
        *,
        context: Any | None = None,
        metadata: Any | None = None,
        user_role: str | None = None,
    ) -> JsonDict:
        raw_question = (
            question
            or _get_context_value(context, "normalized_question")
            or _get_context_value(context, "question")
            or ""
        )
        normalized_question = self._normalize_question(str(raw_question), metadata=metadata)
        effective_user_role = user_role or _get_context_value(context, "user_role") or "demo_user"
        policy_hints = self._build_policy_hints(
            metadata=metadata, user_role=str(effective_user_role)
        )

        base_details = {
            "user_role": effective_user_role,
            "minimum_group_size": policy_hints.get("minimum_group_size", self.min_group_size),
            "validator_version": "1.0.0",
        }

        if not normalized_question or len(normalized_question.strip()) < self.min_question_chars:
            return QuestionValidationResult(
                route=ROUTE_NEEDS_CLARIFICATION,
                status=STATUS_NEEDS_CLARIFICATION,
                is_valid=False,
                reason="Question is empty, too short, or unclear.",
                confidence=1.0,
                normalized_question=normalized_question,
                detected_output_level="unknown",
                detected_question_type="ambiguous",
                matched_rules=[
                    ValidationRuleMatch(
                        rule_id="QVAL_EMPTY_OR_TOO_SHORT",
                        category="clarification",
                        severity="medium",
                        message_fa="سؤال خیلی کوتاه یا نامشخص است.",
                        route=ROUTE_NEEDS_CLARIFICATION,
                        status=STATUS_NEEDS_CLARIFICATION,
                    ).to_dict()
                ],
                suggested_next_step="Ask the user to provide a clear HR analytics question.",
                policy_hints=policy_hints,
                details=base_details,
            ).to_dict()

        # If domain classifier already made a terminal decision, preserve it.
        domain_terminal = self._check_context_domain_result(context, normalized_question)
        if domain_terminal is not None:
            domain_terminal.normalized_question = normalized_question
            domain_terminal.policy_hints = policy_hints
            domain_terminal.details.update(base_details)
            return domain_terminal.to_dict()

        # Hard security/privacy checks first. These should override Data Gap.
        security_result = self._validate_security_and_privacy(
            normalized_question,
            metadata=metadata,
            policy_hints=policy_hints,
            base_details=base_details,
        )
        if security_result is not None:
            return security_result.to_dict()

        # Clearly out-of-scope questions should not continue to HR intent parsing.
        out_of_scope_result = self._validate_out_of_scope(
            normalized_question,
            context=context,
            policy_hints=policy_hints,
            base_details=base_details,
        )
        if out_of_scope_result is not None:
            return out_of_scope_result.to_dict()

        # Questions known to be unsupported in the current MVP should route to GAP.
        data_gap_result = self._validate_known_data_gaps(
            normalized_question,
            metadata=metadata,
            policy_hints=policy_hints,
            base_details=base_details,
        )
        if data_gap_result is not None:
            return data_gap_result.to_dict()

        # Very generic questions should ask for clarification instead of guessing.
        ambiguity_result = self._validate_ambiguity(
            normalized_question,
            context=context,
            metadata=metadata,
            policy_hints=policy_hints,
            base_details=base_details,
        )
        if ambiguity_result is not None:
            return ambiguity_result.to_dict()

        output_level = self._detect_output_level(normalized_question)
        question_type = self._detect_question_type(normalized_question)
        safety_flags = self._collect_non_terminal_flags(normalized_question, context=context)

        return QuestionValidationResult(
            route=None,
            status=STATUS_OK,
            is_valid=True,
            reason=None,
            confidence=0.92,
            normalized_question=normalized_question,
            detected_output_level=output_level,
            detected_question_type=question_type,
            matched_rules=[
                ValidationRuleMatch(
                    rule_id="QVAL_VALID_AGGREGATED_HR_QUESTION",
                    category="valid",
                    severity="info",
                    message_fa="سؤال برای مسیر بعدی معتبر است.",
                    route=None,
                    status=STATUS_OK,
                ).to_dict()
            ],
            safety_flags=safety_flags,
            policy_hints=policy_hints,
            suggested_next_step="Continue to semantic_mapper.py and intent_parser.py.",
            details={
                **base_details,
                "requires_aggregation": True,
                "must_use_view_only": True,
                "allow_individual_rows": False,
            },
        ).to_dict()

    async def arun(self, *args: Any, **kwargs: Any) -> JsonDict:
        return self.validate(*args, **kwargs)

    def run(self, *args: Any, **kwargs: Any) -> JsonDict:
        return self.validate(*args, **kwargs)

    def __call__(self, *args: Any, **kwargs: Any) -> JsonDict:
        return self.validate(*args, **kwargs)

    # ------------------------------------------------------------------
    # Validation stages
    # ------------------------------------------------------------------

    def _check_context_domain_result(
        self, context: Any | None, question: str = ""
    ) -> QuestionValidationResult | None:
        if not self.use_context_domain_result or context is None:
            return None

        domain_result = _get_context_value(context, "domain_result")
        if not isinstance(domain_result, Mapping) or not domain_result:
            return None

        status = str(domain_result.get("status") or "").upper()
        route = str(domain_result.get("route") or "").upper()
        domain = str(domain_result.get("domain") or "").upper()

        if status == STATUS_OUT_OF_SCOPE or route == ROUTE_REJECT or domain == DOMAIN_NON_HR:
            # Education-specific vocabulary (degree names, "college-educated") is
            # unambiguously HR — bypass the domain rejection when these appear.
            if question and _has_education_hr_signals(question):
                return None
            return QuestionValidationResult(
                route=ROUTE_REJECT,
                status=STATUS_OUT_OF_SCOPE,
                is_valid=False,
                reason="Question is outside the HR BI Assistant domain.",
                confidence=float(domain_result.get("confidence") or 0.95),
                detected_output_level="unknown",
                detected_question_type="out_of_scope",
                matched_rules=[
                    ValidationRuleMatch(
                        rule_id="QVAL_DOMAIN_OUT_OF_SCOPE",
                        category="domain",
                        severity="medium",
                        message_fa="سؤال خارج از دامنه منابع انسانی است.",
                        route=ROUTE_REJECT,
                        status=STATUS_OUT_OF_SCOPE,
                    ).to_dict()
                ],
                violations=["out_of_scope"],
                suggested_next_step="Return OUT_OF_SCOPE response.",
                details={"domain_result": dict(domain_result)},
            )

        if (
            status == STATUS_NEEDS_CLARIFICATION
            or route == ROUTE_NEEDS_CLARIFICATION
            or domain == DOMAIN_UNKNOWN
        ):
            return QuestionValidationResult(
                route=ROUTE_NEEDS_CLARIFICATION,
                status=STATUS_NEEDS_CLARIFICATION,
                is_valid=False,
                reason="Question is too ambiguous to validate safely.",
                confidence=float(domain_result.get("confidence") or 0.8),
                detected_output_level="unknown",
                detected_question_type="ambiguous",
                matched_rules=[
                    ValidationRuleMatch(
                        rule_id="QVAL_DOMAIN_AMBIGUOUS",
                        category="clarification",
                        severity="medium",
                        message_fa="سؤال مبهم است و نیاز به شفاف‌سازی دارد.",
                        route=ROUTE_NEEDS_CLARIFICATION,
                        status=STATUS_NEEDS_CLARIFICATION,
                    ).to_dict()
                ],
                suggested_next_step="Ask a clarification question.",
                details={"domain_result": dict(domain_result)},
            )

        return None

    def _validate_security_and_privacy(
        self,
        question: str,
        *,
        metadata: Any | None,
        policy_hints: JsonDict,
        base_details: JsonDict,
    ) -> QuestionValidationResult | None:
        lower_question = question.lower()

        prompt_matches = _find_terms(
            lower_question, self.prompt_injection_terms, case_sensitive=False
        )
        dangerous_sql_matches = _find_terms(
            lower_question, self.dangerous_sql_terms, case_sensitive=False
        )
        raw_table_matches = _find_terms(lower_question, self.raw_table_terms, case_sensitive=False)
        direct_sql_match = self._looks_like_direct_sql(lower_question)

        # A question that asks about access *policy* ("is it possible?") rather than requesting
        # raw data should be clarified, not denied. Only applies when raw_table is the sole hit.
        _permission_markers = ["ممکنه", "ممکن است", "امکانپذیره", "آیا اجازه", "آیا مجاز"]
        if (
            raw_table_matches
            and not prompt_matches
            and not dangerous_sql_matches
            and not direct_sql_match
            and any(m in lower_question for m in _permission_markers)
        ):
            return QuestionValidationResult(
                route=ROUTE_REJECT,
                status=STATUS_NEEDS_CLARIFICATION,
                is_valid=False,
                reason="Question asks about raw-data access policy rather than requesting data.",
                confidence=0.85,
                normalized_question=question,
                detected_output_level="clarification",
                detected_question_type="access_policy_inquiry",
                matched_rules=[],
                violations=[],
                safety_flags=[],
                policy_hints=policy_hints,
                suggested_next_step="Ask user what specific aggregate information they need.",
                details=base_details,
            )

        if prompt_matches or dangerous_sql_matches or raw_table_matches or direct_sql_match:
            matches: list[JsonDict] = []
            if prompt_matches:
                matches.append(
                    ValidationRuleMatch(
                        rule_id="QVAL_PROMPT_INJECTION",
                        category="security",
                        severity="critical",
                        matched_terms=prompt_matches,
                        message_fa="درخواست شبیه تلاش برای دور زدن قوانین یا پرامپت سیستم است.",
                        route=ROUTE_REJECT,
                        status=STATUS_ACCESS_DENIED,
                    ).to_dict()
                )
            if dangerous_sql_matches:
                matches.append(
                    ValidationRuleMatch(
                        rule_id="QVAL_DANGEROUS_SQL",
                        category="security",
                        severity="critical",
                        matched_terms=dangerous_sql_matches,
                        message_fa="درخواست شامل دستورهای خطرناک یا غیرمجاز SQL است.",
                        route=ROUTE_REJECT,
                        status=STATUS_ACCESS_DENIED,
                    ).to_dict()
                )
            if raw_table_matches:
                matches.append(
                    ValidationRuleMatch(
                        rule_id="QVAL_RAW_TABLE_ACCESS",
                        category="security",
                        severity="high",
                        matched_terms=raw_table_matches,
                        message_fa="در فاز دوم دسترسی به جدول خام مجاز نیست.",
                        route=ROUTE_REJECT,
                        status=STATUS_ACCESS_DENIED,
                    ).to_dict()
                )
            if direct_sql_match:
                matches.append(
                    ValidationRuleMatch(
                        rule_id="QVAL_DIRECT_SQL_FROM_USER",
                        category="security",
                        severity="high",
                        matched_terms=["direct_sql"],
                        message_fa="اجرای SQL مستقیم از طرف کاربر در این مسیر مجاز نیست.",
                        route=ROUTE_REJECT,
                        status=STATUS_ACCESS_DENIED,
                    ).to_dict()
                )

            return QuestionValidationResult(
                route=ROUTE_REJECT,
                status=STATUS_ACCESS_DENIED,
                is_valid=False,
                reason="Unsafe, direct SQL, raw-table, or prompt-injection-like request.",
                confidence=0.99,
                normalized_question=question,
                detected_output_level="unsafe",
                detected_question_type="security_violation",
                matched_rules=matches,
                violations=["unsafe_request"],
                safety_flags=["prompt_injection_or_sql_abuse"],
                policy_hints=policy_hints,
                suggested_next_step="Return ACCESS_DENIED response and do not continue to SQL generation.",
                details={**base_details, "direct_sql_detected": direct_sql_match},
            )

        employee_level_matches = _find_terms(question, self.employee_level_terms)
        sensitive_matches = _find_terms(question, self.sensitive_terms)
        sensitive_column_matches = self._find_sensitive_columns(question, metadata=metadata)
        asks_for_visible_rows = self._asks_for_employee_level_rows(question)

        # Avoid false positive: "employee count" is valid aggregate. Employee-level terms
        # need either sensitive terms or list/detail/output-level signals.
        if (
            sensitive_matches
            or sensitive_column_matches
            or (employee_level_matches and asks_for_visible_rows)
        ):
            return QuestionValidationResult(
                route=ROUTE_REJECT,
                status=STATUS_ACCESS_DENIED,
                is_valid=False,
                reason="Individual employee information or sensitive personal data is not allowed.",
                confidence=0.98,
                normalized_question=question,
                detected_output_level="employee_level",
                detected_question_type="privacy_violation",
                matched_rules=[
                    ValidationRuleMatch(
                        rule_id="QVAL_INDIVIDUAL_OR_SENSITIVE_DATA",
                        category="privacy",
                        severity="critical",
                        matched_terms=sorted(
                            set(
                                employee_level_matches
                                + sensitive_matches
                                + sensitive_column_matches
                            )
                        ),
                        message_fa="نمایش اطلاعات فردی یا حساس کارکنان مجاز نیست.",
                        route=ROUTE_REJECT,
                        status=STATUS_ACCESS_DENIED,
                    ).to_dict()
                ],
                violations=["individual_employee_output", "sensitive_personal_data"],
                safety_flags=["privacy_risk"],
                policy_hints=policy_hints,
                suggested_next_step="Return ACCESS_DENIED response.",
                details={
                    **base_details,
                    "employee_level_matches": employee_level_matches,
                    "sensitive_matches": sensitive_matches,
                    "sensitive_column_matches": sensitive_column_matches,
                },
            )

        return None

    def _validate_out_of_scope(
        self,
        question: str,
        *,
        context: Any | None,
        policy_hints: JsonDict,
        base_details: JsonDict,
    ) -> QuestionValidationResult | None:
        # Domain classifier is the primary owner of this decision. This is a
        # safety net when the validator is used standalone.
        domain_result = _get_context_value(context, "domain_result")
        if isinstance(domain_result, Mapping):
            if str(domain_result.get("domain") or "").upper() == DOMAIN_HR:
                return None

        out_matches = _find_terms(question, self.out_of_scope_terms)
        hr_matches = _find_terms(question, self.hr_anchor_terms)
        if out_matches and not hr_matches:
            return QuestionValidationResult(
                route=ROUTE_REJECT,
                status=STATUS_OUT_OF_SCOPE,
                is_valid=False,
                reason="Question is outside the HR BI Assistant domain.",
                confidence=0.9,
                normalized_question=question,
                detected_output_level="unknown",
                detected_question_type="out_of_scope",
                matched_rules=[
                    ValidationRuleMatch(
                        rule_id="QVAL_OUT_OF_SCOPE_TERMS",
                        category="domain",
                        severity="medium",
                        matched_terms=out_matches,
                        message_fa="سؤال خارج از حوزه منابع انسانی است.",
                        route=ROUTE_REJECT,
                        status=STATUS_OUT_OF_SCOPE,
                    ).to_dict()
                ],
                violations=["out_of_scope"],
                policy_hints=policy_hints,
                suggested_next_step="Return OUT_OF_SCOPE response.",
                details={**base_details, "matched_out_of_scope_terms": out_matches},
            )

        return None

    def _validate_known_data_gaps(
        self,
        question: str,
        *,
        metadata: Any | None,
        policy_hints: JsonDict,
        base_details: JsonDict,
    ) -> QuestionValidationResult | None:
        matched_rules: list[ValidationRuleMatch] = []
        gap_candidates: list[str] = []
        has_analytical_gap = False
        has_knowledge_gap = False

        # Rule definitions intentionally mirror metadata GAP examples.
        for rule in self.data_gap_rules:
            rule_id = str(rule["rule_id"])
            terms = list(rule["terms"])
            required_any = list(rule.get("required_any") or [])
            excluded_any = list(rule.get("excluded_any") or [])
            matched = _find_terms(question, terms)
            if not matched:
                continue
            if required_any and not _find_terms(question, required_any):
                continue
            if excluded_any and _find_terms(question, excluded_any):
                continue
            if rule_id == "QVAL_GAP_CITY" and self._metadata_says_city_is_reliable(metadata):
                continue
            if rule_id == "QVAL_GAP_NEAR_RETIREMENT" and (
                re.search(r"\d+\s*سال", question)
                or _find_terms(question, ["چند نفر", "توزیع", "به تفکیک", "چقدر نیرو"])
            ):
                continue

            gap_type = rule.get("gap_type")
            if gap_type == "analytical":
                has_analytical_gap = True
            elif gap_type == "knowledge":
                has_knowledge_gap = True

            gap_candidates.append(str(rule["gap_key"]))
            matched_rules.append(
                ValidationRuleMatch(
                    rule_id=rule_id,
                    category="data_gap",
                    severity=str(rule.get("severity") or "medium"),
                    matched_terms=matched,
                    message_fa=str(rule.get("message_fa") or "این سؤال در MVP فعلی Data Gap است."),
                    route=ROUTE_GAP,
                    status=STATUS_KNOWLEDGE_GAP
                    if gap_type == "knowledge"
                    else STATUS_ANALYTICAL_GAP
                    if gap_type == "analytical"
                    else STATUS_DATA_GAP,
                )
            )

        if matched_rules:
            primary = matched_rules[0]
            if has_knowledge_gap:
                final_status = STATUS_KNOWLEDGE_GAP
            elif has_analytical_gap:
                final_status = STATUS_ANALYTICAL_GAP
            else:
                final_status = STATUS_DATA_GAP
            return QuestionValidationResult(
                route=ROUTE_GAP,
                status=final_status,
                is_valid=False,
                reason=primary.message_en
                or primary.message_fa
                or "Known Data Gap for the current MVP.",
                confidence=0.94,
                normalized_question=question,
                detected_output_level=self._detect_output_level(question),
                detected_question_type="data_gap",
                matched_rules=[m.to_dict() for m in matched_rules],
                gap_candidates=list(dict.fromkeys(gap_candidates)),
                policy_hints=policy_hints,
                suggested_next_step="Create a Data Gap record and return a helpful limitation message.",
                details={
                    **base_details,
                    "gap_reason_fa": primary.message_fa,
                    "no_guessing_allowed": True,
                },
            )

        return None

    def _validate_ambiguity(
        self,
        question: str,
        *,
        context: Any | None,
        metadata: Any | None,
        policy_hints: JsonDict,
        base_details: JsonDict,
    ) -> QuestionValidationResult | None:
        tokens = _tokenize(question)
        aggregate_matches = _find_terms(question, self.aggregate_terms)
        hr_matches = _find_terms(question, self.hr_anchor_terms)
        generic_matches = _find_terms(question, self.generic_ambiguous_terms)

        metadata_matches = self._safe_metadata_semantic_matches(question, metadata)
        has_metadata_signal = bool(metadata_matches)

        # Very short generic requests like "give report" should not be guessed.
        if generic_matches and not hr_matches and not has_metadata_signal and len(tokens) <= 5:
            return QuestionValidationResult(
                route=ROUTE_NEEDS_CLARIFICATION,
                status=STATUS_NEEDS_CLARIFICATION,
                is_valid=False,
                reason="Question is generic and lacks a clear HR metric or dimension.",
                confidence=0.88,
                normalized_question=question,
                detected_output_level="unknown",
                detected_question_type="ambiguous",
                matched_rules=[
                    ValidationRuleMatch(
                        rule_id="QVAL_GENERIC_AMBIGUOUS_QUESTION",
                        category="clarification",
                        severity="medium",
                        matched_terms=generic_matches,
                        message_fa="سؤال کلی است و مشخص نیست کدام شاخص منابع انسانی مدنظر است.",
                        route=ROUTE_NEEDS_CLARIFICATION,
                        status=STATUS_NEEDS_CLARIFICATION,
                    ).to_dict()
                ],
                policy_hints=policy_hints,
                suggested_next_step="Ask which HR metric or breakdown the user wants.",
                details={**base_details, "metadata_matches_found": len(metadata_matches)},
            )

        # If the question does not request a metric/action and has no metadata
        # signal, intent parsing would likely hallucinate.
        if (
            not aggregate_matches
            and not hr_matches
            and not has_metadata_signal
            and len(tokens) <= 8
        ):
            return QuestionValidationResult(
                route=ROUTE_NEEDS_CLARIFICATION,
                status=STATUS_NEEDS_CLARIFICATION,
                is_valid=False,
                reason="Question does not contain enough HR analytics context.",
                confidence=0.78,
                normalized_question=question,
                detected_output_level="unknown",
                detected_question_type="ambiguous",
                matched_rules=[
                    ValidationRuleMatch(
                        rule_id="QVAL_LOW_CONTEXT_QUESTION",
                        category="clarification",
                        severity="medium",
                        message_fa="برای پاسخ دقیق، سؤال باید شاخص یا بُعد منابع انسانی را مشخص کند.",
                        route=ROUTE_NEEDS_CLARIFICATION,
                        status=STATUS_NEEDS_CLARIFICATION,
                    ).to_dict()
                ],
                policy_hints=policy_hints,
                suggested_next_step="Ask for a more specific HR question.",
                details={**base_details, "tokens": tokens[:20]},
            )

        return None

    # ------------------------------------------------------------------
    # Detection helpers
    # ------------------------------------------------------------------

    def _detect_output_level(self, question: str) -> str:
        if self._asks_for_employee_level_rows(question):
            return "employee_level"
        if _find_terms(question, self.aggregate_terms):
            return "aggregated"
        return "unknown"

    def _detect_question_type(self, question: str) -> str:
        if _find_terms(question, ["چند درصد", "درصد", "سهم", "نسبت"]):
            return "percentage"
        if _find_terms(question, ["میانگین", "متوسط"]):
            return "average"
        if _find_terms(question, ["روند", "سالانه", "۱۵ سال", "15 سال", "سال جذب"]):
            return "trend"
        if _find_terms(question, ["بیشترین", "کمترین", "حداکثر", "حداقل", "کدام"]):
            return "ranking"
        if _find_terms(question, ["تفکیک", "بر اساس", "به تفکیک", "در هر"]):
            return "grouped_count"
        if _find_terms(question, ["تعداد", "چند نفر", "چقدر"]):
            return "count"
        if _find_terms(question, ["آیا", "ریسک", "اثر", "تأثیر", "تحلیل"]):
            return "analytical"
        return "general"

    def _asks_for_employee_level_rows(self, question: str) -> bool:
        row_terms = [
            "لیست",
            "فهرست",
            "اسامی",
            "نام کارکنان",
            "نام و مشخصات",
            "مشخصات",
            "اطلاعات فردی",
            "تک تک",
            "هر نفر",
            "هر کارمند",
            "به ازای هر کارمند",
            "ردیف",
            "رکورد",
            "همه کارکنان را نمایش بده",
            "تمام کارکنان را نمایش بده",
            "نمایش همه کارکنان",
            "خروجی اکسل کارکنان",
            "export employees",
        ]
        return bool(_find_terms(question, row_terms))

    def _looks_like_direct_sql(self, question_lower: str) -> bool:
        if self.allow_direct_sql_from_user:
            return False
        # Direct SELECT may be a user trying to bypass the template engine.
        # Avoid false positive for ordinary Persian questions by requiring SQL keywords.
        sql_patterns = [
            r"\bselect\b.+\bfrom\b",
            r"\bwith\b.+\bselect\b",
            r"\bwhere\b.+\bgroup\s+by\b",
            r"\bfrom\s+hr_mvp\.",
        ]
        return any(
            re.search(pattern, question_lower, flags=re.IGNORECASE | re.DOTALL)
            for pattern in sql_patterns
        )

    def _find_sensitive_columns(self, question: str, *, metadata: Any | None) -> list[str]:
        # Static list from access policy and prompt/schema context.
        static_sensitive_columns = [
            "national_id",
            "personnel_number",
            "first_name",
            "last_name",
            "phone_number",
            "address",
            "bank_account",
            "insurance_number",
            "personal_identifier",
            "کد ملی",
            "شماره ملی",
            "شماره پرسنلی",
            "نام خانوادگی",
            "شماره تماس",
            "حساب بانکی",
            "شماره بیمه",
        ]
        matches = _find_terms(question, static_sensitive_columns, case_sensitive=False)

        # Metadata-aware sensitivity scan when available.
        try:
            columns = (
                metadata.list_columns()
                if metadata is not None and hasattr(metadata, "list_columns")
                else []
            )
        except Exception:
            columns = []

        for col in columns or []:
            if not isinstance(col, Mapping):
                continue
            name = str(col.get("column_name") or col.get("name") or "")
            sensitivity = str(col.get("sensitivity") or col.get("privacy_level") or "").lower()
            output_allowed = col.get("output_allowed")
            if not name:
                continue
            is_sensitive = any(
                token in sensitivity for token in ["sensitive", "restricted", "personal", "pii"]
            )
            if output_allowed is False or is_sensitive:
                if name.lower() in question.lower():
                    matches.append(name)

        return sorted(set(matches))

    def _collect_non_terminal_flags(self, question: str, *, context: Any | None) -> list[str]:
        flags: list[str] = []
        domain_result = _get_context_value(context, "domain_result")
        if isinstance(domain_result, Mapping):
            for flag in domain_result.get("safety_flags", []) or []:
                if isinstance(flag, str):
                    flags.append(flag)
        if _find_terms(question, ["تحلیل", "ریسک", "اثر", "تأثیر"]):
            flags.append("analytical_question")
        if _find_terms(question, ["درصد", "سهم", "نسبت"]):
            flags.append("percentage_question")
        if _find_terms(question, ["چارت مصوب", "کمبود نیرو", "نیروی موجود"]):
            flags.append("headcount_gap_sensitive_calculation")
        return list(dict.fromkeys(flags))

    def _normalize_question(self, question: str, *, metadata: Any | None) -> str:
        if metadata is not None and hasattr(metadata, "normalize_question"):
            try:
                normalized = metadata.normalize_question(question)
                if isinstance(normalized, str):
                    return normalized.strip()
            except Exception:
                pass
        return normalize_fa_text(question)

    def _safe_metadata_semantic_matches(
        self, question: str, metadata: Any | None
    ) -> list[JsonDict]:
        if metadata is None or not hasattr(metadata, "find_semantic_matches"):
            return []
        try:
            matches = metadata.find_semantic_matches(question, max_matches=10)
            return [m for m in matches if isinstance(m, Mapping)]
        except Exception:
            return []

    def _metadata_says_city_is_reliable(self, metadata: Any | None) -> bool:
        if metadata is None:
            return False
        try:
            column = metadata.get_column("city") if hasattr(metadata, "get_column") else None
        except Exception:
            column = None
        if isinstance(column, Mapping):
            for key in ("data_status", "reliability", "quality", "is_reliable"):
                val = column.get(key)
                if isinstance(val, bool):
                    return val
                if isinstance(val, str) and val.lower() in {
                    "reliable",
                    "populated",
                    "available",
                    "true",
                }:
                    return True
        return False

    def _build_policy_hints(self, *, metadata: Any | None, user_role: str) -> JsonDict:
        hints = {
            "user_role": user_role,
            "output_level": "aggregated_only",
            "allow_individual_employee_output": False,
            "allow_sensitive_personal_data": False,
            "allow_raw_table_access": False,
            "allow_join": False,
            "allow_select_star": False,
            "minimum_group_size": self.min_group_size,
            "status_for_individual_output": STATUS_ACCESS_DENIED,
            "status_for_missing_data": STATUS_DATA_GAP,
        }

        # Best-effort extraction from access_policies metadata if MetadataService
        # exposes it directly or through get_metadata.
        policies: Any = None
        for attr in ("access_policies", "metadata", "documents"):
            obj = getattr(metadata, attr, None) if metadata is not None else None
            if isinstance(obj, Mapping):
                policies = (
                    obj.get("access_policies") or obj.get("Template_08_access_policies") or obj
                )
                break
        if policies is None and metadata is not None and hasattr(metadata, "get_metadata"):
            try:
                policies = metadata.get_metadata("access_policies")
            except Exception:
                policies = None

        if isinstance(policies, Mapping):
            default_policy = (
                policies.get("default_policy")
                if isinstance(policies.get("default_policy"), Mapping)
                else {}
            )
            aggregation_rules = (
                policies.get("aggregation_rules")
                if isinstance(policies.get("aggregation_rules"), Mapping)
                else {}
            )
            minimum_group = (
                aggregation_rules.get("minimum_group_size")
                if isinstance(aggregation_rules.get("minimum_group_size"), Mapping)
                else {}
            )
            if "allow_individual_employee_output" in default_policy:
                hints["allow_individual_employee_output"] = bool(
                    default_policy.get("allow_individual_employee_output")
                )
            if "allow_sensitive_personal_data" in default_policy:
                hints["allow_sensitive_personal_data"] = bool(
                    default_policy.get("allow_sensitive_personal_data")
                )
            if "allow_raw_table_access_for_llm" in default_policy:
                hints["allow_raw_table_access"] = bool(
                    default_policy.get("allow_raw_table_access_for_llm")
                )
            if isinstance(minimum_group.get("value"), int):
                hints["minimum_group_size"] = int(minimum_group["value"])

        return hints


# ---------------------------------------------------------------------------
# Term builders
# ---------------------------------------------------------------------------


def _build_aggregate_terms() -> list[str]:
    return [
        "تعداد",
        "چند نفر",
        "چقدر",
        "درصد",
        "سهم",
        "نسبت",
        "میانگین",
        "متوسط",
        "تفکیک",
        "بر اساس",
        "به تفکیک",
        "در هر",
        "روند",
        "سالانه",
        "بیشترین",
        "کمترین",
        "حداکثر",
        "حداقل",
        "توزیع",
        "اختلاف",
        "گپ",
        "کمبود",
        "نیروی موجود",
        "چارت مصوب",
        "شاخص",
        "kpi",
    ]


def _build_hr_anchor_terms() -> list[str]:
    return [
        "کارکنان",
        "کارمند",
        "پرسنل",
        "نیروی انسانی",
        "منابع انسانی",
        "جنسیت",
        "زن",
        "مرد",
        "سن",
        "گروه سنی",
        "بازنشستگی",
        "مدرک",
        "تحصیلات",
        "رشته تحصیلی",
        "دکترا",
        "دکتری",
        "نوع استخدام",
        "نوع قرارداد",
        "پیمانکاری",
        "قراردادی",
        "رسمی",
        "پیمانی",
        "حوزه خدمت",
        "حوزه",
        "واحد",
        "بخش",
        "اداره",
        "دپارتمان",
        "استان",
        "محل خدمت",
        "پست",
        "عنوان پست",
        "استخدام",
        "جذب",
        "سال جذب",
        "سابقه",
        "چارت مصوب",
        "کمبود نیرو",
        "وضعیت تأهل",
        "وضعیت تاهل",
    ]


def _build_generic_ambiguous_terms() -> list[str]:
    return [
        "گزارش بده",
        "گزارش را بده",
        "آمار بده",
        "تحلیل کن",
        "وضعیت چطوره",
        "وضعیت را نشان بده",
        "داشبورد را نشان بده",
        "نمودار بده",
        "جدول بده",
        "این را تحلیل کن",
        "روند را بگو",
    ]


def _build_sensitive_terms() -> list[str]:
    return [
        "کد ملی",
        "شماره ملی",
        "شماره پرسنلی",
        "کد پرسنلی",
        "شناسه پرسنلی",
        "شماره تماس",
        "تلفن",
        "موبایل",
        "آدرس",
        "نشانی",
        "حساب بانکی",
        "شماره حساب",
        "شماره شبا",
        "شماره بیمه",
        "حقوق هر فرد",
        "فیش حقوقی",
        "پرونده پرسنلی",
        "اطلاعات شخصی",
        "اطلاعات فردی",
        "اطلاعات کامل",
        "جزئیات شخصی",
        "پروفایل کامل",
        "مشخصات فردی",
        "مشخصات کارکنان",
        "نام و نام خانوادگی",
        "نام خانوادگی",
        "تاریخ تولد",
        "با شناسه",
        "با کدشون",
        "national_id",
        "personnel_number",
        "first_name",
        "last_name",
        "phone_number",
        "bank_account",
        "insurance_number",
    ]


def _build_employee_level_terms() -> list[str]:
    return [
        "لیست کارکنان",
        "لیست افراد",
        "فهرست کارکنان",
        "فهرست افراد",
        "اسامی کارکنان",
        "لیست اسامی",
        "نام کارکنان",
        "نام و مشخصات",
        "مشخصات کارکنان",
        "اطلاعات کارکنان",
        "تک تک کارکنان",
        "هر کارمند",
        "هر نفر",
        "به ازای هر کارمند",
        "ردیف کارکنان",
        "رکورد کارکنان",
        "تمام کارکنان را نمایش بده",
        "همه کارکنان را نمایش بده",
        "خروجی اکسل کارکنان",
        "employee list",
        "employee details",
    ]


def _build_prompt_injection_terms() -> list[str]:
    return [
        "ignore previous",
        "ignore all",
        "ignore the previous",
        "system prompt",
        "developer message",
        "show your prompt",
        "reveal prompt",
        "bypass",
        "jailbreak",
        "دستور قبلی",
        "قوانین قبلی",
        "پرامپت قبلی",
        "پرامپت سیستم",
        "پیام سیستم",
        "قوانین را نادیده بگیر",
        "دستورها را نادیده بگیر",
        "از محدودیت عبور کن",
        "بدون اعتبارسنجی اجرا کن",
        "sql validator را دور بزن",
    ]


def _build_dangerous_sql_terms() -> list[str]:
    return [
        "drop table",
        "delete from",
        "truncate",
        "alter table",
        "insert into",
        "update ",
        "create table",
        "create view",
        "grant ",
        "revoke ",
        "copy ",
        "pg_catalog",
        "information_schema",
        ";--",
        "--",
        "/*",
        "*/",
        "حذف جدول",
        "پاک کن جدول",
        "آپدیت کن",
        "تغییر جدول",
        "ساخت جدول",
    ]


def _build_raw_table_terms() -> list[str]:
    return [
        "hr_mvp.hr_employees",
        "hr_mvp.hr_contracts",
        "hr_mvp.hr_employee_education",
        "hr_mvp.hr_education_levels",
        "hr_mvp.hr_departments",
        "hr_mvp.hr_positions",
        "hr_mvp.hr_locations",
        "hr_mvp.hr_age_groups",
        "hr_employees",
        "hr_contracts",
        "hr_employee_education",
        "hr_education_levels",
        "hr_departments",
        "hr_positions",
        "hr_locations",
        "hr_age_groups",
        "جدول خام",
        "جداول خام",
        "اطلاعات خام",
        "raw table",
        "base table",
    ]


def _build_data_gap_rules() -> list[JsonDict]:
    return [
        {
            "rule_id": "QVAL_GAP_CITY",
            "gap_key": "city_level_analysis",
            "terms": [
                "شهر",
                "شهری",
                "هر شهر",
                "سطح شهر",
                "تهران",
                "مشهد",
                "اصفهان",
                "شیراز",
                "تبریز",
                "کرج",
            ],
            "excluded_any": ["استان"],
            "severity": "medium",
            "message_fa": "در داده MVP فعلی، اطلاعات شهر قابل اتکا نیست و باید به عنوان Data Gap ثبت شود.",
        },
        {
            "rule_id": "QVAL_GAP_NEAR_RETIREMENT",
            "gap_key": "near_retirement_analysis",
            # Only catch conceptual "about to retire" questions without an explicit threshold.
            # "آستانه بازنشستگی" and plain "بازنشستگی" are covered by the near_retirement_analysis
            # template (age >= 60) and by dedicated KNOWLEDGE_GAP rules for policy/law questions.
            "terms": ["نزدیک بازنشستگی", "در شرف بازنشستگی"],
            "severity": "high",
            "message_fa": "برای پاسخ دقیق، قانون رسمی بازنشستگی بر اساس سن، سابقه، جنسیت و قواعد سازمانی باید تعریف شود.",
        },
        {
            "rule_id": "QVAL_GAP_CONTRACTOR_PRODUCTIVITY",
            "gap_key": "contractor_productivity_analysis",
            "terms": [
                "بهره وری پیمانکار",
                "بهره‌وری پیمانکار",
                "بهره وری پیمانکاری",
                "بهره‌وری پیمانکاری",
                "بهره وری نیروی پیمانکاری",
                "بهره‌وری نیروی پیمانکاری",
                "بهره وری نیروهای پیمانکاری",
                "بهره‌وری نیروهای پیمانکاری",
                "عملکرد پیمانکار",
            ],
            "severity": "medium",
            "gap_type": "analytical",
            "message_fa": "داده بهره‌وری یا شاخص عملکرد پیمانکارها در MVP فعلی وجود ندارد.",
        },
        {
            "rule_id": "QVAL_GAP_MONTHLY_HIRING",
            "gap_key": "monthly_hiring_trend",
            "terms": ["ماهانه", "هر ماه", "ماه به ماه", "ماه جذب", "جذب ماه"],
            "required_any": ["جذب", "استخدام", "نیرو"],
            "severity": "medium",
            "message_fa": "تحلیل ماهانه جذب در MVP فعلی قابل اتکا نیست؛ فعلاً تحلیل جذب بر اساس hire_year انجام می‌شود.",
        },
        {
            "rule_id": "QVAL_GAP_WORKLOAD_ALIGNMENT",
            "gap_key": "hiring_workload_alignment",
            "terms": ["حجم کار", "افزایش کار", "بار کاری", "رشد کار", "هماهنگ بوده", "هماهنگی جذب"],
            "severity": "medium",
            "gap_type": "analytical",
            "message_fa": "برای سنجش هماهنگی جذب با حجم کار، داده حجم کار یا شاخص عملیاتی لازم است.",
        },
        {
            "rule_id": "QVAL_GAP_TRAINING_NEED",
            "gap_key": "education_training_need_analysis",
            "terms": [
                "نیاز آموزشی",
                "نیاز به آموزش",
                "دوره تخصصی",
                "کمبود تخصص",
                "افزایش نیاز به آموزش",
            ],
            "severity": "medium",
            "gap_type": "analytical",
            "message_fa": "تحلیل نیاز آموزشی نیازمند تعریف شاخص یا اسناد آموزشی است و در MVP فعلی کامل نیست.",
        },
        {
            "rule_id": "QVAL_GAP_AGING_STRUCTURE",
            "gap_key": "workforce_aging_trend_analysis",
            "terms": [
                "سالخوردگی",
                "پیر شدن",
                "پیر میشه",
                "پیر میشود",
                "پیر می‌شود",
                "به سمت سالخوردگی",
                "ساختار کلی کارکنان به سمت",
            ],
            "severity": "medium",
            "gap_type": "analytical",
            "message_fa": "تحلیل سالخوردگی نیروی انسانی نیازمند تعریف آستانه و منطق تحلیلی رسمی است.",
        },
        {
            "rule_id": "QVAL_GAP_KNOWLEDGE_DEFINITION",
            "gap_key": "hr_terminology_definition",
            "terms": ["تعریف", "منظور از", "مفهوم", "چه مفهومیه", "چه مفهومی"],
            "required_any": ["چیست", "چیه", "است؟", "هست؟", "مفهومیه"],
            "severity": "medium",
            "gap_type": "knowledge",
            "message_fa": "این سؤال درباره تعریف یا مفهوم یک اصطلاح است. پیش از ارائه RAG، پاسخ مستند در سیستم موجود نیست.",
        },
        {
            "rule_id": "QVAL_GAP_KNOWLEDGE_MEANING",
            "gap_key": "hr_terminology_meaning",
            "terms": ["یعنی چه", "یعنی چی"],
            "severity": "medium",
            "gap_type": "knowledge",
            "message_fa": "این سؤال درباره معنی یک اصطلاح HR است و نیاز به منبع دانشی دارد.",
        },
        {
            "rule_id": "QVAL_GAP_KNOWLEDGE_DIFFERENCE",
            "gap_key": "hr_terminology_difference",
            "terms": ["تفاوت", "فرق"],
            "required_any": ["چیست", "چیه", "دارن", "دارند"],
            "excluded_any": ["تعداد", "چند نفر", "چقدر است", "چند درصد"],
            "severity": "medium",
            "gap_type": "knowledge",
            "message_fa": "این سؤال درباره تفاوت مفهومی دو اصطلاح است و نیاز به منبع دانشی دارد.",
        },
        {
            "rule_id": "QVAL_GAP_KNOWLEDGE_METHODOLOGY",
            "gap_key": "hr_indicator_methodology",
            # Use short stem so normalization variants (می‌شود / می شود / میشود) all match
            "terms": ["چگونه محاسبه", "چطور محاسبه", "نحوه محاسبه شاخص", "فرمول محاسبه"],
            "required_any": ["شاخص", "محاسبه"],
            "severity": "medium",
            "gap_type": "knowledge",
            "message_fa": "این سؤال درباره نحوه محاسبه یک شاخص است و نیاز به مستند روش‌شناسی دارد.",
        },
        {
            "rule_id": "QVAL_GAP_KNOWLEDGE_HOW_CALCULATED",
            "gap_key": "hr_indicator_methodology",
            "terms": ["حساب میشه", "چطوری حساب"],
            "severity": "medium",
            "gap_type": "knowledge",
            "message_fa": "نحوه محاسبه این شاخص در سیستم HR مستند نیست.",
        },
        {
            "rule_id": "QVAL_GAP_KNOWLEDGE_WHO_IS",
            "gap_key": "hr_employee_type_definition",
            "terms": ["کیه", "کیست"],
            "required_any": [
                "پیمانی",
                "پیمانکاری",
                "رسمی",
                "قراردادی",
                "کارمند",
                "نیرو",
                "فعال",
                "استخدام",
            ],
            "severity": "medium",
            "gap_type": "knowledge",
            "message_fa": "تعریف این نوع نیروی انسانی در سیستم مستند نیست.",
        },
        {
            "rule_id": "QVAL_GAP_KNOWLEDGE_RETIREMENT_POLICY",
            "gap_key": "retirement_policy_knowledge",
            "terms": [
                "سیاست سازمان",
                "سیاست بازنشستگی",
                "قانون بازنشستگی",
                "رویه بازنشستگی",
            ],
            "severity": "medium",
            "gap_type": "knowledge",
            "message_fa": "سیاست‌های بازنشستگی سازمان در سیستم مستند نیست و نیاز به منبع دانشی دارد.",
        },
        {
            "rule_id": "QVAL_GAP_KNOWLEDGE_RETIREMENT_LAW",
            "gap_key": "retirement_law_knowledge",
            "terms": ["قانون رسمی"],
            "required_any": ["بازنشستگی", "سن بازنشستگی"],
            "severity": "medium",
            "gap_type": "knowledge",
            "message_fa": "قانون رسمی بازنشستگی تعریف نشده است و نیاز به منبع دانشی دارد.",
        },
        {
            "rule_id": "QVAL_GAP_KNOWLEDGE_RETIREMENT_CRITERIA",
            "gap_key": "retirement_age_criteria_knowledge",
            "terms": ["سن بازنشستگی", "ملاک سنی", "از چند سالگی"],
            "required_any": ["چند ساله", "چیه", "چیست", "بازنشستگی", "نزدیک حساب", "ملاک"],
            "excluded_any": ["چند نفر", "تعداد کارکنان", "توزیع"],
            "severity": "medium",
            "gap_type": "knowledge",
            "message_fa": "ملاک سنی بازنشستگی در سیستم تعریف نشده و نیاز به منبع دانشی دارد.",
        },
        {
            "rule_id": "QVAL_GAP_ANALYTICAL_RISK_ASSESSMENT",
            "gap_key": "risk_assessment_analysis",
            "terms": [
                "چه ریسکی",
                "چه خطری",
                "ریسکی برای سازمان",
                "ریسکی ایجاد می کند",
                "ریسکی ایجاد می‌کند",
                "ریسک داره",
                "ریسک دارد",
                "چه تهدیدی",
                "تهدیدی برای سازمان",
            ],
            "severity": "medium",
            "gap_type": "analytical",
            "message_fa": "ارزیابی ریسک نیازمند تعریف شاخص، آستانه و داده تحلیلی فراتر از داده‌های جاری است.",
        },
        {
            "rule_id": "QVAL_GAP_ANALYTICAL_MANAGEMENT_JUDGMENT",
            "gap_key": "management_judgment_analysis",
            "terms": [
                "نیازمند توجه مدیریتی",
                "نیاز به توجه مدیریتی",
                "نیاز مدیریتی دارد",
                "نیاز به توجه داره",
                "نیاز به توجه دارد",
                "نگران‌کننده",
                "نگران کننده",
                "چالش داره",
                "چالش دارد",
            ],
            "severity": "medium",
            "gap_type": "analytical",
            "message_fa": "تشخیص نیاز مدیریتی نیازمند معیار، وزن‌دهی و قضاوت تخصصی است که در سیستم تعریف نشده.",
        },
        {
            "rule_id": "QVAL_GAP_ANALYTICAL_ALIGNMENT",
            "gap_key": "organizational_need_alignment_analysis",
            "terms": ["همگام بوده", "همخوانی داره", "همخوانی دارد"],
            "required_any": ["نیاز", "کارکنان", "تحصیلات", "جذب"],
            # Org chart vs headcount questions are SQL-answerable; exclude them.
            "excluded_any": ["چارت"],
            "severity": "medium",
            "gap_type": "analytical",
            "message_fa": "سنجش همخوانی با نیاز سازمانی نیازمند داده عملیاتی و معیار رسمی است.",
        },
        {
            "rule_id": "QVAL_GAP_JOB_FAMILY",
            "gap_key": "job_family_analysis",
            "terms": ["خانواده شغلی"],
            "severity": "medium",
            "message_fa": "ستون خانواده شغلی در view تحلیلی MVP فعلی موجود نیست.",
        },
        {
            "rule_id": "QVAL_GAP_KNOWLEDGE_ACTIVE_EMPLOYEE",
            "gap_key": "hr_active_employee_definition",
            "terms": ["کارمند فعال", "نیروی فعال", "کارکن فعال"],
            "required_any": ["کیه", "کیست", "چیه", "چیست"],
            "severity": "medium",
            "gap_type": "knowledge",
            "message_fa": "تعریف 'کارمند فعال' در سیستم مستند نیست و نیاز به منبع دانشی دارد.",
        },
    ]


def _build_out_of_scope_terms() -> list[str]:
    return [
        "فروش",
        "درآمد",
        "سود",
        "زیان",
        "هزینه مالی",
        "مشتری",
        "بازاریابی",
        "کمپین",
        "انبار",
        "موجودی کالا",
        "تولید محصول",
        "قیمت سهام",
        "بورس",
        "آب و هوا",
        "weather",
        "sales",
        "revenue",
        "profit",
        "inventory",
        "customer",
    ]


# ---------------------------------------------------------------------------
# Utility functions
# ---------------------------------------------------------------------------


def normalize_fa_text(text: str) -> str:
    text = unicodedata.normalize("NFKC", text or "")
    replacements = {
        "ي": "ی",
        "ك": "ک",
        "ة": "ه",
        "ۀ": "ه",
        "ؤ": "و",
        "إ": "ا",
        "أ": "ا",
        "آ": "آ",
        "‌": " ",
        "\u200f": "",
        "\u200e": "",
    }
    for src, dst in replacements.items():
        text = text.replace(src, dst)
    text = _translate_digits_to_ascii(text)
    text = re.sub(r"\s+", " ", text).strip()
    return text


def _translate_digits_to_ascii(text: str) -> str:
    persian = "۰۱۲۳۴۵۶۷۸۹"
    arabic = "٠١٢٣٤٥٦٧٨٩"
    for idx, ch in enumerate(persian):
        text = text.replace(ch, str(idx))
    for idx, ch in enumerate(arabic):
        text = text.replace(ch, str(idx))
    return text


def _has_education_hr_signals(question: str) -> bool:
    """Return True when question contains unambiguous HR-education vocabulary.

    Used to override a NON_HR domain classifier verdict: these terms are
    specific enough to degree levels that the question is almost certainly
    about employee education distribution.
    """
    specific_edu = [
        "فوق‌لیسانس",
        "فوق لیسانس",  # master's degree (also matches فوق‌لیسانسا)
        "دانشگاه‌دیده",
        "دانشگاه دیده",  # university-educated
        "دانشگاه‌رفته",
        "دانشگاه رفته",  # went to university
    ]
    if any(t in question for t in specific_edu):
        return True
    # "مدارک" alone is ambiguous (can mean documents); require org context.
    org_anchors = ["سازمان", "کارکنان", "پرسنل", "نیرو"]
    if "مدارک" in question and any(a in question for a in org_anchors):
        return True
    return False


def _find_terms(text: str, terms: Iterable[str], *, case_sensitive: bool = True) -> list[str]:
    if not case_sensitive:
        haystack = text.lower()
        found = [term for term in terms if term and term.lower() in haystack]
    else:
        found = [term for term in terms if term and term in text]
    return sorted(set(found), key=lambda item: (-len(item), item))


def _tokenize(text: str) -> list[str]:
    return [tok for tok in re.split(r"[\s،,.؛:!?؟()\[\]{}<>\"']+", text) if tok]


def _get_context_value(context: Any | None, key: str) -> Any:
    if context is None:
        return None
    if isinstance(context, Mapping):
        return context.get(key)
    return getattr(context, key, None)


# Convenient module-level singleton/factory helpers.
def get_question_validator(**kwargs: Any) -> QuestionValidator:
    return QuestionValidator(**kwargs)


DEFAULT_QUESTION_VALIDATOR = QuestionValidator()


# Backward-compatible aliases some teams prefer.
Validator = QuestionValidator
HRQuestionValidator = QuestionValidator
