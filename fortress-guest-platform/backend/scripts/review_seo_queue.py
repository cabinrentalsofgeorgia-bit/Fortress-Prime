"""
Human-in-the-loop CLI for reviewing and approving SEO proposals.
"""
from __future__ import annotations

import os
from typing import Iterable, Optional

from dotenv import load_dotenv
from sqlalchemy import create_engine, func, select, update
from sqlalchemy.orm import Session

from backend.models.seo_patch import SeoPatchQueue


load_dotenv()


class C:
    RESET = "\033[0m"
    BOLD = "\033[1m"
    DIM = "\033[2m"
    GREEN = "\033[92m"
    CYAN = "\033[96m"
    YELLOW = "\033[93m"
    RED = "\033[91m"
    MAGENTA = "\033[95m"
    WHITE = "\033[97m"


def _sync_url_candidates(db_url: str) -> Iterable[str]:
    """Generate sync SQLAlchemy URL candidates from DATABASE_URL."""
    if not db_url:
        return []
    urls = [db_url]
    if "postgresql+asyncpg://" in db_url:
        urls.append(db_url.replace("postgresql+asyncpg://", "postgresql+psycopg2://", 1))
        urls.append(db_url.replace("postgresql+asyncpg://", "postgresql://", 1))
    if "postgres://" in db_url:
        urls.append(db_url.replace("postgres://", "postgresql://", 1))

    deduped = []
    seen = set()
    for url in urls:
        if url and url not in seen:
            deduped.append(url)
            seen.add(url)
    return deduped


def _build_sync_engine():
    db_url = os.getenv("DATABASE_URL", "").strip()
    if not db_url:
        raise RuntimeError("DATABASE_URL is not set. Add it to .env before running.")

    last_err: Optional[Exception] = None
    for candidate in _sync_url_candidates(db_url):
        try:
            engine = create_engine(candidate, future=True)
            with engine.connect():
                pass
            print(f"{C.DIM}Using DB URL: {candidate}{C.RESET}")
            return engine
        except Exception as exc:  # noqa: BLE001
            last_err = exc

    raise RuntimeError(f"Unable to connect with sync DB driver. Last error: {last_err}")


def _truncate(text: Optional[str], limit: int = 220) -> str:
    if not text:
        return "-"
    clean = " ".join(str(text).strip().split())
    if len(clean) <= limit:
        return clean
    return clean[: limit - 3] + "..."


def _jsonld_summary(payload) -> str:
    if isinstance(payload, dict):
        keys = sorted(payload.keys())
        return f"dict keys={keys[:8]}" + (" ..." if len(keys) > 8 else "")
    if isinstance(payload, list):
        return f"list len={len(payload)}"
    if payload in (None, "", {}):
        return "empty"
    return _truncate(str(payload), limit=140)


def _render_record(patch: SeoPatchQueue, index: int, total: int) -> None:
    print(f"\n{C.MAGENTA}{C.BOLD}{'=' * 84}{C.RESET}")
    print(f"{C.MAGENTA}{C.BOLD}SEO Queue Review [{index}/{total}] id={patch.id}{C.RESET}")
    print(f"{C.MAGENTA}{C.BOLD}{'=' * 84}{C.RESET}")

    print(
        f"{C.WHITE}Property:{C.RESET} {patch.property_id}    "
        f"{C.WHITE}Campaign:{C.RESET} {patch.campaign or '-'}    "
        f"{C.WHITE}Keyword:{C.RESET} {patch.target_keyword or '-'}"
    )
    print(f"{C.WHITE}Score:{C.RESET} {patch.score_overall if patch.score_overall is not None else '-'}")
    print(f"{C.GREEN}{C.BOLD}Title:{C.RESET} {_truncate(patch.proposed_title, limit=180)}")
    print(f"{C.GREEN}{C.BOLD}H1:{C.RESET} {_truncate(patch.proposed_h1, limit=180)}")
    print(f"{C.YELLOW}{C.BOLD}Meta:{C.RESET} {_truncate(patch.proposed_meta_description, limit=260)}")
    print(f"{C.CYAN}{C.BOLD}JSON-LD:{C.RESET} {_jsonld_summary(patch.proposed_json_ld)}")


def _build_approved_payload(patch: SeoPatchQueue) -> dict:
    return {
        "title": patch.proposed_title or "",
        "meta_description": patch.proposed_meta_description or "",
        "h1": patch.proposed_h1 or "",
        "intro": patch.proposed_intro or "",
        "faq": patch.proposed_faq or [],
        "json_ld": patch.proposed_json_ld or {},
        "score_overall": patch.score_overall,
        "score_breakdown": patch.score_breakdown or {},
        "campaign": patch.campaign or "default",
        "target_keyword": patch.target_keyword or "",
    }


def main() -> int:
    engine = _build_sync_engine()

    with Session(engine) as session:
        rows = (
            session.execute(
                select(SeoPatchQueue)
                .where(SeoPatchQueue.status == "proposed")
                .order_by(SeoPatchQueue.created_at.asc())
            )
            .scalars()
            .all()
        )

        if not rows:
            print("Queue is empty.")
            return 0

        print(f"{C.BOLD}Found {len(rows)} proposed SEO patch(es).{C.RESET}")

        approved = 0
        rejected = 0
        skipped = 0

        for idx, patch in enumerate(rows, start=1):
            _render_record(patch, idx, len(rows))

            while True:
                action = input(
                    f"{C.BOLD}Action [y=Approve, n=Reject, s=Skip, q=Quit]: {C.RESET}"
                ).strip().lower()
                if action in {"y", "n", "s", "q"}:
                    break
                print(f"{C.RED}Invalid action. Use y, n, s, or q.{C.RESET}")

            if action == "q":
                print(f"{C.DIM}Quit requested. Stopping review loop.{C.RESET}")
                break

            if action == "s":
                skipped += 1
                print(f"{C.DIM}Skipped.{C.RESET}")
                continue

            if action == "y":
                approved_payload = _build_approved_payload(patch)
                session.execute(
                    update(SeoPatchQueue)
                    .where(SeoPatchQueue.id == patch.id)
                    .values(
                        status="approved",
                        approved_at=func.now(),
                        approved_payload=approved_payload,
                    )
                )
                session.commit()
                approved += 1
                print(f"{C.GREEN}Approved.{C.RESET}")
                continue

            session.execute(
                update(SeoPatchQueue)
                .where(SeoPatchQueue.id == patch.id)
                .values(status="rejected")
            )
            session.commit()
            rejected += 1
            print(f"{C.RED}Rejected.{C.RESET}")

        print(
            f"\n{C.BOLD}Review summary:{C.RESET} "
            f"approved={approved} rejected={rejected} skipped={skipped}"
        )
        return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except KeyboardInterrupt:
        print("\nInterrupted.")
        raise SystemExit(130)
