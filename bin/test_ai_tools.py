#!/usr/bin/env python3
"""
FORTRESS AI TOOLBELT DIAGNOSTIC
================================
Imports and exercises every agentic tool executor against the live database.
Validates that each tool:
  1. Returns valid JSON (not a Python exception).
  2. Returns the correct Pydantic schema (no stale column references).
  3. Handles missing/bad input gracefully (error boundary).

Run:  python3 bin/test_ai_tools.py
Exit: 0 = all tools pass, 1 = failures detected.
"""

import asyncio
import json
import os
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
FGP = ROOT / "fortress-guest-platform"
sys.path.insert(0, str(FGP))

env_file = FGP / ".env"
if env_file.exists():
    for line in env_file.read_text().splitlines():
        line = line.strip()
        if line and not line.startswith("#") and "=" in line:
            k, _, v = line.partition("=")
            os.environ.setdefault(k.strip(), v.strip())

PASS = "\033[92m✓ PASS\033[0m"
FAIL = "\033[91m✗ FAIL\033[0m"

failures = 0


def check(label: str, condition: bool, detail: str = ""):
    global failures
    if condition:
        print(f"  {PASS}  {label}")
    else:
        failures += 1
        print(f"  {FAIL}  {label}  — {detail}")


async def main():
    global failures
    t0 = time.perf_counter()

    from backend.api.intelligence import (
        _exec_search_legal_cases,
        _exec_get_case_detail,
        _exec_get_case_deadlines,
        _exec_search_knowledge_base,
        CaseSearchResponse,
        CaseDetailResponse,
        DeadlinesResponse,
        KnowledgeSearchResponse,
        ToolError,
    )

    print("\n" + "=" * 60)
    print("  FORTRESS AI TOOLBELT DIAGNOSTIC")
    print("=" * 60)

    # ── Test 1: search_legal_cases ──────────────────────────────
    print("\n── search_legal_cases('Generali') ──")
    result = await _exec_search_legal_cases("Generali")
    check("Returns dict", isinstance(result, dict))
    check("No tool_error key", "tool_error" not in result, result.get("tool_error", ""))
    check("Has 'cases' key", "cases" in result)
    check("Has 'total' key", "total" in result)
    if "cases" in result and len(result["cases"]) > 0:
        case = result["cases"][0]
        check("case_slug present", "case_slug" in case)
        check("case_name present", "case_name" in case)
        check("risk_score present", "risk_score" in case)
        check("critical_date present", "critical_date" in case)
        # Validate through Pydantic
        try:
            CaseSearchResponse(**result)
            check("Pydantic CaseSearchResponse validates", True)
        except Exception as e:
            check("Pydantic CaseSearchResponse validates", False, str(e))
    else:
        check("At least 1 case returned", False, f"got {result.get('total', 0)}")

    # ── Test 2: search with empty query ─────────────────────────
    print("\n── search_legal_cases('') ──")
    result2 = await _exec_search_legal_cases("")
    check("Returns dict", isinstance(result2, dict))
    check("No crash on empty query", "tool_error" not in result2, result2.get("tool_error", ""))

    # ── Test 3: get_case_detail ─────────────────────────────────
    print("\n── get_case_detail('fish-trap-suv2026000013') ──")
    result3 = await _exec_get_case_detail("fish-trap-suv2026000013")
    check("Returns dict", isinstance(result3, dict))
    check("No tool_error key", "tool_error" not in result3, result3.get("tool_error", ""))
    check("Has 'case' key", "case" in result3)
    if "case" in result3:
        c = result3["case"]
        check("case.case_slug present", "case_slug" in c)
        check("case.judge present", "judge" in c)
        check("case.plan_admin present", "plan_admin" in c)
        check("case.our_claim_basis present", "our_claim_basis" in c)
        check("NO stale 'source' column", "source" not in c)
    check("Has 'deadlines' list", isinstance(result3.get("deadlines"), list))
    check("Has 'recent_actions' list", isinstance(result3.get("recent_actions"), list))
    check("Has 'evidence' list", isinstance(result3.get("evidence"), list))
    if "evidence" in result3 and len(result3["evidence"]) > 0:
        ev = result3["evidence"][0]
        check("evidence uses 'relevance' (not 'source')", "relevance" in ev)
        check("evidence has 'is_critical'", "is_critical" in ev)
    try:
        CaseDetailResponse(**result3)
        check("Pydantic CaseDetailResponse validates", True)
    except Exception as e:
        check("Pydantic CaseDetailResponse validates", False, str(e))

    # ── Test 4: get_case_detail with bad slug ───────────────────
    print("\n── get_case_detail('nonexistent-slug-999') ──")
    result4 = await _exec_get_case_detail("nonexistent-slug-999")
    check("Returns dict", isinstance(result4, dict))
    check("Returns error for missing case", "error" in result4)

    # ── Test 5: get_case_deadlines ──────────────────────────────
    print("\n── get_case_deadlines('fish-trap-suv2026000013') ──")
    result5 = await _exec_get_case_deadlines("fish-trap-suv2026000013")
    check("Returns dict", isinstance(result5, dict))
    check("No tool_error key", "tool_error" not in result5, result5.get("tool_error", ""))
    check("Has 'deadlines' list", isinstance(result5.get("deadlines"), list))
    check("Has 'case_slug'", result5.get("case_slug") == "fish-trap-suv2026000013")
    check("Has 'total'", isinstance(result5.get("total"), int))
    if result5.get("deadlines"):
        d = result5["deadlines"][0]
        check("deadline.review_status present", "review_status" in d)
        check("deadline.content_hash present", "content_hash" in d)
        check("deadline.source_document present", "source_document" in d)
        check("deadline.deadline_type present", "deadline_type" in d)
    try:
        DeadlinesResponse(**result5)
        check("Pydantic DeadlinesResponse validates", True)
    except Exception as e:
        check("Pydantic DeadlinesResponse validates", False, str(e))

    # ── Test 6: search_knowledge_base (FEDERATED) ────────────────
    print("\n── search_knowledge_base('Generali travel insurance lawsuit cabin rentals') ──")
    result6 = await _exec_search_knowledge_base(
        "Generali travel insurance lawsuit cabin rentals Georgia commissions"
    )
    check("Returns dict", isinstance(result6, dict))
    check("No tool_error key", "tool_error" not in result6, result6.get("tool_error", ""))
    check("Has 'results' list", isinstance(result6.get("results"), list))
    check("Has 'total'", isinstance(result6.get("total"), int))
    check("Has 'collections_searched'", isinstance(result6.get("collections_searched"), list))
    searched = result6.get("collections_searched", [])
    check("Searched fortress_knowledge", "fortress_knowledge" in searched)
    check("Searched email_embeddings", "email_embeddings" in searched)
    check("Searched legal_library", "legal_library" in searched)
    if result6.get("results"):
        top = result6["results"][0]
        check("result has 'content' field", "content" in top)
        check("result has 'source' field", "source" in top)
        check("result has 'collection' field", "collection" in top)
        check("result has 'score' field", "score" in top)
        check(
            "content is NOT empty",
            len(top.get("content", "").strip()) > 0,
            f"got: '{top.get('content', '')[:80]}'",
        )
        check(
            "source is NOT 'unknown'",
            top.get("source", "unknown") != "unknown",
            f"got: '{top.get('source', '')}'",
        )
        check(
            "collection is a known Qdrant collection",
            top.get("collection") in (
                "fortress_knowledge", "email_embeddings", "legal_library",
            ),
            f"got: '{top.get('collection')}'",
        )
        collections_in_results = set(
            r.get("collection") for r in result6.get("results", [])
        )
        check(
            "Results span multiple collections",
            len(collections_in_results) >= 2,
            f"only got: {collections_in_results}",
        )
        print(f"\n  \033[90m  Top result preview:\033[0m")
        print(f"  \033[90m    collection: {top.get('collection')}\033[0m")
        print(f"  \033[90m    score:      {top.get('score')}\033[0m")
        print(f"  \033[90m    source:     {top.get('source', '')[:100]}\033[0m")
        print(f"  \033[90m    content:    {top.get('content', '')[:120]}...\033[0m")
    else:
        check("At least 1 result returned", False, "empty results")
    try:
        KnowledgeSearchResponse(**result6)
        check("Pydantic KnowledgeSearchResponse validates", True)
    except Exception as e:
        check("Pydantic KnowledgeSearchResponse validates", False, str(e))

    # ── Test 7: JSON round-trip safety ──────────────────────────
    print("\n── JSON serialization round-trip ──")
    for name, data in [
        ("search", result),
        ("detail", result3),
        ("deadlines", result5),
        ("knowledge", result6),
    ]:
        try:
            serialized = json.dumps(data)
            parsed = json.loads(serialized)
            check(f"{name}: json.dumps/loads round-trip", isinstance(parsed, dict))
        except (TypeError, ValueError) as e:
            check(f"{name}: json.dumps/loads round-trip", False, str(e))

    # ── Summary ─────────────────────────────────────────────────
    elapsed = round((time.perf_counter() - t0) * 1000)
    print("\n" + "=" * 60)
    if failures == 0:
        print(f"  \033[92mALL CHECKS PASSED\033[0m  ({elapsed}ms)")
    else:
        print(f"  \033[91m{failures} CHECK(S) FAILED\033[0m  ({elapsed}ms)")
    print("=" * 60 + "\n")
    return failures


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
