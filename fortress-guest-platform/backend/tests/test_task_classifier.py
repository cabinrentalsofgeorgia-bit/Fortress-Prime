"""Tests for Phase 4e.2 task type classifier."""
from unittest.mock import patch, MagicMock

import pytest


def _cls():
    from backend.services.task_classifier import classify_task_type
    return classify_task_type


def _types():
    from backend.services.task_types import _TASK_TYPES, _MODULE_TO_TASK
    return _TASK_TYPES, _MODULE_TO_TASK


# ---------------------------------------------------------------------------
# Tier 1: source module hints
# ---------------------------------------------------------------------------

class TestTier1ModuleHints:
    def test_every_module_returns_valid_task_type(self):
        _TASK_TYPES, _MODULE_TO_TASK = _types()
        classify = _cls()
        for module, expected_task in _MODULE_TO_TASK.items():
            result = classify(source_module=module, prompt="anything")
            assert result == expected_task, f"{module} → expected {expected_task}, got {result}"
            assert result in _TASK_TYPES, f"{result} not in _TASK_TYPES"

    def test_legal_council_returns_legal_reasoning(self):
        assert _cls()("legal_council", "analyze case") == "legal_reasoning"

    def test_legal_deposition_returns_brief_drafting(self):
        assert _cls()("legal_deposition_prep", "prep witness") == "brief_drafting"

    def test_ediscovery_returns_legal_citations(self):
        assert _cls()("ediscovery_agent", "find docs") == "legal_citations"

    def test_vrs_dispatcher_returns_vrs_concierge(self):
        assert _cls()("vrs_agent_dispatcher", "guest inquiry") == "vrs_concierge"

    def test_quote_engine_returns_pricing_math(self):
        assert _cls()("quote_engine", "price cabin") == "pricing_math"

    def test_ota_vision_returns_vision_photo(self):
        assert _cls()("ota_vision_recon", "analyze photo") == "vision_photo"

    def test_macro_treasury_returns_market_research(self):
        assert _cls()("macro_treasury", "market analysis") == "market_research"

    def test_legal_council_seat_prefix_matches(self):
        """legal_council_of_9/seat_1/... prefix should resolve to legal_reasoning."""
        result = _cls()("legal_council_of_9/seat_1/Senior Litigator", "analyze case")
        assert result == "legal_reasoning"

    def test_unknown_module_falls_through_to_tier2(self):
        """Unknown module should not return via tier 1 — allows tier 2 to run."""
        with patch("backend.services.task_classifier._llm_classify", return_value="generic"):
            result = _cls()("unknown_module_xyz", "refactor this function")
        assert result == "code_refactoring"  # keyword pattern tier 2


# ---------------------------------------------------------------------------
# Tier 2: keyword patterns
# ---------------------------------------------------------------------------

class TestTier2Keywords:
    def _classify_unknown_module(self, prompt: str, response: str = "") -> str:
        with patch("backend.services.task_classifier._llm_classify", return_value="generic"):
            return _cls()("unknown_module", prompt, response)

    def test_brief_drafting_keyword(self):
        assert self._classify_unknown_module("draft a brief for the court") == "brief_drafting"

    def test_contract_analysis_keyword(self):
        assert self._classify_unknown_module("analyze this contract clause") == "contract_analysis"

    def test_legal_citation_keyword(self):
        assert self._classify_unknown_module("cite the relevant statute") == "legal_citations"

    def test_pricing_math_keyword(self):
        assert self._classify_unknown_module("price this cabin for June") == "pricing_math"

    def test_code_refactoring_keyword(self):
        assert self._classify_unknown_module("refactor this function for clarity") == "code_refactoring"

    def test_code_debugging_keyword(self):
        assert self._classify_unknown_module("debug why this is failing") == "code_debugging"

    def test_code_generation_keyword(self):
        assert self._classify_unknown_module("write a function to parse JSON") == "code_generation"

    def test_vision_damage_keyword(self):
        assert self._classify_unknown_module("damage assessment of the roof") == "vision_damage"

    def test_vision_photo_keyword(self):
        assert self._classify_unknown_module("describe this photo of the cabin") == "vision_photo"

    def test_real_time_keyword(self):
        assert self._classify_unknown_module("latest news on rental regulations") == "real_time"

    def test_vrs_ota_keyword(self):
        assert self._classify_unknown_module("respond to this guest inquiry about checkout") == "vrs_ota_response"

    def test_acquisitions_keyword(self):
        assert self._classify_unknown_module("due diligence on this property acquisition") == "acquisitions_analysis"

    def test_math_keyword(self):
        assert self._classify_unknown_module("calculate the revenue split") == "math_reasoning"

    def test_case_insensitive(self):
        assert self._classify_unknown_module("DRAFT A BRIEF") == "brief_drafting"

    def test_combined_prompt_and_response_used(self):
        """Keyword in response should also trigger classification."""
        result = self._classify_unknown_module(
            prompt="help me",
            response="I'll draft a brief for this case",
        )
        assert result == "brief_drafting"

    def test_first_pattern_wins(self):
        """When multiple patterns match, first in list wins."""
        # "draft a brief" matches brief_drafting before anything else
        result = self._classify_unknown_module("draft a brief and analyze the contract")
        assert result == "brief_drafting"


