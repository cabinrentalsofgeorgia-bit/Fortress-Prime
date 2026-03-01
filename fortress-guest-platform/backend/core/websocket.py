"""
WebSocket connection manager for real-time dashboard updates.

Events emitted:
  - new_message: Inbound/outbound SMS
  - reservation_update: Check-in, check-out, new booking
  - work_order_update: New/status change
  - review_queue_item: New AI draft pending review
  - stats_update: Periodic dashboard stats refresh
"""

import asyncio
import json
from datetime import datetime
from typing import Dict, Set
from fastapi import WebSocket, WebSocketDisconnect
import structlog

logger = structlog.get_logger()


class ConnectionManager:
    """Manages WebSocket connections per staff user/dashboard."""

    def __init__(self):
        self._connections: Set[WebSocket] = set()
        self._lock = asyncio.Lock()

    async def connect(self, ws: WebSocket):
        await ws.accept()
        async with self._lock:
            self._connections.add(ws)
        logger.info("ws_connected", total=len(self._connections))

    async def disconnect(self, ws: WebSocket):
        async with self._lock:
            self._connections.discard(ws)
        logger.info("ws_disconnected", total=len(self._connections))

    async def broadcast(self, event: str, data: dict):
        """Send an event to all connected dashboards."""
        payload = json.dumps({
            "event": event,
            "data": data,
            "timestamp": datetime.utcnow().isoformat(),
        })
        async with self._lock:
            dead: list[WebSocket] = []
            for ws in self._connections:
                try:
                    await ws.send_text(payload)
                except Exception:
                    dead.append(ws)
            for ws in dead:
                self._connections.discard(ws)

    @property
    def active_count(self) -> int:
        return len(self._connections)


manager = ConnectionManager()


async def emit_new_message(message_data: dict):
    await manager.broadcast("new_message", message_data)


async def emit_reservation_update(reservation_data: dict):
    await manager.broadcast("reservation_update", reservation_data)


async def emit_work_order_update(work_order_data: dict):
    await manager.broadcast("work_order_update", work_order_data)


async def emit_review_queue_item(item_data: dict):
    await manager.broadcast("review_queue_item", item_data)


async def emit_stats_update(stats_data: dict):
    await manager.broadcast("stats_update", stats_data)
