"""
Captain — Multi-mailbox email intake (Gmail API + cPanel IMAP).

Polls every configured mailbox, hooks privilege_filter.classify_for_capture()
on every captured email, and routes the result to llm_training_captures
(ALLOW) or restricted_captures (RESTRICTED). BLOCK results are dropped.

Configuration comes from the MAILBOXES_CONFIG env var — a JSON list where
each entry has:

    {
      "name":             "legal-cpanel",
      "transport":        "imap" | "gmail_api",
      "host":             "mail.cabin-rentals-of-georgia.com",
      "port":             993,
      "address":          "legal@cabin-rentals-of-georgia.com",
      "credentials_ref":  "MAILPLUS_PASSWORD_LEGAL_CABIN_RENTALS",
      "poll_interval_sec": 120,
      "routing_tag":      "legal"
    }

For IMAP entries `credentials_ref` names an env var holding the password;
for Gmail API entries it is ignored — OAuth credentials are read from
GMAIL_CLIENT_ID / GMAIL_CLIENT_SECRET / GMAIL_REFRESH_TOKEN.

No schema migration is required: captures land in the existing
llm_training_captures / restricted_captures tables, and source_mailbox
and routing_tag are written into the capture_metadata JSONB column.
"""
from __future__ import annotations

import asyncio
import email as email_lib
import imaplib
import json
import os
import re
import uuid
from dataclasses import dataclass, field
from email.header import decode_header
from email.message import Message
from typing import Any, Optional

import structlog

from backend.core.config import settings
from backend.services.privilege_filter import (
    CaptureDecision,
    CaptureRoute,
    classify_for_capture,
)

logger = structlog.get_logger(service="captain_multi_mailbox")


# ──────────────────────────────────────────────────────────────────────────────
# Config
# ──────────────────────────────────────────────────────────────────────────────

class MailboxConfigError(ValueError):
    """Raised when MAILBOXES_CONFIG is malformed."""


VALID_TRANSPORTS = frozenset({"imap", "gmail_api"})
VALID_ROUTING_TAGS = frozenset({"operations", "legal", "executive"})


@dataclass(frozen=True)
class MailboxConfig:
    name: str
    transport: str
    address: str
    routing_tag: str
    host: str = ""
    port: int = 993
    credentials_ref: str = ""
    poll_interval_sec: int = 120
    folder: str = "INBOX"

    def resolve_password(self) -> str:
        if self.transport != "imap":
            return ""
        if not self.credentials_ref:
            raise MailboxConfigError(
                f"mailbox {self.name}: imap transport requires credentials_ref"
            )
        value = os.environ.get(self.credentials_ref, "")
        return value


def load_mailbox_configs(raw: str | None = None) -> list[MailboxConfig]:
    """Parse MAILBOXES_CONFIG env var into a list of MailboxConfig."""
    raw_value = raw if raw is not None else os.environ.get("MAILBOXES_CONFIG", "")
    if not raw_value.strip():
        return []

    try:
        entries = json.loads(raw_value)
    except json.JSONDecodeError as exc:
        raise MailboxConfigError(f"MAILBOXES_CONFIG is not valid JSON: {exc}") from exc

    if not isinstance(entries, list):
        raise MailboxConfigError("MAILBOXES_CONFIG must be a JSON list")

    out: list[MailboxConfig] = []
    seen_addresses: set[str] = set()
    for idx, entry in enumerate(entries):
        if not isinstance(entry, dict):
            raise MailboxConfigError(f"entry #{idx} is not an object")
        name = str(entry.get("name") or "").strip()
        transport = str(entry.get("transport") or "").strip()
        address = str(entry.get("address") or "").strip()
        routing_tag = str(entry.get("routing_tag") or "").strip()
        if not name or not transport or not address or not routing_tag:
            raise MailboxConfigError(
                f"entry #{idx}: name/transport/address/routing_tag are required"
            )
        if transport not in VALID_TRANSPORTS:
            raise MailboxConfigError(
                f"entry {name}: transport must be one of {sorted(VALID_TRANSPORTS)}"
            )
        if routing_tag not in VALID_ROUTING_TAGS:
            raise MailboxConfigError(
                f"entry {name}: routing_tag must be one of {sorted(VALID_ROUTING_TAGS)}"
            )
        if address.lower() in seen_addresses:
            raise MailboxConfigError(f"entry {name}: duplicate address {address}")
        seen_addresses.add(address.lower())

        out.append(MailboxConfig(
            name=name,
            transport=transport,
            address=address,
            routing_tag=routing_tag,
            host=str(entry.get("host") or ""),
            port=int(entry.get("port") or 993),
            credentials_ref=str(entry.get("credentials_ref") or ""),
            poll_interval_sec=int(entry.get("poll_interval_sec") or 120),
            folder=str(entry.get("folder") or "INBOX"),
        ))
    return out


