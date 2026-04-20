"""
Fortress Prime — Human-in-the-Loop Review Mode
================================================
Weekly review tool for prompt quality assurance.
Star good responses to build a dynamic few-shot learning loop.

Pull recent logs, filter by tone/template/failures, review AI outputs,
and identify prompts that need better few-shot examples.

Usage:
    # Review all emergency-tone responses from the last 7 days
    python -m prompts.review --tone emergency --days 7

    # Review all failures
    python -m prompts.review --failures --days 3

    # Review a specific template
    python -m prompts.review --template guest_email_reply --days 7

    # Full weekly report
    python -m prompts.review --weekly

    # Star a good response for dynamic few-shot learning
    python -m prompts.review --star <run_id> --tag ev_charging
    python -m prompts.review --star <run_id> --tag pets --quality 5 --notes "Great tone"

    # Unstar a response
    python -m prompts.review --unstar <run_id>

    # View all starred responses
    python -m prompts.review --starred
    python -m prompts.review --starred --tag ev_charging

    # Export for offline review
    python -m prompts.review --tone emergency --days 7 --export review_batch.json
"""

import os
import sys
import json
import time
import argparse
from pathlib import Path
from datetime import datetime, timedelta
from typing import List, Dict, Any, Optional

# Ensure prompts package is importable
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
from prompts.loader import LOGS_DIR, get_prompt_logs, get_prompt_stats
from prompts.starred_db import (
    star_response, unstar_response, get_all_starred,
    get_topic_stats, load_dynamic_examples,
)


# =============================================================================
# LOG RETRIEVAL (Multi-Day)
# =============================================================================

