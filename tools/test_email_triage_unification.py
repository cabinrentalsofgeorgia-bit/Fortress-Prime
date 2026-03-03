#!/usr/bin/env python3
"""Quick preflight for unified email triage path."""

import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from src.utils.text_sanitizer import sanitize_email_text
from tools.batch_classifier import classify_document


def main() -> int:
    raw_body = """
    <html>
      <head><style>.x{display:none}</style><script>alert(1)</script></head>
      <body>Synology NAS alert: volume degraded &zwnj; immediate action required.</body>
    </html>
    """
    clean_body = sanitize_email_text(raw_body)
    result = classify_document(
        clean_body,
        context="email_triage",
        metadata={"source": "test_email_triage_unification"},
    )

    required = {"division", "priority", "confidence", "summary", "context", "metadata"}
    missing = required.difference(result.keys())
    if missing:
        raise RuntimeError(f"Missing keys in classifier result: {sorted(missing)}")

    print("sanitized_body:", clean_body)
    print("classifier_result:", result)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
