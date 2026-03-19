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
from backend.models.vrs_quotes import GuestQuote, GuestQuoteStatus
from backend.models.blocked_day import BlockedDay
from backend.models.template import EmailTemplate
from backend.models.message_queue import MessageQueue
from backend.models.seo_patch import SeoPatchQueue
from backend.models.citation_audit import CitationRecord
from backend.models.concierge_queue import ConciergeQueue
from backend.models.property_knowledge import PropertyKnowledge
from backend.vrs.domain.automations import VRSRuleEngine, AutomationEvent
# from backend.services.housekeeping_service import HousekeepingTask
from backend.models.iot_device import DigitalTwin, DeviceEvent
from backend.models.verses import VersesProduct
from backend.models.hunter import HunterQueueEntry, HunterRun
from backend.models.legal_graph import LegalCase, CaseGraphNode, CaseGraphEdge
from backend.models.legal_discovery import DiscoveryDraftPack, DiscoveryDraftItem
from backend.models.legal_deposition import DepositionTarget, CrossExamFunnel
from backend.models.legal_phase2 import CaseStatement, SanctionsAlert, JurisdictionRule, HiveMindFeedbackEvent, PrivilegeLog, AiAuditLedger
from backend.models.treasury import YieldSimulation, YieldOverride, SeoRankSnapshot, OtaMicroUpdate
from backend.models.intelligence_distillation import DistillationQueue, DistillationStatus
from backend.models.legal import (
    LegalEntity,
    CaseEvidence,
    TimelineEvent,
    DistillationMemory,
    CaseGraphNode as CaseGraphNodeV2,
    CaseGraphEdge as CaseGraphEdgeV2,
    SanctionsAlert as SanctionsAlertV2,
    SanctionsTripwireRun as SanctionsTripwireRunV2,
    CaseStatement as CaseStatementV2,
    DepositionKillSheet as DepositionKillSheetV2,
    LegalExemplar,
)

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
    # "HousekeepingTask",
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
    "GuestQuote",
    "GuestQuoteStatus",
    # Calendar / Availability
    "BlockedDay",
    # Templating Engine
    "EmailTemplate",
    # Copilot Queue
    "MessageQueue",
    # SEO Queue
    "SeoPatchQueue",
    # Local SEO Citation Audits
    "CitationRecord",
    # Concierge queue / RAG memory
    "ConciergeQueue",
    "PropertyKnowledge",
    # Rule Engine
    "VRSRuleEngine",
    "AutomationEvent",
    # Digital Twins (IoT)
    "DigitalTwin",
    "DeviceEvent",
    # Verses in Bloom (E-Commerce)
    "VersesProduct",
    # Hunter queue
    "HunterQueueEntry",
    "HunterRun",
    # Legal graph/discovery
    "LegalCase",
    "CaseGraphNode",
    "CaseGraphEdge",
    "DiscoveryDraftPack",
    "DiscoveryDraftItem",
    "DepositionTarget",
    "CrossExamFunnel",
    # Legal Phase 2
    "CaseStatement",
    "SanctionsAlert",
    "JurisdictionRule",
    "HiveMindFeedbackEvent",
    "PrivilegeLog",
    "AiAuditLedger",
    "LegalEntity",
    "CaseEvidence",
    "TimelineEvent",
    "DistillationMemory",
    "CaseGraphNodeV2",
    "CaseGraphEdgeV2",
    "SanctionsAlertV2",
    "SanctionsTripwireRunV2",
    "CaseStatementV2",
    "DepositionKillSheetV2",
    "LegalExemplar",
    # Treasury
    "YieldSimulation",
    "YieldOverride",
    "SeoRankSnapshot",
    "OtaMicroUpdate",
    # Intelligence Distillation
    "DistillationQueue",
    "DistillationStatus",
]
