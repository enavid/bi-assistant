from __future__ import annotations

from app.use_cases.hr_analytics.steps.domain_classifier import DomainClassifier
from app.use_cases.hr_analytics.steps.question_validator import QuestionValidator

# ---------------------------------------------------------------------------
# DomainClassifier
# ---------------------------------------------------------------------------


def test_domain_classifier_accepts_hr_question(metadata_service):
    result = DomainClassifier().classify("تعداد کارکنان زن چند نفر است؟", metadata=metadata_service)
    assert result["is_hr"] is True
    assert result["domain"] == "HR"
    assert result["status"] == "OK"


def test_domain_classifier_rejects_non_hr_question(metadata_service):
    result = DomainClassifier().classify("قیمت دلار امروز چنده؟", metadata=metadata_service)
    assert result["is_hr"] is False
    assert result["route"] == "REJECT"
    assert result["status"] == "OUT_OF_SCOPE"


def test_domain_classifier_rejects_sales_question(metadata_service):
    result = DomainClassifier().classify(
        "میزان فروش ماه گذشته چقدر بود؟", metadata=metadata_service
    )
    assert result["is_hr"] is False
    assert result["route"] == "REJECT"


def test_domain_classifier_handles_empty_question(metadata_service):
    result = DomainClassifier().classify("", metadata=metadata_service)
    assert result["route"] in {"REJECT", "NEEDS_CLARIFICATION"}
    assert "status" in result


def test_domain_classifier_result_has_required_fields(metadata_service):
    result = DomainClassifier().classify("تعداد کارکنان زن چند نفر است؟", metadata=metadata_service)
    for field in ("is_hr", "domain", "status", "route"):
        assert field in result, f"Missing field: {field}"


# ---------------------------------------------------------------------------
# QuestionValidator
# ---------------------------------------------------------------------------


def test_question_validator_blocks_personal_data(metadata_service):
    result = QuestionValidator().validate("نام و کد ملی کارکنان را بده", metadata=metadata_service)
    assert result["is_valid"] is False
    assert result["route"] == "REJECT"
    assert result["status"] == "ACCESS_DENIED"


def test_question_validator_marks_city_as_data_gap(metadata_service):
    result = QuestionValidator().validate(
        "تعداد کارکنان شهر تهران چند نفر است؟", metadata=metadata_service
    )
    assert result["is_valid"] is False
    assert result["route"] == "GAP"
    assert result["status"] == "DATA_GAP"


def test_question_validator_accepts_valid_hr_question(metadata_service):
    result = QuestionValidator().validate(
        "تعداد کل کارکنان چند نفر است؟", metadata=metadata_service
    )
    assert result["is_valid"] is True
    assert result.get("route") in {"SQL", "GAP", "NEEDS_CLARIFICATION", None}


def test_question_validator_blocks_phone_number_request(metadata_service):
    result = QuestionValidator().validate(
        "شماره تماس کارکنان واحد فروش را بده", metadata=metadata_service
    )
    assert result["is_valid"] is False
    assert result["status"] in {"ACCESS_DENIED", "DATA_GAP", "SQL_VALIDATION_FAILED"}


def test_question_validator_result_has_required_fields(metadata_service):
    result = QuestionValidator().validate("تعداد کارکنان چند نفر است؟", metadata=metadata_service)
    for field in ("is_valid", "status", "route"):
        assert field in result, f"Missing field: {field}"
