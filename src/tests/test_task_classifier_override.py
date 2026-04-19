"""
Tests for the Tier 1 content-mismatch override in task_classifier.py.

Phase 4e.2 defect: quote_engine maps to pricing_math by module hint,
but it also handles property description / marketing copy requests.
The override fires when the prompt has no pricing signal and clear
descriptive signal — reclassifying to vrs_concierge.
"""
from __future__ import annotations

import sys
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "fortress-guest-platform"))
from backend.services.task_classifier import classify_task_type, _detect_content_mismatch


# ---------------------------------------------------------------------------
# _detect_content_mismatch unit tests
# ---------------------------------------------------------------------------

class TestDetectContentMismatch:
    def test_pricing_prompt_keeps_pricing_math(self):
        assert _detect_content_mismatch("pricing_math",
            "Price this property for 3 nights at nightly rate $250") is None

    def test_rate_strategy_keeps_pricing_math(self):
        assert _detect_content_mismatch("pricing_math",
            "COMPETITOR VISUAL ANALYSIS: {} \nrate_multiplier extraction strategy") is None

    def test_dollar_amount_keeps_pricing_math(self):
        assert _detect_content_mismatch("pricing_math",
            "What would be a $350/night rate for this cabin?") is None

    def test_strike_type_extraction_keeps_pricing_math(self):
        assert _detect_content_mismatch("pricing_math",
            'strike_type: "extraction", rate_multiplier: 1.20') is None

    def test_descriptive_no_pricing_overrides_to_vrs_concierge(self):
        result = _detect_content_mismatch("pricing_math",
            "What does High Hopes look like? Describe the exterior and amenities.")
        assert result == "vrs_concierge"

    def test_marketing_copy_request_overrides(self):
        result = _detect_content_mismatch("pricing_math",
            "Generate marketing copy for this luxury retreat. "
            "Property: Above the Timberline. Self check-in, panoramic views.")
        assert result == "vrs_concierge"

    def test_tell_me_about_amenities_overrides(self):
        result = _detect_content_mismatch("pricing_math",
            "Tell me about the amenities of High Hopes cabin.")
        assert result == "vrs_concierge"

    def test_non_pricing_math_module_never_overrides(self):
        """Override must not fire for any other task_type."""
        for task in ("vrs_concierge", "legal_reasoning", "vision_photo",
                     "market_research", "generic"):
            assert _detect_content_mismatch(task, "describe the property exterior") is None

    def test_prompt_with_both_signals_keeps_pricing(self):
        """Pricing signal present → no override even if descriptive language also present."""
        result = _detect_content_mismatch("pricing_math",
            "Describe the property and give me a nightly rate for 3 nights.")
        assert result is None

    def test_empty_prompt_no_override(self):
        assert _detect_content_mismatch("pricing_math", "") is None


# ---------------------------------------------------------------------------
# Full classify_task_type integration tests
# ---------------------------------------------------------------------------

class TestClassifyTaskTypeOverride:
    def _classify(self, module: str, prompt: str) -> str:
        """Classify with LLM tier mocked out (not needed for these tests)."""
        with patch("backend.services.task_classifier._llm_classify", return_value="generic"):
            return classify_task_type(module, prompt)

    # --- Tier 1 wins: pricing keywords confirm module hint ---

    def test_quote_engine_explicit_pricing_stays_pricing_math(self):
        assert self._classify(
            "quote_engine",
            "Price this property for 3 nights. Nightly rate: $275. What is the total?",
        ) == "pricing_math"

    def test_quote_engine_rate_strategy_stays_pricing_math(self):
        assert self._classify(
            "quote_engine",
            "COMPETITOR VISUAL ANALYSIS: {}\nrate_multiplier: 1.20, strike_type: extraction",
        ) == "pricing_math"

    def test_quote_engine_dollar_amount_stays_pricing_math(self):
        assert self._classify(
            "quote_engine",
            "Adjust the nightly rate. Current: $320. Competitor avg: $289.",
        ) == "pricing_math"

    # --- Tier 2 overrides: descriptive prompt from pricing module ---

    def test_quote_engine_what_does_look_like_overrides(self):
        assert self._classify(
            "quote_engine",
            "What does High Hopes look like? Describe exterior and amenities.",
        ) == "vrs_concierge"

    def test_quote_engine_listing_description_overrides(self):
        assert self._classify(
            "quote_engine",
            "Property: High Hopes\nDates: 2026-05-15 to 2026-05-17\n"
            "Generate a listing description. Luxury retreat, self check-in, panoramic views.",
        ) == "vrs_concierge"

    def test_quote_engine_tell_me_about_amenities_overrides(self):
        assert self._classify(
            "quote_engine",
            "Tell me about the amenities of this cabin. Features of the outdoor deck.",
        ) == "vrs_concierge"

    # --- vrs_agent_dispatcher: pricing keywords do NOT override to pricing_math ---

    def test_vrs_dispatcher_with_pricing_keywords_stays_vrs_concierge(self):
        """
        vrs_agent_dispatcher → vrs_concierge via Tier 1.
        Pricing keywords alone don't trigger override (only pricing_math can be overridden).
        """
        assert self._classify(
            "vrs_agent_dispatcher",
            "The nightly rate is $250. Price this stay for 3 nights total.",
        ) == "vrs_concierge"

    def test_vrs_dispatcher_generic_concierge_stays_vrs_concierge(self):
        assert self._classify(
            "vrs_agent_dispatcher",
            "Guest asking about checkout procedures.",
        ) == "vrs_concierge"

    # --- Legal and other modules unaffected ---

    def test_legal_module_unaffected(self):
        assert self._classify(
            "legal_council",
            "describe the exterior of the property at issue in this case",
        ) == "legal_reasoning"

    def test_unknown_module_falls_through_to_keyword(self):
        """Module not in _MODULE_TO_TASK falls to Tier 2 keyword patterns."""
        result = self._classify(
            "unknown_module",
            "Please debug this traceback: AttributeError on line 42",
        )
        assert result == "code_debugging"

    # --- Retroactive fix verification: the mislabeled High Hopes capture ---

    def test_high_hopes_marketing_copy_prompt_reclassified(self):
        """
        Regression test for capture 308ec10c (label 1881b85f).
        quote_engine sent a property data packet; response was marketing copy.
        The new classifier must return vrs_concierge, not pricing_math.
        """
        prompt = (
            "Property: High Hopes\n"
            "Dates: 2026-05-15 to 2026-05-17\n"
            "Amenities: self check-in, smart home, panoramic views, luxury retreat\n"
            "Generate a property description for our listing."
        )
        assert self._classify("quote_engine", prompt) == "vrs_concierge"
