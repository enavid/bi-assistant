"""Manual high-precision intent rules (Phase 3.1, target A).

Extracted from the ``IntentParser._manual_intent_rules`` God method into an
ordered registry of small, individually testable rule functions. Each rule is a
pure callable ``(RuleContext) -> list[(intent_id, score, reason)]``; the registry
``MANUAL_INTENT_RULES`` preserves the original top-to-bottom evaluation order, so
``evaluate()`` reproduces the legacy method's output exactly (locked by
tests/test_intent_parser_parity.py). Scoring is additive downstream, so a rule
only ever *contributes* candidate (intent, score) pairs.

The rules depend only on the question text, the detected ``features`` mapping and
a handful of metadata-backed helpers, all reached through ``RuleContext`` — the
module imports nothing from intent_parser, keeping the dependency one-way.
"""

from __future__ import annotations

from collections.abc import Callable, Iterable, Mapping
from dataclasses import dataclass
from typing import Any

Rule = Callable[["RuleContext"], list[tuple[str, float, str]]]


@dataclass
class RuleContext:
    """Read-only inputs + helper delegates shared by every rule."""

    question: str
    features: Mapping[str, Any]
    service: Any
    parser: Any  # IntentParser; source of the shared text/metadata helpers
    month_range_fn: Callable[[str], tuple[int, int] | None]

    @property
    def f(self) -> Mapping[str, Any]:
        return self.features

    def has_any(self, terms: Iterable[str]) -> bool:
        return self.parser._has_any(self.question, terms)

    def term_in_question(self, term: str) -> bool:
        return self.parser._term_in_question(self.question, term)

    def dept_keyword_filter(self):
        return self.parser._extract_department_keyword_filter(self.question)

    def service_domain_value(self):
        return self.parser._extract_service_domain_value(self.question, self.service)

    def shamsi_month_range(self) -> tuple[int, int] | None:
        return self.month_range_fn(self.question)


def _rule_individual(ctx: RuleContext) -> list[tuple[str, float, str]]:
    out: list[tuple[str, float, str]] = []
    if ctx.f.get("asks_individual"):
        out.append(("individual_employee_info", 100, "sensitive_or_individual_request"))
    return out


def _rule_contract_dates(ctx: RuleContext) -> list[tuple[str, float, str]]:
    out: list[tuple[str, float, str]] = []
    # Annual trend of contract-end Shamsi years. Only the derived year is
    # exposed (via hr_mvp.shamsi_year()), never the exact date — checked
    # before the plain "ending soon" count rule so "روند" wins.
    if (
        ctx.has_any(["قرارداد"])
        and ctx.has_any(["روند"])
        and ctx.has_any(["پایان قرارداد", "تموم میشه", "تموم میشود", "اتمام قرارداد"])
    ):
        out.append(("contract_ending_trend_annual", 92, "contract_ending_trend"))

    # Aggregate count of contracts ending soon. contract_end_date is used
    # only as a WHERE filter (never SELECTed/grouped), so this stays
    # compliant with the "filter_only_if_explicit_and_safe" validator rule.
    if ctx.has_any(["قرارداد"]) and ctx.has_any(
        ["تموم میشه", "تموم میشود", "تمدید", "پایان قرارداد", "اتمام قرارداد"]
    ):
        out.append(("employee_count_contract_ending_soon", 90, "contract_ending_soon"))
    return out


def _rule_birth_hire_month(ctx: RuleContext) -> list[tuple[str, float, str]]:
    out: list[tuple[str, float, str]] = []
    # Aggregate count by Shamsi birth/hire month or season. hire_date/birth_date
    # are used only as a WHERE filter (via hr_mvp.shamsi_month()), never
    # SELECTed or grouped directly.
    _month_range = ctx.shamsi_month_range()
    if _month_range is not None:
        if ctx.has_any(["متولد", "تولد", "به دنیا"]):
            out.append(("employee_count_by_birth_month", 90, "birth_month_filter"))
        elif ctx.has_any(["استخدام", "جذب"]):
            out.append(("employee_count_by_hire_month", 90, "hire_month_filter"))
    elif ctx.has_any(["ماه گذشته", "ماه پیش"]) and ctx.has_any(["استخدام", "جذب"]):
        # No specific month named ("ماه گذشته"/"ماه پیش") — compute the
        # range dynamically relative to CURRENT_DATE via
        # hr_mvp.shamsi_to_gregorian(), the reverse of shamsi_month()/year().
        out.append(("employee_count_hired_last_month", 90, "hired_last_month"))
    return out


def _rule_city(ctx: RuleContext) -> list[tuple[str, float, str]]:
    out: list[tuple[str, float, str]] = []
    if ctx.f.get("explicit_city"):
        out.append(("city_level_analysis", 90, "city_level_data_gap"))
    return out


def _rule_public_recruitment(ctx: RuleContext) -> list[tuple[str, float, str]]:
    out: list[tuple[str, float, str]] = []
    if ctx.has_any(["جذب عمومی", "آزمون استخدامی", "منبع جذب"]):
        out.append(("public_recruitment_channel_analysis", 92, "no_hire_source_column"))
    return out


