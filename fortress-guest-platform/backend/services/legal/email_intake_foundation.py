"""Manifest-only Fortress Legal email source-drop planning.

This module is the safety gate before historical email evidence ingestion. It
parses operator-controlled ``.eml`` source drops, extracts chain-of-custody
metadata, makes conservative case/privilege guesses, and emits a manifest.

It deliberately does not touch IMAP flags, Postgres, Qdrant, the NAS vault, or
``process_vault_upload``. Real ingestion stays behind a later operator gate.
"""
from __future__ import annotations

import email
import email.policy
import email.utils
import hashlib
import json
import re
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable

SUPPORTED_EMAIL_SUFFIXES = frozenset({".eml"})
LEGACY_7IL_MIXED_DUMP = Path("/mnt/fortress_nas/legal_vault/7il-v-knight-ndga")

PRIVILEGED_COUNSEL_DOMAINS = frozenset(
    {
        "dralaw.com",
        "fgplaw.com",
        "mhtlegal.com",
        "msp-lawfirm.com",
        "masp-lawfirm.com",
        "wilsonhamilton.com",
        "wilsonpruittlaw.com",
    }
)

PRIVILEGE_NAME_TERMS = frozenset(
    {
        "alicia argo",
        "terry wilson",
        "frank podesta",
        "jason sanker",
        "jsank",
        "attorney-client",
        "attorney client",
        "privileged",
    }
)

OPPOSING_OR_THIRD_PARTY_TERMS = frozenset(
    {
        "brian goldberg",
        "goldberg",
        "fmglaw.com",
        "thatcher",
        "thor james",
        "7il properties",
        "7 il properties",
    }
)

CASE_PATTERNS: tuple[tuple[re.Pattern[str], str], ...] = (
    (re.compile(r"\b2:26-cv-00113\b", re.IGNORECASE), "7il-v-knight-ndga-ii"),
    (re.compile(r"\b2:21-cv-00226\b", re.IGNORECASE), "7il-v-knight-ndga-i"),
    (re.compile(r"\bSUV20260000?13\b", re.IGNORECASE), "fish-trap-suv2026000013"),
    (re.compile(r"\bfish[\s-]?trap\b", re.IGNORECASE), "fish-trap-suv2026000013"),
    (re.compile(r"\bgenerali\b", re.IGNORECASE), "fish-trap-suv2026000013"),
    (re.compile(r"\bvanderb(?:urge|urgh|erge|ergh)\b", re.IGNORECASE), "vanderburge-v-knight-fannin"),
    (re.compile(r"\bfannin county\b", re.IGNORECASE), "vanderburge-v-knight-fannin"),
)

SEVEN_IL_RE = re.compile(r"\b(?:7[\s-]?il|thor james|thatcher)\b", re.IGNORECASE)
MESSAGE_ID_RE = re.compile(r"<[^>]+>")
SUBJECT_PREFIX_RE = re.compile(r"^\s*(?:re|fw|fwd)\s*:\s*", re.IGNORECASE)
EXTERNAL_PREFIX_RE = re.compile(r"^\s*\[(?:external|ext)\]\s*", re.IGNORECASE)


class EmailSourceDropSafetyError(ValueError):
    """Raised when a source-drop path violates the legal intake contract."""


@dataclass(frozen=True)
class AttachmentManifest:
    file_name: str
    content_type: str
    size_bytes: int
    sha256: str
    content_id: str = ""


@dataclass(frozen=True)
class EmailIntakeCandidate:
    source_path: str
    source_relative_path: str
    source_sha256: str
    message_id: str
    in_reply_to: str
    references: list[str]
    thread_key: str
    subject: str
    normalized_subject: str
    sent_at: str | None
    sender: str
    sender_email: str
    to_addresses: list[str]
    cc_addresses: list[str]
    bcc_addresses: list[str]
    participant_domains: list[str]
    body_preview: str
    attachments: list[AttachmentManifest]
    case_slug_guess: str | None
    case_guess_reason: str
    privilege_risk: str
    privilege_reason: str
    intake_decision: str = "manifest_only"


