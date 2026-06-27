"""Behavior-lock parity for the Phase 3.1 God-class decomposition.

Snapshots the exact output of ``IntentParser._manual_intent_rules`` (rule
registry, target A) and ``IntentParser._extract_structured_payload`` (payload
builder registry, target B) over a corpus of real routing-eval questions. The
fixture is generated from the *pre-refactor* code and committed, so the
post-refactor registries must reproduce it byte-for-byte.

Regenerate the fixture (only when an intentional behavior change is made):

    uv run python tests/test_intent_parser_parity.py
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from app.hr_analytics.use_cases.steps.intent_parser import IntentParser

FIXTURE = Path(__file__).parent / "fixtures" / "intent_parser_parity.json"
CURRENT_SHAMSI_YEAR = 1404


def _canon(obj):
    """Recursively turn tuples into lists so JSON round-trips compare cleanly."""
    if isinstance(obj, tuple | list):
        return [_canon(x) for x in obj]
    if isinstance(obj, dict):
        return {k: _canon(v) for k, v in obj.items()}
    return obj


def compute(parser: IntentParser, raw_question: str) -> dict:
    """Drive both God methods for one question and capture their outputs."""
    question = parser.normalize_text(raw_question)
    features = parser._detect_query_features(question, {})
    manual = parser._manual_intent_rules(question, features, parser.metadata)

    signals = parser._collect_semantic_signals({})
    catalog = parser._get_document(parser.metadata, "intent_catalog")
    candidates = parser._score_intents(
        question=question,
        service=parser.metadata,
        intent_catalog=catalog,
        semantic_signals=signals,
        query_features=features,
    )
    best = candidates[0].intent_id if candidates else ""
    intent = parser._get_intent(parser.metadata, best) or {}
    payload = parser._extract_structured_payload(
        question=question,
        intent=intent,
        best_intent_id=best,
        semantic_result={},
        query_features=features,
        current_shamsi_year=CURRENT_SHAMSI_YEAR,
        service=parser.metadata,
    )
    return {"manual_rules": _canon(manual), "best_intent_id": best, "payload": _canon(payload)}


def _load_fixture() -> dict:
    return json.loads(FIXTURE.read_text(encoding="utf-8"))


@pytest.mark.skipif(not FIXTURE.exists(), reason="parity fixture not generated yet")
def test_manual_rules_and_payload_parity():
    fixture = _load_fixture()
    parser = IntentParser()
    mismatches = []
    for question, expected in fixture.items():
        actual = compute(parser, question)
        if actual != expected:
            mismatches.append(question)
    assert not mismatches, (
        f"{len(mismatches)} parity mismatch(es) after refactor; first few: {mismatches[:5]}"
    )


def _regenerate() -> None:
    corpus = json.loads(
        (Path(__file__).parent / "fixtures" / "parity_corpus.json").read_text("utf-8")
    )
    parser = IntentParser()
    out = {q: compute(parser, q) for q in corpus}
    FIXTURE.parent.mkdir(parents=True, exist_ok=True)
    FIXTURE.write_text(json.dumps(out, ensure_ascii=False, indent=1, sort_keys=True), "utf-8")
    print(f"wrote {len(out)} parity snapshots to {FIXTURE}")


if __name__ == "__main__":
    _regenerate()
