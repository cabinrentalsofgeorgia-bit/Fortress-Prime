"""
Streamline VRS Integration — Property Management System Connector
=================================================================
Production-grade integration with Streamline VRS RPC-based JSON API.

API Endpoint: https://web.streamlinevrs.com/api/json
Auth: token_key + token_secret (passed per-request in params)
Protocol: JSON-RPC — POST with { methodName, params }

Available API Methods (confirmed working 2026-02-20):

  PROPERTIES:
    - GetPropertyList            → All properties
    - GetPropertyInfo            → Single property detail (unit_id)
    - GetPropertyAmenities       → Amenities for a unit
    - GetPropertyGalleryImages   → Gallery images for a unit
    - GetPropertyRates           → Pricing, fees, taxes for a unit

  RESERVATIONS:
    - GetReservations            → All reservations (return_full:true for guest details)
    - GetReservationInfo         → Full detail: address, taxes/fees, commissions,
                                   payment folio, owner charges, housekeeping schedule
    - GetReservationPrice        → Financial breakdown: fees, payments, security deposits,
                                   owner charges, package addons
    - GetReservationNotes        → Staff notes per reservation (confirmation_id)

  GUEST DATA:
    - GetAllReservationsByEmail  → Guest lookup by email → confirmation_id
    - GetClientReservationsHistory → Full reservation history for a guest (client_id)
    - GetAllFeedback             → All guest feedback/reviews across properties
    - GetGuestReviews            → Reviews (may be empty — use GetAllFeedback)

  OWNER FINANCIALS:
    - GetOwnerList               → Property owner directory
    - GetUnitOwnerBalance        → Current owner balance per unit
    - GetMonthEndStatement       → Monthly owner statement (with optional PDF)

  OPERATIONS:
    - GetHousekeepingCleaningReport → Full housekeeping schedule across units
    - GetWorkOrders              → Maintenance work orders
    - GetBlockedDaysForUnit      → Availability/bookings calendar

  STRIKE 19 (OPTIONAL — ACCOUNT-SPECIFIC):
    - Configured RPC via STREAMLINE_SOVEREIGN_BRIDGE_HOLD_METHOD pushes a sovereign checkout
      hold to Streamline using :meth:`StreamlineVRS.push_sovereign_hold_block` (deferred on
      circuit OPEN). Method name and params require Streamline approval for your token.

  STRIKE 20 (OPTIONAL — ACCOUNT-SPECIFIC):
    - After webhook settlement (hold → reservation), STREAMLINE_SOVEREIGN_BRIDGE_RESERVATION_METHOD
      can notify Streamline via :meth:`StreamlineVRS.dispatch_sovereign_write_rpc`.

  SYSTEM:
    - RenewExpiredToken          → Rotate API credentials

  STILL RESTRICTED (E0014) — request upgrade if needed:
    - GetDocumentList, GetReservationDocuments, GetSignedDocuments
    - GetGuestList, GetGuestNotes
    - GetHousekeepingTasks (use GetHousekeepingCleaningReport instead)
    - GetOwnerStatements (use GetMonthEndStatement instead)

Token auto-renewal is handled transparently.
"""

import asyncio
import re
from datetime import datetime, date, timedelta, timezone
from typing import Dict, List, Optional, Any
from decimal import Decimal

import httpx
import structlog
from tenacity import (
    retry,
    stop_after_attempt,
    wait_exponential,
    retry_if_exception_type,
)

from backend.core.config import settings
from backend.integrations.circuit_breaker import streamline_breaker, CircuitOpenError
from backend.services.property_availability_cache import build_property_availability_snapshot
from backend.integrations.rate_limiter import streamline_limiter

logger = structlog.get_logger()

STREAMLINE_HTTP_TIMEOUT = httpx.Timeout(connect=10, read=60, write=30, pool=30)

_ADMIN_FEE_KEYWORDS = frozenset([
    "damage waiver", "adw", "accidental damage",
    "processing fee", "processing", "administrative fee", "admin fee",
])


def _classify_streamline_fee(name: str) -> str:
    """Classify a Streamline fee as 'admin' or 'lodging' for tax-bucket routing."""
    lower = name.strip().lower()
    for kw in _ADMIN_FEE_KEYWORDS:
        if kw in lower:
            return "admin"
    return "lodging"


class StreamlineVRSError(Exception):
    """Base exception for Streamline VRS integration errors."""
    pass


class StreamlineAuthError(StreamlineVRSError):
    """Authentication failed — token expired or invalid."""
    pass


class StreamlineMethodNotAllowed(StreamlineVRSError):
    """Token does not have permission for this API method."""
    pass


class StreamlineRateLimitError(StreamlineVRSError):
    """API rate limit exceeded — will retry with backoff."""
    pass


def is_streamline_circuit_placeholder(payload: Any) -> bool:
    """Detect the sentinel payload returned when the circuit breaker is open."""
    return (
        isinstance(payload, dict)
        and payload.get("_circuit_open") is True
        and payload.get("_stale") is True
    )


