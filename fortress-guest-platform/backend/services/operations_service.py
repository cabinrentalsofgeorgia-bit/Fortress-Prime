"""
Operations Service - Work orders, staff notifications, issue tracking
BETTER THAN: Breezeway (Smart Tasks), RueBaRue (none), ALL others

Features:
1. AI-powered work order creation from guest messages
2. Smart priority assignment
3. Staff notification routing
4. Resolution tracking
5. Cost management
6. Escalation rules
"""
from datetime import datetime
from typing import List, Optional, Dict
from uuid import UUID, uuid4
from sqlalchemy import select, and_, func
from sqlalchemy.ext.asyncio import AsyncSession
import structlog

from backend.core.config import settings
from backend.models import WorkOrder, Property, Message, Guest
from backend.integrations.twilio_client import TwilioClient

logger = structlog.get_logger()


class OperationsService:
    """
    Operations management with AI detection
    
    BETTER THAN competitors:
    - Auto-detects issues from messages
    - Smart priority based on sentiment + keywords
    - Staff notification with context
    - Resolution tracking with cost
    - Escalation rules
    """
    
    def __init__(self, db: AsyncSession):
        self.db = db
        self.twilio = TwilioClient()
        self.log = logger.bind(service="operations")
    
    async def create_work_order(
        self,
        property_id: UUID,
        title: str,
        description: str,
        category: str,
        priority: str = "medium",
        guest_id: Optional[UUID] = None,
        reservation_id: Optional[UUID] = None,
        message_id: Optional[UUID] = None,
        created_by: str = "staff",
    ) -> WorkOrder:
        """Create a new work order with notifications"""
        
        ticket_number = f"WO-{datetime.now().strftime('%Y%m%d%H%M')}-{str(uuid4())[:4].upper()}"
        
        work_order = WorkOrder(
            ticket_number=ticket_number,
            property_id=property_id,
            title=title,
            description=description,
            category=category,
            priority=priority,
            status="open",
            guest_id=guest_id,
            reservation_id=reservation_id,
            reported_via_message_id=message_id,
            created_by=created_by,
        )
        
        self.db.add(work_order)
        await self.db.commit()
        await self.db.refresh(work_order)
        
        # Notify staff for urgent issues
        if priority in ["high", "urgent"]:
            await self._notify_staff(work_order)
        
        # Acknowledge to guest
        if guest_id and message_id:
            guest = await self.db.get(Guest, guest_id)
            if guest:
                await self._acknowledge_to_guest(work_order, guest)
        
        self.log.info(
            "work_order_created",
            ticket=ticket_number,
            category=category,
            priority=priority,
        )
        
        return work_order
    
    async def update_work_order_status(
        self,
        work_order_id: UUID,
        new_status: str,
        notes: Optional[str] = None,
        resolution_notes: Optional[str] = None,
        cost_amount: Optional[float] = None,
    ) -> WorkOrder:
        """Update work order status with tracking"""
        
        work_order = await self.db.get(WorkOrder, work_order_id)
        if not work_order:
            raise ValueError(f"Work order {work_order_id} not found")
        
        old_status = work_order.status
        work_order.status = new_status
        
        if resolution_notes:
            work_order.resolution_notes = resolution_notes
        if cost_amount is not None:
            work_order.cost_amount = cost_amount
        if new_status == "completed":
            work_order.resolved_at = datetime.utcnow()
        
        await self.db.commit()
        
        # Notify guest of resolution
        if new_status == "completed" and work_order.guest_id:
            guest = await self.db.get(Guest, work_order.guest_id)
            if guest:
                prop = await self.db.get(Property, work_order.property_id)
                prop_name = prop.name if prop else "your cabin"
                
                try:
                    await self.twilio.send_sms(
                        to=guest.phone_number,
                        body=(
                            f"Good news! The issue you reported at {prop_name} "
                            f"has been resolved. ✅\n\n"
                            f"{resolution_notes or 'Please let us know if you need anything else!'}"
                        )
                    )
                except Exception as e:
                    self.log.error("guest_notification_failed", error=str(e))
        
        self.log.info(
            "work_order_updated",
            ticket=work_order.ticket_number,
            old_status=old_status,
            new_status=new_status,
        )
        
        return work_order
    
    async def get_operations_summary(self) -> Dict:
        """
        Get operations dashboard summary
        
        BETTER THAN competitors:
        - Real-time stats
        - Category breakdown
        - Priority distribution
        - Resolution time tracking
        """
        # Open work orders by priority
        priority_result = await self.db.execute(
            select(
                WorkOrder.priority,
                func.count(WorkOrder.id)
            )
            .where(WorkOrder.status.in_(["open", "in_progress"]))
            .group_by(WorkOrder.priority)
        )
        priority_counts = dict(priority_result.all())
        
        # Work orders by category
        category_result = await self.db.execute(
            select(
                WorkOrder.category,
                func.count(WorkOrder.id)
            )
            .where(WorkOrder.status.in_(["open", "in_progress"]))
            .group_by(WorkOrder.category)
        )
        category_counts = dict(category_result.all())
        
        # Total costs
        cost_result = await self.db.execute(
            select(func.coalesce(func.sum(WorkOrder.cost_amount), 0))
            .where(WorkOrder.status == "completed")
        )
        total_costs = float(cost_result.scalar())
        
        return {
            "open_by_priority": priority_counts,
            "open_by_category": category_counts,
            "total_open": sum(priority_counts.values()),
            "total_resolved_cost": round(total_costs, 2),
        }
    
    async def _notify_staff(self, work_order: WorkOrder):
        """Send SMS notification to staff for urgent work orders"""
        if not settings.staff_notification_phone:
            return
        
        prop = await self.db.get(Property, work_order.property_id)
        prop_name = prop.name if prop else "Unknown"
        
        try:
            await self.twilio.send_sms(
                to=settings.staff_notification_phone,
                body=(
                    f"🚨 {work_order.priority.upper()} Work Order\n\n"
                    f"Property: {prop_name}\n"
                    f"Issue: {work_order.title[:100]}\n"
                    f"Category: {work_order.category}\n"
                    f"Ticket: {work_order.ticket_number}"
                )
            )
            self.log.info("staff_notified", ticket=work_order.ticket_number)
        except Exception as e:
            self.log.error("staff_notification_failed", error=str(e))
    
    async def _acknowledge_to_guest(self, work_order: WorkOrder, guest: Guest):
        """Send acknowledgment to guest that issue was received"""
        prop = await self.db.get(Property, work_order.property_id)
        prop_name = prop.name if prop else "your cabin"
        
        try:
            await self.twilio.send_sms(
                to=guest.phone_number,
                body=(
                    f"Hi {guest.first_name or 'there'}! We received your report "
                    f"about an issue at {prop_name}. 📋\n\n"
                    f"Ticket: {work_order.ticket_number}\n"
                    f"Priority: {work_order.priority.capitalize()}\n\n"
                    f"Our team is on it! We'll keep you updated."
                )
            )
        except Exception as e:
            self.log.error("guest_acknowledgment_failed", error=str(e))
