"""
Fortress Prime — Taylor Protocol (Persona Extraction Engine)
=============================================================
Mines Taylor Knight's writing voice from the NAS email archives.

STRATEGY:
Taylor's Maildir is her INBOX — emails sent TO her, not FROM her.
However, 1,100+ of those emails contain QUOTED REPLIES of Taylor's
original messages. We extract her words from those quoted blocks.

We also scan Gary's Maildir (159K emails) for emails FROM Taylor.

EMBEDDING:
Uses the same Ollama nomic-embed-text (768-dim) as rag_ingest.py
to match the existing fortress_docs collection.

Sources:
    1. Taylor's Maildir (quoted reply extraction)
    2. Gary's Maildir (From: taylor filter)
    3. MailPlus local Maildir (From: taylor filter)

Usage:
    python3 -m src.ingest_taylor          # from Fortress-Prime root
    python3 src/ingest_taylor.py          # direct execution
"""

import os
import sys
import uuid
import re
import time
import email
from email import policy
from email.parser import BytesParser
from pathlib import Path

import requests
import chromadb
from bs4 import BeautifulSoup
from dotenv import load_dotenv

# ── Fortress Path Resolution ──
load_dotenv(Path(__file__).parent.parent / ".env")

try:
    from src.fortress_paths import paths, CHROMA_PATH
except ImportError:
    sys.path.insert(0, str(Path(__file__).parent.parent))
    from src.fortress_paths import paths, CHROMA_PATH

# =============================================================================
# CONFIGURATION
# =============================================================================

NAS_COMMS = Path("/mnt/fortress_nas/Communications/System_MailPlus_Server")

# Taylor's inbox (mine quoted replies)
TAYLOR_INBOX = (
    NAS_COMMS / "ENTERPRISE_DATA_LAKE" / "01_LANDING_ZONE" / "RAW_EMAIL_DUMP"
    / "EXTRACTED_EMAILS" / "backup" / "email"
    / "cabin-rentals-of-georgia.com" / "taylor.knight" / "cur"
)

# Gary's inbox (filter for From: Taylor)
GARY_INBOX = (
    NAS_COMMS / "ENTERPRISE_DATA_LAKE" / "01_LANDING_ZONE" / "RAW_EMAIL_DUMP"
    / "EXTRACTED_EMAILS" / "backup" / "email"
    / "cabin-rentals-of-georgia.com" / "gary" / "cur"
)

# MailPlus local (filter for From: Taylor)
MAILPLUS_LOCAL = NAS_COMMS / "@local" / "1026" / "1026" / "Maildir" / "cur"

# Taylor's known sender addresses
TAYLOR_ADDRS = [
    "taylor@cabin-rentals-of-georgia.com",
    "taylor.knight@cabin-rentals-of-georgia.com",
    "taylor@georgiacabins.com",
    "taylor@crgluxury.com",
]

# Embedding — must match the existing collection (768-dim nomic-embed-text)
EMBED_URL   = os.getenv("EMBED_URL", "http://localhost:11434/api/embeddings")
EMBED_MODEL = os.getenv("EMBED_MODEL", "nomic-embed-text")
EMBED_DIM   = 768

# ChromaDB collection — dedicated persona collection (separate from legal docs)
COLLECTION_NAME = "taylor_voice"
MIN_BODY_LENGTH = 50


# =============================================================================
# EMBEDDING (match rag_ingest.py's 768-dim nomic-embed-text)
# =============================================================================

def get_embedding(text: str, retries: int = 3):
    """Generate 768-dim embedding via Ollama nomic-embed-text."""
    for attempt in range(retries):
        try:
            resp = requests.post(EMBED_URL, json={
                "model": EMBED_MODEL,
                "prompt": text[:8000],  # Cap input length
            }, timeout=30)
            resp.raise_for_status()
            embedding = resp.json().get("embedding", [])
            if embedding and len(embedding) == EMBED_DIM:
                return embedding
        except Exception as e:
            if attempt < retries - 1:
                time.sleep(1)
            else:
                print(f"  [WARN] Embedding failed: {e}")
    return None


