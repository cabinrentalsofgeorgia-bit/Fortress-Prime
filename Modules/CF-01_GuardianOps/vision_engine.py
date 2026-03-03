"""
Module CF-01: Guardian Ops -- Vision Inspection Engine
======================================================
Cabin Rentals of Georgia | Crog-Fortress-AI
Data Sovereignty: All vision inference on Muscle Node GPU. No cloud APIs.

Bridges the FastAPI inspection API to the Muscle Node's local vision model.
Encodes images, builds structured prompts from room checklists, parses
the LLM JSON response, and calculates inspection scores.

Core processing functions (_call_muscle_vision, _build_inspection_prompt,
_parse_vision_response, _calculate_scores) are module-level to support
test mocking via unittest.mock.patch.

Usage:
    from vision_engine import GuardianVisionEngine, ROOM_CHECKLISTS

    engine = GuardianVisionEngine(cabin_name="rolling_river", inspector_id="maria")
    result = engine.analyze_cleanliness("/path/to/photo.jpg", "kitchen")
"""

import os
import json
import uuid
import base64
import hashlib
import re
import httpx
from datetime import datetime
from config import MUSCLE_GENERATE_URL, MUSCLE_VISION_MODEL

ROOM_CHECKLISTS = {
    "kitchen": {
        "display_name": "Kitchen",
        "items": [
            {"id": "counters_wiped", "label": "Counters wiped down", "weight": 20},
            {"id": "sink_clean", "label": "Sink empty and scrubbed", "weight": 20},
            {"id": "appliances_clean", "label": "Appliance faces clean", "weight": 20},
            {"id": "floor_swept", "label": "Floor swept and mopped", "weight": 20},
            {"id": "trash_emptied", "label": "Trash emptied", "weight": 20},
        ]
    },
    "bathroom": {
        "display_name": "Bathroom",
        "items": [
            {"id": "toilet_scrubbed", "label": "Toilet scrubbed and sanitized", "weight": 25},
            {"id": "shower_clean", "label": "Shower/tub free of hair and soap", "weight": 25},
            {"id": "mirror_wiped", "label": "Mirror wiped streak-free", "weight": 20},
            {"id": "sink_wiped", "label": "Sink and faucet clean", "weight": 15},
            {"id": "towels_stocked", "label": "Fresh towels stocked", "weight": 15},
        ]
    },
    "bedroom": {
        "display_name": "Bedroom",
        "items": [
            {"id": "bed_made", "label": "Bed made with fresh linens", "weight": 40},
            {"id": "floor_vacuumed", "label": "Floor vacuumed/swept", "weight": 30},
            {"id": "surfaces_dusted", "label": "Nightstands and dressers dusted", "weight": 30},
        ]
    },
    "living_room": {
        "display_name": "Living Room",
        "items": [
            {"id": "pillows_arranged", "label": "Pillows arranged neatly", "weight": 30},
            {"id": "surfaces_dusted", "label": "Surfaces dusted", "weight": 30},
            {"id": "floor_vacuumed", "label": "Floor vacuumed", "weight": 40},
        ]
    },
}


# ---------------------------------------------------------------------------
# MODULE-LEVEL FUNCTIONS (patchable by test suite via unittest.mock.patch)
# ---------------------------------------------------------------------------

def _call_muscle_vision(base64_image: str, prompt: str) -> str:
    """Send image + prompt to the Muscle Node's local vision model."""
    payload = {
        "model": MUSCLE_VISION_MODEL,
        "prompt": prompt,
        "images": [base64_image],
        "stream": False,
        "options": {"temperature": 0.0},
    }
    try:
        with httpx.Client(timeout=110.0) as client:
            resp = client.post(MUSCLE_GENERATE_URL, json=payload)
            resp.raise_for_status()
            return resp.json().get("response", "{}")
    except Exception as e:
        return json.dumps({"error": f"Muscle Node Unreachable: {e}"})


def _build_inspection_prompt(room_type: str, cabin_name: str) -> str:
    """Build a structured prompt that includes all checklist item IDs."""
    checklist = ROOM_CHECKLISTS.get(room_type)
    if not checklist:
        return "Analyze this image and return valid JSON."
    items = [item["id"] for item in checklist["items"]]
    return (
        f"You are the GuardianOps Inspector for {cabin_name}. "
        f"Analyze this {room_type}. "
        "Return STRICTLY valid JSON with the following structure: "
        '{"items": {<key>: {"pass": bool, "note": str}}, '
        '"additional_issues": [str], "photo_quality": str}. '
        f"Required item keys: {', '.join(items)}. "
        "Evaluate each as true if clean/done, false if dirty/missed."
    )


def _parse_vision_response(raw_text: str, room_type: str) -> dict:
    """Parse LLM response JSON, stripping markdown fences if present."""
    try:
        clean_text = re.sub(r"```json|```", "", raw_text).strip()
        match = re.search(r"\{.*\}", clean_text, re.DOTALL)
        data = json.loads(match.group(0)) if match else json.loads(clean_text)
        if "error" in data:
            return {"parsed": False, "items": {}, "raw": raw_text}
        return {"parsed": True, **data}
    except Exception:
        return {"parsed": False, "items": {}, "raw": raw_text}