# ──────────────────────────────────────────────────────────────────────────────
# Credential validation (fail loud)
# ──────────────────────────────────────────────────────────────────────────────

# Strings that are clearly placeholders, not real secrets. If a resolved
# credentials_ref lands on any of these, we treat it as unset.
_PLACEHOLDER_PASSWORDS: frozenset[str] = frozenset({
    "",
    "replace_me",
    "replaceme",
    "changeme",
    "change_me",
    "placeholder",
    "dummy",
    "test",
    "<set-via-vault>",
    "set-via-vault",
    "your-password-here",
    "todo",
    "tbd",
})


class MailboxCredentialError(RuntimeError):
    """Raised when a referenced credential is missing, empty, or a placeholder."""


def _is_placeholder(value: str) -> bool:
    return value.strip().lower() in _PLACEHOLDER_PASSWORDS


def validate_mailbox_credentials(mailboxes: list[MailboxConfig]) -> None:
    """
    Fail-loud credential check. Does NOT attempt network I/O — that is the
    job of preflight_authenticate. This only confirms the referenced env
    vars resolve to something that looks like a real secret.

    Raises MailboxCredentialError listing every missing / placeholder
    reference in one go (so operators see the full picture on startup,
    not one failure at a time).
    """
    if not mailboxes:
        return

    problems: list[str] = []
    seen_gmail_creds: bool | None = None

    for mb in mailboxes:
        if mb.transport == "imap":
            if not mb.credentials_ref:
                problems.append(
                    f"{mb.name}: imap mailbox has no credentials_ref"
                )
                continue
            value = os.environ.get(mb.credentials_ref, "")
            if not value:
                problems.append(
                    f"{mb.name}: env var {mb.credentials_ref} is unset"
                )
            elif _is_placeholder(value):
                problems.append(
                    f"{mb.name}: env var {mb.credentials_ref} is a placeholder"
                )
        elif mb.transport == "gmail_api":
            if seen_gmail_creds is None:
                # Gmail OAuth uses shared settings across all gmail_api entries.
                from backend.core.config import settings
                missing: list[str] = []
                if not settings.gmail_client_id \
                        or _is_placeholder(settings.gmail_client_id):
                    missing.append("GMAIL_CLIENT_ID")
                if not settings.gmail_client_secret \
                        or _is_placeholder(settings.gmail_client_secret):
                    missing.append("GMAIL_CLIENT_SECRET")
                if not settings.gmail_refresh_token \
                        or _is_placeholder(settings.gmail_refresh_token):
                    missing.append("GMAIL_REFRESH_TOKEN")
                seen_gmail_creds = not missing
                if missing:
                    problems.append(
                        f"{mb.name}: gmail OAuth incomplete — missing: "
                        f"{', '.join(missing)}"
                    )
            elif not seen_gmail_creds:
                problems.append(f"{mb.name}: gmail OAuth incomplete (see above)")

    if problems:
        # Intentionally terse — no values, only names — to keep secrets out
        # of error text and logs.
        raise MailboxCredentialError(
            "MAILBOXES_CONFIG credential validation failed:\n  - "
            + "\n  - ".join(problems)
        )


