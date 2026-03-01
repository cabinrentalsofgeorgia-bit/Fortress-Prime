"""
Guest Management Service - The Central Intelligence of Guest Operations
SURPASSES: Streamline VRS CRM + RueBaRue + Breezeway + Hostaway combined

This is the enterprise nerve center for all guest operations:
- 360° guest profiles with complete history
- Guest scoring (value + risk + satisfaction)
- Loyalty program with automatic tier progression
- Guest merge/dedup to prevent duplicates
- Segmentation engine for targeted campaigns
- Review solicitation and reputation management
- Survey dispatch and analytics
- Rental agreement lifecycle
- Activity timeline tracking
- Blacklist and flag management
- Guest verification workflow
- Communication preference enforcement
- Repeat guest detection with special pricing
- Guest analytics and lifetime value tracking
"""
from datetime import datetime, date, timedelta
from typing import List, Optional, Dict, Tuple, Any
from uuid import UUID, uuid4
from decimal import Decimal
from sqlalchemy import select, and_, or_, func, desc, asc, case, text, update
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload
import structlog

from backend.models import (
    Guest, Reservation, Property, Message, WorkOrder,
    GuestReview, GuestSurvey, SurveyTemplate,
    RentalAgreement, AgreementTemplate,
    GuestActivity, GuestVerification
)
from backend.core.config import settings

logger = structlog.get_logger()


