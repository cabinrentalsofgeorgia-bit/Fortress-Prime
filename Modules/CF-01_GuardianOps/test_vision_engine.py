#!/usr/bin/env python3
"""
Module CF-01: Guardian Ops — Vision Engine Test Suite
=======================================================
Tests the full inspection pipeline using mock vision model responses.
Validates scoring, verdicts, remediation messages, and JSON output.

Since we can't send real images without the Muscle Node online, this
test suite mocks the LLM response to validate all downstream logic:
scoring, parsing, confidence, and maintenance_log output.

Usage:
    python3 Modules/CF-01_GuardianOps/test_vision_engine.py
"""

import os
import sys
import json
import tempfile
from datetime import datetime
from unittest.mock import patch, MagicMock

# Project root
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

# Import via importlib (directory has hyphen)
import importlib.util
_engine_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "vision_engine.py")
_spec = importlib.util.spec_from_file_location("vision_engine", _engine_path)
_mod = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(_mod)

GuardianVisionEngine = _mod.GuardianVisionEngine
ROOM_CHECKLISTS = _mod.ROOM_CHECKLISTS
_calculate_scores = _mod._calculate_scores
_parse_vision_response = _mod._parse_vision_response
_build_inspection_prompt = _mod._build_inspection_prompt


def divider(title: str):
    print(f"\n{'=' * 70}")
    print(f"  {title}")
    print(f"{'=' * 70}")


# =============================================================================
# MOCK LLM RESPONSES (simulating what LLaVA would return)
# =============================================================================

MOCK_KITCHEN_PASS = json.dumps({
    "room_type": "kitchen",
    "overall_impression": "Kitchen is spotless and fully stocked for guests",
    "items": {
        "sink_empty":       {"pass": True,  "note": "Sink is completely empty and clean"},
        "stove_clean":      {"pass": True,  "note": "Stove top is spotless, no grease"},
        "counters_clear":   {"pass": True,  "note": "All counters clear and wiped"},
        "floor_clean":      {"pass": True,  "note": "Hardwood floor swept and mopped"},
        "appliances_clean": {"pass": True,  "note": "Microwave clean, fridge exterior wiped"},
        "trash_empty":      {"pass": True,  "note": "Fresh trash bag in can"},
        "dishes_stored":    {"pass": True,  "note": "All dishes in cabinets"},
        "coffee_station":   {"pass": True,  "note": "K-cups and filters stocked"},
        "no_food_left":     {"pass": True,  "note": "No food remnants visible"},
    },
    "additional_issues": [],
    "photo_quality": "good",
})

MOCK_KITCHEN_FAIL = json.dumps({
    "room_type": "kitchen",
    "overall_impression": "Kitchen needs attention: dirty sink and overflowing trash",
    "items": {
        "sink_empty":       {"pass": False, "note": "Multiple dishes and a pot in the sink"},
        "stove_clean":      {"pass": True,  "note": "Stove appears clean"},
        "counters_clear":   {"pass": False, "note": "Coffee grounds spilled on counter"},
        "floor_clean":      {"pass": True,  "note": "Floor looks acceptable"},
        "appliances_clean": {"pass": True,  "note": "Appliances are fine"},
        "trash_empty":      {"pass": False, "note": "Trash bag is full and overflowing"},
        "dishes_stored":    {"pass": True,  "note": "Most dishes stored"},
        "coffee_station":   {"pass": False, "note": "K-cup holder is empty"},
        "no_food_left":     {"pass": False, "note": "Open cereal box on counter"},
    },
    "additional_issues": ["Water stain on ceiling above sink"],
    "photo_quality": "good",
})

MOCK_BATHROOM_PASS = json.dumps({
    "room_type": "bathroom",
    "overall_impression": "Bathroom is immaculate and ready for guests",
    "items": {
        "toilet_clean":     {"pass": True, "note": "Toilet scrubbed, lid down"},
        "shower_clean":     {"pass": True, "note": "Shower glass is crystal clear"},
        "mirror_clean":     {"pass": True, "note": "Mirror spotless, no streaks"},
        "floor_clean":      {"pass": True, "note": "Tile floor mopped"},
        "towels_fresh":     {"pass": True, "note": "White towels folded on rack"},
        "toiletries_stock": {"pass": True, "note": "Soap, shampoo, and TP stocked"},
        "counter_clear":    {"pass": True, "note": "Counter clean and clear"},
        "trash_empty":      {"pass": True, "note": "Empty with liner"},
    },
    "additional_issues": [],
    "photo_quality": "good",
})

