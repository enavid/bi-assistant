"""Tests for Phase 2.3: Template Engine must raise a hard error when a critical
filter parameter is passed but the template does not use it.

TDD: these tests must fail before implementation and pass after.
"""

from __future__ import annotations

from app.hr_analytics.use_cases.sql.template_engine import SQLTemplateEngine

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

_ENGINE = SQLTemplateEngine(metadata_service=None)

_SIMPLE_TEMPLATE = {
    "template_id": "TPL_TEST",
    "sql": "SELECT COUNT(*) FROM employees WHERE {some_param} = 1",
    "parameters": [
        {"name": "some_param", "required": True, "type": "integer"},
    ],
}

_SIMPLE_PARAMS = {"some_param": 1, "current_shamsi_year": 1404}


def _call(template: dict, params: dict) -> tuple[list[str], list[str]]:
    errors, warnings, _ = _ENGINE._validate_template_params(None, template, dict(params))
    return errors, warnings


# ---------------------------------------------------------------------------
# Non-critical unused params still produce warnings (existing behaviour)
# ---------------------------------------------------------------------------


def test_non_critical_unused_param_produces_warning():
    params = {**_SIMPLE_PARAMS, "unknown_extra": "x"}
    errors, warnings = _call(_SIMPLE_TEMPLATE, params)
    assert errors == []
    assert any("unknown_extra" in w for w in warnings)


def test_no_unused_params_no_errors_no_warnings():
    errors, warnings = _call(_SIMPLE_TEMPLATE, _SIMPLE_PARAMS)
    assert errors == []
    assert all("Unused" not in w for w in warnings)


# ---------------------------------------------------------------------------
# Critical params that are passed but not in the template SQL → ERRORS
# ---------------------------------------------------------------------------


def test_critical_gender_value_unused_produces_error():
    params = {**_SIMPLE_PARAMS, "gender_value": "زن"}
    errors, warnings = _call(_SIMPLE_TEMPLATE, params)
    assert any("gender_value" in e for e in errors), f"errors={errors}"
    assert not any("gender_value" in w for w in warnings)


def test_critical_education_title_unused_produces_error():
    params = {**_SIMPLE_PARAMS, "education_title": "لیسانس"}
    errors, warnings = _call(_SIMPLE_TEMPLATE, params)
    assert any("education_title" in e for e in errors), f"errors={errors}"


def test_critical_service_years_min_unused_produces_error():
    params = {**_SIMPLE_PARAMS, "service_years_min": 5}
    errors, warnings = _call(_SIMPLE_TEMPLATE, params)
    assert any("service_years_min" in e for e in errors), f"errors={errors}"


def test_critical_service_years_max_inclusive_unused_produces_error():
    params = {**_SIMPLE_PARAMS, "service_years_max_inclusive": 10}
    errors, warnings = _call(_SIMPLE_TEMPLATE, params)
    assert any("service_years_max_inclusive" in e for e in errors), f"errors={errors}"


def test_critical_service_years_max_exclusive_unused_produces_error():
    params = {**_SIMPLE_PARAMS, "service_years_max_exclusive": 10}
    errors, warnings = _call(_SIMPLE_TEMPLATE, params)
    assert any("service_years_max_exclusive" in e for e in errors), f"errors={errors}"


def test_critical_hire_year_unused_produces_error():
    params = {**_SIMPLE_PARAMS, "hire_year": 1400}
    errors, warnings = _call(_SIMPLE_TEMPLATE, params)
    assert any("hire_year" in e for e in errors), f"errors={errors}"


def test_critical_employment_type_unused_produces_error():
    params = {**_SIMPLE_PARAMS, "employment_type": "رسمی"}
    errors, warnings = _call(_SIMPLE_TEMPLATE, params)
    assert any("employment_type" in e for e in errors), f"errors={errors}"


def test_critical_contract_type_unused_produces_error():
    params = {**_SIMPLE_PARAMS, "contract_type": "دائم"}
    errors, warnings = _call(_SIMPLE_TEMPLATE, params)
    assert any("contract_type" in e for e in errors), f"errors={errors}"


# ---------------------------------------------------------------------------
# Critical param IS used → no error
# ---------------------------------------------------------------------------


def test_critical_gender_value_used_in_template_no_error():
    template = {
        "template_id": "TPL_GENDER",
        "sql": "SELECT COUNT(*) FROM employees WHERE gender = {gender_value}",
        "parameters": [{"name": "gender_value", "required": True, "type": "string"}],
    }
    params = {"gender_value": "زن", "current_shamsi_year": 1404}
    errors, warnings = _call(template, params)
    assert not any("gender_value" in e for e in errors)


def test_critical_hire_year_used_in_template_no_error():
    template = {
        "template_id": "TPL_HIRE",
        "sql": "SELECT COUNT(*) FROM employees WHERE hire_year = {hire_year}",
        "parameters": [{"name": "hire_year", "required": True, "type": "integer"}],
    }
    params = {"hire_year": 1400, "current_shamsi_year": 1404}
    errors, warnings = _call(template, params)
    assert not any("hire_year" in e for e in errors)


# ---------------------------------------------------------------------------
# Multiple critical params unused → all appear in errors
# ---------------------------------------------------------------------------


def test_multiple_critical_unused_all_reported():
    params = {
        **_SIMPLE_PARAMS,
        "gender_value": "زن",
        "hire_year": 1400,
        "employment_type": "رسمی",
    }
    errors, warnings = _call(_SIMPLE_TEMPLATE, params)
    error_text = " ".join(errors)
    assert "gender_value" in error_text
    assert "hire_year" in error_text
    assert "employment_type" in error_text


# ---------------------------------------------------------------------------
# Mixed: one critical + one non-critical unused → error + warning
# ---------------------------------------------------------------------------


def test_critical_and_non_critical_both_handled():
    params = {**_SIMPLE_PARAMS, "gender_value": "زن", "misc_extra": "x"}
    errors, warnings = _call(_SIMPLE_TEMPLATE, params)
    assert any("gender_value" in e for e in errors)
    assert any("misc_extra" in w for w in warnings)


# ---------------------------------------------------------------------------
# Integration: build() returns PARAMETER_VALIDATION_FAILED for critical unused
# ---------------------------------------------------------------------------


def test_build_returns_parameter_validation_failed_for_critical_unused(metadata_service):
    """gender_value passed but the template TPL_TOTAL_EMPLOYEE_COUNT has no {gender_value}."""
    context = {
        "route_result": {"route": "SQL", "template_id": "TPL_TOTAL_EMPLOYEE_COUNT"},
        "intent_result": {
            "intent_id": "total_employee_count",
            "template_id": "TPL_TOTAL_EMPLOYEE_COUNT",
            "filters": [
                {"column": "gender", "operator": "=", "value": "زن"},
            ],
        },
    }
    result = SQLTemplateEngine(metadata_service=metadata_service).build(
        question="تعداد کل زنان چند نفر است؟",
        context=context,
        metadata=metadata_service,
    )
    assert result["status"] == "PARAMETER_VALIDATION_FAILED", (
        f"Expected PARAMETER_VALIDATION_FAILED but got status={result['status']!r}\n"
        f"errors={result.get('errors')}\nwarnings={result.get('warnings')}"
    )
    assert any("gender_value" in str(e) for e in result.get("errors", []))