def _rule_terminated_retirement(ctx: RuleContext) -> list[tuple[str, float, str]]:
    out: list[tuple[str, float, str]] = []
    question = ctx.question
    _terminated_terms = [
        "اخراج",
        "اخراجی",
        "اخراج شده",
        "اخراجی‌ها",
        "غیرفعال",
        "ترک خدمت",
        "ترک کرده",
        "پایان کار",
        "خروج از سازمان",
        "بازنشستگان",
    ]
    _near_retirement_indicators = [
        "آستانه بازنشستگی",
        "نزدیک بازنشستگی",
        "در شرف بازنشستگی",
        "بازنشسته می‌شوند",
        "بازنشسته میشوند",
        "بازنشسته می‌شود",
        "بازنشسته میشود",
        "بازنشسته خواهند",
        "سال آینده بازنشسته",
        "ریسک بازنشستگی",
        "به زودی بازنشسته",
    ]
    if ctx.has_any(_terminated_terms) or (
        "بازنشسته" in question and not ctx.has_any(_near_retirement_indicators)
    ):
        out.append(("terminated_employee_analysis", 200, "terminated_employee_data_gap"))
    if ctx.has_any(["آستانه بازنشستگی", "نزدیک بازنشستگی", "در شرف بازنشستگی", "بازنشستگی قریب"]):
        out.append(("near_retirement_analysis", 300, "near_future_retirement_keywords"))
    if ctx.has_any(["بازنشستگی", "بازنشسته می‌شوند", "بازنشسته میشوند", "بازنشسته خواهند"]):
        out.append(("near_retirement_analysis", 90, "retirement_keywords"))
    return out


def _rule_analytical_gaps(ctx: RuleContext) -> list[tuple[str, float, str]]:
    out: list[tuple[str, float, str]] = []
    question = ctx.question
    if ctx.has_any(["بهره وری پیمانکار", "بهره وری پیمانکاری", "عملکرد پیمانکار"]):
        out.append(("contractor_productivity_analysis", 90, "contractor_productivity_gap"))
    if ctx.has_any(
        ["افزایش کار", "رشد کار", "حجم کار", "گسترش سازمان", "رشد سازمان", "توسعه سازمان"]
    ):
        out.append(("hiring_business_growth_alignment", 80, "business_growth_data_gap"))
    if "متناسب" in question and ctx.has_any(["جذب", "استخدام"]):
        out.append(("hiring_business_growth_alignment", 75, "growth_alignment_gap"))
    if ctx.has_any(["سالخوردگی", "پیر شدن", "به سمت سالخوردگی"]):
        out.append(("workforce_aging_trend_analysis", 80, "aging_analysis_gap"))
    if ctx.has_any(["نیاز آموزشی", "دوره تخصصی", "کمبود تخصص"]):
        out.append(("education_training_need_analysis", 80, "training_need_gap"))
    if ctx.has_any(["ثبات سازمان", "ثبات شغلی", "ثبات نیروی انسانی"]):
        # High score overrides employment_type/contract routing that fires on the
        # same vocabulary ("رسمی/پیمانی").
        out.append(("employment_stability_impact_analysis", 200, "employment_stability_gap"))
    return out


def _rule_total_headcount(ctx: RuleContext) -> list[tuple[str, float, str]]:
    out: list[tuple[str, float, str]] = []
    if ctx.has_any(
        [
            "تعداد کل کارکنان",
            "کل کارکنان",
            "کل پرسنل",
            "چند نفر نیرو داریم",
            "تعداد پرسنل فعال",
        ]
    ):
        out.append(("total_employee_count", 60, "total_headcount_phrase"))
    return out


def _rule_gender(ctx: RuleContext) -> list[tuple[str, float, str]]:
    out: list[tuple[str, float, str]] = []
    f = ctx.f
    if f.get("explicit_gender"):
        if f.get("explicit_department"):
            out.append(("employee_count_by_department_gender", 88, "department_gender_2d"))
        elif f.get("asks_percentage") and not ctx.has_any(["زن و مرد", "تفکیک جنسیت"]):
            out.append(("gender_percentage", 65, "gender_percentage_phrase"))
        elif f.get("explicit_age") and f.get("age_filter"):
            # Boost to 65 (above age_filter=60) only when gender is the primary
            # dimension ("به تفکیک جنسیت", "زن و مرد") — not a single-gender filter
            # like "چند زن زیر ۳۰" where age_filter is the right intent.
            if ctx.has_any(["تفکیک جنسیت", "به تفکیک جنس", "زن و مرد"]):
                out.append(("employee_count_by_gender_age_filter", 65, "gender_age_filter_dim"))
            else:
                out.append(("employee_count_by_gender_age_filter", 55, "gender_age_filter"))
        else:
            out.append(("employee_count_by_gender", 45, "gender_distribution"))
    return out