# =============================================================================
# EMAIL PARSING HELPERS
# =============================================================================

def parse_email_safe(filepath: str):
    """Parse an email file, returning the Message object or None."""
    try:
        with open(filepath, 'rb') as f:
            return BytesParser(policy=policy.default).parse(f)
    except Exception:
        return None


def get_body(msg) -> str:
    """Extract the best text body from an email Message."""
    body = ""
    if msg.is_multipart():
        for part in msg.walk():
            ctype = part.get_content_type()
            if ctype == "text/plain":
                try:
                    body = part.get_content()
                except Exception:
                    try:
                        payload = part.get_payload(decode=True)
                        if payload:
                            body = payload.decode("utf-8", errors="replace")
                    except Exception:
                        continue
                break
        # Fallback to HTML
        if not body:
            for part in msg.walk():
                if part.get_content_type() == "text/html":
                    try:
                        raw = part.get_content()
                    except Exception:
                        try:
                            payload = part.get_payload(decode=True)
                            raw = payload.decode("utf-8", errors="replace") if payload else ""
                        except Exception:
                            continue
                    if raw:
                        soup = BeautifulSoup(raw, "html.parser")
                        body = soup.get_text(separator="\n")
                    break
    else:
        try:
            body = msg.get_content()
        except Exception:
            try:
                payload = msg.get_payload(decode=True)
                if payload:
                    body = payload.decode("utf-8", errors="replace")
            except Exception:
                body = ""

    # Final HTML cleanup
    if body and "<html" in body.lower():
        soup = BeautifulSoup(body, "html.parser")
        body = soup.get_text(separator="\n")

    return body if isinstance(body, str) else ""


def is_from_taylor(msg) -> bool:
    """Check if the email's From: header matches Taylor's addresses."""
    sender = (msg.get("From", "") or "").lower()
    return any(addr in sender for addr in TAYLOR_ADDRS)


# =============================================================================
# TAYLOR VOICE EXTRACTION FROM QUOTED REPLIES
# =============================================================================

def extract_taylor_quoted(body: str) -> str:
    """
    Extract Taylor's original message from a quoted reply chain.

    Handles BOTH single-line and multi-line attributions:
      Single: > On May 14, Taylor Knight <email> wrote:
      Multi:  On Wed, May 15, 2019 at 9:54 AM Taylor Knight <
              taylor.knight@cabin-rentals-of-georgia.com> wrote:
      Forward: > From: Taylor Knight <email>

    Extracts the quoted `> ` lines after the attribution as Taylor's words.
    """
    lines = body.split("\n")
    taylor_blocks = []
    current_block = []
    capturing = False
    skip_headers = False  # For forwarded message headers after From:

    for i, line in enumerate(lines):
        raw = line
        # Strip leading `> ` for attribution matching (but keep original for later)
        stripped_no_quote = re.sub(r'^>+\s*', '', line).strip()

        # ── Check for Taylor attribution (single line) ──
        # "On <date>, Taylor Knight <email> wrote:"
        if re.search(r'Taylor\s+Knight\s*<[^>]*>.*?wrote:', raw, re.IGNORECASE):
            if current_block:
                taylor_blocks.append(current_block)
            current_block = []
            capturing = True
            skip_headers = False
            continue

        # "From: Taylor Knight <email>" (forwarded)
        if re.search(r'From:\s*(?:"?Taylor\s+Knight"?\s*<|taylor\.?knight@)', raw, re.IGNORECASE):
            if current_block:
                taylor_blocks.append(current_block)
            current_block = []
            capturing = True
            skip_headers = True  # Skip Subject/Date/To/Cc headers
            continue

        # ── Check for multi-line attribution ──
        # Line N: "On Wed, May 15, 2019 at 9:54 AM Taylor Knight <"
        # Line N+1: "taylor.knight@cabin-rentals-of-georgia.com> wrote:"
        if i + 1 < len(lines):
            combined = raw + " " + lines[i + 1]
            if re.search(r'Taylor\s+Knight\s*<[^>]*>.*?wrote:', combined, re.IGNORECASE):
                if current_block:
                    taylor_blocks.append(current_block)
                current_block = []
                capturing = True
                skip_headers = False
                # We'll skip the next line in the loop by marking it
                # Actually we can't skip, but the next line ends with "wrote:"
                # so it won't start with ">" and won't be captured as content
                continue

        if capturing:
            stripped = line.strip()

            # Skip forwarded message headers (Subject:, Date:, To:, Cc:)
            if skip_headers:
                if stripped_no_quote and any(stripped_no_quote.startswith(h) for h in
                    ["Subject:", "Date:", "To:", "Cc:", "Bcc:", "Reply-To:", "Sent:"]):
                    continue
                # End of headers = empty line or first content line
                if not stripped_no_quote:
                    skip_headers = False
                    continue
                else:
                    skip_headers = False
                    # Fall through to capture this line

            # Lines starting with > are quoted text
            if stripped.startswith(">"):
                cleaned = re.sub(r'^>+\s?', '', stripped)
                if cleaned.strip():
                    current_block.append(cleaned.strip())
                elif current_block:
                    current_block.append("")  # Paragraph break
            elif not stripped:
                # Blank line
                if current_block:
                    current_block.append("")
            else:
                # Non-quoted, non-blank = end of Taylor's block
                # UNLESS this is a continuation (multi-line attribution consumed next line)
                if "wrote:" in stripped.lower() and any(a in stripped.lower() for a in TAYLOR_ADDRS):
                    continue  # This is the 2nd line of a multi-line attribution
                if current_block:
                    taylor_blocks.append(current_block)
                    current_block = []
                capturing = False

    # Capture remaining block
    if current_block:
        taylor_blocks.append(current_block)

    if not taylor_blocks:
        return ""

    # Join each block, take the longest (most substantive Taylor content)
    processed = []
    for block in taylor_blocks:
        text = "\n".join(block)
        # Clean up
        cleaned = _clean_taylor_text(text)
        if cleaned:
            processed.append(cleaned)

    if not processed:
        return ""

    # Return the longest block (most complete Taylor message)
    return max(processed, key=len)


