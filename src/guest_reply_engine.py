"""
Fortress Prime — Guest Reply Engine (Main Loop)
==================================================
The single orchestration layer that ties the entire AI pipeline together.

This is "the command center." Every guest email passes through this engine:

    Email In -> Classify Topic -> Detect Tone -> Slice Context
             -> Load Dynamic Examples -> Render Prompt -> LLM Call
             -> Log Execution -> Output Draft

Architecture:
    1. CLASSIFY: topic_classifier identifies what the guest is asking about
    2. DETECT:   tone_detector identifies how the guest is feeling
    3. SLICE:    context_slicer injects ONLY the relevant cabin data
    4. EXAMPLES: starred_db loads human-approved "golden" responses for this topic
    5. RENDER:   loader assembles the final prompt with all dynamic components
    6. THINK:    captain_think sends it to DeepSeek-R1 for response generation
    7. LOG:      log_prompt_execution records everything for observability
    8. OUTPUT:   Draft is returned for human review or auto-delivery

MODES:
    single   - Process one email (CLI or programmatic)
    batch    - Process a list of emails from a JSON file
    watch    - Monitor a directory for new .txt email files (future: Gmail API)
    test     - Dry-run with synthetic emails (no LLM call)

Usage:
    # CLI — Single email
    python -m src.guest_reply_engine \\
        --cabin rolling_river \\
        --email "Can I charge my Tesla at the cabin?"

    # CLI — Batch mode
    python -m src.guest_reply_engine \\
        --cabin rolling_river \\
        --batch inbox/pending_emails.json

    # CLI — Test mode (no LLM, just shows what WOULD be sent)
    python -m src.guest_reply_engine \\
        --cabin rolling_river \\
        --email "The pipes burst!" \\
        --test

    # Programmatic
    from src.guest_reply_engine import process_email
    result = process_email("rolling_river", "Can I charge my Tesla?")
    print(result.draft)
"""

import sys
import os
import json
import time
import argparse
from pathlib import Path
from dataclasses import dataclass, field
from typing import Optional, List, Dict, Any

# Add project root to path for imports
PROJECT_ROOT = Path(__file__).parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from prompts.loader import load_prompt, log_prompt_execution
from prompts.topic_classifier import classify_topic, classify_topic_tag
from prompts.tone_detector import detect_tone
from prompts.context_slicer import slice_context, list_cabins
from prompts.starred_db import load_dynamic_examples


# =============================================================================
# RESULT DATACLASS
# =============================================================================

@dataclass
class ReplyResult:
    """Complete result of processing a single guest email."""

    # Input
    cabin_slug: str
    guest_email: str

    # Classification
    topic: str = ""
    secondary_topics: List[str] = field(default_factory=list)
    topic_confidence: float = 0.0
    tone: str = ""
    tone_modifier: str = ""
    tone_confidence: float = 0.0
    escalation_required: bool = False

    # Context slicing
    context_tokens: int = 0
    full_context_tokens: int = 0
    tokens_saved: int = 0
    topics_included: List[str] = field(default_factory=list)

    # Dynamic examples
    examples_loaded: int = 0
    examples_topic: str = ""

    # LLM
    draft: str = ""
    model: str = ""
    duration_ms: float = 0.0
    success: bool = False
    error: Optional[str] = None

    # Observability
    run_id: str = ""
    rendered_prompt: str = ""
    prompt_tokens: int = 0

    @property
    def savings_pct(self) -> float:
        """Percentage of context tokens saved by slicing."""
        if self.full_context_tokens == 0:
            return 0.0
        return (self.tokens_saved / self.full_context_tokens) * 100

    def summary(self) -> str:
        """One-line summary for batch processing output."""
        status = "OK" if self.success else "FAIL"
        esc = " [ESCALATE]" if self.escalation_required else ""
        return (
            f"[{status}] topic={self.topic} tone={self.tone} "
            f"tokens={self.context_tokens}/{self.full_context_tokens} "
            f"({self.savings_pct:.0f}% saved) "
            f"examples={self.examples_loaded} "
            f"model={self.model} "
            f"time={self.duration_ms:.0f}ms{esc}"
        )


# =============================================================================
# CORE ENGINE
# =============================================================================