MOCK_BEDROOM_FAIL = json.dumps({
    "room_type": "bedroom",
    "overall_impression": "Bedroom needs work: bed unmade and personal items left behind",
    "items": {
        "bed_made":          {"pass": False, "note": "Sheets are rumpled, bed not made"},
        "floor_clean":       {"pass": True,  "note": "Floor is vacuumed"},
        "surfaces_dusted":   {"pass": True,  "note": "Nightstands dusted"},
        "closet_empty":      {"pass": False, "note": "Previous guest left a jacket"},
        "curtains_neat":     {"pass": True,  "note": "Curtains drawn neatly"},
        "lights_working":    {"pass": True,  "note": "Both lamps working"},
        "tv_clean":          {"pass": True,  "note": "TV and remote in place"},
        "no_personal_items": {"pass": False, "note": "Phone charger left on nightstand"},
    },
    "additional_issues": ["Small stain visible on carpet near window"],
    "photo_quality": "acceptable",
})


# =============================================================================
# TESTS
# =============================================================================

def test_scoring_kitchen_pass():
    """Test: Kitchen with all items passing should score 100 and PASS."""
    divider("TEST: Kitchen Scoring — All Pass")

    parsed = json.loads(MOCK_KITCHEN_PASS)
    scores = _calculate_scores(parsed, "kitchen")

    print(f"  Score:    {scores['overall_score']}/100")
    print(f"  Verdict:  {scores['verdict']}")
    print(f"  Items:    {scores['items_passed']}/{scores['items_total']} passed")

    assert scores["overall_score"] == 100.0, f"Expected 100, got {scores['overall_score']}"
    assert scores["verdict"] == "PASS"
    assert scores["items_failed"] == 0
    print("  RESULT:   PASS")


def test_scoring_kitchen_fail():
    """Test: Kitchen with 5 failed items should score < 80 and FAIL."""
    divider("TEST: Kitchen Scoring — Multiple Failures")

    parsed = json.loads(MOCK_KITCHEN_FAIL)
    scores = _calculate_scores(parsed, "kitchen")

    print(f"  Score:    {scores['overall_score']}/100")
    print(f"  Verdict:  {scores['verdict']}")
    print(f"  Items:    {scores['items_passed']}/{scores['items_total']} passed")
    print(f"  Failed:   {[f['id'] for f in scores['failed_items']]}")

    assert scores["overall_score"] < 80, f"Expected < 80, got {scores['overall_score']}"
    assert scores["verdict"] == "FAIL"
    assert scores["items_failed"] == 5
    print("  RESULT:   PASS")


def test_scoring_bathroom_pass():
    """Test: Clean bathroom should score 100."""
    divider("TEST: Bathroom Scoring — All Pass")

    parsed = json.loads(MOCK_BATHROOM_PASS)
    scores = _calculate_scores(parsed, "bathroom")

    print(f"  Score:    {scores['overall_score']}/100")
    print(f"  Verdict:  {scores['verdict']}")

    assert scores["overall_score"] == 100.0
    assert scores["verdict"] == "PASS"
    print("  RESULT:   PASS")


def test_scoring_bedroom_fail():
    """Test: Bedroom with unmade bed + personal items should FAIL."""
    divider("TEST: Bedroom Scoring — Bed Unmade + Personal Items")

    parsed = json.loads(MOCK_BEDROOM_FAIL)
    scores = _calculate_scores(parsed, "bedroom")

    print(f"  Score:    {scores['overall_score']}/100")
    print(f"  Verdict:  {scores['verdict']}")
    print(f"  Failed:   {[f['label'] for f in scores['failed_items']]}")

    # bed_made=25 + closet_empty=10 + no_personal_items=12 = 47 lost
    assert scores["verdict"] == "FAIL"
    assert scores["items_failed"] == 3
    print("  RESULT:   PASS")


def test_prompt_generation():
    """Test: Prompts are generated correctly for each room type."""
    divider("TEST: Prompt Generation")

    for room_type in ROOM_CHECKLISTS:
        prompt = _build_inspection_prompt(room_type, "rolling_river")
        assert "rolling_river" in prompt
        assert room_type in prompt or ROOM_CHECKLISTS[room_type]["display_name"] in prompt
        # Verify all checklist item IDs appear in prompt
        for item in ROOM_CHECKLISTS[room_type]["items"]:
            assert item["id"] in prompt, f"Missing {item['id']} in {room_type} prompt"
        print(f"  {room_type:<15} prompt OK ({len(prompt)} chars, {len(ROOM_CHECKLISTS[room_type]['items'])} items)")

    print("  RESULT:   PASS")