@dataclass(frozen=True)
class SkippedSourceFile:
    source_path: str
    reason: str


@dataclass(frozen=True)
class EmailSourceDropPlan:
    source_root: str
    generated_at: str
    dry_run: bool
    total_files_seen: int
    candidates: list[EmailIntakeCandidate] = field(default_factory=list)
    skipped: list[SkippedSourceFile] = field(default_factory=list)
    errors: list[SkippedSourceFile] = field(default_factory=list)

    @property
    def candidate_count(self) -> int:
        return len(self.candidates)

    @property
    def attachment_count(self) -> int:
        return sum(len(candidate.attachments) for candidate in self.candidates)

    def to_dict(self) -> dict[str, Any]:
        data = asdict(self)
        data["candidate_count"] = self.candidate_count
        data["attachment_count"] = self.attachment_count
        return data


def validate_source_root(source_root: Path, *, allow_legacy_mixed_dump: bool = False) -> Path:
    """Return a resolved source root, rejecting the poisoned legacy 7IL dump."""
    resolved = source_root.expanduser().resolve(strict=False)
    if not allow_legacy_mixed_dump:
        try:
            resolved.relative_to(LEGACY_7IL_MIXED_DUMP)
        except ValueError:
            pass
        else:
            raise EmailSourceDropSafetyError(
                "refusing legacy mixed 7IL legal_vault source drop; use curated "
                "Corporate_Legal/Business_Legal/<case_slug> paths"
            )
    return resolved


def parse_email_file(path: Path, *, source_root: Path | None = None) -> EmailIntakeCandidate:
    raw_bytes = path.read_bytes()
    return parse_email_bytes(raw_bytes, source_path=path, source_root=source_root)


def parse_email_bytes(
    raw_bytes: bytes,
    *,
    source_path: Path,
    source_root: Path | None = None,
) -> EmailIntakeCandidate:
    msg = email.message_from_bytes(raw_bytes, policy=email.policy.default)
    root = source_root.expanduser().resolve(strict=False) if source_root else None
    resolved_path = source_path.expanduser().resolve(strict=False)
    relative_path = _relative_path(resolved_path, root)

    subject = _header(msg.get("Subject", ""))
    normalized_subject = normalize_subject(subject)
    sender_header = _header(msg.get("From", ""))
    sender_name, sender_email = _first_address(sender_header)
    to_addresses = _addresses(msg.get_all("To", []))
    cc_addresses = _addresses(msg.get_all("Cc", []))
    bcc_addresses = _addresses(msg.get_all("Bcc", []))
    participant_domains = sorted(
        {
            _domain(addr)
            for addr in [sender_email, *to_addresses, *cc_addresses, *bcc_addresses]
            if _domain(addr)
        }
    )
    body_preview = _body_preview(msg)
    attachments = _attachments(msg)
    message_id = _header(msg.get("Message-ID", "")).strip()
    in_reply_to = _header(msg.get("In-Reply-To", "")).strip()
    references = _message_ids(_header(msg.get("References", "")))
    sent_at = _sent_at(msg.get("Date"))
    case_slug, case_reason = classify_case_slug(
        subject=subject,
        body_preview=body_preview,
        participants=[sender_email, *to_addresses, *cc_addresses, *bcc_addresses],
        sent_at=sent_at,
    )
    privilege_risk, privilege_reason = classify_privilege_risk(
        subject=subject,
        body_preview=body_preview,
        participant_domains=participant_domains,
        participants=[sender_email, *to_addresses, *cc_addresses, *bcc_addresses],
    )

    return EmailIntakeCandidate(
        source_path=str(resolved_path),
        source_relative_path=relative_path,
        source_sha256=hashlib.sha256(raw_bytes).hexdigest(),
        message_id=message_id,
        in_reply_to=in_reply_to,
        references=references,
        thread_key=thread_key(
            message_id=message_id,
            in_reply_to=in_reply_to,
            references=references,
            normalized_subject=normalized_subject,
            sender_email=sender_email,
            source_sha256=hashlib.sha256(raw_bytes).hexdigest(),
        ),
        subject=subject,
        normalized_subject=normalized_subject,
        sent_at=sent_at,
        sender=sender_name or sender_email,
        sender_email=sender_email,
        to_addresses=to_addresses,
        cc_addresses=cc_addresses,
        bcc_addresses=bcc_addresses,
        participant_domains=participant_domains,
        body_preview=body_preview,
        attachments=attachments,
        case_slug_guess=case_slug,
        case_guess_reason=case_reason,
        privilege_risk=privilege_risk,
        privilege_reason=privilege_reason,
    )