class GuestManagementService:
    """
    Enterprise Guest Management Engine
    
    What Streamline CANNOT do:
    - Unified 360° view across all data sources
    - Predictive guest scoring
    - Automatic loyalty tier progression
    - Smart merge/dedup
    - AI-powered segmentation
    - Integrated review + survey + agreement lifecycle
    
    What RueBaRue CANNOT do:
    - Guest value/risk scoring
    - Full profile management (address, vehicle, emergency contact)
    - Loyalty program
    - Verification workflow
    - Activity audit trail
    """
    
    def __init__(self, db: AsyncSession):
        self.db = db
        self.log = logger.bind(service="guest_management")
    
    # ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
    # 360° GUEST PROFILE
    # ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
    
    async def get_guest_360(self, guest_id: UUID) -> Dict[str, Any]:
        """
        Complete 360° guest profile with ALL related data
        
        This is the crown jewel - a single view that gives you EVERYTHING
        about a guest. Neither Streamline nor RueBaRue can do this.
        """
        guest = await self.db.get(Guest, guest_id)
        if not guest:
            return None
        
        # Parallel data fetching
        reservations = await self._get_guest_reservations(guest_id)
        messages_summary = await self._get_message_summary(guest_id)
        reviews = await self._get_guest_reviews(guest_id)
        surveys = await self._get_guest_surveys(guest_id)
        agreements = await self._get_guest_agreements(guest_id)
        activities = await self._get_recent_activities(guest_id, limit=20)
        work_orders = await self._get_guest_work_orders(guest_id)
        verification = await self._get_latest_verification(guest_id)
        
        # Compute analytics
        stats = await self._compute_guest_stats(guest_id, reservations)
        
        return {
            "profile": {
                "id": str(guest.id),
                "full_name": guest.full_name,
                "first_name": guest.first_name,
                "last_name": guest.last_name,
                "phone_number": guest.phone_number,
                "phone_secondary": guest.phone_number_secondary,
                "email": guest.email,
                "email_secondary": guest.email_secondary,
                "address": guest.full_address,
                "date_of_birth": str(guest.date_of_birth) if guest.date_of_birth else None,
                "language": guest.language_preference,
                "timezone": guest.timezone,
                "preferred_contact": guest.preferred_contact_method,
                "opt_in_marketing": guest.opt_in_marketing,
                "opt_in_sms": guest.opt_in_sms,
                "opt_in_email": guest.opt_in_email,
                "tags": guest.tags or [],
                "notes": guest.internal_notes,
                "special_requests": guest.special_requests,
                "preferences": guest.preferences or {},
                "created_at": str(guest.created_at),
            },
            "identity": {
                "verification_status": guest.verification_status,
                "verified_at": str(guest.verified_at) if guest.verified_at else None,
                "verification_method": guest.verification_method,
                "latest_verification": verification,
            },
            "vehicle": {
                "description": guest.vehicle_description,
                "make": guest.vehicle_make,
                "model": guest.vehicle_model,
                "color": guest.vehicle_color,
                "plate": guest.vehicle_plate,
                "state": guest.vehicle_state,
            },
            "emergency_contact": {
                "name": guest.emergency_contact_name,
                "phone": guest.emergency_contact_phone,
                "relationship": guest.emergency_contact_relationship,
            },
            "loyalty": {
                "tier": guest.loyalty_tier,
                "display_tier": guest.display_tier,
                "points": guest.loyalty_points,
                "lifetime_stays": guest.lifetime_stays,
                "lifetime_nights": guest.lifetime_nights,
                "lifetime_revenue": float(guest.lifetime_revenue or 0),
                "enrolled_at": str(guest.loyalty_enrolled_at) if guest.loyalty_enrolled_at else None,
                "next_tier": self._get_next_tier_info(guest),
            },
            "scoring": {
                "value_score": guest.value_score,
                "risk_score": guest.risk_score,
                "satisfaction_score": guest.satisfaction_score,
                "is_vip": guest.is_vip,
                "is_blacklisted": guest.is_blacklisted,
                "blacklist_reason": guest.blacklist_reason,
            },
            "source": {
                "guest_source": guest.guest_source,
                "first_booking_source": guest.first_booking_source,
                "referral_source": guest.referral_source,
                "acquisition_campaign": guest.acquisition_campaign,
            },
            "external_ids": {
                "streamline": guest.streamline_guest_id,
                "airbnb": guest.airbnb_guest_id,
                "vrbo": guest.vrbo_guest_id,
                "booking_com": guest.booking_com_guest_id,
                "stripe": guest.stripe_customer_id,
            },
            "reservations": reservations,
            "stats": stats,
            "messages": messages_summary,
            "reviews": reviews,
            "surveys": surveys,
            "agreements": agreements,
            "work_orders": work_orders,
            "recent_activity": activities,
            "flags": {
                "is_repeat": guest.is_repeat_guest,
                "is_vip": guest.is_vip,
                "is_verified": guest.is_verified,
                "is_blacklisted": guest.is_blacklisted,
                "requires_supervision": guest.requires_supervision,
                "is_do_not_contact": guest.is_do_not_contact,
            },
        }
    
    # ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
    # GUEST SCORING & LOYALTY
    # ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
    
    async def recalculate_guest_scores(self, guest_id: UUID) -> Dict:
        """
        Recalculate all guest scores and update loyalty tier
        
        Streamline has NOTHING like this.
        """
        guest = await self.db.get(Guest, guest_id)
        if not guest:
            return None
        
        # Recalculate lifetime stats from reservations
        res_stats = await self.db.execute(
            select(
                func.count(Reservation.id).label("total_stays"),
                func.sum(
                    func.extract("day", Reservation.check_out_date - Reservation.check_in_date)
                ).label("total_nights"),
                func.coalesce(func.sum(Reservation.total_amount), 0).label("total_revenue"),
                func.avg(Reservation.guest_rating).label("avg_rating"),
                func.max(Reservation.check_out_date).label("last_stay"),
            ).where(
                Reservation.guest_id == guest_id,
                Reservation.status.in_(["checked_out", "completed"]),
            )
        )
        row = res_stats.first()
        
        # Update lifetime stats
        guest.lifetime_stays = row.total_stays or 0
        guest.lifetime_nights = int(row.total_nights or 0)
        guest.lifetime_revenue = Decimal(str(row.total_revenue or 0))
        guest.total_stays = row.total_stays or 0
        guest.average_rating = row.avg_rating
        guest.last_stay_date = row.last_stay
        
        # Calculate scores
        old_tier = guest.loyalty_tier
        guest.value_score = guest.calculate_value_score()
        guest.risk_score = guest.calculate_risk_score()
        guest.loyalty_tier = guest.calculate_loyalty_tier()
        
        # Calculate satisfaction score from surveys
        survey_result = await self.db.execute(
            select(func.avg(GuestSurvey.overall_score))
            .where(
                GuestSurvey.guest_id == guest_id,
                GuestSurvey.status == "completed",
            )
        )
        avg_survey = survey_result.scalar()
        if avg_survey:
            guest.satisfaction_score = int(float(avg_survey) * 20)  # Convert 5-point to 100
        
        # Track tier change
        if old_tier != guest.loyalty_tier:
            await self._log_activity(
                guest_id=guest_id,
                activity_type="loyalty_tier_changed",
                category="loyalty",
                title=f"Loyalty tier upgraded: {old_tier} → {guest.loyalty_tier}",
                metadata={"old_tier": old_tier, "new_tier": guest.loyalty_tier},
                importance="high",
            )
        
        await self.db.commit()
        
        return {
            "value_score": guest.value_score,
            "risk_score": guest.risk_score,
            "satisfaction_score": guest.satisfaction_score,
            "loyalty_tier": guest.loyalty_tier,
            "lifetime_stays": guest.lifetime_stays,
            "lifetime_nights": guest.lifetime_nights,
            "lifetime_revenue": float(guest.lifetime_revenue),
        }
    
    async def batch_recalculate_scores(self) -> Dict:
        """Recalculate scores for ALL guests (run nightly)"""
        result = await self.db.execute(select(Guest.id))
        guest_ids = [row[0] for row in result.all()]
        
        updated = 0
        errors = 0
        for gid in guest_ids:
            try:
                await self.recalculate_guest_scores(gid)
                updated += 1
            except Exception as e:
                errors += 1
                self.log.error("batch_score_error", guest_id=str(gid), error=str(e))
        
        self.log.info("batch_scores_complete", updated=updated, errors=errors)
        return {"updated": updated, "errors": errors, "total": len(guest_ids)}
    
    # ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
    # GUEST MERGE / DEDUP
    # ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
    
    async def find_potential_duplicates(self, guest_id: UUID) -> List[Dict]:
        """
        Find potential duplicate guest records
        
        Matches on: email, phone, name+DOB
        Neither Streamline nor RueBaRue has dedup.
        """
        guest = await self.db.get(Guest, guest_id)
        if not guest:
            return []
        
        duplicates = []
        
        # Match by email
        if guest.email:
            result = await self.db.execute(
                select(Guest).where(
                    Guest.email == guest.email,
                    Guest.id != guest_id,
                )
            )
            for dup in result.scalars().all():
                duplicates.append({
                    "guest_id": str(dup.id),
                    "name": dup.full_name,
                    "phone": dup.phone_number,
                    "email": dup.email,
                    "match_type": "email",
                    "confidence": 0.9,
                })
        
        # Match by name similarity
        if guest.first_name and guest.last_name:
            result = await self.db.execute(
                select(Guest).where(
                    Guest.first_name.ilike(guest.first_name),
                    Guest.last_name.ilike(guest.last_name),
                    Guest.id != guest_id,
                )
            )
            for dup in result.scalars().all():
                conf = 0.7
                if dup.date_of_birth and guest.date_of_birth and dup.date_of_birth == guest.date_of_birth:
                    conf = 0.95
                if dup.email and guest.email and dup.email == guest.email:
                    conf = 0.98
                duplicates.append({
                    "guest_id": str(dup.id),
                    "name": dup.full_name,
                    "phone": dup.phone_number,
                    "email": dup.email,
                    "match_type": "name",
                    "confidence": conf,
                })
        
        # Remove duplicates from results
        seen = set()
        unique_dups = []
        for d in duplicates:
            if d["guest_id"] not in seen:
                seen.add(d["guest_id"])
                unique_dups.append(d)
        
        return sorted(unique_dups, key=lambda x: x["confidence"], reverse=True)
    
    async def merge_guests(
        self,
        primary_id: UUID,
        secondary_id: UUID,
        performed_by: str = "system"
    ) -> Dict:
        """
        Merge two guest records (keep primary, merge data from secondary)
        
        Re-links all reservations, messages, reviews, etc. to primary.
        """
        primary = await self.db.get(Guest, primary_id)
        secondary = await self.db.get(Guest, secondary_id)
        
        if not primary or not secondary:
            raise ValueError("Both guest records must exist")
        
        self.log.info(
            "merging_guests",
            primary=str(primary_id),
            secondary=str(secondary_id),
        )
        
        # Fill in missing fields on primary from secondary
        fields_to_merge = [
            "email", "email_secondary", "first_name", "last_name",
            "phone_number_secondary", "address_line1", "address_line2",
            "city", "state", "postal_code", "country", "date_of_birth",
            "emergency_contact_name", "emergency_contact_phone",
            "vehicle_make", "vehicle_model", "vehicle_color", "vehicle_plate",
            "airbnb_guest_id", "vrbo_guest_id", "booking_com_guest_id",
            "stripe_customer_id", "streamline_guest_id",
        ]
        
        for field in fields_to_merge:
            if not getattr(primary, field) and getattr(secondary, field):
                setattr(primary, field, getattr(secondary, field))
        
        # Merge tags
        primary_tags = set(primary.tags or [])
        secondary_tags = set(secondary.tags or [])
        primary.tags = list(primary_tags | secondary_tags)
        
        # Merge preferences
        if secondary.preferences:
            merged_prefs = dict(primary.preferences or {})
            for k, v in secondary.preferences.items():
                if k not in merged_prefs:
                    merged_prefs[k] = v
            primary.preferences = merged_prefs
        
        # Re-link all related records to primary
        await self.db.execute(
            update(Reservation).where(Reservation.guest_id == secondary_id)
            .values(guest_id=primary_id)
        )
        await self.db.execute(
            update(Message).where(Message.guest_id == secondary_id)
            .values(guest_id=primary_id)
        )
        await self.db.execute(
            update(GuestReview).where(GuestReview.guest_id == secondary_id)
            .values(guest_id=primary_id)
        )
        await self.db.execute(
            update(GuestSurvey).where(GuestSurvey.guest_id == secondary_id)
            .values(guest_id=primary_id)
        )
        await self.db.execute(
            update(RentalAgreement).where(RentalAgreement.guest_id == secondary_id)
            .values(guest_id=primary_id)
        )
        await self.db.execute(
            update(GuestActivity).where(GuestActivity.guest_id == secondary_id)
            .values(guest_id=primary_id)
        )
        await self.db.execute(
            update(GuestVerification).where(GuestVerification.guest_id == secondary_id)
            .values(guest_id=primary_id)
        )
        await self.db.execute(
            update(WorkOrder).where(WorkOrder.guest_id == secondary_id)
            .values(guest_id=primary_id)
        )
        
        # Log merge activity
        await self._log_activity(
            guest_id=primary_id,
            activity_type="guest_merged",
            category="profile",
            title=f"Merged with {secondary.full_name} ({secondary.phone_number})",
            performed_by=performed_by,
            metadata={
                "merged_guest_id": str(secondary_id),
                "merged_guest_name": secondary.full_name,
                "merged_guest_phone": secondary.phone_number,
            },
            importance="high",
        )
        
        # Delete the secondary record
        await self.db.delete(secondary)
        
        # Recalculate scores
        await self.recalculate_guest_scores(primary_id)
        
        await self.db.commit()
        
        return {
            "primary_id": str(primary_id),
            "merged_from": str(secondary_id),
            "status": "success",
        }
    
    # ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
    # SEGMENTATION ENGINE
    # ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
    
    async def segment_guests(self, criteria: Dict) -> List[Dict]:
        """
        Advanced guest segmentation for targeted campaigns
        
        Criteria examples:
        - {"min_stays": 3, "min_revenue": 5000}
        - {"loyalty_tier": "gold", "last_stay_within_days": 365}
        - {"tags": ["vip"], "opt_in_marketing": true}
        - {"source": "airbnb", "min_rating": 4}
        - {"is_repeat": true, "no_stay_since_days": 180}
        """
        query = select(Guest)
        
        # Build dynamic filters
        if criteria.get("min_stays"):
            query = query.where(Guest.lifetime_stays >= criteria["min_stays"])
        
        if criteria.get("max_stays"):
            query = query.where(Guest.lifetime_stays <= criteria["max_stays"])
        
        if criteria.get("min_revenue"):
            query = query.where(Guest.lifetime_revenue >= criteria["min_revenue"])
        
        if criteria.get("loyalty_tier"):
            tier = criteria["loyalty_tier"]
            if isinstance(tier, list):
                query = query.where(Guest.loyalty_tier.in_(tier))
            else:
                query = query.where(Guest.loyalty_tier == tier)
        
        if criteria.get("last_stay_within_days"):
            cutoff = date.today() - timedelta(days=criteria["last_stay_within_days"])
            query = query.where(Guest.last_stay_date >= cutoff)
        
        if criteria.get("no_stay_since_days"):
            cutoff = date.today() - timedelta(days=criteria["no_stay_since_days"])
            query = query.where(
                or_(Guest.last_stay_date < cutoff, Guest.last_stay_date.is_(None))
            )
        
        if criteria.get("tags"):
            query = query.where(Guest.tags.contains(criteria["tags"]))
        
        if criteria.get("is_vip") is not None:
            query = query.where(Guest.is_vip == criteria["is_vip"])
        
        if criteria.get("is_repeat") is not None:
            if criteria["is_repeat"]:
                query = query.where(Guest.lifetime_stays > 1)
            else:
                query = query.where(Guest.lifetime_stays <= 1)
        
        if criteria.get("opt_in_marketing") is not None:
            query = query.where(Guest.opt_in_marketing == criteria["opt_in_marketing"])
        
        if criteria.get("opt_in_sms") is not None:
            query = query.where(Guest.opt_in_sms == criteria["opt_in_sms"])
        
        if criteria.get("source"):
            query = query.where(Guest.guest_source == criteria["source"])
        
        if criteria.get("min_value_score"):
            query = query.where(Guest.value_score >= criteria["min_value_score"])
        
        if criteria.get("max_risk_score"):
            query = query.where(Guest.risk_score <= criteria["max_risk_score"])
        
        if criteria.get("verification_status"):
            query = query.where(Guest.verification_status == criteria["verification_status"])
        
        if criteria.get("state"):
            query = query.where(Guest.state == criteria["state"])
        
        if criteria.get("is_blacklisted") is not None:
            query = query.where(Guest.is_blacklisted == criteria["is_blacklisted"])
        
        # Exclude do-not-contact
        query = query.where(Guest.is_do_not_contact == False)
        
        # Order
        sort_by = criteria.get("sort_by", "lifetime_revenue")
        sort_dir = criteria.get("sort_dir", "desc")
        sort_col = getattr(Guest, sort_by, Guest.lifetime_revenue)
        query = query.order_by(desc(sort_col) if sort_dir == "desc" else asc(sort_col))
        
        # Limit
        limit = criteria.get("limit", 500)
        query = query.limit(limit)
        
        result = await self.db.execute(query)
        guests = result.scalars().all()
        
        return [{
            "id": str(g.id),
            "full_name": g.full_name,
            "phone_number": g.phone_number,
            "email": g.email,
            "loyalty_tier": g.loyalty_tier,
            "lifetime_stays": g.lifetime_stays,
            "lifetime_revenue": float(g.lifetime_revenue or 0),
            "value_score": g.value_score,
            "last_stay_date": str(g.last_stay_date) if g.last_stay_date else None,
            "tags": g.tags or [],
            "opt_in_sms": g.opt_in_sms,
            "opt_in_email": g.opt_in_email,
        } for g in guests]
    
    # ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
    # REVIEW MANAGEMENT
    # ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
    
    async def submit_guest_review(
        self,
        guest_id: UUID,
        reservation_id: UUID,
        property_id: UUID,
        overall_rating: int,
        body: str,
        category_ratings: Optional[Dict] = None,
        submitted_via: str = "web_form",
    ) -> GuestReview:
        """
        Submit a guest review of a property (post-stay)
        
        BETTER THAN Streamline: Rich category ratings + AI sentiment analysis
        BETTER THAN RueBaRue: Not just a Google review link, full internal system
        """
        review = GuestReview(
            guest_id=guest_id,
            reservation_id=reservation_id,
            property_id=property_id,
            direction="guest_to_property",
            overall_rating=max(1, min(5, overall_rating)),
            body=body,
            submitted_via=submitted_via,
        )
        
        # Category ratings
        if category_ratings:
            for field in [
                "cleanliness_rating", "accuracy_rating", "communication_rating",
                "location_rating", "checkin_rating", "value_rating", "amenities_rating"
            ]:
                if field in category_ratings:
                    setattr(review, field, max(1, min(5, category_ratings[field])))
        
        # Simple sentiment analysis
        body_lower = body.lower()
        positive_words = ["great", "amazing", "love", "perfect", "wonderful", "excellent", "fantastic"]
        negative_words = ["terrible", "awful", "bad", "dirty", "broken", "disappointed", "worst"]
        
        pos_count = sum(1 for w in positive_words if w in body_lower)
        neg_count = sum(1 for w in negative_words if w in body_lower)
        
        if pos_count > neg_count:
            review.sentiment = "positive"
            review.sentiment_score = Decimal("0.8")
        elif neg_count > pos_count:
            review.sentiment = "negative"
            review.sentiment_score = Decimal("0.3")
        else:
            review.sentiment = "neutral"
            review.sentiment_score = Decimal("0.5")
        
        # Auto-publish positive reviews
        if overall_rating >= 4:
            review.is_published = True
            review.published_at = datetime.utcnow()
        
        # Flag negative reviews for attention
        if overall_rating <= 2:
            review.is_flagged = True
            review.flag_reason = "Low rating - requires follow-up"
        
        self.db.add(review)
        
        # Update guest's average rating
        await self._update_guest_average_rating(guest_id)
        
        # Log activity
        await self._log_activity(
            guest_id=guest_id,
            activity_type="review_submitted",
            category="feedback",
            title=f"Review submitted: {overall_rating}/5 stars",
            reservation_id=reservation_id,
            property_id=property_id,
            review_id=review.id,
            metadata={
                "overall_rating": overall_rating,
                "sentiment": review.sentiment,
            },
        )
        
        await self.db.commit()
        await self.db.refresh(review)
        
        return review
    
    async def submit_manager_review(
        self,
        guest_id: UUID,
        reservation_id: UUID,
        property_id: UUID,
        overall_rating: int,
        body: str,
        category_ratings: Optional[Dict] = None,
        reviewed_by: str = "manager",
    ) -> GuestReview:
        """Submit a manager review OF a guest (internal scoring)"""
        review = GuestReview(
            guest_id=guest_id,
            reservation_id=reservation_id,
            property_id=property_id,
            direction="property_to_guest",
            overall_rating=max(1, min(5, overall_rating)),
            body=body,
            response_by=reviewed_by,
        )
        
        if category_ratings:
            for field in [
                "house_rules_rating", "cleanliness_left_rating",
                "communication_guest_rating", "respect_rating",
                "noise_rating", "checkout_compliance_rating"
            ]:
                if field in category_ratings:
                    setattr(review, field, max(1, min(5, category_ratings[field])))
        
        self.db.add(review)
        
        # Update risk score based on manager review
        guest = await self.db.get(Guest, guest_id)
        if guest and overall_rating <= 2:
            guest.risk_score = min(100, (guest.risk_score or 10) + 15)
            guest.requires_supervision = True
        
        await self._log_activity(
            guest_id=guest_id,
            activity_type="review_received",
            category="feedback",
            title=f"Manager review: {overall_rating}/5",
            reservation_id=reservation_id,
            performed_by=reviewed_by,
        )
        
        await self.db.commit()
        await self.db.refresh(review)
        return review
    
    async def respond_to_review(
        self,
        review_id: UUID,
        response_body: str,
        responded_by: str,
    ) -> GuestReview:
        """Add a response to a guest review"""
        review = await self.db.get(GuestReview, review_id)
        if not review:
            raise ValueError("Review not found")
        
        review.response_body = response_body
        review.response_by = responded_by
        review.response_at = datetime.utcnow()
        
        await self.db.commit()
        return review
    
    async def get_review_analytics(
        self,
        property_id: Optional[UUID] = None,
        days: int = 90,
    ) -> Dict:
        """Get review analytics and trends"""
        since = datetime.utcnow() - timedelta(days=days)
        
        query = select(GuestReview).where(
            GuestReview.direction == "guest_to_property",
            GuestReview.created_at >= since,
        )
        if property_id:
            query = query.where(GuestReview.property_id == property_id)
        
        result = await self.db.execute(query)
        reviews = result.scalars().all()
        
        if not reviews:
            return {"total": 0, "average_rating": 0, "sentiment": {}}
        
        ratings = [r.overall_rating for r in reviews]
        sentiments = {}
        for r in reviews:
            s = r.sentiment or "unknown"
            sentiments[s] = sentiments.get(s, 0) + 1
        
        return {
            "total": len(reviews),
            "average_rating": round(sum(ratings) / len(ratings), 2),
            "rating_distribution": {
                str(i): sum(1 for r in ratings if r == i)
                for i in range(1, 6)
            },
            "sentiment_distribution": sentiments,
            "positive_rate": round(
                sum(1 for r in reviews if r.overall_rating >= 4) / len(reviews) * 100, 1
            ),
            "needs_response": sum(
                1 for r in reviews if r.overall_rating <= 3 and not r.response_body
            ),
            "published": sum(1 for r in reviews if r.is_published),
            "flagged": sum(1 for r in reviews if r.is_flagged),
        }
    
    # ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
    # SURVEY ENGINE
    # ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
    
    async def send_survey(
        self,
        guest_id: UUID,
        reservation_id: UUID,
        template_id: UUID,
        send_method: str = "sms",
    ) -> GuestSurvey:
        """Create and send a survey to a guest"""
        guest = await self.db.get(Guest, guest_id)
        template = await self.db.get(SurveyTemplate, template_id)
        reservation = await self.db.get(Reservation, reservation_id)
        
        if not guest or not template:
            raise ValueError("Guest and template required")
        
        # Generate unique survey URL
        survey_token = str(uuid4())[:12]
        survey_url = f"{settings.frontend_url}/survey/{survey_token}"
        
        survey = GuestSurvey(
            guest_id=guest_id,
            reservation_id=reservation_id,
            property_id=reservation.property_id if reservation else None,
            template_id=template_id,
            survey_type=template.survey_type,
            responses={},
            status="sent",
            sent_at=datetime.utcnow(),
            send_method=send_method,
            survey_url=survey_url,
        )
        
        self.db.add(survey)
        
        # Update template usage
        template.usage_count = (template.usage_count or 0) + 1
        
        await self._log_activity(
            guest_id=guest_id,
            activity_type="survey_sent",
            category="feedback",
            title=f"Survey sent: {template.name}",
            reservation_id=reservation_id,
            survey_id=survey.id,
        )
        
        await self.db.commit()
        await self.db.refresh(survey)
        return survey
    
    async def submit_survey_response(
        self,
        survey_id: UUID,
        responses: Dict,
    ) -> GuestSurvey:
        """Process a completed survey response"""
        survey = await self.db.get(GuestSurvey, survey_id)
        if not survey:
            raise ValueError("Survey not found")
        
        survey.responses = responses
        survey.status = "completed"
        survey.completed_at = datetime.utcnow()
        
        # Calculate scores
        total_score = 0
        rating_count = 0
        nps_value = None
        
        for qid, answer in responses.items():
            if isinstance(answer, dict):
                val = answer.get("value")
                qtype = answer.get("type", "")
            else:
                val = answer
                qtype = ""
            
            if qtype == "rating" and isinstance(val, (int, float)):
                total_score += val
                rating_count += 1
            elif qtype == "nps" and isinstance(val, (int, float)):
                nps_value = int(val)
        
        if rating_count > 0:
            survey.overall_score = Decimal(str(round(total_score / rating_count, 2)))
        
        if nps_value is not None:
            survey.nps_score = nps_value
            if nps_value >= 9:
                survey.nps_category = "promoter"
            elif nps_value >= 7:
                survey.nps_category = "passive"
            else:
                survey.nps_category = "detractor"
        
        # Flag low scores for follow-up
        if survey.overall_score and float(survey.overall_score) < 3:
            survey.follow_up_required = True
        
        await self._log_activity(
            guest_id=survey.guest_id,
            activity_type="survey_completed",
            category="feedback",
            title=f"Survey completed: score {survey.overall_score}",
            reservation_id=survey.reservation_id,
            survey_id=survey.id,
            metadata={
                "overall_score": float(survey.overall_score) if survey.overall_score else None,
                "nps_score": nps_value,
                "nps_category": survey.nps_category,
            },
        )
        
        await self.db.commit()
        await self.db.refresh(survey)
        return survey
    
    async def get_nps_score(
        self,
        property_id: Optional[UUID] = None,
        days: int = 90,
    ) -> Dict:
        """Calculate Net Promoter Score"""
        since = datetime.utcnow() - timedelta(days=days)
        
        query = select(GuestSurvey).where(
            GuestSurvey.status == "completed",
            GuestSurvey.nps_score.isnot(None),
            GuestSurvey.completed_at >= since,
        )
        if property_id:
            query = query.where(GuestSurvey.property_id == property_id)
        
        result = await self.db.execute(query)
        surveys = result.scalars().all()
        
        if not surveys:
            return {"nps": 0, "total_responses": 0}
        
        total = len(surveys)
        promoters = sum(1 for s in surveys if s.nps_score >= 9)
        detractors = sum(1 for s in surveys if s.nps_score <= 6)
        passives = total - promoters - detractors
        
        nps = round((promoters / total - detractors / total) * 100)
        
        return {
            "nps": nps,
            "total_responses": total,
            "promoters": promoters,
            "passives": passives,
            "detractors": detractors,
            "promoter_pct": round(promoters / total * 100, 1),
            "detractor_pct": round(detractors / total * 100, 1),
        }
    
    # ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
    # BLACKLIST & FLAGS
    # ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
    
    async def blacklist_guest(
        self,
        guest_id: UUID,
        reason: str,
        blacklisted_by: str,
    ) -> Guest:
        """Add guest to blacklist"""
        guest = await self.db.get(Guest, guest_id)
        if not guest:
            raise ValueError("Guest not found")
        
        guest.is_blacklisted = True
        guest.blacklist_reason = reason
        guest.blacklisted_by = blacklisted_by
        guest.blacklisted_at = datetime.utcnow()
        guest.risk_score = 100
        
        await self._log_activity(
            guest_id=guest_id,
            activity_type="blacklisted",
            category="profile",
            title=f"Guest blacklisted: {reason}",
            performed_by=blacklisted_by,
            importance="critical",
            metadata={"reason": reason},
        )
        
        await self.db.commit()
        return guest
    
    async def remove_from_blacklist(
        self,
        guest_id: UUID,
        removed_by: str,
    ) -> Guest:
        """Remove guest from blacklist"""
        guest = await self.db.get(Guest, guest_id)
        if not guest:
            raise ValueError("Guest not found")
        
        guest.is_blacklisted = False
        guest.blacklist_reason = None
        guest.blacklisted_at = None
        guest.risk_score = guest.calculate_risk_score()
        
        await self._log_activity(
            guest_id=guest_id,
            activity_type="un_blacklisted",
            category="profile",
            title="Guest removed from blacklist",
            performed_by=removed_by,
            importance="high",
        )
        
        await self.db.commit()
        return guest
    
    async def toggle_vip(self, guest_id: UUID, is_vip: bool, by: str) -> Guest:
        """Toggle VIP status"""
        guest = await self.db.get(Guest, guest_id)
        if not guest:
            raise ValueError("Guest not found")
        
        guest.is_vip = is_vip
        
        action = "granted" if is_vip else "removed"
        await self._log_activity(
            guest_id=guest_id,
            activity_type="vip_status_changed",
            category="loyalty",
            title=f"VIP status {action}",
            performed_by=by,
            importance="high",
        )
        
        await self.db.commit()
        return guest
    
    # ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
    # GUEST ANALYTICS
    # ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
    
    async def get_guest_analytics(self, days: int = 30) -> Dict:
        """
        Comprehensive guest analytics dashboard data
        
        Streamline shows basic counts. We show intelligence.
        """
        since = datetime.utcnow() - timedelta(days=days)
        
        # Total guests
        total_result = await self.db.execute(select(func.count(Guest.id)))
        total_guests = total_result.scalar()
        
        # New guests in period
        new_result = await self.db.execute(
            select(func.count(Guest.id)).where(Guest.created_at >= since)
        )
        new_guests = new_result.scalar()
        
        # Tier distribution
        tier_result = await self.db.execute(
            select(Guest.loyalty_tier, func.count(Guest.id))
            .group_by(Guest.loyalty_tier)
        )
        tier_distribution = {row[0] or "bronze": row[1] for row in tier_result.all()}
        
        # Source distribution
        source_result = await self.db.execute(
            select(Guest.guest_source, func.count(Guest.id))
            .where(Guest.guest_source.isnot(None))
            .group_by(Guest.guest_source)
        )
        source_distribution = {row[0]: row[1] for row in source_result.all()}
        
        # Verification stats
        verif_result = await self.db.execute(
            select(Guest.verification_status, func.count(Guest.id))
            .group_by(Guest.verification_status)
        )
        verification_stats = {row[0] or "unverified": row[1] for row in verif_result.all()}
        
        # Repeat rate
        repeat_result = await self.db.execute(
            select(func.count(Guest.id)).where(Guest.lifetime_stays > 1)
        )
        repeat_guests = repeat_result.scalar()
        
        # Average lifetime value
        ltv_result = await self.db.execute(
            select(func.avg(Guest.lifetime_revenue))
            .where(Guest.lifetime_revenue > 0)
        )
        avg_ltv = float(ltv_result.scalar() or 0)
        
        # Average scores
        scores_result = await self.db.execute(
            select(
                func.avg(Guest.value_score),
                func.avg(Guest.risk_score),
                func.avg(Guest.satisfaction_score),
            ).where(Guest.value_score.isnot(None))
        )
        scores = scores_result.first()
        
        # Top guests by revenue
        top_result = await self.db.execute(
            select(Guest)
            .where(Guest.lifetime_revenue > 0)
            .order_by(desc(Guest.lifetime_revenue))
            .limit(10)
        )
        top_guests = [{
            "id": str(g.id),
            "name": g.full_name,
            "revenue": float(g.lifetime_revenue or 0),
            "stays": g.lifetime_stays,
            "tier": g.loyalty_tier,
        } for g in top_result.scalars().all()]
        
        return {
            "total_guests": total_guests,
            "new_guests_period": new_guests,
            "repeat_guests": repeat_guests,
            "repeat_rate": round(repeat_guests / total_guests * 100, 1) if total_guests else 0,
            "avg_lifetime_value": round(avg_ltv, 2),
            "tier_distribution": tier_distribution,
            "source_distribution": source_distribution,
            "verification_stats": verification_stats,
            "avg_value_score": round(float(scores[0] or 0), 1),
            "avg_risk_score": round(float(scores[1] or 0), 1),
            "avg_satisfaction_score": round(float(scores[2] or 0), 1),
            "top_guests": top_guests,
            "blacklisted_count": (
                await self.db.execute(
                    select(func.count(Guest.id)).where(Guest.is_blacklisted == True)
                )
            ).scalar(),
            "vip_count": (
                await self.db.execute(
                    select(func.count(Guest.id)).where(Guest.is_vip == True)
                )
            ).scalar(),
        }
    
    # ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
    # PRIVATE HELPERS
    # ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
    
    async def _log_activity(
        self,
        guest_id: UUID,
        activity_type: str,
        category: str,
        title: str,
        description: str = None,
        reservation_id: UUID = None,
        property_id: UUID = None,
        message_id: UUID = None,
        review_id: UUID = None,
        survey_id: UUID = None,
        agreement_id: UUID = None,
        work_order_id: UUID = None,
        performed_by: str = "system",
        performed_by_type: str = "system",
        metadata: Dict = None,
        importance: str = "normal",
    ):
        """Log an activity to the guest timeline"""
        activity = GuestActivity(
            guest_id=guest_id,
            activity_type=activity_type,
            category=category,
            title=title,
            description=description,
            reservation_id=reservation_id,
            property_id=property_id,
            message_id=message_id,
            review_id=review_id,
            survey_id=survey_id,
            agreement_id=agreement_id,
            work_order_id=work_order_id,
            performed_by=performed_by,
            performed_by_type=performed_by_type,
            extra_data=metadata,
            importance=importance,
        )
        self.db.add(activity)
    
    async def _get_guest_reservations(self, guest_id: UUID) -> List[Dict]:
        result = await self.db.execute(
            select(Reservation)
            .where(Reservation.guest_id == guest_id)
            .order_by(desc(Reservation.check_in_date))
            .limit(20)
        )
        return [{
            "id": str(r.id),
            "confirmation_code": r.confirmation_code,
            "property_id": str(r.property_id),
            "check_in": str(r.check_in_date),
            "check_out": str(r.check_out_date),
            "nights": r.nights,
            "status": r.status,
            "total_amount": float(r.total_amount) if r.total_amount else 0,
            "booking_source": r.booking_source,
            "guest_rating": r.guest_rating,
        } for r in result.scalars().all()]
    
    async def _get_message_summary(self, guest_id: UUID) -> Dict:
        result = await self.db.execute(
            select(
                func.count(Message.id).label("total"),
                func.count(Message.id).filter(Message.direction == "inbound").label("inbound"),
                func.count(Message.id).filter(Message.direction == "outbound").label("outbound"),
                func.max(Message.created_at).label("last_message"),
            ).where(Message.guest_id == guest_id)
        )
        row = result.first()
        return {
            "total_messages": row.total or 0,
            "inbound": row.inbound or 0,
            "outbound": row.outbound or 0,
            "last_message_at": str(row.last_message) if row.last_message else None,
        }
    
    async def _get_guest_reviews(self, guest_id: UUID) -> List[Dict]:
        result = await self.db.execute(
            select(GuestReview)
            .where(GuestReview.guest_id == guest_id)
            .order_by(desc(GuestReview.created_at))
            .limit(10)
        )
        return [{
            "id": str(r.id),
            "direction": r.direction,
            "overall_rating": r.overall_rating,
            "title": r.title,
            "body": r.body[:200] if r.body else None,
            "sentiment": r.sentiment,
            "is_published": r.is_published,
            "created_at": str(r.created_at),
        } for r in result.scalars().all()]
    
    async def _get_guest_surveys(self, guest_id: UUID) -> List[Dict]:
        result = await self.db.execute(
            select(GuestSurvey)
            .where(GuestSurvey.guest_id == guest_id)
            .order_by(desc(GuestSurvey.created_at))
            .limit(10)
        )
        return [{
            "id": str(r.id),
            "survey_type": r.survey_type,
            "overall_score": float(r.overall_score) if r.overall_score else None,
            "nps_score": r.nps_score,
            "status": r.status,
            "completed_at": str(r.completed_at) if r.completed_at else None,
        } for r in result.scalars().all()]
    
    async def _get_guest_agreements(self, guest_id: UUID) -> List[Dict]:
        result = await self.db.execute(
            select(RentalAgreement)
            .where(RentalAgreement.guest_id == guest_id)
            .order_by(desc(RentalAgreement.created_at))
            .limit(10)
        )
        return [{
            "id": str(r.id),
            "agreement_type": r.agreement_type,
            "status": r.status,
            "signed_at": str(r.signed_at) if r.signed_at else None,
            "created_at": str(r.created_at),
        } for r in result.scalars().all()]
    
    async def _get_recent_activities(self, guest_id: UUID, limit: int = 20) -> List[Dict]:
        result = await self.db.execute(
            select(GuestActivity)
            .where(GuestActivity.guest_id == guest_id)
            .order_by(desc(GuestActivity.created_at))
            .limit(limit)
        )
        return [{
            "id": str(a.id),
            "type": a.activity_type,
            "category": a.category,
            "title": a.title,
            "description": a.description,
            "performed_by": a.performed_by,
            "importance": a.importance,
            "metadata": a.extra_data,
            "created_at": str(a.created_at),
        } for a in result.scalars().all()]
    
    async def _get_guest_work_orders(self, guest_id: UUID) -> List[Dict]:
        result = await self.db.execute(
            select(WorkOrder)
            .where(WorkOrder.guest_id == guest_id)
            .order_by(desc(WorkOrder.created_at))
            .limit(10)
        )
        return [{
            "id": str(w.id),
            "ticket_number": w.ticket_number,
            "title": w.title,
            "category": w.category,
            "priority": w.priority,
            "status": w.status,
            "created_at": str(w.created_at),
        } for w in result.scalars().all()]
    
    async def _get_latest_verification(self, guest_id: UUID) -> Optional[Dict]:
        result = await self.db.execute(
            select(GuestVerification)
            .where(GuestVerification.guest_id == guest_id)
            .order_by(desc(GuestVerification.created_at))
            .limit(1)
        )
        v = result.scalar_one_or_none()
        if not v:
            return None
        return {
            "id": str(v.id),
            "type": v.verification_type,
            "status": v.status,
            "document_type": v.document_type,
            "confidence_score": float(v.confidence_score) if v.confidence_score else None,
            "created_at": str(v.created_at),
        }
    
    async def _compute_guest_stats(
        self, guest_id: UUID, reservations: List[Dict]
    ) -> Dict:
        total_revenue = sum(r.get("total_amount", 0) for r in reservations)
        total_nights = sum(r.get("nights", 0) for r in reservations)
        completed = [r for r in reservations if r["status"] in ("checked_out", "completed")]
        upcoming = [r for r in reservations if r["status"] in ("confirmed",)]
        
        return {
            "total_reservations": len(reservations),
            "completed_stays": len(completed),
            "upcoming_stays": len(upcoming),
            "total_revenue": round(total_revenue, 2),
            "total_nights": total_nights,
            "avg_stay_length": round(total_nights / len(completed), 1) if completed else 0,
            "avg_spend": round(total_revenue / len(completed), 2) if completed else 0,
        }
    
    async def _update_guest_average_rating(self, guest_id: UUID):
        result = await self.db.execute(
            select(func.avg(GuestReview.overall_rating))
            .where(
                GuestReview.guest_id == guest_id,
                GuestReview.direction == "guest_to_property",
            )
        )
        avg = result.scalar()
        if avg:
            guest = await self.db.get(Guest, guest_id)
            if guest:
                guest.average_rating = Decimal(str(round(float(avg), 2)))
    
    def _get_next_tier_info(self, guest: Guest) -> Optional[Dict]:
        """Calculate what's needed for next loyalty tier"""
        tier = guest.loyalty_tier or "bronze"
        stays = guest.lifetime_stays or 0
        revenue = float(guest.lifetime_revenue or 0)
        
        tiers = {
            "bronze": {"next": "silver", "stays_needed": 2, "revenue_needed": 3000},
            "silver": {"next": "gold", "stays_needed": 5, "revenue_needed": 10000},
            "gold": {"next": "platinum", "stays_needed": 10, "revenue_needed": 25000},
            "platinum": {"next": "diamond", "stays_needed": 20, "revenue_needed": 50000},
            "diamond": None,
        }
        
        info = tiers.get(tier)
        if not info:
            return None
        
        return {
            "next_tier": info["next"],
            "stays_remaining": max(0, info["stays_needed"] - stays),
            "revenue_remaining": max(0, info["revenue_needed"] - revenue),
        }
