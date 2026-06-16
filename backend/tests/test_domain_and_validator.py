from __future__ import annotations

from app.hr_analytics.use_cases.steps.domain_classifier import DomainClassifier
from app.hr_analytics.use_cases.steps.question_validator import QuestionValidator

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


# ---------------------------------------------------------------------------
# Knowledge GAP rules
# ---------------------------------------------------------------------------


def test_validator_knowledge_gap_definition_peymani(metadata_service):
    result = QuestionValidator().validate("تعریف نیروی پیمانی چیست؟", metadata=metadata_service)
    assert result["route"] == "GAP"
    assert result["status"] == "KNOWLEDGE_GAP"


def test_validator_knowledge_gap_definition_peymankari(metadata_service):
    result = QuestionValidator().validate("تعریف نیروی پیمانکاری چیست؟", metadata=metadata_service)
    assert result["route"] == "GAP"
    assert result["status"] == "KNOWLEDGE_GAP"


def test_validator_knowledge_gap_difference_estekhdam_gharardad(metadata_service):
    result = QuestionValidator().validate(
        "تفاوت نوع استخدام و نوع قرارداد چیست؟", metadata=metadata_service
    )
    assert result["route"] == "GAP"
    assert result["status"] == "KNOWLEDGE_GAP"


def test_validator_knowledge_gap_methodology_average_age(metadata_service):
    result = QuestionValidator().validate(
        "شاخص میانگین سن چگونه محاسبه می‌شود؟", metadata=metadata_service
    )
    assert result["route"] == "GAP"
    assert result["status"] == "KNOWLEDGE_GAP"


def test_validator_knowledge_gap_methodology_contractor_share(metadata_service):
    result = QuestionValidator().validate(
        "شاخص سهم پیمانکاری چگونه محاسبه می‌شود؟", metadata=metadata_service
    )
    assert result["route"] == "GAP"
    assert result["status"] == "KNOWLEDGE_GAP"


def test_validator_knowledge_gap_definition_chart_mosavab(metadata_service):
    result = QuestionValidator().validate(
        "تعریف چارت مصوب در منابع انسانی چیست؟", metadata=metadata_service
    )
    assert result["route"] == "GAP"
    assert result["status"] == "KNOWLEDGE_GAP"


def test_validator_knowledge_gap_meaning_data_gap(metadata_service):
    result = QuestionValidator().validate(
        "منظور از Data Gap در این سامانه چیست؟", metadata=metadata_service
    )
    assert result["route"] == "GAP"
    assert result["status"] == "KNOWLEDGE_GAP"


def test_validator_knowledge_gap_retirement_policy(metadata_service):
    result = QuestionValidator().validate(
        "سیاست سازمان درباره بازنشستگی چیست؟", metadata=metadata_service
    )
    assert result["route"] == "GAP"
    assert result["status"] == "KNOWLEDGE_GAP"


def test_validator_knowledge_gap_retirement_law(metadata_service):
    result = QuestionValidator().validate(
        "قانون رسمی سن بازنشستگی در این تحلیل چیست؟", metadata=metadata_service
    )
    assert result["route"] == "GAP"
    assert result["status"] == "KNOWLEDGE_GAP"


def test_validator_knowledge_gap_active_employee_definition(metadata_service):
    result = QuestionValidator().validate(
        "تعریف کارکنان فعال در این سامانه چیست؟", metadata=metadata_service
    )
    assert result["route"] == "GAP"
    assert result["status"] == "KNOWLEDGE_GAP"


# ---------------------------------------------------------------------------
# Analytical GAP rules
# ---------------------------------------------------------------------------


def test_validator_analytical_gap_risk_female_age(metadata_service):
    result = QuestionValidator().validate(
        "میانگین سن کارکنان زن چه ریسکی برای سازمان دارد؟", metadata=metadata_service
    )
    assert result["route"] == "GAP"
    assert result["status"] == "ANALYTICAL_GAP"


def test_validator_analytical_gap_risk_contractor_share(metadata_service):
    result = QuestionValidator().validate(
        "سهم کارکنان پیمانکاری چه ریسکی برای سازمان ایجاد می‌کند؟", metadata=metadata_service
    )
    assert result["route"] == "GAP"
    assert result["status"] == "ANALYTICAL_GAP"


