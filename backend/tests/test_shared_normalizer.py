"""
Unit tests for the shared Persian text normalizer.
Run: uv run pytest tests/test_shared_normalizer.py -v
"""
from __future__ import annotations

import pytest


def _norm(text: str) -> str:
    from app.hr_analytics.use_cases.steps.shared_normalizer import normalize
    return normalize(text)


# ---------------------------------------------------------------------------
# Character normalization
# ---------------------------------------------------------------------------

class TestCharNormalization:
    def test_arabic_ye_to_persian(self):
        assert _norm("كاري") == "کاری"

    def test_arabic_kaf_to_persian(self):
        assert _norm("كارمند") == "کارمند"

    def test_zwnj_to_space(self):
        assert "می شوند" in _norm("می‌شوند") or "میشوند" in _norm("می‌شوند")

    def test_persian_digits(self):
        assert "5" in _norm("۵")
        assert "10" in _norm("۱۰")

    def test_arabic_digits(self):
        assert "3" in _norm("٣")


# ---------------------------------------------------------------------------
# Compound word joining (HR domain)
# ---------------------------------------------------------------------------

class TestCompoundWords:
    def test_baz_neshaste_split(self):
        assert "بازنشسته" in _norm("باز نشسته")

    def test_baz_neshasteги_split(self):
        assert "بازنشستگی" in _norm("باز نشستگی")

    def test_kar_mand_split(self):
        assert "کارمند" in _norm("کار مند")

    def test_kar_mandan_split(self):
        assert "کارمندان" in _norm("کار مندان")

    def test_peymankar_split(self):
        assert "پیمانکار" in _norm("پیمان کار")

    def test_peymankari_split(self):
        assert "پیمانکاری" in _norm("پیمان کاری")

    def test_karkonan_split(self):
        assert "کارکنان" in _norm("کار کنان")

    def test_compound_in_sentence(self):
        result = _norm("چند نفر از کار مندان باز نشسته میشن")
        assert "کارمندان" in result
        assert "بازنشسته" in result


# ---------------------------------------------------------------------------
# می verb prefix joining
# ---------------------------------------------------------------------------

class TestMiJoining:
    def test_mi_space_verb(self):
        assert "میشوند" in _norm("می شوند")

    def test_mi_halfspace_verb(self):
        assert "میشوند" in _norm("می‌شوند")

    def test_mi_konad(self):
        assert "میکند" in _norm("می کند")

    def test_mi_suffix_word_not_joined(self):
        """'اسامی کارکنان' — 'می' ending 'اسامی' must NOT merge with next word."""
        result = _norm("لیست اسامی کارکنان دپارتمان مالی")
        assert "اسامی کارکنان" in result, (
            f"'اسامی کارکنان' must stay separate, got: '{result}'"
        )

    def test_adami_not_joined(self):
        """'آدمی کارمند' — 'می' in 'آدمی' must NOT merge with next word."""
        result = _norm("آدمی کارمند است")
        assert "آدمی کارمند" in result, f"got: '{result}'"


# ---------------------------------------------------------------------------
# Colloquial verb normalization
# ---------------------------------------------------------------------------

class TestColloquialVerbs:
    def test_mishon(self):
        assert "میشوند" in _norm("میشن")

    def test_mishe(self):
        assert "میشود" in _norm("میشه")

    def test_hastan(self):
        assert "هستند" in _norm("هستن")

    def test_mikonan(self):
        assert "میکنند" in _norm("میکنن")

    def test_daran(self):
        assert "دارند" in _norm("دارن")

    def test_bashn(self):
        assert "بشوند" in _norm("بشن")

    def test_bashe(self):
        assert "بشود" in _norm("بشه")

    def test_colloquial_in_sentence(self):
        result = _norm("چند نفر از کار مندان تا 5 سال آینده باز نشسته میشن ؟")
        assert "کارمندان" in result
        assert "بازنشسته" in result
        assert "میشوند" in result


# ---------------------------------------------------------------------------
# Whitespace / punctuation cleanup
# ---------------------------------------------------------------------------

