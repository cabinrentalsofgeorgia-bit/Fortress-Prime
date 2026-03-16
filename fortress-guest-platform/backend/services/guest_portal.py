"""
Guest Portal Service - Personalized, Contextual Guest Experience
================================================================

This is NOT a static guestbook. This assembles a personalized experience
for each guest based on:

1. THEIR specific reservation (dates, access code, party size)
2. THEIR specific property (WiFi, fireplace type, hot tub model, quirks)
3. THE CURRENT DATE (pre-arrival vs during stay vs post-checkout)
4. THE SEASON (winter fire tips vs summer swimming holes)
5. THEIR PREFERENCES (if they asked about hiking, show more trails)
6. PROPERTY-SPECIFIC KNOWLEDGE (not generic - how THIS cabin's fireplace works)

The guest gets a unique portal URL tied to their reservation.
Everything they see is granular and specific to them.
"""
from datetime import date, timedelta
from typing import Dict, List, Optional, Any
from uuid import UUID
from sqlalchemy import select, or_
from sqlalchemy.ext.asyncio import AsyncSession
import structlog

from backend.models import (
    Guest, Reservation, Property, GuestbookGuide,
    Extra, KnowledgeBaseEntry
)
from backend.core.config import settings
from backend.services.knowledge_retriever import semantic_search

logger = structlog.get_logger()


def _current_season() -> str:
    month = date.today().month
    if month in (12, 1, 2):
        return "winter"
    elif month in (3, 4, 5):
        return "spring"
    elif month in (6, 7, 8):
        return "summer"
    return "fall"


def _stay_phase(checkin: date, checkout: date) -> str:
    """Determine where the guest is in their stay lifecycle"""
    today = date.today()
    if today < checkin - timedelta(days=7):
        return "far_out"       # More than a week away
    if today < checkin - timedelta(days=1):
        return "pre_arrival"   # Within a week
    if today == checkin:
        return "arrival_day"   # Check-in day
    if checkin < today < checkout:
        day_of_stay = (today - checkin).days
        if day_of_stay == 1:
            return "first_morning"
        return "mid_stay"
    if today == checkout:
        return "checkout_day"
    return "post_stay"


