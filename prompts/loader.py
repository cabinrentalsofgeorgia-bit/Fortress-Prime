"""
Fortress Prime — Prompt Loader + Observability
================================================
Enterprise-grade prompt template management with versioning, caching,
variable injection, and execution traceability.

Templates are stored as YAML files in versioned subdirectories:
    prompts/v1/ledger_classifier.yaml
    prompts/v2/ledger_classifier.yaml   (future revision)

Variable Syntax:
    Use {variable_name} for injected values.
    Use {{ and }} for literal braces (e.g., in JSON examples).

Observability:
    Every prompt execution can be logged via log_prompt_execution().
    Logs are written as daily JSONL files in the logs/ directory.
    Use these for tuning, auditing, and future fine-tuning datasets.

Usage:
    from prompts.loader import load_prompt, log_prompt_execution

    tmpl = load_prompt("ledger_classifier")
    prompt_text = tmpl.render(filename="invoice.pdf", document_text="...")

    # After getting LLM response:
    log_prompt_execution(
        template_name="ledger_classifier",
        version="v1",
        variables={"filename": "invoice.pdf"},
        rendered_prompt=prompt_text,
        raw_output=llm_response,
        model_name="deepseek-r1:8b"
    )
"""

import os
import sys
import json
import time
import uuid
import logging
import yaml
from pathlib import Path
from typing import Optional, List, Dict, Any

# Centralized path resolution (NAS-first, local fallback)
sys.path.insert(0, str(Path(__file__).parent.parent))
from src.fortress_paths import LOGS_DIR as _RESOLVED_LOGS_DIR

PROMPTS_DIR = Path(__file__).parent
DEFAULT_VERSION = "v1"

# Logs directory — resolved by fortress_paths:
#   NAS:   /mnt/fortress_nas/fortress_data/ai_brain/logs
#   Local: ./data/logs
LOGS_DIR = _RESOLVED_LOGS_DIR

# Module-level logger for internal errors (won't interfere with app logging)
_logger = logging.getLogger("fortress.prompts")


class PromptTemplate:
    """
    A loaded prompt template with metadata and variable rendering.
    """

    def __init__(self, data: dict, filepath: str):
        self.name = data.get("name", "Unnamed")
        self.version = data.get("version", DEFAULT_VERSION)
        self.division = data.get("division", "general")
        self.description = data.get("description", "")
        self.model_config = data.get("model", {})
        self.variables = data.get("variables", [])
        self._template = data.get("template", "")
        self._filepath = filepath

    def render(self, **kwargs) -> str:
        """
        Inject variables into the template.

        Uses Python str.format() — literal braces in YAML are escaped
        as {{ and }} which resolve to { and } after formatting.

        Args:
            **kwargs: Variable name/value pairs matching the template's {placeholders}.

        Returns:
            Fully rendered prompt string ready for LLM consumption.

        Raises:
            KeyError: If a required variable is missing from kwargs.
        """
        try:
            return self._template.format(**kwargs)
        except KeyError as e:
            missing = str(e).strip("'")
            available = ", ".join(self.variables) if self.variables else "(none declared)"
            raise KeyError(
                f"Prompt '{self.name}' requires variable {e}. "
                f"Declared variables: {available}"
            ) from None

    def render_safe(self, **kwargs) -> str:
        """
        Render with graceful handling of missing variables.
        Missing variables are left as {variable_name} in the output.
        """
        import string

        class SafeDict(dict):
            def __missing__(self, key):
                return "{" + key + "}"

        return self._template.format_map(SafeDict(**kwargs))

    @property
    def template(self) -> str:
        """Return the raw template string (with {placeholders} intact)."""
        return self._template

    @property
    def filepath(self) -> str:
        """Return the filesystem path this template was loaded from."""
        return self._filepath

    def __repr__(self):
        return f"<PromptTemplate '{self.name}' {self.version} [{self.division}]>"

    def __str__(self):
        return self._template


# =============================================================================
# TEMPLATE CACHE
# =============================================================================

_cache: Dict[str, PromptTemplate] = {}


def _clear_cache():
    """Clear the template cache (useful for testing or hot-reload)."""
    _cache.clear()


# =============================================================================
# PUBLIC API
# =============================================================================

