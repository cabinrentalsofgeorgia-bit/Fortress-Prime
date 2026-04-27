"""Shared INO MarketClub Trade Triangle alert parser.

Used by both:
- scripts/phase1_nas_loader.py    (parses JSON files from NAS)
- scripts/phase3_imap_harvester.py (parses raw email bodies from Gmail)

The subject regex and body regexes are deliberately identical between
the two intake paths. Drift between them would defeat cross-source
dedup — the same alert via NAS vs IMAP must produce identical hashes.

Hash strategy (POST migration 0003):
    SHA256(ticker | alert_timestamp_utc.isoformat() | color | timeframe | score)

source_external_id is NOT in the hash. It is stored alongside for
forensic purposes only.
"""

from __future__ import annotations

import datetime as dt
import hashlib
import json
import re
from dataclasses import dataclass, field
from typing import Any

# Subject line: "Trade Triangle Alert - NYSE_AG NEW Green Daily Trade Triangle of 100"
SUBJECT_RE = re.compile(
    r"Trade Triangle Alert\s*-\s*"
    r"(?P<exchange>[A-Z]+)_(?P<ticker>[A-Z\.\-]+)\s+"
    r"NEW\s+"
    r"(?P<color>Green|Red)\s+"
    r"(?P<timeframe>Monthly|Weekly|Daily)\s+"
    r"Trade Triangle of\s+"
    r"(?P<score>-?\d+)",
    re.IGNORECASE,
)

LAST_RE = re.compile(r"Last\s+(?P<last>[\d,]+\.?\d*)")
NET_CHANGE_RE = re.compile(
    r"Net Change\s+(?P<change>[+-]?[\d,]+\.?\d*)\s+"
    r"\(\s*(?P<pct>[+-]?[\d\.]+)\s*%\s*\)"
)
SCORE_BODY_RE = re.compile(r"Score\s+(?P<score>-?\d+)")
VOLUME_RE = re.compile(r"Volume\s+(?P<volume>\d+)")
OPEN_RE = re.compile(r"Open\s+(?P<open>[\d,]+\.?\d*)")
DAY_HIGH_RE = re.compile(r"Day High\s+(?P<high>[\d,]+\.?\d*)")
DAY_LOW_RE = re.compile(r"Day Low\s+(?P<low>[\d,]+\.?\d*)")
PREV_CLOSE_RE = re.compile(r"Prev Close\s+(?P<prev>[\d,]+\.?\d*)")


@dataclass
class ParsedObservation:
    source_corpus: str
    source_reference: str
    source_external_id: str | None
    raw_json_path: str | None
    ticker: str
    exchange: str
    triangle_color: str
    timeframe: str
    score: int
    last_price: float | None
    net_change: float | None
    net_change_pct: float | None
    volume: int | None
    open_price: float | None
    day_high: float | None
    day_low: float | None
    prev_close: float | None
    alert_timestamp_utc: dt.datetime
    trading_day: dt.date
    raw_subject: str
    raw_body_text: str
    parse_warnings: list[dict[str, Any]] = field(default_factory=list)

    @property
    def observation_hash(self) -> str:
        """Cross-source dedup hash. Excludes source_external_id."""
        ts_iso = self.alert_timestamp_utc.astimezone(dt.UTC).isoformat()
        parts = [
            self.ticker,
            ts_iso,
            self.triangle_color,
            self.timeframe,
            str(self.score),
        ]
        return hashlib.sha256("|".join(parts).encode("utf-8")).hexdigest()


@dataclass
class ParseResult:
    observation: ParsedObservation | None
    error: str | None
    file_path: str

    @property
    def succeeded(self) -> bool:
        return self.observation is not None and self.error is None


def _parse_decimal(s: str) -> float | None:
    try:
        return float(s.replace(",", ""))
    except (ValueError, AttributeError):
        return None


def _parse_int(s: str) -> int | None:
    try:
        return int(s.replace(",", ""))
    except (ValueError, AttributeError):
        return None


def derive_trading_day(ts: dt.datetime) -> dt.date:
    """Approximate US-equity trading day. UTC - 4h (EDT). Sufficient for
    daily-grain calibration. Replace with proper zoneinfo if Phase 4 needs
    sub-day precision."""
    et = ts.astimezone(dt.UTC) - dt.timedelta(hours=4)
    return et.date()