def _calculate_scores(parsed: dict, room_type: str) -> dict:
    """Score inspection based on pass/fail status of items in the LLM response.

    Scoring uses the items dict returned by the vision model, not the
    ROOM_CHECKLISTS weights. ROOM_CHECKLISTS drives prompt generation;
    the LLM's own item evaluations drive scoring. This decoupling allows
    the model to report on items it actually observes in the image.
    """
    items = parsed.get("items", {})
    if not items:
        return {
            "overall_score": 0.0,
            "verdict": "FAIL",
            "items_passed": 0,
            "items_total": 0,
            "items_failed": 0,
            "failed_items": [],
        }

    total = len(items)
    passed_count = 0
    failed_items = []

    for item_id, item_data in items.items():
        if isinstance(item_data, dict):
            passed = bool(item_data.get("pass", False))
            note = item_data.get("note", item_id)
        else:
            passed = bool(item_data)
            note = str(item_id)

        if passed:
            passed_count += 1
        else:
            failed_items.append({"id": item_id, "label": note})

    score = (passed_count / total * 100.0) if total > 0 else 0.0
    verdict = "PASS" if score >= 80 else "FAIL"

    return {
        "overall_score": round(score, 1),
        "verdict": verdict,
        "items_passed": passed_count,
        "items_total": total,
        "items_failed": total - passed_count,
        "failed_items": failed_items,
    }


# ---------------------------------------------------------------------------
# CORE ENGINE CLASS
# ---------------------------------------------------------------------------

class GuardianVisionEngine:
    def __init__(self, cabin_name: str, inspector_id: str = "system"):
        self.cabin_name = cabin_name
        self.inspector_id = inspector_id
        self.engine_version = "1.0.0"
        self._inspections_run = 0
        self._total_score_acc = 0.0

    def analyze_cleanliness(self, image_path: str, room_type: str) -> dict:
        run_id = uuid.uuid4().hex[:12]
        generated_at = datetime.utcnow().isoformat()

        try:
            with open(image_path, "rb") as f:
                img_bytes = f.read()
                base64_img = base64.b64encode(img_bytes).decode("utf-8")
                img_hash = hashlib.sha256(img_bytes).hexdigest()
        except Exception as e:
            return {
                "run_id": run_id,
                "verdict": "FAIL",
                "overall_score": 0.0,
                "raw_analysis": f"Image read failed: {e}",
            }

        prompt = _build_inspection_prompt(room_type, self.cabin_name)
        raw_response = _call_muscle_vision(base64_img, prompt)
        parsed = _parse_vision_response(raw_response, room_type)
        scoring = _calculate_scores(parsed, room_type)

        self._inspections_run += 1
        self._total_score_acc += scoring["overall_score"]

        return {
            "run_id": run_id,
            "cabin_name": self.cabin_name,
            "room_type": room_type,
            "room_display": ROOM_CHECKLISTS.get(room_type, {}).get(
                "display_name", room_type
            ),
            "image_path": image_path,
            "image_hash": img_hash,
            "overall_score": scoring["overall_score"],
            "verdict": scoring["verdict"],
            "ai_confidence_score": 0.95 if parsed.get("parsed") else 0.0,
            "detected_by": MUSCLE_VISION_MODEL,
            "issues_found": json.dumps(scoring["failed_items"]),
            "checklist_json": parsed,
            "raw_analysis": raw_response,
            "inspector_id": self.inspector_id,
            "engine_version": self.engine_version,
            "generated_at": generated_at,
            "items_passed": scoring["items_passed"],
            "items_total": scoring["items_total"],
        }

    def inspect_full_cabin(self, room_images: dict) -> dict:
        results = {}
        total_score = 0.0
        rooms_passed = 0
        rooms_failed = 0
        all_issues = []

        for room, path in room_images.items():
            res = self.analyze_cleanliness(path, room)
            results[room] = res
            total_score += res.get("overall_score", 0)
            if res.get("verdict") == "PASS":
                rooms_passed += 1
            else:
                rooms_failed += 1
            all_issues.extend(json.loads(res.get("issues_found", "[]")))

        rooms_inspected = len(room_images)
        cabin_score = total_score / rooms_inspected if rooms_inspected else 0.0

        return {
            "cabin_name": self.cabin_name,
            "cabin_score": round(cabin_score, 2),
            "cabin_verdict": "PASS" if cabin_score >= 90 else "FAIL",
            "rooms_inspected": rooms_inspected,
            "rooms_passed": rooms_passed,
            "rooms_failed": rooms_failed,
            "all_issues": all_issues,
            "room_results": results,
            "inspector_id": self.inspector_id,
            "generated_at": datetime.utcnow().isoformat(),
        }

    def generate_remediation(self, result: dict) -> str:
        if result.get("verdict") == "PASS":
            return "Room meets Fortress Prime standards. No remediation needed."

        issues = json.loads(result.get("issues_found", "[]"))
        score = result.get("overall_score", 0)
        room = result.get("room_display", result.get("room_type", "unknown"))

        lines = [f"REMEDIATION REQUIRED: {room} (Score: {score}/100)"]
        if issues:
            lines.append("Failed items:")
            for item in issues:
                label = item.get("label", item.get("id", "unknown")) if isinstance(item, dict) else str(item)
                lines.append(f"  - {label}")
        return "\n".join(lines)

    @property
    def session_summary(self) -> dict:
        avg = self._total_score_acc / self._inspections_run if self._inspections_run else 0.0
        return {
            "inspections": self._inspections_run,
            "avg_score": round(avg, 2),
        }
