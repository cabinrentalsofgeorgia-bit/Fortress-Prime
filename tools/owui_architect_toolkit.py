"""
title: Fortress Architect Toolkit
author: Fortress Prime
author_url: https://fortress.crog-ai.com
description: Gives AI models eyes and hands on the Fortress cluster — read files, query Postgres, search Qdrant vectors, run shell commands, and dispatch reasoning tasks to the Hydra Swarm (DeepSeek-R1-70B x4).
requirements: psycopg2-binary, requests
version: 1.0.0
licence: MIT
"""

import os
import sys
import re
import json
import subprocess
from pathlib import Path
from typing import Callable, Any, Optional

from pydantic import BaseModel, Field

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
from config import NGINX_LB_URL

# =============================================================================
# SAFETY CONSTANTS
# =============================================================================

FORBIDDEN_PATHS = {".env", "credentials", "secrets", ".ssh", "private_key", ".key", ".pem"}
FORBIDDEN_SQL = {"insert", "update", "delete", "drop", "alter", "create", "truncate", "grant", "revoke"}
FORBIDDEN_COMMANDS = {"rm -rf", "mkfs", "dd if=", "shutdown", "reboot", "> /dev/", "chmod 777", "curl|sh", "wget|sh"}
MAX_RESULT_CHARS = 6000  # Reduced from 12k to prevent context window overflow in long sessions


def _truncate(text: str, limit: int = MAX_RESULT_CHARS) -> str:
    if len(text) <= limit:
        return text
    return text[:limit] + f"\n\n[TRUNCATED — {len(text):,} total chars, showing first {limit:,}]"


# Host-to-container path translation table
_PATH_REWRITES = [
    ("/home/admin/Fortress-Prime/", "/fortress/"),
    ("/home/admin/Fortress-Prime", "/fortress"),
    ("/mnt/fortress_nas/", "/nas/"),
    ("/mnt/fortress_nas", "/nas"),
]


def _resolve_path(raw_path: str) -> str:
    """Translate host paths to container paths automatically."""
    for host_prefix, container_prefix in _PATH_REWRITES:
        if raw_path.startswith(host_prefix):
            return container_prefix + raw_path[len(host_prefix):]
    return raw_path


# =============================================================================
# TOOLS CLASS (registered with Open WebUI)
# =============================================================================