# ──────────────────────────────────────────────────────────────────────────────
# Email shape
# ──────────────────────────────────────────────────────────────────────────────

@dataclass
class FetchedEmail:
    subject: str
    body: str
    sender_email: str
    recipient_emails: list[str] = field(default_factory=list)
    attachment_filenames: list[str] = field(default_factory=list)
    message_id: str = ""

    @property
    def sender_domain(self) -> str:
        if "@" not in self.sender_email:
            return ""
        return self.sender_email.rsplit("@", 1)[-1].strip().lower()


def _decode_header_value(raw: Any) -> str:
    if not raw:
        return ""
    parts = decode_header(raw)
    out: list[str] = []
    for content, charset in parts:
        if isinstance(content, bytes):
            out.append(content.decode(charset or "utf-8", errors="replace"))
        else:
            out.append(str(content))
    return " ".join(out)


def _extract_plain_body(msg: Message) -> str:
    if msg.is_multipart():
        for part in msg.walk():
            ctype = part.get_content_type()
            disp = str(part.get("Content-Disposition", ""))
            if ctype == "text/plain" and "attachment" not in disp:
                payload = part.get_payload(decode=True)
                if isinstance(payload, (bytes, bytearray)):
                    charset = part.get_content_charset() or "utf-8"
                    return bytes(payload).decode(charset, errors="replace")
    else:
        payload = msg.get_payload(decode=True)
        if isinstance(payload, (bytes, bytearray)):
            charset = msg.get_content_charset() or "utf-8"
            return bytes(payload).decode(charset, errors="replace")
    return ""


_ADDRESS_RE = re.compile(r"<([^>]+)>")


def _extract_address(raw: str) -> str:
    match = _ADDRESS_RE.search(raw)
    return match.group(1).strip() if match else raw.strip()


def _extract_recipient_list(header_values: list[str]) -> list[str]:
    addresses: list[str] = []
    for value in header_values:
        decoded = _decode_header_value(value)
        for chunk in decoded.split(","):
            addr = _extract_address(chunk)
            if addr and "@" in addr:
                addresses.append(addr)
    return addresses


def _extract_attachments(msg: Message) -> list[str]:
    names: list[str] = []
    if not msg.is_multipart():
        return names
    for part in msg.walk():
        disp = str(part.get("Content-Disposition", ""))
        if "attachment" in disp:
            fname = _decode_header_value(part.get_filename() or "")
            if fname:
                names.append(fname)
    return names


def _parse_rfc822(raw_bytes: bytes) -> FetchedEmail:
    msg = email_lib.message_from_bytes(raw_bytes)
    subject = _decode_header_value(msg.get("Subject", ""))
    from_header = _decode_header_value(msg.get("From", ""))
    sender_email = _extract_address(from_header)
    recipients = _extract_recipient_list(
        msg.get_all("To") or []
    ) + _extract_recipient_list(
        msg.get_all("Cc") or []
    )
    return FetchedEmail(
        subject=subject,
        body=_extract_plain_body(msg),
        sender_email=sender_email,
        recipient_emails=recipients,
        attachment_filenames=_extract_attachments(msg),
        message_id=_decode_header_value(msg.get("Message-ID", "")),
    )


# ──────────────────────────────────────────────────────────────────────────────
# Transports
# ──────────────────────────────────────────────────────────────────────────────