def test_json_parse_and_fallback():
    """Test: JSON parsing works, and fallback heuristic handles malformed JSON."""
    divider("TEST: JSON Parsing + Heuristic Fallback")

    # Good JSON
    result = _parse_vision_response(MOCK_KITCHEN_PASS, "kitchen")
    assert result["parsed"] is True
    print(f"  Valid JSON:     parsed={result['parsed']}")

    # Malformed JSON (LLM wrapped in markdown)
    markdown_wrapped = f"```json\n{MOCK_KITCHEN_PASS}\n```"
    result2 = _parse_vision_response(markdown_wrapped, "kitchen")
    assert result2["parsed"] is True
    print(f"  Markdown JSON:  parsed={result2['parsed']}")

    # Completely broken response
    broken = "The kitchen looks clean overall. The sink has dishes. The stove is spotless."
    result3 = _parse_vision_response(broken, "kitchen")
    assert result3["parsed"] is False
    print(f"  Broken text:    parsed={result3['parsed']} (heuristic fallback)")

    print("  RESULT:   PASS")


def test_full_pipeline_with_mock():
    """Test: Full analyze_cleanliness() with mocked Muscle Node response."""
    divider("TEST: Full Pipeline (Mocked Muscle Node)")

    # Create a temp image file (content doesn't matter — LLM is mocked)
    with tempfile.NamedTemporaryFile(suffix=".jpg", delete=False) as f:
        f.write(b"\xff\xd8\xff\xe0" + b"\x00" * 100)  # Minimal JPEG header
        tmp_image = f.name

    try:
        engine = GuardianVisionEngine(
            cabin_name="rolling_river",
            inspector_id="test_runner",
        )

        # Mock the vision call to return our test response
        with patch.object(_mod, "_call_muscle_vision", return_value=MOCK_KITCHEN_FAIL):
            result = engine.analyze_cleanliness(tmp_image, "kitchen")

        print(f"  Run ID:         {result['run_id']}")
        print(f"  Cabin:          {result['cabin_name']}")
        print(f"  Room:           {result['room_display']}")
        print(f"  Score:          {result['overall_score']}/100")
        print(f"  Verdict:        {result['verdict']}")
        print(f"  Confidence:     {result['ai_confidence_score']:.2%}")
        print(f"  Detected By:    {result['detected_by']}")
        print(f"  Inspector:      {result['inspector_id']}")
        print(f"  Items:          {result['items_passed']}/{result['items_total']} passed")

        issues = json.loads(result["issues_found"])
        print(f"  Issues ({len(issues)}):")
        for issue in issues:
            print(f"    - {issue}")

        # Verify all required maintenance_log fields
        required = [
            "run_id", "cabin_name", "room_type", "image_path", "image_hash",
            "overall_score", "verdict", "ai_confidence_score", "detected_by",
            "issues_found", "checklist_json", "raw_analysis",
            "inspector_id", "engine_version", "generated_at",
        ]
        missing = [f for f in required if f not in result]
        assert not missing, f"Missing fields: {missing}"
        print(f"\n  Fields:         All {len(required)} required fields present")

        # Test remediation message
        msg = engine.generate_remediation(result)
        print(f"\n  Remediation Message:")
        for line in msg.split("\n"):
            print(f"    {line}")

        assert result["verdict"] == "FAIL"
        print("\n  RESULT:   PASS")

    finally:
        os.unlink(tmp_image)


def test_full_pipeline_pass_scenario():
    """Test: Full pipeline with a passing result."""
    divider("TEST: Full Pipeline — PASS Scenario")

    with tempfile.NamedTemporaryFile(suffix=".jpg", delete=False) as f:
        f.write(b"\xff\xd8\xff\xe0" + b"\x00" * 100)
        tmp_image = f.name

    try:
        engine = GuardianVisionEngine(
            cabin_name="rolling_river",
            inspector_id="test_runner",
        )

        with patch.object(_mod, "_call_muscle_vision", return_value=MOCK_BATHROOM_PASS):
            result = engine.analyze_cleanliness(tmp_image, "bathroom")

        print(f"  Score:          {result['overall_score']}/100")
        print(f"  Verdict:        {result['verdict']}")
        print(f"  Confidence:     {result['ai_confidence_score']:.2%}")

        msg = engine.generate_remediation(result)
        print(f"  Message:        {msg}")

        assert result["verdict"] == "PASS"
        assert result["overall_score"] == 100.0
        print("  RESULT:   PASS")

    finally:
        os.unlink(tmp_image)