class Tools:
    """
    Fortress Architect Toolkit — gives AI models operational access to the
    Fortress Prime 4-node DGX Spark cluster.

    Safety: All tools enforce read-only semantics where applicable.
    Constitution Article I: No PII/financial data leaves the cluster.
    """

    class Valves(BaseModel):
        db_host: str = Field(default="localhost", description="Postgres host")
        db_port: int = Field(default=5432, description="Postgres port")
        db_name: str = Field(default="fortress_db", description="Postgres database name")
        db_user: str = Field(default="miner_bot", description="Postgres user")
        db_pass: str = Field(default="", description="Postgres password (empty for local trust)")
        hydra_endpoint: str = Field(
            default=f"{NGINX_LB_URL}/hydra/v1",
            description="Hydra R1-70B endpoint (dedicated Nginx route to 3 GPU nodes with 600s timeout)",
        )
        hydra_model: str = Field(
            default="deepseek-r1:70b",
            description="Hydra model name for deep reasoning tasks",
        )
        qdrant_url: str = Field(
            default="http://localhost:6333",
            description="Qdrant vector database URL",
        )
        qdrant_api_key: str = Field(
            default="",
            description="Qdrant API key (set after lockdown). Leave empty if no auth.",
        )
        embed_url: str = Field(
            default="http://localhost:11434/api/embeddings",
            description="Ollama embeddings endpoint for vector search",
        )
        project_root: str = Field(
            default="/fortress",
            description="Fortress-Prime project root inside the container",
        )
        nas_root: str = Field(
            default="/nas",
            description="NAS mount point inside the container",
        )
        command_timeout: int = Field(
            default=30,
            description="Shell command timeout in seconds",
        )

    def __init__(self):
        self.valves = self.Valves()

    # ─────────────────────────────────────────────────────────────────
    # TOOL 1: read_file
    # ─────────────────────────────────────────────────────────────────

    async def read_file(
        self,
        file_path: str,
        max_lines: int = 200,
        __event_emitter__: Callable[[dict], Any] = None,
    ) -> str:
        """
        Read a file from the Fortress cluster filesystem. Use this to inspect
        source code, config files, CSV reports, logs, or any text file.
        Files are available under /fortress (project root, maps to /home/admin/Fortress-Prime)
        and /nas (NAS storage, maps to /mnt/fortress_nas).
        Host paths like /home/admin/Fortress-Prime/... are automatically translated.
        Restricted: cannot read .env, credentials, or private key files.

        :param file_path: Path to the file (e.g. /fortress/config.py, /fortress/audit_sample.csv, or /nas/backups/report.txt)
        :param max_lines: Maximum number of lines to return (default 200)
        :return: File contents as text
        """
        # Auto-translate host paths to container paths
        file_path = _resolve_path(file_path)

        if __event_emitter__:
            await __event_emitter__({"type": "status", "data": {"description": f"Reading {file_path}...", "done": False}})

        p = Path(file_path)

        # Safety: block sensitive files
        path_lower = str(p).lower()
        for forbidden in FORBIDDEN_PATHS:
            if forbidden in path_lower:
                result = f"[RESTRICTED] Cannot read files matching '{forbidden}' — Constitution Article I"
                if __event_emitter__:
                    await __event_emitter__({"type": "status", "data": {"description": "Blocked: restricted file", "done": True}})
                return result

        if not p.exists():
            if __event_emitter__:
                await __event_emitter__({"type": "status", "data": {"description": "File not found", "done": True}})
            return f"[NOT FOUND] {p}"

        if p.is_dir():
            if __event_emitter__:
                await __event_emitter__({"type": "status", "data": {"description": "Path is a directory", "done": True}})
            return f"[ERROR] {p} is a directory. Use list_directory instead."

        try:
            with open(p, "r", errors="replace") as f:
                lines = f.readlines()
            total = len(lines)
            content = "".join(lines[:max_lines])
            result = f"[File: {p}] ({total} lines)\n{content}"
            if total > max_lines:
                result += f"\n[TRUNCATED at {max_lines}/{total} lines]"

            if __event_emitter__:
                await __event_emitter__({"type": "status", "data": {"description": f"Read {total} lines", "done": True}})
            return _truncate(result)
        except Exception as e:
            if __event_emitter__:
                await __event_emitter__({"type": "status", "data": {"description": f"Error: {e}", "done": True}})
            return f"[ERROR] Failed to read {p}: {e}"

    # ─────────────────────────────────────────────────────────────────
    # TOOL 2: list_directory
    # ─────────────────────────────────────────────────────────────────

    async def list_directory(
        self,
        directory_path: str,
        recursive: bool = False,
        __event_emitter__: Callable[[dict], Any] = None,
    ) -> str:
        """
        List files and directories at a given path on the Fortress cluster.
        Use this to explore the project structure, find files, or check
        what's on the NAS. Paths: /fortress (project root, maps to /home/admin/Fortress-Prime)
        and /nas (NAS storage, maps to /mnt/fortress_nas).
        Host paths are automatically translated.

        :param directory_path: Directory to list (e.g. /fortress/src or /nas/backups)
        :param recursive: If true, list recursively up to depth 2
        :return: Directory listing with file sizes
        """
        # Auto-translate host paths to container paths
        directory_path = _resolve_path(directory_path)

        if __event_emitter__:
            await __event_emitter__({"type": "status", "data": {"description": f"Listing {directory_path}...", "done": False}})

        p = Path(directory_path)
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
                    for fn in sorted(files)[:50]:
                        entries.append(f"{indent}  {fn}")
            else:
                for item in sorted(p.iterdir()):
                    marker = "/" if item.is_dir() else ""
                    size = ""
                    if item.is_file():
                        sz = item.stat().st_size
                        size = f" ({sz:,} bytes)" if sz < 1_000_000 else f" ({sz / 1_000_000:.1f}MB)"
                    entries.append(f"  {item.name}{marker}{size}")

            result = f"[Directory: {p}] ({len(entries)} entries)\n" + "\n".join(entries)
            if __event_emitter__:
                await __event_emitter__({"type": "status", "data": {"description": f"{len(entries)} entries", "done": True}})
            return _truncate(result)
        except Exception as e:
            return f"[ERROR] {e}"

    # ─────────────────────────────────────────────────────────────────
    # TOOL 3: query_database
    # ─────────────────────────────────────────────────────────────────

    async def query_database(
        self,
        sql_query: str,
        __event_emitter__: Callable[[dict], Any] = None,
    ) -> str:
        """
        Execute a read-only SQL query against the Fortress Postgres database (fortress_db).
        Only SELECT and WITH (CTE) queries are allowed. Results are limited to 50 rows.

        IMPORTANT: Always check the actual schema first with:
          SELECT schemaname, tablename FROM pg_tables WHERE schemaname NOT IN ('pg_catalog','information_schema');
        Or get columns for a specific table with:
          SELECT column_name, data_type FROM information_schema.columns WHERE table_schema='X' AND table_name='Y';

        DATABASE SCHEMA MAP (populated tables):
        ── public (main) ──
          finance_invoices (6823 rows): id, vendor(text), amount(numeric), date, category, source_email_id
          email_archive (57231 rows): id, sender, subject, body, date, division, ...
          general_ledger (25569 rows), revenue_ledger (3488 rows): adjusted_rate, base_rate, alpha (NOT amount!)
          guest_leads (13691 rows), market_intel (25716 rows), real_estate_intel (8133 rows)
          sender_registry (8274 rows), properties (36 rows), ops_tasks (66 rows)
          legal_intel (5877 rows), sales_intel (17598 rows), model_telemetry (994633 rows)
        ── finance ──
          vendor_classifications (817 rows): id, vendor_pattern(text), vendor_label(text), classification(text),
            is_revenue(bool), is_expense(bool), titan_notes(text), classified_by(text)
            Classifications: CROG_INTERNAL, REAL_BUSINESS, CONTRACTOR, OPERATIONAL_EXPENSE,
            FINANCIAL_SERVICE, PROFESSIONAL_SERVICE, GOVERNMENT, FAMILY_INTERNAL, NOISE, UNKNOWN
        ── division_a (Holding) ──
          chart_of_accounts (34), transactions (4)
        ── division_b (CROG Property) ──
          chart_of_accounts (62), general_ledger (5983), journal_entries (2991), transactions (9)
        ── engineering ──
          drawings (1766), mep_systems (401), permits (14), projects (13)
        ── hedge_fund ──
          market_signals (1105), watchlist (431), extraction_log (1602)
        ── intelligence ──
          entities (180), relationships (213), golden_reasoning (4), titan_traces (10)

        CONTRACTOR SPEND QUERY PATTERN:
          To get contractor spend, JOIN finance.vendor_classifications with public.finance_invoices:
          SELECT vc.vendor_label, SUM(fi.amount) as total_spend, COUNT(*) as tx_count
          FROM finance.vendor_classifications vc
          JOIN public.finance_invoices fi ON fi.vendor LIKE vc.vendor_pattern || '%'
          WHERE vc.classification = 'CONTRACTOR'
          GROUP BY vc.vendor_label ORDER BY total_spend DESC;

        WARNING: revenue_ledger has adjusted_rate/base_rate/alpha — NOT an 'amount' column.
        WARNING: finance_invoices.amount values are inflated by AI email extraction from emails.

        :param sql_query: SQL SELECT or WITH query to execute
        :return: Query results as a formatted table
        """
        if __event_emitter__:
            await __event_emitter__({"type": "status", "data": {"description": "Querying database...", "done": False}})

        import psycopg2
        import psycopg2.extras

        sql_lower = sql_query.lower().strip()

        # Safety: only SELECT/WITH
        if not sql_lower.startswith("select") and not sql_lower.startswith("with"):
            return "[RESTRICTED] Only SELECT/WITH queries allowed — Constitution Article I"

        for keyword in FORBIDDEN_SQL:
            if keyword in sql_lower:
                return f"[RESTRICTED] SQL keyword '{keyword}' not allowed"

        try:
            conn = psycopg2.connect(
                host=self.valves.db_host,
                dbname=self.valves.db_name,
                user=self.valves.db_user,
                password=self.valves.db_pass,
                port=self.valves.db_port,
            )
            conn.set_session(readonly=True)
            cur = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)

            # Add LIMIT if not present (cap at 25 to reduce context window usage)
            if "limit" not in sql_lower:
                sql_query = sql_query.rstrip(";") + " LIMIT 25"

            cur.execute(sql_query)
            rows = cur.fetchall()
            columns = [desc[0] for desc in cur.description] if cur.description else []
            cur.close()
            conn.close()

            if not rows:
                if __event_emitter__:
                    await __event_emitter__({"type": "status", "data": {"description": "0 rows returned", "done": True}})
                return f"[OK] Query returned 0 rows.\nSQL: {sql_query}"

            # Format as table
            lines = [f"[OK] {len(rows)} rows returned."]
            lines.append(" | ".join(columns))
            lines.append("-" * len(lines[-1]))
            for row in rows:
                lines.append(" | ".join(str(row.get(c, "")) for c in columns))

            if __event_emitter__:
                await __event_emitter__({"type": "status", "data": {"description": f"{len(rows)} rows returned", "done": True}})
            return _truncate("\n".join(lines))

        except Exception as e:
            if __event_emitter__:
                await __event_emitter__({"type": "status", "data": {"description": f"Query failed", "done": True}})
            return f"[ERROR] Postgres query failed: {e}"

    # ─────────────────────────────────────────────────────────────────
    # TOOL 4: search_vectors
    # ─────────────────────────────────────────────────────────────────

    async def search_vectors(
        self,
        collection: str,
        query: str,
        top_k: int = 5,
        __event_emitter__: Callable[[dict], Any] = None,
    ) -> str:
        """
        Perform semantic search across a Qdrant vector collection on the Fortress cluster.
        Use this to find documents, emails, code, or legal content by meaning rather than keywords.
        Available collections:
          - fortress_knowledge (17K+ vectors) — PDFs, code, configs, docs from project + NAS
          - email_embeddings (56K vectors) — 57K classified emails
          - legal_library — legal documents and case files
        Use fortress_knowledge for general document/code/config questions.
        Use email_embeddings for email-specific searches.

        :param collection: Qdrant collection name (email_embeddings or legal_library)
        :param query: Natural language search query (e.g. "property tax dispute 2024")
        :param top_k: Number of results to return (default 5, max 10)
        :return: Matching documents with scores and metadata
        """
        import requests

        if __event_emitter__:
            await __event_emitter__({"type": "status", "data": {"description": f"Searching {collection}...", "done": False}})

        top_k = min(top_k, 10)

        try:
            # Generate embedding
            resp = requests.post(
                self.valves.embed_url,
                json={"model": "nomic-embed-text", "prompt": query},
                timeout=30,
            )
            resp.raise_for_status()
            embedding = resp.json().get("embedding", [])
            if not embedding:
                return "[ERROR] Embedding generation failed"

            # Search Qdrant (auth header if API key configured)
            qdrant_headers = {"api-key": self.valves.qdrant_api_key} if self.valves.qdrant_api_key else {}
            search_resp = requests.post(
                f"{self.valves.qdrant_url}/collections/{collection}/points/search",
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
                if __event_emitter__:
                    await __event_emitter__({"type": "status", "data": {"description": "No results", "done": True}})
                return f"[OK] No results in '{collection}' for: {query}"

            lines = [f"[OK] {len(results)} results from '{collection}'"]
            for i, hit in enumerate(results, 1):
                payload = hit.get("payload", {})
                score = hit.get("score", 0)

                # Safety: redact sensitive content for legal collection
                text_preview = payload.get("text", "")[:200]
                if collection == "legal_library":
                    text_preview = "[LEGAL CONTENT — preview only] " + text_preview[:100]

                lines.append(f"\n[{i}] Score: {score:.4f}")
                for key in ["file_name", "category", "source_file", "division", "sender", "subject", "date"]:
                    if key in payload:
                        lines.append(f"    {key}: {payload[key]}")
                lines.append(f"    preview: {text_preview}")

            if __event_emitter__:
                await __event_emitter__({"type": "status", "data": {"description": f"{len(results)} results found", "done": True}})
            return _truncate("\n".join(lines))

        except Exception as e:
            if __event_emitter__:
                await __event_emitter__({"type": "status", "data": {"description": f"Search failed", "done": True}})
            return f"[ERROR] Qdrant search failed: {e}"

    # ─────────────────────────────────────────────────────────────────
    # TOOL 5: run_command
    # ─────────────────────────────────────────────────────────────────

    async def run_command(
        self,
        command: str,
        __event_emitter__: Callable[[dict], Any] = None,
    ) -> str:
        """
        Execute a shell command on the Fortress Captain node.
        Use for system diagnostics: docker ps, nvidia-smi, df -h, uptime, free -h,
        checking service status, listing running containers, or inspecting logs.
        Restricted: no destructive commands (rm -rf, dd, shutdown, reboot).

        :param command: Shell command to execute (e.g. "docker ps" or "nvidia-smi")
        :return: Command output (stdout + stderr)
        """
        if __event_emitter__:
            await __event_emitter__({"type": "status", "data": {"description": f"Running: {command[:50]}...", "done": False}})

        cmd_lower = command.lower()
        for forbidden in FORBIDDEN_COMMANDS:
            if forbidden in cmd_lower:
                return f"[RESTRICTED] Command contains '{forbidden}' — not allowed"

        try:
            result = subprocess.run(
                command,
                shell=True,
                capture_output=True,
                text=True,
                timeout=self.valves.command_timeout,
                cwd=self.valves.project_root,
            )
            output = result.stdout + result.stderr
            if __event_emitter__:
                await __event_emitter__({"type": "status", "data": {"description": f"Exit code: {result.returncode}", "done": True}})
            return _truncate(f"[exit={result.returncode}]\n{output}")

        except subprocess.TimeoutExpired:
            return f"[ERROR] Command timed out ({self.valves.command_timeout}s limit)"
        except Exception as e:
            return f"[ERROR] {e}"

    # ─────────────────────────────────────────────────────────────────
    # TOOL 6: query_hydra
    # ─────────────────────────────────────────────────────────────────

    async def query_hydra(
        self,
        prompt: str,
        system_prompt: str = "",
        __event_emitter__: Callable[[dict], Any] = None,
    ) -> str:
        """
        Send a deep reasoning task to the local Hydra — 3x DeepSeek-R1-70B
        instances (Muscle, Ocular, Sovereign) via a dedicated Nginx route.
        R1-70B runs at ~5 tok/s with deep chain-of-thought reasoning.
        Use for tasks requiring analysis of PRIVATE data that must not leave
        the cluster: contract review, financial audit, legal analysis.

        IMPORTANT: Keep prompts focused. R1-70B thinks deeply — broad prompts
        (e.g., "analyze 15 vendors") generate very long responses that risk
        timeout. For multi-item analysis, call Hydra once per item or provide
        a concise, structured prompt.

        :param prompt: The reasoning task or analysis prompt for R1-70B
        :param system_prompt: Optional system prompt to set the Hydra's role
        :return: R1-70B's analysis with chain-of-thought summary
        """
        import requests
        import time

        if __event_emitter__:
            await __event_emitter__({"type": "status", "data": {"description": "Hydra thinking (R1-70B @ ~5 tok/s)...", "done": False}})

        endpoint = self.valves.hydra_endpoint.rstrip("/") + "/chat/completions"

        messages = []
        if system_prompt:
            messages.append({"role": "system", "content": system_prompt})
        messages.append({"role": "user", "content": prompt})

        try:
            start = time.time()
            resp = requests.post(
                endpoint,
                json={
                    "model": self.valves.hydra_model,
                    "messages": messages,
                    "max_tokens": 4096,
                    "temperature": 0.1,
                },
                timeout=600,
            )
            elapsed = time.time() - start
            resp.raise_for_status()

            data = resp.json()
            content = data["choices"][0]["message"]["content"]
            usage = data.get("usage", {})

            # Strip <think> tags, extract reasoning summary
            think_match = re.search(r"<think>(.*?)</think>", content, re.DOTALL)
            clean = re.sub(r"<think>.*?</think>", "", content, flags=re.DOTALL).strip()

            result_lines = [
                f"[HYDRA] R1-70B response ({elapsed:.1f}s, {usage.get('completion_tokens', '?')} tokens)"
            ]
            if think_match:
                reasoning = think_match.group(1).strip()[:500]
                result_lines.append(f"\n[Chain-of-Thought Summary] {reasoning}...")
            result_lines.append(f"\n[Answer]\n{clean}")

            if __event_emitter__:
                await __event_emitter__({"type": "status", "data": {"description": f"Hydra responded ({elapsed:.1f}s)", "done": True}})
            return _truncate("\n".join(result_lines))

        except requests.exceptions.Timeout:
            if __event_emitter__:
                await __event_emitter__({"type": "status", "data": {"description": "Hydra timed out (600s)", "done": True}})
            return "[ERROR] Hydra query timed out (600s). Break the task into smaller, focused prompts — R1-70B runs at ~5 tok/s."
        except Exception as e:
            if __event_emitter__:
                await __event_emitter__({"type": "status", "data": {"description": f"Hydra error", "done": True}})
            return f"[ERROR] Hydra query failed: {e}"

    # =========================================================================
    # AGENTIC TOOLS (Autonomous Swarm Directive — Pillar 2)
    # =========================================================================

    async def analyze_container_logs(
        self,
        container_name: str,
        lines: int = 100,
        __event_emitter__: Callable[[dict], Any] = None,
    ) -> str:
        """
        Pull recent Docker container logs and extract structured anomalies.
        Returns JSON with anomalies, severity, and suggested actions.
        Use this when investigating container crashes, health failures, or performance issues.
        """
        if __event_emitter__:
            await __event_emitter__({"type": "status", "data": {"description": f"Pulling {lines} log lines from {container_name}...", "done": False}})

        safe_name = re.sub(r"[^a-zA-Z0-9_\-.]", "", container_name)
        if not safe_name:
            return "[ERROR] Invalid container name after sanitization."
        try:
            rc = subprocess.run(
                ["docker", "logs", "--tail", str(min(lines, 500)), safe_name],
                capture_output=True, text=True, timeout=15,
            )
        except subprocess.TimeoutExpired:
            return f"[ERROR] Timed out pulling logs from {safe_name} (15s limit)."
        except Exception as e:
            return f"[ERROR] Failed to pull logs from {safe_name}: {e}"
        logs = (rc.stdout + rc.stderr).strip()
        if not logs:
            return f"[INFO] No logs found for container {safe_name}."

        error_lines = []
        warn_lines = []
        for line in logs.splitlines():
            ll = line.lower()
            if any(k in ll for k in ("error", "fatal", "critical", "exception", "traceback", "panic")):
                error_lines.append(line.strip())
            elif any(k in ll for k in ("warn", "timeout", "retry", "refused", "denied")):
                warn_lines.append(line.strip())

        result = {
            "container": safe_name,
            "total_lines": len(logs.splitlines()),
            "error_count": len(error_lines),
            "warning_count": len(warn_lines),
            "errors": error_lines[-10:],
            "warnings": warn_lines[-10:],
            "severity": "critical" if len(error_lines) > 5 else "warning" if error_lines else "healthy",
            "suggested_action": (
                "Investigate error patterns and consider container restart"
                if error_lines else "No anomalies detected"
            ),
        }

        if __event_emitter__:
            await __event_emitter__({"type": "status", "data": {"description": f"Analysis complete: {result['severity']}", "done": True}})
        return _truncate(json.dumps(result, indent=2))

    async def diagnose_system_health(
        self,
        __event_emitter__: Callable[[dict], Any] = None,
    ) -> str:
        """
        Run a full cluster health diagnostic (containers, GPU, NAS mount) and return
        a structured report the AI can reason over. Equivalent to a captain omnibus probe.
        """
        if __event_emitter__:
            await __event_emitter__({"type": "status", "data": {"description": "Running system health probe...", "done": False}})

        sections = {}
        containers = {}

        try:
            r = subprocess.run(
                ["docker", "ps", "--format", "{{.Names}}|{{.Status}}"],
                capture_output=True, text=True, timeout=10,
            )
            for line in r.stdout.strip().splitlines():
                parts = line.split("|", 1)
                if len(parts) == 2:
                    containers[parts[0]] = parts[1]
            sections["containers"] = containers
        except Exception as e:
            sections["containers"] = {"error": str(e)}

        try:
            r2 = subprocess.run(
                ["nvidia-smi", "--query-gpu=name,temperature.gpu,utilization.gpu,memory.used,memory.total",
                 "--format=csv,noheader,nounits"],
                capture_output=True, text=True, timeout=10,
            )
            sections["gpu"] = r2.stdout.strip() if r2.returncode == 0 else "unavailable"
        except Exception as e:
            sections["gpu"] = f"probe_failed: {e}"

        try:
            r3 = subprocess.run(
                ["findmnt", "-T", "/mnt/fortress_nas", "-n", "-o", "SOURCE,FSTYPE"],
                capture_output=True, text=True, timeout=5,
            )
            nas_info = r3.stdout.strip()
            sections["nas_mount"] = nas_info if nas_info else "not_mounted"
        except Exception as e:
            sections["nas_mount"] = f"probe_failed: {e}"

        healthy = sum(1 for s in containers.values() if isinstance(s, str) and "healthy" in s.lower())
        total = len(containers)
        sections["summary"] = {
            "total_containers": total,
            "healthy_containers": healthy,
            "nas_status": "ok" if "nfs" in str(sections.get("nas_mount", "")).lower() else "degraded",
        }

        if __event_emitter__:
            await __event_emitter__({"type": "status", "data": {"description": f"Health probe complete: {healthy}/{total} healthy", "done": True}})
        return _truncate(json.dumps(sections, indent=2))

    async def trigger_ooda_investigation(
        self,
        sector: str,
        component: str,
        error_summary: str,
        __event_emitter__: Callable[[dict], Any] = None,
    ) -> str:
        """
        Create a system post-mortem entry and queue an OODA investigation.
        Use this when you detect a systemic issue that needs root-cause analysis.
        Sector should be one of: crog, dev, comp, bloom, legal.
        """
        if __event_emitter__:
            await __event_emitter__({"type": "status", "data": {"description": f"Creating post-mortem for {component}...", "done": False}})

        import psycopg2
        try:
            conn = psycopg2.connect(
                host=self.valves.db_host, port=self.valves.db_port,
                database=self.valves.db_name, user=self.valves.db_user,
                password=self.valves.db_pass, connect_timeout=5,
            )
            cur = conn.cursor()
            cur.execute(
                """INSERT INTO system_post_mortems
                   (occurred_at, sector, severity, component, error_summary, status, resolved_by)
                   VALUES (NOW(), %s, 'warning', %s, %s, 'open', 'council_ai')
                   RETURNING id""",
                (sector[:10], component[:255], error_summary[:2000]),
            )
            pm_id = cur.fetchone()[0]
            conn.commit()
            conn.close()

            result = {
                "post_mortem_id": pm_id,
                "sector": sector,
                "component": component,
                "status": "open",
                "next_step": "OODA Orient phase will analyze root cause on next cycle",
            }
            if __event_emitter__:
                await __event_emitter__({"type": "status", "data": {"description": f"Post-mortem #{pm_id} created", "done": True}})
            return json.dumps(result, indent=2)

        except Exception as exc:
            if __event_emitter__:
                await __event_emitter__({"type": "status", "data": {"description": "Post-mortem creation failed", "done": True}})
            return f"[ERROR] Failed to create post-mortem: {exc}"

    async def escalate_to_god_head(
        self,
        domain: str,
        prompt: str,
        context: str,
        dry_run: bool = False,
        __event_emitter__: Callable[[dict], Any] = None,
    ) -> str:
        """
        Escalate a complex task to an external God-Head API (Tier 2).
        Mandatory PII sanitization is applied automatically before any data leaves the cluster.
        Domain must be one of: legal, financial, architecture, general.
        Set dry_run=True to preview sanitized context without calling the API.
        """
        valid_domains = ("legal", "financial", "architecture", "general")
        if domain not in valid_domains:
            return f"[ERROR] Invalid domain '{domain}'. Must be one of: {', '.join(valid_domains)}"

        if __event_emitter__:
            action = "Dry-run sanitization" if dry_run else f"Escalating to {domain} God-Head"
            await __event_emitter__({"type": "status", "data": {"description": f"{action}...", "done": False}})

        try:
            import sys
            sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
            from src.god_head_router import route as god_head_route

            result = god_head_route(
                domain=domain,
                prompt=prompt,
                context=context,
                dry_run=dry_run,
            )

            if dry_run:
                output = {
                    "mode": "dry_run",
                    "domain": domain,
                    "sanitized_context": result.get("sanitized_context", ""),
                    "note": "No API call was made. Review the sanitized context above.",
                }
            else:
                output = {
                    "domain": domain,
                    "provider": result.get("provider"),
                    "response": result.get("response", "")[:4000],
                    "tokens_used": result.get("tokens_used", 0),
                    "escalation_id": result.get("escalation_id"),
                    "fallback_used": result.get("fallback_used", False),
                }

            if __event_emitter__:
                desc = "Dry-run complete" if dry_run else f"Response from {result.get('provider', '?')}"
                await __event_emitter__({"type": "status", "data": {"description": desc, "done": True}})
            return _truncate(json.dumps(output, indent=2))

        except RuntimeError as exc:
            if __event_emitter__:
                await __event_emitter__({"type": "status", "data": {"description": "Governance block", "done": True}})
            return f"[GOVERNANCE BLOCK] {exc}"
        except Exception as exc:
            if __event_emitter__:
                await __event_emitter__({"type": "status", "data": {"description": "Escalation failed", "done": True}})
            return f"[ERROR] God-Head escalation failed: {exc}"
