"""
Unit tests for TrafficRouter (Strangler Pattern logic)

Tests the core routing decisions based on feature flags.
"""

import pytest
from datetime import datetime
from unittest.mock import AsyncMock, MagicMock

from app.services.router import TrafficRouter
from app.models.domain import (
    Message,
    MessageIntent,
    MessageResponse,
    MessageStatus,
    Guest,
    Reservation,
)
from app.core.config import settings


@pytest.fixture
def mock_sms_service():
    """Mock SMS service adapter"""
    service = AsyncMock()
    service.send_message.return_value = MessageResponse(
        message_id="msg_123",
        status=MessageStatus.SENT,
        body="Test message",
        sent_at=datetime.now(),
        trace_id="trace_123",
        provider="ruebarue",
    )
    service.classify_intent.return_value = MessageIntent.WIFI_QUESTION
    return service


@pytest.fixture
def mock_pms_service():
    """Mock PMS service adapter"""
    service = AsyncMock()

    guest = Guest(
        guest_id="guest_123",
        first_name="John",
        last_name="Smith",
        phone_number="+15551234567",
    )

    reservation = Reservation(
        reservation_id="RES123",
        guest=guest,
        property_name="Blue Ridge Cabin",
        unit_id="UNIT001",
        checkin_date=datetime(2024, 1, 15, 16, 0),
        checkout_date=datetime(2024, 1, 20, 11, 0),
        status="confirmed",
        created_at=datetime.now(),
        updated_at=datetime.now(),
    )

    service.get_reservation_by_phone.return_value = reservation
    return service


@pytest.fixture
def mock_ai_service():
    """Mock AI service adapter"""
    service = AsyncMock()
    service.generate_response.return_value = MessageResponse(
        message_id="msg_ai_123",
        status=MessageStatus.SENT,
        body="AI-generated response",
        sent_at=datetime.now(),
        trace_id="trace_123",
        provider="crog_ai",
    )
    return service


@pytest.fixture
def traffic_router(mock_sms_service, mock_pms_service, mock_ai_service):
    """Traffic router with mocked adapters"""
    return TrafficRouter(
        legacy_sms=mock_sms_service,
        legacy_pms=mock_pms_service,
        ai_service=mock_ai_service,
    )


@pytest.fixture
def sample_message():
    """Sample incoming guest message"""
    return Message(
        message_id="msg_incoming_123",
        from_phone="+15551234567",
        to_phone="+15559876543",
        body="What is the WiFi password?",
        received_at=datetime.now(),
        trace_id="trace_123",
    )


@pytest.mark.asyncio
async def test_pass_through_mode(traffic_router, sample_message, monkeypatch):
    """
    Test Pass-through Mode (default): Legacy handles all requests
    """
    # Configure feature flags
    monkeypatch.setattr(settings, "enable_ai_replies", False)
    monkeypatch.setattr(settings, "shadow_mode", False)

    response, decision = await traffic_router.route_guest_message(sample_message)

    # Assertions
    assert decision.route_to == "legacy"
    assert decision.reason == "Default pass-through to legacy system"
    assert response.provider == "ruebarue"


@pytest.mark.asyncio
async def test_shadow_mode(traffic_router, sample_message, monkeypatch):
    """
    Test Shadow Mode: Legacy handles, AI observes
    """
    # Configure feature flags
    monkeypatch.setattr(settings, "enable_ai_replies", False)
    monkeypatch.setattr(settings, "shadow_mode", True)

    response, decision = await traffic_router.route_guest_message(sample_message)

    # Assertions
    assert decision.route_to == "shadow"
    assert "Shadow mode enabled" in decision.reason
    assert response.provider == "ruebarue"  # Guest receives legacy response

    # Verify both services were called
    traffic_router.legacy_sms.send_message.assert_called_once()
    traffic_router.ai_service.generate_response.assert_called_once()


@pytest.mark.asyncio
async def test_ai_cutover_mode(traffic_router, sample_message, monkeypatch):
    """
    Test AI Cutover Mode: AI handles specific intents
    """
    # Configure feature flags
    monkeypatch.setattr(settings, "enable_ai_replies", True)
    monkeypatch.setattr(settings, "shadow_mode", False)
    monkeypatch.setattr(settings, "ai_intent_filter", ["WIFI_QUESTION"])

    response, decision = await traffic_router.route_guest_message(sample_message)

    # Assertions
    assert decision.route_to == "ai"
    assert "AI enabled for intent" in decision.reason
    # Note: Response provider is still "ruebarue" because SMS is sent via legacy provider


@pytest.mark.asyncio
async def test_intent_filtering(traffic_router, sample_message, monkeypatch):
    """
    Test AI Intent Filter: AI handles ONLY specified intents
    """
    # Configure: AI enabled only for WiFi questions
    monkeypatch.setattr(settings, "enable_ai_replies", True)
    monkeypatch.setattr(settings, "shadow_mode", False)
    monkeypatch.setattr(settings, "ai_intent_filter", ["WIFI_QUESTION"])

    # Mock: Classify as ACCESS_CODE_REQUEST (not in filter)
    traffic_router.legacy_sms.classify_intent.return_value = (
        MessageIntent.ACCESS_CODE_REQUEST
    )

    response, decision = await traffic_router.route_guest_message(sample_message)

    # Should fall back to legacy
    assert decision.route_to == "legacy"
