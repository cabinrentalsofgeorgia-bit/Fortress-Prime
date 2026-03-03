#!/usr/bin/env python3
"""
Module CF-03: Counselor CRM — Test Suite
==========================================
Validates the ingestion pipeline components (text extraction, chunking,
classification, embedding) without requiring a live Qdrant instance.

Usage:
    python3 Modules/CF-03_CounselorCRM/test_counselor.py
"""

import os
import sys
import json
import tempfile
from pathlib import Path
from datetime import datetime

# Add project root
_project_root = os.path.dirname(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
)
sys.path.insert(0, _project_root)

# Dynamic import (hyphen in directory name)
import importlib.util

_module_dir = os.path.dirname(os.path.abspath(__file__))


def _load(name, filename):
    spec = importlib.util.spec_from_file_location(
        name, os.path.join(_module_dir, filename)
    )
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


ingest = _load("ingest_docs", "ingest_docs.py")
query_eng = _load("query_engine", "query_engine.py")

# Test counters
passed = 0
failed = 0


def test(name, condition, detail=""):
    global passed, failed
    if condition:
        print(f"  [PASS] {name}")
        passed += 1
    else:
        print(f"  [FAIL] {name} — {detail}")
        failed += 1


# =============================================================================
# TEST 1: TEXT EXTRACTION
# =============================================================================
print("=" * 60)
print("  CF-03 COUNSELOR CRM — TEST SUITE")
print("=" * 60)

print("\n--- Test 1: Text Extraction ---")

# Create temp text file
with tempfile.NamedTemporaryFile(mode="w", suffix=".txt", delete=False) as f:
    f.write("This is a test legal document.\nSection 1: Definitions.\n" * 10)
    txt_path = f.name

text = ingest.extract_text(txt_path)
test("TXT extraction", len(text) > 100, f"Got {len(text)} chars")
os.unlink(txt_path)

# Create temp markdown file
with tempfile.NamedTemporaryFile(mode="w", suffix=".md", delete=False) as f:
    f.write("# Lease Agreement\n\n## Section 1\n\nTenant agrees to terms.\n" * 20)
    md_path = f.name

text_md = ingest.extract_text(md_path)
test("Markdown extraction", len(text_md) > 100, f"Got {len(text_md)} chars")
os.unlink(md_path)

# Test extraction of non-existent file
text_none = ingest.extract_text("/nonexistent/file.txt")
test("Non-existent file returns empty", text_none == "")

# =============================================================================
# TEST 2: TEXT CHUNKING
# =============================================================================
print("\n--- Test 2: Text Chunking ---")

sample_legal_text = """
LEASE AGREEMENT

This Lease Agreement ("Agreement") is entered into as of January 15, 2025,
by and between Cabin Rentals of Georgia, LLC ("Landlord") and John Doe ("Tenant").

SECTION 1: PREMISES
Landlord hereby leases to Tenant the property known as "Rolling River Cabin",
located at 123 Blue Ridge Parkway, Blue Ridge, Georgia 30513 (the "Premises").

SECTION 2: TERM
The initial term of this Lease shall be for a period of twelve (12) months,
commencing on February 1, 2025, and ending on January 31, 2026. Unless either
party provides written notice of termination at least sixty (60) days prior to
the expiration of the initial term or any renewal term, this Lease shall
automatically renew for successive twelve (12) month periods.

SECTION 3: RENT
Tenant shall pay to Landlord monthly rent in the amount of Two Thousand Five
Hundred Dollars ($2,500.00) per month, due on the first day of each calendar
month. Payment shall be made via electronic transfer to the account designated
by Landlord. Late payments shall incur a fee of Fifty Dollars ($50.00) per day.

SECTION 4: SECURITY DEPOSIT
Upon execution of this Agreement, Tenant shall pay a security deposit of Five
Thousand Dollars ($5,000.00). Said deposit shall be held in a separate escrow
account in accordance with O.C.G.A. 44-7-31 and shall be returned within thirty
(30) days of the termination of this Lease, less any deductions for damages
beyond normal wear and tear, as documented by photographic evidence.

SECTION 5: MAINTENANCE
Tenant shall maintain the Premises in good condition and promptly notify Landlord
of any needed repairs. Landlord shall be responsible for structural repairs and
major appliance replacement. Tenant shall be responsible for routine maintenance
including lawn care, HVAC filter replacement, and keeping all drains clear.
""".strip()

