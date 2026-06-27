"""Per-intent structured-payload builders (Phase 3.1, target B).

Extracted from the ``IntentParser._extract_structured_payload`` God method. The
huge ``if/elif best_intent_id == ...`` chain is now a registry of small builder
functions, each mutating a shared :class:`PayloadState`. ``PAYLOAD_BUILDERS``
maps an intent id to its builder; ``build_payload`` dispatches exactly one (or
none), reproducing the original elif semantics. The dimension-extraction setup
and the cross-intent post-processing (superlative limit, default active filter,
metrics, output type, visualization) stay in the calling method.

Behavior is locked by tests/test_intent_parser_parity.py. The module imports
nothing from intent_parser; every parser/helper call goes through
:class:`PayloadContext`.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any

JsonDict = dict[str, Any]
Builder = Callable[["PayloadContext", "PayloadState"], None]


@dataclass
class PayloadState:
    """Mutable accumulator shared by the dimension setup and the builders."""

    filters: list[JsonDict] = field(default_factory=list)
    group_by: list[str] = field(default_factory=list)
    order_by: list[str] = field(default_factory=list)
    params: JsonDict = field(default_factory=dict)
    required_columns: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)


@dataclass
class PayloadContext:
    """Read-only inputs + helper delegates for the payload builders."""

    parser: Any  # IntentParser
    question: str
    service: Any
    query_features: JsonDict
    current_shamsi_year: int
    intent: JsonDict
    best_intent_id: str
    gender_value: str | None
    education_value: str | None
    employment_value: str | None
    contract_value: str | None
    age_filter: JsonDict | None
    month_range_fn: Callable[[str], tuple[int, int] | None]

    # --- helper delegates (kept here so builders never touch parser privates) ---
    def ensure_group_by(self, group_by: list[str], column: str) -> list[str]:
        return self.parser._ensure_group_by(group_by, column)

    def age_filter_to_params(self, age_filter: JsonDict | None) -> JsonDict:
        return self.parser._age_filter_to_params(age_filter)

    def has_any(self, terms) -> bool:
        return self.parser._has_any(self.question, terms)

    def dept_keyword_filter(self):
        return self.parser._extract_department_keyword_filter(self.question)

    def service_domain_value(self):
        return self.parser._extract_service_domain_value(self.question, self.service)

    def province_value(self):
        return self.parser._extract_province_value(self.question)

    def service_years_filter_extract(self):
        return self.parser._extract_service_years_filter(self.question)

    def hire_year_extract(self):
        return self.parser._extract_hire_year(self.question)

    def shamsi_month_range(self):
        return self.month_range_fn(self.question)


def _b_gender_percentage(ctx: PayloadContext, st: PayloadState) -> None:
    question = ctx.question
    st.params["gender_value"] = ctx.gender_value or (
        "زن" if "زن" in question else "مرد" if "مرد" in question else None
    )
    if st.params["gender_value"]:
        st.filters.append({"column": "gender", "operator": "=", "value": st.params["gender_value"]})
        st.required_columns.extend(["gender", "employee_id", "is_active"])
    else:
        st.warnings.append(
            "gender_percentage requires gender_value; fallback clarification may be needed."
        )


def _b_employee_count_by_age_filter(ctx: PayloadContext, st: PayloadState) -> None:
    question = ctx.question
    age_params = ctx.age_filter_to_params(ctx.age_filter)
    st.params.update(age_params)
    if ctx.age_filter:
        st.filters.append(ctx.age_filter)
    if ctx.query_features.get("explicit_service_domain"):
        st.group_by = ctx.ensure_group_by(st.group_by, "service_domain")
        st.required_columns.extend(["service_domain"])
    # A bare employment-status value (رسمی/قراردادی/پیمانی) alongside an
    # age filter must not be silently dropped. Two such values present
    # ("بیشتر رسمین یا قراردادی") means a comparison — group by instead
    # of picking one as a filter.
    _status_terms = [t for t in ("رسمی", "قراردادی", "پیمانی") if t in question]
    if len(_status_terms) >= 2:
        st.group_by = ctx.ensure_group_by(st.group_by, "employment_type")
        st.required_columns.append("employment_type")
    elif ctx.employment_value:
        st.params["employment_type"] = ctx.employment_value
        st.filters.append(
            {"column": "employment_type", "operator": "=", "value": ctx.employment_value}
        )
        st.required_columns.append("employment_type")
    elif ctx.contract_value:
        st.params["contract_type"] = ctx.contract_value
        st.filters.append({"column": "contract_type", "operator": "=", "value": ctx.contract_value})
        st.required_columns.append("contract_type")
    st.required_columns.extend(["age", "employee_id", "is_active"])


def _b_employee_count_by_gender_age_filter(ctx: PayloadContext, st: PayloadState) -> None:
    if ctx.age_filter:
        st.filters.append(ctx.age_filter)
    st.group_by = ctx.ensure_group_by(st.group_by, "gender")
    st.required_columns.extend(["gender", "age", "employee_id", "is_active"])


def _b_employee_count_by_age_group(ctx: PayloadContext, st: PayloadState) -> None:
    st.group_by = ctx.ensure_group_by(st.group_by, "age_group_title")
    st.required_columns.extend(["age_group_title", "employee_id", "is_active"])


def _b_populated_age_group(ctx: PayloadContext, st: PayloadState) -> None:
    st.group_by = ctx.ensure_group_by(st.group_by, "age_group_title")
    st.required_columns.extend(["age_group_title", "employee_id", "is_active"])


def _b_average_age(ctx: PayloadContext, st: PayloadState) -> None:
    question = ctx.question
    if "زن و مرد" in question or "تفکیک جنسیت" in question:
        st.group_by = ["gender"]
    elif "هر حوزه" in question or "به تفکیک حوزه" in question:
        st.group_by = ["service_domain"]
    elif ctx.has_any(["هر دپارتمان", "هر بخش", "هر واحد", "هر اداره"]):
        st.group_by = ["department_name"]
    else:
        st.group_by = []
    # Secondary WHERE filters — kept separate from group_by dimensions
    if ctx.query_features.get("explicit_contractor"):
        st.filters.append({"column": "is_contractor", "operator": "=", "value": True})
        st.required_columns.append("is_contractor")
    if ctx.gender_value and "gender" not in st.group_by:
        st.filters.append({"column": "gender", "operator": "=", "value": ctx.gender_value})
        st.required_columns.append("gender")
    if ctx.education_value:
        st.filters.append(
            {"column": "education_title", "operator": "=", "value": ctx.education_value}
        )
        st.required_columns.append("education_title")
    st.required_columns.extend(["age", "employee_id", "is_active", *st.group_by])


def _b_age_scalar(ctx: PayloadContext, st: PayloadState) -> None:
    st.required_columns.extend(["age", "employee_id", "is_active"])


def _b_gender_share_by_department(ctx: PayloadContext, st: PayloadState) -> None:
    st.params["gender_value"] = ctx.gender_value or "زن"
    st.required_columns.extend(["department_name", "gender", "employee_id", "is_active"])


def _b_employee_count_by_specific_department(ctx: PayloadContext, st: PayloadState) -> None:
    # This is a single filtered total, never a breakdown — discard any
    # group_by the semantic mapper proposed for the bare "حوزه"/"بخش"
    # word (e.g. implicit_service_domain), or it leaks into coverage
    # checking and forces an incorrect grouped-fallback SQL.
    st.group_by = []
    dept_kw_match = ctx.dept_keyword_filter()
    if dept_kw_match:
        _, dept_values = dept_kw_match
        st.filters.append(
            {"column": "department_name", "operator": "IN", "value": list(dept_values)}
        )
    else:
        domain_value = ctx.service_domain_value()
        if domain_value:
            st.filters.append({"column": "service_domain", "operator": "=", "value": domain_value})
    st.required_columns.extend(["employee_id", "is_active"])


def _b_employee_count_by_education(ctx: PayloadContext, st: PayloadState) -> None:
    if ctx.education_value and not ctx.query_features.get("asks_percentage"):
        st.params["education_title"] = ctx.education_value
        st.filters.append(
            {"column": "education_title", "operator": "=", "value": ctx.education_value}
        )
    else:
        st.group_by = ctx.ensure_group_by(st.group_by, "education_title")
    st.required_columns.extend(["education_title", "employee_id", "is_active"])


def _b_common_education(ctx: PayloadContext, st: PayloadState) -> None:
    st.group_by = ["education_title"]
    st.order_by = [
        "employee_count DESC"
        if ctx.best_intent_id == "most_common_education"
        else "employee_count ASC"
    ]
    st.required_columns.extend(["education_title", "employee_id", "is_active"])


def _b_low_education_in_expert_roles(ctx: PayloadContext, st: PayloadState) -> None:
    st.filters.append(
        {"column": "education_rank", "operator": "<", "value_column": "min_education_rank"}
    )
    st.required_columns.extend(
        ["education_rank", "min_education_rank", "is_expert_role", "employee_id", "is_active"]
    )


def _b_employee_count_by_employment_type(ctx: PayloadContext, st: PayloadState) -> None:
    if ctx.employment_value:
        st.params["employment_type"] = ctx.employment_value
        st.filters.append(
            {"column": "employment_type", "operator": "=", "value": ctx.employment_value}
        )
    else:
        st.group_by = ctx.ensure_group_by(st.group_by, "employment_type")
    if ctx.gender_value and not ctx.employment_value:
        # "درصد زنان در هر نوع استخدام" — gender as a percentage dimension, not a filter
        st.filters.append({"column": "gender", "operator": "=", "value": ctx.gender_value})
        st.required_columns.append("gender")
    # An age filter alongside an explicit employment_type phrase
    # ("استخدام قراردادی زیر ۳۰ سال") must not be dropped just because
    # the employment_type phrase won the intent race.
    if ctx.age_filter and ctx.employment_value:
        age_params = ctx.age_filter_to_params(ctx.age_filter)
        st.params.update(age_params)
        st.filters.append(ctx.age_filter)
        st.required_columns.append("age")
    st.required_columns.extend(["employment_type", "employee_id", "is_active"])


def _b_employee_count_by_contract_type(ctx: PayloadContext, st: PayloadState) -> None:
    if ctx.contract_value:
        st.params["contract_type"] = ctx.contract_value
        st.filters.append({"column": "contract_type", "operator": "=", "value": ctx.contract_value})
    else:
        st.group_by = ctx.ensure_group_by(st.group_by, "contract_type")
    st.required_columns.extend(["contract_type", "employee_id", "is_active"])


def _b_least_populated_type(ctx: PayloadContext, st: PayloadState) -> None:
    st.required_columns.extend(["employee_id", "is_active"])


def _b_employee_count_by_criticality_level(ctx: PayloadContext, st: PayloadState) -> None:
    st.group_by = ctx.ensure_group_by(st.group_by, "criticality_level")
    st.required_columns.extend(["criticality_level", "employee_id", "is_active"])


def _b_employee_count_by_department_level(ctx: PayloadContext, st: PayloadState) -> None:
    st.group_by = ctx.ensure_group_by(st.group_by, "department_level")
    st.required_columns.extend(["department_level", "employee_id", "is_active"])


def _b_contract_ending_soon(ctx: PayloadContext, st: PayloadState) -> None:
    st.required_columns.extend(["contract_end_date", "employee_id", "is_active"])


def _b_contract_ending_trend_annual(ctx: PayloadContext, st: PayloadState) -> None:
    st.required_columns.extend(["contract_end_date", "employee_id", "is_active"])


def _b_hired_last_month(ctx: PayloadContext, st: PayloadState) -> None:
    st.required_columns.extend(["hire_date", "employee_id", "is_active"])


def _b_count_by_shamsi_month(ctx: PayloadContext, st: PayloadState) -> None:
    month_range = ctx.shamsi_month_range() or (1, 12)
    st.params["shamsi_month_min"], st.params["shamsi_month_max"] = month_range
    date_column = (
        "birth_date" if ctx.best_intent_id == "employee_count_by_birth_month" else "hire_date"
    )
    st.required_columns.extend([date_column, "employee_id", "is_active"])


def _b_contractor_share(ctx: PayloadContext, st: PayloadState) -> None:
    st.filters.append(
        {"column": "is_contractor", "operator": "=", "value": True, "scope": "numerator"}
    )
    st.required_columns.extend(["is_contractor", "employee_id", "is_active"])


def _b_contractor_share_by_service_domain(ctx: PayloadContext, st: PayloadState) -> None:
    st.filters.append(
        {"column": "is_contractor", "operator": "=", "value": True, "scope": "numerator"}
    )
    st.group_by = ctx.ensure_group_by(st.group_by, "service_domain")
    st.required_columns.extend(["is_contractor", "service_domain", "employee_id", "is_active"])


def _b_contractor_share_by_department(ctx: PayloadContext, st: PayloadState) -> None:
    st.filters.append(
        {"column": "is_contractor", "operator": "=", "value": True, "scope": "numerator"}
    )
    st.group_by = ctx.ensure_group_by(st.group_by, "department_name")
    st.required_columns.extend(["is_contractor", "department_name", "employee_id", "is_active"])


def _b_education_by_service_domain(ctx: PayloadContext, st: PayloadState) -> None:
    st.group_by = ["service_domain", "education_title"]
    st.required_columns.extend(
        ["service_domain", "education_title", "education_rank", "employee_id", "is_active"]
    )


def _b_employee_count_by_service_domain(ctx: PayloadContext, st: PayloadState) -> None:
    st.group_by = ctx.ensure_group_by(st.group_by, "service_domain")
    # Gender as WHERE filter (not group_by) so controlled_dynamic can inject it
    if ctx.gender_value:
        st.filters.append({"column": "gender", "operator": "=", "value": ctx.gender_value})
        st.required_columns.append("gender")
    elif ctx.query_features.get("explicit_gender"):
        # "ترکیب جنسیتی هر حوزه" — no specific gender value named, so this
        # is a composition/breakdown request, not a filter.
        st.group_by = ctx.ensure_group_by(st.group_by, "gender")
        st.required_columns.append("gender")
    # Employment/contract type as WHERE filters
    if ctx.employment_value:
        st.filters.append(
            {"column": "employment_type", "operator": "=", "value": ctx.employment_value}
        )
        st.required_columns.append("employment_type")
    elif ctx.contract_value:
        st.filters.append({"column": "contract_type", "operator": "=", "value": ctx.contract_value})
        st.required_columns.append("contract_type")
    if ctx.query_features.get("explicit_province"):
        province_val = ctx.province_value()
        if province_val:
            st.filters.append({"column": "province", "operator": "=", "value": province_val})
            st.required_columns.extend(["province"])
            st.group_by = [col for col in st.group_by if col != "province"]
    st.required_columns.extend(["service_domain", "employee_id", "is_active"])


def _b_employee_count_by_department(ctx: PayloadContext, st: PayloadState) -> None:
    st.group_by = ctx.ensure_group_by(st.group_by, "department_name")
    st.required_columns.extend(["department_name", "employee_id", "is_active"])


def _b_top_department_per_service_domain(ctx: PayloadContext, st: PayloadState) -> None:
    st.group_by = ["service_domain", "department_name"]
    st.required_columns.extend(["service_domain", "department_name", "employee_id", "is_active"])


def _b_employee_count_by_department_education(ctx: PayloadContext, st: PayloadState) -> None:
    st.group_by = ["department_name", "education_title"]
    st.required_columns.extend(["department_name", "education_title", "employee_id", "is_active"])


def _b_employee_count_by_department_gender(ctx: PayloadContext, st: PayloadState) -> None:
    st.group_by = ["department_name", "gender"]
    st.required_columns.extend(["department_name", "gender", "employee_id", "is_active"])


def _b_headcount_gap_by_department(ctx: PayloadContext, st: PayloadState) -> None:
    st.group_by = ["department_id", "department_name"]
    st.required_columns.extend(
        [
            "department_id",
            "department_name",
            "department_approved_headcount",
            "employee_id",
            "is_active",
        ]
    )


def _b_headcount_gap_by_service_domain(ctx: PayloadContext, st: PayloadState) -> None:
    st.group_by = ["service_domain"]
    st.required_columns.extend(
        [
            "department_id",
            "department_name",
            "service_domain",
            "department_approved_headcount",
            "employee_id",
            "is_active",
        ]
    )


def _b_monthly_hiring_trend(ctx: PayloadContext, st: PayloadState) -> None:
    st.required_columns.extend(["hire_date", "hire_year", "employee_id", "is_active"])


def _b_employee_count_by_province(ctx: PayloadContext, st: PayloadState) -> None:
    st.group_by = ctx.ensure_group_by(st.group_by, "province")
    st.required_columns.extend(["province", "employee_id", "is_active"])


def _b_employee_count_by_work_location(ctx: PayloadContext, st: PayloadState) -> None:
    st.group_by = ctx.ensure_group_by(st.group_by, "site_name")
    st.required_columns.extend(["site_name", "province", "employee_id", "is_active"])


def _b_hiring_trend_annual(ctx: PayloadContext, st: PayloadState) -> None:
    st.group_by = ["hire_year"]
    st.order_by = ["hire_year ASC"]
    st.required_columns.extend(["hire_year", "employee_id", "is_active"])


def _b_hiring_last_15_years(ctx: PayloadContext, st: PayloadState) -> None:
    st.params["current_shamsi_year"] = ctx.current_shamsi_year
    st.filters.append(
        {
            "column": "hire_year",
            "operator": ">=",
            "value_expression": f"{ctx.current_shamsi_year} - 15",
        }
    )
    st.group_by = ["hire_year"]
    st.order_by = ["hire_year ASC"]
    st.required_columns.extend(["hire_year", "employee_id", "is_active"])


def _b_most_or_least_hiring_year(ctx: PayloadContext, st: PayloadState) -> None:
    st.group_by = ["hire_year"]
    st.order_by = [
        "employee_count ASC" if ctx.query_features.get("asks_least") else "employee_count DESC"
    ]
    st.required_columns.extend(["hire_year", "employee_id", "is_active"])


def _b_hiring_by_contract_type_recent_year(ctx: PayloadContext, st: PayloadState) -> None:
    st.params["current_shamsi_year"] = ctx.current_shamsi_year
    st.filters.append({"column": "hire_year", "operator": "=", "value": ctx.current_shamsi_year})
    st.group_by = ["contract_type"]
    st.required_columns.extend(["contract_type", "hire_year", "employee_id", "is_active"])


def _b_service_years_scalar(ctx: PayloadContext, st: PayloadState) -> None:
    st.required_columns.extend(["service_years", "employee_id", "is_active"])


def _b_employee_count_without_service_years(ctx: PayloadContext, st: PayloadState) -> None:
    st.filters.append({"column": "service_years", "operator": "=", "value": 0})
    st.required_columns.extend(["service_years", "employee_id", "is_active"])


def _b_employee_count_by_service_years_filter(ctx: PayloadContext, st: PayloadState) -> None:
    sy_filter = ctx.query_features.get("service_years_filter") or ctx.service_years_filter_extract()
    if sy_filter:
        st.filters.append(sy_filter)
        op = sy_filter.get("operator", "")
        value = sy_filter.get("value")
        if op in {">=", ">"}:
            st.params["service_years_min"] = int(value)
        elif op == "<":
            st.params["service_years_max_exclusive"] = int(value)
        elif op == "<=":
            st.params["service_years_max_inclusive"] = int(value)
        elif op == "BETWEEN" and isinstance(value, list) and len(value) == 2:
            st.params["service_years_min"] = int(value[0])
            st.params["service_years_max_inclusive"] = int(value[1])
    st.required_columns.extend(["service_years", "employee_id", "is_active"])


def _b_employee_count_by_hire_year(ctx: PayloadContext, st: PayloadState) -> None:
    year = ctx.query_features.get("hire_year_filter") or ctx.hire_year_extract()
    if year is not None:
        st.filters.append({"column": "hire_year", "operator": "=", "value": year})
        st.params["hire_year"] = year
    st.required_columns.extend(["hire_year", "employee_id", "is_active"])


def _b_near_retirement_analysis(ctx: PayloadContext, st: PayloadState) -> None:
    if ctx.query_features.get("explicit_service_domain"):
        st.group_by = ctx.ensure_group_by(st.group_by, "service_domain")
        st.required_columns.extend(["service_domain"])
    if ctx.age_filter:
        st.filters.append(ctx.age_filter)
    st.required_columns.extend(["age", "service_years", "employee_id", "is_active"])


def _b_employee_count_by_marital_status(ctx: PayloadContext, st: PayloadState) -> None:
    st.group_by = ctx.ensure_group_by(st.group_by, "marital_status")
    if ctx.gender_value:
        st.filters.append({"column": "gender", "operator": "=", "value": ctx.gender_value})
        st.required_columns.append("gender")
    st.required_columns.extend(["marital_status", "employee_id", "is_active"])


PAYLOAD_BUILDERS: dict[str, Builder] = {
    "gender_percentage": _b_gender_percentage,
    "employee_count_by_age_filter": _b_employee_count_by_age_filter,
    "employee_count_by_gender_age_filter": _b_employee_count_by_gender_age_filter,
    "employee_count_by_age_group": _b_employee_count_by_age_group,
    "most_populated_age_group": _b_populated_age_group,
    "least_populated_age_group": _b_populated_age_group,
    "average_age": _b_average_age,
    "max_age": _b_age_scalar,
    "min_age": _b_age_scalar,
    "stddev_age": _b_age_scalar,
    "age_min_max": _b_age_scalar,
    "median_age": _b_age_scalar,
    "gender_share_by_department_lowest": _b_gender_share_by_department,
    "gender_share_by_department_highest": _b_gender_share_by_department,
    "employee_count_by_specific_department": _b_employee_count_by_specific_department,
    "employee_count_by_education": _b_employee_count_by_education,
    "most_common_education": _b_common_education,
    "least_common_education": _b_common_education,
    "low_education_in_expert_roles": _b_low_education_in_expert_roles,
    "employee_count_by_employment_type": _b_employee_count_by_employment_type,
    "employee_count_by_contract_type": _b_employee_count_by_contract_type,
    "least_populated_employment_type": _b_least_populated_type,
    "least_populated_contract_type": _b_least_populated_type,
    "employee_count_by_criticality_level": _b_employee_count_by_criticality_level,
    "employee_count_by_department_level": _b_employee_count_by_department_level,
    "employee_count_contract_ending_soon": _b_contract_ending_soon,
    "contract_ending_trend_annual": _b_contract_ending_trend_annual,
    "employee_count_hired_last_month": _b_hired_last_month,
    "employee_count_by_birth_month": _b_count_by_shamsi_month,
    "employee_count_by_hire_month": _b_count_by_shamsi_month,
    "contractor_share": _b_contractor_share,
    "contractor_share_by_service_domain": _b_contractor_share_by_service_domain,
    "contractor_share_by_department": _b_contractor_share_by_department,
    "education_distribution_by_service_domain": _b_education_by_service_domain,
    "education_by_service_domain": _b_education_by_service_domain,
    "employee_count_by_service_domain": _b_employee_count_by_service_domain,
    "employee_count_by_department": _b_employee_count_by_department,
    "top_department_per_service_domain": _b_top_department_per_service_domain,
    "employee_count_by_department_education": _b_employee_count_by_department_education,
    "employee_count_by_department_gender": _b_employee_count_by_department_gender,
    "headcount_gap_by_department": _b_headcount_gap_by_department,
    "headcount_gap_by_service_domain": _b_headcount_gap_by_service_domain,
    "monthly_hiring_trend": _b_monthly_hiring_trend,
    "employee_count_by_province": _b_employee_count_by_province,
    "employee_count_by_work_location": _b_employee_count_by_work_location,
    "hiring_trend_annual": _b_hiring_trend_annual,
    "hiring_trend_yoy_growth": _b_hiring_trend_annual,
    "hiring_last_15_years": _b_hiring_last_15_years,
    "most_or_least_hiring_year": _b_most_or_least_hiring_year,
    "hiring_by_contract_type_recent_year": _b_hiring_by_contract_type_recent_year,
    "average_service_years": _b_service_years_scalar,
    "median_service_years": _b_service_years_scalar,
    "employee_count_without_service_years": _b_employee_count_without_service_years,
    "employee_count_by_service_years_filter": _b_employee_count_by_service_years_filter,
    "employee_count_by_hire_year": _b_employee_count_by_hire_year,
    "near_retirement_analysis": _b_near_retirement_analysis,
    "employee_count_by_marital_status": _b_employee_count_by_marital_status,
}


def build_payload(ctx: PayloadContext, state: PayloadState) -> None:
    """Dispatch to the builder for ``ctx.best_intent_id`` (no-op if none)."""
    builder = PAYLOAD_BUILDERS.get(ctx.best_intent_id)
    if builder is not None:
        builder(ctx, state)