def test_validator_analytical_gap_management_judgment(metadata_service):
    result = QuestionValidator().validate(
        "کدام حوزه از نظر ترکیب سن و تحصیلات نیازمند توجه مدیریتی است؟",
        metadata=metadata_service,
    )
    assert result["route"] == "GAP"
    assert result["status"] == "ANALYTICAL_GAP"


# ---------------------------------------------------------------------------
# Data GAP rules
# ---------------------------------------------------------------------------


def test_validator_data_gap_job_family(metadata_service):
    result = QuestionValidator().validate(
        "تعداد کارکنان به تفکیک خانواده شغلی چقدر است؟", metadata=metadata_service
    )
    assert result["route"] == "GAP"
    assert result["status"] == "DATA_GAP"


def test_validator_data_gap_job_family_top(metadata_service):
    result = QuestionValidator().validate(
        "کدام خانواده شغلی بیشترین تعداد کارکنان را دارد؟", metadata=metadata_service
    )
    assert result["route"] == "GAP"
    assert result["status"] == "DATA_GAP"


# ---------------------------------------------------------------------------
# False-positive fix: "نامتوازن" should not trigger QVAL_GAP_ADVANCED_BALANCE
# ---------------------------------------------------------------------------


def test_validator_gender_age_imbalance_routes_to_sql(metadata_service):
    result = QuestionValidator().validate(
        "آیا توزیع جنسیتی در برخی گروه‌های سنی نامتوازن است؟", metadata=metadata_service
    )
    assert result.get("route") in {None, "SQL"}


def test_validator_access_denied_personal_employee_data(metadata_service):
    result = QuestionValidator().validate(
        "اطلاعات فردی کارکنان قراردادی را نمایش بده.", metadata=metadata_service
    )
    assert result["route"] == "REJECT"
    assert result["status"] == "ACCESS_DENIED"


# ---------------------------------------------------------------------------
# Near-retirement data queries should pass through to SQL (not be caught as GAP)
# ---------------------------------------------------------------------------


def test_validator_near_retirement_count_passes_through(metadata_service):
    result = QuestionValidator().validate(
        "چند نفر در آستانه بازنشستگی هستند؟", metadata=metadata_service
    )
    assert result.get("route") in {None, "SQL"}


def test_validator_near_retirement_by_domain_passes_through(metadata_service):
    result = QuestionValidator().validate(
        "کارکنان در آستانه بازنشستگی به تفکیک حوزه چند نفر هستند؟", metadata=metadata_service
    )
    assert result.get("route") in {None, "SQL"}


def test_validator_near_retirement_headcount_passes_through(metadata_service):
    result = QuestionValidator().validate(
        "آیا نیروی انسانی در آستانه بازنشستگی زیاد است؟", metadata=metadata_service
    )
    assert result.get("route") in {None, "SQL"}


# ---------------------------------------------------------------------------
# Aging structure and training need should be ANALYTICAL_GAP (not DATA_GAP)
# ---------------------------------------------------------------------------


def test_validator_aging_structure_is_analytical_gap(metadata_service):
    result = QuestionValidator().validate(
        "آیا ساختار کلی کارکنان به سمت سالخوردگی در حال حرکت است؟", metadata=metadata_service
    )
    assert result["route"] == "GAP"
    assert result["status"] == "ANALYTICAL_GAP"


def test_validator_training_need_is_analytical_gap(metadata_service):
    result = QuestionValidator().validate(
        "آیا ترکیب تحصیلات کارکنان نشان‌دهنده نیاز آموزشی است؟", metadata=metadata_service
    )
    assert result["route"] == "GAP"
    assert result["status"] == "ANALYTICAL_GAP"


# ---------------------------------------------------------------------------
# Headcount balance questions should pass through to SQL (not be caught as GAP)
# ---------------------------------------------------------------------------


def test_validator_headcount_gap_chart_vs_actual_passes_through(metadata_service):
    result = QuestionValidator().validate(
        "آیا تعادل بین چارت سازمانی و واقعیت نیروی انسانی برقرار است؟", metadata=metadata_service
    )
    assert result.get("route") in {None, "SQL"}


def test_validator_headcount_distribution_passes_through(metadata_service):
    result = QuestionValidator().validate(
        "آیا توزیع نیروی انسانی بین حوزه‌ها متوازن است؟", metadata=metadata_service
    )
    assert result.get("route") in {None, "SQL"}
