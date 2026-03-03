"""
The Strangler Pattern Traffic Router

This is the CORE of the migration strategy. It decides:
1. Should this request go to Legacy?
2. Should it go to AI?
3. Should we Shadow (send to both)?

Feature flags control the migration in a safe, incremental way.
"""

import asyncio
from datetime import datetime
from typing import Optional, Tuple
import structlog

from app.core.config import settings
from app.core.interfaces import SMSService, ReservationService, AIService
from app.models.domain import (
    Message,
    MessageResponse,
    MessageIntent,
    Reservation,
    StranglerRouteDecision,
    ShadowResult,
)

logger = structlog.get_logger()


class TrafficRouter:
    """
    Strangler Fig Pattern Router
    
    Routes guest messages between Legacy and AI systems based on feature flags.
    Supports three migration modes:
    1. Pass-through: 100% legacy (safe default)
    2. Shadow: Legacy handles, AI observes (validation phase)
    3. Cutover: AI handles specific intents (incremental migration)
    """

    def __init__(
        self,
        legacy_sms: SMSService,
        legacy_pms: ReservationService,
        ai_service: AIService,
    ):
        self.legacy_sms = legacy_sms
        self.legacy_pms = legacy_pms
        self.ai_service = ai_service
        self.log = logger.bind(service="traffic_router")

    async def route_guest_message(
        self,
        message: Message,
    ) -> Tuple[MessageResponse, StranglerRouteDecision]:
        """
        Main routing logic - The Strangler Pattern in action.
        
        Args:
            message: Incoming guest SMS
            
        Returns:
            Tuple of (MessageResponse sent to guest, Routing decision metadata)
        """
        trace_id = message.trace_id
        log = self.log.bind(trace_id=trace_id, from_phone=message.from_phone)

        log.info("routing_incoming_message", body=message.body[:50])

        # Step 1: Classify intent
        intent = await self._classify_intent(message, trace_id)
        log.info("intent_classified", intent=intent.value)

        # Step 2: Lookup reservation
        reservation = await self._lookup_reservation(message.from_phone, trace_id)
        has_reservation = reservation is not None

        log.info(
            "reservation_lookup_complete",
            found=has_reservation,
            reservation_id=reservation.reservation_id if reservation else None,
        )

        # Step 3: Make routing decision
        decision = self._make_routing_decision(
            intent=intent,
            has_reservation=has_reservation,
            trace_id=trace_id,
        )

        log.info(
            "routing_decision_made",
            route_to=decision.route_to,
            reason=decision.reason,
        )

        # Step 4: Execute routing strategy
        if decision.route_to == "shadow":
            response = await self._execute_shadow_mode(
                message, reservation, intent, trace_id
            )
        elif decision.route_to == "ai":
            response = await self._execute_ai_route(
                message, reservation, intent, trace_id
            )
        else:  # legacy
            response = await self._execute_legacy_route(
                message, reservation, intent, trace_id
            )

        log.info(
            "message_routed_successfully",
            route=decision.route_to,
            response_provider=response.provider,
        )

        return response, decision

    def _make_routing_decision(
        self,
        intent: MessageIntent,
        has_reservation: bool,
        trace_id: str,
    ) -> StranglerRouteDecision:
        """
        The Strangler Pattern Decision Tree
        
        This is where feature flags control the migration.
        """
        now = datetime.now()

        # Capture current feature flag state for audit trail
        flags = {
            "enable_ai_replies": settings.enable_ai_replies,
            "shadow_mode": settings.shadow_mode,
            "ai_intent_filter": settings.ai_intent_filter,
        }

        # Decision Logic
        if settings.shadow_mode:
            # SHADOW MODE: Legacy handles, AI observes (validation phase)
            return StranglerRouteDecision(
                trace_id=trace_id,
                intent=intent,
                route_to="shadow",
                reason="Shadow mode enabled - comparing legacy vs AI responses",
                feature_flags=flags,
                reservation_found=has_reservation,
                timestamp=now,
            )

        if settings.should_use_ai_for_intent(intent.value):
            # CUTOVER MODE: AI handles specific intents
            return StranglerRouteDecision(
                trace_id=trace_id,
                intent=intent,
                route_to="ai",
                reason=f"AI enabled for intent: {intent.value}",
                feature_flags=flags,
                reservation_found=has_reservation,
                timestamp=now,
            )

        # DEFAULT: Pass-through to legacy (safest option)
        return StranglerRouteDecision(
            trace_id=trace_id,
            intent=intent,
            route_to="legacy",
            reason="Default pass-through to legacy system",
            feature_flags=flags,
            reservation_found=has_reservation,
            timestamp=now,
        )

    async def _execute_legacy_route(
        self,
        message: Message,
        reservation: Optional[Reservation],
        intent: MessageIntent,
        trace_id: str,
    ) -> MessageResponse:
        """
        Pure legacy path - no AI involvement.
        """
        log = self.log.bind(trace_id=trace_id, route="legacy")
        log.info("executing_legacy_route")

        # Legacy SMS handler generates response (mock for now)
        response_body = await self._generate_legacy_response(
            message, reservation, intent
        )

        # Send via legacy SMS provider
        response = await self.legacy_sms.send_message(
            phone_number=message.from_phone,
            message_body=response_body,
            trace_id=trace_id,
        )

        log.info("legacy_route_complete", message_id=response.message_id)
        return response

    async def _execute_ai_route(
        self,
        message: Message,
        reservation: Optional[Reservation],
        intent: MessageIntent,
        trace_id: str,
    ) -> MessageResponse:
        """
        AI-powered path - The new system handles the request.
        """
        log = self.log.bind(trace_id=trace_id, route="ai")
        log.info("executing_ai_route")

        # AI generates response
        ai_response = await self.ai_service.generate_response(
            message=message,
            reservation=reservation,
            intent=intent,
            trace_id=trace_id,
        )

        # Send via SMS provider (could be legacy SMS or new provider)
        response = await self.legacy_sms.send_message(
            phone_number=message.from_phone,
            message_body=ai_response.body,
            trace_id=trace_id,
        )

        log.info("ai_route_complete", message_id=response.message_id)
        return response

    async def _execute_shadow_mode(
        self,
        message: Message,
        reservation: Optional[Reservation],
        intent: MessageIntent,
        trace_id: str,
    ) -> MessageResponse:
        """
        Shadow Mode - Send to BOTH legacy and AI, compare results.
        
        Guest receives legacy response (safe), but we log AI's response
        for validation and comparison.
        """
        log = self.log.bind(trace_id=trace_id, route="shadow")
        log.info("executing_shadow_mode")

        # Run both in parallel (non-blocking)
        legacy_task = asyncio.create_task(
            self._execute_legacy_route(message, reservation, intent, trace_id)
        )

        ai_task = asyncio.create_task(
            self._get_ai_shadow_response(message, reservation, intent, trace_id)
        )

        # Wait for both
        legacy_response, ai_response = await asyncio.gather(
            legacy_task, ai_task, return_exceptions=True
        )

        # Handle potential AI failure gracefully
        if isinstance(ai_response, Exception):
            log.warning("ai_shadow_failed", error=str(ai_response))
            ai_response = None

        # Compare responses
        if ai_response:
            shadow_result = self._compare_responses(
                legacy_response, ai_response, trace_id
            )
            log.info(
                "shadow_comparison_complete",
                responses_match=shadow_result.responses_match,
                divergence=shadow_result.divergence_details,
            )
            # TODO: Persist shadow_result to database for analysis

        # ALWAYS return legacy response to guest (safety first)
        return legacy_response

    async def _get_ai_shadow_response(
        self,
        message: Message,
        reservation: Optional[Reservation],
        intent: MessageIntent,
        trace_id: str,
    ) -> MessageResponse:
        """Get AI response without sending to guest (shadow only)"""
        return await self.ai_service.generate_response(
            message=message,
            reservation=reservation,
            intent=intent,
            trace_id=trace_id,
        )

    def _compare_responses(
        self,
        legacy: MessageResponse,
        ai: MessageResponse,
        trace_id: str,
    ) -> ShadowResult:
        """
        Compare Legacy vs AI responses for divergence analysis.
        """
        responses_match = legacy.body.strip() == ai.body.strip()

        divergence = None
        if not responses_match:
            divergence = f"Legacy: '{legacy.body[:100]}...' vs AI: '{ai.body[:100]}...'"

        return ShadowResult(
            trace_id=trace_id,
            legacy_response=legacy,
            ai_response=ai,
            responses_match=responses_match,
            divergence_details=divergence,
            comparison_timestamp=datetime.now(),
        )

    async def _classify_intent(
        self, message: Message, trace_id: str
    ) -> MessageIntent:
        """
        Classify the intent of an incoming message.
        
        For now, delegate to legacy SMS service. Later, could use AI.
        """
        return await self.legacy_sms.classify_intent(message, trace_id)

    async def _lookup_reservation(
        self, phone_number: str, trace_id: str
    ) -> Optional[Reservation]:
        """
        Lookup guest reservation by phone number.
        """
        return await self.legacy_pms.get_reservation_by_phone(phone_number, trace_id)

    async def _generate_legacy_response(
        self,
        message: Message,
        reservation: Optional[Reservation],
        intent: MessageIntent,
    ) -> str:
        """
        Mock legacy response generation.
        
        In production, this would call your existing business logic.
        """
        if not reservation:
            return "We couldn't find a reservation for this number. Please contact support."

        if intent == MessageIntent.WIFI_QUESTION:
            return f"Hi {reservation.guest.first_name}! WiFi password for {reservation.property_name} is: MountainView2024"

        if intent == MessageIntent.ACCESS_CODE_REQUEST:
            # In production: fetch from Streamline VRS
            return f"Your access code for {reservation.property_name} is: 1234"

        return "Thank you for your message. Our team will respond shortly."
