"""
SQLAlchemy Models for Fortress Guest Platform
Enterprise-grade vacation rental management system
"""
from backend.models.guest import Guest
from backend.models.property import Property
from backend.models.reservation import Reservation
from backend.models.message import Message, MessageTemplate, ScheduledMessage
from backend.models.workorder import WorkOrder
from backend.models.guestbook import GuestbookGuide, Extra, ExtraOrder
from backend.models.analytics import AnalyticsEvent
from backend.models.staff import StaffUser
from backend.models.knowledge import KnowledgeBaseEntry
from backend.models.guest_verification import GuestVerification
from backend.models.guest_review import GuestReview
from backend.models.guest_survey import GuestSurvey, SurveyTemplate
from backend.models.rental_agreement import RentalAgreement, AgreementTemplate
from backend.models.guest_activity import GuestActivity
from backend.models.agent_queue import AgentResponseQueue
from backend.models.damage_claim import DamageClaim
from backend.models.property_utility import PropertyUtility, UtilityReading
from backend.models.staff_invite import StaffInvite
from backend.models.lead import Lead
from backend.models.quote import Quote, QuoteOption
from backend.models.blocked_day import BlockedDay
from backend.models.template import EmailTemplate
from backend.models.message_queue import MessageQueue
from backend.vrs.domain.automations import VRSRuleEngine, AutomationEvent
from backend.services.housekeeping_service import HousekeepingTask
from backend.models.iot_device import DigitalTwin, DeviceEvent
from backend.models.verses import VersesProduct

__all__ = [
    # Core
    "Guest",
    "Property",
    "Reservation",
    # Communication
    "Message",
    "MessageTemplate",
    "ScheduledMessage",
    # Operations
    "WorkOrder",
    "HousekeepingTask",
    # Guest Experience
    "GuestbookGuide",
    "Extra",
    "ExtraOrder",
    # Guest Management
    "GuestVerification",
    "GuestReview",
    "GuestSurvey",
    "SurveyTemplate",
    "RentalAgreement",
    "AgreementTemplate",
    "GuestActivity",
    # AI Agent
    "AgentResponseQueue",
    # Damage / Legal
    "DamageClaim",
    # Utilities / Services
    "PropertyUtility",
    "UtilityReading",
    # Analytics & Admin
    "AnalyticsEvent",
    "StaffUser",
    "StaffInvite",
    "KnowledgeBaseEntry",
    # Lead Engine
    "Lead",
    "Quote",
    "QuoteOption",
    # Calendar / Availability
    "BlockedDay",
    # Templating Engine
    "EmailTemplate",
    # Copilot Queue
    "MessageQueue",
    # Rule Engine
    "VRSRuleEngine",
    "AutomationEvent",
    # Digital Twins (IoT)
    "DigitalTwin",
    "DeviceEvent",
    # Verses in Bloom (E-Commerce)
    "VersesProduct",
]
