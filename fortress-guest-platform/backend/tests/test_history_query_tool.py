from __future__ import annotations

import asyncio
import csv
import json
import os
import sys
from pathlib import Path

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

from backend.services.history_query_tool import HistoryLibrarian


def _write_csv(path: Path) -> None:
    rows = [
        {
            "property_id": "lot-9",
            "stay_date": "2023-05-26",
            "nightly_rate": "395.00",
            "total_revenue": "1185.00",
            "guests": "6",
            "nights": "3",
            "booked_at": "2023-02-01",
            "addons_total": "125.00",
            "notes": "Wedding weekend add-on bundle purchased.",
            "event_type": "wedding",
            "is_occupied": "true",
        },
        {
            "property_id": "lot-9",
            "stay_date": "2024-05-24",
            "nightly_rate": "425.00",
            "total_revenue": "1275.00",
            "guests": "6",
            "nights": "3",
            "booked_at": "2024-01-15",
            "addons_total": "150.00",
            "notes": "Wedding weekend with late checkout add-on.",
            "event_type": "wedding",
            "is_occupied": "true",
        },
        {
            "property_id": "lot-9",
            "stay_date": "2025-05-23",
            "nightly_rate": "455.00",
            "total_revenue": "1365.00",
            "guests": "6",
            "nights": "3",
            "booked_at": "2025-01-05",
            "addons_total": "175.00",
            "notes": "Wedding weekend. Guest accepted celebration package.",
            "event_type": "wedding",
            "is_occupied": "true",
        },
        {
            "property_id": "lot-9",
            "stay_date": "2025-10-10",
            "nightly_rate": "290.00",
            "total_revenue": "580.00",
            "guests": "2",
            "nights": "2",
            "booked_at": "2025-09-26",
            "addons_total": "0.00",
            "notes": "Guest said the price felt too much for foliage season.",
            "event_type": "leaf season",
            "is_occupied": "true",
        },
        {
            "property_id": "lot-2",
            "stay_date": "2025-05-23",
            "nightly_rate": "310.00",
            "total_revenue": "930.00",
            "guests": "4",
            "nights": "3",
            "booked_at": "2025-03-01",
            "addons_total": "0.00",
            "notes": "Memorial Day stay.",
            "event_type": "holiday",
            "is_occupied": "true",
        },
    ]
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(rows[0].keys()))
        writer.writeheader()
        writer.writerows(rows)


def test_history_query_returns_wedding_weekend_context(tmp_path: Path) -> None:
    history_dir = tmp_path / "history"
    history_dir.mkdir()
    _write_csv(history_dir / "sales_2021_2025.csv")

    librarian = HistoryLibrarian(history_path=str(history_dir), index_path=str(history_dir / ".idx"))
    result = asyncio.run(
        librarian.get_lookalike_context(
            property_id="lot-9",
            target_date="2026-05-22",
            guests=6,
            nights=3,
            event_hint="wedding",
            top_k=5,
        )
    )

    assert result["status"] == "ok"
    assert result["comparison_scope"] == "same_property_same_month"
    assert result["match_count"] >= 3
    assert result["last_year_rate"] == 455.0
    assert result["historical_peak"] == 455.0
    assert result["historical_avg"] >= 425.0
    assert result["opportunity_gap_suggested"] > 0
    assert result["occupancy_trend"] in {"HIGH", "MEDIUM"}
    assert result["lookalikes"][0]["property_id"] == "lot-9"


def test_history_index_rebuild_persists_manifest(tmp_path: Path) -> None:
    history_dir = tmp_path / "history"
    history_dir.mkdir()
    _write_csv(history_dir / "sales.csv")
    with (history_dir / "archive.json").open("w", encoding="utf-8") as handle:
        json.dump(
            {
                "records": [
                    {
                        "property_id": "lot-9",
                        "stay_date": "2022-05-27",
                        "nightly_rate": 360.0,
                        "total_revenue": 1080.0,
                        "guests": 6,
                        "nights": 3,
                        "booked_at": "2022-02-10",
                        "addons_total": 90.0,
                        "notes": "Wedding weekend archived in JSON.",
                        "event_type": "wedding",
                        "is_occupied": True,
                    }
                ]
            },
            handle,
        )

    index_dir = history_dir / ".idx"
    librarian = HistoryLibrarian(history_path=str(history_dir), index_path=str(index_dir))
    result = asyncio.run(librarian.rebuild_persistent_index())

    assert result["status"] == "ok"
    assert result["record_count"] >= 2
    manifest = json.loads((index_dir / "history_manifest.json").read_text(encoding="utf-8"))
    assert manifest["record_count"] == result["record_count"]
    assert Path(manifest["records_path"]).exists()
