"""
History-aware pricing context for the Librarian lane.

This service scans mounted Synology history data, normalizes records from
CSV/JSON/SQLite backups, and exposes a similarity search interface for
history-aware quote enrichment. When FAISS is available it is used for fast
nearest-neighbor search; otherwise a deterministic in-process fallback keeps
the tool functional inside constrained environments.
"""
from __future__ import annotations

import asyncio
import csv
import hashlib
import json
import math
import os
import sqlite3
from dataclasses import asdict, dataclass
from datetime import UTC, date, datetime
from pathlib import Path
from typing import Any, Iterable, Optional

import structlog

try:  # Optional acceleration path.
    import faiss  # type: ignore
except Exception:  # pragma: no cover - optional dependency
    faiss = None

try:  # Optional persistence helper.
    import numpy as np  # type: ignore
except Exception:  # pragma: no cover - optional dependency
    np = None

logger = structlog.get_logger(service="history_query_tool")

SUPPORTED_EXTENSIONS = {".csv", ".json", ".jsonl", ".db", ".sqlite", ".sqlite3"}
DEFAULT_VECTOR_DIM = 48
DEFAULT_TOP_K = 5
PRICE_RESISTANCE_KEYWORDS = (
    "price",
    "priced",
    "expensive",
    "too much",
    "overpriced",
    "costly",
    "rate shock",
)
POSITIVE_ADDON_KEYWORDS = (
    "add-on",
    "addon",
    "late checkout",
    "early check-in",
    "firewood",
    "pet fee",
    "romance package",
    "celebration",
)
FIELD_ALIASES: dict[str, tuple[str, ...]] = {
    "property_id": ("property_id", "propertyid", "unit_id", "listing_id", "property", "cabin_id"),
    "stay_date": ("stay_date", "check_in", "arrival_date", "arrival", "start_date", "reservation_date"),
    "check_out": ("check_out", "departure_date", "end_date"),
    "nightly_rate": ("nightly_rate", "adr", "avg_daily_rate", "rate", "nightly", "nightlyrent"),
    "total_revenue": ("total_revenue", "revenue", "gross_revenue", "reservation_total", "total", "amount"),
    "guests": ("guests", "guest_count", "occupancy", "pax", "adults"),
    "nights": ("nights", "stay_nights", "length_of_stay", "los", "night_count"),
    "booked_at": ("booked_at", "booked_on", "created_at", "reservation_created_at", "booking_date"),
    "notes": ("notes", "note", "guest_notes", "comments", "comment", "complaint_text"),
    "addons_total": ("addons_total", "extras_total", "upsell_total", "ancillary_revenue", "add_on_total"),
    "event_type": ("event_type", "event", "trip_reason", "stay_reason", "tags"),
    "occupied": ("is_occupied", "occupied", "booked", "is_booked", "sold"),
}


@dataclass(slots=True)
class HistoricalStayRecord:
    property_id: str
    stay_date: str
    stay_month: int
    nightly_rate: float
    total_revenue: float
    guests: int
    nights: int
    booked_at: Optional[str]
    occupancy_flag: Optional[bool]
    addons_total: float
    price_resistance: bool
    notes: str
    event_hint: str
    source_file: str
    source_row_id: str

    @property
    def stay_date_obj(self) -> date:
        return date.fromisoformat(self.stay_date)

    @property
    def booked_at_obj(self) -> Optional[date]:
        if not self.booked_at:
            return None
        return _parse_date(self.booked_at)

    @property
    def lead_days(self) -> Optional[int]:
        booked_on = self.booked_at_obj
        if booked_on is None:
            return None
        return max((self.stay_date_obj - booked_on).days, 0)


@dataclass(slots=True)
class HistoryIndexBundle:
    signature: str
    records: list[HistoricalStayRecord]
    vectors: list[list[float]]
    built_at: str
    index_backend: str


def _normalize_key(key: str) -> str:
    return "".join(ch for ch in key.lower().strip() if ch.isalnum() or ch == "_")


def _safe_text(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, str):
        return value.strip()
    return str(value).strip()