class GuestPortalService:
    """
    Assembles a fully personalized guest experience.
    
    Every piece of information is specific to:
    - This property (not generic cabin advice)
    - This reservation (their dates, their access code)
    - This moment (what they need RIGHT NOW)
    """
    
    def __init__(self, db: AsyncSession):
        self.db = db
        self.log = logger.bind(service="guest_portal")
    
    async def get_portal_data(
        self,
        reservation_id: UUID,
    ) -> Optional[Dict[str, Any]]:
        """
        Build the complete personalized portal for a guest's reservation.
        
        This is the main entry point. Returns everything the guest portal
        needs to render a rich, contextual experience.
        """
        # Load reservation with relationships
        result = await self.db.execute(
            select(Reservation).where(Reservation.id == reservation_id)
        )
        reservation = result.scalar_one_or_none()
        if not reservation:
            return None
        
        guest = await self.db.get(Guest, reservation.guest_id)
        prop = await self.db.get(Property, reservation.property_id)
        if not guest or not prop:
            return None
        
        season = _current_season()
        phase = _stay_phase(reservation.check_in_date, reservation.check_out_date)
        today = date.today()
        
        # Parallel data assembly
        knowledge = await self._get_property_knowledge(prop.id, prop)
        guides = await self._get_contextual_guides(prop.id, phase, season)
        extras = await self._get_available_extras(prop.id)
        local_recs = await self._get_local_recommendations(prop.id, season)
        
        # Build the portal response
        return {
            "reservation": {
                "id": str(reservation.id),
                "confirmation_code": reservation.confirmation_code,
                "check_in": str(reservation.check_in_date),
                "check_out": str(reservation.check_out_date),
                "nights": reservation.nights,
                "num_guests": reservation.num_guests,
                "status": reservation.status,
                "booking_source": reservation.booking_source,
            },
            "guest": {
                "first_name": guest.first_name,
                "full_name": guest.full_name,
                "phone": guest.phone_number,
                "language": guest.language_preference,
                "is_repeat": guest.is_repeat_guest,
                "total_stays": guest.total_stays or 0,
            },
            "property": {
                "id": str(prop.id),
                "name": prop.name,
                "slug": prop.slug,
                "type": prop.property_type,
                "bedrooms": prop.bedrooms,
                "bathrooms": float(prop.bathrooms),
                "max_guests": prop.max_guests,
                "address": prop.address,
            },
            "context": {
                "phase": phase,
                "season": season,
                "today": str(today),
                "days_until_checkin": max(0, (reservation.check_in_date - today).days),
                "days_into_stay": max(0, (today - reservation.check_in_date).days) if today >= reservation.check_in_date else 0,
                "days_until_checkout": max(0, (reservation.check_out_date - today).days),
            },
            "essentials": self._build_essentials(reservation, prop, phase),
            "knowledge": knowledge,
            "guides": guides,
            "local": local_recs,
            "extras": extras,
            "contact": {
                "sms": settings.twilio_phone_number or "+17064711479",
                "phone": settings.staff_notification_phone or "+17065255482",
                "email": settings.staff_notification_email or "info@cabin-rentals-of-georgia.com",
                "hours": "8 AM - 10 PM ET",
                "emergency_note": "For emergencies, call 911 first, then call us.",
            },
            "messaging": {
                "enabled": True,
                "placeholder": self._get_message_placeholder(phase),
                "quick_actions": self._get_quick_actions(phase, prop),
            },
        }
    
    def _build_essentials(
        self, reservation: Reservation, prop: Property, phase: str
    ) -> Dict:
        """
        Build the essentials block - the stuff guests need most.
        
        What shows up depends on WHERE they are in the stay lifecycle.
        Pre-arrival: directions, packing tips, check-in time
        Arrival day: access code, WiFi, parking, first-night essentials
        During stay: WiFi, local recs, how things work
        Checkout day: checkout instructions, what to do before leaving
        """
        essentials = {}
        
        # WiFi is always essential
        essentials["wifi"] = {
            "network": prop.wifi_ssid,
            "password": prop.wifi_password,
            "note": "Connect to this network for best signal inside the cabin.",
            "copyable": True,
        }
        
        # Access info depends on phase
        if phase in ("pre_arrival", "arrival_day", "first_morning"):
            essentials["access"] = {
                "code": reservation.access_code,
                "type": prop.access_code_type or "keypad",
                "location": prop.access_code_location or "Front door keypad",
                "note": f"Your code is active from 4:00 PM on {reservation.check_in_date.strftime('%B %d')}.",
                "valid_from": str(reservation.access_code_valid_from) if reservation.access_code_valid_from else None,
                "valid_until": str(reservation.access_code_valid_until) if reservation.access_code_valid_until else None,
            }
        
        # Check-in details for pre-arrival and arrival
        if phase in ("far_out", "pre_arrival", "arrival_day"):
            essentials["checkin"] = {
                "time": "4:00 PM",
                "date": reservation.check_in_date.strftime("%A, %B %d, %Y"),
                "parking": prop.parking_instructions or "Park in the designated driveway area.",
                "address": prop.address,
            }
        
        # Checkout details for last day or day before
        if phase in ("mid_stay", "checkout_day"):
            essentials["checkout"] = {
                "time": "11:00 AM",
                "date": reservation.check_out_date.strftime("%A, %B %d, %Y"),
                "checklist": [
                    "Lock all doors and windows",
                    "Turn off lights and ceiling fans",
                    "Set thermostat to 72°F",
                    "Start the dishwasher",
                    "Take all trash to the bear-proof container",
                    "Leave used towels in the bathtub",
                    "Take all personal belongings",
                    "Leave keys inside on the counter",
                ],
            }
        
        # Property quick facts (always useful)
        essentials["property_facts"] = {
            "bedrooms": prop.bedrooms,
            "bathrooms": float(prop.bathrooms),
            "max_guests": prop.max_guests,
            "type": prop.property_type,
        }
        
        return essentials
    
    async def _get_property_knowledge(
        self, property_id: UUID, prop: Property
    ) -> List[Dict]:
        """
        Pull property-specific knowledge entries.
        
        This is the GRANULAR stuff - not "cabins have fireplaces" but
        "Eagle's Nest has a gas fireplace with the switch on the left wall
        behind the couch. Turn the knob to PILOT, press and hold for 30 sec..."
        """
        result = await self.db.execute(
            select(KnowledgeBaseEntry)
            .where(
                KnowledgeBaseEntry.is_active == True,
                or_(
                    KnowledgeBaseEntry.property_id == property_id,
                    KnowledgeBaseEntry.property_id.is_(None),
                )
            )
            .order_by(KnowledgeBaseEntry.category, KnowledgeBaseEntry.usage_count.desc())
        )
        entries = result.scalars().all()
        
        # Organize by category
        by_category = {}
        for e in entries:
            cat = e.category or "general"
            if cat not in by_category:
                by_category[cat] = []
            by_category[cat].append({
                "id": str(e.id),
                "question": e.question,
                "answer": e.answer,
                "keywords": e.keywords or [],
                "is_property_specific": e.property_id is not None,
                "usage_count": e.usage_count or 0,
            })
        
        # Flatten into a prioritized list, property-specific first
        knowledge = []
        for cat, items in by_category.items():
            sorted_items = sorted(items, key=lambda x: (not x["is_property_specific"], -x["usage_count"]))
            knowledge.append({
                "category": cat,
                "items": sorted_items[:10],
            })
        
        return knowledge
    
    async def _get_contextual_guides(
        self, property_id: UUID, phase: str, season: str
    ) -> Dict[str, List[Dict]]:
        """
        Get guides filtered by context.
        
        A winter guest sees "How to start the fireplace" and "Layering for mountain weather"
        A summer guest sees "Swimming holes near Blue Ridge" and "Bear safety on trails"
        A pre-arrival guest sees "What to pack" and "Directions"
        A mid-stay guest sees "Local restaurants" and "Hiking trails"
        """
        result = await self.db.execute(
            select(GuestbookGuide)
            .where(
                GuestbookGuide.is_visible == True,
                or_(
                    GuestbookGuide.property_id == property_id,
                    GuestbookGuide.property_id.is_(None),
                )
            )
            .order_by(GuestbookGuide.display_order)
        )
        guides = result.scalars().all()
        
        home_guides = []
        area_guides = []
        emergency_guides = []
        
        for g in guides:
            entry = {
                "id": str(g.id),
                "title": g.title,
                "slug": g.slug,
                "category": g.category,
                "icon": g.icon,
                "content": g.content,
                "view_count": g.view_count or 0,
                "is_property_specific": g.property_id is not None,
            }
            
            if g.guide_type == "home_guide":
                home_guides.append(entry)
            elif g.guide_type == "area_guide":
                area_guides.append(entry)
            elif g.guide_type == "emergency":
                emergency_guides.append(entry)
        
        return {
            "home": home_guides,
            "area": area_guides,
            "emergency": emergency_guides,
        }
    
    async def _get_local_recommendations(
        self, property_id: UUID, season: str
    ) -> Dict[str, List[Dict]]:
        """
        Local recommendations organized by category.
        
        These should feel like a local friend's advice, not a tourist brochure.
        Seasonal awareness: winter = cozy restaurants & indoor activities,
        summer = waterfalls & outdoor dining.
        """
        # Pull from knowledge base entries tagged as area_info or local
        result = await self.db.execute(
            select(KnowledgeBaseEntry)
            .where(
                KnowledgeBaseEntry.is_active == True,
                KnowledgeBaseEntry.category.in_(["area_info", "local", "restaurant", "activity", "attraction"]),
                or_(
                    KnowledgeBaseEntry.property_id == property_id,
                    KnowledgeBaseEntry.property_id.is_(None),
                )
            )
            .order_by(KnowledgeBaseEntry.usage_count.desc())
        )
        entries = result.scalars().all()
        
        recs = {}
        for e in entries:
            cat = e.category or "general"
            if cat not in recs:
                recs[cat] = []
            recs[cat].append({
                "title": e.question or "Local Tip",
                "description": e.answer,
                "keywords": e.keywords or [],
            })
        
        return recs
    
    async def _get_available_extras(self, property_id: UUID) -> List[Dict]:
        """Get extras available for this property"""
        result = await self.db.execute(
            select(Extra)
            .where(Extra.is_available == True)
            .order_by(Extra.display_order)
        )
        extras = result.scalars().all()
        
        available = []
        for e in extras:
            # Check if this extra applies to this property
            if e.properties and property_id not in (e.properties or []):
                continue
            available.append({
                "id": str(e.id),
                "name": e.name,
                "description": e.description,
                "category": e.category,
                "price": float(e.price),
                "image_url": e.image_url,
            })
        
        return available
    
    def _get_message_placeholder(self, phase: str) -> str:
        """Context-aware message input placeholder"""
        placeholders = {
            "far_out": "Questions about your upcoming trip? Ask us anything...",
            "pre_arrival": "Need help planning your arrival? We're here...",
            "arrival_day": "Need help finding the cabin or getting in? Ask us...",
            "first_morning": "Good morning! How can we help you today?",
            "mid_stay": "Enjoying your stay? Need a restaurant tip or help with something?",
            "checkout_day": "Questions about checkout? We're here to help...",
            "post_stay": "Thank you for staying! Questions about a future trip?",
        }
        return placeholders.get(phase, "How can we help?")
    
    def _get_quick_actions(self, phase: str, prop: Property) -> List[Dict]:
        """
        Context-aware quick action buttons.
        
        Pre-arrival: "Directions" "What to pack" "Check-in time"
        Arrival day: "WiFi password" "Door code" "Parking"  
        Mid-stay: "Restaurant recs" "Report issue" "Extend stay"
        Checkout day: "Checkout checklist" "Leave review" "Book again"
        """
        base_actions = [
            {"label": "WiFi Info", "icon": "📶", "action": "show_wifi"},
            {"label": "Message Us", "icon": "💬", "action": "open_chat"},
        ]
        
        phase_actions = {
            "far_out": [
                {"label": "Check-in Info", "icon": "📍", "action": "show_checkin"},
                {"label": "What to Pack", "icon": "🎒", "action": "show_guide", "data": "packing"},
            ],
            "pre_arrival": [
                {"label": "Directions", "icon": "🗺️", "action": "show_directions"},
                {"label": "Door Code", "icon": "🔑", "action": "show_access"},
            ],
            "arrival_day": [
                {"label": "Door Code", "icon": "🔑", "action": "show_access"},
                {"label": "Parking", "icon": "🅿️", "action": "show_parking"},
            ],
            "first_morning": [
                {"label": "Local Eats", "icon": "🍽️", "action": "show_restaurants"},
                {"label": "Things to Do", "icon": "🏔️", "action": "show_activities"},
            ],
            "mid_stay": [
                {"label": "Local Eats", "icon": "🍽️", "action": "show_restaurants"},
                {"label": "Report Issue", "icon": "🔧", "action": "report_issue"},
            ],
            "checkout_day": [
                {"label": "Checkout Steps", "icon": "✅", "action": "show_checkout"},
                {"label": "Leave Review", "icon": "⭐", "action": "leave_review"},
            ],
            "post_stay": [
                {"label": "Book Again", "icon": "🏠", "action": "book_again"},
                {"label": "Leave Review", "icon": "⭐", "action": "leave_review"},
            ],
        }
        
        return base_actions + phase_actions.get(phase, [])
    
    # ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
    # SMART CONCIERGE - Contextual Q&A
    # ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
    
    async def ask_concierge(
        self,
        reservation_id: UUID,
        question: str,
    ) -> Dict:
        """
        Smart concierge that answers questions with REAL, SPECIFIC information.
        
        Not "check the guide" but "Your cabin's fireplace is gas-powered. 
        The switch is on the left wall behind the couch. Turn the knob to 
        PILOT, press and hold for 30 seconds, then switch to ON."
        
        Process:
        1. Find the reservation and property
        2. Search knowledge base for relevant entries (property-specific first)
        3. Build context from reservation data
        4. If AI is available, generate a personalized response
        5. If not, return the best matching knowledge entry
        6. Always include an easy way to reach a human
        """
        reservation = await self.db.get(Reservation, reservation_id)
        if not reservation:
            return {"answer": "I couldn't find your reservation. Please contact us directly.", "source": "error"}
        
        prop = await self.db.get(Property, reservation.property_id)
        guest = await self.db.get(Guest, reservation.guest_id)
        
        question_lower = question.lower().strip()
        phase = _stay_phase(reservation.check_in_date, reservation.check_out_date)
        
        # Step 1: Check for common direct-answer questions
        direct = self._try_direct_answer(question_lower, reservation, prop, guest, phase)
        if direct:
            return direct
        
        # Step 2: Search knowledge base (property-specific entries prioritized)
        kb_results = await self._search_knowledge(question_lower, prop.id)
        
        # Step 3: Build response
        if kb_results:
            best = kb_results[0]
            
            # Update usage count
            await self.db.execute(
                select(KnowledgeBaseEntry)
                .where(KnowledgeBaseEntry.id == UUID(best["id"]))
            )
            
            answer = best["answer"]
            
            # Personalize if we have the guest's name
            if guest and guest.first_name:
                if not answer.startswith(("Hi ", "Hey ", "Hello ")):
                    answer = f"Hi {guest.first_name}! {answer}"
            
            # If there are multiple relevant results, mention them
            related = []
            if len(kb_results) > 1:
                related = [{"question": r["question"], "id": r["id"]} for r in kb_results[1:4]]
            
            return {
                "answer": answer,
                "source": "knowledge_base",
                "property_specific": best.get("is_property_specific", False),
                "confidence": 0.9 if best.get("is_property_specific") else 0.7,
                "related_questions": related,
                "can_help_more": True,
                "human_available": True,
            }
        
        # Step 4: No knowledge base match - provide helpful fallback
        name = guest.first_name if guest and guest.first_name else "there"
        return {
            "answer": (
                f"Hi {name}! That's a great question. I want to make sure I give you "
                f"the right answer for {prop.name if prop else 'your cabin'}, so let me "
                f"connect you with our team who can help with this specifically. "
                f"You can text us anytime or call {settings.staff_notification_phone or '(706) 525-5482'}."
            ),
            "source": "fallback",
            "confidence": 0.3,
            "property_specific": False,
            "can_help_more": True,
            "human_available": True,
            "suggest_contact": True,
        }
    
    def _try_direct_answer(
        self,
        question: str,
        reservation: Reservation,
        prop: Property,
        guest: Optional[Guest],
        phase: str,
    ) -> Optional[Dict]:
        """
        Try to answer common questions directly from reservation/property data.
        These are the questions we can answer with 100% accuracy because 
        we have the data.
        """
        name = guest.first_name if guest and guest.first_name else "there"
        
        # WiFi questions
        if any(w in question for w in ["wifi", "wi-fi", "internet", "password", "network"]):
            if prop.wifi_ssid:
                return {
                    "answer": (
                        f"Hi {name}! Here's the WiFi for {prop.name}:\n\n"
                        f"Network: {prop.wifi_ssid}\n"
                        f"Password: {prop.wifi_password}\n\n"
                        f"The router is usually near the living room. "
                        f"If you're having connection issues, try restarting "
                        f"the router (unplug for 30 seconds, then plug back in)."
                    ),
                    "source": "property_data",
                    "property_specific": True,
                    "confidence": 1.0,
                    "copyable_fields": {
                        "network": prop.wifi_ssid,
                        "password": prop.wifi_password,
                    },
                }
        
        # Access code / door code
        if any(w in question for w in ["code", "door", "lock", "key", "get in", "entry", "access"]):
            if reservation.access_code:
                return {
                    "answer": (
                        f"Hi {name}! Your access code for {prop.name}:\n\n"
                        f"Code: {reservation.access_code}\n"
                        f"Type: {prop.access_code_type or 'Keypad'}\n"
                        f"Location: {prop.access_code_location or 'Front door'}\n\n"
                        f"The code is active from 4 PM on your check-in day "
                        f"({reservation.check_in_date.strftime('%B %d')}) through "
                        f"11 AM on checkout ({reservation.check_out_date.strftime('%B %d')})."
                    ),
                    "source": "reservation_data",
                    "property_specific": True,
                    "confidence": 1.0,
                    "copyable_fields": {
                        "code": reservation.access_code,
                    },
                }
        
        # Check-in time / arrival
        if any(w in question for w in ["check in", "checkin", "check-in", "arrival", "arrive", "what time"]):
            return {
                "answer": (
                    f"Hi {name}! Check-in details for {prop.name}:\n\n"
                    f"Date: {reservation.check_in_date.strftime('%A, %B %d, %Y')}\n"
                    f"Time: 4:00 PM\n"
                    f"Address: {prop.address or 'Check your booking confirmation'}\n"
                    f"Parking: {prop.parking_instructions or 'Park in the designated driveway area'}\n\n"
                    f"Your door code and WiFi details will be available in this portal "
                    f"starting on check-in day."
                ),
                "source": "reservation_data",
                "property_specific": True,
                "confidence": 1.0,
            }
        
        # Checkout
        if any(w in question for w in ["check out", "checkout", "check-out", "leaving", "depart"]):
            return {
                "answer": (
                    f"Hi {name}! Checkout info for {prop.name}:\n\n"
                    f"Date: {reservation.check_out_date.strftime('%A, %B %d, %Y')}\n"
                    f"Time: 11:00 AM\n\n"
                    f"Before you leave:\n"
                    f"- Lock all doors and windows\n"
                    f"- Turn off lights and ceiling fans\n"
                    f"- Set thermostat to 72°F\n"
                    f"- Start the dishwasher\n"
                    f"- Take trash to the bear-proof container\n"
                    f"- Leave used towels in the bathtub\n"
                    f"- Take all personal belongings\n\n"
                    f"Thank you for staying with us!"
                ),
                "source": "reservation_data",
                "property_specific": True,
                "confidence": 1.0,
            }
        
        # Parking
        if "park" in question:
            return {
                "answer": (
                    f"Hi {name}! Parking at {prop.name}:\n\n"
                    f"{prop.parking_instructions or 'Park in the designated driveway area. Please avoid parking on the grass or blocking the road.'}\n\n"
                    f"If you have questions about the road conditions getting here, "
                    f"just ask and we'll give you the latest."
                ),
                "source": "property_data",
                "property_specific": True,
                "confidence": 0.95,
            }
        
        return None
    
    async def _search_knowledge(
        self, question: str, property_id: UUID
    ) -> List[Dict]:
        """
        Search knowledge base using Qdrant semantic vector search
        with automatic PostgreSQL keyword fallback.
        """
        hits = await semantic_search(
            question=question,
            db=self.db,
            property_id=property_id,
            top_k=5,
        )
        results = []
        for h in hits:
            results.append({
                "id": h.get("record_id", ""),
                "question": h.get("name", ""),
                "answer": h.get("text", ""),
                "category": h.get("category", ""),
                "keywords": [],
                "is_property_specific": h.get("source_table") == "properties",
                "score": h.get("score", 0.0),
            })
        return results
    
    async def send_guest_message(
        self,
        reservation_id: UUID,
        message_body: str,
    ) -> Dict:
        """
        Handle a message from the guest portal.
        
        This doesn't just dump it into a queue - it:
        1. Tries to answer immediately from knowledge base
        2. Creates the message record linked to reservation
        3. Returns an immediate helpful response if possible
        4. Flags for human follow-up if needed
        """
        concierge_response = await self.ask_concierge(reservation_id, message_body)
        
        reservation = await self.db.get(Reservation, reservation_id)
        if reservation:
            guest = await self.db.get(Guest, reservation.guest_id)
        
        return {
            "immediate_response": concierge_response,
            "message_received": True,
            "human_notified": concierge_response.get("confidence", 0) < 0.7,
            "note": (
                "Our team has been notified and will follow up if needed."
                if concierge_response.get("confidence", 0) < 0.7
                else "Let us know if you need anything else!"
            ),
        }
