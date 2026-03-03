#!/usr/bin/env python3
"""
FORTRESS PRIME — RAG Agent (Neural Search + LLM Synthesis)
============================================================
The primary intelligence agent. Searches Qdrant vector collections and
Postgres email_archive, then synthesizes answers via the current DEFCON
mode's LLM (qwen2.5:7b in SWARM, DeepSeek-R1 in TITAN).

Architecture:
    1. Query → Embed via nomic-embed-text (Ollama)
    2. Vector search across Qdrant collections (email_embeddings, legal_library, etc.)
    3. SQL search for keyword matches in email_archive
    4. Context assembly → LLM synthesis
    5. Response with citations

Usage:
    from src.agent_fortress import FortressAgent

    agent = FortressAgent()
    answer = agent.ask("What did Stuart say about the Eckles case?")

CLI:
    ./venv/bin/python src/agent_fortress.py --query "Find all emails about Prime Trust"
"""

import json
import os
import sys
import logging
import requests
import psycopg2
import psycopg2.extras
from datetime import datetime
from pathlib import Path
from typing import Optional

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from config import (
    get_inference_client, get_embeddings_url,
    SPARK_01_IP, FORTRESS_DEFCON,
)

log = logging.getLogger("fortress.agent")
logging.basicConfig(level=logging.INFO, format="%(asctime)s [AGENT] %(message)s")

QDRANT_HOST = os.getenv("QDRANT_HOST", SPARK_01_IP)
QDRANT_PORT = int(os.getenv("QDRANT_PORT", "6333"))
QDRANT_API_KEY = os.getenv("QDRANT_API_KEY", os.getenv("QDRANT__SERVICE__API_KEY", ""))
DEFAULT_COLLECTIONS = ["email_embeddings", "legal_library", "fortress_knowledge"]

DB_CONFIG = {"dbname": os.getenv("DB_NAME", "fortress_db"), "user": os.getenv("DB_USER", "admin")}


class FortressAgent:
    """RAG agent with neural search and LLM synthesis."""

    def __init__(self, collections: list = None):
        self.collections = collections or DEFAULT_COLLECTIONS
        self.embed_url = get_embeddings_url()
        self.qdrant_url = f"http://{QDRANT_HOST}:{QDRANT_PORT}"
        self.qdrant_headers = {"api-key": QDRANT_API_KEY} if QDRANT_API_KEY else {}

    def _embed(self, text: str) -> list:
        """Generate embedding via Ollama nomic-embed-text."""
        try:
            resp = requests.post(
                self.embed_url,
                json={"model": "nomic-embed-text", "prompt": text},
                timeout=30,
            )
            resp.raise_for_status()
            return resp.json().get("embedding", [])
        except Exception as e:
            log.error(f"Embedding failed: {e}")
            return []

    def _vector_search(self, embedding: list, collection: str,
                       limit: int = 5, division_filter: str = None) -> list:
        """Search a Qdrant collection by vector similarity."""
        if not embedding:
            return []

        body = {
            "vector": embedding,
            "limit": limit,
            "with_payload": True,
        }
        if division_filter:
            body["filter"] = {
                "must": [{"key": "division", "match": {"value": division_filter}}]
            }

        try:
            resp = requests.post(
                f"{self.qdrant_url}/collections/{collection}/points/search",
                json=body,
                headers=self.qdrant_headers,
                timeout=15,
            )
            resp.raise_for_status()
            return resp.json().get("result", [])
        except Exception as e:
            log.warning(f"Qdrant search failed on {collection}: {e}")
            return []

    def _sql_search(self, query: str, limit: int = 10) -> list:
        """Keyword search in email_archive as fallback."""
        try:
            conn = psycopg2.connect(**DB_CONFIG)
            cur = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
            cur.execute("""
                SELECT id, sender_email, sender_name, subject, body_plain,
                       sent_at, division
                FROM email_archive
                WHERE to_tsvector('english', coalesce(subject,'') || ' ' || coalesce(body_plain,''))
                      @@ plainto_tsquery('english', %s)
                ORDER BY sent_at DESC
                LIMIT %s
            """, (query, limit))
            results = [dict(r) for r in cur.fetchall()]
            cur.close()
            conn.close()
            return results
        except Exception as e:
            log.warning(f"SQL search failed: {e}")
            return []

    def search(self, query: str, top_k: int = 5, division: str = None) -> dict:
        """Multi-source search: vectors + SQL."""
        embedding = self._embed(query)

        vector_results = []
        for coll in self.collections:
            hits = self._vector_search(embedding, coll, limit=top_k, division_filter=division)
            for hit in hits:
                vector_results.append({
                    "collection": coll,
                    "score": hit.get("score", 0),
                    "payload": hit.get("payload", {}),
                })

        vector_results.sort(key=lambda x: x["score"], reverse=True)
        sql_results = self._sql_search(query, limit=top_k)

        return {
            "query": query,
            "vector_hits": vector_results[:top_k],
            "sql_hits": sql_results,
        }

    def ask(self, query: str, top_k: int = 5, division: str = None) -> dict:
        """Full RAG pipeline: search → context assembly → LLM synthesis."""
        results = self.search(query, top_k=top_k, division=division)

        context_parts = []
        for hit in results["vector_hits"]:
            payload = hit["payload"]
            text = payload.get("text", payload.get("body", payload.get("subject", "")))
            sender = payload.get("sender_email", payload.get("sender", ""))
            context_parts.append(f"[Vector:{hit['collection']} score:{hit['score']:.3f}] "
                                f"From: {sender}\n{text[:500]}")

        for hit in results["sql_hits"]:
            context_parts.append(f"[SQL] From: {hit.get('sender_email','')} "
                                f"Subject: {hit.get('subject','')}\n"
                                f"{str(hit.get('body_plain',''))[:500]}")

        context = "\n---\n".join(context_parts) or "No relevant documents found."

        system_prompt = (
            "You are the Fortress Intelligence Agent. Answer the user's question based "
            "on the retrieved evidence below. Cite specific emails, dates, and senders. "
            "If the evidence is insufficient, say so clearly.\n\n"
            f"DEFCON mode: {FORTRESS_DEFCON}\n"
            f"Evidence ({len(context_parts)} sources):\n{context}"
        )

        client, model = get_inference_client()
        try:
            response = client.chat.completions.create(
                model=model,
                messages=[
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": query},
                ],
                temperature=0.2,
                max_tokens=4096,
            )
            answer = response.choices[0].message.content or ""
        except Exception as e:
            log.error(f"LLM synthesis failed: {e}")
            answer = f"Error generating response: {e}"

        return {
            "query": query,
            "answer": answer,
            "model": model,
            "sources_used": len(context_parts),
            "vector_hits": len(results["vector_hits"]),
            "sql_hits": len(results["sql_hits"]),
        }


if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser(description="Fortress RAG Agent")
    parser.add_argument("--query", type=str, required=True, help="Question to answer")
    parser.add_argument("--top-k", type=int, default=5, help="Number of results")
    parser.add_argument("--division", type=str, help="Filter by division")
    parser.add_argument("--search-only", action="store_true", help="Search without LLM")
    args = parser.parse_args()

    agent = FortressAgent()

    if args.search_only:
        results = agent.search(args.query, top_k=args.top_k, division=args.division)
        print(json.dumps(results, indent=2, default=str))
    else:
        result = agent.ask(args.query, top_k=args.top_k, division=args.division)
        print(f"\n{'='*60}")
        print(f"Query: {result['query']}")
        print(f"Model: {result['model']} | Sources: {result['sources_used']}")
        print(f"{'='*60}\n")
        print(result["answer"])