def load_prompt(name: str, version: Optional[str] = None) -> PromptTemplate:
    """
    Load a prompt template by name.

    Args:
        name:    Template name (e.g., "ledger_classifier", "thunderdome_pitbull")
        version: Version directory (default: "v1"). Pass "v2" for future revisions.

    Returns:
        PromptTemplate object with .render(**kwargs) method.

    Raises:
        FileNotFoundError: If the template YAML doesn't exist.

    Example:
        tmpl = load_prompt("ledger_classifier")
        prompt = tmpl.render(filename="invoice.pdf", document_text="Total: $500")
    """
    version = version or DEFAULT_VERSION
    cache_key = f"{version}/{name}"

    if cache_key in _cache:
        return _cache[cache_key]

    filepath = PROMPTS_DIR / version / f"{name}.yaml"
    if not filepath.exists():
        # Try without .yaml extension in case user passed it
        filepath_alt = PROMPTS_DIR / version / name
        if filepath_alt.exists():
            filepath = filepath_alt
        else:
            available = list_prompts(version)
            raise FileNotFoundError(
                f"Prompt template not found: {filepath}\n"
                f"Available templates ({version}): {', '.join(available) if available else '(none)'}"
            )

    with open(filepath, "r", encoding="utf-8") as f:
        data = yaml.safe_load(f)

    if not data:
        raise ValueError(f"Empty or invalid YAML: {filepath}")

    template = PromptTemplate(data, str(filepath))
    _cache[cache_key] = template
    return template


def list_prompts(version: Optional[str] = None) -> List[str]:
    """
    List all available prompt template names for a given version.

    Args:
        version: Version directory (default: "v1")

    Returns:
        Sorted list of template names (without .yaml extension).
    """
    version = version or DEFAULT_VERSION
    version_dir = PROMPTS_DIR / version

    if not version_dir.exists():
        return []

    return sorted(f.stem for f in version_dir.glob("*.yaml"))


def list_versions() -> List[str]:
    """
    List all available prompt versions (e.g., ["v1", "v2"]).
    """
    return sorted(
        d.name for d in PROMPTS_DIR.iterdir()
        if d.is_dir() and d.name.startswith("v") and d.name[1:].isdigit()
    )


def get_prompt_registry(version: Optional[str] = None) -> Dict[str, Dict[str, Any]]:
    """
    Return a registry of all templates with their metadata.
    Useful for dashboards and admin interfaces.

    Returns:
        Dict mapping template names to their metadata.
    """
    version = version or DEFAULT_VERSION
    registry = {}

    for name in list_prompts(version):
        tmpl = load_prompt(name, version)
        registry[name] = {
            "name": tmpl.name,
            "version": tmpl.version,
            "division": tmpl.division,
            "description": tmpl.description,
            "variables": tmpl.variables,
            "model_config": tmpl.model_config,
            "filepath": tmpl.filepath,
        }

    return registry


# =============================================================================
# PROMPT OBSERVABILITY — Execution Logging
# =============================================================================

def log_prompt_execution(
    template_name: str,
    version: str = DEFAULT_VERSION,
    variables: Optional[Dict[str, Any]] = None,
    rendered_prompt: Optional[str] = None,
    raw_output: Optional[str] = None,
    model_name: str = "unknown",
    duration_ms: Optional[float] = None,
    success: bool = True,
    error: Optional[str] = None,
    metadata: Optional[Dict[str, Any]] = None,
) -> str:
    """
    Log a prompt execution for traceability, tuning, and dataset creation.

    Writes a single JSON line to a daily JSONL file in logs/.
    Each entry gets a unique run_id for cross-referencing.

    Args:
        template_name: Which template was used (e.g., "guest_review_response")
        version:       Template version (e.g., "v1")
        variables:     Dict of variables injected into the template
        rendered_prompt: The fully rendered prompt sent to the LLM
        raw_output:    The raw LLM response text
        model_name:    Which model processed it (e.g., "deepseek-r1:8b")
        duration_ms:   How long the LLM call took in milliseconds
        success:       Whether the execution succeeded
        error:         Error message if execution failed
        metadata:      Any additional context (cabin name, guest ID, etc.)

    Returns:
        The unique run_id for this execution (for downstream tracing).

    Example:
        run_id = log_prompt_execution(
            template_name="guest_review_response",
            version="v1",
            variables={"cabin_name": "Rolling River", "guest_name": "Sarah"},
            rendered_prompt=prompt_text,
            raw_output=ai_response,
            model_name="deepseek-r1:70b",
            duration_ms=2340.5,
        )
    """
    run_id = str(uuid.uuid4())[:12]

    # Sanitize variables — truncate long text fields for log readability
    sanitized_vars = {}
    if variables:
        for k, v in variables.items():
            if isinstance(v, str) and len(v) > 500:
                sanitized_vars[k] = v[:500] + f"... ({len(v)} chars)"
            else:
                sanitized_vars[k] = v

    # Truncate raw_output for log storage (keep first 2000 chars)
    output_preview = None
    output_length = 0
    if raw_output:
        output_length = len(raw_output)
        output_preview = raw_output[:2000]
        if output_length > 2000:
            output_preview += f"\n... ({output_length} chars total)"

    log_entry = {
        "run_id": run_id,
        "timestamp": time.strftime("%Y-%m-%dT%H:%M:%S%z"),
        "epoch": time.time(),
        "template": template_name,
        "version": version,
        "division": _get_division(template_name, version),
        "model": model_name,
        "inputs": sanitized_vars,
        "input_token_estimate": _estimate_tokens(rendered_prompt) if rendered_prompt else None,
        "output": output_preview,
        "output_length": output_length,
        "output_token_estimate": _estimate_tokens(raw_output) if raw_output else None,
        "duration_ms": duration_ms,
        "success": success,
        "error": error,
        "metadata": metadata,
    }

    # Write to daily JSONL file
    try:
        LOGS_DIR.mkdir(parents=True, exist_ok=True)
        filename = LOGS_DIR / f"prompts_{time.strftime('%Y%m%d')}.jsonl"
        with open(filename, "a", encoding="utf-8") as f:
            f.write(json.dumps(log_entry, default=str) + "\n")
    except Exception as e:
        _logger.warning(f"Failed to write prompt log: {e}")

    return run_id


