"""
Tests for dedup winner-selection stability in backfill_label_historical.

The dedup rule: for each MD5(user_prompt) cluster, the winner is the row
with the longest assistant_resp, tie-broken by oldest created_at (ASC).
This must be deterministic: same input → same winner, always.
"""
from __future__ import annotations

from datetime import datetime, timezone
from hashlib import md5


# ---------------------------------------------------------------------------
# Extracted winner-selection logic (mirrors the SQL ORDER BY in backfill)
# ---------------------------------------------------------------------------

def select_winner(rows: list[dict]) -> str:
    """
    Given a list of rows from the same prompt-hash cluster, return the id
    of the winner using the same rule as the SQL CTE:
      ORDER BY LENGTH(assistant_resp) DESC, created_at ASC
    """
    return sorted(
        rows,
        key=lambda r: (-len(r["assistant_resp"]), r["created_at"]),
    )[0]["id"]


def partition_by_prompt(rows: list[dict]) -> dict[str, list[dict]]:
    """Group rows by MD5(user_prompt), mirroring the SQL PARTITION BY."""
    clusters: dict[str, list[dict]] = {}
    for row in rows:
        key = md5(row["user_prompt"].encode()).hexdigest()
        clusters.setdefault(key, []).append(row)
    return clusters


def apply_dedup(rows: list[dict]) -> dict[str, bool]:
    """Return {id: is_winner} for all rows."""
    clusters = partition_by_prompt(rows)
    result: dict[str, bool] = {}
    for cluster_rows in clusters.values():
        winner_id = select_winner(cluster_rows)
        for row in cluster_rows:
            result[row["id"]] = row["id"] == winner_id
    return result


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _ts(s: str) -> datetime:
    return datetime.fromisoformat(s).replace(tzinfo=timezone.utc)


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------

class TestSelectWinner:
    def test_longest_response_wins(self):
        rows = [
            {"id": "a", "user_prompt": "same", "assistant_resp": "short",    "created_at": _ts("2026-03-14T10:00:00")},
            {"id": "b", "user_prompt": "same", "assistant_resp": "much longer response here",  "created_at": _ts("2026-03-14T10:01:00")},
            {"id": "c", "user_prompt": "same", "assistant_resp": "medium length resp",         "created_at": _ts("2026-03-14T10:02:00")},
        ]
        assert select_winner(rows) == "b"

    def test_tiebreak_oldest_wins(self):
        rows = [
            {"id": "newer", "user_prompt": "same", "assistant_resp": "equal length!!", "created_at": _ts("2026-03-14T12:00:00")},
            {"id": "older", "user_prompt": "same", "assistant_resp": "equal length!!", "created_at": _ts("2026-03-14T10:00:00")},
        ]
        assert select_winner(rows) == "older"

    def test_singleton_wins(self):
        rows = [
            {"id": "only", "user_prompt": "unique", "assistant_resp": "response", "created_at": _ts("2026-03-14T10:00:00")},
        ]
        assert select_winner(rows) == "only"

    def test_stable_repeated_calls(self):
        """Same input → same winner across multiple calls."""
        rows = [
            {"id": f"row{i}", "user_prompt": "p", "assistant_resp": "x" * (10 - i), "created_at": _ts(f"2026-03-14T{10+i:02d}:00:00")}
            for i in range(5)
        ]
        first = select_winner(rows)
        for _ in range(10):
            assert select_winner(rows) == first, "winner selection is not stable"

    def test_stable_with_shuffled_input(self):
        """Winner must be the same regardless of row ordering."""
        import random
        rows = [
            {"id": "long",   "user_prompt": "p", "assistant_resp": "a" * 100, "created_at": _ts("2026-03-14T12:00:00")},
            {"id": "short1", "user_prompt": "p", "assistant_resp": "b" * 10,  "created_at": _ts("2026-03-14T10:00:00")},
            {"id": "short2", "user_prompt": "p", "assistant_resp": "c" * 10,  "created_at": _ts("2026-03-14T11:00:00")},
        ]
        expected = select_winner(rows)
        for _ in range(20):
            shuffled = rows[:]
            random.shuffle(shuffled)
            assert select_winner(shuffled) == expected


class TestApplyDedup:
    def test_all_singletons_are_winners(self):
        rows = [
            {"id": f"r{i}", "user_prompt": f"unique prompt {i}", "assistant_resp": "resp", "created_at": _ts("2026-03-14T10:00:00")}
            for i in range(5)
        ]
        result = apply_dedup(rows)
        assert all(result.values()), "all singletons should be winners"

    def test_exactly_one_winner_per_cluster(self):
        rows = [
            {"id": "a1", "user_prompt": "cluster_a", "assistant_resp": "short",  "created_at": _ts("2026-03-14T10:00:00")},
            {"id": "a2", "user_prompt": "cluster_a", "assistant_resp": "longer", "created_at": _ts("2026-03-14T10:01:00")},
            {"id": "a3", "user_prompt": "cluster_a", "assistant_resp": "medium len", "created_at": _ts("2026-03-14T10:02:00")},
            {"id": "b1", "user_prompt": "cluster_b", "assistant_resp": "x" * 50, "created_at": _ts("2026-03-14T11:00:00")},
            {"id": "b2", "user_prompt": "cluster_b", "assistant_resp": "x" * 50, "created_at": _ts("2026-03-14T12:00:00")},
        ]
        result = apply_dedup(rows)
        winners = [id_ for id_, w in result.items() if w]
        assert len(winners) == 2  # one per cluster

    def test_terri_shea_cluster_picks_correct_winner(self):
        """Simulates the 29-row Terri Shea cluster. The oldest row with the
        longest response must win, not an arbitrary row."""
        base_resp = "turnover_json_" + "x" * 200
        long_resp  = "turnover_json_" + "x" * 300  # this one should win

        rows = [
            {"id": f"ts{i}", "user_prompt": "Terri Shea checkout", "assistant_resp": base_resp,
             "created_at": _ts(f"2026-03-14T{17 + i//6:02d}:{(i*10)%60:02d}:00")}
            for i in range(28)
        ]
        # Insert the long-response row at a non-first position
        rows.insert(14, {
            "id": "ts_winner",
            "user_prompt": "Terri Shea checkout",
            "assistant_resp": long_resp,
            "created_at": _ts("2026-03-14T18:00:00"),
        })
        result = apply_dedup(rows)
        assert result["ts_winner"] is True
        assert sum(result.values()) == 1