def _rule_age_min_max(ctx: RuleContext) -> list[tuple[str, float, str]]:
    out: list[tuple[str, float, str]] = []
    # Combined "youngest AND oldest" wording — must win over the separate
    # max_age/min_age rules below, which would otherwise only answer half
    # of a question like "جوان‌ترین و مسن‌ترین کارکنان چند ساله‌اند؟".
    if ctx.has_any(
        [
            "جوان‌ترین و مسن‌ترین",
            "جوان ترین و مسن ترین",
            "مسن‌ترین و جوان‌ترین",
            "مسن ترین و جوان ترین",
            "حداقل و حداکثر سن",
            "حداکثر و حداقل سن",
            "کمترین و بیشترین سن",
            "بیشترین و کمترین سن",
        ]
    ):
        out.append(("age_min_max", 96, "age_min_max_combined"))
    return out


def _rule_age_central(ctx: RuleContext) -> list[tuple[str, float, str]]:
    out: list[tuple[str, float, str]] = []
    f = ctx.f
    if f.get("asks_median") and f.get("explicit_age"):
        out.append(("median_age", 92, "median_age"))
    elif f.get("asks_average") and f.get("explicit_age"):
        if f.get("explicit_department"):
            out.append(("avg_age_by_department", 85, "avg_age_by_department"))
        else:
            # Boost to beat contractor_share (75) when question asks avg age of contractors
            out.append(("average_age", 92, "average_age"))
    return out


def _rule_age_extremes(ctx: RuleContext) -> list[tuple[str, float, str]]:
    out: list[tuple[str, float, str]] = []
    f = ctx.f
    # "مسن‌ترین"/"پیرترین" (oldest) and "جوان‌ترین"/"کم‌سن‌ترین" (youngest) are
    # synonyms for asks_most/asks_least that are specific to age and were
    # previously only caught by weak catalog trigger/example-overlap scoring
    # (score ~7), making max_age/min_age fragile to small phrasing changes.
    # Recognizing them directly as a manual rule (score 75) makes routing
    # robust, matching the precision of every other rule in this method.
    _oldest_age_terms = ["مسن‌ترین", "مسن ترین", "پیرترین"]
    _youngest_age_terms = [
        "جوان‌ترین",
        "جوان ترین",
        "جوون‌ترین",
        "جوون ترین",
        "کم‌سن‌ترین",
        "کم سن ترین",
    ]
    # Domain/department-scoped questions (e.g. "پیرترین حوزه از نظر کارکنان
    # کدومه؟") ask which org unit has the oldest workforce — a different
    # intent (employee_count_by_age_filter) than the single global max/min
    # age value this rule answers, so they are excluded here.
    if (
        (f.get("asks_most") or ctx.has_any(_oldest_age_terms))
        and f.get("explicit_age")
        and not f.get("age_filter")
        and not f.get("explicit_service_domain")
        and not f.get("explicit_department")
    ):
        if ctx.has_any(["گروه سنی", "رنج سنی", "بازه سنی"]):
            out.append(("most_populated_age_group", 90, "most_age_group"))
        else:
            out.append(("max_age", 75, "max_age"))
    if (
        (f.get("asks_least") or ctx.has_any(_youngest_age_terms))
        and f.get("explicit_age")
        and not f.get("age_filter")
        and not f.get("explicit_service_domain")
        and not f.get("explicit_department")
    ):
        if ctx.has_any(["گروه سنی", "رنج سنی", "بازه سنی"]):
            out.append(("least_populated_age_group", 90, "least_age_group"))
        else:
            out.append(("min_age", 75, "min_age"))
    if f.get("asks_stddev") and f.get("explicit_age"):
        out.append(("stddev_age", 80, "stddev_age"))
    return out


def _rule_age_filter(ctx: RuleContext) -> list[tuple[str, float, str]]:
    out: list[tuple[str, float, str]] = []
    f = ctx.f
    if f.get("explicit_age") and f.get("age_filter"):
        if f.get("explicit_department"):
            out.append(("employee_count_by_age_filter_by_department", 85, "age_filter_by_dept"))
        elif (
            f.get("explicit_education")
            and not f.get("explicit_service_domain")
            and not f.get("explicit_service_years")
            and not ctx.has_any(["به تفکیک مدرک", "چه مدرکی", "به تفکیک تحصیل"])
        ):
            # age_filter + education without domain: age is the primary filter dimension.
            # Guard: education-as-grouping phrases or service_years context → education wins.
            out.append(("employee_count_by_age_filter", 80, "age_filter_with_education"))
        else:
            out.append(("employee_count_by_age_filter", 60, "age_filter"))

    # Age demographic vocabulary + extracted age_filter (no service_domain/employment_type):
    # demographic label ("مسن"/"جوان") makes age the primary dimension.
    # Guards: education-grouping phrases → education is the answer, age is just a filter.
    #         province without "under" direction → province is the primary dimension.
    if (
        f.get("explicit_age_demographic")
        and f.get("age_filter")
        and not f.get("explicit_service_domain")
        and not f.get("explicit_employment_type")
        and not ctx.has_any(["چه مدرکی", "به تفکیک مدرک", "به تفکیک تحصیل"])
        and not (f.get("explicit_province") and not f.get("explicit_age_lt"))
    ):
        out.append(("employee_count_by_age_filter", 80, "age_demographic_filter"))
    return out