def process_email(
    cabin_slug: str,
    guest_email: str,
    model: Optional[str] = None,
    dry_run: bool = False,
    verbose: bool = False,
) -> ReplyResult:
    """
    Process a single guest email through the full AI pipeline.

    This is the main entry point. It:
        1. Classifies the topic
        2. Detects the tone
        3. Slices the cabin context
        4. Loads dynamic few-shot examples
        5. Renders the prompt
        6. Calls the LLM (unless dry_run=True)
        7. Logs everything

    Args:
        cabin_slug:  Cabin identifier (e.g., "rolling_river")
        guest_email: The raw guest email text
        model:       Override LLM model (default: from template config)
        dry_run:     If True, skip LLM call and return the rendered prompt
        verbose:     Print pipeline steps to stdout

    Returns:
        ReplyResult with full pipeline trace and the AI draft.
    """
    result = ReplyResult(cabin_slug=cabin_slug, guest_email=guest_email)
    pipeline_start = time.time()

    # ─────────────────────────────────────────────────────────────────
    # STEP 1: CLASSIFY TOPIC
    # ─────────────────────────────────────────────────────────────────
    topic_result = classify_topic(guest_email)
    result.topic = topic_result.primary
    result.secondary_topics = topic_result.secondary
    result.topic_confidence = topic_result.confidence

    if verbose:
        sec = f" + {', '.join(topic_result.secondary)}" if topic_result.secondary else ""
        print(f"  [1/6] TOPIC:    {topic_result.primary}{sec} "
              f"(conf: {topic_result.confidence:.2f})")

    # ─────────────────────────────────────────────────────────────────
    # STEP 2: DETECT TONE
    # ─────────────────────────────────────────────────────────────────
    tone_result = detect_tone(guest_email)
    result.tone = tone_result.tone
    result.tone_modifier = tone_result.modifier
    result.tone_confidence = tone_result.confidence
    result.escalation_required = tone_result.escalation_required

    if verbose:
        esc = " [ESCALATE]" if tone_result.escalation_required else ""
        print(f"  [2/6] TONE:     {tone_result.tone} "
              f"(conf: {tone_result.confidence:.2f}){esc}")

    # ─────────────────────────────────────────────────────────────────
    # STEP 3: SLICE CONTEXT
    # ─────────────────────────────────────────────────────────────────
    slice_result = slice_context(
        cabin_slug,
        topic_result.primary,
        topic_result.secondary or None,
    )
    result.context_tokens = slice_result.token_estimate
    result.full_context_tokens = slice_result.full_context_tokens
    result.tokens_saved = slice_result.full_context_tokens - slice_result.token_estimate
    result.topics_included = slice_result.topics_included

    if verbose:
        pct = result.savings_pct
        print(f"  [3/6] CONTEXT:  {slice_result.token_estimate} tokens "
              f"(full: {slice_result.full_context_tokens}, saved {pct:.0f}%)")
        print(f"         Sections: {', '.join(slice_result.topics_included)}")

    # ─────────────────────────────────────────────────────────────────
    # STEP 4: LOAD DYNAMIC EXAMPLES
    # ─────────────────────────────────────────────────────────────────
    examples_text = load_dynamic_examples(topic_result.primary)
    result.examples_topic = topic_result.primary

    if not examples_text:
        # Try secondary topics if no examples for primary
        for sec_topic in topic_result.secondary:
            examples_text = load_dynamic_examples(sec_topic)
            if examples_text:
                result.examples_topic = sec_topic
                break

    if examples_text:
        result.examples_loaded = examples_text.count("[Verified Response")
    else:
        examples_text = "(No proven examples for this topic yet.)"

    if verbose:
        print(f"  [4/6] EXAMPLES: {result.examples_loaded} loaded "
              f"(topic: {result.examples_topic})")

    # ─────────────────────────────────────────────────────────────────
    # STEP 5: RENDER PROMPT
    # ─────────────────────────────────────────────────────────────────
    tmpl = load_prompt("guest_email_reply")
    rendered = tmpl.render(
        cabin_context=slice_result.context,
        guest_email=guest_email,
        tone_modifier=tone_result.modifier,
        dynamic_examples=examples_text,
    )
    result.rendered_prompt = rendered
    result.prompt_tokens = len(rendered) // 4

    # Determine model
    model_name = model or tmpl.model_config.get("recommended", "deepseek-r1:70b")
    result.model = model_name

    if verbose:
        print(f"  [5/6] PROMPT:   {result.prompt_tokens} tokens -> {model_name}")

    # ─────────────────────────────────────────────────────────────────
    # STEP 6: LLM CALL (or dry-run)
    # ─────────────────────────────────────────────────────────────────
    if dry_run:
        result.draft = "[DRY RUN — No LLM call made]"
        result.success = True
        result.duration_ms = (time.time() - pipeline_start) * 1000

        if verbose:
            print(f"  [6/6] LLM:      SKIPPED (dry run)")

    else:
        try:
            from config import captain_think, CAPTAIN_MODEL

            # Use the template's recommended model if no override
            if not model:
                model_name = CAPTAIN_MODEL
                result.model = model_name

            llm_start = time.time()
            # Use the rendered prompt as the user message, with a focused system role
            system_role = (
                "You are a Customer Support AI for Cabin Rentals of Georgia (CROG). "
                "Respond using ONLY the facts provided in the prompt. "
                "Never fabricate amenities or policies."
            )
            response = captain_think(
                prompt=rendered,
                system_role=system_role,
                temperature=tmpl.model_config.get("temperature", 0.5),
            )
            result.duration_ms = (time.time() - llm_start) * 1000
            result.draft = response
            result.success = not response.startswith("[CAPTAIN ERROR]")

            if not result.success:
                result.error = response

            if verbose:
                print(f"  [6/6] LLM:      {result.duration_ms:.0f}ms "
                      f"({'OK' if result.success else 'FAIL'})")

        except ImportError as e:
            result.error = f"Config import failed: {e}"
            result.duration_ms = (time.time() - pipeline_start) * 1000

            if verbose:
                print(f"  [6/6] LLM:      IMPORT ERROR — {e}")

        except Exception as e:
            result.error = str(e)
            result.duration_ms = (time.time() - pipeline_start) * 1000

            if verbose:
                print(f"  [6/6] LLM:      ERROR — {e}")

    # ─────────────────────────────────────────────────────────────────
    # STEP 7: LOG EXECUTION
    # ─────────────────────────────────────────────────────────────────
    try:
        run_id = log_prompt_execution(
            template_name="guest_email_reply",
            version="v1",
            variables={
                "cabin_slug": cabin_slug,
                "topic": result.topic,
                "tone": result.tone,
                "topics_included": result.topics_included,
                "examples_loaded": result.examples_loaded,
                "context_tokens": result.context_tokens,
                "tokens_saved": result.tokens_saved,
            },
            rendered_prompt=rendered,
            raw_output=result.draft if result.success else None,
            model_name=result.model,
            duration_ms=result.duration_ms,
            success=result.success,
            error=result.error,
            metadata={
                "cabin_name": slice_result.cabin_name,
                "escalation_required": result.escalation_required,
                "dry_run": dry_run,
                "savings_pct": round(result.savings_pct, 1),
            },
        )
        result.run_id = run_id
    except Exception as e:
        if verbose:
            print(f"  [LOG]  Warning: Failed to log execution — {e}")

    return result


