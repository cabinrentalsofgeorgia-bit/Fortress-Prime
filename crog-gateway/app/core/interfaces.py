"""
Hexagonal Architecture - Port Definitions (Abstract Base Classes)

These interfaces define the contracts that all adapters MUST implement.
This allows us to swap implementations without changing business logic.
"""

from abc import ABC, abstractmethod
from typing import Optional
from datetime import datetime

from app.models.domain import (
    Guest,
    Message,
    MessageResponse,
    Reservation,
    AccessCode,
    MessageIntent,
)


class SMSService(ABC):
    """
    Port: SMS Communication Interface
    
    Implementations: RueBaRueAdapter, TwilioAdapter (future), CrogAIAdapter
    """

    @abstractmethod
    async def send_message(
        self,
        phone_number: str,
        message_body: str,
        trace_id: str,
    ) -> MessageResponse:
        """
        Send an SMS to a guest.
        
        Args:
            phone_number: E.164 formatted phone number (+1XXXXXXXXXX)
            message_body: Text content to send
            trace_id: Correlation ID for observability
            
        Returns:
            MessageResponse with status and metadata
            
        Raises:
            SMSDeliveryError: If message cannot be delivered
        """
        pass

    @abstractmethod
    async def receive_message(
        self,
        raw_payload: dict,
        trace_id: str,
    ) -> Message:
        """
        Parse an incoming SMS webhook payload.
        
        Args:
            raw_payload: Vendor-specific webhook body
            trace_id: Correlation ID
            
        Returns:
            Normalized Message object
        """
        pass

    @abstractmethod
    async def classify_intent(
        self,
        message: Message,
        trace_id: str,
    ) -> MessageIntent:
        """
        Determine the intent of an incoming message.
        
        Args:
            message: Parsed message object
            trace_id: Correlation ID
            
        Returns:
            MessageIntent (WIFI_QUESTION, ACCESS_CODE_REQUEST, etc.)
        """
        pass


class ReservationService(ABC):
    """
    Port: Property Management System Interface
    
    Implementations: StreamlineVRSAdapter, GuesthubAdapter (future)
    """

    @abstractmethod
    async def get_reservation_by_phone(
        self,
        phone_number: str,
        trace_id: str,
    ) -> Optional[Reservation]:
        """
        Lookup active reservation by guest phone number.
        
        Args:
            phone_number: Guest's phone (E.164 format)
            trace_id: Correlation ID
            
        Returns:
            Reservation object if found, else None
        """
        pass

    @abstractmethod
    async def get_reservation_by_id(
        self,
        reservation_id: str,
        trace_id: str,
    ) -> Optional[Reservation]:
        """
        Lookup reservation by PMS confirmation code.
        
        Args:
            reservation_id: PMS-specific identifier
            trace_id: Correlation ID
            
        Returns:
            Reservation object if found, else None
        """
        pass

    @abstractmethod
    async def get_access_code(
        self,
        reservation: Reservation,
        trace_id: str,
    ) -> AccessCode:
        """
        Retrieve unit access code (door lock code) for reservation.
        
        Args:
            reservation: The guest's reservation
            trace_id: Correlation ID
            
        Returns:
            AccessCode with code and expiration
            
        Raises:
            AccessCodeNotFoundError: If no code exists
        """
        pass

    @abstractmethod
    async def update_guest_info(
        self,
        reservation_id: str,
        guest_updates: dict,
        trace_id: str,
    ) -> bool:
        """
        Update guest information in the PMS.
        
        Args:
            reservation_id: PMS confirmation code
            guest_updates: Key-value pairs to update
            trace_id: Correlation ID
            
        Returns:
            True if successful
        """
        pass


class AIService(ABC):
    """
    Port: AI-Powered Guest Communication Interface
    
    Implementations: CrogAIAdapter (your internal AI system)
    """

    @abstractmethod
    async def generate_response(
        self,
        message: Message,
        reservation: Optional[Reservation],
        intent: MessageIntent,
        trace_id: str,
    ) -> MessageResponse:
        """
        Generate an AI-powered response to a guest message.
        
        Args:
            message: The incoming guest message
            reservation: Guest's reservation (if found)
            intent: Classified intent
            trace_id: Correlation ID
            
        Returns:
            MessageResponse with AI-generated reply
        """
        pass

    @abstractmethod
    async def handle_intent(
        self,
        intent: MessageIntent,
        reservation: Reservation,
        message: Message,
        trace_id: str,
    ) -> MessageResponse:
        """
        Execute intent-specific AI logic.
        
        Args:
            intent: The classified intent
            reservation: Guest's reservation
            message: Original message
            trace_id: Correlation ID
            
        Returns:
            MessageResponse with action taken
        """
        pass