def _rule_age_group_vocab(ctx: RuleContext) -> list[tuple[str, float, str]]:
    out: list[tuple[str, float, str]] = []
    f = ctx.f
    if f.get("explicit_age") and ctx.has_any(["گروه سنی", "کدام گروه سنی", "بازه سنی"]):
        if f.get("asks_most") or ctx.has_any(["پرتعداد", "پر تعداد", "پرنفر"]):
            out.append(("most_populated_age_group", 90, "most_age_group_vocab"))
        elif f.get("asks_least") or ctx.has_any(["کم‌نفر", "کم نفر", "از همه کمتر", "کمترین نیرو"]):
            out.append(("least_populated_age_group", 90, "least_age_group_vocab"))
        elif f.get("explicit_gender") and (
            ctx.has_any(["تفکیک جنسیت", "زن و مرد", "مرد و زن"])
            or (ctx.term_in_question("زن") and ctx.term_in_question("مرد"))
        ):
            # Both genders present → gender × age_group distribution (TPL_GENDER_BY_AGE_GROUP)
            out.append(("employee_count_by_gender_age_filter", 80, "gender_by_age_group_vocab"))
        else:
            out.append(("employee_count_by_age_group", 60, "age_group"))
    return out


def _rule_education(ctx: RuleContext) -> list[tuple[str, float, str]]:
    out: list[tuple[str, float, str]] = []
    f = ctx.f
    question = ctx.question
    if f.get("explicit_education"):
        if f.get("explicit_department"):
            out.append(("employee_count_by_department_education", 88, "department_education_2d"))
        elif f.get("explicit_service_domain"):
            out.append(
                ("education_distribution_by_service_domain", 82, "education_by_service_domain")
            )
        elif (
            f.get("asks_most")
            or ctx.has_any(
                ["بیشتر داریم", "بیشتره", "بیشتر دیده", "بیشتر چه مدرک", "بیشتر چه تحصیل"]
            )
            or ("بیشتر" in question and "چه مدرک" in question)
        ):
            out.append(("most_common_education", 70, "most_common_education"))
        elif (
            f.get("asks_least")
            or ctx.has_any(["کمتر داریم", "کمتره", "نادرترین", "کم‌تکرارترین", "کم تکرارترین"])
        ) and not f.get("age_filter"):
            out.append(("least_common_education", 70, "least_common_education"))
        elif (
            ctx.has_any(["نیاز پست", "مدرک لازم", "تحصیلات پایین"])
            or ("پایین تر" in question and ctx.has_any(["نیاز", "پست", "کارشناسی"]))
            or ("پست کارشناسی" in question and ctx.has_any(["ولی", "اما", "دیپلم", "پایین"]))
        ):
            out.append(("low_education_in_expert_roles", 60, "low_education_expert_roles"))
        else:
            # Boost over total_employee_count (60) triggered by "کل کارکنان" in phrasing
            out.append(("employee_count_by_education", 72, "education_distribution_or_filter"))
    return out


def _rule_employment_contract(ctx: RuleContext) -> list[tuple[str, float, str]]:
    out: list[tuple[str, float, str]] = []
    f = ctx.f
    if f.get("explicit_employment_type"):
        if f.get("explicit_department"):
            out.append(("employment_type_by_department", 85, "employment_type_by_dept"))
        elif f.get("asks_least"):
            out.append(("least_populated_employment_type", 90, "least_employment_type"))
        else:
            out.append(("employee_count_by_employment_type", 70, "employment_type"))
    if f.get("explicit_contract_type"):
        if (
            f.get("explicit_hiring")
            or f.get("asks_recent_year")
            or ctx.has_any(["هر سال", "بسته شده", "سالانه"])
        ):
            out.append(("hiring_by_contract_type_recent_year", 70, "recent_hiring_contract_type"))
        elif f.get("asks_least"):
            out.append(("least_populated_contract_type", 90, "least_contract_type"))
        else:
            out.append(("employee_count_by_contract_type", 70, "contract_type"))
    if ctx.has_any(["رسمی", "قراردادی", "پیمانی", "شاغل در پیمانکاری"]):
        if f.get("explicit_contract_type"):
            out.append(("employee_count_by_contract_type", 35, "contract_type_value"))
        else:
            out.append(("employee_count_by_employment_type", 35, "employment_type_value"))
    return out


def _rule_contractor(ctx: RuleContext) -> list[tuple[str, float, str]]:
    out: list[tuple[str, float, str]] = []
    f = ctx.f
    question = ctx.question
    if f.get("explicit_contractor"):
        if f.get("explicit_department") or ctx.has_any(
            ["در هر بخش", "در هر واحد", "به تفکیک بخش", "به تفکیک واحد", "به تفکیک دپارتمان"]
        ):
            out.append(("contractor_share_by_department", 84, "contractor_by_department"))
        elif f.get("explicit_service_domain") or "در هر حوزه" in question:
            out.append(("contractor_share_by_service_domain", 80, "contractor_by_service_domain"))
        else:
            out.append(("contractor_share", 75, "contractor_share"))
    return out


