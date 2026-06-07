from __future__ import annotations

from app.services.hr_bi.domain_classifier import DomainClassifier
from app.services.hr_bi.question_validator import QuestionValidator


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


def test_question_validator_blocks_personal_data(metadata_service):
    result = QuestionValidator().validate("نام و کد ملی کارکنان را بده", metadata=metadata_service)
    assert result["is_valid"] is False
    assert result["route"] == "REJECT"
    assert result["status"] == "ACCESS_DENIED"


def test_question_validator_marks_city_as_data_gap(metadata_service):
    result = QuestionValidator().validate("تعداد کارکنان شهر تهران چند نفر است؟", metadata=metadata_service)
    assert result["is_valid"] is False
    assert result["route"] == "GAP"
    assert result["status"] == "DATA_GAP"