def _clean_taylor_text(text: str) -> str:
    """Clean extracted Taylor text — remove signatures, footers, phone numbers."""
    lines = text.split("\n")
    cleaned = []
    for line in lines:
        line = line.strip()
        # Stop at signature block
        if line in ("--", "---", "___"):
            break
        # Skip email/website/phone in signature
        if any(a in line.lower() for a in TAYLOR_ADDRS):
            continue
        if line.startswith("www.") or line.startswith("http"):
            continue
        if re.match(r'^\d{3}[-.]?\d{3}[-.]?\d{4}$', line):
            continue
        if line.lower().startswith("sent from my"):
            continue
        # Skip common signature lines
        if any(sig in line.lower() for sig in [
            "blue ridge vacation specialist",
            "owner, cabin rentals",
            "blue ridge, ga",
            "1690 appalachian",
        ]) and len(line) < 100:
            continue
        if line.lower().startswith("best regards") and len(line) < 30:
            break
        if line.lower().startswith("taylor knight") and len(line) < 40:
            continue

        if line:
            cleaned.append(line)

    result = " ".join(cleaned).strip()
    result = re.sub(r'\s{2,}', ' ', result)
    return result


def clean_direct_body(body: str) -> str:
    """
    Clean a direct email body (emails where Taylor is the sender).
    Strips quoted replies, signatures, and formatting noise.
    """
    lines = body.split("\n")
    clean_lines = []

    for line in lines:
        stripped = line.strip()
        # Stop at quoted reply block
        if stripped.startswith(">"):
            break
        # Stop at attribution line
        if "On " in line and "wrote:" in line:
            break
        # Stop at forwarded message
        if stripped.startswith("---------- Forwarded message"):
            break
        if stripped in ("--", "---", "___"):
            break
        if stripped.lower().startswith("sent from my"):
            break

        # Skip signature/footer
        if any(a in stripped.lower() for a in TAYLOR_ADDRS):
            continue
        if stripped.startswith("www.") or stripped.startswith("http"):
            continue
        if re.match(r'^\d{3}[-.]?\d{3}[-.]?\d{4}$', stripped):
            continue
        if any(sig in stripped.lower() for sig in [
            "blue ridge vacation specialist",
            "owner, cabin rentals",
            "blue ridge, ga",
        ]) and len(stripped) < 100:
            continue
        if stripped.lower().startswith("taylor knight") and len(stripped) < 40:
            continue

        if stripped:
            clean_lines.append(stripped)

    result = " ".join(clean_lines).strip()
    result = re.sub(r'\s{2,}', ' ', result)
    return result