def _get_division(template_name: str, version: str) -> Optional[str]:
    """Look up the division for a template (from cache if available)."""
    cache_key = f"{version}/{template_name}"
    if cache_key in _cache:
        return _cache[cache_key].division
    return None


def _estimate_tokens(text: str) -> int:
    """
    Rough token estimate (~4 chars per token for English text).
    Good enough for logging; not a substitute for a real tokenizer.
    """
    if not text:
        return 0
    return len(text) // 4


def get_prompt_logs(
    date: Optional[str] = None,
    template_filter: Optional[str] = None,
    limit: int = 50,
) -> List[Dict[str, Any]]:
    """
    Read prompt execution logs for review and analysis.

    Args:
        date:            Date string "YYYYMMDD" (default: today)
        template_filter: Only return logs for this template name
        limit:           Max number of entries to return (newest first)

    Returns:
        List of log entry dicts, newest first.
    """
    if date is None:
        date = time.strftime("%Y%m%d")

    log_file = LOGS_DIR / f"prompts_{date}.jsonl"
    if not log_file.exists():
        return []

    entries = []
    with open(log_file, "r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                entry = json.loads(line)
                if template_filter and entry.get("template") != template_filter:
                    continue
                entries.append(entry)
            except json.JSONDecodeError:
                continue

    # Return newest first, capped at limit
    return entries[-limit:][::-1]


def get_prompt_stats(date: Optional[str] = None) -> Dict[str, Any]:
    """
    Aggregate statistics from a day's prompt logs.
    Useful for dashboards and daily review.

    Returns:
        Dict with counts by template, division, model, success rate, etc.
    """
    entries = get_prompt_logs(date=date, limit=10000)
    if not entries:
        return {"total": 0, "date": date or time.strftime("%Y%m%d")}

    stats = {
        "date": date or time.strftime("%Y%m%d"),
        "total": len(entries),
        "success": sum(1 for e in entries if e.get("success")),
        "failed": sum(1 for e in entries if not e.get("success")),
        "by_template": {},
        "by_division": {},
        "by_model": {},
        "avg_duration_ms": None,
        "total_input_tokens": 0,
        "total_output_tokens": 0,
    }

    durations = []
    for e in entries:
        # By template
        tmpl = e.get("template", "unknown")
        stats["by_template"][tmpl] = stats["by_template"].get(tmpl, 0) + 1

        # By division
        div = e.get("division", "unknown")
        stats["by_division"][div] = stats["by_division"].get(div, 0) + 1

        # By model
        model = e.get("model", "unknown")
        stats["by_model"][model] = stats["by_model"].get(model, 0) + 1

        # Duration
        if e.get("duration_ms") is not None:
            durations.append(e["duration_ms"])

        # Tokens
        stats["total_input_tokens"] += e.get("input_token_estimate") or 0
        stats["total_output_tokens"] += e.get("output_token_estimate") or 0

    if durations:
        stats["avg_duration_ms"] = round(sum(durations) / len(durations), 1)

    return stats


# =============================================================================
# CLI: python -m prompts.loader
# =============================================================================

if __name__ == "__main__":
    print("=" * 60)
    print("  FORTRESS PRIME — PROMPT REGISTRY")
    print("=" * 60)

    for version in list_versions():
        print(f"\n  Version: {version}")
        print(f"  {'─' * 50}")
        for name in list_prompts(version):
            tmpl = load_prompt(name, version)
            vars_str = ", ".join(tmpl.variables) if tmpl.variables else "(static)"
            print(f"    {name:<35} [{tmpl.division}]  vars: {vars_str}")

    print(f"\n{'=' * 60}")
