"""Tests for the privilege filter."""
import pytest

from backend.services.privilege_filter import (
    classify_for_capture,
    CaptureRoute,
    LEGAL_PERSONAS,
)


class TestLegalPersonas:
    def test_each_legal_persona_routes_to_restricted(self):
        for persona in LEGAL_PERSONAS:
            result = classify_for_capture(
                prompt="What is the standard of review?",
                response="De novo review applies.",
                source_persona=persona,
            )
            assert result.route == CaptureRoute.RESTRICTED
            assert persona in result.reason


class TestPrivilegedModules:
    def test_legal_council_module_routes_to_restricted(self):
        result = classify_for_capture(
            prompt="analyze this contract",
            response="the termination clause is ambiguous",
            source_module="legal_council",
        )
        assert result.route == CaptureRoute.RESTRICTED
        assert "legal_council" in result.reason

    def test_ediscovery_module_routes_to_restricted(self):
        result = classify_for_capture(
            prompt="review these documents",
            response="document 47 is responsive",
            source_module="ediscovery_agent",
        )
        assert result.route == CaptureRoute.RESTRICTED


class TestExplicitMarkers:
    def test_privileged_marker_in_response_routes_to_restricted(self):
        result = classify_for_capture(
            prompt="analyze this",
            response="[PRIVILEGED] this analysis is confidential",
        )
        assert result.route == CaptureRoute.RESTRICTED

    def test_attorney_client_marker_routes_to_restricted(self):
        result = classify_for_capture(
            prompt="review",
            response="ATTORNEY-CLIENT PRIVILEGED communication",
        )
        assert result.route == CaptureRoute.RESTRICTED

    def test_metadata_privilege_marker_routes_to_restricted(self):
        result = classify_for_capture(
            prompt="benign",
            response="benign response",
            metadata={"privilege_marker": True},
        )
        assert result.route == CaptureRoute.RESTRICTED


class TestBlockPatterns:
    def test_ssn_in_prompt_blocks(self):
        result = classify_for_capture(
            prompt="tenant ssn 123-45-6789 applied",
            response="application processed",
        )
        assert result.route == CaptureRoute.BLOCK
        assert "ssn" in result.matched_patterns

    def test_ssn_in_response_blocks(self):
        result = classify_for_capture(
            prompt="look up the tenant",
            response="found record for 987-65-4321",
        )
        assert result.route == CaptureRoute.BLOCK

    def test_credit_card_blocks(self):
        result = classify_for_capture(
            prompt="process this card",
            response="4532-1234-5678-9012 authorized",
        )
        assert result.route == CaptureRoute.BLOCK


class TestAllow:
    def test_generic_prompt_allows(self):
        result = classify_for_capture(
            prompt="what time is checkout",
            response="checkout is at 11am",
            source_persona="concierge_worker",
            source_module="concierge",
        )
        assert result.route == CaptureRoute.ALLOW

    def test_no_context_allows(self):
        result = classify_for_capture(
            prompt="weather today",
            response="sunny, 72 degrees",
        )
        assert result.route == CaptureRoute.ALLOW


class TestBlockTakesPrecedenceOverRestricted:
    def test_ssn_from_legal_persona_still_blocks(self):
        result = classify_for_capture(
            prompt="client ssn is 111-22-3333",
            response="noted",
            source_persona="senior_litigator",
        )
        assert result.route == CaptureRoute.BLOCK


class TestAdminOverride:
    def test_override_to_allow_works(self):
        result = classify_for_capture(
            prompt="anything",
            response="anything",
            source_persona="senior_litigator",
            metadata={"restriction_override": "allow"},
        )
        assert result.route == CaptureRoute.ALLOW
        assert result.reason == "admin_override"
