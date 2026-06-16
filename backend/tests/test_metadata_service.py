from __future__ import annotations

DB_DOCTORAL_VALUE = "دکترای تخصصی PHD / دکترای حرفه ای"


def test_metadata_health_is_ok(metadata_service):
    health = metadata_service.health_check().to_dict()
    assert health["ok"] is True
    assert not health["errors"]


def test_main_view_and_core_templates_exist(metadata_service):
    main_view = metadata_service.get_main_view()
    assert main_view.get("name") == "hr_mvp.vw_hr_employee_analytics"

    assert metadata_service.get_sql_template("TPL_TOTAL_EMPLOYEE_COUNT") is not None
    assert metadata_service.get_sql_template("TPL_DATA_GAP") is not None
    assert metadata_service.get_sql_template("TPL_ACCESS_DENIED") is not None
    assert metadata_service.get_status_sql("DATA_GAP") == "SELECT 'DATA_GAP' AS status;"


def _get_education_value_aliases(metadata_service):
    sl = metadata_service.get_document("semantic_layer") or {}
    return (sl.get("value_aliases") or {}).get("education_title", [])


def _get_validator_education_allowed(metadata_service):
    vr = metadata_service.get_document("sql_validator_rules") or {}
    pv = vr.get("parameter_validation", {}) or {}
    return (pv.get("allowed_values") or {}).get("education_title", [])


def test_education_doctoral_filter_sql_matches_db(metadata_service):
    entries = _get_education_value_aliases(metadata_service)
    doctoral_entry = next(
        (e for e in entries if DB_DOCTORAL_VALUE in str(e.get("canonical_value", ""))),
        None,
    )
    assert doctoral_entry is not None, f"No education entry with canonical_value='{DB_DOCTORAL_VALUE}'"
    filter_sql = doctoral_entry.get("filter_sql", "")
    assert DB_DOCTORAL_VALUE in filter_sql, (
        f"filter_sql '{filter_sql}' does not contain correct DB value '{DB_DOCTORAL_VALUE}'"
    )


def test_education_no_bare_doktora_canonical(metadata_service):
    entries = _get_education_value_aliases(metadata_service)
    canonical_values = [str(e.get("canonical_value", "")) for e in entries]
    assert "دکترا" not in canonical_values, (
        "'دکترا' should not be a canonical_value — it is not in the DB"
    )


def test_education_doktora_is_alias_not_canonical(metadata_service):
    entries = _get_education_value_aliases(metadata_service)
    doctoral_entry = next(
        (e for e in entries if DB_DOCTORAL_VALUE in str(e.get("canonical_value", ""))),
        None,
    )
    assert doctoral_entry is not None
    aliases = [str(a) for a in (doctoral_entry.get("aliases_fa") or [])]
    assert "دکترا" in aliases, "'دکترا' should be an alias for the doctoral entry"
    assert "دکتری" in aliases, "'دکتری' should be an alias for the doctoral entry"


def test_education_kamtar_az_sikl_has_own_canonical(metadata_service):
    entries = _get_education_value_aliases(metadata_service)
    kamtar_entry = next(
        (e for e in entries if str(e.get("canonical_value", "")) == "کمتر از سیکل"),
        None,
    )
    assert kamtar_entry is not None, (
        "'کمتر از سیکل' is a valid DB value and must have its own canonical entry"
    )
    assert "کمتر از سیکل" in str(kamtar_entry.get("filter_sql", "")), (
        "filter_sql for 'کمتر از سیکل' must use the DB value 'کمتر از سیکل'"
    )


def test_validator_education_allowed_values_match_db(metadata_service):
    allowed = _get_validator_education_allowed(metadata_service)
    assert DB_DOCTORAL_VALUE in allowed, (
        f"'{DB_DOCTORAL_VALUE}' missing from validator allowed_values"
    )
    assert "دکترا" not in allowed, (
        "'دکترا' must not be in validator allowed_values — it is not in the DB"
    )
