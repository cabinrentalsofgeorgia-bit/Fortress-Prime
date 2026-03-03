#!/usr/bin/env python3
"""
═══════════════════════════════════════════════════════════════════════════════
FORTRESS PRIME — MCP SERVER TEST SUITE
═══════════════════════════════════════════════════════════════════════════════
Tests the Sovereign Context Protocol MCP server tools and resources.

USAGE:
    # Test all tools
    python src/test_mcp_server.py

    # Test specific tool
    python src/test_mcp_server.py search-legal "easement rights"
    python src/test_mcp_server.py search-jordi "Bitcoin outlook"
    python src/test_mcp_server.py search-oracle "Toccoa Heights"
    python src/test_mcp_server.py list-collections
    python src/test_mcp_server.py fortress-stats

Author: Fortress Prime Architect
Version: 1.0.0
═══════════════════════════════════════════════════════════════════════════════
"""

import sys
import json

# Import the tools directly from the MCP server module
sys.path.insert(0, '/home/admin/Fortress-Prime')
from src import sovereign_mcp_server as mcp


def test_search_legal():
    """Test legal document search."""
    print("\n" + "=" * 70)
    print("  TEST: search_fortress_legal()")
    print("=" * 70)

    query = "easement rights Morgan Ridge"
    print(f"\n  Query: {query}\n")

    result = mcp.search_fortress_legal(query=query, top_k=3)
    data = json.loads(result)

    print(json.dumps(data, indent=2))
    print(f"\n  Results: {data.get('count', 0)}")


def test_search_jordi():
    """Test Jordi Visser knowledge search."""
    print("\n" + "=" * 70)
    print("  TEST: search_jordi_knowledge()")
    print("=" * 70)

    query = "Bitcoin outlook"
    print(f"\n  Query: {query}\n")

    result = mcp.search_jordi_knowledge(query=query, top_k=5)
    data = json.loads(result)

    print(json.dumps(data, indent=2))


def test_search_oracle():
    """Test Oracle (ChromaDB) search."""
    print("\n" + "=" * 70)
    print("  TEST: search_oracle()")
    print("=" * 70)

    query = "Toccoa Heights Survey"
    print(f"\n  Query: {query}\n")

    result = mcp.search_oracle(query=query, max_results=5)
    data = json.loads(result)

    print(json.dumps(data, indent=2))
    print(f"\n  Results: {data.get('count', 0)}")


def test_search_email():
    """Test email intelligence search."""
    print("\n" + "=" * 70)
    print("  TEST: search_email_intel()")
    print("=" * 70)

    query = "vendor invoices"
    print(f"\n  Query: {query}\n")

    result = mcp.search_email_intel(query=query, division="REAL_ESTATE", top_k=3)
    data = json.loads(result)

    print(json.dumps(data, indent=2))
    print(f"\n  Results: {data.get('count', 0)}")


def test_list_collections():
    """Test collection listing."""
    print("\n" + "=" * 70)
    print("  TEST: list_collections()")
    print("=" * 70)

    result = mcp.list_collections()
    data = json.loads(result)

    print(json.dumps(data, indent=2))
    print(f"\n  Collections found: {data.get('count', 0)}")


def test_fortress_stats():
    """Test fortress stats."""
    print("\n" + "=" * 70)
    print("  TEST: get_fortress_stats()")
    print("=" * 70)

    result = mcp.get_fortress_stats()
    data = json.loads(result)

    print(json.dumps(data, indent=2))


def test_jordi_status():
    """Test Jordi status."""
    print("\n" + "=" * 70)
    print("  TEST: get_jordi_status()")
    print("=" * 70)

    result = mcp.get_jordi_status()
    data = json.loads(result)

    print(json.dumps(data, indent=2))


def test_resources():
    """Test MCP resources."""
    print("\n" + "=" * 70)
    print("  TEST: MCP Resources (Godhead Prompts)")
    print("=" * 70)

    resources = {
        "jordi": mcp.get_jordi_prompt(),
        "legal": mcp.get_legal_prompt(),
        "crog": mcp.get_crog_prompt(),
        "comp": mcp.get_comp_prompt(),
    }

    for name, prompt in resources.items():
        print(f"\n  {name.upper()} GODHEAD:")
        print(f"    Length: {len(prompt)} chars")
        print(f"    Preview: {prompt[:150]}...")


def main():
    if len(sys.argv) < 2:
        # Run all tests
        print("\n" + "=" * 70)
        print("  FORTRESS PRIME — MCP SERVER TEST SUITE")
        print("=" * 70)

        tests = [
            ("Fortress Stats", test_fortress_stats),
            ("List Collections", test_list_collections),
            ("Jordi Status", test_jordi_status),
            ("Resources", test_resources),
            ("Search Legal", test_search_legal),
            ("Search Oracle", test_search_oracle),
            ("Search Email", test_search_email),
            ("Search Jordi", test_search_jordi),
        ]

        for name, func in tests:
            try:
                func()
            except Exception as e:
                print(f"\n  [ERROR] {name} failed: {e}")

        print("\n" + "=" * 70)
        print("  ALL TESTS COMPLETE")
        print("=" * 70)
        print()

    else:
        # Run specific test
        cmd = sys.argv[1].lower()

        if cmd == "search-legal":
            query = " ".join(sys.argv[2:]) if len(sys.argv) > 2 else "easement rights"
            result = mcp.search_fortress_legal(query=query)
            print(json.dumps(json.loads(result), indent=2))

        elif cmd == "search-jordi":
            query = " ".join(sys.argv[2:]) if len(sys.argv) > 2 else "Bitcoin"
            result = mcp.search_jordi_knowledge(query=query)
            print(json.dumps(json.loads(result), indent=2))

        elif cmd == "search-oracle":
            query = " ".join(sys.argv[2:]) if len(sys.argv) > 2 else "survey"
            result = mcp.search_oracle(query=query)
            print(json.dumps(json.loads(result), indent=2))

        elif cmd == "search-email":
            query = " ".join(sys.argv[2:]) if len(sys.argv) > 2 else "invoice"
            result = mcp.search_email_intel(query=query)
            print(json.dumps(json.loads(result), indent=2))

        elif cmd == "list-collections":
            result = mcp.list_collections()
            print(json.dumps(json.loads(result), indent=2))

        elif cmd == "fortress-stats":
            result = mcp.get_fortress_stats()
            print(json.dumps(json.loads(result), indent=2))

        elif cmd == "jordi-status":
            result = mcp.get_jordi_status()
            print(json.dumps(json.loads(result), indent=2))

        elif cmd == "resources":
            test_resources()

        else:
            print(f"Unknown command: {cmd}")
            print("\nAvailable commands:")
            print("  search-legal <query>")
            print("  search-jordi <query>")
            print("  search-oracle <query>")
            print("  search-email <query>")
            print("  list-collections")
            print("  fortress-stats")
            print("  jordi-status")
            print("  resources")


if __name__ == "__main__":
    main()