def _coerce_float(value: Any) -> Optional[float]:
    text = _safe_text(value)
    if not text:
        return None
    cleaned = (
        text.replace("$", "")
        .replace(",", "")
        .replace("%", "")
        .replace("USD", "")
        .replace("usd", "")
    ).strip()
    if not cleaned:
        return None
    try:
        return float(cleaned)
    except ValueError:
        return None


def _coerce_int(value: Any) -> Optional[int]:
    number = _coerce_float(value)
    if number is None:
        return None
    try:
        return int(round(number))
    except Exception:
        return None


def _coerce_bool(value: Any) -> Optional[bool]:
    if isinstance(value, bool):
        return value
    text = _safe_text(value).lower()
    if not text:
        return None
    if text in {"1", "true", "t", "yes", "y", "booked", "occupied", "sold"}:
        return True
    if text in {"0", "false", "f", "no", "n", "cancelled", "open", "vacant"}:
        return False
    return None


def _parse_date(value: Any) -> Optional[date]:
    text = _safe_text(value)
    if not text:
        return None
    text = text.replace("Z", "+00:00")
    for candidate in (text, text.split("T")[0], text.split(" ")[0]):
        try:
            return date.fromisoformat(candidate)
        except ValueError:
            pass
        try:
            return datetime.fromisoformat(candidate).date()
        except ValueError:
            pass
    for fmt in ("%m/%d/%Y", "%Y/%m/%d", "%m-%d-%Y", "%b %d %Y", "%B %d %Y"):
        try:
            return datetime.strptime(text, fmt).date()
        except ValueError:
            continue
    return None


def _extract_field(row: dict[str, Any], canonical_name: str) -> Any:
    normalized = {_normalize_key(k): v for k, v in row.items()}
    for alias in FIELD_ALIASES.get(canonical_name, (canonical_name,)):
        value = normalized.get(_normalize_key(alias))
        if value not in (None, ""):
            return value
    return None


def _bucketize(value: int, *, boundaries: tuple[int, ...]) -> str:
    for boundary in boundaries:
        if value <= boundary:
            return f"le_{boundary}"
    return f"gt_{boundaries[-1]}"


def _hashed_index(token: str, width: int) -> int:
    digest = hashlib.sha256(token.encode("utf-8")).hexdigest()
    return int(digest[:8], 16) % width


def _normalize_vector(vector: list[float]) -> list[float]:
    norm = math.sqrt(sum(value * value for value in vector))
    if norm <= 0:
        return vector
    return [value / norm for value in vector]


def _similarity(left: list[float], right: list[float]) -> float:
    return round(sum(a * b for a, b in zip(left, right)), 6)


def _season_for_month(month: int) -> str:
    if month in {12, 1, 2}:
        return "winter"
    if month in {3, 4, 5}:
        return "spring"
    if month in {6, 7, 8}:
        return "summer"
    return "fall"


def _event_tokens(event_hint: str, notes: str) -> list[str]:
    tokens: list[str] = []
    for raw_token in f"{event_hint} {notes}".lower().replace("/", " ").replace(",", " ").split():
        cleaned = "".join(ch for ch in raw_token if ch.isalnum() or ch == "-")
        if len(cleaned) >= 4:
            tokens.append(cleaned)
    return tokens[:12]


def _safe_prior_year(target_day: date) -> date:
    try:
        return target_day.replace(year=target_day.year - 1)
    except ValueError:
        # Feb 29 fallback.
        return target_day.replace(year=target_day.year - 1, day=28)