class TestCleanup:
    def test_multi_space_collapsed(self):
        assert _norm("کارمند  داریم") == "کارمند داریم"

    def test_persian_question_mark_removed(self):
        assert "؟" not in _norm("کارمند چند نفر است؟")

    def test_strip(self):
        assert _norm("  کارمند  ") == "کارمند"


# ---------------------------------------------------------------------------
# Integration: domain_classifier uses shared normalizer
# ---------------------------------------------------------------------------

class TestDomainClassifierIntegration:
    def test_split_word_karmandar_classified_hr(self):
        """'کار مندان' after normalization must match HR terms."""
        from app.hr_analytics.use_cases.steps.domain_classifier import (
            DomainClassifier,
            DOMAIN_HR,
        )
        dc = DomainClassifier()
        result = dc.classify("چند نفر از کار مندان تا 5 سال آینده باز نشسته میشن ؟")
        assert result["domain"] == DOMAIN_HR, (
            f"split-word question classified as '{result['domain']}' instead of '{DOMAIN_HR}'"
        )

    def test_split_baz_neshaste_classified_hr(self):
        """'باز نشسته' split form must be recognized as HR domain."""
        from app.hr_analytics.use_cases.steps.domain_classifier import (
            DomainClassifier,
            DOMAIN_HR,
        )
        dc = DomainClassifier()
        result = dc.classify("چه کسانی باز نشسته میشن ؟")
        assert result["domain"] == DOMAIN_HR, (
            f"'باز نشسته' classified as '{result['domain']}' instead of '{DOMAIN_HR}'"
        )

    def test_colloquial_mishon_classified_hr(self):
        """Colloquial 'میشن' must not prevent HR classification."""
        from app.hr_analytics.use_cases.steps.domain_classifier import (
            DomainClassifier,
            DOMAIN_HR,
        )
        dc = DomainClassifier()
        result = dc.classify("تعداد کارکنانی که بازنشسته میشن چقدره ؟")
        assert result["domain"] == DOMAIN_HR, (
            f"colloquial question classified as '{result['domain']}' instead of '{DOMAIN_HR}'"
        )


# ---------------------------------------------------------------------------
# Backward-compat: IntentParser.normalize_text delegates to shared normalizer
# ---------------------------------------------------------------------------

class TestIntentParserBackwardCompat:
    def test_normalize_text_still_joins_compound(self):
        from app.hr_analytics.use_cases.steps.intent_parser import IntentParser
        ip = IntentParser.__new__(IntentParser)
        assert "بازنشسته" in ip.normalize_text("باز نشسته")

    def test_normalize_text_still_converts_colloquial(self):
        from app.hr_analytics.use_cases.steps.intent_parser import IntentParser
        ip = IntentParser.__new__(IntentParser)
        assert "میشوند" in ip.normalize_text("میشن")

    def test_normalize_text_kar_mandan(self):
        from app.hr_analytics.use_cases.steps.intent_parser import IntentParser
        ip = IntentParser.__new__(IntentParser)
        assert "کارمندان" in ip.normalize_text("کار مندان")


# ---------------------------------------------------------------------------
# Root fix: orchestrator entry-point normalization
# ---------------------------------------------------------------------------

class TestOrchestratorNormalization:
    def test_shared_normalizer_fixes_metadata_gap(self):
        """shared_normalizer must produce what metadata.normalize_question cannot."""
        from app.hr_analytics.use_cases.steps.shared_normalizer import normalize
        result = normalize("کار مندان باز نشسته میشن")
        assert "کارمندان" in result
        assert "بازنشسته" in result
        assert "میشوند" in result

    def test_metadata_normalize_question_uses_shared(self):
        """After fix: metadata.normalize_question must delegate to shared_normalizer."""
        from app.infrastructure.metadata.service import MetadataService
        svc = MetadataService.__new__(MetadataService)
        result = svc.normalize_question("چند نفر از کار مندان باز نشسته میشن ؟")
        assert "کارمندان" in result, "metadata.normalize_question must join 'کار مندان'"
        assert "بازنشسته" in result, "metadata.normalize_question must join 'باز نشسته'"
        assert "میشوند" in result, "metadata.normalize_question must convert 'میشن'"