class ImapTransport:
    """
    Blocking IMAP poller. Designed to be dispatched via asyncio.to_thread().

    Opens a fresh IMAP4_SSL connection per fetch cycle. If the first login or
    select fails mid-flight (imaplib.IMAP4.abort, EOFError, OSError), reconnects
    once with a fresh connection — this covers the common cPanel keep-alive
    drop while an IDLE-style loop is waiting. Multiple mailboxes on the same
    host each open their own short-lived connection; cPanel does not support
    concurrent IMAP logins reliably, so pooling is intentionally avoided.
    """

    def __init__(self, mailbox: MailboxConfig, max_messages: int = 25) -> None:
        if mailbox.transport != "imap":
            raise ValueError(f"{mailbox.name}: not an IMAP mailbox")
        if not mailbox.host:
            raise MailboxConfigError(f"{mailbox.name}: imap host is required")
        self.mailbox = mailbox
        self.max_messages = max_messages
        self._reconnects = 0

    @property
    def reconnect_count(self) -> int:
        return self._reconnects

    def _connect(self) -> imaplib.IMAP4_SSL:
        conn = imaplib.IMAP4_SSL(self.mailbox.host, self.mailbox.port)
        password = self.mailbox.resolve_password()
        if not password:
            raise MailboxConfigError(
                f"{self.mailbox.name}: credentials_ref {self.mailbox.credentials_ref} "
                f"is unset or empty"
            )
        conn.login(self.mailbox.address, password)
        conn.select(self.mailbox.folder)
        return conn

    def verify_credentials(self) -> None:
        """Connect + login + logout only. Raises on any failure."""
        conn = self._connect()
        try:
            conn.close()
        except Exception:
            pass
        try:
            conn.logout()
        except Exception:
            pass

    def fetch_unseen(self) -> list[FetchedEmail]:
        attempts = 0
        last_err: Exception | None = None
        while attempts < 2:
            attempts += 1
            conn: Optional[imaplib.IMAP4_SSL] = None
            try:
                conn = self._connect()
                return self._fetch_with(conn)
            except (imaplib.IMAP4.abort, EOFError, OSError,
                    imaplib.IMAP4.error) as exc:
                last_err = exc
                if attempts == 1:
                    self._reconnects += 1
                    logger.warning(
                        "captain_imap_reconnect",
                        mailbox=self.mailbox.name,
                        error=str(exc)[:200],
                    )
                    continue
                logger.error(
                    "captain_imap_final_failure",
                    mailbox=self.mailbox.name,
                    error=str(exc)[:200],
                )
                return []
            finally:
                if conn is not None:
                    try:
                        conn.close()
                    except Exception:
                        pass
                    try:
                        conn.logout()
                    except Exception:
                        pass
        if last_err is not None:
            logger.error(
                "captain_imap_unexpected_exit",
                mailbox=self.mailbox.name,
                error=str(last_err)[:200],
            )
        return []

    def _fetch_with(self, conn: imaplib.IMAP4_SSL) -> list[FetchedEmail]:
        _, msg_nums = conn.search(None, "UNSEEN")
        if not msg_nums or not msg_nums[0]:
            return []
        ids = msg_nums[0].split()[: self.max_messages]
        out: list[FetchedEmail] = []
        for mid in ids:
            try:
                _, data = conn.fetch(mid, "(RFC822)")
                if not data or not data[0]:
                    continue
                raw_value = data[0][1]
                if not isinstance(raw_value, (bytes, bytearray)):
                    continue
                out.append(_parse_rfc822(bytes(raw_value)))
                conn.store(mid, "+FLAGS", "\\Seen")
            except Exception as exc:
                logger.warning(
                    "captain_imap_fetch_error",
                    mailbox=self.mailbox.name,
                    mid=str(mid),
                    error=str(exc)[:200],
                )
        return out


