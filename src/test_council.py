#!/usr/bin/env python3
"""
═══════════════════════════════════════════════════════════════════════════════
TEST COUNCIL OF GIANTS — Multi-Persona Consensus
═══════════════════════════════════════════════════════════════════════════════
Test the Council's ability to generate consensus signals from diverse personas.

Usage:
    python src/test_council.py

Tests:
    1. Single persona opinion
    2. Two-persona debate
    3. Full council vote (9 personas)
    4. Consensus score calculation

Author: Fortress Prime Architect
Version: 2.0.0 — Hardened with path resolution, dotenv, and preflight checks
═══════════════════════════════════════════════════════════════════════════════
"""

import os
import sys

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, PROJECT_ROOT)
sys.path.insert(0, os.path.join(PROJECT_ROOT, "src"))

from dotenv import load_dotenv
load_dotenv(os.path.join(PROJECT_ROOT, ".env"))

from persona_template import Persona, Council
import json


def preflight_check() -> bool:
    """
    Validate required environment variables before touching any APIs.
    Returns True if all required keys are present, False otherwise.
    """
    print("\n" + "=" * 70)
    print("PRE-FLIGHT CHECK")
    print("=" * 70 + "\n")

    required = {
        "ALLOW_CLOUD_LLM": os.getenv("ALLOW_CLOUD_LLM", ""),
        "XAI_API_KEY": os.getenv("XAI_API_KEY", ""),
    }
    optional = {
        "OPENAI_API_KEY": os.getenv("OPENAI_API_KEY", ""),
        "GOOGLE_AI_API_KEY": os.getenv("GOOGLE_AI_API_KEY", ""),
        "ANTHROPIC_API_KEY": os.getenv("ANTHROPIC_API_KEY", ""),
    }

    all_pass = True

    cloud_val = required["ALLOW_CLOUD_LLM"]
    if cloud_val.lower() == "true":
        print(f"  [PASS] ALLOW_CLOUD_LLM = \"{cloud_val}\"")
    else:
        print(f"  [FAIL] ALLOW_CLOUD_LLM = \"{cloud_val}\" (expected \"true\")")
        all_pass = False

    xai_val = required["XAI_API_KEY"]
    if xai_val:
        masked = xai_val[:6] + "..." + xai_val[-4:]
        print(f"  [PASS] XAI_API_KEY = {masked} (set)")
    else:
        print(f"  [FAIL] XAI_API_KEY = \"\" (required for financial personas)")
        all_pass = False

    for key, val in optional.items():
        if val:
            masked = val[:6] + "..." + val[-4:]
            print(f"  [PASS] {key} = {masked} (set)")
        else:
            print(f"  [SKIP] {key} (optional, not set)")

    env_path = os.path.join(PROJECT_ROOT, ".env")
    print(f"\n  .env loaded from: {env_path}")
    print(f"  Project root: {PROJECT_ROOT}")

    if not all_pass:
        print(f"\n  PRE-FLIGHT FAILED. Set missing keys in {env_path}")
        print("  Aborting.\n")

    print()
    return all_pass


def test_single_persona():
    """Test single persona analysis."""
    print("\n" + "="*70)
    print("TEST 1: Single Persona Opinion")
    print("="*70 + "\n")
    
    try:
        jordi = Persona.load("jordi")
        print(f"Loading persona: {jordi.name}")
        print(f"Vector collection: {jordi.vector_collection}")
        print(f"Vectors: {jordi.vectors_count}")
        print()
        
        event = "Fed announces 50bps rate cut"
        print(f"Event: {event}")
        print(f"Analyzing through {jordi.name}'s lens...")
        print()
        
        opinion = jordi.analyze_event(event)
        
        print("Opinion:")
        print(f"  Signal: {opinion.signal.value}")
        print(f"  Conviction: {opinion.conviction:.2f}")
        print(f"  Reasoning: {opinion.reasoning}")
        print(f"  Assets: {', '.join(opinion.assets)}")
        
        if opinion.risk_factors:
            print(f"  Risk Factors: {', '.join(opinion.risk_factors)}")
        if opinion.catalysts:
            print(f"  Catalysts: {', '.join(opinion.catalysts)}")
        
        return True
    
    except FileNotFoundError:
        print("❌ Jordi persona not found. Run: python src/create_personas.py")
        return False
    except Exception as e:
        print(f"❌ Error: {e}")
        return False


def test_debate():
    """Test two-persona debate."""
    print("\n" + "="*70)
    print("TEST 2: Two-Persona Debate")
    print("="*70 + "\n")
    
    try:
        jordi = Persona.load("jordi")
        permabear = Persona.load("permabear")
        
        topic = "Bitcoin will hit $150,000 in 2026"
        print(f"Topic: {topic}")
        print(f"Debaters: {jordi.name} vs {permabear.name}")
        print()
        
        debate = jordi.debate_with(permabear, topic)
        
        print(f"{jordi.name}'s View:")
        print(f"  Signal: {debate.opinion_a.signal.value}")
        print(f"  Conviction: {debate.opinion_a.conviction:.2f}")
        print(f"  Reasoning: {debate.opinion_a.reasoning}")
        print()
        
        print(f"{permabear.name}'s View:")
        print(f"  Signal: {debate.opinion_b.signal.value}")
        print(f"  Conviction: {debate.opinion_b.conviction:.2f}")
        print(f"  Reasoning: {debate.opinion_b.reasoning}")
        print()
        
        agreement = debate.agreement_score()
        print(f"Agreement Score: {agreement:.2%}")
        
        if agreement > 0.7:
            print("  → Strong consensus")
        elif agreement > 0.4:
            print("  → Moderate disagreement")
        else:
            print("  → Sharp conflict")
        
        return True
    
    except FileNotFoundError as e:
        print(f"❌ Persona not found: {e}")
        print("   Run: python src/create_personas.py")
        return False
    except Exception as e:
        print(f"❌ Error: {e}")
        return False