def _rule_specific_department(ctx: RuleContext) -> list[tuple[str, float, str]]:
    out: list[tuple[str, float, str]] = []
    f = ctx.f
    # A specific, named department/domain (e.g. "حوزه مدیر عامل", "حوزه
    # فناوری اطلاعات") asks for a single filtered count, not the full
    # breakdown-by-all-departments distribution.
    _wants_breakdown = ctx.has_any(["تفکیک", "به تفکیک"])
    _dept_kw_match = ctx.dept_keyword_filter()
    _domain_value_match = ctx.service_domain_value() if f.get("explicit_service_domain") else None
    if (
        _dept_kw_match
        and not _wants_breakdown
        and not f.get("explicit_gender")
        and not f.get("asks_gap_or_shortage")
    ):
        out.append(("employee_count_by_specific_department", 92, "specific_department_keyword"))
    elif (
        _domain_value_match
        and not _wants_breakdown
        and not f.get("explicit_gender")
        and not f.get("asks_gap_or_shortage")
    ):
        out.append(("employee_count_by_specific_department", 91, "specific_service_domain_value"))
    return out


def _rule_gender_share_department(ctx: RuleContext) -> list[tuple[str, float, str]]:
    out: list[tuple[str, float, str]] = []
    f = ctx.f
    question = ctx.question
    # Gender share/ratio per department — "سهم زنان در چه بخش‌هایی کمتر
    # است" wants the female ratio WITHIN each department (not the share of
    # all women across departments), sorted by direction of "کمتر"/"بیشتر".
    if (
        f.get("explicit_gender")
        and f.get("explicit_department")
        and f.get("asks_percentage")
        and not f.get("explicit_service_domain")
    ):
        if "کمتر" in question:
            out.append(("gender_share_by_department_lowest", 100, "gender_share_dept_lowest"))
        elif "بیشتر" in question:
            out.append(("gender_share_by_department_highest", 100, "gender_share_dept_highest"))
        else:
            out.append(("gender_share_by_department_lowest", 98, "gender_share_dept_default"))
    return out


def _rule_top_per_group(ctx: RuleContext) -> list[tuple[str, float, str]]:
    out: list[tuple[str, float, str]] = []
    f = ctx.f
    question = ctx.question
    # Largest department WITHIN each service domain — a within-group top-1
    # (ROW_NUMBER + PARTITION BY) that the plain distribution intents cannot
    # express. Requires both a department term and a service-domain term, a
    # per-domain scope ("هر حوزه"), and a "largest/most" qualifier.
    _top_per_group_terms = [
        "پرجمعیت‌ترین",
        "پرجمعیت ترین",
        "بزرگ‌ترین",
        "بزرگترین",
        "بیشترین",
        "پرتعدادترین",
        "پرنفرترین",
    ]
    if (
        f.get("explicit_service_domain")
        and f.get("explicit_department")
        and not f.get("asks_least")
        and not f.get("asks_gap_or_shortage")
        and not f.get("explicit_gender")
        and not f.get("explicit_contractor")
        and "هر حوزه" in question
        and ctx.has_any(_top_per_group_terms)
    ):
        out.append(("top_department_per_service_domain", 95, "top_dept_per_service_domain"))
    return out


def _rule_service_domain(ctx: RuleContext) -> list[tuple[str, float, str]]:
    out: list[tuple[str, float, str]] = []
    f = ctx.f
    if (
        f.get("explicit_service_domain")
        and not f.get("explicit_contractor")
        and not f.get("explicit_education")
    ):
        if f.get("asks_gap_or_shortage"):
            out.append(("headcount_gap_by_service_domain", 82, "headcount_gap_service_domain"))
        elif f.get("explicit_gender"):
            # Gender breakdown by service domain — boost to beat gender_percentage (65)
            out.append(("employee_count_by_service_domain", 85, "gender_by_service_domain"))
        elif f.get("asks_least"):
            # "least" must rank ascending to a single answer — the plain distribution
            # template is ORDER BY employee_count DESC, the wrong direction for "least".
            out.append(("least_populated_service_domain", 90, "least_service_domain"))
        else:
            out.append(("employee_count_by_service_domain", 60, "service_domain_distribution"))
    return out


def _rule_criticality_department(ctx: RuleContext) -> list[tuple[str, float, str]]:
    out: list[tuple[str, float, str]] = []
    f = ctx.f
    if f.get("explicit_criticality_level"):
        # criticality_level is a real column — takes priority over generic dept routing
        out.append(("employee_count_by_criticality_level", 90, "criticality_level_distribution"))
    elif f.get("explicit_department"):
        if f.get("asks_gap_or_shortage"):
            out.append(("headcount_gap_by_department", 75, "headcount_gap_department"))
        elif f.get("asks_least"):
            out.append(("least_populated_department", 90, "least_department"))
        else:
            out.append(("employee_count_by_department", 55, "department_distribution"))
    return out


def _rule_province(ctx: RuleContext) -> list[tuple[str, float, str]]:
    out: list[tuple[str, float, str]] = []
    f = ctx.f
    # Only add province distribution when not already covered by a service_domain or dept filter
    if f.get("explicit_province") and not f.get("explicit_service_domain"):
        out.append(("employee_count_by_province", 60, "province_distribution"))
    return out


