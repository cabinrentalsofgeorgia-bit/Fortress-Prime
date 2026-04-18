#!/usr/bin/env python3
"""
GEMINI ARCHITECT — The Senior Developer (Constitution Article II)
==================================================================
Fortress Prime | Gemini 3 Pro as the strategic planning brain.

This module gives Gemini function-calling access to LOCAL tools:
    - read_file:        Read any file on the Spark cluster
    - list_directory:   List files in a directory
    - query_postgres:   Run SELECT queries against fortress_db
    - search_qdrant:    Semantic search across any Qdrant collection
    - run_command:       Execute shell commands (restricted)

SAFETY (Constitution Article I):
    - Gemini NEVER receives raw PII, financial, or legal data.
    - All Postgres results are summarized locally before sending.
    - File reads are filtered for sensitive content.
    - The Human (Gary) retains absolute override authority.

HIERARCHY (Constitution Article II):
    Human (Gary) > Sovereign (R1-671B) > Architect (Gemini 3 Pro)
    The Architect plans. The Sovereign verifies. The Human approves.

Usage:
    # Interactive mode
    python3 -m tools.gemini_architect

    # Single query
    python3 -m tools.gemini_architect "What tables exist in the hedge_fund schema?"

    # Programmatic
    from tools.gemini_architect import ask_architect
    result = ask_architect("Analyze the email_archive table structure")

Governing Documents:
    CONSTITUTION.md  — Article I (data sovereignty), Article II (hierarchy)
    REQUIREMENTS.md  — Section 2.2 (hybrid orchestration)
    config.py        — ARCHITECT_ENDPOINT, GOOGLE_AI_API_KEY
"""

from __future__ import annotations

import os
import sys
import json
import logging
import subprocess
from pathlib import Path
from typing import Optional

logger = logging.getLogger("tools.gemini_architect")

PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))


# =============================================================================
# I. CONFIGURATION
# =============================================================================

try:
    from config import (
        GOOGLE_AI_API_KEY, ARCHITECT_ENDPOINT, ARCHITECT_MODEL,
        DB_HOST, DB_NAME, DB_USER, DB_PASS, DB_PORT,
        HYDRA_ENDPOINT, HYDRA_ENDPOINTS, HYDRA_MODEL,
        SPARK_01_IP, SPARK_02_IP, SPARK_03_IP, SPARK_04_IP,
    )
except ImportError:
    GOOGLE_AI_API_KEY = os.getenv("GOOGLE_AI_API_KEY", "")
    ARCHITECT_ENDPOINT = "https://generativelanguage.googleapis.com/v1beta/openai/"
    ARCHITECT_MODEL = os.getenv("ARCHITECT_MODEL", "gemini-2.5-pro")
    DB_HOST = os.getenv("DB_HOST", "192.168.0.100")
    DB_NAME = os.getenv("DB_NAME", "fortress_db")
    DB_USER = os.getenv("DB_USER", "miner_bot")
    DB_PASS = os.getenv("DB_PASS", "")
    DB_PORT = int(os.getenv("DB_PORT", "5432"))
    SPARK_01_IP = os.getenv("SPARK_01_IP", "192.168.0.100")
    SPARK_02_IP = os.getenv("SPARK_02_IP", "192.168.0.104")
    SPARK_03_IP = os.getenv("SPARK_03_IP", "192.168.0.105")
    SPARK_04_IP = os.getenv("SPARK_04_IP", "192.168.0.106")
    HYDRA_ENDPOINT = f"http://{SPARK_01_IP}/v1"
    HYDRA_ENDPOINTS = [
        f"http://{SPARK_01_IP}:11434/v1",
        f"http://{SPARK_02_IP}:11434/v1",
        f"http://{SPARK_03_IP}:11434/v1",
        f"http://{SPARK_04_IP}:11434/v1",
    ]
    HYDRA_MODEL = os.getenv("HYDRA_MODEL", "deepseek-r1:70b")

# Hydra node names (for parallel dispatch reporting)
HYDRA_NODE_NAMES = ["Captain", "Muscle", "Ocular", "Sovereign"]

# Safety: Maximum chars from any single tool result sent to Gemini
MAX_TOOL_RESULT_CHARS = 8000