def get_logs_for_period(
    days: int = 7,
    template_filter: Optional[str] = None,
    tone_filter: Optional[str] = None,
    failures_only: bool = False,
    limit: int = 200,
) -> List[Dict[str, Any]]:
    """
    Retrieve logs across multiple days with filtering.

    Args:
        days:            Number of days to look back
        template_filter: Only return entries for this template
        tone_filter:     Only return entries where tone_modifier matches
        failures_only:   Only return failed executions
        limit:           Max entries to return

    Returns:
        List of log entries, newest first.
    """
    all_entries = []

    for day_offset in range(days):
        date = datetime.now() - timedelta(days=day_offset)
        date_str = date.strftime("%Y%m%d")
        log_file = LOGS_DIR / f"prompts_{date_str}.jsonl"

        if not log_file.exists():
            continue

        with open(log_file, "r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    entry = json.loads(line)
                except json.JSONDecodeError:
                    continue

                # Apply filters
                if template_filter and entry.get("template") != template_filter:
                    continue

                if failures_only and entry.get("success", True):
                    continue

                if tone_filter:
                    inputs = entry.get("inputs", {})
                    tone = inputs.get("tone_modifier", "")
                    if tone_filter.lower() not in tone.lower():
                        continue

                all_entries.append(entry)

    # Sort newest first
    all_entries.sort(key=lambda e: e.get("epoch", 0), reverse=True)
    return all_entries[:limit]


# =============================================================================
# DISPLAY FUNCTIONS
# =============================================================================

def display_entry(entry: Dict[str, Any], index: int, verbose: bool = False):
    """Pretty-print a single log entry for human review."""
    status = "OK" if entry.get("success") else "FAIL"
    template = entry.get("template", "?")
    model = entry.get("model", "?")
    timestamp = entry.get("timestamp", "?")
    duration = entry.get("duration_ms")
    run_id = entry.get("run_id", "?")

    dur_str = f"{duration:.0f}ms" if duration else "N/A"

    print(f"\n  {'─' * 60}")
    print(f"  [{index}] [{status}] {template}")
    print(f"       Run:       {run_id}")
    print(f"       Time:      {timestamp}")
    print(f"       Model:     {model}  ({dur_str})")

    # Show inputs
    inputs = entry.get("inputs", {})
    if inputs:
        tone = inputs.get("tone_modifier", "")
        if tone:
            # Truncate long tone modifiers
            tone_short = tone[:60] + "..." if len(tone) > 60 else tone
            print(f"       Tone:      {tone_short}")

        # Show other key inputs
        for key in ["cabin_name", "guest_name", "filename", "question"]:
            if key in inputs:
                print(f"       {key}: {inputs[key]}")

    # Show error if failed
    if not entry.get("success"):
        error = entry.get("error", "Unknown error")
        print(f"       ERROR:     {error}")

    # Show output preview
    output = entry.get("output", "")
    if output and verbose:
        print(f"\n       --- AI OUTPUT ---")
        # Indent output for readability
        for line in output[:800].split("\n"):
            print(f"       | {line}")
        if len(output) > 800:
            print(f"       | ... ({entry.get('output_length', '?')} chars total)")
        print(f"       --- END OUTPUT ---")


def display_weekly_report(days: int = 7):
    """Generate a weekly summary report across all templates."""
    print(f"\n{'=' * 60}")
    print(f"  FORTRESS PRIME — WEEKLY PROMPT REVIEW")
    print(f"  Period: Last {days} days")
    print(f"  Generated: {datetime.now().strftime('%Y-%m-%d %H:%M')}")
    print(f"{'=' * 60}")

    # Aggregate stats across all days
    total_runs = 0
    total_success = 0
    total_failed = 0
    by_template = {}
    by_division = {}
    by_model = {}
    durations = []

    for day_offset in range(days):
        date = datetime.now() - timedelta(days=day_offset)
        date_str = date.strftime("%Y%m%d")
        stats = get_prompt_stats(date=date_str)

        total_runs += stats.get("total", 0)
        total_success += stats.get("success", 0)
        total_failed += stats.get("failed", 0)

        for k, v in stats.get("by_template", {}).items():
            by_template[k] = by_template.get(k, 0) + v
        for k, v in stats.get("by_division", {}).items():
            key = k or "(untagged)"
            by_division[key] = by_division.get(key, 0) + v
        for k, v in stats.get("by_model", {}).items():
            by_model[k] = by_model.get(k, 0) + v

    if total_runs == 0:
        print("\n  No prompt executions found in the last {days} days.")
        print(f"{'=' * 60}")
        return

    success_rate = (total_success / total_runs * 100) if total_runs > 0 else 0

    print(f"\n  OVERVIEW:")
    print(f"  Total Executions:  {total_runs:,}")
    print(f"  Successful:        {total_success:,}")
    print(f"  Failed:            {total_failed:,}")
    print(f"  Success Rate:      {success_rate:.1f}%")

    # By template
    print(f"\n  {'TEMPLATE':<35} {'RUNS':>8}")
    print(f"  {'-' * 45}")
    for tmpl, count in sorted(by_template.items(), key=lambda x: -x[1]):
        print(f"  {tmpl:<35} {count:>8,}")

    # By division
    print(f"\n  {'DIVISION':<35} {'RUNS':>8}")
    print(f"  {'-' * 45}")
    for div, count in sorted(by_division.items(), key=lambda x: -x[1]):
        print(f"  {div:<35} {count:>8,}")

    # By model
    print(f"\n  {'MODEL':<35} {'RUNS':>8}")
    print(f"  {'-' * 45}")
    for model, count in sorted(by_model.items(), key=lambda x: -x[1]):
        print(f"  {model:<35} {count:>8,}")

    # Highlight failures
    if total_failed > 0:
        print(f"\n  FAILED EXECUTIONS (showing up to 10):")
        failures = get_logs_for_period(days=days, failures_only=True, limit=10)
        for i, entry in enumerate(failures, 1):
            template = entry.get("template", "?")
            error = entry.get("error", "Unknown")
            timestamp = entry.get("timestamp", "?")
            print(f"    {i}. [{template}] {timestamp}")
            print(f"       Error: {error[:80]}")

    # Emergency tone review
    emergencies = get_logs_for_period(days=days, tone_filter="emergency", limit=100)
    if emergencies:
        print(f"\n  EMERGENCY TONE RESPONSES: {len(emergencies)} found")
        print(f"  (Run: python -m prompts.review --tone emergency --days {days} -v)")

    print(f"\n{'=' * 60}")


def export_logs(entries: List[Dict[str, Any]], filepath: str):
    """Export log entries to a JSON file for offline review."""
    export_data = {
        "exported_at": datetime.now().isoformat(),
        "count": len(entries),
        "entries": entries,
    }
    with open(filepath, "w", encoding="utf-8") as f:
        json.dump(export_data, f, indent=2, default=str)
    print(f"\n  Exported {len(entries)} entries to: {filepath}")


# =============================================================================
# STARRING — Dynamic Few-Shot Learning Loop
# =============================================================================

def handle_star(run_id: str, tag: str, quality: int = 5, notes: Optional[str] = None):
    """Star a response from the logs as a golden example."""
    # Find the log entry by run_id
    entry = _find_log_entry(run_id)
    if not entry:
        print(f"\n  ERROR: No log entry found with run_id '{run_id}'")
        print(f"  Tip: Use 'python -m prompts.review --days 7 -v' to find run_ids.")
        return

    # Extract the guest input and AI output
    inputs = entry.get("inputs", {})
    guest_input = inputs.get("guest_email", inputs.get("question", "(no input recorded)"))
    ai_output = entry.get("output", "(no output recorded)")
    cabin_name = inputs.get("cabin_name") or entry.get("metadata", {}).get("cabin")
    tone = inputs.get("tone_modifier", "")

    # Truncate long tone modifiers for storage
    if tone and len(tone) > 100:
        tone = tone[:100]

    row_id = star_response(
        run_id=run_id,
        topic_tag=tag,
        guest_input=guest_input,
        ai_output=ai_output,
        cabin_name=cabin_name,
        tone=tone,
        quality_score=quality,
        notes=notes,
    )

    print(f"\n{'=' * 60}")
    print(f"  STARRED RESPONSE")
    print(f"{'=' * 60}")
    print(f"  Run ID:    {run_id}")
    print(f"  Topic:     {tag}")
    print(f"  Quality:   {'*' * quality} ({quality}/5)")
    print(f"  DB Row:    #{row_id}")
    if cabin_name:
        print(f"  Cabin:     {cabin_name}")
    print(f"\n  Input:     {guest_input[:80]}...")
    print(f"  Output:    {ai_output[:80]}...")
    if notes:
        print(f"  Notes:     {notes}")
    print(f"\n  This response will now be used as a dynamic few-shot example")
    print(f"  for future '{tag}' topic queries.")
    print(f"{'=' * 60}")


def handle_unstar(run_id: str):
    """Remove a starred response."""
    if unstar_response(run_id):
        print(f"\n  Unstarred: {run_id}")
    else:
        print(f"\n  ERROR: No starred entry found with run_id '{run_id}'")


def display_starred(tag_filter: Optional[str] = None):
    """Display all starred responses."""
    entries = get_all_starred(topic_filter=tag_filter)
    stats = get_topic_stats()
    total = sum(stats.values()) if stats else 0

    print(f"\n{'=' * 60}")
    if tag_filter:
        print(f"  STARRED RESPONSES — Topic: {tag_filter}")
    else:
        print(f"  STARRED RESPONSES — All Topics")
    print(f"  Total: {len(entries)} starred examples")
    print(f"{'=' * 60}")

    if not entries:
        print("\n  No starred responses found.")
        print("  Star responses during review:")
        print("    python -m prompts.review --star <run_id> --tag <topic>")
        print(f"{'=' * 60}")
        return

    # Group by topic
    current_topic = None
    for entry in entries:
        if entry.topic_tag != current_topic:
            current_topic = entry.topic_tag
            count = stats.get(current_topic, 0)
            print(f"\n  --- {current_topic.upper()} ({count} examples) ---")

        quality_stars = "*" * entry.quality_score
        print(f"\n  [{quality_stars}] {entry.run_id}")
        print(f"       Q: {entry.guest_input[:70]}")
        print(f"       A: {entry.ai_output[:70]}")
        if entry.cabin_name:
            print(f"       Cabin: {entry.cabin_name}")
        if entry.notes:
            print(f"       Note: {entry.notes}")

    # Topic summary
    if stats and not tag_filter:
        print(f"\n  {'─' * 50}")
        print(f"  {'TOPIC':<25} {'EXAMPLES':>8}")
        print(f"  {'─' * 35}")
        for topic, count in stats.items():
            print(f"  {topic:<25} {count:>8}")

    print(f"\n{'=' * 60}")


def _find_log_entry(run_id: str) -> Optional[Dict[str, Any]]:
    """Search recent logs for a specific run_id."""
    for day_offset in range(30):  # Search last 30 days
        date = datetime.now() - timedelta(days=day_offset)
        date_str = date.strftime("%Y%m%d")
        log_file = LOGS_DIR / f"prompts_{date_str}.jsonl"

        if not log_file.exists():
            continue

        with open(log_file, "r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    entry = json.loads(line)
                    if entry.get("run_id") == run_id:
                        return entry
                except json.JSONDecodeError:
                    continue

    return None


# =============================================================================
# CLI
# =============================================================================

def main():
    parser = argparse.ArgumentParser(
        description="Fortress Prime — Prompt Review + Learning Loop",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  python -m prompts.review --weekly
  python -m prompts.review --tone emergency --days 7 -v
  python -m prompts.review --failures --days 3
  python -m prompts.review --template ledger_classifier --days 1
  python -m prompts.review --tone emergency --export batch.json

  # Dynamic Few-Shot Learning:
  python -m prompts.review --star abc123 --tag ev_charging
  python -m prompts.review --star abc123 --tag pets --quality 5 --notes "Great tone"
  python -m prompts.review --unstar abc123
  python -m prompts.review --starred
  python -m prompts.review --starred --tag ev_charging
        """
    )

    parser.add_argument("--days", type=int, default=7,
                        help="Number of days to look back (default: 7)")
    parser.add_argument("--template", type=str, default=None,
                        help="Filter by template name")
    parser.add_argument("--tone", type=str, default=None,
                        help="Filter by tone_modifier content (e.g., 'emergency')")
    parser.add_argument("--failures", action="store_true",
                        help="Show only failed executions")
    parser.add_argument("--weekly", action="store_true",
                        help="Generate weekly summary report")
    parser.add_argument("--limit", type=int, default=50,
                        help="Max entries to show (default: 50)")
    parser.add_argument("-v", "--verbose", action="store_true",
                        help="Show full AI output for each entry")
    parser.add_argument("--export", type=str, default=None,
                        help="Export filtered results to JSON file")

    # Starring commands
    parser.add_argument("--star", type=str, default=None, metavar="RUN_ID",
                        help="Star a response by its run_id")
    parser.add_argument("--unstar", type=str, default=None, metavar="RUN_ID",
                        help="Unstar a response by its run_id")
    parser.add_argument("--tag", type=str, default=None,
                        help="Topic tag for starring (e.g., 'ev_charging', 'pets')")
    parser.add_argument("--quality", type=int, default=5, choices=[1, 2, 3, 4, 5],
                        help="Quality score 1-5 (default: 5)")
    parser.add_argument("--notes", type=str, default=None,
                        help="Notes about why this response was starred")
    parser.add_argument("--starred", action="store_true",
                        help="Display all starred responses")

    args = parser.parse_args()

    # --- Starring operations (take priority) ---
    if args.star:
        if not args.tag:
            print("\n  ERROR: --tag is required when starring a response.")
            print("  Example: python -m prompts.review --star abc123 --tag ev_charging")
            return
        handle_star(args.star, args.tag, args.quality, args.notes)
        return

    if args.unstar:
        handle_unstar(args.unstar)
        return

    if args.starred:
        display_starred(tag_filter=args.tag)
        return

    # --- Weekly report mode ---
    if args.weekly:
        display_weekly_report(days=args.days)
        return

    # --- Filtered review mode ---
    entries = get_logs_for_period(
        days=args.days,
        template_filter=args.template,
        tone_filter=args.tone,
        failures_only=args.failures,
        limit=args.limit,
    )

    # Build title
    title_parts = []
    if args.tone:
        title_parts.append(f"tone={args.tone}")
    if args.template:
        title_parts.append(f"template={args.template}")
    if args.failures:
        title_parts.append("failures only")
    title_suffix = f" ({', '.join(title_parts)})" if title_parts else ""

    print(f"\n{'=' * 60}")
    print(f"  PROMPT REVIEW — Last {args.days} day(s){title_suffix}")
    print(f"  Found: {len(entries)} entries")
    print(f"{'=' * 60}")

    if not entries:
        print("\n  No matching log entries found.")
        print(f"\n  Tip: Logs are stored in: {LOGS_DIR}/")
        print(f"  Check that prompt executions are calling log_prompt_execution().")
        print(f"{'=' * 60}")
        return

    # Display entries
    for i, entry in enumerate(entries, 1):
        display_entry(entry, i, verbose=args.verbose)

    # Export if requested
    if args.export:
        export_logs(entries, args.export)

    print(f"\n{'=' * 60}")
    print(f"  Review complete. {len(entries)} entries shown.")
    if not args.verbose:
        print(f"  Tip: Add -v for full AI output text.")
    print(f"  Tip: Star good responses: --star <run_id> --tag <topic>")
    print(f"{'=' * 60}")


if __name__ == "__main__":
    main()