def _rule_age_service_domain(ctx: RuleContext) -> list[tuple[str, float, str]]:
    out: list[tuple[str, float, str]] = []
    f = ctx.f
    # Age context (demographic label, numeric filter, or explicit_age) + service_domain:
    # the age dimension is the primary focus, service_domain is used for grouping.
    _age_ctx = (
        f.get("explicit_age_demographic")
        or (f.get("age_filter") and not f.get("explicit_service_years"))
        or (f.get("explicit_age") and not f.get("explicit_service_years"))
    )
    if (
        _age_ctx
        and f.get("explicit_service_domain")
        and not f.get("explicit_employment_type")
        and not f.get("explicit_education")
        and not f.get("explicit_contractor")
    ):
        out.append(("employee_count_by_age_filter", 80, "age_context_service_domain"))

    # "Under N" + province: young-worker filter wins over province grouping.
    if (
        f.get("explicit_age_lt")
        and f.get("explicit_province")
        and (f.get("age_filter") or f.get("explicit_age"))
        and not f.get("explicit_service_years")
        and not f.get("explicit_employment_type")
    ):
        out.append(("employee_count_by_age_filter", 75, "age_lt_province"))
    return out


def _rule_work_location(ctx: RuleContext) -> list[tuple[str, float, str]]:
    out: list[tuple[str, float, str]] = []
    if ctx.f.get("explicit_work_location"):
        out.append(("employee_count_by_work_location", 55, "work_location_distribution"))
    return out


def _rule_org_chart(ctx: RuleContext) -> list[tuple[str, float, str]]:
    out: list[tuple[str, float, str]] = []
    # Org chart alignment question → headcount gap vs approved chart.
    if ctx.has_any(["چارت سازمانی"]):
        out.append(("headcount_gap_by_department", 70, "org_chart_alignment"))
    return out


def _rule_org_level(ctx: RuleContext) -> list[tuple[str, float, str]]:
    out: list[tuple[str, float, str]] = []
    f = ctx.f
    question = ctx.question
    # Specific org sensitivity level (e.g. "سطح ۱") → filtered total count.
    if f.get("explicit_specific_org_level"):
        out.append(("total_employee_count", 65, "specific_org_level_filter"))

    # Org-level grouping dimension ("سطح سازمانی"/"سطح دپارتمان"/"سطح واحد"/...) maps to the
    # real department_level column. Skip when explicit_criticality_level already claimed
    # it above (criticality_level is a distinct column sharing the "سطح حساسیت" wording).
    if f.get("explicit_org_level") and not f.get("explicit_criticality_level"):
        if "کدوم" in question or f.get("asks_most") or f.get("asks_least"):
            out.append(("employee_count_by_department_level", 95, "org_level_ranking"))
        elif ctx.has_any(["به کل", "از کل", "نسبت", "درصد"]):
            out.append(("employee_count_by_department_level", 95, "org_level_ratio"))
        else:
            out.append(("employee_count_by_department_level", 95, "org_level_distribution"))
    return out


def _rule_job_position(ctx: RuleContext) -> list[tuple[str, float, str]]:
    out: list[tuple[str, float, str]] = []
    f = ctx.f
    question = ctx.question
    # Job position context (پست سازمانی, سطح پست, etc.) → grouped by position, not total count.
    if f.get("explicit_job_position") and not f.get("explicit_education"):
        is_ranking = "کدوم" in question or f.get("asks_most") or f.get("asks_least")
        if "سطح پست" in question:
            out.append(("employee_count_by_position_level", 65, "position_level_distribution"))
        elif is_ranking:
            out.append(("most_populated_position", 65, "job_position_ranking"))
        else:
            out.append(("employee_count_by_position", 60, "job_position_distribution"))
    return out


def _rule_hire_year_filter(ctx: RuleContext) -> list[tuple[str, float, str]]:
    out: list[tuple[str, float, str]] = []
    if ctx.f.get("hire_year_filter") is not None:
        out.append(("employee_count_by_hire_year", 85, "hire_year_exact_filter"))
    return out


def _rule_hiring(ctx: RuleContext) -> list[tuple[str, float, str]]:
    out: list[tuple[str, float, str]] = []
    f = ctx.f
    if f.get("explicit_hiring") and f.get("hire_year_filter") is None:
        if f.get("explicit_monthly"):
            out.append(("monthly_hiring_trend", 92, "monthly_hiring_data_gap"))
        elif f.get("asks_last_15_years"):
            out.append(("hiring_last_15_years", 85, "last_15_years_hiring"))
        elif f.get("asks_growth_rate"):
            out.append(("hiring_trend_yoy_growth", 92, "hiring_trend_yoy_growth"))
        elif f.get("asks_most") or f.get("asks_least"):
            out.append(("most_or_least_hiring_year", 75, "most_or_least_hiring_year"))
        elif f.get("explicit_contract_type") or f.get("asks_recent_year"):
            out.append(
                ("hiring_by_contract_type_recent_year", 70, "recent_hiring_by_contract_type")
            )
        else:
            out.append(("hiring_trend_annual", 70, "annual_hiring_trend"))
    return out


