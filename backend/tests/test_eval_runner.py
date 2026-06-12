"""Tests for eval/run_evaluation.py — category support."""

from __future__ import annotations

import csv
import json
from pathlib import Path
from unittest.mock import MagicMock

from eval.run_evaluation import _CSV_FIELDS, _extract, _load_input

# ---------------------------------------------------------------------------
# _load_input
# ---------------------------------------------------------------------------


def test_load_input_json_preserves_category(tmp_path: Path) -> None:
    data = [
        {"question_id": "q001", "question": "سوال اول", "category": "demographics"},
        {"question_id": "q002", "question": "سوال دوم", "category": "employment_type"},
    ]
    f = tmp_path / "questions.json"
    f.write_text(json.dumps(data), encoding="utf-8")

    rows = _load_input(f)

    assert rows[0]["category"] == "demographics"
    assert rows[1]["category"] == "employment_type"


def test_load_input_csv_preserves_category(tmp_path: Path) -> None:
    f = tmp_path / "questions.csv"
    with open(f, "w", encoding="utf-8", newline="") as fh:
        writer = csv.DictWriter(fh, fieldnames=["question_id", "question", "category"])
        writer.writeheader()
        writer.writerow(
            {"question_id": "q001", "question": "سوال اول", "category": "org_structure"}
        )
        writer.writerow({"question_id": "q002", "question": "سوال دوم", "category": "recruitment"})

    rows = _load_input(f)

    assert rows[0]["category"] == "org_structure"
    assert rows[1]["category"] == "recruitment"


def test_load_input_missing_category_defaults_to_none(tmp_path: Path) -> None:
    data = [{"question_id": "q001", "question": "سوال بدون دسته"}]
    f = tmp_path / "questions.json"
    f.write_text(json.dumps(data), encoding="utf-8")

    rows = _load_input(f)

    assert rows[0].get("category") is None


def test_load_input_auto_assigns_question_id(tmp_path: Path) -> None:
    data = [{"question": "اول"}, {"question": "دوم"}]
    f = tmp_path / "questions.json"
    f.write_text(json.dumps(data), encoding="utf-8")

    rows = _load_input(f)

    assert rows[0]["question_id"] == "q001"
    assert rows[1]["question_id"] == "q002"


# ---------------------------------------------------------------------------
# _extract — category pass-through
# ---------------------------------------------------------------------------


def _make_mock_response(route: str = "SQL", status: str = "NOT_EXECUTED") -> MagicMock:
    response = MagicMock()
    response.to_dict.return_value = {
        "route": route,
        "status": status,
        "detected_intent": "",
        "errors": [],
        "warnings": [],
        "context": {
            "traces": [],
            "sql_plan": {},
            "query_result": {},
            "sql_validation": {},
            "visualization_plan": {},
        },
    }
    return response


def test_extract_includes_category_when_present() -> None:
    case = {"question_id": "q001", "question": "سوال", "category": "demographics"}
    result = _extract(_make_mock_response(), elapsed_ms=100, case=case)

    assert result["category"] == "demographics"


def test_extract_category_none_when_missing() -> None:
    case = {"question_id": "q001", "question": "سوال"}
    result = _extract(_make_mock_response(), elapsed_ms=100, case=case)

    assert result["category"] is None


# ---------------------------------------------------------------------------
# _CSV_FIELDS
# ---------------------------------------------------------------------------


def test_csv_fields_include_category() -> None:
    assert "category" in _CSV_FIELDS