class GmailApiTransport:
    """
    Gmail API poller using the users.messages endpoint with pageToken
    pagination. Uses GMAIL_CLIENT_ID / GMAIL_CLIENT_SECRET / GMAIL_REFRESH_TOKEN
    from settings to build OAuth2 credentials.

    Delegates the HTTP transport to a `client` callable that returns a Gmail
    service object. The callable is injectable so tests can hand in a mock
    without pulling in googleapiclient.
    """

    def __init__(
        self,
        mailbox: MailboxConfig,
        max_messages: int = 50,
        client_factory: Optional[Any] = None,
    ) -> None:
        if mailbox.transport != "gmail_api":
            raise ValueError(f"{mailbox.name}: not a gmail_api mailbox")
        self.mailbox = mailbox
        self.max_messages = max_messages
        self._client_factory = client_factory
        self._service: Any | None = None

    def _build_service(self) -> Any:
        if self._service is not None:
            return self._service
        if self._client_factory is not None:
            self._service = self._client_factory()
            return self._service
        # Lazy import so installations without googleapiclient can still
        # load the module (e.g. test-only environments).
        from google.oauth2.credentials import Credentials  # type: ignore[import-not-found]
        from googleapiclient.discovery import build  # type: ignore[import-not-found]

        creds = Credentials(
            token=None,
            refresh_token=settings.gmail_refresh_token,
            token_uri="https://oauth2.googleapis.com/token",
            client_id=settings.gmail_client_id,
            client_secret=settings.gmail_client_secret,
            scopes=["https://www.googleapis.com/auth/gmail.readonly",
                    "https://www.googleapis.com/auth/gmail.modify"],
        )
        self._service = build("gmail", "v1", credentials=creds, cache_discovery=False)
        return self._service

    def verify_credentials(self) -> None:
        """Build the service and call users().getProfile() to force auth."""
        service = self._build_service()
        service.users().getProfile(userId="me").execute()

    def fetch_unseen(self) -> list[FetchedEmail]:
        try:
            service = self._build_service()
        except Exception as exc:
            logger.error(
                "captain_gmail_build_failed",
                mailbox=self.mailbox.name,
                error=str(exc)[:200],
            )
            return []

        ids: list[str] = []
        page_token: str | None = None
        while len(ids) < self.max_messages:
            req = service.users().messages().list(
                userId="me",
                q="is:unread",
                pageToken=page_token,
                maxResults=min(100, self.max_messages - len(ids)),
            )
            try:
                resp = req.execute()
            except Exception as exc:
                logger.error(
                    "captain_gmail_list_failed",
                    mailbox=self.mailbox.name,
                    error=str(exc)[:200],
                )
                break
            for m in resp.get("messages", []) or []:
                mid = m.get("id")
                if mid:
                    ids.append(mid)
            page_token = resp.get("nextPageToken")
            if not page_token:
                break

        out: list[FetchedEmail] = []
        for mid in ids[: self.max_messages]:
            try:
                raw_resp = service.users().messages().get(
                    userId="me", id=mid, format="raw"
                ).execute()
                import base64
                raw_b64 = raw_resp.get("raw", "")
                raw_bytes = base64.urlsafe_b64decode(raw_b64.encode("utf-8"))
                out.append(_parse_rfc822(raw_bytes))
                service.users().messages().modify(
                    userId="me", id=mid,
                    body={"removeLabelIds": ["UNREAD"]},
                ).execute()
            except Exception as exc:
                logger.warning(
                    "captain_gmail_fetch_error",
                    mailbox=self.mailbox.name,
                    mid=str(mid),
                    error=str(exc)[:200],
                )
        return out


def build_transport(
    mailbox: MailboxConfig,
    gmail_client_factory: Optional[Any] = None,
) -> Any:
    """Build a transport for a mailbox. Factory hook for Gmail testing."""
    if mailbox.transport == "imap":
        return ImapTransport(mailbox)
    if mailbox.transport == "gmail_api":
        return GmailApiTransport(mailbox, client_factory=gmail_client_factory)
    raise MailboxConfigError(f"{mailbox.name}: unknown transport {mailbox.transport}")


# ──────────────────────────────────────────────────────────────────────────────
# Capture persistence — privilege_filter hook + write
# ──────────────────────────────────────────────────────────────────────────────

def _build_capture_metadata(em: FetchedEmail, mailbox: MailboxConfig) -> dict[str, Any]:
    return {
        "source_mailbox": mailbox.address,
        "routing_tag": mailbox.routing_tag,
        "transport": mailbox.transport,
        "sender_email": em.sender_email,
        "sender_domain": em.sender_domain,
        "recipient_emails": list(em.recipient_emails),
        "attachment_filenames": list(em.attachment_filenames),
    }