def _rule_service_years(ctx: RuleContext) -> list[tuple[str, float, str]]:
    out: list[tuple[str, float, str]] = []
    f = ctx.f
    if f.get("explicit_service_years"):
        if f.get("service_years_filter"):
            out.append(("employee_count_by_service_years_filter", 80, "service_years_range_filter"))
        elif f.get("asks_median"):
            out.append(("median_service_years", 92, "median_service_years"))
        elif f.get("asks_zero_service"):
            if f.get("explicit_service_domain") or f.get("explicit_department"):
                # "which domain has the most zero-service employees?" → rank by zero-service
                if f.get("asks_most") or f.get("asks_least"):
                    out.append(
                        ("employee_count_without_service_years", 85, "zero_service_most_by_domain")
                    )
                # else: service_domain/department intent handles the breakdown (rec-152 pattern)
            else:
                out.append(("employee_count_without_service_years", 80, "without_service_years"))
        elif f.get("asks_average") and not f.get("explicit_employment_type"):
            out.append(("average_service_years", 85, "average_service_years"))
        elif f.get("asks_most") or f.get("asks_least"):
            # "which domain has the most/least service years?" → average to rank
            out.append(("average_service_years", 80, "service_years_most_least"))
        elif f.get("explicit_gender"):
            # gender comparison on service years → average service years per group
            out.append(("average_service_years", 75, "service_years_gender_comparison"))
        elif (
            f.get("age_filter")
            and not f.get("explicit_age")
            and not f.get("explicit_age_demographic")
        ):
            # numeric filter extracted but age context absent → treat as service_years filter
            out.append(
                ("employee_count_by_service_years_filter", 85, "service_years_via_numeric_filter")
            )
        elif ctx.has_any(["توزیع سابقه", "توزیع سابقه خدمت", "تفکیک سابقه خدمت"]):
            # No bucketed service_years dimension exists in the MVP view — answering
            # with average_service_years would silently mismatch what was asked.
            out.append(
                ("service_years_distribution_analysis", 90, "service_years_distribution_gap")
            )
        else:
            out.append(("average_service_years", 25, "service_years_default"))
    return out


def _rule_marital(ctx: RuleContext) -> list[tuple[str, float, str]]:
    out: list[tuple[str, float, str]] = []
    if ctx.f.get("explicit_marital"):
        out.append(("employee_count_by_marital_status", 60, "marital_status"))
    return out


def _rule_general_gap(ctx: RuleContext) -> list[tuple[str, float, str]]:
    out: list[tuple[str, float, str]] = []
    f = ctx.f
    if f.get("asks_gap_or_shortage") and not f.get("explicit_department"):
        out.append(("headcount_gap_by_department", 35, "general_headcount_gap"))
    return out


def _rule_chart_gap(ctx: RuleContext) -> list[tuple[str, float, str]]:
    out: list[tuple[str, float, str]] = []
    f = ctx.f
    # High-confidence chart-based headcount gap phrases dominate catalog triggers.
    _chart_gap_phrases = [
        "چارت مصوب",
        "نسبت به چارت",
        "تکمیل چارت",
        "تحقق چارت",
        "پر شدن چارت",
        "چارتش",
        "چارتشون",
    ]
    if ctx.has_any(_chart_gap_phrases):
        if f.get("explicit_service_domain"):
            out.append(("headcount_gap_by_service_domain", 95, "chart_gap_service_domain"))
        else:
            out.append(("headcount_gap_by_department", 95, "chart_gap_department"))
    return out


def _rule_colloquial_age(ctx: RuleContext) -> list[tuple[str, float, str]]:
    out: list[tuple[str, float, str]] = []
    # Colloquial age comparison ("they are younger/older") → average_age.
    # Only verb/copula forms (ن suffix) to avoid matching filter adjectives
    # like "جوان‌تر از ۳۰ سال" or "کارکنان جوان‌تر".
    if ctx.has_any(["جوون ترن", "جوان ترن", "مسن ترن"]):
        out.append(("average_age", 80, "age_comparison_colloquial"))
    return out


def _rule_zero_service_colloquial(ctx: RuleContext) -> list[tuple[str, float, str]]:
    out: list[tuple[str, float, str]] = []
    f = ctx.f
    # Colloquial zero-service phrasing with copula "صفره" or negation "ندارن/ندارند".
    # Yield to service_domain/department context — those intents apply the zero-service filter.
    if (
        f.get("explicit_service_years")
        and ctx.has_any(["صفره", "ندارن", "ندارند", "ندارد", "بی سابقه"])
        and not f.get("service_years_filter")
        and not f.get("explicit_service_domain")
        and not f.get("explicit_department")
    ):
        out.append(("employee_count_without_service_years", 88, "zero_service_colloquial"))
    return out