# =============================================================================
# BATCH PROCESSING
# =============================================================================

def process_batch(
    cabin_slug: str,
    emails: List[Dict[str, str]],
    model: Optional[str] = None,
    dry_run: bool = False,
    verbose: bool = False,
) -> List[ReplyResult]:
    """
    Process a batch of guest emails.

    Args:
        cabin_slug: Cabin identifier
        emails:     List of dicts with at least a "text" key (and optional "id", "from")
        model:      Override LLM model
        dry_run:    Skip LLM calls
        verbose:    Print pipeline steps

    Returns:
        List of ReplyResult objects.
    """
    results = []
    total = len(emails)

    for i, email_data in enumerate(emails, 1):
        email_text = email_data.get("text", email_data.get("body", ""))
        email_id = email_data.get("id", f"email_{i}")

        if verbose:
            print(f"\n{'─' * 60}")
            print(f"  EMAIL {i}/{total}: {email_id}")
            print(f"  Text: \"{email_text[:80]}...\"")

        result = process_email(
            cabin_slug=cabin_slug,
            guest_email=email_text,
            model=model,
            dry_run=dry_run,
            verbose=verbose,
        )
        results.append(result)

        if verbose:
            print(f"  => {result.summary()}")

    return results


# =============================================================================
# CLI INTERFACE
# =============================================================================

