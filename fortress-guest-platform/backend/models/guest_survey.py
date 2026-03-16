"""
Guest Survey model - Structured feedback collection
SURPASSES: Streamline's basic surveys, RueBaRue's limited survey tool

Features:
- Configurable survey templates (multiple question types)
- Pre-stay, mid-stay, and post-stay surveys
- NPS (Net Promoter Score) tracking
- Operational insights (housekeeping, maintenance, amenities)
- Response analytics and trend detection
- Auto-generated improvement recommendations
"""
from datetime import datetime
from uuid import uuid4
from sqlalchemy import Column, String, Boolean, Integer, DECIMAL, Text, TIMESTAMP, ForeignKey
from sqlalchemy.dialects.postgresql import UUID, JSONB
from sqlalchemy.orm import relationship

from backend.core.database import Base


class SurveyTemplate(Base):
    """Reusable survey template"""
    
    __tablename__ = "survey_templates"
    
    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid4)
    
    name = Column(String(255), nullable=False, unique=True)
    description = Column(Text)
    survey_type = Column(String(50), nullable=False, index=True)
    # post_stay, mid_stay, pre_stay, nps, operational, custom
    
    # Questions structure
    questions = Column(JSONB, nullable=False)
    # [
    #   {
    #     "id": "q1",
    #     "type": "rating",  # rating, text, multiple_choice, yes_no, nps, scale
    #     "question": "How would you rate your overall stay?",
    #     "required": true,
    #     "options": null,  # for multiple_choice
    #     "scale_min": 1, "scale_max": 5,  # for rating/scale
    #     "category": "overall"  # for grouping
    #   },
    #   {
    #     "id": "q2",
    #     "type": "nps",
    #     "question": "How likely are you to recommend us? (0-10)",
    #     "required": true,
    #     "scale_min": 0, "scale_max": 10,
    #     "category": "nps"
    #   },
    #   {
    #     "id": "q3",
    #     "type": "multiple_choice",
    #     "question": "What was the highlight of your stay?",
    #     "options": ["Hot tub", "Views", "Fireplace", "Location", "Cleanliness", "Other"],
    #     "allow_multiple": true,
    #     "category": "highlights"
    #   }
    # ]
    
    # Trigger settings
    trigger_type = Column(String(50))  # auto_post_checkout, auto_mid_stay, manual
    trigger_offset_hours = Column(Integer)  # hours after checkout to send
    send_method = Column(String(20), default="sms")  # sms, email, both
    
    # Status
    is_active = Column(Boolean, default=True, index=True)
    usage_count = Column(Integer, default=0)
    avg_completion_rate = Column(DECIMAL(5, 2))  # percentage
    
    created_at = Column(TIMESTAMP, default=datetime.utcnow)
    updated_at = Column(TIMESTAMP, default=datetime.utcnow, onupdate=datetime.utcnow)
    
    # Relationships
    responses = relationship("GuestSurvey", back_populates="template")
    
    def __repr__(self) -> str:
        return f"<SurveyTemplate {self.name}>"


class GuestSurvey(Base):
    """Individual guest survey response"""
    
    __tablename__ = "guest_surveys"
    
    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid4)
    
    # Context
    guest_id = Column(UUID(as_uuid=True), ForeignKey("guests.id", ondelete="CASCADE"), nullable=False, index=True)
    reservation_id = Column(UUID(as_uuid=True), ForeignKey("reservations.id", ondelete="SET NULL"), index=True)
    property_id = Column(UUID(as_uuid=True), ForeignKey("properties.id", ondelete="SET NULL"), index=True)
    template_id = Column(UUID(as_uuid=True), ForeignKey("survey_templates.id", ondelete="SET NULL"), index=True)
    
    # Survey Type
    survey_type = Column(String(50), nullable=False, index=True)
    
    # Responses (structured)
    responses = Column(JSONB, nullable=False)
    # {
    #   "q1": {"value": 4, "type": "rating"},
    #   "q2": {"value": 9, "type": "nps"},
    #   "q3": {"value": ["Hot tub", "Views"], "type": "multiple_choice"},
    #   "q4": {"value": "Amazing cabin, loved the views!", "type": "text"}
    # }
    
    # Computed Scores
    overall_score = Column(DECIMAL(4, 2))  # Weighted average of ratings
    nps_score = Column(Integer)  # 0-10 NPS response
    
    # NPS Classification
    nps_category = Column(String(20))  # promoter (9-10), passive (7-8), detractor (0-6)
    
    # Operational Insights
    housekeeping_score = Column(Integer)  # Extracted from relevant questions
    maintenance_score = Column(Integer)
    communication_score = Column(Integer)
    amenities_score = Column(Integer)
    
    # AI Analysis
    sentiment = Column(String(20))
    key_themes = Column(JSONB)  # ["cleanliness", "views", "hot_tub_issue"]
    action_items = Column(JSONB)  # AI-generated improvement tasks
    
    # Status
    status = Column(String(30), nullable=False, default="pending", index=True)
    # pending, sent, started, completed, expired
    
    sent_at = Column(TIMESTAMP)
    started_at = Column(TIMESTAMP)
    completed_at = Column(TIMESTAMP)
    send_method = Column(String(20))  # sms, email
    survey_url = Column(Text)  # Unique survey link
    
    # Follow-up
    follow_up_required = Column(Boolean, default=False)
    follow_up_notes = Column(Text)
    follow_up_completed_at = Column(TIMESTAMP)
    follow_up_by = Column(String(100))
    
    created_at = Column(TIMESTAMP, default=datetime.utcnow)
    updated_at = Column(TIMESTAMP, default=datetime.utcnow, onupdate=datetime.utcnow)
    
    # Relationships
    guest = relationship("Guest", back_populates="surveys")
    template = relationship("SurveyTemplate", back_populates="responses")
    
    @property
    def is_completed(self) -> bool:
        return self.status == "completed"
    
    @property
    def is_nps_promoter(self) -> bool:
        return self.nps_score is not None and self.nps_score >= 9
    
    @property
    def is_nps_detractor(self) -> bool:
        return self.nps_score is not None and self.nps_score <= 6
    
    def __repr__(self) -> str:
        return f"<GuestSurvey {self.survey_type} score={self.overall_score}>"