def parse_alert_fields(
    *,
    subject: str,
    body_text: str,
    alert_timestamp_utc: dt.datetime,
    source_corpus: str,
    source_reference: str,
    source_external_id: str | None,
    raw_json_path: str | None = None,
) -> ParseResult:
    """Parse subject + body into a ParsedObservation.

    Used by both NAS loader (provides source from JSON) and IMAP
    harvester (provides source from email headers). Pure function —
    no I/O.
    """
    if not subject:
        return ParseResult(None, "missing subject", source_reference)

    m = SUBJECT_RE.search(subject)
    if not m:
        return ParseResult(
            None, f"subject did not match pattern: {subject!r}", source_reference
        )

    ticker = m.group("ticker").upper()
    exchange = m.group("exchange").upper()
    color = m.group("color").lower()
    timeframe = m.group("timeframe").lower()
    try:
        score = int(m.group("score"))
    except ValueError:
        return ParseResult(
            None, f"score not an integer: {m.group('score')!r}", source_reference
        )
    if not (-100 <= score <= 100):
        return ParseResult(None, f"score out of range -100..100: {score}", source_reference)

    warnings: list[dict[str, Any]] = []

    def _pull_decimal(rx: re.Pattern[str], group: str, fname: str) -> float | None:
        bm = rx.search(body_text)
        if not bm:
            warnings.append({"field": fname, "reason": "regex_miss"})
            return None
        v = _parse_decimal(bm.group(group))
        if v is None:
            warnings.append(
                {"field": fname, "reason": "decimal_parse_fail", "raw": bm.group(group)}
            )
        return v

    last_price = _pull_decimal(LAST_RE, "last", "last_price")

    nc_match = NET_CHANGE_RE.search(body_text)
    if nc_match:
        net_change = _parse_decimal(nc_match.group("change"))
        net_change_pct = _parse_decimal(nc_match.group("pct"))
    else:
        net_change = None
        net_change_pct = None
        warnings.append({"field": "net_change", "reason": "regex_miss"})

    vol_match = VOLUME_RE.search(body_text)
    volume = _parse_int(vol_match.group("volume")) if vol_match else None
    if volume is None:
        warnings.append(
            {"field": "volume", "reason": "regex_miss" if not vol_match else "int_parse_fail"}
        )

    open_price = _pull_decimal(OPEN_RE, "open", "open_price")
    day_high = _pull_decimal(DAY_HIGH_RE, "high", "day_high")
    day_low = _pull_decimal(DAY_LOW_RE, "low", "day_low")
    prev_close = _pull_decimal(PREV_CLOSE_RE, "prev", "prev_close")

    body_score_match = SCORE_BODY_RE.search(body_text)
    if body_score_match:
        body_score = int(body_score_match.group("score"))
        if body_score != score:
            warnings.append(
                {
                    "field": "score",
                    "reason": "subject_body_mismatch",
                    "subject_score": score,
                    "body_score": body_score,
                }
            )

    obs = ParsedObservation(
        source_corpus=source_corpus,
        source_reference=source_reference,
        source_external_id=source_external_id,
        raw_json_path=raw_json_path,
        ticker=ticker,
        exchange=exchange,
        triangle_color=color,
        timeframe=timeframe,
        score=score,
        last_price=last_price,
        net_change=net_change,
        net_change_pct=net_change_pct,
        volume=volume,
        open_price=open_price,
        day_high=day_high,
        day_low=day_low,
        prev_close=prev_close,
        alert_timestamp_utc=alert_timestamp_utc,
        trading_day=derive_trading_day(alert_timestamp_utc),
        raw_subject=subject,
        raw_body_text=body_text,
        parse_warnings=warnings,
    )
    return ParseResult(obs, None, source_reference)


def parse_alert_json_file(file_path: str, source_corpus: str) -> ParseResult:
    """Parse one INO MarketClub alert JSON file (NAS path)."""
    try:
        with open(file_path, encoding="utf-8") as f:
            doc = json.load(f)
    except (OSError, json.JSONDecodeError) as e:
        return ParseResult(None, f"unreadable_or_invalid_json: {e}", file_path)

    meta = doc.get("meta") or {}
    data = doc.get("data") or {}
    if not data:
        return ParseResult(None, "missing data block", file_path)

    subject = data.get("subject") or ""
    body_text = data.get("body_text") or ""
    timestamp_utc_str = data.get("timestamp_utc")
    if not timestamp_utc_str:
        return ParseResult(None, "missing timestamp", file_path)

    try:
        ts = dt.datetime.fromisoformat(timestamp_utc_str.replace("Z", "+00:00"))
        if ts.tzinfo is None:
            ts = ts.replace(tzinfo=dt.UTC)
    except ValueError as e:
        return ParseResult(
            None, f"unparseable timestamp {timestamp_utc_str!r}: {e}", file_path
        )

    return parse_alert_fields(
        subject=subject,
        body_text=body_text,
        alert_timestamp_utc=ts,
        source_corpus=source_corpus,
        source_reference=file_path,
        source_external_id=meta.get("id"),
        raw_json_path=file_path,
    )