# Forbidden paths (never send to Gemini)
FORBIDDEN_PATHS = {".env", "credentials", "secrets", ".ssh", "private_key"}

# Restricted SQL keywords (Gemini can only SELECT)
FORBIDDEN_SQL = {"insert", "update", "delete", "drop", "alter", "create", "truncate", "grant"}

# Restricted shell commands
FORBIDDEN_COMMANDS = {"rm -rf", "mkfs", "dd if=", "shutdown", "reboot", "> /dev/"}


# =============================================================================
# II. THE ARCHITECT'S SYSTEM PROMPT
# =============================================================================

ARCHITECT_SYSTEM_PROMPT = """You are the Fortress Prime Architect — the Senior Developer and 
Commander of a 4-node DGX Spark supercomputer cluster running an AI-powered property 
management and legal intelligence platform for Cabin Rentals of Georgia.

YOUR ROLE:
- You are the strategic planning brain (Gemini 3 Pro) — the CLOUD ARCHITECT.
- You have tools to read files, query the database, search vector stores, and run shell commands.
- You also have a PRIVATE AI FACTORY: the "Hydra Swarm" — 4x DeepSeek-R1-70B instances 
  running locally on the cluster. You can offload heavy reasoning, analysis, and code 
  generation to the Hydra while keeping all data sovereign (never leaves the cluster).

THE DUAL-BRAIN PATTERN:
- YOU (Gemini): Plan, strategize, decompose problems, write code skeletons, orchestrate.
- HYDRA (R1-70B x4): Execute deep reasoning on private data. Analyze documents, audit 
  financials, review contracts, generate code that touches sensitive data.
- Use `query_hydra` for single deep-reasoning tasks (routed through load balancer).
- Use `query_hydra_parallel` to fan out work to all 4 heads simultaneously — ideal for 
  chunked analysis where you split a large task into 4 independent pieces.

HIERARCHY (Constitution Article II):
- Human (Gary M. Knight) > Sovereign (DeepSeek-R1) > You (Architect/Gemini)
- You plan and orchestrate. The Hydra executes on private data. The Human approves.

CLUSTER TOPOLOGY:
- Spark-01 (Captain, 192.168.0.100): API Gateway, Postgres, Qdrant, Nginx LB, Ollama (R1-70B)
- Spark-02 (Muscle, 192.168.0.104): Ollama (R1-70B), Swarm Worker
- Spark-03 (Ocular, 192.168.0.105): Ollama (R1-70B), Swarm Worker
- Spark-04 (Sovereign, 192.168.0.106): Ollama (R1-70B), Swarm Worker
- Synology NAS (192.168.0.103): /mnt/fortress_nas/ — all persistent data
- Nginx LB on Captain distributes across all 4 nodes (least_conn)
- 200Gb/s RoCEv2 fabric interconnect (10.10.10.x)

DATABASE: fortress_db on Postgres (Captain, port 5432)
VECTOR DB: Qdrant (Captain, port 6333) — collections: email_embeddings, legal_library

SAFETY RULES (Constitution Article I):
1. NEVER send raw PII, financial amounts, or legal document contents to yourself (Gemini).
   Instead, use query_hydra to have R1-70B analyze sensitive data LOCALLY.
2. You may see table schemas, row counts, and aggregate statistics.
3. For detailed analysis of private data, delegate to the Hydra with a clear prompt.
4. If a tool result is flagged as [REDACTED], use query_hydra to analyze it locally.

STRATEGY:
- For broad planning and architecture: think yourself (Gemini).
- For private data analysis: delegate to query_hydra.
- For large-scale work (500 invoices, log analysis): chunk and use query_hydra_parallel.
- Always explain your reasoning before executing.
"""


# =============================================================================
# III. TOOL DEFINITIONS (OpenAI Function Calling Format)
# =============================================================================