def build_source_drop_plan(
    source_root: Path,
    *,
    limit: int | None = None,
    allow_legacy_mixed_dump: bool = False,
) -> EmailSourceDropPlan:
    root = validate_source_root(source_root, allow_legacy_mixed_dump=allow_legacy_mixed_dump)
    if not root.exists():
        raise FileNotFoundError(f"source root does not exist: {root}")
    if not root.is_dir():
        raise NotADirectoryError(f"source root is not a directory: {root}")

    candidates: list[EmailIntakeCandidate] = []
    skipped: list[SkippedSourceFile] = []
    errors: list[SkippedSourceFile] = []
    total_seen = 0

    for path in _walk_files(root):
        total_seen += 1
        if path.suffix.lower() not in SUPPORTED_EMAIL_SUFFIXES:
            skipped.append(SkippedSourceFile(str(path), "unsupported_suffix"))
            continue
        if limit is not None and len(candidates) >= limit:
            skipped.append(SkippedSourceFile(str(path), "limit_reached"))
            continue
        try:
            candidates.append(parse_email_file(path, source_root=root))
        except Exception as exc:  # pragma: no cover - exact parser errors vary
            errors.append(SkippedSourceFile(str(path), f"{type(exc).__name__}: {exc}"))

    return EmailSourceDropPlan(
        source_root=str(root),
        generated_at=datetime.now(timezone.utc).isoformat(),
        dry_run=True,
        total_files_seen=total_seen,
        candidates=candidates,
        skipped=skipped,
        errors=errors,
    )


def write_manifest(plan: EmailSourceDropPlan, output_path: Path) -> Path:
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(json.dumps(plan.to_dict(), indent=2, sort_keys=True), encoding="utf-8")
    return output_path


def normalize_subject(subject: str) -> str:
    out = subject or ""
    previous = None
    while out != previous:
        previous = out
        out = EXTERNAL_PREFIX_RE.sub("", out)
        out = SUBJECT_PREFIX_RE.sub("", out)
    out = re.sub(r"\s+", " ", out).strip()
    return out


def thread_key(
    *,
    message_id: str,
    in_reply_to: str,
    references: list[str],
    normalized_subject: str,
    sender_email: str,
    source_sha256: str,
) -> str:
    if references:
        return f"ref:{references[0].lower()}"
    if in_reply_to:
        return f"reply:{in_reply_to.lower()}"
    if message_id:
        return f"msg:{message_id.lower()}"
    domain = _domain(sender_email) or "unknown"
    if normalized_subject:
        return f"subject:{domain}:{normalized_subject.lower()}"
    return f"sha256:{source_sha256}"


def classify_case_slug(
    *,
    subject: str,
    body_preview: str,
    participants: Iterable[str],
    sent_at: str | None,
) -> tuple[str | None, str]:
    haystack = " ".join([subject or "", body_preview or "", *participants])
    for pattern, case_slug in CASE_PATTERNS:
        if pattern.search(haystack):
            return case_slug, f"matched:{pattern.pattern}"
    if SEVEN_IL_RE.search(haystack):
        if sent_at and sent_at[:4].isdigit() and int(sent_at[:4]) >= 2026:
            return "7il-v-knight-ndga-ii", "seven_il_date_window:2026_plus"
        return "7il-v-knight-ndga-i", "seven_il_date_window:pre_2026_or_unknown"
    return None, "no_deterministic_case_signal"


