"""
Fortress Prime — THE THUNDERDOME
Adversarial Legal Swarm: Three AI agents fight over your case.

    The Pitbull (Prosecutor) — Attacks. Cites O.C.G.A. for maximum penalty.
    The Shield  (Defense)    — Defends. Finds loopholes and motions to dismiss.
    The Judge   (Arbiter)    — Weighs both sides. Delivers final strategy.

Each agent has access to the law_library ChromaDB (1,334 statutes).

Usage:
    python division_legal/thunderdome.py "Guest refuses to leave after checkout"
    python division_legal/thunderdome.py --interactive
"""
import os
import sys
import json
import time
import requests
import chromadb
from datetime import datetime

# Fortress Prompt System
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
from prompts.loader import load_prompt

# --- CONFIG ---
R1_URL = "http://localhost:11434/api/generate"
R1_MODEL = "deepseek-r1:8b"  # Fast model for multi-turn debate
CHROMA_PATH = os.path.join(os.path.dirname(__file__), "chroma_db")
CASE_FILES = os.path.join(
    "/mnt/fortress_nas/Enterprise_War_Room/Legal_Evidence", "Case_Files"
)

# Force unbuffered output
sys.stdout.reconfigure(line_buffering=True)

# --- AGENT PERSONALITIES (loaded from prompts/v1/) ---
PITBULL_SYSTEM = load_prompt("thunderdome_pitbull").render()
SHIELD_SYSTEM = load_prompt("thunderdome_shield").render()
JUDGE_SYSTEM = load_prompt("thunderdome_judge").render()