def classify_email(em: FetchedEmail, mailbox: MailboxConfig) -> CaptureDecision:
    """Run privilege_filter over a captured email with full context."""
    metadata = _build_capture_metadata(em, mailbox)
    return classify_for_capture(
        prompt=em.subject,
        response=em.body,
        source_module=f"captain_{mailbox.routing_tag}",
        metadata=metadata,
    )


async def write_capture(
    em: FetchedEmail,
    mailbox: MailboxConfig,
    decision: CaptureDecision,
    session_factory: Any | None = None,
) -> str:
    """Persist a capture per the privilege_filter decision. Returns route value."""
    if decision.route == CaptureRoute.BLOCK:
        logger.info(
            "captain_capture_blocked",
            mailbox=mailbox.name,
            reason=decision.reason,
        )
        return decision.route.value

    if session_factory is None:
        from backend.core.database import AsyncSessionLocal
        factory: Any = AsyncSessionLocal
    else:
        factory = session_factory

    from sqlalchemy import text as sqltext
    capture_meta = _build_capture_metadata(em, mailbox)
    source_module = f"captain_{mailbox.routing_tag}"
    prompt_text = em.subject or ""
    response_text = em.body or ""

    async with factory() as session:
        if decision.route == CaptureRoute.ALLOW:
            await session.execute(
                sqltext("""
                    INSERT INTO llm_training_captures
                        (id, source_module, model_used, user_prompt, assistant_resp,
                         status, capture_metadata)
                    VALUES
                        (CAST(:id AS uuid), :module, :model, :prompt, :response,
                         'pending', CAST(:meta AS jsonb))
                    ON CONFLICT DO NOTHING
                """),
                {
                    "id": str(uuid.uuid4()),
                    "module": source_module[:120],
                    "model": "captain_intake",
                    "prompt": prompt_text[:32_000],
                    "response": response_text[:32_000],
                    "meta": json.dumps(capture_meta),
                },
            )
        else:  # RESTRICTED
            await session.execute(
                sqltext("""
                    INSERT INTO restricted_captures
                        (source_module, prompt, response,
                         restriction_reason, matched_patterns, capture_metadata)
                    VALUES
                        (:module, :prompt, :response, :reason, :patterns,
                         CAST(:meta AS jsonb))
                """),
                {
                    "module": source_module[:120],
                    "prompt": prompt_text[:32_000],
                    "response": response_text[:32_000],
                    "reason": decision.reason[:256],
                    "patterns": list(decision.matched_patterns),
                    "meta": json.dumps(capture_meta),
                },
            )
        await session.commit()
    return decision.route.value


async def process_email(
    em: FetchedEmail,
    mailbox: MailboxConfig,
    session_factory: Any | None = None,
) -> dict[str, str]:
    """Classify + persist one email. Returns dict with route and routing_tag."""
    decision = classify_email(em, mailbox)
    route = await write_capture(em, mailbox, decision, session_factory=session_factory)
    logger.info(
        "captain_email_processed",
        mailbox=mailbox.name,
        routing_tag=mailbox.routing_tag,
        route=route,
        reason=decision.reason[:120],
    )
    return {
        "mailbox": mailbox.name,
        "routing_tag": mailbox.routing_tag,
        "route": route,
    }


# ──────────────────────────────────────────────────────────────────────────────
# Patrol + loop
# ──────────────────────────────────────────────────────────────────────────────