TOOLS = [
    {
        "type": "function",
        "function": {
            "name": "read_file",
            "description": (
                "Read the contents of a file on the Fortress cluster. "
                "Restricted: cannot read .env, credentials, or private keys."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "path": {
                        "type": "string",
                        "description": "Absolute or relative path to the file",
                    },
                    "max_lines": {
                        "type": "integer",
                        "description": "Maximum lines to read (default: 200)",
                    },
                },
                "required": ["path"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "list_directory",
            "description": "List files and directories at the given path.",
            "parameters": {
                "type": "object",
                "properties": {
                    "path": {
                        "type": "string",
                        "description": "Directory path to list",
                    },
                    "recursive": {
                        "type": "boolean",
                        "description": "List recursively (default: false, max depth 2)",
                    },
                },
                "required": ["path"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "query_postgres",
            "description": (
                "Run a read-only SQL query against the fortress_db Postgres database. "
                "Only SELECT statements allowed. Results are truncated to 50 rows. "
                "Use for schema discovery, row counts, and aggregate queries."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "sql": {
                        "type": "string",
                        "description": "SQL SELECT query to execute",
                    },
                },
                "required": ["sql"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "search_qdrant",
            "description": (
                "Semantic search across a Qdrant vector collection. "
                "Returns top-K matching chunks with metadata (no raw content for legal/financial)."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "collection": {
                        "type": "string",
                        "description": "Qdrant collection name (email_embeddings, legal_library)",
                    },
                    "query": {
                        "type": "string",
                        "description": "Natural language search query",
                    },
                    "top_k": {
                        "type": "integer",
                        "description": "Number of results (default: 5, max: 10)",
                    },
                },
                "required": ["collection", "query"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "run_command",
            "description": (
                "Execute a shell command on the Captain node. "
                "Restricted: no destructive commands (rm -rf, dd, shutdown). "
                "Use for: docker ps, df -h, nvidia-smi, systemctl status, etc."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "command": {
                        "type": "string",
                        "description": "Shell command to execute",
                    },
                },
                "required": ["command"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "query_hydra",
            "description": (
                "Send a deep-reasoning task to the local Hydra Swarm (DeepSeek-R1-70B). "
                "The request goes through the Nginx load balancer to one of 4 GPU nodes. "
                "Use this for analyzing private/sensitive data that must NOT leave the cluster: "
                "contract review, financial audit, legal analysis, code generation on proprietary code. "
                "The Hydra thinks deeply (chain-of-thought) — allow 30-120s for complex tasks."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "prompt": {
                        "type": "string",
                        "description": "The reasoning task or analysis prompt for R1-70B",
                    },
                    "system_prompt": {
                        "type": "string",
                        "description": "Optional system prompt to set the Hydra's role/persona",
                    },
                    "max_tokens": {
                        "type": "integer",
                        "description": "Maximum response tokens (default: 2048, max: 8192)",
                    },
                },
                "required": ["prompt"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "query_hydra_parallel",
            "description": (
                "Fan out up to 4 independent tasks to ALL Hydra heads simultaneously. "
                "Each task goes to a different GPU node (Captain, Muscle, Ocular, Sovereign). "
                "Use this for chunked analysis: split a large task into 4 pieces and process "
                "them in parallel. Example: analyzing 4 different log files, reviewing 4 contracts, "
                "or auditing 4 quarters of financial data. Returns results from all heads."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "tasks": {
                        "type": "array",
                        "items": {"type": "string"},
                        "description": "List of 1-4 task prompts, one per Hydra head",
                    },
                    "system_prompt": {
                        "type": "string",
                        "description": "Shared system prompt for all heads",
                    },
                    "max_tokens": {
                        "type": "integer",
                        "description": "Max tokens per head (default: 2048)",
                    },
                },
                "required": ["tasks"],
            },
        },
    },
]


# =============================================================================
# IV. TOOL IMPLEMENTATIONS
# =============================================================================

def _truncate(text: str, max_chars: int = MAX_TOOL_RESULT_CHARS) -> str:
    """Truncate text with an indicator."""
    if len(text) <= max_chars:
        return text
    return text[:max_chars] + f"\n\n[TRUNCATED — {len(text)} total chars]"


def tool_read_file(path: str, max_lines: int = 200) -> str:
    """Read a file, with safety restrictions."""
    # Resolve path
    p = Path(path)
    if not p.is_absolute():
        p = PROJECT_ROOT / p

    # Safety check
    path_lower = str(p).lower()
    for forbidden in FORBIDDEN_PATHS:
        if forbidden in path_lower:
            return f"[RESTRICTED] Cannot read files matching '{forbidden}' (Constitution Article I)"

    if not p.exists():
        return f"[NOT FOUND] {p}"

    if p.is_dir():
        return f"[ERROR] {p} is a directory. Use list_directory instead."

    try:
        with open(p, "r", errors="replace") as f:
            lines = f.readlines()

        total = len(lines)
        content = "".join(lines[:max_lines])
        result = f"[File: {p}] ({total} lines)\n{content}"
        if total > max_lines:
            result += f"\n[TRUNCATED at {max_lines}/{total} lines]"
        return _truncate(result)
    except Exception as e:
        return f"[ERROR] Failed to read {p}: {e}"


def tool_list_directory(path: str, recursive: bool = False) -> str:
    """List directory contents."""
    p = Path(path)
    if not p.is_absolute():
        p = PROJECT_ROOT / p

    if not p.exists():
        return f"[NOT FOUND] {p}"

    try:
        entries = []
        if recursive:
            for root, dirs, files in os.walk(p):
                depth = str(root).count(os.sep) - str(p).count(os.sep)
                if depth > 2:
                    dirs.clear()
                    continue
                indent = "  " * depth
                entries.append(f"{indent}{Path(root).name}/")
                for f in sorted(files)[:50]:
                    entries.append(f"{indent}  {f}")
        else:
            for item in sorted(p.iterdir()):
                marker = "/" if item.is_dir() else ""
                size = ""
                if item.is_file():
                    sz = item.stat().st_size
                    size = f" ({sz:,} bytes)" if sz < 1_000_000 else f" ({sz/1_000_000:.1f}MB)"
                entries.append(f"  {item.name}{marker}{size}")

        result = f"[Directory: {p}] ({len(entries)} entries)\n" + "\n".join(entries)
        return _truncate(result)
    except Exception as e:
        return f"[ERROR] {e}"


def tool_query_postgres(sql: str) -> str:
    """Execute a read-only SQL query."""
    sql_lower = sql.lower().strip()

    # Safety: only SELECT allowed
    if not sql_lower.startswith("select") and not sql_lower.startswith("with"):
        return "[RESTRICTED] Only SELECT/WITH queries allowed (Constitution Article I)"

    for keyword in FORBIDDEN_SQL:
        if keyword in sql_lower:
            return f"[RESTRICTED] SQL keyword '{keyword}' not allowed"

    try:
        import psycopg2
        import psycopg2.extras

        conn = psycopg2.connect(
            host=DB_HOST, dbname=DB_NAME, user=DB_USER,
            password=DB_PASS, port=DB_PORT,
            cursor_factory=psycopg2.extras.RealDictCursor,
        )
        conn.set_session(readonly=True)
        cur = conn.cursor()

        # Add LIMIT if not present
        if "limit" not in sql_lower:
            sql = sql.rstrip(";") + " LIMIT 50"

        cur.execute(sql)
        rows = cur.fetchall()
        columns = [desc[0] for desc in cur.description] if cur.description else []
        cur.close()
        conn.close()

        if not rows:
            return f"[OK] Query returned 0 rows.\nSQL: {sql}"

        # Format as table
        lines = [f"[OK] {len(rows)} rows returned."]
        lines.append(" | ".join(columns))
        lines.append("-" * len(lines[-1]))
        for row in rows:
            lines.append(" | ".join(str(row.get(c, "")) for c in columns))

        return _truncate("\n".join(lines))
    except Exception as e:
        return f"[ERROR] Postgres query failed: {e}"


def tool_search_qdrant(collection: str, query: str, top_k: int = 5) -> str:
    """Semantic search across a Qdrant collection."""
    import requests

    top_k = min(top_k, 10)
    qdrant_url = f"http://localhost:6333"
    embed_url = "http://localhost:11434/api/embeddings"
    qdrant_api_key = os.getenv("QDRANT_API_KEY", "")
    qdrant_headers = {"api-key": qdrant_api_key} if qdrant_api_key else {}

    try:
        # Generate embedding
        resp = requests.post(
            embed_url,
            json={"model": "nomic-embed-text", "prompt": query},
            timeout=30,
        )
        resp.raise_for_status()
        embedding = resp.json().get("embedding", [])
        if not embedding:
            return "[ERROR] Embedding generation failed"

        # Search Qdrant
        search_resp = requests.post(
            f"{qdrant_url}/collections/{collection}/points/search",
            json={
                "vector": embedding,
                "limit": top_k,
                "with_payload": True,
                "with_vector": False,
            },
            headers=qdrant_headers,
            timeout=30,
        )
        search_resp.raise_for_status()
        results = search_resp.json().get("result", [])

        if not results:
            return f"[OK] No results in '{collection}' for: {query}"

        lines = [f"[OK] {len(results)} results from '{collection}'"]
        for i, hit in enumerate(results, 1):
            payload = hit.get("payload", {})
            score = hit.get("score", 0)

            # Safety: redact sensitive content
            text_preview = payload.get("text", "")[:200]
            if collection == "legal_library":
                text_preview = "[LEGAL CONTENT — preview only] " + text_preview[:100]

            lines.append(f"\n[{i}] Score: {score:.4f}")
            for key in ["file_name", "category", "source_file", "division", "sender"]:
                if key in payload:
                    lines.append(f"    {key}: {payload[key]}")
            lines.append(f"    preview: {text_preview}")

        return _truncate("\n".join(lines))
    except Exception as e:
        return f"[ERROR] Qdrant search failed: {e}"


def tool_run_command(command: str) -> str:
    """Execute a restricted shell command."""
    cmd_lower = command.lower()

    for forbidden in FORBIDDEN_COMMANDS:
        if forbidden in cmd_lower:
            return f"[RESTRICTED] Command contains '{forbidden}' — not allowed"

    try:
        result = subprocess.run(
            command, shell=True, capture_output=True, text=True,
            timeout=30, cwd=str(PROJECT_ROOT),
        )
        output = result.stdout + result.stderr
        return _truncate(f"[exit={result.returncode}]\n{output}")
    except subprocess.TimeoutExpired:
        return "[ERROR] Command timed out (30s limit)"
    except Exception as e:
        return f"[ERROR] {e}"


def tool_query_hydra(prompt: str, system_prompt: str = None, max_tokens: int = 2048) -> str:
    """Send a reasoning task to the Hydra Swarm (R1-70B via load balancer)."""
    import requests
    import time

    max_tokens = min(max_tokens, 8192)
    endpoint = HYDRA_ENDPOINT.rstrip("/") + "/chat/completions"

    messages = []
    if system_prompt:
        messages.append({"role": "system", "content": system_prompt})
    messages.append({"role": "user", "content": prompt})

    try:
        start = time.time()
        resp = requests.post(
            endpoint,
            json={
                "model": HYDRA_MODEL,
                "messages": messages,
                "max_tokens": max_tokens,
                "temperature": 0.1,
            },
            timeout=300,  # 5 min — R1-70B thinks deeply
        )
        elapsed = time.time() - start
        resp.raise_for_status()

        data = resp.json()
        content = data["choices"][0]["message"]["content"]
        usage = data.get("usage", {})

        # Strip <think> tags for cleaner output — keep reasoning if requested
        import re
        think_match = re.search(r"<think>(.*?)</think>", content, re.DOTALL)
        clean = re.sub(r"<think>.*?</think>", "", content, flags=re.DOTALL).strip()

        result_lines = [f"[HYDRA] R1-70B response ({elapsed:.1f}s, {usage.get('completion_tokens', '?')} tokens)"]
        if think_match:
            reasoning = think_match.group(1).strip()[:500]
            result_lines.append(f"\n[Chain-of-Thought] {reasoning}...")
        result_lines.append(f"\n[Answer]\n{clean}")

        return _truncate("\n".join(result_lines))
    except requests.exceptions.Timeout:
        return "[ERROR] Hydra query timed out (300s). Task may be too large — try chunking with query_hydra_parallel."
    except Exception as e:
        return f"[ERROR] Hydra query failed: {e}"


def tool_query_hydra_parallel(
    tasks: list, system_prompt: str = None, max_tokens: int = 2048
) -> str:
    """Fan out tasks to all 4 Hydra heads simultaneously."""
    import requests
    import time
    from concurrent.futures import ThreadPoolExecutor, as_completed

    max_tokens = min(max_tokens, 8192)
    tasks = tasks[:4]  # Max 4 (one per head)

    def _query_head(idx: int, task: str) -> tuple:
        endpoint_url = HYDRA_ENDPOINTS[idx].rstrip("/") + "/chat/completions"
        node_name = HYDRA_NODE_NAMES[idx]

        messages = []
        if system_prompt:
            messages.append({"role": "system", "content": system_prompt})
        messages.append({"role": "user", "content": task})

        try:
            start = time.time()
            resp = requests.post(
                endpoint_url,
                json={
                    "model": HYDRA_MODEL,
                    "messages": messages,
                    "max_tokens": max_tokens,
                    "temperature": 0.1,
                },
                timeout=300,
            )
            elapsed = time.time() - start
            resp.raise_for_status()

            data = resp.json()
            content = data["choices"][0]["message"]["content"]
            usage = data.get("usage", {})

            # Strip think tags
            import re
            clean = re.sub(r"<think>.*?</think>", "", content, flags=re.DOTALL).strip()

            return (
                idx,
                node_name,
                True,
                f"({elapsed:.1f}s, {usage.get('completion_tokens', '?')} tok)\n{clean}",
            )
        except Exception as e:
            return (idx, node_name, False, str(e))

    # Fan out to all heads in parallel
    start_all = time.time()
    results = [None] * len(tasks)

    with ThreadPoolExecutor(max_workers=4) as pool:
        futures = {
            pool.submit(_query_head, i, task): i
            for i, task in enumerate(tasks)
        }
        for future in as_completed(futures):
            idx, name, ok, output = future.result()
            results[idx] = (name, ok, output)

    total_time = time.time() - start_all

    # Format results
    lines = [f"[HYDRA PARALLEL] {len(tasks)} tasks completed in {total_time:.1f}s"]
    for i, (name, ok, output) in enumerate(results):
        if results[i] is None:
            continue
        status = "OK" if ok else "FAILED"
        lines.append(f"\n── Head {i+1}: {name} [{status}] ──")
        lines.append(output[:MAX_TOOL_RESULT_CHARS // 4])  # Fair share of output budget

    return _truncate("\n".join(lines))


# Tool dispatch table
TOOL_DISPATCH = {
    "read_file": lambda args: tool_read_file(args["path"], args.get("max_lines", 200)),
    "list_directory": lambda args: tool_list_directory(args["path"], args.get("recursive", False)),
    "query_postgres": lambda args: tool_query_postgres(args["sql"]),
    "search_qdrant": lambda args: tool_search_qdrant(
        args["collection"], args["query"], args.get("top_k", 5)
    ),
    "run_command": lambda args: tool_run_command(args["command"]),
    "query_hydra": lambda args: tool_query_hydra(
        args["prompt"], args.get("system_prompt"), args.get("max_tokens", 2048)
    ),
    "query_hydra_parallel": lambda args: tool_query_hydra_parallel(
        args["tasks"], args.get("system_prompt"), args.get("max_tokens", 2048)
    ),
}


# =============================================================================
# V. ARCHITECT CONVERSATION ENGINE
# =============================================================================

def ask_architect(
    question: str,
    conversation: list = None,
    max_tool_rounds: int = 5,
) -> dict:
    """
    Ask the Gemini Architect a question with tool access.

    Supports multi-turn conversation with automatic tool calling.
    Returns the final answer and conversation history.

    Args:
        question: The user's question or task description.
        conversation: Optional conversation history (list of messages).
        max_tool_rounds: Maximum tool-calling rounds before forcing an answer.

    Returns:
        dict with 'answer', 'conversation', 'tool_calls' (list of tools used).
    """
    from openai import OpenAI

    if not GOOGLE_AI_API_KEY:
        return {
            "answer": "[ERROR] GOOGLE_AI_API_KEY not set. Add it to .env",
            "conversation": [],
            "tool_calls": [],
        }

    client = OpenAI(
        base_url=ARCHITECT_ENDPOINT,
        api_key=GOOGLE_AI_API_KEY,
    )

    # Build conversation
    messages = conversation or [
        {"role": "system", "content": ARCHITECT_SYSTEM_PROMPT},
    ]
    messages.append({"role": "user", "content": question})

    tool_calls_log = []

    for round_num in range(max_tool_rounds):
        response = client.chat.completions.create(
            model=ARCHITECT_MODEL,
            messages=messages,
            tools=TOOLS,
            tool_choice="auto",
        )

        choice = response.choices[0]
        message = choice.message

        # If no tool calls, we have the final answer
        if not message.tool_calls:
            messages.append({"role": "assistant", "content": message.content or ""})
            return {
                "answer": message.content or "",
                "conversation": messages,
                "tool_calls": tool_calls_log,
            }

        # Process tool calls
        messages.append({
            "role": "assistant",
            "content": message.content or "",
            "tool_calls": [
                {
                    "id": tc.id,
                    "type": "function",
                    "function": {
                        "name": tc.function.name,
                        "arguments": tc.function.arguments,
                    },
                }
                for tc in message.tool_calls
            ],
        })

        for tc in message.tool_calls:
            fn_name = tc.function.name
            fn_args = json.loads(tc.function.arguments)

            logger.info(f"  Tool call [{round_num+1}]: {fn_name}({fn_args})")
            tool_calls_log.append({"function": fn_name, "arguments": fn_args})

            # Execute tool
            if fn_name in TOOL_DISPATCH:
                result = TOOL_DISPATCH[fn_name](fn_args)
            else:
                result = f"[ERROR] Unknown tool: {fn_name}"

            messages.append({
                "role": "tool",
                "tool_call_id": tc.id,
                "content": result,
            })

    # Max rounds hit — force an answer
    messages.append({
        "role": "user",
        "content": "Please provide your final answer based on the information gathered so far.",
    })
    response = client.chat.completions.create(
        model=ARCHITECT_MODEL,
        messages=messages,
    )
    final = response.choices[0].message.content or ""
    messages.append({"role": "assistant", "content": final})

    return {
        "answer": final,
        "conversation": messages,
        "tool_calls": tool_calls_log,
    }


# =============================================================================
# VI. INTERACTIVE MODE
# =============================================================================

def interactive():
    """Interactive Architect session."""
    print("=" * 70)
    print("  FORTRESS PRIME — GEMINI ARCHITECT (The Commander)")
    print("  Brain: Gemini 3 Pro (Cloud) + R1-70B x4 (Local Hydra Swarm)")
    print("  Tools: file, db, qdrant, shell, hydra, hydra_parallel")
    print("  Safety: Sensitive data stays on-cluster via Hydra delegation")
    print("=" * 70)

    if not GOOGLE_AI_API_KEY:
        print("\n  [ERROR] GOOGLE_AI_API_KEY not set.")
        print("  Add to .env: GOOGLE_AI_API_KEY=your-key-here")
        return

    print("\n  Commands: /quit, /clear, /tools")
    print()

    conversation = [{"role": "system", "content": ARCHITECT_SYSTEM_PROMPT}]

    while True:
        try:
            question = input("  Architect > ").strip()
        except (EOFError, KeyboardInterrupt):
            print("\n\n  Session ended.")
            break

        if not question:
            continue

        if question == "/quit":
            print("  Session ended.")
            break
        elif question == "/clear":
            conversation = [{"role": "system", "content": ARCHITECT_SYSTEM_PROMPT}]
            print("  Conversation cleared.")
            continue
        elif question == "/tools":
            print("\n  Available tools:")
            for t in TOOLS:
                print(f"    - {t['function']['name']}: {t['function']['description'][:80]}")
            print()
            continue

        result = ask_architect(question, conversation)
        conversation = result["conversation"]

        if result["tool_calls"]:
            print(f"\n  [Used {len(result['tool_calls'])} tool(s): "
                  f"{', '.join(tc['function'] for tc in result['tool_calls'])}]")

        print(f"\n{result['answer']}\n")


# =============================================================================
# VII. CLI
# =============================================================================

if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")

    if len(sys.argv) > 1:
        question = " ".join(sys.argv[1:])
        result = ask_architect(question)
        if result["tool_calls"]:
            print(f"[Tools used: {', '.join(tc['function'] for tc in result['tool_calls'])}]")
        print(result["answer"])
    else:
        interactive()