chunks = ingest.chunk_text(sample_legal_text)
test("Chunking produces multiple chunks", len(chunks) >= 2, f"Got {len(chunks)} chunks")
test("Chunks are non-empty", all(len(c) > 50 for c in chunks))
test(
    "Chunks have overlap (shared content)",
    len(chunks) > 1 and any(
        chunks[i][-100:] in chunks[i + 1][:400]
        for i in range(len(chunks) - 1)
        if len(chunks[i]) > 100
    ) if len(chunks) > 1 else True,
)

# Edge cases
empty_chunks = ingest.chunk_text("")
test("Empty text returns no chunks", len(empty_chunks) == 0)

short_chunks = ingest.chunk_text("Too short.")
test("Short text returns no chunks", len(short_chunks) == 0)

# =============================================================================
# TEST 3: DOCUMENT CLASSIFICATION
# =============================================================================
print("\n--- Test 3: Document Classification ---")

test_paths = [
    ("/mnt/nas/Corporate_Legal/Leases/rolling_river_lease.pdf", "lease_agreement"),
    ("/mnt/nas/Property_Deeds/mountain_view_deed.pdf", "property_deed"),
    ("/mnt/nas/Easements/morgan_ridge_easement.pdf", "easement"),
    ("/mnt/nas/Contracts/vendor_agreement.pdf", "contract"),
    ("/mnt/nas/Insurance/liability_policy_2025.pdf", "insurance"),
    ("/mnt/nas/Tax/property_tax_assessment.pdf", "tax_document"),
    ("/mnt/nas/Permits/building_permit_001.pdf", "permit_license"),
    ("/mnt/nas/Court/complaint_2024.pdf", "court_filing"),
    ("/home/admin/Fortress-Prime/division_legal/knowledge_base/Title_44.txt", "georgia_statute"),
    ("/mnt/nas/Regulations/county_ordinance.pdf", "local_regulation"),
    ("/mnt/nas/Letters/demand_notice.pdf", "correspondence"),
    ("/mnt/nas/Misc/random_document.pdf", "general_legal"),
]

for path_str, expected_cat in test_paths:
    actual = ingest.classify_document(Path(path_str))
    test(f"Classify '{Path(path_str).name}'", actual == expected_cat, f"Got '{actual}', expected '{expected_cat}'")

# =============================================================================
# TEST 4: FILE HASHING
# =============================================================================
print("\n--- Test 4: File Hashing ---")

with tempfile.NamedTemporaryFile(mode="w", suffix=".txt", delete=False) as f:
    f.write("Test document for hashing.\n")
    hash_path = Path(f.name)

h1 = ingest.file_hash(hash_path)
h2 = ingest.file_hash(hash_path)
test("Deterministic hashing", h1 == h2)
test("Hash is 16 chars hex", len(h1) == 16 and all(c in "0123456789abcdef" for c in h1))

os.unlink(hash_path)

# =============================================================================
# TEST 5: EMBEDDING MODEL CHECK
# =============================================================================
print("\n--- Test 5: Embedding Model (nomic-embed-text) ---")

try:
    emb = ingest.get_embedding("What are the lease terms for Rolling River?")
    if emb is not None:
        test("Embedding model reachable", True)
        test("Embedding dimension = 768", len(emb) == 768, f"Got {len(emb)}")
        test("Embedding is non-zero", any(v != 0.0 for v in emb))

        # Test second embedding for similarity check
        emb2 = ingest.get_embedding("Rolling River cabin lease agreement terms")
        if emb2:
            # Cosine similarity should be > 0.5 for similar queries
            import math
            dot = sum(a * b for a, b in zip(emb, emb2))
            mag1 = math.sqrt(sum(a * a for a in emb))
            mag2 = math.sqrt(sum(b * b for b in emb2))
            cosine_sim = dot / (mag1 * mag2) if mag1 > 0 and mag2 > 0 else 0
            test(
                f"Similar queries have high cosine sim",
                cosine_sim > 0.5,
                f"cosine_sim = {cosine_sim:.4f}",
            )
    else:
        test("Embedding model reachable", False, "Model returned None (Ollama may be offline)")
except Exception as e:
    test("Embedding model reachable", False, str(e))

# =============================================================================
# TEST 6: QUERY ENGINE — CONTEXT BUILDER
# =============================================================================
print("\n--- Test 6: Context Builder ---")