class LegalRoundTable:
    def __init__(self):
        # Initialize ChromaDB connection
        self.client = chromadb.PersistentClient(path=CHROMA_PATH)
        self.collection = self.client.get_collection("law_library")
        print(f"   ChromaDB connected: {self.collection.count()} statutes loaded.")

    def get_query_embedding(self, text):
        """Get embedding using the same model used for indexing."""
        try:
            r = requests.post("http://localhost:11434/api/embeddings", json={
                "model": "nomic-embed-text:latest",
                "prompt": text
            }, timeout=30)
            if r.status_code == 200:
                return r.json().get("embedding")
        except Exception as e:
            print(f"      Embedding error: {e}")
        return None

    def retrieve_law(self, query, n_results=8):
        """Pull relevant statutes from ChromaDB for context."""
        embedding = self.get_query_embedding(query)
        if not embedding:
            return "(Failed to generate query embedding)"
        results = self.collection.query(
            query_embeddings=[embedding],
            n_results=n_results
        )
        if results and results["documents"]:
            statutes = []
            for doc, meta in zip(results["documents"][0], results["metadatas"][0]):
                statutes.append(f"[{meta.get('source', 'O.C.G.A.')} § {meta.get('section', '?')}]\n{doc[:800]}")
            return "\n\n---\n\n".join(statutes)
        return "(No relevant statutes found)"

    def consult_agent(self, system_prompt, task, context=""):
        """Send a request to DeepSeek-R1 via Ollama."""
        prompt = f"""[SYSTEM]
{system_prompt}

[RELEVANT GEORGIA LAW]
{context}

[CASE / TASK]
{task}"""

        payload = {
            "model": R1_MODEL,
            "prompt": prompt,
            "stream": False,
            "options": {"temperature": 0.7, "num_predict": 1500}
        }
        try:
            res = requests.post(R1_URL, json=payload, timeout=300)
            if res.status_code == 200:
                response = res.json().get("response", "")
                # Strip thinking tags if present
                if "<think>" in response:
                    parts = response.split("</think>")
                    response = parts[-1].strip() if len(parts) > 1 else response
                return response
            return f"(Agent returned HTTP {res.status_code})"
        except Exception as e:
            return f"(Agent error: {e})"

    def retrieve_drawing_evidence(self, topic):
        """Pull relevant engineering drawing data for property-related cases."""
        try:
            sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
            from tools.drawing_reader import extract_for_legal, inventory_drawings

            # Check for property-related keywords
            keywords = ["survey", "plat", "boundary", "easement", "property line",
                        "encroach", "right of way", "railroad", "crossing",
                        "deed", "parcel", "lot", "setback", "septic", "grading",
                        "toccoa", "blue ridge", "fannin", "cabin"]
            topic_lower = topic.lower()
            if not any(kw in topic_lower for kw in keywords):
                return ""

            # Find all drawings on NAS
            inv = inventory_drawings()
            dxf_files = [f for f in inv.get("files", []) if f["extension"] == ".dxf"]

            if not dxf_files:
                return ""

            print("   Searching engineering drawings for relevant evidence...")
            evidence_parts = []
            for finfo in dxf_files[:10]:  # Cap at 10 drawings
                try:
                    legal_data = extract_for_legal(finfo["filepath"])
                    if not legal_data.get("readable"):
                        continue
                    # Only include if it has legal-relevant content
                    if (legal_data.get("encumbrances_detected") or
                            legal_data.get("survey", {}).get("call_count", 0) > 0):
                        parts = [f"\n[Drawing: {legal_data['filename']}]"]
                        parts.append(f"  Type: {legal_data['doc_type']}")
                        prop = legal_data.get("property", {})
                        if prop.get("owner"):
                            parts.append(f"  Owner: {prop['owner']}")
                        if prop.get("subdivision"):
                            parts.append(f"  Subdivision: {prop['subdivision']}")
                        if prop.get("county"):
                            parts.append(f"  County: {prop['county']}")
                        sc = legal_data.get("survey", {})
                        if sc.get("call_count", 0) > 0:
                            parts.append(f"  Survey calls: {sc['call_count']} "
                                         f"(bearings + distances)")
                        for kw_type, refs in legal_data.get("legal_keywords", {}).items():
                            parts.append(f"  {kw_type}: {'; '.join(refs[:3])}")
                        evidence_parts.append("\n".join(parts))
                except Exception:
                    continue

            if evidence_parts:
                return ("\n\n--- ENGINEERING DRAWING EVIDENCE ---\n"
                        + "\n".join(evidence_parts))
            return ""
        except Exception as e:
            print(f"   (Drawing evidence retrieval: {e})")
            return ""

    def argue(self, topic):
        """Run the full adversarial debate."""
        timestamp = datetime.now().strftime("%Y-%m-%d_%H-%M")
        print(f"\n{'='*70}")
        print(f"  THUNDERDOME — ADVERSARIAL LEGAL ANALYSIS")
        print(f"  Case: {topic}")
        print(f"  Time: {timestamp}")
        print(f"{'='*70}\n")

        # Retrieve relevant law
        print("📚 Retrieving relevant statutes from law_library...")
        law_context = self.retrieve_law(topic, n_results=10)
        print(f"   (Retrieved context: {len(law_context)} chars)")

        # Retrieve engineering drawing evidence (surveys, plats, easements)
        drawing_evidence = self.retrieve_drawing_evidence(topic)
        if drawing_evidence:
            law_context += drawing_evidence
            print(f"   (+ Engineering drawing evidence added)\n")
        else:
            print()

        transcript = []
        transcript.append(f"# THUNDERDOME — Legal Analysis\n")
        transcript.append(f"**Case:** {topic}\n")
        transcript.append(f"**Date:** {timestamp}\n")
        transcript.append(f"**Statutes Consulted:** {self.collection.count()} in law_library\n")
        transcript.append(f"---\n")

        # --- ROUND 1: PITBULL OPENING ---
        print("🐕 ROUND 1: THE PITBULL — Opening Statement")
        print("-" * 50)
        pitbull_opening = self.consult_agent(
            PITBULL_SYSTEM,
            f"Present your prosecution case for this situation:\n\n{topic}",
            law_context
        )
        print(pitbull_opening)
        transcript.append(f"\n## 🐕 ROUND 1: THE PITBULL (Prosecution)\n\n{pitbull_opening}\n")

        # --- ROUND 2: SHIELD REBUTTAL ---
        print(f"\n{'='*50}")
        print("🛡️  ROUND 2: THE SHIELD — Rebuttal")
        print("-" * 50)
        shield_rebuttal = self.consult_agent(
            SHIELD_SYSTEM,
            f"The Prosecution has argued the following:\n\n{pitbull_opening}\n\nDestroy their argument. Defend the client's position and find every weakness.",
            law_context
        )
        print(shield_rebuttal)
        transcript.append(f"\n## 🛡️ ROUND 2: THE SHIELD (Defense)\n\n{shield_rebuttal}\n")

        # --- ROUND 3: PITBULL COUNTER ---
        print(f"\n{'='*50}")
        print("🐕 ROUND 3: THE PITBULL — Counter-Argument")
        print("-" * 50)
        pitbull_counter = self.consult_agent(
            PITBULL_SYSTEM,
            f"The Defense has rebutted your argument:\n\n{shield_rebuttal}\n\nCounter their points. Strengthen your case.",
            law_context
        )
        print(pitbull_counter)
        transcript.append(f"\n## 🐕 ROUND 3: THE PITBULL (Counter-Argument)\n\n{pitbull_counter}\n")

        # --- ROUND 4: THE JUDGE ---
        print(f"\n{'='*50}")
        print("⚖️  ROUND 4: THE JUDGE — Final Verdict")
        print("-" * 50)
        full_debate = f"""PROSECUTION OPENING:\n{pitbull_opening}\n\nDEFENSE REBUTTAL:\n{shield_rebuttal}\n\nPROSECUTION COUNTER:\n{pitbull_counter}"""
        judge_verdict = self.consult_agent(
            JUDGE_SYSTEM,
            f"You have heard the full debate on this case:\n\n{topic}\n\nHere is the transcript:\n\n{full_debate}\n\nDeliver your verdict and strategic action plan.",
            law_context
        )
        print(judge_verdict)
        transcript.append(f"\n## ⚖️ ROUND 4: THE JUDGE (Verdict)\n\n{judge_verdict}\n")

        # --- SAVE TRANSCRIPT ---
        os.makedirs(CASE_FILES, exist_ok=True)
        safe_topic = "".join(c if c.isalnum() or c in " _-" else "_" for c in topic[:50])
        filename = f"{timestamp}_{safe_topic}.md"
        filepath = os.path.join(CASE_FILES, filename)
        with open(filepath, "w", encoding="utf-8") as f:
            f.write("\n".join(transcript))

        print(f"\n{'='*70}")
        print(f"  📄 TRANSCRIPT SAVED: {filepath}")
        print(f"{'='*70}\n")

        return {
            "pitbull": pitbull_opening,
            "shield": shield_rebuttal,
            "counter": pitbull_counter,
            "verdict": judge_verdict,
            "transcript": filepath
        }


def main():
    if len(sys.argv) < 2 or sys.argv[1] == "--interactive":
        print("⚖️  FORTRESS PRIME: THE THUNDERDOME")
        print("   Enter a legal scenario for adversarial analysis.\n")
        topic = input("📋 Case: ")
    else:
        topic = " ".join(sys.argv[1:])

    court = LegalRoundTable()
    court.argue(topic)


if __name__ == "__main__":
    main()