def _rule_service_years_via_age(ctx: RuleContext) -> list[tuple[str, float, str]]:
    out: list[tuple[str, float, str]] = []
    f = ctx.f
    question = ctx.question
    # When explicit_service_years is set and an age-like numeric filter was extracted
    # but no service_years_filter was found, the numeric threshold is a seniority filter.
    # This handles "باسابقه (بالای ۲۰ سال)" where extractor sees age but context is seniority.
    if (
        f.get("explicit_service_years")
        and f.get("age_filter")
        and not f.get("service_years_filter")
    ):
        out.append(("employee_count_by_service_years_filter", 88, "service_years_via_age_filter"))

    # "تازه وارد" (newly joined) implies a very short service_years window → service_years_filter.
    if "تازه وارد" in question:
        out.append(("employee_count_by_service_years_filter", 85, "newly_joined_service_filter"))
    return out


def _rule_contractor_education(ctx: RuleContext) -> list[tuple[str, float, str]]:
    out: list[tuple[str, float, str]] = []
    f = ctx.f
    question = ctx.question
    # contractor + education + gender OR "به تفکیک" → education distribution, not contractor share.
    if (
        f.get("explicit_contractor")
        and f.get("explicit_education")
        and (f.get("explicit_gender") or "به تفکیک" in question)
    ):
        out.append(
            ("employee_count_by_education", 88, "contractor_education_by_gender_or_breakdown")
        )
    return out


def _rule_contractor_hiring(ctx: RuleContext) -> list[tuple[str, float, str]]:
    out: list[tuple[str, float, str]] = []
    f = ctx.f
    # contractor + explicit hiring context → prefer hiring intents over contractor_share.
    # Exception: "سهم/نسبت/درصد" phrases ask for contractor SHARE of hiring → keep contractor_share.
    _is_share_query = ctx.has_any(["سهم", "نسبت", "درصد"])
    if f.get("explicit_contractor") and f.get("explicit_hiring") and not _is_share_query:
        if f.get("asks_last_15_years"):
            out.append(("hiring_last_15_years", 90, "contractor_hiring_last_15"))
        elif f.get("asks_most") or f.get("asks_least"):
            out.append(("most_or_least_hiring_year", 90, "contractor_most_least_hiring_year"))
        elif f.get("explicit_monthly"):
            out.append(("monthly_hiring_trend", 88, "contractor_monthly_hiring"))
        else:
            out.append(("hiring_trend_annual", 88, "contractor_annual_hiring_trend"))
    return out


def _rule_hiring_keyword(ctx: RuleContext) -> list[tuple[str, float, str]]:
    out: list[tuple[str, float, str]] = []
    f = ctx.f
    question = ctx.question
    _is_share_query = ctx.has_any(["سهم", "نسبت", "درصد"])
    # "استخدام" keyword in non-employment-type context → hiring intents.
    # Skip when contractor+share context: those are contractor_share questions, not hiring trends.
    if (
        "استخدام" in question
        and not f.get("explicit_employment_type")
        and not (f.get("explicit_contractor") and _is_share_query)
    ):
        if f.get("asks_most") or f.get("asks_least"):
            out.append(("most_or_least_hiring_year", 75, "hiring_year_from_استخدام"))
        elif f.get("asks_last_15_years"):
            out.append(("hiring_last_15_years", 80, "last15_from_استخدام"))
        elif ctx.has_any(["هر سال", "سالانه", "روند"]):
            out.append(("hiring_trend_annual", 75, "trend_from_استخدام"))
        elif f.get("asks_recent_year") or "امسال" in question:
            out.append(("hiring_by_contract_type_recent_year", 72, "recent_year_from_استخدام"))
    return out


# Ordered exactly as the legacy _manual_intent_rules emitted its rules.
MANUAL_INTENT_RULES: tuple[Rule, ...] = (
    _rule_individual,
    _rule_contract_dates,
    _rule_birth_hire_month,
    _rule_city,
    _rule_public_recruitment,
    _rule_terminated_retirement,
    _rule_analytical_gaps,
    _rule_total_headcount,
    _rule_gender,
    _rule_age_min_max,
    _rule_age_central,
    _rule_age_extremes,
    _rule_age_filter,
    _rule_age_group_vocab,
    _rule_education,
    _rule_employment_contract,
    _rule_contractor,
    _rule_specific_department,
    _rule_gender_share_department,
    _rule_top_per_group,
    _rule_service_domain,
    _rule_criticality_department,
    _rule_province,
    _rule_age_service_domain,
    _rule_work_location,
    _rule_org_chart,
    _rule_org_level,
    _rule_job_position,
    _rule_hire_year_filter,
    _rule_hiring,
    _rule_service_years,
    _rule_marital,
    _rule_general_gap,
    _rule_chart_gap,
    _rule_colloquial_age,
    _rule_zero_service_colloquial,
    _rule_service_years_via_age,
    _rule_contractor_education,
    _rule_contractor_hiring,
    _rule_hiring_keyword,
)


def evaluate(ctx: RuleContext) -> list[tuple[str, float, str]]:
    """Run every manual rule in order and concatenate their contributions."""
    rules: list[tuple[str, float, str]] = []
    for rule in MANUAL_INTENT_RULES:
        rules.extend(rule(ctx))
    return rules