# ---------------------------------------------------------------------------
# Tier 3: LLM fallback
# ---------------------------------------------------------------------------

class TestTier3LLMFallback:
    def _no_pattern_prompt(self):
        return "tell me something interesting about neural networks"

    def test_valid_llm_response_returned(self):
        mock_resp = MagicMock()
        mock_resp.json.return_value = {"response": "market_research"}
        mock_resp.raise_for_status = MagicMock()
        with patch("httpx.post", return_value=mock_resp):
            result = _cls()("unknown", self._no_pattern_prompt())
        assert result == "market_research"

    def test_invalid_llm_response_returns_generic(self):
        mock_resp = MagicMock()
        mock_resp.json.return_value = {"response": "totally_invalid_type_xyz"}
        mock_resp.raise_for_status = MagicMock()
        with patch("httpx.post", return_value=mock_resp):
            result = _cls()("unknown", self._no_pattern_prompt())
        assert result == "generic"

    def test_llm_timeout_returns_generic(self):
        import httpx as _httpx
        with patch("httpx.post", side_effect=_httpx.TimeoutException("timeout")):
            result = _cls()("unknown", self._no_pattern_prompt())
        assert result == "generic"

    def test_llm_connection_error_returns_generic(self):
        with patch("httpx.post", side_effect=Exception("connection refused")):
            result = _cls()("unknown", self._no_pattern_prompt())
        assert result == "generic"

    def test_llm_empty_response_returns_generic(self):
        mock_resp = MagicMock()
        mock_resp.json.return_value = {"response": ""}
        mock_resp.raise_for_status = MagicMock()
        with patch("httpx.post", return_value=mock_resp):
            result = _cls()("unknown", self._no_pattern_prompt())
        assert result == "generic"

    def test_llm_response_parsed_case_insensitively(self):
        """LLM might return uppercase."""
        mock_resp = MagicMock()
        mock_resp.json.return_value = {"response": "LEGAL_REASONING"}
        mock_resp.raise_for_status = MagicMock()
        with patch("httpx.post", return_value=mock_resp):
            result = _cls()("unknown", self._no_pattern_prompt())
        assert result == "legal_reasoning"


# ---------------------------------------------------------------------------
# Safety: never raises
# ---------------------------------------------------------------------------

class TestSafetyNeverRaises:
    def test_none_source_module_safe(self):
        result = _cls()(None, "test prompt")  # type: ignore[arg-type]
        assert isinstance(result, str)

    def test_empty_prompt_safe(self):
        with patch("backend.services.task_classifier._llm_classify", return_value="generic"):
            result = _cls()("unknown", "")
        assert result == "generic"

    def test_very_long_prompt_safe(self):
        with patch("backend.services.task_classifier._llm_classify", return_value="market_research"):
            result = _cls()("unknown", "x" * 100_000)
        assert result in ("market_research", "generic")

    def test_all_results_are_valid_task_types(self):
        _TASK_TYPES, _MODULE_TO_TASK = _types()
        prompts = [
            ("legal_council", "analyze this case"),
            ("unknown", "write some code"),
            ("unknown", "draft a brief"),
            ("unknown", "totally unrecognized query"),
        ]
        for module, prompt in prompts:
            with patch("backend.services.task_classifier._llm_classify", return_value="generic"):
                result = _cls()(module, prompt)
            assert result in _TASK_TYPES, f"'{result}' not in _TASK_TYPES for module={module!r}"
