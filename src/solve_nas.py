import json
import requests
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
from config import SPARK_02_IP

# --- CONFIG ---
REPORT_FILE = os.path.expanduser("~/Fortress-Prime/nas_audit_report.json")

# Ollama /api/chat endpoints (proven to work with both models)
PLANNER_URL = "http://localhost:11434/api/chat"
PLANNER_MODEL = "deepseek-r1:8b"

WORKER_URL = f"http://{SPARK_02_IP}:11434/api/chat"
WORKER_MODEL = "llama3.2-vision:90b"


def query(url, model, prompt, role):
    """Query an Ollama model via /api/chat with proper timeout."""
    print(f"   --> {role} ({model}) is thinking...")
    payload = {
        "model": model,
        "messages": [{"role": "user", "content": prompt}],
        "stream": False,
        "options": {
            "temperature": 0.4,
            "num_predict": 4096,
        },
    }
    try:
        res = requests.post(url, json=payload, timeout=900)
        data = res.json()
        msg = data.get("message", {})
        # DeepSeek R1 puts reasoning in 'thinking' and answer in 'content'
        content = msg.get("content", "")
        if not content.strip() and "thinking" in msg:
            content = msg["thinking"]
        return content
    except Exception as e:
        return f"Error: {e}"


def analyze_and_solve():
    print(f"\n📂 LOADING AUDIT REPORT: {REPORT_FILE}")
    if not os.path.exists(REPORT_FILE):
        print("❌ Report not found! Please wait for forensic_audit.py to finish.")
        return

    # 1. Digest the Data (Read the JSON)
    with open(REPORT_FILE) as f:
        data = json.load(f)

    dupes = data.get("duplicates", [])
    total_dupes = len(dupes)

    # Calculate wasted space safely
    wasted_space = 0
    if total_dupes > 0:
        wasted_space = sum(d.get("size", 0) for d in dupes) / (1024**3)  # GB

    situation = (
        f"Forensic Scan Complete.\n"
        f"Total Files Scanned: {len(data.get('files', {}))}\n"
        f"Total Duplicates: {total_dupes}\n"
        f"Wasted Space: {wasted_space:.2f} GB\n"
    )
    print("=" * 60)
    print(situation)
    print("=" * 60)

    if total_dupes == 0:
        print("✅ Clean drive. No action needed.")
        return

    # 2. The Planner (DeepSeek 8B)
    print("\n🧠 STEP 1: PLANNER (Strategy)")
    strategy_prompt = (
        f"You are the Data Architect. We found {total_dupes} duplicate files wasting {wasted_space:.2f} GB. "
        f"Here is a sample duplicate entry: {json.dumps(dupes[0]) if dupes else 'N/A'}. "
        "Define a strict safety protocol for deleting these. "
        "Rules: Always keep the oldest file. Preserve file paths with 'Final' or 'Tax' in the name. "
        "Output a numbered logic plan. Be concise and precise."
    )
    plan = query(PLANNER_URL, PLANNER_MODEL, strategy_prompt, "Planner")
    print(f"\n📋 PROTOCOL:\n{plan}\n")

    # 3. The Worker (Llama 90B)
    print("\n👁️ STEP 2: WORKER (Code Generation)")
    code_prompt = (
        f"Based on this protocol:\n{plan}\n\n"
        "Write a Python script that:\n"
        "1. Reads 'nas_audit_report.json' which has a 'duplicates' list where each entry has 'original' (path), 'duplicate' (path), and 'size' (bytes).\n"
        "2. For each duplicate pair, applies the safety rules from the protocol above.\n"
        "3. Includes a --dry-run flag (default ON) that only prints what would be deleted.\n"
        "4. When --dry-run is OFF, actually deletes the duplicate file using os.remove().\n"
        "5. Logs every action to 'cleanup_log.txt'.\n"
        "Output ONLY the Python code, no explanation."
    )
    script_solution = query(WORKER_URL, WORKER_MODEL, code_prompt, "Worker")

    print(f"\n💻 GENERATED CLEANUP SCRIPT:\n{script_solution}")

    # Save the solution
    output_path = os.path.expanduser("~/Fortress-Prime/generated_cleanup.py")
    with open(output_path, "w") as f:
        f.write(script_solution)
    print(f"\n✅ Solution saved to '{output_path}'")


if __name__ == "__main__":
    analyze_and_solve()