def test_council_vote():
    """Test full council consensus."""
    print("\n" + "="*70)
    print("TEST 3: Council of Giants Vote")
    print("="*70 + "\n")
    
    # Try to load all personas
    persona_slugs = Persona.list_all()
    
    if not persona_slugs:
        print("❌ No personas found. Run: python src/create_personas.py")
        return False
    
    personas = []
    for slug in persona_slugs:
        try:
            persona = Persona.load(slug)
            personas.append(persona)
            print(f"  ✅ Loaded: {persona.name}")
        except Exception as e:
            print(f"  ⚠️  Skipped {slug}: {e}")
    
    if len(personas) < 2:
        print(f"\n❌ Need at least 2 personas. Found: {len(personas)}")
        return False
    
    print(f"\n✅ Council assembled: {len(personas)} personas")
    print()
    
    council = Council(personas)
    
    event = "Fed announces 50bps emergency rate cut amid banking crisis"
    print(f"Event: {event}")
    print()
    
    consensus = council.vote_on(event)
    
    print("\n" + "-"*70)
    print("CONSENSUS RESULTS")
    print("-"*70 + "\n")
    
    print(f"Consensus Signal: {consensus['consensus_signal']}")
    print(f"Consensus Conviction: {consensus['consensus_conviction']:.2%}")
    print(f"Agreement Rate: {consensus['agreement_rate']:.2%}")
    print()
    
    print(f"Vote Breakdown:")
    print(f"  Bullish: {consensus['bullish_count']}/{consensus['total_voters']}")
    print(f"  Bearish: {consensus['bearish_count']}/{consensus['total_voters']}")
    print(f"  Neutral: {consensus['neutral_count']}/{consensus['total_voters']}")
    print()
    
    if consensus['dissenters']:
        print(f"Dissenters ({len(consensus['dissenters'])}):")
        for dissent in consensus['dissenters']:
            print(f"  - {dissent['persona']}: {dissent['signal']} ({dissent['conviction']:.0%} conviction)")
            print(f"    Reason: {dissent['reasoning'][:100]}...")
    else:
        print("No dissenters - unanimous decision!")
    
    print()
    print("Full Results:")
    print(json.dumps(consensus, indent=2))
    
    return True


def test_consensus_score():
    """Test consensus scoring for specific asset."""
    print("\n" + "="*70)
    print("TEST 4: Asset-Specific Consensus Score")
    print("="*70 + "\n")
    
    # Mock opinions for demonstration
    from persona_template import Opinion, Signal
    
    opinions = [
        Opinion("The Jordi", "Fed cuts", Signal.BUY, 0.85, "Triple convergence", ["BTC", "QQQ"], "2026-02-15"),
        Opinion("The Raoul", "Fed cuts", Signal.STRONG_BUY, 0.90, "Liquidity tsunami", ["BTC", "ETH"], "2026-02-15"),
        Opinion("The Lyn", "Fed cuts", Signal.BUY, 0.75, "Fiscal dominance", ["BTC", "GOLD"], "2026-02-15"),
        Opinion("Permabear", "Fed cuts", Signal.SELL, 0.60, "Credit spreads widening", ["SPX"], "2026-02-15"),
    ]
    
    council = Council([])  # Empty council, just using the scoring method
    
    btc_score = council.get_consensus_score("BTC", opinions)
    gold_score = council.get_consensus_score("GOLD", opinions)
    spx_score = council.get_consensus_score("SPX", opinions)
    
    print("Asset Consensus Scores (0.0 = bearish, 1.0 = bullish):")
    print(f"  BTC:  {btc_score:.2%} 🟢" if btc_score > 0.7 else f"  BTC:  {btc_score:.2%}")
    print(f"  GOLD: {gold_score:.2%}")
    print(f"  SPX:  {spx_score:.2%} 🔴" if spx_score < 0.3 else f"  SPX:  {spx_score:.2%}")
    
    return True


def main():
    """Run all tests."""
    print("\n" + "="*70)
    print("  COUNCIL OF GIANTS — TEST SUITE")
    print("="*70)
    
    if not preflight_check():
        sys.exit(1)
    
    results = []
    
    # Test 1: Single persona
    results.append(("Single Persona", test_single_persona()))
    
    # Test 2: Debate
    results.append(("Two-Persona Debate", test_debate()))
    
    # Test 3: Council vote
    results.append(("Council Vote", test_council_vote()))
    
    # Test 4: Consensus score
    results.append(("Consensus Score", test_consensus_score()))
    
    # Summary
    print("\n" + "="*70)
    print("TEST SUMMARY")
    print("="*70 + "\n")
    
    for name, passed in results:
        status = "✅ PASS" if passed else "❌ FAIL"
        print(f"  {status}  {name}")
    
    total_passed = sum(1 for _, passed in results if passed)
    print(f"\n  {total_passed}/{len(results)} tests passed")
    
    if total_passed == len(results):
        print("\n🎉 All tests passed! Council is operational.")
    else:
        print("\n⚠️  Some tests failed. Check errors above.")
    
    print("\n" + "="*70)


if __name__ == "__main__":
    main()
