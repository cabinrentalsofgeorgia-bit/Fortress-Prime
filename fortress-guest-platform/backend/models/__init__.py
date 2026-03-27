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
from backend.models.knowledge import KnowledgeBaseEntry, PropertyKnowledgeChunk
from backend.models.guest_verification import GuestVerification
from backend.models.guest_review import GuestReview
from backend.models.guest_survey import GuestSurvey, SurveyTemplate
from backend.models.rental_agreement import RentalAgreement, AgreementTemplate
from backend.models.guest_activity import GuestActivity
from backend.models.agent_queue import AgentResponseQueue
from backend.models.ai_insight import AiInsight
from backend.models.damage_claim import DamageClaim
from backend.models.property_utility import PropertyUtility, UtilityReading
from backend.models.staff_invite import StaffInvite
from backend.models.lead import Lead
from backend.models.quote import Quote, QuoteOption
from backend.models.vrs_quotes import GuestQuote, GuestQuoteStatus
from backend.models.blocked_day import BlockedDay
from backend.models.property_stay_restriction import PropertyStayRestriction
from backend.models.reservation_hold import ReservationHold
from backend.models.template import EmailTemplate
from backend.models.message_queue import MessageQueue
from backend.models.seo_patch import SeoPatchQueue, SEORubric, SEOPatch
from backend.models.storefront_intent import StorefrontIntentEvent
from backend.models.storefront_session_guest_link import StorefrontSessionGuestLink
from backend.models.concierge_recovery_dispatch import ConciergeRecoveryDispatch
from backend.models.citation_audit import CitationRecord
from backend.models.concierge_queue import ConciergeQueue
from backend.models.property_knowledge import PropertyKnowledge
from backend.models.pricing import QuoteLineItem, QuoteRequest, QuoteResponse
from backend.models.financial_primitives import Fee, PropertyFee, PropertyTax, Tax
from backend.models.pricing_override import PricingOverride
from backend.models.content import TaxonomyCategory, MarketingArticle
from backend.models.functional_node import FunctionalNode
from backend.vrs.domain.automations import VRSRuleEngine, AutomationEvent
# from backend.services.housekeeping_service import HousekeepingTask
from backend.models.iot_device import DigitalTwin, DeviceEvent
from backend.models.verses import VersesProduct
from backend.models.hunter import HunterQueueEntry, HunterRun
from backend.models.hunter_recovery_op import HunterRecoveryOp, HunterRecoveryOpStatus
from backend.models.legal_graph import LegalCase, CaseGraphNode, CaseGraphEdge
from backend.models.legal_discovery import DiscoveryDraftPack, DiscoveryDraftItem
from backend.models.legal_deposition import DepositionTarget, CrossExamFunnel
from backend.models.legal_phase2 import CaseStatement, SanctionsAlert, JurisdictionRule, HiveMindFeedbackEvent, PrivilegeLog, AiAuditLedger
from backend.models.treasury import (
    CompetitorListing,
    OTAProvider,
    OtaMicroUpdate,
    SeoRankSnapshot,
    YieldOverride,
    YieldSimulation,
)
from backend.models.intelligence_distillation import DistillationQueue, DistillationStatus
from backend.models.intelligence_ledger import IntelligenceLedgerEntry
from backend.models.recovery_parity_comparison import RecoveryParityComparison
from backend.models.rue_bar_rue_legacy_recovery_template import RueBaRueLegacyRecoveryTemplate
from backend.models.openshell_audit import OpenShellAuditLog
from backend.models.deferred_api_write import DeferredApiWrite, DeferredWriteStatus
from backend.models.seo_redirect import SeoRedirect
from backend.models.seo_redirect_remap import SeoRedirectRemapQueue
from backend.models.async_job import AsyncJobRun
from backend.models.vrs_add_on import VRSAddOn, VRSAddOnPricingModel, VRSAddOnScope
from backend.models.media import PropertyImage
from backend.models.swarm_governance import (
    AgentRegistry,
    AgentRun,
    AgentRunStatus,
    Escalation,
    EscalationStatus,
    OperatorOverride,
    OverrideAction,
    TrustDecision,
    TrustDecisionStatus,
)
from backend.models.trust_ledger import (
    TrustAccount,
    TrustAccountType,
    TrustLedgerEntry,
    TrustLedgerEntryType,
    TrustTransaction,
)
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
    "AiInsight",
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
    "PropertyKnowledgeChunk",
    # Lead Engine
    "Lead",
    "Quote",
    "QuoteOption",
    "GuestQuote",
    "GuestQuoteStatus",
    # Calendar / Availability
    "BlockedDay",
    "PropertyStayRestriction",
    "ReservationHold",
    # Templating Engine
    "EmailTemplate",
    # Copilot Queue
    "MessageQueue",
    "QuoteRequest",
    "QuoteLineItem",
    "QuoteResponse",
    "Tax",
    "Fee",
    "PropertyTax",
    "PropertyFee",
    "PricingOverride",
    "TaxonomyCategory",
    "MarketingArticle",
    "FunctionalNode",
    # SEO Queue
    "SeoPatchQueue",
    "SEORubric",
    "SEOPatch",
    "StorefrontIntentEvent",
    "StorefrontSessionGuestLink",
    "ConciergeRecoveryDispatch",
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
    "HunterRecoveryOp",
    "HunterRecoveryOpStatus",
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
    "OTAProvider",
    "CompetitorListing",
    # Intelligence Distillation
    "DistillationQueue",
    "DistillationStatus",
    "IntelligenceLedgerEntry",
    "RecoveryParityComparison",
    "RueBaRueLegacyRecoveryTemplate",
    "OpenShellAuditLog",
    "DeferredApiWrite",
    "DeferredWriteStatus",
    "SeoRedirect",
    "SeoRedirectRemapQueue",
    "AsyncJobRun",
    "VRSAddOn",
    "VRSAddOnPricingModel",
    "VRSAddOnScope",
    "PropertyImage",
    "AgentRegistry",
    "AgentRun",
    "AgentRunStatus",
    "TrustDecision",
    "TrustDecisionStatus",
    "Escalation",
    "EscalationStatus",
    "OperatorOverride",
    "OverrideAction",
    "TrustAccount",
    "TrustAccountType",
    "TrustTransaction",
    "TrustLedgerEntry",
    "TrustLedgerEntryType",
]