async def run_patrol(
    mailboxes: list[MailboxConfig] | None = None,
    session_factory: Any | None = None,
    gmail_client_factory: Any | None = None,
) -> dict[str, Any]:
    """Poll every mailbox once and persist captures. Safe to call on demand."""
    if mailboxes is None:
        mailboxes = load_mailbox_configs()
    if not mailboxes:
        return {"status": "no_mailboxes", "processed": 0}

    stats: dict[str, int] = {"processed": 0, "allow": 0, "restricted": 0, "block": 0}
    by_tag: dict[str, int] = {}

    for mailbox in mailboxes:
        try:
            transport = build_transport(
                mailbox, gmail_client_factory=gmail_client_factory
            )
        except MailboxConfigError as exc:
            logger.error(
                "captain_transport_config_error",
                mailbox=mailbox.name, error=str(exc)[:200],
            )
            continue
        try:
            emails = await asyncio.to_thread(transport.fetch_unseen)
        except Exception as exc:
            logger.error(
                "captain_fetch_error",
                mailbox=mailbox.name, error=str(exc)[:200],
            )
            continue
        for em in emails:
            try:
                result = await process_email(em, mailbox, session_factory=session_factory)
            except Exception as exc:
                logger.error(
                    "captain_process_error",
                    mailbox=mailbox.name, error=str(exc)[:200],
                )
                continue
            stats["processed"] += 1
            stats[result["route"]] = stats.get(result["route"], 0) + 1
            by_tag[result["routing_tag"]] = by_tag.get(result["routing_tag"], 0) + 1

    return {"status": "patrol_complete", "mailboxes": len(mailboxes), **stats, "by_tag": by_tag}


# ──────────────────────────────────────────────────────────────────────────────
# Preflight auth check
# ──────────────────────────────────────────────────────────────────────────────

class PreflightAuthError(RuntimeError):
    """One or more mailboxes failed live authentication."""


async def preflight_authenticate(
    mailboxes: list[MailboxConfig],
    gmail_client_factory: Any | None = None,
) -> list[dict[str, str]]:
    """
    Try a real connect + login against every mailbox. Returns a per-mailbox
    status report (one dict per mailbox). Raises PreflightAuthError if any
    mailbox fails — collected so the operator sees the full picture.

    Runs every IMAP auth in a thread (imaplib is blocking). Gmail builds are
    synchronous in the google client but do a live HTTP request during
    getProfile, so they also run in a thread.
    """
    results: list[dict[str, str]] = []
    failures: list[str] = []

    for mb in mailboxes:
        try:
            transport = build_transport(
                mb, gmail_client_factory=gmail_client_factory
            )
        except (MailboxConfigError, ValueError) as exc:
            results.append({
                "mailbox": mb.name, "address": mb.address,
                "status": "config_error", "error": str(exc)[:200],
            })
            failures.append(f"{mb.name}: config_error — {str(exc)[:200]}")
            continue

        try:
            await asyncio.to_thread(transport.verify_credentials)
        except Exception as exc:
            # Error messages from imap/google sometimes include echoes of the
            # login string — keep it terse and out of the log.
            err_type = type(exc).__name__
            results.append({
                "mailbox": mb.name, "address": mb.address,
                "status": "auth_failed", "error": err_type,
            })
            failures.append(f"{mb.name}: auth_failed — {err_type}")
            logger.error(
                "captain_preflight_auth_failed",
                mailbox=mb.name,
                address=mb.address,
                error_type=err_type,
            )
            continue

        results.append({
            "mailbox": mb.name, "address": mb.address, "status": "ok",
        })
        logger.info(
            "captain_preflight_auth_ok",
            mailbox=mb.name,
            address=mb.address,
            transport=mb.transport,
        )

    if failures:
        raise PreflightAuthError(
            "Captain preflight auth failed for "
            f"{len(failures)}/{len(mailboxes)} mailbox(es):\n  - "
            + "\n  - ".join(failures)
        )
    return results


async def run_captain_multi_mailbox_loop(
    stop_event: asyncio.Event | None = None,
) -> None:
    """Infinite loop. Cancellable via asyncio or the provided stop_event."""
    mailboxes = load_mailbox_configs()
    interval = min((m.poll_interval_sec for m in mailboxes), default=120)
    logger.info(
        "captain_multi_mailbox_loop_started",
        mailboxes=[m.name for m in mailboxes],
        interval=interval,
    )
    await asyncio.sleep(15)
    while True:
        if stop_event is not None and stop_event.is_set():
            return
        try:
            result = await run_patrol(mailboxes=mailboxes)
            if result.get("processed", 0) > 0:
                logger.info("captain_patrol_report", **result)
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            logger.error("captain_loop_error", error=str(exc)[:200])
        await asyncio.sleep(interval)