class HistoryLibrarian:
    def __init__(
        self,
        history_path: str = "/mnt/history",
        *,
        index_path: Optional[str] = None,
        vector_dim: int = DEFAULT_VECTOR_DIM,
        top_k_default: int = DEFAULT_TOP_K,
    ):
        self.history_path = Path(os.getenv("FORTRESS_HISTORY_PATH", history_path))
        self.index_path = Path(
            os.getenv(
                "FORTRESS_HISTORY_INDEX_PATH",
                index_path or str(self.history_path / ".history_index"),
            )
        )
        self.vector_dim = max(vector_dim, 16)
        self.top_k_default = max(top_k_default, 1)
        self._bundle_cache: Optional[HistoryIndexBundle] = None

    async def get_lookalike_context(
        self,
        *,
        property_id: str,
        target_date: str,
        guests: int = 2,
        nights: int = 2,
        event_hint: Optional[str] = None,
        top_k: Optional[int] = None,
    ) -> dict[str, Any]:
        return await asyncio.to_thread(
            self._get_lookalike_context_sync,
            property_id=property_id,
            target_date=target_date,
            guests=guests,
            nights=nights,
            event_hint=event_hint,
            top_k=top_k or self.top_k_default,
        )

    async def rebuild_persistent_index(self) -> dict[str, Any]:
        return await asyncio.to_thread(self._rebuild_persistent_index_sync)

    def _get_lookalike_context_sync(
        self,
        *,
        property_id: str,
        target_date: str,
        guests: int,
        nights: int,
        event_hint: Optional[str],
        top_k: int,
    ) -> dict[str, Any]:
        target_day = _parse_date(target_date)
        if target_day is None:
            raise ValueError("target_date must be a valid date")

        bundle = self._load_bundle()
        if not bundle.records:
            return {
                "status": "no_history",
                "property_id": property_id,
                "target_date": target_day.isoformat(),
                "match_count": 0,
                "comparison_scope": "none",
                "lookalikes": [],
                "opportunity_gap_suggested": 0.0,
            }

        query_vector = self._build_query_vector(
            property_id=property_id,
            target_day=target_day,
            guests=guests,
            nights=nights,
            event_hint=event_hint or "",
        )
        candidate_indexes = self._search_vectors(bundle, query_vector, top_k=max(top_k * 4, top_k))
        exact_matches = [
            idx
            for idx in candidate_indexes
            if bundle.records[idx].property_id == property_id
            and bundle.records[idx].stay_month == target_day.month
        ]
        selected_indexes = exact_matches[:top_k]
        comparison_scope = "same_property_same_month"
        if not selected_indexes:
            selected_indexes = [
                idx for idx in candidate_indexes if bundle.records[idx].property_id == property_id
            ][:top_k]
            comparison_scope = "same_property"
        if not selected_indexes:
            selected_indexes = candidate_indexes[:top_k]
            comparison_scope = "portfolio_fallback"

        lookalikes: list[dict[str, Any]] = []
        selected_records: list[HistoricalStayRecord] = []
        for idx in selected_indexes:
            record = bundle.records[idx]
            selected_records.append(record)
            score = _similarity(query_vector, bundle.vectors[idx])
            lookalikes.append(
                {
                    "property_id": record.property_id,
                    "stay_date": record.stay_date,
                    "nightly_rate": round(record.nightly_rate, 2),
                    "total_revenue": round(record.total_revenue, 2),
                    "guests": record.guests,
                    "nights": record.nights,
                    "booked_at": record.booked_at,
                    "lead_days": record.lead_days,
                    "addons_total": round(record.addons_total, 2),
                    "price_resistance": record.price_resistance,
                    "event_hint": record.event_hint,
                    "similarity": score,
                    "source_file": record.source_file,
                }
            )

        if not selected_records:
            return {
                "status": "no_history",
                "property_id": property_id,
                "target_date": target_day.isoformat(),
                "match_count": 0,
                "comparison_scope": comparison_scope,
                "lookalikes": [],
                "opportunity_gap_suggested": 0.0,
            }

        last_year_rate = self._last_year_rate(bundle.records, property_id=property_id, target_day=target_day)
        avg_rate = sum(item.nightly_rate for item in selected_records) / len(selected_records)
        peak_rate = max(item.nightly_rate for item in selected_records)
        avg_lead_days = self._mean([item.lead_days for item in selected_records if item.lead_days is not None])
        occupancy_ratio = self._occupancy_ratio(selected_records)
        addon_attach_rate = round(
            sum(1 for item in selected_records if item.addons_total > 0) / len(selected_records),
            4,
        )
        price_resistance_rate = round(
            sum(1 for item in selected_records if item.price_resistance) / len(selected_records),
            4,
        )
        optimization_anchor = max(
            value for value in (peak_rate, last_year_rate or 0.0, avg_rate) if value is not None
        )
        opportunity_gap = max(optimization_anchor - avg_rate, 0.0)

        return {
            "status": "ok",
            "property_id": property_id,
            "target_date": target_day.isoformat(),
            "comparison_scope": comparison_scope,
            "match_count": len(selected_records),
            "index_backend": bundle.index_backend,
            "historical_avg": round(avg_rate, 2),
            "historical_peak": round(peak_rate, 2),
            "last_year_rate": round(last_year_rate, 2) if last_year_rate is not None else None,
            "occupancy_trend": self._occupancy_trend(occupancy_ratio=occupancy_ratio, avg_lead_days=avg_lead_days),
            "occupancy_booked_ratio": round(occupancy_ratio, 4) if occupancy_ratio is not None else None,
            "sold_out_by_now": bool(occupancy_ratio is not None and occupancy_ratio >= 0.95),
            "avg_lead_days": round(avg_lead_days, 1) if avg_lead_days is not None else None,
            "addon_attach_rate": addon_attach_rate,
            "price_resistance_rate": price_resistance_rate,
            "opportunity_gap_suggested": round(opportunity_gap, 2),
            "lookalikes": lookalikes,
        }

    def _rebuild_persistent_index_sync(self) -> dict[str, Any]:
        bundle = self._build_bundle()
        self.index_path.mkdir(parents=True, exist_ok=True)
        records_path = self.index_path / "history_records.json"
        manifest_path = self.index_path / "history_manifest.json"
        with records_path.open("w", encoding="utf-8") as handle:
            json.dump([asdict(record) for record in bundle.records], handle, indent=2)

        manifest: dict[str, Any] = {
            "signature": bundle.signature,
            "record_count": len(bundle.records),
            "vector_dim": self.vector_dim,
            "built_at": bundle.built_at,
            "index_backend": bundle.index_backend,
            "records_path": str(records_path),
        }

        if faiss is not None and np is not None and bundle.records:
            vector_array = np.array(bundle.vectors, dtype="float32")
            index = faiss.IndexFlatIP(self.vector_dim)
            index.add(vector_array)
            faiss_path = self.index_path / "history.index.faiss"
            faiss.write_index(index, str(faiss_path))
            manifest["faiss_index_path"] = str(faiss_path)

        with manifest_path.open("w", encoding="utf-8") as handle:
            json.dump(manifest, handle, indent=2)

        self._bundle_cache = bundle
        return {
            "status": "ok",
            "record_count": len(bundle.records),
            "index_backend": bundle.index_backend,
            "signature": bundle.signature,
            "manifest_path": str(manifest_path),
            "records_path": str(records_path),
        }

    def _load_bundle(self) -> HistoryIndexBundle:
        current_signature = self._directory_signature()
        if self._bundle_cache and self._bundle_cache.signature == current_signature:
            return self._bundle_cache

        manifest_path = self.index_path / "history_manifest.json"
        records_path = self.index_path / "history_records.json"
        if manifest_path.exists() and records_path.exists():
            try:
                manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
                if manifest.get("signature") == current_signature:
                    records = [
                        HistoricalStayRecord(**row)
                        for row in json.loads(records_path.read_text(encoding="utf-8"))
                    ]
                    vectors = [self._vectorize_record(record) for record in records]
                    bundle = HistoryIndexBundle(
                        signature=current_signature,
                        records=records,
                        vectors=vectors,
                        built_at=manifest.get("built_at") or datetime.now(UTC).isoformat(timespec="seconds"),
                        index_backend=manifest.get("index_backend") or self._backend_name(),
                    )
                    self._bundle_cache = bundle
                    return bundle
            except Exception as exc:  # noqa: BLE001
                logger.warning("history_manifest_load_failed", error=str(exc)[:300])

        bundle = self._build_bundle(signature=current_signature)
        self._bundle_cache = bundle
        return bundle

    def _build_bundle(self, *, signature: Optional[str] = None) -> HistoryIndexBundle:
        records = self._load_records()
        vectors = [self._vectorize_record(record) for record in records]
        return HistoryIndexBundle(
            signature=signature or self._directory_signature(),
            records=records,
            vectors=vectors,
            built_at=datetime.now(UTC).isoformat(timespec="seconds"),
            index_backend=self._backend_name(),
        )

    def _backend_name(self) -> str:
        return "faiss" if faiss is not None and np is not None else "python_fallback"

    def _search_vectors(self, bundle: HistoryIndexBundle, query_vector: list[float], top_k: int) -> list[int]:
        if not bundle.records:
            return []
        top_k = min(top_k, len(bundle.records))
        if top_k <= 0:
            return []
        if faiss is not None and np is not None:
            try:
                index = faiss.IndexFlatIP(self.vector_dim)
                index.add(np.array(bundle.vectors, dtype="float32"))
                _, idxs = index.search(np.array([query_vector], dtype="float32"), top_k)
                return [int(idx) for idx in idxs[0] if int(idx) >= 0]
            except Exception as exc:  # noqa: BLE001
                logger.warning("history_faiss_search_failed", error=str(exc)[:300])
        scored = [
            (idx, _similarity(query_vector, record_vector))
            for idx, record_vector in enumerate(bundle.vectors)
        ]
        scored.sort(key=lambda item: item[1], reverse=True)
        return [idx for idx, _score in scored[:top_k]]

    def _load_records(self) -> list[HistoricalStayRecord]:
        records: list[HistoricalStayRecord] = []
        for path in self._discover_history_files():
            try:
                if path.suffix.lower() == ".csv":
                    records.extend(self._load_csv(path))
                elif path.suffix.lower() == ".json":
                    records.extend(self._load_json(path))
                elif path.suffix.lower() == ".jsonl":
                    records.extend(self._load_jsonl(path))
                else:
                    records.extend(self._load_sqlite(path))
            except Exception as exc:  # noqa: BLE001
                logger.warning("history_file_parse_failed", path=str(path), error=str(exc)[:300])
        return records

    def _discover_history_files(self) -> list[Path]:
        if not self.history_path.exists():
            logger.info("history_path_missing", path=str(self.history_path))
            return []
        files = [
            path
            for path in self.history_path.rglob("*")
            if path.is_file() and path.suffix.lower() in SUPPORTED_EXTENSIONS
            and self.index_path not in path.parents
        ]
        return sorted(files, key=lambda item: str(item))

    def _load_csv(self, path: Path) -> list[HistoricalStayRecord]:
        with path.open("r", encoding="utf-8-sig", newline="") as handle:
            reader = csv.DictReader(handle)
            return self._normalize_rows(reader, source_file=str(path))

    def _load_json(self, path: Path) -> list[HistoricalStayRecord]:
        payload = json.loads(path.read_text(encoding="utf-8"))
        if isinstance(payload, list):
            rows = payload
        elif isinstance(payload, dict):
            for key in ("records", "items", "bookings", "reservations", "data"):
                if isinstance(payload.get(key), list):
                    rows = payload[key]
                    break
            else:
                rows = [payload]
        else:
            rows = []
        return self._normalize_rows(rows, source_file=str(path))

    def _load_jsonl(self, path: Path) -> list[HistoricalStayRecord]:
        rows = []
        with path.open("r", encoding="utf-8") as handle:
            for line in handle:
                line = line.strip()
                if line:
                    rows.append(json.loads(line))
        return self._normalize_rows(rows, source_file=str(path))

    def _load_sqlite(self, path: Path) -> list[HistoricalStayRecord]:
        connection = sqlite3.connect(str(path))
        connection.row_factory = sqlite3.Row
        try:
            tables = [
                row[0]
                for row in connection.execute(
                    "SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%'"
                ).fetchall()
            ]
            rows: list[HistoricalStayRecord] = []
            for table in tables:
                table_rows = connection.execute(f'SELECT * FROM "{table}"').fetchall()
                if not table_rows:
                    continue
                normalized_rows = [dict(row) for row in table_rows]
                rows.extend(self._normalize_rows(normalized_rows, source_file=f"{path}::{table}"))
            return rows
        finally:
            connection.close()

    def _normalize_rows(
        self,
        rows: Iterable[dict[str, Any]],
        *,
        source_file: str,
    ) -> list[HistoricalStayRecord]:
        normalized: list[HistoricalStayRecord] = []
        for idx, row in enumerate(rows):
            if not isinstance(row, dict):
                continue
            record = self._normalize_record(row, source_file=source_file, source_row_id=str(idx))
            if record is not None:
                normalized.append(record)
        return normalized

    def _normalize_record(
        self,
        row: dict[str, Any],
        *,
        source_file: str,
        source_row_id: str,
    ) -> Optional[HistoricalStayRecord]:
        property_id = _safe_text(_extract_field(row, "property_id"))
        if not property_id:
            return None

        stay_day = _parse_date(_extract_field(row, "stay_date"))
        check_out_day = _parse_date(_extract_field(row, "check_out"))
        nights = _coerce_int(_extract_field(row, "nights"))
        if stay_day is None:
            return None
        if nights is None and check_out_day is not None and check_out_day > stay_day:
            nights = max((check_out_day - stay_day).days, 1)
        nights = max(nights or 1, 1)

        nightly_rate = _coerce_float(_extract_field(row, "nightly_rate"))
        total_revenue = _coerce_float(_extract_field(row, "total_revenue"))
        if nightly_rate is None and total_revenue is not None:
            nightly_rate = total_revenue / nights
        if total_revenue is None and nightly_rate is not None:
            total_revenue = nightly_rate * nights
        if nightly_rate is None or total_revenue is None:
            return None

        guests = max(_coerce_int(_extract_field(row, "guests")) or 2, 1)
        booked_at = _parse_date(_extract_field(row, "booked_at"))
        notes = _safe_text(_extract_field(row, "notes"))
        event_hint = _safe_text(_extract_field(row, "event_type"))
        addons_total = _coerce_float(_extract_field(row, "addons_total")) or 0.0
        occupancy_flag = _coerce_bool(_extract_field(row, "occupied"))
        if occupancy_flag is None:
            status_text = " ".join(_safe_text(row.get(key)) for key in row.keys()).lower()
            if "cancel" in status_text:
                occupancy_flag = False
            elif "booked" in status_text or "confirmed" in status_text:
                occupancy_flag = True
        price_resistance = any(keyword in notes.lower() for keyword in PRICE_RESISTANCE_KEYWORDS)
        if not price_resistance:
            event_lower = event_hint.lower()
            price_resistance = any(keyword in event_lower for keyword in PRICE_RESISTANCE_KEYWORDS)
        if addons_total <= 0 and any(keyword in notes.lower() for keyword in POSITIVE_ADDON_KEYWORDS):
            addons_total = 1.0

        return HistoricalStayRecord(
            property_id=property_id,
            stay_date=stay_day.isoformat(),
            stay_month=stay_day.month,
            nightly_rate=float(nightly_rate),
            total_revenue=float(total_revenue),
            guests=guests,
            nights=nights,
            booked_at=booked_at.isoformat() if booked_at else None,
            occupancy_flag=occupancy_flag,
            addons_total=float(addons_total),
            price_resistance=price_resistance,
            notes=notes[:500],
            event_hint=event_hint[:120],
            source_file=source_file,
            source_row_id=source_row_id,
        )

    def _build_query_vector(
        self,
        *,
        property_id: str,
        target_day: date,
        guests: int,
        nights: int,
        event_hint: str,
    ) -> list[float]:
        pseudo_record = HistoricalStayRecord(
            property_id=property_id,
            stay_date=target_day.isoformat(),
            stay_month=target_day.month,
            nightly_rate=0.0,
            total_revenue=0.0,
            guests=max(guests, 1),
            nights=max(nights, 1),
            booked_at=None,
            occupancy_flag=None,
            addons_total=0.0,
            price_resistance=False,
            notes="",
            event_hint=event_hint,
            source_file="query",
            source_row_id="query",
        )
        return self._vectorize_record(pseudo_record)

    def _vectorize_record(self, record: HistoricalStayRecord) -> list[float]:
        vector = [0.0] * self.vector_dim
        stay_day = record.stay_date_obj
        lead_days = record.lead_days or 0
        vector[0] = min(record.nightly_rate / 1000.0, 3.0)
        vector[1] = min(record.total_revenue / 5000.0, 3.0)
        vector[2] = min(record.guests / 16.0, 1.0)
        vector[3] = min(record.nights / 14.0, 1.0)
        vector[4] = stay_day.month / 12.0
        vector[5] = stay_day.weekday() / 6.0
        vector[6] = min(lead_days / 365.0, 1.0)
        vector[7] = min(record.addons_total / 500.0, 1.0)
        vector[8] = 1.0 if record.price_resistance else 0.0
        vector[9] = 1.0 if record.occupancy_flag else 0.0

        categorical_tokens = [
            f"property:{record.property_id}",
            f"month:{stay_day.month}",
            f"weekday:{stay_day.weekday()}",
            f"season:{_season_for_month(stay_day.month)}",
            f"guests:{_bucketize(record.guests, boundaries=(2, 4, 6, 8, 12))}",
            f"nights:{_bucketize(record.nights, boundaries=(2, 3, 5, 7, 14))}",
            f"lead:{_bucketize(lead_days, boundaries=(7, 14, 30, 60, 120))}",
        ]
        categorical_tokens.extend(
            f"event:{token}" for token in _event_tokens(record.event_hint, record.notes)
        )
        for token in categorical_tokens:
            idx = 10 + _hashed_index(token, self.vector_dim - 10)
            vector[idx] += 1.0
        return _normalize_vector(vector)

    def _directory_signature(self) -> str:
        digest = hashlib.sha256()
        for path in self._discover_history_files():
            stat = path.stat()
            digest.update(str(path.relative_to(self.history_path)).encode("utf-8"))
            digest.update(str(int(stat.st_mtime)).encode("utf-8"))
            digest.update(str(stat.st_size).encode("utf-8"))
        return digest.hexdigest()

    @staticmethod
    def _mean(values: list[int]) -> Optional[float]:
        if not values:
            return None
        return sum(values) / len(values)

    @staticmethod
    def _occupancy_ratio(records: list[HistoricalStayRecord]) -> Optional[float]:
        flags = [record.occupancy_flag for record in records if record.occupancy_flag is not None]
        if not flags:
            return None
        return sum(1 for flag in flags if flag) / len(flags)

    @staticmethod
    def _occupancy_trend(*, occupancy_ratio: Optional[float], avg_lead_days: Optional[float]) -> str:
        if occupancy_ratio is not None:
            if occupancy_ratio >= 0.95:
                return "HIGH"
            if occupancy_ratio >= 0.75:
                return "MEDIUM"
            return "LOW"
        if avg_lead_days is None:
            return "UNKNOWN"
        if avg_lead_days >= 90:
            return "HIGH"
        if avg_lead_days >= 35:
            return "MEDIUM"
        return "LOW"

    @staticmethod
    def _last_year_rate(
        records: list[HistoricalStayRecord],
        *,
        property_id: str,
        target_day: date,
    ) -> Optional[float]:
        candidates: list[tuple[int, float]] = []
        prior_year_day = _safe_prior_year(target_day)
        for record in records:
            if record.property_id != property_id:
                continue
            stay_day = record.stay_date_obj
            if stay_day.year != target_day.year - 1:
                continue
            if stay_day.weekday() != target_day.weekday():
                continue
            distance = abs((stay_day - prior_year_day).days)
            if distance <= 7:
                candidates.append((distance, record.nightly_rate))
        if not candidates:
            return None
        candidates.sort(key=lambda item: item[0])
        return candidates[0][1]