# =============================================================================
# INGESTION ENGINE
# =============================================================================

def ingest_taylor_voice():
    """
    The Taylor Protocol: Extract and ingest Taylor's writing voice
    from NAS email archives into ChromaDB with proper 768-dim embeddings.
    """
    print("=" * 65)
    print("  TAYLOR PROTOCOL — Persona Extraction Engine v3")
    print("  Strategy: Quoted reply mining + direct email filtering")
    print(f"  Embeddings: {EMBED_MODEL} ({EMBED_DIM}-dim via Ollama)")
    print("=" * 65)

    # Verify Ollama embedding is available
    print("\n  Verifying embedding model...")
    test_emb = get_embedding("test")
    if test_emb is None:
        print("  [FATAL] Cannot generate embeddings. Is Ollama running?")
        sys.exit(1)
    print(f"  Embedding OK: {len(test_emb)}-dim vector from {EMBED_MODEL}")

    # Connect to ChromaDB on NVMe
    print(f"  ChromaDB path : {CHROMA_PATH}")
    client = chromadb.PersistentClient(path=CHROMA_PATH)
    collection = client.get_or_create_collection(
        name=COLLECTION_NAME,
        metadata={"hnsw:space": "cosine"},
    )
    existing = collection.count()
    print(f"  Collection '{COLLECTION_NAME}' has {existing} existing documents")

    count = 0
    skipped = 0
    errors = 0
    embed_failures = 0

    def ingest_text(text: str, source_label: str, subject: str,
                    date: str, filename: str, extraction_method: str) -> bool:
        """Ingest a cleaned text block into ChromaDB with proper embeddings."""
        nonlocal count, embed_failures

        # Generate embedding via Ollama (matching the 768-dim collection)
        embedding = get_embedding(text)
        if embedding is None:
            embed_failures += 1
            return False

        doc_id = f"taylor_{uuid.uuid4().hex[:16]}"
        collection.add(
            documents=[text],
            embeddings=[embedding],
            metadatas=[{
                "source": "email",
                "author": "Taylor Knight",
                "type": "training_gold",
                "style": "warm_luxury",
                "extraction": extraction_method,
                "source_dir": source_label[:100],
                "subject": str(subject)[:200],
                "date": str(date)[:50],
                "file": str(filename)[:100],
            }],
            ids=[doc_id],
        )
        count += 1
        if count % 25 == 0:
            print(f"     ... {count} Taylor voice samples ingested so far")
        return True

    # ── PHASE 1: Mine Taylor's Maildir for quoted replies ──
    print(f"\n  PHASE 1: Mining Taylor's Maildir (quoted reply extraction)")
    if TAYLOR_INBOX.exists():
        print(f"  Path: {TAYLOR_INBOX}")
        phase1_count = 0
        phase1_checked = 0
        for fname in sorted(os.listdir(TAYLOR_INBOX)):
            filepath = os.path.join(TAYLOR_INBOX, fname)
            try:
                msg = parse_email_safe(filepath)
                if msg is None:
                    errors += 1
                    continue

                body = get_body(msg)
                if not body:
                    skipped += 1
                    continue

                phase1_checked += 1

                # Check if body mentions Taylor's address (likely has quoted reply)
                if not any(addr in body.lower() for addr in TAYLOR_ADDRS):
                    skipped += 1
                    continue

                # Extract Taylor's quoted text
                taylor_text = extract_taylor_quoted(body)
                if len(taylor_text) < MIN_BODY_LENGTH:
                    skipped += 1
                    continue

                subject = msg.get("Subject", "No Subject") or "No Subject"
                date = msg.get("Date", "Unknown") or "Unknown"

                if ingest_text(
                    taylor_text,
                    source_label="taylor_inbox_quoted",
                    subject=subject,
                    date=date,
                    filename=fname[:80],
                    extraction_method="quoted_reply",
                ):
                    phase1_count += 1

            except Exception as e:
                errors += 1

        print(f"  Phase 1 result: {phase1_count} Taylor voice samples "
              f"from {phase1_checked} checked emails")
    else:
        print(f"  [SKIP] Taylor Maildir not found: {TAYLOR_INBOX}")

    # ── PHASE 2: Scan Gary's Maildir for emails FROM Taylor ──
    print(f"\n  PHASE 2: Scanning Gary's Maildir (FROM Taylor filter)")
    if GARY_INBOX.exists():
        print(f"  Path: {GARY_INBOX}")
        print(f"  (159K+ emails — scanning all...)")
        phase2_count = 0
        gary_total = 0

        for fname in os.listdir(GARY_INBOX):
            gary_total += 1
            filepath = os.path.join(GARY_INBOX, fname)
            try:
                msg = parse_email_safe(filepath)
                if msg is None:
                    continue

                if not is_from_taylor(msg):
                    continue

                body = get_body(msg)
                clean_text = clean_direct_body(body)

                if len(clean_text) < MIN_BODY_LENGTH:
                    skipped += 1
                    continue

                subject = msg.get("Subject", "No Subject") or "No Subject"
                date = msg.get("Date", "Unknown") or "Unknown"

                if ingest_text(
                    clean_text,
                    source_label="gary_inbox_from_taylor",
                    subject=subject,
                    date=date,
                    filename=fname[:80],
                    extraction_method="direct_from",
                ):
                    phase2_count += 1

            except Exception:
                errors += 1

            if gary_total % 20000 == 0:
                print(f"     ... scanned {gary_total} of Gary's emails, "
                      f"found {phase2_count} from Taylor")

        print(f"  Phase 2 result: {phase2_count} emails FROM Taylor "
              f"(out of {gary_total} scanned)")
    else:
        print(f"  [SKIP] Gary's Maildir not found: {GARY_INBOX}")

    # ── PHASE 3: MailPlus local Maildir ──
    print(f"\n  PHASE 3: Scanning MailPlus local Maildir")
    if MAILPLUS_LOCAL.exists():
        phase3_count = 0
        for fname in os.listdir(MAILPLUS_LOCAL):
            filepath = os.path.join(MAILPLUS_LOCAL, fname)
            try:
                msg = parse_email_safe(filepath)
                if msg is None:
                    continue
                if not is_from_taylor(msg):
                    continue

                body = get_body(msg)
                clean_text = clean_direct_body(body)

                if len(clean_text) < MIN_BODY_LENGTH:
                    skipped += 1
                    continue

                subject = msg.get("Subject", "No Subject") or "No Subject"
                date = msg.get("Date", "Unknown") or "Unknown"

                if ingest_text(
                    clean_text,
                    source_label="mailplus_local_from_taylor",
                    subject=subject,
                    date=date,
                    filename=fname[:80],
                    extraction_method="direct_from",
                ):
                    phase3_count += 1

            except Exception:
                errors += 1

        print(f"  Phase 3 result: {phase3_count} emails from MailPlus local")
    else:
        print(f"  [SKIP] MailPlus local not found: {MAILPLUS_LOCAL}")

    # ── Summary ──
    print("\n" + "=" * 65)
    print("  TAYLOR PROTOCOL — COMPLETE")
    print("=" * 65)
    print(f"  Ingested         : {count} voice samples (training gold)")
    print(f"  Skipped          : {skipped} (too short / no Taylor content)")
    print(f"  Errors           : {errors} (unreadable files)")
    print(f"  Embed failures   : {embed_failures}")
    print(f"  Total in DB      : {collection.count()} docs in '{COLLECTION_NAME}'")
    print(f"\n  R1 has absorbed {count} examples of Taylor's voice.")
    print("=" * 65)


# =============================================================================
# ENTRY POINT
# =============================================================================

if __name__ == "__main__":
    ingest_taylor_voice()