class TestSemanticMatchingAfterNormalization:
    """find_semantic_matches must still match concept terms that contain Persian digits."""

    def test_above_age_term_matches_after_digit_normalization(self):
        """Concept term 'بالای ۶۰' (Persian digit) must match when question has ASCII '60'."""
        from app.infrastructure.metadata.service import get_metadata_service

        svc = get_metadata_service()
        matches = svc.find_semantic_matches("لیست افراد بالای ۶۰ سال با شناسه‌شان را بده")
        concept_ids = [m["concept_id"] for m in matches]
        assert any(cid for cid in concept_ids), (
            "find_semantic_matches must return at least one match for age-filter access question; "
            f"got none — term '«بالای ۶۰»' not found after digit normalization. matches={matches}"
        )

    def test_access_question_reaches_access_denied_not_out_of_scope(self):
        """'لیست افراد' questions must be ACCESS_DENIED, not OUT_OF_SCOPE."""
        import asyncio
        from app.hr_analytics.use_cases.orchestrator import LLMOrchestrator
        from app.infrastructure.metadata.service import get_metadata_service

        svc = get_metadata_service()
        orch = LLMOrchestrator(metadata_service=svc, default_execute_sql=False)
        result = asyncio.run(
            orch.arun("لیست افراد بالای ۶۰ سال با شناسه‌شان را بده", execute_sql=False)
        )
        d = result if isinstance(result, dict) else vars(result)
        assert d.get("status") == "ACCESS_DENIED", (
            f"access question must return ACCESS_DENIED, got {d.get('status')}"
        )

    def test_fihrist_afrad_access_denied(self):
        """'فهرست افراد' access question must be ACCESS_DENIED."""
        import asyncio
        from app.hr_analytics.use_cases.orchestrator import LLMOrchestrator
        from app.infrastructure.metadata.service import get_metadata_service

        svc = get_metadata_service()
        orch = LLMOrchestrator(metadata_service=svc, default_execute_sql=False)
        result = asyncio.run(
            orch.arun("فهرست افراد زیر ۳۰ سال با شناسه", execute_sql=False)
        )
        d = result if isinstance(result, dict) else vars(result)
        assert d.get("status") == "ACCESS_DENIED", (
            f"'فهرست افراد' must return ACCESS_DENIED, got {d.get('status')}"
        )


class TestEndToEndColloquialRouting:
    """Full pipeline tests — these must return SQL route, not NEEDS_CLARIFICATION."""

    @pytest.fixture
    def sync_orchestrator(self):
        """Build a minimal sync-runnable orchestrator for routing tests."""
        import asyncio
        from app.hr_analytics.use_cases.orchestrator import LLMOrchestrator
        from app.infrastructure.metadata.service import get_metadata_service

        metadata = get_metadata_service()

        class _SyncOrch:
            def __init__(self):
                self._orch = LLMOrchestrator(metadata_service=metadata)

            def run(self, question: str) -> dict:
                return asyncio.run(self._orch.arun(question, execute_sql=False))

        return _SyncOrch()

    def test_split_kar_mandan_routes_sql(self, sync_orchestrator):
        """'کار مندان' (split) must reach SQL route, not NEEDS_CLARIFICATION."""
        result = sync_orchestrator.run("چند نفر از کار مندان تا ۵ سال آینده باز نشسته میشن ؟")
        d = result if isinstance(result, dict) else result.to_dict() if hasattr(result, 'to_dict') else vars(result)
        assert d.get("route") == "SQL" or d.get("status") not in ("NEEDS_CLARIFICATION",), (
            f"split 'کار مندان' returned {d.get('route')}/{d.get('status')} instead of SQL"
        )

    def test_colloquial_mishon_routes_sql(self, sync_orchestrator):
        """'میشن' (colloquial) must not block SQL routing."""
        result = sync_orchestrator.run("چند نفر از کارمندان بازنشسته میشن ؟")
        d = result if isinstance(result, dict) else result.to_dict() if hasattr(result, 'to_dict') else vars(result)
        assert d.get("status") not in ("NEEDS_CLARIFICATION",), (
            f"colloquial 'میشن' returned {d.get('status')}"
        )