mock_chunks = [
    {
        "text": "Tenant shall pay rent of $2,500 per month.",
        "file_name": "lease_agreement.pdf",
        "category": "lease_agreement",
        "parent_dir": "Leases",
        "score": 0.92,
        "chunk_index": 0,
        "total_chunks": 5,
    },
    {
        "text": "O.C.G.A. 44-7-31 requires security deposit escrow.",
        "file_name": "Title_44.txt",
        "category": "georgia_statute",
        "parent_dir": "knowledge_base",
        "score": 0.78,
        "chunk_index": 3,
        "total_chunks": 100,
    },
]

context = query_eng.build_context(mock_chunks)
test("Context builder produces non-empty output", len(context) > 0)
test("Context includes file names", "lease_agreement.pdf" in context)
test("Context includes categories", "lease_agreement" in context)
test("Context includes scores", "0.92" in context)

# =============================================================================
# TEST 7: THINK TAG STRIPPING
# =============================================================================
print("\n--- Test 7: DeepSeek <think> Tag Stripping ---")

raw_response = """<think>
Let me analyze the lease agreement...
The key clause is in Section 3 about rent payments.
I should cite the specific amounts.
</think>

Based on the lease agreement, the monthly rent is $2,500.00 per month,
due on the first day of each calendar month. [Source: lease_agreement.pdf]

Late payments incur a $50.00/day penalty."""

cleaned = query_eng.strip_think_tags(raw_response)
test("Think tags stripped", "<think>" not in cleaned)
test("Answer content preserved", "$2,500.00" in cleaned)
test("Source citation preserved", "[Source: lease_agreement.pdf]" in cleaned)
test("Cleaned text starts with content", cleaned.startswith("Based on"))

# Multi-think test
multi_think = "<think>First</think>Answer A<think>Second</think> plus B"
cleaned_multi = query_eng.strip_think_tags(multi_think)
test("Multiple think blocks stripped", "<think>" not in cleaned_multi)
test("Both answer parts preserved", "Answer A" in cleaned_multi and "plus B" in cleaned_multi)

# =============================================================================
# TEST 8: QDRANT CONNECTION CHECK
# =============================================================================
print("\n--- Test 8: Qdrant Connection ---")

try:
    import requests as req
    resp = req.get(f"{ingest.QDRANT_URL}/collections", timeout=5)
    if resp.status_code == 200:
        collections = resp.json().get("result", {}).get("collections", [])
        test("Qdrant reachable", True)
        test(f"Qdrant has {len(collections)} collections", True)
    else:
        test("Qdrant reachable", False, f"HTTP {resp.status_code}")
except Exception as e:
    test("Qdrant reachable", False, f"Not running at {ingest.QDRANT_URL} ({e})")
    print(f"         To start Qdrant: docker-compose -f Modules/CF-03_CounselorCRM/docker-compose.yml up -d")

# =============================================================================
# TEST 9: CONFIGURATION VALIDATION
# =============================================================================
print("\n--- Test 9: Configuration ---")

test("QDRANT_HOST is localhost", ingest.QDRANT_HOST == "localhost")
test("QDRANT_PORT is 6333", ingest.QDRANT_PORT == 6333)
test("EMBED_DIM is 768", ingest.EMBED_DIM == 768)
test("EMBED_MODEL is nomic-embed-text", ingest.EMBED_MODEL == "nomic-embed-text")
test("COLLECTION_NAME is legal_library", ingest.COLLECTION_NAME == "legal_library")
test("CHUNK_SIZE > 1000 (legal-optimized)", ingest.CHUNK_SIZE >= 1000)
test("CHUNK_OVERLAP > 200 (legal-optimized)", ingest.CHUNK_OVERLAP >= 200)

# Query engine config
test("Query DEFAULT_TOP_K >= 5", query_eng.DEFAULT_TOP_K >= 5)
test("Query MAX_CONTEXT_CHARS >= 8000", query_eng.MAX_CONTEXT_CHARS >= 8000)

# =============================================================================
# SUMMARY
# =============================================================================
print("\n" + "=" * 60)
total = passed + failed
print(f"  CF-03 COUNSELOR CRM TEST RESULTS: {passed}/{total} passed")
if failed == 0:
    print("  STATUS: ALL TESTS PASSED")
else:
    print(f"  STATUS: {failed} FAILURE(S)")
    print("  NOTE: Qdrant/embedding failures are expected if services are offline.")
print("=" * 60)