def classify_privilege_risk(
    *,
    subject: str,
    body_preview: str,
    participant_domains: Iterable[str],
    participants: Iterable[str],
) -> tuple[str, str]:
    domains = set(participant_domains)
    privileged_domains = sorted(domains & PRIVILEGED_COUNSEL_DOMAINS)
    if privileged_domains:
        return "likely_privileged", f"privileged_counsel_domain:{privileged_domains[0]}"

    haystack = " ".join([subject or "", body_preview or "", *participants]).lower()
    for term in PRIVILEGE_NAME_TERMS:
        if term in haystack:
            return "likely_privileged", f"privilege_term:{term}"
    for term in OPPOSING_OR_THIRD_PARTY_TERMS:
        if term in haystack:
            return "work_product_or_opposing_party", f"opposing_or_third_party_term:{term}"
    return "unknown", "no_privilege_signal"


def _walk_files(root: Path) -> Iterable[Path]:
    for path in sorted(root.rglob("*")):
        if any(part == "@eaDir" or part.startswith(".") for part in path.parts):
            continue
        if path.is_file():
            yield path


def _header(value: Any) -> str:
    return str(value or "").replace("\r", " ").replace("\n", " ").strip()


def _first_address(header_value: str) -> tuple[str, str]:
    addresses = email.utils.getaddresses([header_value])
    if not addresses:
        return "", ""
    name, addr = addresses[0]
    return _header(name), addr.lower().strip()


def _addresses(headers: Iterable[str]) -> list[str]:
    return [addr.lower().strip() for _name, addr in email.utils.getaddresses(list(headers)) if addr]


def _domain(address: str) -> str:
    if "@" not in address:
        return ""
    return address.rsplit("@", 1)[-1].lower().strip()


def _relative_path(path: Path, root: Path | None) -> str:
    if root is None:
        return path.name
    try:
        return str(path.relative_to(root))
    except ValueError:
        return path.name


def _message_ids(value: str) -> list[str]:
    return [match.lower() for match in MESSAGE_ID_RE.findall(value or "")]


def _sent_at(value: str | None) -> str | None:
    if not value:
        return None
    try:
        parsed = email.utils.parsedate_to_datetime(value)
    except (TypeError, ValueError):
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc).isoformat()


def _body_preview(msg: email.message.EmailMessage, *, max_chars: int = 1000) -> str:
    bodies: list[str] = []
    if msg.is_multipart():
        for part in msg.walk():
            if part.is_multipart() or part.get_content_disposition() == "attachment":
                continue
            if part.get_content_type() != "text/plain":
                continue
            bodies.append(_part_text(part))
            if bodies:
                break
    else:
        bodies.append(_part_text(msg))
    text = re.sub(r"\s+", " ", " ".join(bodies)).strip()
    return text[:max_chars]


def _part_text(part: email.message.EmailMessage) -> str:
    payload = part.get_payload(decode=True)
    if payload is None:
        return ""
    charset = part.get_content_charset() or "utf-8"
    return payload.decode(charset, errors="replace")


def _attachments(msg: email.message.EmailMessage) -> list[AttachmentManifest]:
    out: list[AttachmentManifest] = []
    for part in msg.walk():
        if part.is_multipart():
            continue
        filename = part.get_filename()
        disposition = part.get_content_disposition()
        if disposition != "attachment" and not filename:
            continue
        payload = part.get_payload(decode=True) or b""
        out.append(
            AttachmentManifest(
                file_name=_header(filename or "attachment"),
                content_type=part.get_content_type() or "application/octet-stream",
                size_bytes=len(payload),
                sha256=hashlib.sha256(payload).hexdigest(),
                content_id=_header(part.get("Content-ID", "")),
            )
        )
    return out