class StreamlineVRS:
    """
    Async Streamline VRS JSON-RPC API client.
    
    All calls go through POST to the single endpoint with:
        { "methodName": "...", "params": { "token_key": ..., "token_secret": ..., ...} }
    """

    def __init__(self):
        self.api_url = settings.streamline_api_url or "https://web.streamlinevrs.com/api/json"
        self.token_key = settings.streamline_api_key
        self.token_secret = settings.streamline_api_secret
        self.sync_interval = settings.streamline_sync_interval
        self.log = logger.bind(service="streamline_vrs")
        self._last_sync: Dict[str, datetime] = {}
        self._token_expires: Optional[date] = None

    @staticmethod
    def _probe_enabled(method: str) -> bool:
        return method in {"GetPropertyRates", "GetBlockedDaysForUnit"}

    @staticmethod
    def _redact_probe_params(params: Dict[str, Any]) -> Dict[str, Any]:
        redacted: Dict[str, Any] = {}
        for key, value in params.items():
            if key in {"token_key", "token_secret"}:
                redacted[key] = "[redacted]"
            else:
                redacted[key] = value
        return redacted

    @property
    def is_configured(self) -> bool:
        """Check if Streamline credentials are set."""
        return bool(self.token_key and self.token_secret)

    async def close(self) -> None:
        """Compatibility hook; each Streamline RPC uses a short-lived ``AsyncClient``."""

    # ================================================================
    # CORE RPC CALLER (Circuit Breaker + Retry)
    # ================================================================

    async def _call(self, method: str, extra_params: Optional[Dict] = None) -> Any:
        """
        Resilient RPC caller — routes through the circuit breaker.

        CLOSED/HALF_OPEN: calls _raw_call() (which has @retry).
        OPEN: fast-fails with a stale-data sentinel dict so the sync
        loop preserves existing DB rows untouched.
        """
        try:
            return await streamline_breaker.call(
                self._raw_call, method, extra_params
            )
        except CircuitOpenError:
            self.log.warning(
                "streamline_circuit_open",
                method=method,
                breaker=streamline_breaker.to_dict(),
                message="Serving stale data from local DB — Streamline unreachable",
            )
            return {"data": {}, "_circuit_open": True, "_stale": True}

    async def _call_with_deferred_write(
        self, method: str, extra_params: Optional[Dict] = None
    ) -> Any:
        """
        Write-aware RPC caller — queues payload if circuit is OPEN.

        For write operations (POST/PUT style RPC calls), this method
        captures the full payload into deferred_api_writes so the
        recovery worker can replay it once the API recovers.
        """
        try:
            return await streamline_breaker.call(
                self._raw_call, method, extra_params
            )
        except CircuitOpenError:
            payload = {
                "methodName": method,
                "params": {
                    "token_key": self.token_key,
                    "token_secret": self.token_secret,
                    **(extra_params or {}),
                },
            }
            try:
                from backend.integrations.circuit_breaker import queue_deferred_write
                queue_id = queue_deferred_write("streamline", method, payload)
                self.log.warning(
                    "streamline_write_deferred",
                    method=method,
                    queue_id=queue_id,
                    message="Write queued for replay — circuit OPEN",
                )
            except Exception as e:
                self.log.error(
                    "streamline_deferred_queue_failed",
                    method=method, error=str(e)[:200],
                )
            return {"data": {}, "_circuit_open": True, "_deferred": True}

    @retry(
        stop=stop_after_attempt(3),
        wait=wait_exponential(multiplier=1, min=1, max=10),
        retry=retry_if_exception_type(
            (httpx.HTTPError, httpx.TimeoutException, StreamlineRateLimitError)
        ),
        reraise=True,
    )
    async def _raw_call(self, method: str, extra_params: Optional[Dict] = None) -> Any:
        """
        Low-level RPC call with tenacity retry.

        Args:
            method: The RPC method name (e.g. "GetPropertyList")
            extra_params: Additional parameters beyond auth tokens

        Returns:
            The 'data' portion of the response

        Raises:
            StreamlineAuthError: Token expired or invalid
            StreamlineMethodNotAllowed: Token lacks permissions
            StreamlineVRSError: General API error
        """
        # Rate limit: acquire a token before hitting the API
        await streamline_limiter.acquire_async(timeout=30.0)

        params = {
            "token_key": self.token_key,
            "token_secret": self.token_secret,
        }
        if extra_params:
            params.update(extra_params)

        payload = {
            "methodName": method,
            "params": params,
        }

        if self._probe_enabled(method):
            self.log.info(
                "streamline_rpc_probe_request",
                method=method,
                api_url=self.api_url,
                params=self._redact_probe_params(params),
                param_types={key: type(value).__name__ for key, value in params.items()},
            )

        async with httpx.AsyncClient(
            timeout=STREAMLINE_HTTP_TIMEOUT,
            follow_redirects=True,
        ) as client:
            try:
                resp = await client.post(self.api_url, json=payload)
            except httpx.TimeoutException as exc:
                self.log.warning(
                    "streamline_rpc_timeout",
                    method=method,
                    error=str(exc),
                )
                raise

            if self._probe_enabled(method):
                self.log.info(
                    "streamline_rpc_probe_response_raw",
                    method=method,
                    status_code=resp.status_code,
                    raw_text=resp.text,
                )

            if resp.status_code == 429:
                raise StreamlineRateLimitError("Rate limited")
            if resp.status_code != 200:
                raise StreamlineVRSError(f"HTTP {resp.status_code}: {resp.text[:200]}")

            data = resp.json()

            # Check for Streamline error codes
            if "status" in data and isinstance(data["status"], dict):
                code = data["status"].get("code", "")
                desc = data["status"].get("description", "")

                if code == "E0015":
                    # Token expired — try to renew (separate short-lived client)
                    self.log.warning("token_expired_renewing", method=method)
                    await self._renew_token()
                    params["token_key"] = self.token_key
                    params["token_secret"] = self.token_secret
                    payload["params"] = params
                    try:
                        resp = await client.post(self.api_url, json=payload)
                    except httpx.TimeoutException as exc:
                        self.log.warning(
                            "streamline_rpc_timeout",
                            method=method,
                            phase="after_token_renewal",
                            error=str(exc),
                        )
                        raise
                    data = resp.json()
                    if "status" in data:
                        raise StreamlineAuthError(f"Auth failed after renewal: {data['status']}")

                elif code == "E0014":
                    raise StreamlineMethodNotAllowed(f"{method}: {desc}")
                elif code.startswith("E"):
                    raise StreamlineVRSError(f"{method} error {code}: {desc}")

            return data.get("data", data)

    async def _renew_token(self):
        """Renew expired API token and update in-memory credentials."""
        payload = {
            "methodName": "RenewExpiredToken",
            "params": {
                "token_key": self.token_key,
                "token_secret": self.token_secret,
            },
        }
        async with httpx.AsyncClient(
            timeout=STREAMLINE_HTTP_TIMEOUT,
            follow_redirects=True,
        ) as client:
            try:
                resp = await client.post(self.api_url, json=payload)
            except httpx.TimeoutException as exc:
                self.log.warning("streamline_token_renew_timeout", error=str(exc))
                raise
        data = resp.json()

        new_data = data.get("data", {})
        if new_data.get("token_key") and new_data.get("token_secret"):
            self.token_key = new_data["token_key"]
            self.token_secret = new_data["token_secret"]
            if new_data.get("enddate"):
                try:
                    self._token_expires = datetime.strptime(new_data["enddate"], "%m/%d/%Y").date()
                except ValueError:
                    pass
            self.log.info(
                "token_renewed",
                expires=str(self._token_expires),
                new_key_prefix=self.token_key[:8] + "...",
            )
        else:
            raise StreamlineAuthError("Token renewal failed — no new credentials returned")

    # ================================================================
    # HEALTH CHECK
    # ================================================================

    async def health_check(self) -> Dict[str, Any]:
        """Verify connectivity to Streamline VRS."""
        breaker_state = streamline_breaker.to_dict()

        if not self.is_configured:
            return {
                "status": "not_configured",
                "message": "Set STREAMLINE_API_KEY and STREAMLINE_API_SECRET in .env",
                "circuit_breaker": breaker_state,
            }

        start = datetime.utcnow()
        try:
            data = await self._call("GetPropertyList")
            latency = (datetime.utcnow() - start).total_seconds() * 1000
            props = data.get("property", []) if isinstance(data, dict) else []
            if isinstance(props, dict):
                props = [props]

            status = "degraded_stale" if data.get("_circuit_open") else "connected"

            return {
                "status": status,
                "latency_ms": round(latency, 1),
                "api_url": self.api_url,
                "properties_found": len(props),
                "token_key": self.token_key[:8] + "...",
                "token_expires": str(self._token_expires) if self._token_expires else "unknown",
                "circuit_breaker": breaker_state,
            }
        except StreamlineAuthError as e:
            return {"status": "auth_failed", "message": str(e), "circuit_breaker": breaker_state}
        except httpx.ConnectError:
            return {"status": "unreachable", "message": f"Cannot reach {self.api_url}", "circuit_breaker": breaker_state}
        except Exception as e:
            return {"status": "error", "message": str(e), "circuit_breaker": breaker_state}

    # ================================================================
    # PROPERTY METHODS
    # ================================================================

    async def fetch_properties(self) -> List[Dict[str, Any]]:
        """
        Fetch all properties from Streamline VRS.
        RPC Method: GetPropertyList
        """
        if not self.is_configured:
            return []

        self.log.info("fetching_properties")
        data = await self._call("GetPropertyList")

        raw_props = data.get("property", []) if isinstance(data, dict) else []
        if isinstance(raw_props, dict):
            raw_props = [raw_props]

        properties = []
        for p in raw_props:
            properties.append(self._map_property(p))

        self.log.info("properties_fetched", count=len(properties))
        self._last_sync["properties"] = datetime.utcnow()
        return properties

    async def fetch_property_detail(self, unit_id: int) -> Dict[str, Any]:
        """
        Fetch detailed info for a single property.
        RPC Method: GetPropertyInfo
        """
        data = await self._call("GetPropertyInfo", {"unit_id": str(unit_id)})
        return data if isinstance(data, dict) else {}

    async def fetch_property_amenities(self, unit_id: int) -> List[Dict]:
        """Fetch amenities for a property. RPC: GetPropertyAmenities"""
        data = await self._call("GetPropertyAmenities", {"unit_id": str(unit_id)})
        amenities = data.get("amenity", []) if isinstance(data, dict) else []
        if isinstance(amenities, dict):
            amenities = [amenities]
        return amenities

    async def fetch_property_gallery(self, unit_id: int) -> List[Dict]:
        """Fetch gallery images for a property. RPC: GetPropertyGalleryImages"""
        data = await self._call("GetPropertyGalleryImages", {"unit_id": str(unit_id)})
        images = data.get("image", []) if isinstance(data, dict) else []
        if isinstance(images, dict):
            images = [images]
        return images

    def _map_property(self, p: Dict) -> Dict[str, Any]:
        """Map Streamline property data to our schema.
        
        Note: GetPropertyList does not return bedrooms/bathrooms.
        Those are enriched via GetPropertyInfo in sync_all().
        """
        return {
            "streamline_property_id": str(p.get("id", "")),
            "name": p.get("name", ""),
            "slug": self._slugify(p.get("name", "")),
            "property_type": self._detect_property_type(p),
            "bedrooms": int(p.get("bedrooms_number", 0)),
            "bathrooms": float(p.get("bathrooms_number", 0)),
            "max_guests": int(p.get("max_occupants", 0)),
            "address": p.get("address", ""),
            "city": p.get("city", ""),
            "state": p.get("state_name", ""),
            "zip_code": p.get("zip", ""),
            "latitude": self._safe_decimal(p.get("location_latitude")),
            "longitude": self._safe_decimal(p.get("location_longitude")),
            "wifi_ssid": p.get("wifi_name") or p.get("name", ""),
            "wifi_password": p.get("wifi_security_key", ""),
            "description": self._clean_html(p.get("description", "")),
            "seo_title": p.get("seo_title", ""),
            "max_pets": int(p.get("max_pets", 0)),
            "status": p.get("status_name", ""),
            "location_area": p.get("location_area_name", ""),
            "resort_area": p.get("location_resort_name", ""),
            "unit_code": p.get("unit_code", ""),
            "company_id": p.get("company_id"),
            "is_active": p.get("status_name", "").lower() == "active",
            "raw": p,
        }

    # ================================================================
    # PROPERTY RATES / FEE STRUCTURES
    # ================================================================

    async def fetch_property_rates(self, unit_id: int) -> Dict[str, Any]:
        """
        Fetch rate card, fees, and tax structure for a property.
        RPC Method: GetPropertyRates
        """
        self.log.info(
            "streamline_property_rates_callsite",
            unit_id=unit_id,
            unit_id_type=type(unit_id).__name__,
        )
        try:
            data = await self._call("GetPropertyRates", {"unit_id": str(unit_id)})
            rates: List[Dict[str, Any]] = []
            fees: List[Dict[str, Any]] = []
            taxes: List[Dict[str, Any]] = []
            payload_shape = type(data).__name__

            def _extract_daily_rates(raw: List[Any]) -> List[Dict[str, Any]]:
                """Normalize Streamline daily-format rate items to the internal schema."""
                result = []
                for row in raw:
                    if not isinstance(row, dict):
                        continue
                    rate_date = row.get("date")
                    nightly_rate = row.get("rate")
                    if not rate_date or nightly_rate in (None, ""):
                        continue
                    result.append(
                        {
                            "name": row.get("season", "") or "streamline_daily_rate",
                            "startdate": rate_date,
                            "enddate": rate_date,
                            "price_nightly": nightly_rate,
                            "price_weekly": None,
                            "price_monthly": None,
                            "minimum_days": row.get("minStay"),
                            "booked": row.get("booked"),
                            "change_over": row.get("changeOver"),
                        }
                    )
                return result

            if isinstance(data, list):
                # Bare list: only daily rate data, no fee/tax metadata.
                payload_shape = "daily_rate_list"
                rates = _extract_daily_rates(data)

            elif isinstance(data, dict):
                # Dict wrapper: may contain daily-rate OR season-range items in
                # "rate", plus fee and tax line items in "fee"/"tax".
                raw_rates = data.get("rate", [])
                if isinstance(raw_rates, dict):
                    raw_rates = [raw_rates]

                # Detect daily format by the presence of a "date" field on the
                # first item (daily: {"date":…,"rate":…} vs season: {"startdate":…,"price_nightly":…}).
                first = next((r for r in raw_rates if isinstance(r, dict)), {})
                if first.get("date") is not None:
                    payload_shape = "daily_rate_list"
                    rates = _extract_daily_rates(raw_rates)
                else:
                    rates = raw_rates

                fees = data.get("fee", [])
                if isinstance(fees, dict):
                    fees = [fees]

                taxes = data.get("tax", [])
                if isinstance(taxes, dict):
                    taxes = [taxes]

                self.log.debug(
                    "property_rates_dict_shape",
                    unit_id=unit_id,
                    payload_shape=payload_shape,
                    raw_fee_count=len(fees),
                    raw_tax_count=len(taxes),
                    fee_names=[f.get("name") for f in fees],
                )
            else:
                return {}

            rate_card = {
                "rates": [
                    {
                        "name": r.get("name", ""),
                        "start_date": r.get("startdate"),
                        "end_date": r.get("enddate"),
                        "nightly": r.get("price_nightly"),
                        "weekly": r.get("price_weekly"),
                        "monthly": r.get("price_monthly"),
                        "min_nights": r.get("minimum_days"),
                        "booked": r.get("booked"),
                        "change_over": r.get("change_over"),
                    }
                    for r in rates
                ],
                "fees": [
                    {
                        "name": f.get("name", ""),
                        "amount": f.get("amount"),
                        "type": f.get("type_name", ""),
                        "taxable": f.get("taxable"),
                        "category": _classify_streamline_fee(f.get("name", "")),
                    }
                    for f in fees
                ],
                "taxes": [
                    {
                        "name": t.get("name", ""),
                        "rate": t.get("rate"),
                        "type": t.get("type_name", ""),
                    }
                    for t in taxes
                ],
                "payload_shape": payload_shape,
                "synced_at": datetime.utcnow().isoformat(),
            }

            self.log.info(
                "property_rates_fetched",
                unit_id=unit_id,
                payload_shape=payload_shape,
                rates=len(rate_card["rates"]),
                fees=len(rate_card["fees"]),
                taxes=len(rate_card["taxes"]),
            )
            return rate_card

        except StreamlineMethodNotAllowed:
            self.log.warning("property_rates_not_allowed", unit_id=unit_id)
            return {}
        except Exception as e:
            self.log.warning("property_rates_error", unit_id=unit_id, error=str(e))
            return {}

    # ================================================================
    # AVAILABILITY / BLOCKED DAYS
    # ================================================================

    async def fetch_blocked_days(
        self,
        unit_id: int,
        start_date: Optional[date] = None,
        end_date: Optional[date] = None,
    ) -> List[Dict[str, Any]]:
        """
        Fetch booked/blocked days for a property.
        RPC Method: GetBlockedDaysForUnit
        
        Returns list of booking blocks with dates and types.
        """
        if not start_date:
            start_date = date.today() - timedelta(days=30)
        if not end_date:
            end_date = date.today() + timedelta(days=730)

        self.log.info(
            "streamline_blocked_days_callsite",
            unit_id=unit_id,
            unit_id_type=type(unit_id).__name__,
            start_date=str(start_date),
            start_date_type=type(start_date).__name__,
            end_date=str(end_date),
            end_date_type=type(end_date).__name__,
        )

        data = await self._call("GetBlockedDaysForUnit", {
            "unit_id": str(unit_id),
            "startdate": start_date.strftime("%m/%d/%Y"),
            "enddate": end_date.strftime("%m/%d/%Y"),
        })

        blocked = []
        raw_blocked: Any = []
        if isinstance(data, dict):
            blocked_days = data.get("blocked_days", [])
            if isinstance(blocked_days, dict):
                raw_blocked = blocked_days.get("blocked", [])
            elif isinstance(blocked_days, list):
                raw_blocked = blocked_days
            else:
                raw_blocked = []
        elif isinstance(data, list):
            raw_blocked = data

        if isinstance(raw_blocked, dict):
            raw_blocked = [raw_blocked]

        for b in raw_blocked:
            if not isinstance(b, dict):
                continue
            blocked.append({
                "confirmation_id": b.get("confirmation_id"),
                "start_date": self._parse_streamline_date(b.get("startdate")),
                "end_date": self._parse_streamline_date(b.get("enddate")),
                "checkout_date": self._parse_streamline_date(b.get("checkout")),
                "type_name": b.get("type_name", ""),
                "type_description": b.get("type_description", ""),
            })

        self.log.info("blocked_days_fetched", unit_id=unit_id, count=len(blocked))
        return blocked

    async def dispatch_sovereign_write_rpc(
        self,
        rpc_method: str,
        extra_params: Dict[str, Any],
        *,
        log_name: str = "sovereign_bridge_write",
        log_context: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        """
        Shared write path for Strike 19/20 optional Streamline RPC (deferred on circuit OPEN).

        Does not raise for E0014 / general RPC errors; returns a structured dict for callers.
        """
        method = (rpc_method or "").strip()
        if not self.is_configured or not method:
            return {"ok": False, "skipped": True, "reason": "not_configured_or_method_empty"}

        ctx = {"bridge_kind": log_name, **(log_context or {})}
        try:
            data = await self._call_with_deferred_write(method, extra_params)
            if isinstance(data, dict) and data.get("_deferred"):
                return {"ok": True, "deferred": True, "method": method}
            return {"ok": True, "deferred": False, "method": method, "data": data}
        except StreamlineMethodNotAllowed as exc:
            self.log.warning(
                "sovereign_bridge_write_method_denied",
                method=method,
                error=str(exc),
                **ctx,
            )
            return {"ok": False, "skipped": True, "reason": "method_not_allowed", "error": str(exc)}
        except StreamlineVRSError as exc:
            self.log.warning(
                "sovereign_bridge_write_rpc_error",
                method=method,
                error=str(exc),
                **ctx,
            )
            return {"ok": False, "skipped": False, "reason": "rpc_error", "error": str(exc)}

    async def replay_queued_rpc_payload(
        self,
        queued_body: Optional[Dict[str, Any]] = None,
        *,
        payload: Optional[Dict[str, Any]] = None,
        method_override: Optional[str] = None,
    ) -> Any:
        """
        Replay a full JSON-RPC body from ``deferred_api_writes`` using **current** Streamline tokens.

        Strips stale ``token_key`` / ``token_secret`` from stored params so rotation does not require
        re-queuing. Routes through the circuit breaker like normal writes.

        Pass either ``queued_body`` (positional) or keyword ``payload``. ``method_override`` replaces
        ``methodName`` when the row's ``method`` column is authoritative.
        """
        body = queued_body if queued_body is not None else payload
        if not isinstance(body, dict):
            raise StreamlineVRSError("payload required and must be a dict")
        merged: Dict[str, Any] = dict(body)
        if method_override and str(method_override).strip():
            merged["methodName"] = str(method_override).strip()
        if not self.is_configured:
            raise StreamlineVRSError("Streamline not configured")
        method = str(merged.get("methodName") or "").strip()
        raw_params = merged.get("params")
        if not method or not isinstance(raw_params, dict):
            raise StreamlineVRSError("Invalid deferred RPC payload shape")
        extra_params = {
            k: v
            for k, v in raw_params.items()
            if k not in ("token_key", "token_secret")
        }
        return await streamline_breaker.call(self._raw_call, method, extra_params)

    async def push_sovereign_hold_block(
        self,
        unit_id: int,
        check_in: date,
        check_out: date,
        *,
        note: str = "SOVEREIGN_CHECKOUT_IN_PROGRESS",
        hold_duration_minutes: int = 15,
        rpc_method: str,
    ) -> Dict[str, Any]:
        """
        Strike 19 — optional write bridge: notify Streamline of an in-progress sovereign hold.

        ``rpc_method`` is the Streamline ``methodName`` (varies by API tier). Params use the
        same date style as ``GetBlockedDaysForUnit``. On circuit OPEN, the payload is deferred
        for replay via :meth:`_call_with_deferred_write`.

        Returns a small result dict (never raises for method-not-allowed — callers log and continue).
        """
        extra_params: Dict[str, Any] = {
            "unit_id": str(unit_id),
            "startdate": check_in.strftime("%m/%d/%Y"),
            "enddate": check_out.strftime("%m/%d/%Y"),
            "notes": note,
            "hold_duration_minutes": str(int(hold_duration_minutes)),
        }
        return await self.dispatch_sovereign_write_rpc(
            rpc_method,
            extra_params,
            log_name="sovereign_bridge_hold",
            log_context={"unit_id": unit_id},
        )

    # ================================================================
    # WORK ORDERS
    # ================================================================

    async def fetch_work_orders(self) -> List[Dict[str, Any]]:
        """
        Fetch maintenance work orders from Streamline.
        RPC Method: GetWorkOrders
        """
        data = await self._call("GetWorkOrders")

        raw_wos = []
        if isinstance(data, dict):
            m = data.get("maintenances", {})
            if isinstance(m, dict):
                raw_wos = m.get("maintenance", [])
                if isinstance(raw_wos, dict):
                    raw_wos = [raw_wos]

        work_orders = []
        for w in raw_wos:
            work_orders.append({
                "streamline_id": w.get("id"),
                "unit_id": w.get("unit_id"),
                "address": w.get("address", ""),
                "unit_name": w.get("unit_name", ""),
                "subject": w.get("subject", ""),
                "description": w.get("description", ""),
                "status": w.get("status_description", ""),
                "priority": w.get("priority_description", ""),
                "category": w.get("category_description", ""),
                "created_date": w.get("date_created"),
                "due_date": w.get("date_due"),
            })

        self.log.info("work_orders_fetched", count=len(work_orders))
        self._last_sync["work_orders"] = datetime.utcnow()
        return work_orders

    # ================================================================
    # RESERVATIONS  (newly granted permissions)
    # ================================================================

    async def fetch_reservations(
        self,
        start_date: Optional[date] = None,
        end_date: Optional[date] = None,
    ) -> List[Dict[str, Any]]:
        """
        Fetch reservations with full guest details.
        RPC Method: GetReservations  (return_full:true)

        The upgraded token grants access to this method.  Falls back
        gracefully if still restricted (E0014).
        """
        if not self.is_configured:
            return []

        if not start_date:
            start_date = date.today() - timedelta(days=30)
        if not end_date:
            end_date = date.today() + timedelta(days=90)

        try:
            all_reservations = []
            seen_ids: set = set()
            page = 1

            while True:
                data = await self._call("GetReservations", {
                    "startdate": start_date.strftime("%m/%d/%Y"),
                    "enddate": end_date.strftime("%m/%d/%Y"),
                    "return_full": "true",
                    "page": str(page),
                })

                raw = data.get("reservations", []) if isinstance(data, dict) else []
                if isinstance(raw, dict):
                    raw = [raw]

                for r in raw:
                    res_id = str(r.get("confirmation_id", r.get("id", "")))
                    if res_id and res_id in seen_ids:
                        continue
                    seen_ids.add(res_id)
                    all_reservations.append(self._map_reservation(r))

                pagination = data.get("pagination", {}) if isinstance(data, dict) else {}
                total_pages = int(pagination.get("total_pages", 1))
                if page >= total_pages:
                    break
                page += 1

        except StreamlineMethodNotAllowed:
            self.log.warning(
                "reservations_still_restricted",
                hint="Token doesn't have GetReservations — contact Streamline support",
            )
            return []

        self.log.info(
            "reservations_fetched",
            count=len(all_reservations),
            pages=page,
        )
        self._last_sync["reservations"] = datetime.utcnow()
        return all_reservations

    async def fetch_reservations_by_property(
        self, unit_id: int, start_date: Optional[date] = None, end_date: Optional[date] = None,
    ) -> List[Dict[str, Any]]:
        """Fetch reservations for a single property."""
        if not start_date:
            start_date = date.today() - timedelta(days=7)
        if not end_date:
            end_date = date.today() + timedelta(days=90)

        try:
            data = await self._call("GetReservations", {
                "unit_id": str(unit_id),
                "startdate": start_date.strftime("%m/%d/%Y"),
                "enddate": end_date.strftime("%m/%d/%Y"),
                "return_full": "true",
            })
        except StreamlineMethodNotAllowed:
            return []

        raw = data.get("reservations", []) if isinstance(data, dict) else []
        if isinstance(raw, dict):
            raw = [raw]
        return [self._map_reservation(r) for r in raw]

    @staticmethod
    def detect_owner_booking(r: Dict) -> bool:
        """
        Return True when any of Streamline's three owner-booking signals are present.

        Signals checked (ANY one is sufficient):
          1. maketype_name == 'O'
          2. type_name == 'OWN'
          3. flags array contains a flag named 'OWNER RES' (case-insensitive)

        Works with responses from both GetReservations (list) and
        GetReservationInfo (detail) — only the signals present in the given
        dict are evaluated; missing keys default to non-owner.

        Every code path that needs to evaluate "is this an owner booking?"
        must call this method rather than duplicating the logic.
        """
        if r.get("maketype_name", "") == "O":
            return True
        if r.get("type_name", "") == "OWN":
            return True
        flags_wrapper = r.get("flags", {})
        if isinstance(flags_wrapper, dict):
            flag_list = flags_wrapper.get("flag", [])
        else:
            flag_list = []
        if isinstance(flag_list, dict):
            flag_list = [flag_list]
        flag_names = {
            str(f.get("name", "")).upper()
            for f in flag_list
            if isinstance(f, dict)
        }
        return "OWNER RES" in flag_names

    def _map_reservation(self, r: Dict) -> Dict[str, Any]:
        """Map Streamline reservation JSON to our schema.

        Actual API fields (GetReservations return_full:true):
          confirmation_id, unit_id, startdate, enddate, status_code,
          occupants, occupants_small, pets, price_total, price_paidsum,
          price_balance, first_name, last_name, email, phone, mobile_phone,
          address, city, state_name, zip, client_comments, kabacode,
          unit_name, maketype_name, hear_about_name
        """
        occupants = int(r.get("occupants", 0))
        occupants_small = int(r.get("occupants_small", 0))

        status_code = str(r.get("status_code", ""))
        # Streamline status codes:
        # 1=Confirmed, 2=Checked-In, 3=Checked-Out, 4=Cancelled,
        # 5=Quote, 6=On-Hold, 7=Reserved, 8=No-Show, 9=Declined/Fraud
        status_map = {
            "1": "confirmed", "2": "checked_in", "3": "checked_out",
            "4": "cancelled", "5": "pending", "6": "on_hold",
            "7": "confirmed", "8": "no_show", "9": "cancelled",
        }

        price_total = self._safe_decimal(r.get("price_total"))
        price_nightly = self._safe_decimal(r.get("price_nightly"))
        price_common = self._safe_decimal(r.get("price_common"))
        days = int(r.get("days_number", 0))

        price_breakdown = {
            "price_total": str(price_total) if price_total else None,
            "price_nightly": str(price_nightly) if price_nightly else None,
            "price_common": str(price_common) if price_common else None,
            "price_paidsum": str(self._safe_decimal(r.get("price_paidsum"))),
            "price_balance": str(self._safe_decimal(r.get("price_balance"))),
            "days_number": days,
            "tax_exempt": r.get("tax_exempt"),
            "pricing_model": r.get("pricing_model"),
            "coupon_code": r.get("coupon_code"),
        }

        return {
            "streamline_reservation_id": str(r.get("confirmation_id", r.get("id", ""))),
            "unit_id": str(r.get("unit_id", "")),
            "status": status_map.get(status_code, "confirmed"),
            "check_in_date": self._parse_streamline_date(r.get("startdate")),
            "check_out_date": self._parse_streamline_date(r.get("enddate")),
            "num_guests": occupants + occupants_small,
            "num_adults": occupants,
            "num_children": occupants_small,
            "num_pets": int(r.get("pets", 0)),
            "total_amount": price_total,
            "paid_amount": self._safe_decimal(r.get("price_paidsum")),
            "balance_due": self._safe_decimal(r.get("price_balance")),
            "nightly_rate": price_nightly,
            "nights_count": days if days > 0 else None,
            "price_breakdown": price_breakdown,
            "access_code": r.get("kabacode"),
            "special_requests": r.get("client_comments", ""),
            "source": r.get("hear_about_name") or r.get("maketype_name", ""),
            # detect_owner_booking() checks all three Streamline owner signals:
            #   maketype_name=='O', type_name=='OWN', 'OWNER RES' flag.
            # This replaces the earlier single-signal check and correctly
            # catches reservation 54029 (maketype_name='A', type_name='OWN').
            "is_owner_booking": self.detect_owner_booking(r),
            "guest_first_name": r.get("first_name", ""),
            "guest_last_name": r.get("last_name", ""),
            "guest_email": r.get("email", ""),
            "guest_phone": r.get("phone", "") or r.get("mobile_phone", ""),
            "guest_address": r.get("address", ""),
            "guest_city": r.get("city", ""),
            "guest_state": r.get("state_name", ""),
            "guest_zip": r.get("zip", ""),
            "raw": r,
        }

    # ================================================================
    # LEADS / INQUIRIES (Quote-status reservations + guest comments)
    # ================================================================

    async def fetch_historical_leads(
        self,
        start_date: Optional[date] = None,
        end_date: Optional[date] = None,
        limit: int = 50,
        include_notes: bool = True,
    ) -> List[Dict[str, Any]]:
        """
        Fetch historical lead/inquiry data from Streamline.

        Streamline has no dedicated GetLeads endpoint. Instead, we extract
        lead-quality data from two sources:
          1. Reservations with status_code=5 (Quote) — explicit inquiries
          2. Any reservation whose client_comments field is non-empty —
             these contain the guest's original booking message

        Each record is enriched with staff notes (GetReservationNotes) to
        capture agent responses, creating a guest-inquiry ↔ staff-reply
        training pair.

        Args:
            start_date: Window start (default: 365 days ago)
            end_date:   Window end (default: today + 30 days)
            limit:      Max records to return
            include_notes: Also fetch per-reservation staff notes
        """
        if not self.is_configured:
            return []

        if not start_date:
            start_date = date.today() - timedelta(days=365)
        if not end_date:
            end_date = date.today() + timedelta(days=30)

        self.log.info(
            "fetching_historical_leads",
            start=start_date.isoformat(),
            end=end_date.isoformat(),
            limit=limit,
        )

        all_raw: List[Dict] = []
        seen_ids: set = set()
        page = 1

        while True:
            try:
                data = await self._call("GetReservations", {
                    "startdate": start_date.strftime("%m/%d/%Y"),
                    "enddate": end_date.strftime("%m/%d/%Y"),
                    "return_full": "true",
                    "page": str(page),
                })
            except Exception as e:
                self.log.error("lead_fetch_page_error", page=page, error=str(e))
                break

            raw = data.get("reservations", []) if isinstance(data, dict) else []
            if isinstance(raw, dict):
                raw = [raw]
            if not raw:
                break

            for r in raw:
                cid = str(r.get("confirmation_id", r.get("id", "")))
                if not cid or cid in seen_ids:
                    continue
                seen_ids.add(cid)

                status_code = str(r.get("status_code", ""))
                client_comments = (r.get("client_comments") or "").strip()

                # Keep quotes (status 5) OR any record with a guest message
                if status_code == "5" or client_comments:
                    all_raw.append(r)

            pagination = data.get("pagination", {}) if isinstance(data, dict) else {}
            total_pages = int(pagination.get("total_pages", 1))
            if page >= total_pages:
                break
            page += 1

        self.log.info("lead_candidates_found", count=len(all_raw))

        # Map and optionally enrich with staff notes
        leads = []
        for r in all_raw[:limit]:
            mapped = self._map_reservation(r)
            mapped["is_quote_status"] = str(r.get("status_code", "")) == "5"

            if include_notes:
                cid = mapped["streamline_reservation_id"]
                try:
                    notes = await self.fetch_reservation_notes(cid)
                    mapped["staff_notes"] = notes
                except Exception:
                    mapped["staff_notes"] = []
            else:
                mapped["staff_notes"] = []

            leads.append(mapped)

        self.log.info("historical_leads_extracted", count=len(leads))
        return leads

    # ================================================================
    # OWNER DATA
    # ================================================================

    async def fetch_owners(self) -> List[Dict[str, Any]]:
        """
        Fetch property owner directory.
        RPC Method: GetOwnerList
        """
        data = await self._call("GetOwnerList")

        raw_owners = data.get("owner", []) if isinstance(data, dict) else []
        if isinstance(raw_owners, dict):
            raw_owners = [raw_owners]

        owners = []
        for o in raw_owners:
            owners.append({
                "owner_id": o.get("owner_id"),
                "first_name": o.get("first_name", ""),
                "last_name": o.get("last_name", ""),
                "email": o.get("email", ""),
                "phone": o.get("phone", ""),
                "company": o.get("company_name", ""),
            })

        self.log.info("owners_fetched", count=len(owners))
        return owners

    async def fetch_owner_info(self, owner_id: int) -> Dict[str, Any]:
        """
        Fetch full owner record including mailing address.
        RPC Method: GetOwnerInfo

        Returns a dict with keys:
          owner_id, first_name, last_name, email,
          address1, address2, city, state, zip, country,
          mobile_phone, company
          units: list of {id, name} dicts for each unit this owner manages.

        Returns {} if the owner is not found or the call fails.
        """
        try:
            data = await self._call("GetOwnerInfo", {"owner_id": str(owner_id)})
        except Exception as exc:
            self.log.warning("fetch_owner_info_failed", owner_id=owner_id, error=str(exc)[:120])
            return {}

        # GetOwnerInfo returns the owner record under key "id" (not "owner_id")
        if not isinstance(data, dict) or not data.get("id"):
            return {}

        # Normalise address2 and other optional fields — Streamline returns {} for empty
        def _str(v: Any) -> str:
            return str(v) if v and not isinstance(v, dict) else ""

        # Unpack units list
        raw_units = data.get("units", {})
        units_list: list[dict] = []
        if isinstance(raw_units, dict):
            raw_unit = raw_units.get("unit", [])
            if isinstance(raw_unit, dict):
                raw_unit = [raw_unit]
            for u in raw_unit:
                if isinstance(u, dict):
                    units_list.append({"id": u.get("id"), "name": _str(u.get("name"))})

        first  = _str(data.get("first_name"))
        last   = _str(data.get("last_name"))
        middle = _str(data.get("middle_name"))

        # Streamline displays names in last-first-middle order on statements.
        # Assemble accordingly; omit middle when blank.
        parts = [p for p in [last, middle, first] if p]
        display_name = " ".join(parts) if parts else _str(data.get("email"))

        return {
            "owner_id":    data.get("id"),    # GetOwnerInfo returns "id", not "owner_id"
            "first_name":  first,
            "last_name":   last,
            "middle_name": middle,
            "display_name": display_name,     # last-middle-first, e.g. "Knight Mitchell Gary"
            "email":       _str(data.get("email")),
            "address1":    _str(data.get("address1")),
            "address2":    _str(data.get("address2")),
            "city":        _str(data.get("city")),
            "state":       _str(data.get("state_name")),
            "zip":         _str(data.get("zip")),
            "country":     _str(data.get("country_name")) or "USA",
            "mobile_phone": _str(data.get("mobile_phone")),
            "company":     _str(data.get("company_name")),
            "units":       units_list,
        }

    # ================================================================
    # GUEST REVIEWS
    # ================================================================

    async def fetch_reviews(self, unit_id: Optional[int] = None) -> List[Dict]:
        """
        Fetch guest reviews, optionally filtered by unit.
        RPC Method: GetGuestReviews
        """
        params = {}
        if unit_id:
            params["unit_id"] = str(unit_id)

        data = await self._call("GetGuestReviews", params)
        reviews = data.get("review", []) if isinstance(data, dict) else []
        if isinstance(reviews, dict):
            reviews = [reviews]
        return reviews

    # ================================================================
    # RESERVATION DETAIL / FINANCIAL  (from Ben Sell email 2026-02-16)
    # ================================================================

    async def fetch_reservation_info(self, confirmation_id: str) -> Dict[str, Any]:
        """
        Fetch full reservation detail including taxes, fees, commissions,
        payment folio, owner charges, and housekeeping schedule.
        RPC Method: GetReservationInfo
        """
        try:
            data = await self._call("GetReservationInfo", {
                "confirmation_id": confirmation_id,
                "return_address": "1",
                "return_flags": "1",
                "show_owner_charges": "1",
                "show_taxes_and_fees": "1",
                "show_commission_information": "1",
                "return_payments": "1",
                "return_additional_fields": "1",
                "show_payments_folio_history": "1",
                "include_security_deposit": "1",
                "return_housekeeping_schedule": "1",
                "show_guest_feedback_url": "1",
            })
            return data if isinstance(data, dict) else {}
        except Exception as e:
            self.log.warning("reservation_info_error",
                             confirmation_id=confirmation_id, error=str(e))
            return {}

    async def fetch_reservation_price(self, confirmation_id: str) -> Dict[str, Any]:
        """
        Fetch financial breakdown: fees, payments, security deposits,
        owner charges, and package addons.
        RPC Method: GetReservationPrice
        """
        try:
            data = await self._call("GetReservationPrice", {
                "confirmation_id": confirmation_id,
                "show_bundled_fees": "1",
                "show_security_deposit_information": "1",
                "show_resort_information": "1",
                "return_payments": "1",
                "show_payments_folio_history": "true",
                "show_owner_charges": "1",
                "show_package_addons": "1",
                "updated_expected_charges": "1",
            })
            return data if isinstance(data, dict) else {}
        except Exception as e:
            self.log.warning("reservation_price_error",
                             confirmation_id=confirmation_id, error=str(e))
            return {}

    # ================================================================
    # GUEST DATA
    # ================================================================

    async def fetch_guest_by_email(self, email: str) -> Optional[Dict[str, Any]]:
        """
        Lookup a guest's most recent reservation by email.
        RPC Method: GetAllReservationsByEmail
        """
        try:
            data = await self._call("GetAllReservationsByEmail", {"email": email})
            return data if isinstance(data, dict) else None
        except Exception as e:
            self.log.debug("guest_by_email_error", email=email, error=str(e))
            return None

    async def fetch_guest_history(self, client_id: str) -> List[Dict[str, Any]]:
        """
        Fetch a guest's full reservation history.
        RPC Method: GetClientReservationsHistory
        """
        try:
            data = await self._call("GetClientReservationsHistory", {
                "client_id": client_id,
            })
            history = data.get("history", []) if isinstance(data, dict) else []
            if isinstance(history, dict):
                history = [history]
            return history
        except Exception as e:
            self.log.warning("guest_history_error", client_id=client_id, error=str(e))
            return []

    async def fetch_all_feedback(self) -> List[Dict[str, Any]]:
        """
        Fetch all guest feedback/reviews across all properties.
        RPC Method: GetAllFeedback
        """
        try:
            data = await self._call("GetAllFeedback")
            comments = data.get("comments", []) if isinstance(data, dict) else []
            if isinstance(comments, dict):
                comments = [comments]
            self.log.info("all_feedback_fetched", count=len(comments))
            return comments
        except Exception as e:
            self.log.warning("all_feedback_error", error=str(e))
            return []

    # ================================================================
    # OWNER FINANCIALS
    # ================================================================

    async def fetch_unit_owner_balance(self, unit_id: int) -> Dict[str, Any]:
        """
        Fetch the current owner balance for a unit.
        RPC Method: GetUnitOwnerBalance
        """
        try:
            data = await self._call("GetUnitOwnerBalance", {
                "unit_id": str(unit_id),
            })
            return data if isinstance(data, dict) else {}
        except Exception as e:
            self.log.warning("owner_balance_error", unit_id=unit_id, error=str(e))
            return {}

    async def fetch_owner_statement(
        self,
        owner_id: int,
        unit_id: Optional[int] = None,
        start_date: Optional[date] = None,
        end_date: Optional[date] = None,
        include_pdf: bool = False,
    ) -> Dict[str, Any]:
        """
        Fetch monthly owner statement.
        RPC Method: GetMonthEndStatement

        Args:
            owner_id: Streamline owner ID (from GetOwnerList)
            unit_id: Optional unit filter
            start_date/end_date: Statement period
            include_pdf: If True, returns PDF; if False, skips PDF for speed
        """
        if not start_date:
            start_date = date.today().replace(day=1) - timedelta(days=1)
            start_date = start_date.replace(day=1)
        if not end_date:
            end_date = (start_date.replace(day=28) + timedelta(days=4)).replace(day=1) - timedelta(days=1)

        params: Dict[str, Any] = {
            "owner_id": str(owner_id),
            "status_id": "1",
            "skip_pdf": "0" if include_pdf else "1",
            "startdate": start_date.strftime("%m/%d/%y"),
            "enddate": end_date.strftime("%m/%d/%y"),
        }
        if unit_id:
            params["unit_id"] = str(unit_id)

        try:
            data = await self._call("GetMonthEndStatement", params)
            return data if isinstance(data, dict) else {}
        except Exception as e:
            self.log.warning("owner_statement_error",
                             owner_id=owner_id, error=str(e))
            return {}

    # ================================================================
    # HOUSEKEEPING
    # ================================================================

    async def fetch_housekeeping_report(
        self, unit_id: Optional[int] = None,
    ) -> Dict[str, Any]:
        """
        Fetch the full housekeeping/cleaning schedule.
        RPC Method: GetHousekeepingCleaningReport

        Returns reservations with cleaning dates, types, statuses,
        and unit-level housekeeping status.
        """
        params = {}
        if unit_id:
            params["unit_id"] = str(unit_id)

        try:
            data = await self._call("GetHousekeepingCleaningReport", params)
            return data if isinstance(data, dict) else {}
        except Exception as e:
            self.log.warning("housekeeping_report_error", error=str(e))
            return {}

    # ================================================================
    # RESERVATION NOTES  (granted — uses confirmation_id param)
    # ================================================================

    async def fetch_reservation_notes(self, confirmation_id: str) -> List[Dict[str, Any]]:
        """
        Fetch staff/internal notes for a reservation.
        RPC Method: GetReservationNotes

        Returns list of note dicts:
          {processor_name, creation_date, message, schedule_follow_up}
        """
        if not self.is_configured:
            return []
        try:
            data = await self._call("GetReservationNotes", {
                "confirmation_id": confirmation_id,
            })
            notes = data.get("notes", []) if isinstance(data, dict) else []
            if isinstance(notes, dict):
                notes = [notes]
            return notes
        except StreamlineMethodNotAllowed:
            self.log.warning("reservation_notes_not_allowed")
            return []
        except Exception as e:
            self.log.debug("reservation_notes_error",
                           confirmation_id=confirmation_id, error=str(e))
            return []

    # ================================================================
    # DOCUMENTS / AGREEMENTS  (requires token upgrade — E0014 until granted)
    # ================================================================

    async def fetch_reservation_documents(self, confirmation_id: str) -> List[Dict[str, Any]]:
        """
        Fetch signed documents/agreements for a specific reservation.
        RPC Method: GetReservationDocuments
        
        Requires token permission upgrade from Streamline support.
        Returns empty list if method is not allowed (E0014).
        """
        try:
            data = await self._call("GetReservationDocuments", {
                "confirmation_id": confirmation_id,
            })
            docs = data.get("documents", []) if isinstance(data, dict) else []
            if isinstance(docs, dict):
                docs = [docs]
            self.log.info("reservation_documents_fetched",
                          confirmation_id=confirmation_id, count=len(docs))
            return docs
        except StreamlineMethodNotAllowed:
            return []
        except Exception as e:
            self.log.warning("reservation_documents_error",
                             confirmation_id=confirmation_id, error=str(e))
            return []

    async def fetch_all_documents(self) -> List[Dict[str, Any]]:
        """
        Fetch all managed documents (StreamSign).
        RPC Method: GetDocumentList
        
        Requires token permission upgrade from Streamline support.
        """
        try:
            data = await self._call("GetDocumentList")
            docs = data.get("documents", []) if isinstance(data, dict) else []
            if isinstance(docs, dict):
                docs = [docs]
            self.log.info("all_documents_fetched", count=len(docs))
            return docs
        except StreamlineMethodNotAllowed:
            self.log.warning(
                "documents_not_allowed",
                hint="Token needs GetDocumentList / GetReservationDocuments permissions. "
                     "Contact Streamline support to upgrade.",
            )
            return []

    # ================================================================
    # DATABASE SYNC ENGINE
    # ================================================================

    async def sync_property_availability(self, db) -> Dict[str, Any]:
        """
        Compatibility wrapper for the ARQ availability loop.

        Syncs only blocked-day availability for properties already mapped into the
        local database and returns the historical summary shape consumed by the
        worker logs.
        """
        from sqlalchemy import select, text as sa_text_p3
        from backend.models import Property

        if not self.is_configured:
            return {"status": "skipped", "reason": "Streamline VRS not configured", "synced": 0, "skipped": 0, "bookings_found": 0}

        summary = {"synced": 0, "skipped": 0, "bookings_found": 0}
        remote_properties = await self.fetch_properties()

        for rp in remote_properties:
            try:
                sl_id = rp["streamline_property_id"]
                unit_id = int(sl_id)
                prop_result = await db.execute(
                    select(Property).where(Property.streamline_property_id == sl_id)
                )
                local_prop = prop_result.scalar_one_or_none()
                if not local_prop:
                    summary["skipped"] += 1
                    continue

                blocked = await self.fetch_blocked_days(unit_id)
                for b in blocked:
                    if not b.get("start_date") or not b.get("end_date"):
                        continue
                    block_type = (b.get("type_name") or "reservation").lower().replace(" ", "_")
                    await db.execute(
                        sa_text_p3("""
                            INSERT INTO blocked_days
                                (id, property_id, start_date, end_date, block_type,
                                 confirmation_code, source, created_at, updated_at)
                            VALUES
                                (gen_random_uuid(), :pid, :sd, :ed, :bt, :cc,
                                 'streamline', NOW(), NOW())
                            ON CONFLICT (property_id, start_date, end_date, block_type)
                            DO UPDATE SET
                                confirmation_code = EXCLUDED.confirmation_code,
                                updated_at = NOW()
                        """),
                        {
                            "pid": str(local_prop.id),
                            "sd": b["start_date"],
                            "ed": b["end_date"],
                            "bt": block_type[:50],
                            "cc": str(b.get("confirmation_id") or "")[:50] or None,
                        },
                    )
                await db.commit()
                summary["synced"] += 1
                summary["bookings_found"] += len(blocked)
            except StreamlineMethodNotAllowed:
                break
            except Exception:
                await db.rollback()
                raise

        return summary

    async def sync_all(self, db) -> Dict[str, Any]:
        """
        Full sync: Streamline VRS -> FGP database.

        Sync order:
          1. Properties (with detail enrichment)
          2. Reservations + Guests (from GetReservations return_full:true)
          3. Blocked days / availability per property
          4. Work orders
        """
        from backend.models import Property, WorkOrder, Reservation, Guest

        if not self.is_configured:
            return {"status": "skipped", "reason": "Streamline VRS not configured"}

        summary = {
            "started_at": datetime.utcnow().isoformat(),
            "properties": {"created": 0, "updated": 0, "errors": 0},
            "reservations": {"created": 0, "updated": 0, "guests_created": 0, "errors": 0},
            "notes": {"synced": 0, "skipped": 0, "errors": 0},
            "availability": {"synced": 0, "bookings_found": 0},
            "work_orders": {"created": 0, "updated": 0, "errors": 0},
            "agreements": {"generated": 0, "skipped": 0, "from_streamline": 0, "errors": 0},
            "errors": [],
        }

        try:
            # ---- Phase 1: Sync Properties ----
            self.log.info("sync_phase_1_properties")
            remote_properties = await self.fetch_properties()
            reindex_property_ids: set[str] = set()

            from sqlalchemy import select

            for rp in remote_properties:
                try:
                    sl_id = rp["streamline_property_id"]
                    result = await db.execute(
                        select(Property).where(
                            Property.streamline_property_id == sl_id
                        )
                    )
                    existing = result.scalar_one_or_none()

                    if existing:
                        property_changed = False
                        # Update mutable fields
                        for field in [
                            "name", "max_guests", "address",
                            "latitude", "longitude", "wifi_password",
                            "is_active",
                        ]:
                            val = rp.get(field)
                            if val is not None and getattr(existing, field) != val:
                                setattr(existing, field, val)
                                property_changed = True

                        # Enrich with detail call
                        try:
                            detail = await self.fetch_property_detail(int(sl_id))
                            if detail.get("bedrooms_number"):
                                bedrooms_value = int(detail["bedrooms_number"])
                                if existing.bedrooms != bedrooms_value:
                                    existing.bedrooms = bedrooms_value
                                    property_changed = True
                            if detail.get("bathrooms_number"):
                                bathrooms_value = float(detail["bathrooms_number"])
                                if existing.bathrooms != bathrooms_value:
                                    existing.bathrooms = bathrooms_value
                                    property_changed = True
                        except Exception:
                            pass

                        # Sync rate card (fees, taxes, seasonal rates)
                        try:
                            rc = await self.fetch_property_rates(int(sl_id))
                            if rc and existing.rate_card != rc:
                                existing.rate_card = rc
                                property_changed = True
                        except Exception:
                            pass

                        # Sync amenities from Streamline
                        try:
                            amenity_list = await self.fetch_property_amenities(int(sl_id))
                            if amenity_list and existing.amenities != amenity_list:
                                existing.amenities = amenity_list
                                property_changed = True
                        except Exception as ae:
                            self.log.warning("property_amenities_error", unit_id=sl_id, error=str(ae)[:120])

                        if property_changed:
                            reindex_property_ids.add(str(existing.id))
                        summary["properties"]["updated"] += 1
                    else:
                        # Enrich before creating
                        bedrooms = rp.get("bedrooms", 0)
                        bathrooms = rp.get("bathrooms", 0)
                        try:
                            detail = await self.fetch_property_detail(int(sl_id))
                            bedrooms = int(detail.get("bedrooms_number", bedrooms))
                            bathrooms = float(detail.get("bathrooms_number", bathrooms))
                        except Exception:
                            pass

                        amenities_data = None
                        try:
                            amenity_list = await self.fetch_property_amenities(int(sl_id))
                            if amenity_list:
                                amenities_data = amenity_list
                        except Exception:
                            pass

                        prop = Property(
                            name=rp["name"],
                            slug=rp["slug"],
                            property_type=rp["property_type"],
                            bedrooms=bedrooms,
                            bathrooms=bathrooms,
                            max_guests=rp["max_guests"],
                            address=rp.get("address"),
                            latitude=rp.get("latitude"),
                            longitude=rp.get("longitude"),
                            wifi_ssid=rp.get("wifi_ssid"),
                            wifi_password=rp.get("wifi_password"),
                            streamline_property_id=sl_id,
                            is_active=rp.get("is_active", True),
                            amenities=amenities_data,
                        )
                        db.add(prop)
                        await db.flush()
                        reindex_property_ids.add(str(prop.id))
                        summary["properties"]["created"] += 1

                except Exception as e:
                    summary["properties"]["errors"] += 1
                    summary["errors"].append(f"Property {rp.get('name')}: {e}")

            await db.commit()

            summary["knowledge_reindex"] = {"enqueued": 0, "errors": 0}
            if reindex_property_ids:
                try:
                    from backend.core.queue import create_arq_pool

                    arq_pool = await create_arq_pool()
                    try:
                        for property_id in sorted(reindex_property_ids):
                            await arq_pool.enqueue_job(
                                "reindex_property_knowledge",
                                property_id,
                                _queue_name=settings.arq_queue_name,
                            )
                        summary["knowledge_reindex"]["enqueued"] = len(reindex_property_ids)
                    finally:
                        await arq_pool.aclose()
                except Exception as reindex_exc:
                    self.log.warning("knowledge_reindex_enqueue_error", error=str(reindex_exc)[:300])
                    summary["knowledge_reindex"] = {"enqueued": 0, "errors": len(reindex_property_ids)}

            # ---- Phase 2: Sync Reservations + Guests ----
            self.log.info("sync_phase_2_reservations")
            try:
                remote_res = await self.fetch_reservations()
                batch_count = 0
                for rr in remote_res:
                    try:
                        async with db.begin_nested():
                            sl_res_id = rr["streamline_reservation_id"]
                            if not sl_res_id:
                                continue

                            prop_q = await db.execute(
                                select(Property).where(
                                    Property.streamline_property_id == rr["unit_id"]
                                )
                            )
                            prop = prop_q.scalar_one_or_none()
                            if not prop:
                                continue

                            guest = None
                            guest_phone = self._sanitize_phone(rr.get("guest_phone", ""))
                            guest_email = rr.get("guest_email", "").strip()

                            if guest_phone:
                                gq = await db.execute(
                                    select(Guest).where(Guest.phone_number == guest_phone)
                                )
                                guest = gq.scalar_one_or_none()

                            if not guest and guest_email:
                                gq = await db.execute(
                                    select(Guest).where(Guest.email == guest_email)
                                )
                                guest = gq.scalar_one_or_none()

                            if not guest:
                                guest = Guest(
                                    first_name=rr.get("guest_first_name") or "Unknown",
                                    last_name=rr.get("guest_last_name") or sl_res_id,
                                    phone_number=guest_phone,
                                    email=guest_email or None,
                                    guest_source="streamline_vrs",
                                )
                                db.add(guest)
                                await db.flush()
                                summary["reservations"]["guests_created"] += 1

                            res_q = await db.execute(
                                select(Reservation).where(
                                    Reservation.confirmation_code == sl_res_id
                                )
                            )
                            existing_res = res_q.scalar_one_or_none()

                            if existing_res:
                                _res_track_fields = [
                                    "status", "num_guests", "access_code",
                                    "total_amount", "paid_amount", "balance_due",
                                    "nightly_rate", "nights_count",
                                ]
                                _old_res = {f: getattr(existing_res, f, None) for f in _res_track_fields}

                                mapped_status = rr.get("status", existing_res.status)
                                mapped_status = self._sanitize_reservation_status(
                                    mapped_status, rr.get("check_in_date"),
                                    rr.get("check_out_date"), rr.get("paid_amount"),
                                )
                                existing_res.status = mapped_status
                                existing_res.num_guests = rr.get("num_guests", existing_res.num_guests)
                                if rr.get("access_code"):
                                    existing_res.access_code = rr["access_code"]
                                if rr.get("total_amount"):
                                    existing_res.total_amount = rr["total_amount"]
                                if rr.get("paid_amount") is not None:
                                    existing_res.paid_amount = rr["paid_amount"]
                                if rr.get("balance_due") is not None:
                                    existing_res.balance_due = rr["balance_due"]
                                if rr.get("nightly_rate") is not None:
                                    existing_res.nightly_rate = rr["nightly_rate"]
                                if rr.get("nights_count"):
                                    existing_res.nights_count = rr["nights_count"]
                                if rr.get("price_breakdown"):
                                    existing_res.price_breakdown = rr["price_breakdown"]

                                _new_res = {f: getattr(existing_res, f, None) for f in _res_track_fields}
                                _res_changes = {k: v for k, v in _new_res.items() if _old_res.get(k) != v}
                                if _res_changes:
                                    _evt = "status_changed" if "status" in _res_changes else "updated"
                                    await self._emit_sync_event(
                                        db, "reservation", str(existing_res.id),
                                        _evt,
                                        {k: str(v) if v is not None else None for k, v in _old_res.items()},
                                        {k: str(v) if v is not None else None for k, v in _new_res.items()},
                                    )

                                    old_paid = float(_old_res.get("paid_amount") or 0)
                                    new_paid = float(rr.get("paid_amount") or 0)
                                    if old_paid == 0 and new_paid > 0 and float(rr.get("total_amount") or 0) > 0:
                                        await self._emit_revenue_event(
                                            property_id=prop.streamline_property_id or str(prop.id),
                                            confirmation_code=sl_res_id,
                                            total_amount=rr.get("total_amount"),
                                            cleaning_fee=getattr(existing_res, "cleaning_fee", 0) or 0,
                                            tax_amount=getattr(existing_res, "tax_amount", 0) or 0,
                                            nightly_rate=rr.get("nightly_rate"),
                                            nights_count=rr.get("nights_count"),
                                        )

                                summary["reservations"]["updated"] += 1
                            else:
                                check_in = rr.get("check_in_date")
                                check_out = rr.get("check_out_date")
                                if not check_in or not check_out:
                                    continue

                                new_status = self._sanitize_reservation_status(
                                    rr.get("status", "confirmed"),
                                    check_in, check_out, rr.get("paid_amount"),
                                )

                                new_res = Reservation(
                                    confirmation_code=sl_res_id,
                                    guest_id=guest.id,
                                    property_id=prop.id,
                                    check_in_date=check_in,
                                    check_out_date=check_out,
                                    status=new_status,
                                    num_guests=rr.get("num_guests") or 1,
                                    num_adults=rr.get("num_adults"),
                                    num_children=rr.get("num_children"),
                                    num_pets=rr.get("num_pets", 0),
                                    total_amount=rr.get("total_amount"),
                                    paid_amount=rr.get("paid_amount"),
                                    balance_due=rr.get("balance_due"),
                                    nightly_rate=rr.get("nightly_rate"),
                                    nights_count=rr.get("nights_count"),
                                    price_breakdown=rr.get("price_breakdown"),
                                    access_code=rr.get("access_code"),
                                    special_requests=rr.get("special_requests"),
                                    booking_source=rr.get("source") or "streamline",
                                    is_owner_booking=bool(rr.get("is_owner_booking", False)),
                                    streamline_reservation_id=sl_res_id,
                                )
                                db.add(new_res)
                                await db.flush()
                                await self._emit_sync_event(
                                    db, "reservation", str(new_res.id), "created",
                                    {},
                                    {"status": new_status, "total_amount": str(rr.get("total_amount")),
                                     "property_id": str(prop.id), "confirmation_code": sl_res_id},
                                )

                                new_paid = float(rr.get("paid_amount") or 0)
                                if new_paid > 0 and float(rr.get("total_amount") or 0) > 0:
                                    await self._emit_revenue_event(
                                        property_id=prop.streamline_property_id or str(prop.id),
                                        confirmation_code=sl_res_id,
                                        total_amount=rr.get("total_amount"),
                                        cleaning_fee=0,
                                        tax_amount=0,
                                        nightly_rate=rr.get("nightly_rate"),
                                        nights_count=rr.get("nights_count"),
                                    )

                                summary["reservations"]["created"] += 1

                        batch_count += 1
                        if batch_count % 200 == 0:
                            await db.commit()

                    except Exception as e:
                        summary["reservations"]["errors"] += 1
                        if summary["reservations"]["errors"] <= 5:
                            summary["errors"].append(f"Reservation {rr.get('streamline_reservation_id')}: {e}")

                await db.commit()

            except StreamlineMethodNotAllowed:
                self.log.warning("reservations_method_not_allowed", hint="Token upgrade may not be active yet")
            except Exception as e:
                summary["errors"].append(f"Reservation sync: {e}")

            # ---- Phase 2.5: Sync Reservation Notes ----
            self.log.info("sync_phase_2_5_notes")
            try:
                from sqlalchemy import or_, cast, String, desc
                all_res_q = await db.execute(
                    select(Reservation)
                    .where(or_(
                        Reservation.streamline_notes.is_(None),
                        cast(Reservation.streamline_notes, String) == "[]",
                    ))
                    .where(Reservation.confirmation_code.isnot(None))
                    .order_by(desc(Reservation.check_in_date))
                    .limit(200)
                )
                res_needing_notes = all_res_q.scalars().all()
                batch = 0
                for res in res_needing_notes:
                    try:
                        notes = await self.fetch_reservation_notes(res.confirmation_code)
                        res.streamline_notes = notes if notes else []
                        summary["notes"]["synced"] += 1
                        batch += 1
                        if batch % 50 == 0:
                            await db.commit()
                    except Exception as e:
                        summary["notes"]["errors"] += 1
                        res.streamline_notes = []
                if batch:
                    await db.commit()
            except Exception as e:
                summary["errors"].append(f"Notes sync: {e}")

            # ---- Phase 3: Sync Availability (with DB persistence) ----
            self.log.info("sync_phase_3_availability")
            from sqlalchemy import text as sa_text_p3
            for rp in remote_properties:
                try:
                    sl_id = rp["streamline_property_id"]
                    unit_id = int(sl_id)

                    prop_result = await db.execute(
                        select(Property).where(Property.streamline_property_id == sl_id)
                    )
                    local_prop = prop_result.scalar_one_or_none()
                    if not local_prop:
                        continue

                    blocked = await self.fetch_blocked_days(unit_id)
                    for b in blocked:
                        if not b.get("start_date") or not b.get("end_date"):
                            continue
                        block_type = (b.get("type_name") or "reservation").lower().replace(" ", "_")
                        await db.execute(
                            sa_text_p3("""
                                INSERT INTO blocked_days
                                    (id, property_id, start_date, end_date, block_type,
                                     confirmation_code, source, created_at, updated_at)
                                VALUES
                                    (gen_random_uuid(), :pid, :sd, :ed, :bt, :cc,
                                     'streamline', NOW(), NOW())
                                ON CONFLICT (property_id, start_date, end_date, block_type)
                                DO UPDATE SET
                                    confirmation_code = EXCLUDED.confirmation_code,
                                    updated_at = NOW()
                            """),
                            {
                                "pid": str(local_prop.id),
                                "sd": b["start_date"],
                                "ed": b["end_date"],
                                "bt": block_type[:50],
                                "cc": str(b.get("confirmation_id") or "")[:50] or None,
                            },
                        )
                    local_prop.availability = build_property_availability_snapshot(
                        property_id=str(local_prop.id),
                        property_slug=local_prop.slug,
                        blocked_ranges=blocked,
                        generated_at=datetime.now(timezone.utc),
                    )
                    await db.commit()
                    summary["availability"]["synced"] += 1
                    summary["availability"]["bookings_found"] += len(blocked)
                except StreamlineMethodNotAllowed:
                    break
                except Exception as e:
                    summary["errors"].append(f"Availability {rp.get('name')}: {e}")

            # ---- Phase 4: Sync Work Orders ----
            self.log.info("sync_phase_4_work_orders")
            try:
                remote_wos = await self.fetch_work_orders()
                for rwo in remote_wos:
                    try:
                        sl_wo_id = str(rwo.get("streamline_id", ""))
                        if not sl_wo_id:
                            continue

                        result = await db.execute(
                            select(WorkOrder).where(
                                WorkOrder.title == f"SL-{sl_wo_id}"
                            )
                        )
                        existing_wo = result.scalar_one_or_none()

                        if existing_wo:
                            _old_wo_status = existing_wo.status
                            if rwo.get("status"):
                                existing_wo.status = rwo["status"]
                            if _old_wo_status != existing_wo.status:
                                await self._emit_sync_event(
                                    db, "work_order", str(existing_wo.id), "status_changed",
                                    {"status": _old_wo_status},
                                    {"status": existing_wo.status},
                                )
                            summary["work_orders"]["updated"] += 1
                        else:
                            prop_result = await db.execute(
                                select(Property).where(
                                    Property.streamline_property_id == str(rwo.get("unit_id", ""))
                                )
                            )
                            prop = prop_result.scalar_one_or_none()

                            wo = WorkOrder(
                                title=f"SL-{sl_wo_id}",
                                description=rwo.get("description") or rwo.get("subject", ""),
                                category=rwo.get("category", "maintenance"),
                                priority=rwo.get("priority", "medium"),
                                status="open",
                                property_id=prop.id if prop else None,
                            )
                            db.add(wo)
                            await db.flush()
                            await self._emit_sync_event(
                                db, "work_order", str(wo.id), "created",
                                {},
                                {"status": "open", "title": f"SL-{sl_wo_id}",
                                 "category": rwo.get("category", "maintenance"),
                                 "priority": rwo.get("priority", "medium")},
                            )
                            summary["work_orders"]["created"] += 1

                    except Exception as e:
                        summary["work_orders"]["errors"] += 1
                        summary["errors"].append(f"WorkOrder SL-{sl_wo_id}: {e}")

                await db.commit()

            except StreamlineMethodNotAllowed:
                self.log.info("work_orders_not_allowed")

            # ---- Phase 5: Ensure every reservation has an agreement ----
            self.log.info("sync_phase_5_agreements")
            try:
                from backend.models import RentalAgreement, AgreementTemplate
                from backend.services.agreement_renderer import (
                    build_variable_context,
                    render_template,
                )

                tmpl_result = await db.execute(
                    select(AgreementTemplate).where(
                        AgreementTemplate.agreement_type == "rental_agreement",
                        AgreementTemplate.is_active == True,
                    ).limit(1)
                )
                template = tmpl_result.scalar_one_or_none()

                if template:
                    sl_docs_available = False
                    try:
                        probe = await self.fetch_all_documents()
                        sl_docs_available = len(probe) > 0
                    except Exception:
                        pass

                    res_without_agreement = await db.execute(
                        select(Reservation)
                        .outerjoin(
                            RentalAgreement,
                            (RentalAgreement.reservation_id == Reservation.id)
                            & (RentalAgreement.agreement_type == "rental_agreement"),
                        )
                        .where(
                            RentalAgreement.id.is_(None),
                            Reservation.status.notin_(["cancelled"]),
                        )
                    )
                    missing_res = res_without_agreement.scalars().all()

                    for res in missing_res:
                        try:
                            sl_docs = []
                            if sl_docs_available:
                                sl_docs = await self.fetch_reservation_documents(
                                    res.confirmation_code
                                )
                            if sl_docs:
                                for doc in sl_docs:
                                    doc_content = doc.get("content") or doc.get("body") or doc.get("text", "")
                                    doc_type = (doc.get("type") or doc.get("document_type") or "rental_agreement").lower()
                                    signed_at_str = doc.get("signed_at") or doc.get("date_signed")
                                    signed_at = None
                                    if signed_at_str:
                                        try:
                                            signed_at = datetime.strptime(str(signed_at_str), "%m/%d/%Y")
                                        except ValueError:
                                            try:
                                                signed_at = datetime.fromisoformat(str(signed_at_str))
                                            except ValueError:
                                                pass

                                    ra = RentalAgreement(
                                        guest_id=res.guest_id,
                                        reservation_id=res.id,
                                        property_id=res.property_id,
                                        template_id=template.id,
                                        agreement_type=doc_type,
                                        rendered_content=doc_content,
                                        status="signed" if signed_at else "viewed",
                                        signed_at=signed_at,
                                        signer_name=doc.get("signer_name", ""),
                                    )
                                    db.add(ra)
                                    summary["agreements"]["from_streamline"] += 1
                                continue

                            guest = await db.get(Guest, res.guest_id)
                            prop_obj = await db.get(Property, res.property_id)
                            if not guest or not prop_obj:
                                summary["agreements"]["skipped"] += 1
                                continue

                            ctx = build_variable_context(
                                reservation=res, guest=guest, prop=prop_obj
                            )
                            rendered = render_template(
                                template.content_markdown, ctx
                            )
                            ra = RentalAgreement(
                                guest_id=res.guest_id,
                                reservation_id=res.id,
                                property_id=res.property_id,
                                template_id=template.id,
                                agreement_type="rental_agreement",
                                rendered_content=rendered,
                                status="signed",
                                signed_at=res.check_in_date
                                    if hasattr(res.check_in_date, "isoformat")
                                    else None,
                                signer_name=f"{guest.first_name} {guest.last_name}",
                            )
                            db.add(ra)
                            summary["agreements"]["generated"] += 1

                        except Exception as e:
                            summary["agreements"]["errors"] += 1
                            if summary["agreements"]["errors"] <= 3:
                                summary["errors"].append(
                                    f"Agreement for res {res.confirmation_code}: {e}"
                                )

                    await db.commit()
                else:
                    self.log.warning("no_rental_agreement_template",
                                     hint="Create an active 'rental_agreement' template")
            except Exception as e:
                summary["errors"].append(f"Agreement sync: {e}")

            # ---- Phase 6: Enrich Reservations with Financial Detail ----
            self.log.info("sync_phase_6_financial_enrichment")
            try:
                from sqlalchemy import desc as sa_desc
                recent_res = await db.execute(
                    select(Reservation)
                    .where(
                        Reservation.streamline_financial_detail.is_(None),
                        Reservation.confirmation_code.isnot(None),
                        Reservation.status.notin_(["cancelled"]),
                    )
                    .order_by(sa_desc(Reservation.check_in_date))
                    .limit(100)
                )
                enrichment_batch = recent_res.scalars().all()
                enriched_count = 0
                for res in enrichment_batch:
                    try:
                        price_data = await self.fetch_reservation_price(res.confirmation_code)
                        if price_data:
                            res.streamline_financial_detail = price_data
                            self._apply_financial_detail(res, price_data)
                            enriched_count += 1
                    except Exception as e:
                        if enriched_count == 0 and "E0014" in str(e):
                            break
                        summary["errors"].append(
                            f"Price enrich {res.confirmation_code}: {e}"
                        ) if len(summary["errors"]) < 10 else None
                if enriched_count:
                    await db.commit()
                summary["financial_enrichment"] = {"enriched": enriched_count, "checked": len(enrichment_batch)}
            except Exception as e:
                summary["errors"].append(f"Financial enrichment: {e}")

            # ---- Phase 6.5: Revenue Reconciliation Sweep ----
            # Catches enriched paid reservations that were never journaled
            # (closes the Phase 2/6 ordering gap)
            self.log.info("sync_phase_6_5_revenue_reconciliation")
            try:
                await db.commit()
                recon_query = await db.execute(
                    text("""
                        SELECT r.confirmation_code,
                               p.streamline_property_id AS unit_id,
                               r.total_amount, r.tax_amount, r.cleaning_fee,
                               r.nightly_rate, r.nights_count
                        FROM reservations r
                        JOIN properties p ON p.id = r.property_id
                        LEFT JOIN journal_entries je
                            ON je.reference_id = r.confirmation_code
                            AND je.reference_type = 'reservation_revenue'
                        WHERE r.paid_amount > 0
                          AND r.streamline_financial_detail IS NOT NULL
                          AND r.total_amount > 0
                          AND r.status NOT IN ('cancelled')
                          AND je.id IS NULL
                        LIMIT 50
                    """)
                )
                unjournaled = recon_query.fetchall()
                recon_emitted = 0
                for row in unjournaled:
                    await self._emit_revenue_event(
                        property_id=str(row.unit_id),
                        confirmation_code=row.confirmation_code,
                        total_amount=row.total_amount,
                        cleaning_fee=float(row.cleaning_fee or 0),
                        tax_amount=float(row.tax_amount or 0),
                        nightly_rate=row.nightly_rate,
                        nights_count=row.nights_count,
                    )
                    recon_emitted += 1
                summary["revenue_reconciliation"] = {
                    "unjournaled_found": len(unjournaled),
                    "events_emitted": recon_emitted,
                }
                if recon_emitted:
                    self.log.info(
                        "revenue_reconciliation_complete",
                        emitted=recon_emitted,
                    )
            except Exception as e:
                summary["errors"].append(f"Revenue reconciliation: {e}")

            # ---- Phase 7: Sync Owner Data & Balances ----
            self.log.info("sync_phase_7_owner_balances")
            try:
                owners_data = await self.fetch_owners()
                owner_map = {}
                for ow in owners_data:
                    owner_map[str(ow.get("owner_id", ""))] = ow
                live_streamline_ids = {
                    str(prop["streamline_property_id"])
                    for prop in await self.fetch_properties()
                    if str(prop.get("streamline_property_id", "")).strip()
                }

                all_props = await db.execute(
                    select(Property).where(Property.streamline_property_id.isnot(None))
                )
                props_list = all_props.scalars().all()

                balance_count = 0
                for prop in props_list:
                    try:
                        streamline_id = str(prop.streamline_property_id or "").strip()
                        if streamline_id not in live_streamline_ids:
                            continue
                        unit_id = int(streamline_id)
                        bal = await self.fetch_unit_owner_balance(unit_id)
                        if not bal or is_streamline_circuit_placeholder(bal):
                            continue

                        prop.owner_balance = bal
                        ow_id = str(bal.get("owner_id", ""))
                        if ow_id and ow_id in owner_map:
                            ow = owner_map[ow_id]
                            prop.owner_id = ow_id
                            prop.owner_name = f"{ow.get('first_name', '')} {ow.get('last_name', '')}".strip()
                        elif ow_id:
                            prop.owner_id = ow_id

                        from sqlalchemy import text as sa_text
                        owner_funds = self._safe_decimal(bal.get("owner_balance")) or Decimal("0")
                        await db.execute(
                            sa_text("""
                                INSERT INTO trust_balance (property_id, owner_funds, last_updated)
                                VALUES (:pid, :funds, NOW())
                                ON CONFLICT (property_id)
                                DO UPDATE SET owner_funds = :funds, last_updated = NOW()
                            """),
                            {"pid": prop.streamline_property_id, "funds": float(owner_funds)},
                        )
                        balance_count += 1
                    except StreamlineMethodNotAllowed:
                        break
                    except Exception as e:
                        if balance_count == 0 and "E0014" in str(e):
                            break
                        summary["errors"].append(
                            f"Owner balance {prop.name}: {e}"
                        ) if len(summary["errors"]) < 10 else None

                if balance_count:
                    await db.commit()
                summary["owner_balances"] = {"synced": balance_count, "owners_found": len(owners_data)}
            except StreamlineMethodNotAllowed:
                summary["owner_balances"] = {"synced": 0, "status": "method_not_allowed"}
            except Exception as e:
                summary["errors"].append(f"Owner sync: {e}")

            # ---- Phase 8: Sync Housekeeping from Streamline ----
            self.log.info("sync_phase_8_housekeeping")
            try:
                from backend.services.housekeeping_service import HousekeepingTask

                hk_data = await self.fetch_housekeeping_report()
                hk_created = 0
                hk_updated = 0

                raw_cleanings = []
                res_block = hk_data.get("reservations", {})
                if isinstance(res_block, dict):
                    items = res_block.get("reservation", [])
                    if isinstance(items, dict):
                        items = [items]
                    raw_cleanings = items

                for cl in raw_cleanings:
                    unit_id = str(cl.get("unit_id", ""))
                    prop_q = await db.execute(
                        select(Property).where(
                            Property.streamline_property_id == unit_id
                        )
                    )
                    prop = prop_q.scalar_one_or_none()
                    if not prop:
                        continue

                    clean_date = self._parse_streamline_date(
                        cl.get("cleaning_date") or cl.get("date")
                    )
                    if not clean_date:
                        continue

                    existing_q = await db.execute(
                        select(HousekeepingTask).where(
                            HousekeepingTask.property_id == prop.id,
                            HousekeepingTask.scheduled_date == clean_date,
                        )
                    )
                    existing_hk = existing_q.scalar_one_or_none()

                    ev_status = (cl.get("event_status_name") or "").lower()
                    hk_status_name = (cl.get("housekeeping_status_name") or "").lower()
                    if "complete" in ev_status or "clean" == hk_status_name:
                        mapped_status = "completed"
                    elif "progress" in ev_status or "cleaning" in hk_status_name:
                        mapped_status = "in_progress"
                    else:
                        mapped_status = "pending"

                    clean_type_raw = (cl.get("cleaning_type") or "turnover").lower()
                    if "deep" in clean_type_raw:
                        clean_type = "deep_clean"
                    elif "inspect" in clean_type_raw:
                        clean_type = "inspection"
                    else:
                        clean_type = "turnover"

                    cleaner = cl.get("processor_name", "")

                    if existing_hk:
                        existing_hk.status = mapped_status
                        existing_hk.assigned_to = cleaner or existing_hk.assigned_to
                        existing_hk.streamline_source = cl
                        existing_hk.streamline_synced_at = datetime.utcnow()
                        hk_updated += 1
                    else:
                        conf_id = cl.get("confirmation_id")
                        res_id = None
                        if conf_id:
                            res_q = await db.execute(
                                select(Reservation.id).where(
                                    Reservation.confirmation_code == str(conf_id)
                                )
                            )
                            row = res_q.first()
                            if row:
                                res_id = row[0]

                        hk = HousekeepingTask(
                            property_id=prop.id,
                            reservation_id=res_id,
                            scheduled_date=clean_date,
                            status=mapped_status,
                            assigned_to=cleaner or None,
                            cleaning_type=clean_type,
                            streamline_source=cl,
                            streamline_synced_at=datetime.utcnow(),
                        )
                        db.add(hk)
                        hk_created += 1

                if hk_created or hk_updated:
                    await db.commit()
                summary["housekeeping"] = {"created": hk_created, "updated": hk_updated}
            except StreamlineMethodNotAllowed:
                summary["housekeeping"] = {"created": 0, "updated": 0, "status": "method_not_allowed"}
            except Exception as e:
                summary["errors"].append(f"Housekeeping sync: {e}")
                summary["housekeeping"] = {"created": 0, "updated": 0, "error": str(e)}

            # ---- Phase 9: Sync Guest Feedback ----
            self.log.info("sync_phase_9_guest_feedback")
            try:
                from backend.models import GuestReview

                feedback = await self.fetch_all_feedback()
                fb_created = 0
                fb_skipped = 0

                for fb in feedback:
                    fb_id = str(fb.get("id", fb.get("comment_id", "")))
                    if not fb_id:
                        fb_skipped += 1
                        continue

                    existing_q = await db.execute(
                        select(GuestReview).where(
                            GuestReview.streamline_feedback_id == fb_id
                        )
                    )
                    if existing_q.scalar_one_or_none():
                        fb_skipped += 1
                        continue

                    unit_id = str(fb.get("unit_id", ""))
                    prop_q = await db.execute(
                        select(Property).where(
                            Property.streamline_property_id == unit_id
                        )
                    )
                    prop = prop_q.scalar_one_or_none()
                    if not prop:
                        fb_skipped += 1
                        continue

                    res = None
                    guest_id = None
                    conf_id = fb.get("reservation_id")
                    if conf_id:
                        res_q = await db.execute(
                            select(Reservation).where(
                                Reservation.confirmation_code == str(conf_id)
                            )
                        )
                        res = res_q.scalar_one_or_none()
                        if res:
                            guest_id = res.guest_id

                    if not guest_id:
                        sl_client_id = fb.get("client_id")
                        if sl_client_id:
                            guest_q = await db.execute(
                                select(Guest).where(
                                    Guest.streamline_guest_id == str(sl_client_id)
                                )
                            )
                            g = guest_q.scalar_one_or_none()
                            if g:
                                guest_id = g.id

                    if not guest_id:
                        fb_email = (fb.get("email") or "").strip()
                        if fb_email:
                            guest_q = await db.execute(
                                select(Guest).where(Guest.email == fb_email)
                            )
                            g = guest_q.scalar_one_or_none()
                            if g:
                                guest_id = g.id

                    if not guest_id:
                        fb_skipped += 1
                        continue

                    points = int(fb.get("points", 0) or 0)
                    overall = points if 1 <= points <= 5 else 5

                    review = GuestReview(
                        guest_id=guest_id,
                        reservation_id=res.id if res else None,
                        property_id=prop.id,
                        direction="guest_to_property",
                        overall_rating=overall,
                        title=fb.get("title", ""),
                        body=fb.get("comments") or fb.get("comment") or "",
                        streamline_feedback_id=fb_id,
                        source="streamline_feedback",
                        is_published=bool(fb.get("show_in_site")),
                    )
                    db.add(review)
                    fb_created += 1

                if fb_created:
                    await db.commit()
                summary["feedback"] = {"imported": fb_created, "skipped": fb_skipped}
            except StreamlineMethodNotAllowed:
                summary["feedback"] = {"imported": 0, "status": "method_not_allowed"}
            except Exception as e:
                summary["errors"].append(f"Feedback sync: {e}")
                summary["feedback"] = {"imported": 0, "error": str(e)}

        except StreamlineAuthError as e:
            summary["errors"].append(f"Authentication failed: {e}")
        except Exception as e:
            summary["errors"].append(f"Sync failed: {str(e)}")

        # ---- Phase 10: Vectorize newly synced records into Qdrant ----
        self.log.info("sync_phase_10_vectorization")
        try:
            from backend.core.database import AsyncSessionLocal
            from backend.services.async_jobs import enqueue_async_job

            async with AsyncSessionLocal() as queue_session:
                vector_job = await enqueue_async_job(
                    queue_session,
                    worker_name="vectorize_new_records_job",
                    job_name="vectorize_new_records",
                    payload={"trigger": "streamline_sync"},
                    requested_by="streamline_sync",
                    tenant_id=None,
                    request_id=None,
                )
            summary["vectorization"] = {"enqueued_job_id": str(vector_job.id)}
        except Exception as e:
            self.log.warning("vectorization_phase_error", error=str(e))
            summary["vectorization"] = {"error": str(e)}

        summary["completed_at"] = datetime.utcnow().isoformat()
        summary["status"] = "completed" if not summary["errors"] else "completed_with_errors"

        self.log.info(
            "sync_complete",
            properties_created=summary["properties"]["created"],
            properties_updated=summary["properties"]["updated"],
            work_orders=summary["work_orders"]["created"],
            agreements_generated=summary["agreements"]["generated"],
            agreements_from_streamline=summary["agreements"]["from_streamline"],
            financial_enriched=summary.get("financial_enrichment", {}).get("enriched", 0),
            owner_balances=summary.get("owner_balances", {}).get("synced", 0),
            housekeeping_created=summary.get("housekeeping", {}).get("created", 0),
            feedback_imported=summary.get("feedback", {}).get("imported", 0),
            vectors_created=sum(
                summary.get("vectorization", {}).get(k, 0)
                for k in ("properties", "reservation_notes", "work_orders")
            ),
            errors=len(summary["errors"]),
        )

        return summary

    # ================================================================
    # RULE ENGINE EVENT EMISSION
    # ================================================================

    async def _emit_sync_event(
        self, db, entity_type: str, entity_id: str,
        event_type: str, previous_state: dict, current_state: dict,
    ):
        """Persist automation audit + ARQ publish only after Postgres is clean.

        Commits the caller's sync transaction first so ARQ/Kafka never runs while the
        main session holds uncommitted rows (avoids idle-in-transaction during I/O).
        """
        try:
            await db.commit()
        except Exception as exc:
            self.log.error(
                "emit_sync_event_parent_commit_failed",
                error=str(exc),
                entity=entity_type,
                entity_id=entity_id,
            )
            await db.rollback()
            raise

        try:
            from backend.core.database import get_session_factory
            from backend.vrs.domain.automations import AutomationEvent, StreamlineEventPayload
            from backend.vrs.infrastructure.event_bus import publish_vrs_event

            payload = StreamlineEventPayload(
                entity_type=entity_type,
                entity_id=entity_id,
                event_type=event_type,
                previous_state=previous_state,
                current_state=current_state,
            )

            factory = get_session_factory()
            async with factory() as event_db:
                event_row = AutomationEvent(
                    entity_type=entity_type,
                    entity_id=entity_id,
                    event_type=event_type,
                    previous_state=previous_state,
                    current_state=current_state,
                )
                event_db.add(event_row)
                await event_db.commit()

            await publish_vrs_event(payload)
        except Exception as exc:
            self.log.warning("rule_engine_emit_failed", error=str(exc), entity=entity_type)

    # ================================================================
    # REVENUE EVENT EMISSION (Redpanda → Revenue Consumer Daemon)
    # ================================================================

    async def _emit_revenue_event(
        self, property_id: str, confirmation_code: str,
        total_amount, cleaning_fee, tax_amount,
        nightly_rate, nights_count,
    ):
        """Async publish to trust.revenue.staged via the FGP singleton producer.

        Called from Phase 2 when a reservation is detected as paid, and from
        the post-Phase-6 reconciliation sweep for enriched-but-unjournaled
        reservations. The Revenue Consumer Daemon journals the income split
        into the Iron Dome.
        """
        from backend.core.event_publisher import EventPublisher

        payload = {
            "property_id": str(property_id),
            "confirmation_code": str(confirmation_code),
            "total_amount": float(total_amount or 0),
            "cleaning_fee": float(cleaning_fee or 0),
            "tax_amount": float(tax_amount or 0),
            "nightly_rate": float(nightly_rate or 0),
            "nights_count": int(nights_count or 0),
        }
        try:
            await EventPublisher.publish(
                "trust.revenue.staged", payload, key=str(confirmation_code),
            )
            self.log.info(
                "revenue_event_emitted",
                confirmation_code=confirmation_code,
                property_id=property_id,
                total_amount=float(total_amount or 0),
            )
        except Exception as e:
            self.log.warning(
                "revenue_event_emission_failed",
                confirmation_code=confirmation_code,
                error=str(e),
            )

    # ================================================================
    # BACKGROUND SYNC WORKER
    # ================================================================

    async def run_sync_loop(self, get_db_session):
        """Background task that runs continuous sync at configured interval."""
        self.log.info(
            "sync_loop_starting",
            interval_seconds=self.sync_interval,
            configured=self.is_configured,
        )

        # Initial delay to let the app fully start
        await asyncio.sleep(10)

        while True:
            try:
                if self.is_configured:
                    async for db in get_db_session():
                        summary = await self.sync_all(db)
                        self.log.info("background_sync_complete", summary=summary)
                else:
                    self.log.debug("sync_loop_skipped_not_configured")
            except Exception as e:
                self.log.error("background_sync_error", error=str(e))

            await asyncio.sleep(self.sync_interval)

    # ================================================================
    # HELPER METHODS
    # ================================================================

    @staticmethod
    def _sanitize_phone(raw: str) -> str:
        """Extract digits from messy Streamline phone fields.
        
        Streamline sometimes embeds names in phone fields, e.g.
        '(706) 474-1701 - Sholane Leach'.  Strip to digits only,
        prepend +1 if it looks like a US number.
        """
        if not raw:
            return ""
        digits = re.sub(r"[^\d]", "", raw)
        if len(digits) == 10:
            return f"+1{digits}"
        if len(digits) == 11 and digits.startswith("1"):
            return f"+{digits}"
        return digits[:20] if digits else ""

    @staticmethod
    def _slugify(text: str) -> str:
        slug = text.lower().strip()
        slug = re.sub(r"[^a-z0-9]+", "-", slug)
        return slug.strip("-")

    @staticmethod
    def _safe_decimal(value: Any) -> Optional[Decimal]:
        if value is None or value == "":
            return None
        try:
            return Decimal(str(value))
        except Exception:
            return None

    @staticmethod
    def _parse_streamline_date(value: Any) -> Optional[date]:
        """Parse Streamline's MM/DD/YYYY date format."""
        if not value:
            return None
        if isinstance(value, date):
            return value
        try:
            return datetime.strptime(str(value), "%m/%d/%Y").date()
        except ValueError:
            try:
                return datetime.strptime(str(value), "%Y-%m-%d").date()
            except ValueError:
                return None

    @staticmethod
    def _clean_html(text: str) -> str:
        """Remove HTML tags and decode entities."""
        if not text:
            return ""
        import html
        cleaned = re.sub(r"<[^>]+>", " ", text)
        cleaned = html.unescape(cleaned)
        cleaned = re.sub(r"\s+", " ", cleaned).strip()
        return cleaned[:2000]

    @staticmethod
    def _apply_financial_detail(res, price_data: Dict):
        """Extract specific fee fields from GetReservationPrice into reservation columns.

        Streamline returns:
          required_fees[]: { name, value, active, damage_waiver, ... }
          taxes: float
          total: float
          price: float (nightly total)

        Fees that don't match any known category are captured in
        ``price_breakdown["unrecognized_fees"]`` so they are never
        silently dropped.
        """
        fees = price_data.get("required_fees", [])
        if isinstance(fees, dict):
            fees = [fees]

        unrecognized_fees: list[dict] = []

        for fee in fees:
            if not fee.get("active"):
                continue
            name = (fee.get("name") or "").lower()
            amount = StreamlineVRS._safe_decimal(fee.get("value"))
            if not amount:
                continue
            if "clean" in name or "arrival" in name or "departure" in name:
                res.cleaning_fee = amount
            elif "pet" in name:
                res.pet_fee = amount
            elif "damage" in name or "waiver" in name or "protect" in name:
                res.damage_waiver_fee = amount
            elif "processing" in name or "service" in name or "booking" in name:
                res.service_fee = amount
            else:
                unrecognized_fees.append({
                    "name": fee.get("name"),
                    "amount": float(amount),
                    "streamline_fee_id": fee.get("id"),
                    "raw": fee,
                })

        if unrecognized_fees:
            breakdown = res.price_breakdown if isinstance(res.price_breakdown, dict) else {}
            breakdown["unrecognized_fees"] = unrecognized_fees
            res.price_breakdown = breakdown

        tax_total = StreamlineVRS._safe_decimal(price_data.get("taxes"))
        if tax_total:
            res.tax_amount = tax_total

        new_total = StreamlineVRS._safe_decimal(price_data.get("total"))
        if new_total and new_total > 0:
            res.total_amount = new_total

    @staticmethod
    def _safe_int(value) -> Optional[int]:
        if value is None or value == "":
            return None
        try:
            v = int(value)
            return v if 1 <= v <= 5 else None
        except (ValueError, TypeError):
            return None

    @staticmethod
    def _detect_property_type(p: Dict) -> str:
        name = (p.get("name") or "").lower()
        for keyword in ["cabin", "log"]:
            if keyword in name:
                return "cabin"
        for keyword in ["lodge"]:
            if keyword in name:
                return "lodge"
        for keyword in ["cottage", "bungalow"]:
            if keyword in name:
                return "cottage"
        for keyword in ["house", "home", "villa", "sanctuary"]:
            if keyword in name:
                return "house"
        return "cabin"

    def _sanitize_reservation_status(
        self,
        raw_status: str,
        check_in_date: Optional[date],
        check_out_date: Optional[date],
        paid_amount: Any = None,
    ) -> str:
        """Data Boundary Sanitization — enforces physical reality on Streamline statuses.

        Rule 6 of the SRE Constitution:
        - If checked_in but check_in is strictly in the future → mutate to confirmed
        - If no_show but checkout is past and guest paid → mutate to checked_out
        - Strips empty/garbage status strings to safe defaults
        """
        import pytz
        et_today = datetime.now(pytz.timezone("America/New_York")).date()

        status = (raw_status or "").strip().lower()
        if not status or status not in (
            "confirmed", "checked_in", "checked_out", "cancelled",
            "pending", "on_hold", "no_show",
        ):
            status = "confirmed"

        # Ghost check-in: Streamline says checked_in but check_in is in the future
        if status == "checked_in" and check_in_date and check_in_date > et_today:
            self.log.info(
                "sanitize_future_checkin_to_confirmed",
                check_in=str(check_in_date),
                today=str(et_today),
            )
            status = "confirmed"

        # Paid on-hold: guest is physically in the cabin, paid, but Streamline says on_hold
        if status == "on_hold" and check_in_date and check_out_date:
            if check_in_date <= et_today <= check_out_date:
                paid = self._safe_decimal(paid_amount)
                if paid and paid > 0:
                    self.log.info(
                        "sanitize_paid_onhold_to_checked_in",
                        check_in=str(check_in_date),
                        check_out=str(check_out_date),
                        paid=str(paid),
                    )
                    status = "checked_in"

        # False no_show: checkout is past and guest actually paid
        if status == "no_show" and check_out_date and check_out_date < et_today:
            paid = self._safe_decimal(paid_amount)
            if paid and paid > 0:
                status = "checked_out"

        return status

    def get_sync_status(self) -> Dict[str, Any]:
        return {
            "configured": self.is_configured,
            "api_url": self.api_url,
            "sync_interval_seconds": self.sync_interval,
            "token_expires": str(self._token_expires) if self._token_expires else "unknown",
            "last_sync": {
                k: v.isoformat() for k, v in self._last_sync.items()
            },
        }


# Shared client used by legacy call sites that expect a module-level singleton.
streamline_vrs = StreamlineVRS()