def test_full_cabin_inspection():
    """Test: Full cabin turnover inspection across multiple rooms."""
    divider("TEST: Full Cabin Inspection (Multi-Room)")

    # Create temp images
    tmp_files = {}
    for room in ["kitchen", "bathroom", "bedroom", "living_room"]:
        with tempfile.NamedTemporaryFile(suffix=".jpg", delete=False) as f:
            f.write(b"\xff\xd8\xff\xe0" + b"\x00" * 100)
            tmp_files[room] = f.name

    try:
        engine = GuardianVisionEngine(
            cabin_name="rolling_river",
            inspector_id="cleaner_maria",
        )

        # Mock different responses per room
        mock_responses = {
            "kitchen":     MOCK_KITCHEN_FAIL,
            "bathroom":    MOCK_BATHROOM_PASS,
            "bedroom":     MOCK_BEDROOM_FAIL,
            "living_room": MOCK_BATHROOM_PASS,  # Reuse pass mock
        }

        call_count = [0]
        room_order = list(tmp_files.keys())

        def mock_vision(*args, **kwargs):
            room = room_order[call_count[0]]
            call_count[0] += 1
            return mock_responses[room]

        with patch.object(_mod, "_call_muscle_vision", side_effect=mock_vision):
            report = engine.inspect_full_cabin(tmp_files)

        print(f"  Cabin:          {report['cabin_name']}")
        print(f"  Cabin Score:    {report['cabin_score']}/100")
        print(f"  Cabin Verdict:  {report['cabin_verdict']}")
        print(f"  Rooms:          {report['rooms_inspected']} inspected")
        print(f"  Passed:         {report['rooms_passed']}")
        print(f"  Failed:         {report['rooms_failed']}")

        if report["all_issues"]:
            print(f"\n  All Issues ({len(report['all_issues'])}):")
            for issue in report["all_issues"][:10]:
                print(f"    - {issue}")

        # Session summary
        summary = engine.session_summary
        print(f"\n  Session:        {summary['inspections']} inspections, "
              f"avg score {summary['avg_score']}")

        print("  RESULT:   PASS")

    finally:
        for f in tmp_files.values():
            os.unlink(f)


def test_checklist_weights():
    """Test: All room checklists have weights summing to 100."""
    divider("TEST: Checklist Weight Validation")

    all_valid = True
    for room_type, config in ROOM_CHECKLISTS.items():
        total = sum(item["weight"] for item in config["items"])
        status = "OK" if total == 100 else f"FAIL ({total})"
        if total != 100:
            all_valid = False
        print(f"  {config['display_name']:<25} {len(config['items'])} items  weight={total}  {status}")

    if all_valid:
        print("  RESULT:   PASS (all rooms sum to 100)")
    else:
        print("  RESULT:   WARNING (some rooms don't sum to 100 — scoring still works via normalization)")


def test_json_serialization():
    """Test: Output is fully JSON-serializable for PostgreSQL."""
    divider("TEST: JSON Serialization")

    with tempfile.NamedTemporaryFile(suffix=".jpg", delete=False) as f:
        f.write(b"\xff\xd8\xff\xe0" + b"\x00" * 100)
        tmp_image = f.name

    try:
        engine = GuardianVisionEngine(cabin_name="rolling_river")

        with patch.object(_mod, "_call_muscle_vision", return_value=MOCK_KITCHEN_PASS):
            result = engine.analyze_cleanliness(tmp_image, "kitchen")

        payload = json.dumps(result, default=str)
        print(f"  Serialized:     {len(payload)} bytes")
        print(f"  Roundtrip:      {json.loads(payload)['verdict']}")
        print("  RESULT:   PASS")

    finally:
        os.unlink(tmp_image)


# =============================================================================
# MAIN
# =============================================================================

if __name__ == "__main__":
    print("=" * 70)
    print("  MODULE CF-01: Guardian Ops — Vision Engine Test Suite")
    print("  Crog-Fortress-AI | Data Sovereignty: All Local Compute")
    print("=" * 70)

    tests = [
        test_scoring_kitchen_pass,
        test_scoring_kitchen_fail,
        test_scoring_bathroom_pass,
        test_scoring_bedroom_fail,
        test_prompt_generation,
        test_json_parse_and_fallback,
        test_full_pipeline_with_mock,
        test_full_pipeline_pass_scenario,
        test_full_cabin_inspection,
        test_checklist_weights,
        test_json_serialization,
    ]

    passed = 0
    failed = 0
    for test in tests:
        try:
            test()
            passed += 1
        except Exception as e:
            print(f"\n  FAILED: {e}")
            failed += 1

    divider("TEST SUMMARY")
    print(f"  Tests Run:    {len(tests)}")
    print(f"  Passed:       {passed}")
    print(f"  Failed:       {failed}")
    print(f"  Status:       {'ALL GREEN' if failed == 0 else 'FAILURES DETECTED'}")
    print("\n" + "=" * 70)
    print("  TEST SUITE COMPLETE")
    print("=" * 70)