def build_parser() -> argparse.ArgumentParser:
    """Build the CLI argument parser."""
    parser = argparse.ArgumentParser(
        description="Fortress Prime — Guest Reply Engine",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
EXAMPLES:
  # Process a single email
  python -m src.guest_reply_engine --cabin rolling_river \\
      --email "Can I charge my Tesla at the cabin overnight?"

  # Dry run (see what would be sent to the LLM)
  python -m src.guest_reply_engine --cabin rolling_river \\
      --email "The pipes burst!" --test

  # Batch processing from a JSON file
  python -m src.guest_reply_engine --cabin rolling_river \\
      --batch inbox/pending.json

  # List available cabins
  python -m src.guest_reply_engine --list-cabins

  # Run built-in test suite
  python -m src.guest_reply_engine --demo
        """,
    )

    parser.add_argument(
        "--cabin", "-c",
        type=str,
        help="Cabin slug (e.g., rolling_river)",
    )
    parser.add_argument(
        "--email", "-e",
        type=str,
        help="Single guest email text to process",
    )
    parser.add_argument(
        "--batch", "-b",
        type=str,
        help="Path to JSON file with email batch [{\"text\": \"...\"}]",
    )
    parser.add_argument(
        "--test", "-t",
        action="store_true",
        help="Dry run — render prompt but skip LLM call",
    )
    parser.add_argument(
        "--model", "-m",
        type=str,
        help="Override LLM model (e.g., deepseek-r1:8b for faster testing)",
    )
    parser.add_argument(
        "--verbose", "-v",
        action="store_true",
        default=True,
        help="Show pipeline steps (default: on)",
    )
    parser.add_argument(
        "--quiet", "-q",
        action="store_true",
        help="Suppress pipeline output (only show draft)",
    )
    parser.add_argument(
        "--list-cabins",
        action="store_true",
        help="List available cabin data files and exit",
    )
    parser.add_argument(
        "--show-prompt",
        action="store_true",
        help="Print the full rendered prompt (useful for debugging)",
    )
    parser.add_argument(
        "--demo",
        action="store_true",
        help="Run the built-in demo with synthetic test emails",
    )

    return parser


def run_demo(cabin_slug: str):
    """Run a demo with synthetic test emails covering all scenarios."""
    print("=" * 70)
    print("  FORTRESS PRIME — GUEST REPLY ENGINE DEMO")
    print("=" * 70)
    print(f"  Cabin: {cabin_slug}")
    print(f"  Mode:  DRY RUN (no LLM calls)")

    demo_emails = [
        {
            "label": "Standard — EV Charging",
            "text": "Hi there! We just bought a Rivian R1T and we're wondering "
                    "if we can charge it at the cabin overnight? What kind of "
                    "outlet do you have?",
        },
        {
            "label": "Emergency — Pipe Burst",
            "text": "HELP! The pipes burst under the kitchen sink and water is "
                    "flooding everywhere. We've turned off the main valve but "
                    "the floor is soaked. What do we do?!",
        },
        {
            "label": "VIP — Anniversary",
            "text": "My wife and I are celebrating our 30th wedding anniversary "
                    "at your cabin next weekend! Is there anything special you "
                    "can arrange? We'd love flowers and champagne if possible.",
        },
        {
            "label": "Standard — Pet Policy",
            "text": "Do you allow dogs? We have two golden retrievers and they're "
                    "very well-behaved. What's your pet fee?",
        },
        {
            "label": "Complaint — Cleanliness",
            "text": "We are extremely disappointed. The cabin was filthy when we "
                    "arrived — hair in the shower drain, stains on the bedsheets, "
                    "and cobwebs on the ceiling fan. This is not what we paid for.",
        },
        {
            "label": "Multi-topic — Hot Tub + WiFi",
            "text": "Quick questions: 1) What temperature is the hot tub set to? "
                    "2) What's the WiFi password? We need it for work calls.",
        },
        {
            "label": "Standard — Check-in Logistics",
            "text": "What time is check-in? We're driving from Atlanta and should "
                    "arrive around 3pm. Is early check-in possible? Also, how do "
                    "we get the door code?",
        },
    ]

    for i, email in enumerate(demo_emails, 1):
        print(f"\n{'━' * 70}")
        print(f"  TEST {i}/{len(demo_emails)}: {email['label']}")
        print(f"  Email: \"{email['text'][:75]}...\"")
        print(f"{'━' * 70}")

        result = process_email(
            cabin_slug=cabin_slug,
            guest_email=email["text"],
            dry_run=True,
            verbose=True,
        )

        print(f"\n  RESULT: {result.summary()}")
        print(f"  Run ID: {result.run_id}")

    # Summary statistics
    print(f"\n{'=' * 70}")
    print(f"  DEMO COMPLETE — All {len(demo_emails)} emails processed")
    print(f"{'=' * 70}")


def main():
    """Main entry point for CLI."""
    parser = build_parser()
    args = parser.parse_args()

    verbose = not args.quiet

    # --- List cabins ---
    if args.list_cabins:
        cabins = list_cabins()
        print("Available cabins:")
        for c in cabins:
            try:
                from prompts.context_slicer import get_cabin_summary
                summary = get_cabin_summary(c)
                pet = "pet-friendly" if summary["pet_friendly"] else "no pets"
                print(f"  {c:<25} {summary['name']} "
                      f"({summary['bedrooms']}BR/{summary['bathrooms']}BA, "
                      f"sleeps {summary['max_guests']}, {pet})")
            except Exception:
                print(f"  {c}")
        return

    # --- Demo mode ---
    if args.demo:
        cabin = args.cabin or (list_cabins()[0] if list_cabins() else None)
        if not cabin:
            print("ERROR: No cabin data files found. Create one from cabins/_template.yaml")
            sys.exit(1)
        run_demo(cabin)
        return

    # --- Validate cabin ---
    if not args.cabin:
        available = list_cabins()
        print("ERROR: --cabin is required.")
        if available:
            print(f"Available cabins: {', '.join(available)}")
        else:
            print("No cabin data files found. Create one from cabins/_template.yaml")
        sys.exit(1)

    # --- Single email ---
    if args.email:
        if verbose:
            print("=" * 70)
            print("  FORTRESS PRIME — GUEST REPLY ENGINE")
            print("=" * 70)
            print(f"  Cabin: {args.cabin}")
            print(f"  Mode:  {'DRY RUN' if args.test else 'LIVE'}")
            print(f"  Email: \"{args.email[:75]}...\"" if len(args.email) > 75
                  else f"  Email: \"{args.email}\"")

        result = process_email(
            cabin_slug=args.cabin,
            guest_email=args.email,
            model=args.model,
            dry_run=args.test,
            verbose=verbose,
        )

        if args.show_prompt:
            print(f"\n{'─' * 70}")
            print("  RENDERED PROMPT:")
            print(f"{'─' * 70}")
            print(result.rendered_prompt)

        if verbose:
            print(f"\n{'─' * 70}")
            print(f"  {result.summary()}")
            print(f"  Run ID: {result.run_id}")

        if result.draft and not result.draft.startswith("[DRY RUN"):
            print(f"\n{'━' * 70}")
            print("  AI DRAFT:")
            print(f"{'━' * 70}")
            print(result.draft)
            print(f"{'━' * 70}")

        if result.escalation_required:
            print(f"\n  *** ESCALATION REQUIRED ***")
            print(f"  Tone: {result.tone} — This response needs human review.")

        return

    # --- Batch mode ---
    if args.batch:
        batch_path = Path(args.batch)
        if not batch_path.exists():
            print(f"ERROR: Batch file not found: {batch_path}")
            sys.exit(1)

        with open(batch_path, "r", encoding="utf-8") as f:
            emails = json.load(f)

        if verbose:
            print("=" * 70)
            print("  FORTRESS PRIME — BATCH PROCESSING")
            print("=" * 70)
            print(f"  Cabin:  {args.cabin}")
            print(f"  Emails: {len(emails)}")
            print(f"  Mode:   {'DRY RUN' if args.test else 'LIVE'}")

        results = process_batch(
            cabin_slug=args.cabin,
            emails=emails,
            model=args.model,
            dry_run=args.test,
            verbose=verbose,
        )

        # Summary
        success = sum(1 for r in results if r.success)
        escalations = sum(1 for r in results if r.escalation_required)
        avg_tokens = sum(r.context_tokens for r in results) / max(len(results), 1)
        avg_saved = sum(r.savings_pct for r in results) / max(len(results), 1)

        print(f"\n{'=' * 70}")
        print(f"  BATCH COMPLETE: {success}/{len(results)} succeeded")
        print(f"  Escalations:    {escalations}")
        print(f"  Avg tokens:     {avg_tokens:.0f} (avg {avg_saved:.0f}% saved by slicing)")
        print(f"{'=' * 70}")

        # Save results
        output_path = batch_path.parent / f"drafts_{batch_path.stem}.json"
        drafts = []
        for r in results:
            drafts.append({
                "run_id": r.run_id,
                "email": r.guest_email[:200],
                "topic": r.topic,
                "tone": r.tone,
                "escalation": r.escalation_required,
                "draft": r.draft,
                "success": r.success,
                "tokens_used": r.context_tokens,
                "tokens_saved": r.tokens_saved,
            })
        with open(output_path, "w", encoding="utf-8") as f:
            json.dump(drafts, f, indent=2, default=str)
        print(f"  Drafts saved to: {output_path}")

        return

    # --- No mode selected ---
    parser.print_help()


if __name__ == "__main__":
    main()
