from __future__ import annotations

from app.infrastructure.metadata.service import get_metadata_service


def test_metadata_service_health_ok(metadata_service):
    health = metadata_service.health_check().to_dict()
    assert health["ok"] is True
    assert health["errors"] == []


def test_metadata_service_main_view(metadata_service):
    view = metadata_service.get_main_view()
    assert view.get("name") == "hr_mvp.vw_hr_employee_analytics"


def test_metadata_service_columns_non_empty(metadata_service):
    columns = metadata_service.get_columns()
    assert len(columns) > 0
    assert all("name" in col for col in columns)


def test_metadata_service_sql_template_total_count(metadata_service):
    tpl = metadata_service.get_sql_template("TPL_TOTAL_EMPLOYEE_COUNT")
    assert tpl is not None
    sql = tpl.get("sql", "")
    assert "hr_mvp.vw_hr_employee_analytics" in sql
    assert "COUNT" in sql


def test_metadata_service_status_sql_data_gap(metadata_service):
    sql = metadata_service.get_status_sql("DATA_GAP")
    assert sql == "SELECT 'DATA_GAP' AS status;"


def test_metadata_service_get_intent_exists(metadata_service):
    intents = metadata_service.list_intents()
    assert len(intents) > 0
    first_id = intents[0]["intent_id"]
    fetched = metadata_service.get_intent(first_id)
    assert fetched is not None
    assert fetched["intent_id"] == first_id


def test_metadata_service_sensitive_columns_non_empty(metadata_service):
    sensitive = metadata_service.get_sensitive_columns()
    assert "national_id" in sensitive or "personnel_number" in sensitive


def test_metadata_service_schema_context_for_prompt(metadata_service):
    context = metadata_service.build_schema_context_for_prompt()
    assert "hr_mvp.vw_hr_employee_analytics" in context
    assert "employee_id" in context


def test_metadata_service_reload_returns_bundle(metadata_service):
    bundle = metadata_service.reload()
    assert bundle is not None
    assert bundle.data_dictionary


def test_get_metadata_service_singleton():
    from pathlib import Path

    metadata_dir = Path(__file__).resolve().parents[1] / "metadata"
    s1 = get_metadata_service(reload=True, metadata_dir=metadata_dir, strict=True)
    s2 = get_metadata_service(strict=True)
    assert s1 is s2


# ---------------------------------------------------------------------------
# Phase 4.3 — Smart Schema (focused column_names parameter)
# ---------------------------------------------------------------------------


def test_schema_context_with_column_names_shorter_than_full(metadata_service):
    """Focused schema with a small column list must be shorter than the full schema."""
    full = metadata_service.build_schema_context_for_prompt()
    focused = metadata_service.build_schema_context_for_prompt(
        column_names=["employee_id", "is_active", "department_name"]
    )
    assert len(focused) < len(full), (
        f"Focused schema ({len(focused)}) should be shorter than full ({len(full)})"
    )


def test_schema_context_with_column_names_excludes_irrelevant_columns(metadata_service):
    """Columns not in column_names list must not appear as column lines in focused schema."""
    focused = metadata_service.build_schema_context_for_prompt(
        column_names=["employee_id", "is_active", "gender"]
    )
    all_columns = metadata_service.get_columns()
    irrelevant = [
        c["name"] for c in all_columns if c["name"] not in {"employee_id", "is_active", "gender"}
    ]
    for col in irrelevant[:10]:
        assert f"- {col}:" not in focused, (
            f"Irrelevant column '{col}' column line should not appear in focused schema"
        )


def test_schema_context_with_column_names_always_includes_base_columns(metadata_service):
    """employee_id and is_active are always included regardless of column_names."""
    focused = metadata_service.build_schema_context_for_prompt(column_names=["department_name"])
    assert "- employee_id:" in focused
    assert "- is_active:" in focused


def test_schema_context_with_column_names_includes_requested_columns(metadata_service):
    """Requested columns must appear in focused schema."""
    focused = metadata_service.build_schema_context_for_prompt(
        column_names=["gender", "province", "service_years"]
    )
    assert "- gender:" in focused
    assert "- province:" in focused
    assert "- service_years:" in focused


def test_schema_context_with_column_names_omits_semantic_section(metadata_service):
    """Focused schema should not include the semantic mappings section."""
    focused = metadata_service.build_schema_context_for_prompt(
        column_names=["employee_id", "gender"]
    )
    assert "Semantic mappings" not in focused


def test_schema_context_without_column_names_unchanged(metadata_service):
    """Calling without column_names must still return full schema with semantic section."""
    full = metadata_service.build_schema_context_for_prompt()
    assert "hr_mvp.vw_hr_employee_analytics" in full
    assert "employee_id" in full


# ---------------------------------------------------------------------------
# Bug fix: find_semantic_matches must not match short terms as substrings
# ---------------------------------------------------------------------------


def test_find_semantic_matches_zan_does_not_match_inside_bazneshasteha(metadata_service):
    """'زن' must NOT match inside 'بازنشسته' — substring match is a bug."""
    q = "چند نفر از کارمندان تا ۵ سال آینده بازنشسته می‌شوند؟"
    matches = metadata_service.find_semantic_matches(q)
    matched_ids = [m["concept_id"] for m in matches]
    assert "female" not in matched_ids, (
        f"'female' concept must not match inside 'بازنشسته'. Got: {matched_ids}"
    )


def test_find_semantic_matches_zan_matches_when_standalone(metadata_service):
    """'زن' must still match when it appears as a standalone word."""
    q = "تعداد کارکنان زن چند نفر است؟"
    matches = metadata_service.find_semantic_matches(q)
    matched_ids = [m["concept_id"] for m in matches]
    assert "female" in matched_ids, (
        f"'female' concept must match 'زن' as standalone word. Got: {matched_ids}"
    )


# ---------------------------------------------------------------------------
# Bug fix: near_retirement_analysis must route to SQL
# ---------------------------------------------------------------------------


def test_near_retirement_intent_routes_to_sql(metadata_service):
    """near_retirement_analysis intent must have route=SQL, not GAP."""
    intent = metadata_service.get_intent("near_retirement_analysis")
    assert intent is not None, "near_retirement_analysis intent not found"
    assert intent.get("route") == "SQL", f"Expected route=SQL, got: {intent.get('route')}"


def test_near_retirement_sql_template_exists(metadata_service):
    """near_retirement_analysis must have a resolvable SQL template."""
    intent = metadata_service.get_intent("near_retirement_analysis")
    assert intent is not None
    tpl_id = intent.get("sql_template_id")
    assert tpl_id, "near_retirement_analysis must have sql_template_id"
    tpl = metadata_service.get_sql_template(tpl_id)
    assert tpl is not None, f"Template '{tpl_id}' not found"
    sql = tpl.get("sql", "")
    assert "age" in sql.lower(), "Retirement template must check age"
    assert "service_years" in sql.lower(), "Retirement template must check service_years"
    assert "gender" in sql.lower(), "Retirement template must differentiate gender"
