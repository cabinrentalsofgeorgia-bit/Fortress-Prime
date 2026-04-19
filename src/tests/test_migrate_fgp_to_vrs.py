"""
Tests for migrate_fgp_to_vrs.py — Phase 5a Part 2 snapshot migration.

Mocks both Qdrant clients; tests safety checks, batch pagination,
force flag, dimension mismatch, and byte-equality verification.
"""
from __future__ import annotations

import sys
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import rag.migrate_fgp_to_vrs as m


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

def _make_collection_info(points: int, dim: int = 768, dist: str = "Cosine") -> MagicMock:
    info = MagicMock()
    info.points_count = points
    info.config.params.vectors.size = dim
    info.config.params.vectors.distance.name = dist
    return info


def _make_point(pid: str, vec: list[float] | None = None) -> MagicMock:
    p = MagicMock()
    p.id = pid
    p.vector = vec or [0.01] * 768
    p.payload = {"source_table": "test", "record_id": pid}
    return p


# ---------------------------------------------------------------------------
# _verify_schemas
# ---------------------------------------------------------------------------

class TestVerifySchemas:
    def _run(self, src_pts=168, src_dim=768, src_dist="Cosine",
             tgt_pts=0, tgt_dim=768, tgt_dist="Cosine"):
        source = MagicMock()
        target = MagicMock()
        source.get_collection.return_value = _make_collection_info(src_pts, src_dim, src_dist)
        target.get_collection.return_value = _make_collection_info(tgt_pts, tgt_dim, tgt_dist)
        return m._verify_schemas(source, target)

    def test_happy_path(self):
        src, tgt = self._run()
        assert src == 168 and tgt == 0

    def test_source_empty_raises(self):
        with pytest.raises(ValueError, match="empty"):
            self._run(src_pts=0)

    def test_source_dim_mismatch_raises(self):
        with pytest.raises(ValueError, match="Source dimension"):
            self._run(src_dim=1024)

    def test_target_dim_mismatch_raises(self):
        with pytest.raises(ValueError, match="Target dimension"):
            self._run(tgt_dim=512)

    def test_source_distance_mismatch_raises(self):
        with pytest.raises(ValueError, match="Source distance"):
            self._run(src_dist="Euclid")

    def test_target_distance_mismatch_raises(self):
        with pytest.raises(ValueError, match="Target distance"):
            self._run(tgt_dist="Dot")


# ---------------------------------------------------------------------------
# _scroll_all — batch pagination
# ---------------------------------------------------------------------------

class TestScrollAll:
    def test_single_batch_no_next_offset(self):
        """All points fit in one scroll — next_offset is None."""
        pts = [_make_point(f"id-{i}") for i in range(10)]
        source = MagicMock()
        source.scroll.return_value = (pts, None)

        result = m._scroll_all(source, batch_size=64)
        assert len(result) == 10
        source.scroll.assert_called_once()

    def test_multi_batch_pagination(self):
        """Two batches: first returns next_offset, second returns None."""
        batch1 = [_make_point(f"a{i}") for i in range(3)]
        batch2 = [_make_point(f"b{i}") for i in range(2)]
        source = MagicMock()
        source.scroll.side_effect = [
            (batch1, "next-cursor"),
            (batch2, None),
        ]

        result = m._scroll_all(source, batch_size=3)
        assert len(result) == 5
        assert source.scroll.call_count == 2
        # First call has offset=None, second has offset="next-cursor"
        first_call = source.scroll.call_args_list[0]
        assert first_call.kwargs.get("offset") is None or first_call.args[1] is None

    def test_empty_batch_stops_immediately(self):
        source = MagicMock()
        source.scroll.return_value = ([], None)
        result = m._scroll_all(source, batch_size=64)
        assert result == []


# ---------------------------------------------------------------------------
# run() — empty-target safety check and force flag
# ---------------------------------------------------------------------------

class TestRunSafetyAndForce:
    def _patched_run(self, src_pts=168, tgt_pts=0, force=False, dry_run=False):
        # _scroll_all must return exactly src_pts points to pass the count check
        fake_points = [_make_point(f"p{i}") for i in range(src_pts)]
        with (
            patch("rag.migrate_fgp_to_vrs._make_client") as mock_client,
            patch("rag.migrate_fgp_to_vrs._scroll_all", return_value=fake_points) as _scroll,
            patch("rag.migrate_fgp_to_vrs._upsert_batched", return_value=src_pts) as _upsert,
            patch("rag.migrate_fgp_to_vrs._verify", return_value=True) as _verify,
        ):
            source_mock = MagicMock()
            target_mock = MagicMock()
            mock_client.side_effect = [source_mock, target_mock]
            source_mock.get_collection.return_value = _make_collection_info(src_pts)
            target_mock.get_collection.return_value = _make_collection_info(tgt_pts)

            rc = m.run(dry_run=dry_run, batch_size=64, force=force)
            return rc, _scroll, _upsert, _verify

    def test_dry_run_returns_0_no_writes(self):
        rc, scroll, upsert, verify = self._patched_run(dry_run=True)
        assert rc == 0
        scroll.assert_not_called()
        upsert.assert_not_called()

    def test_empty_target_proceeds(self):
        rc, scroll, upsert, _ = self._patched_run(tgt_pts=0)
        assert rc == 0
        scroll.assert_called_once()
        upsert.assert_called_once()

    def test_non_empty_target_without_force_returns_1(self):
        rc, scroll, upsert, _ = self._patched_run(tgt_pts=50, force=False)
        assert rc == 1
        scroll.assert_not_called()
        upsert.assert_not_called()

    def test_non_empty_target_with_force_proceeds(self):
        rc, scroll, upsert, _ = self._patched_run(tgt_pts=50, force=True)
        assert rc == 0
        scroll.assert_called_once()
        upsert.assert_called_once()

    def test_verification_fail_returns_2(self):
        fake_points = [_make_point(f"p{i}") for i in range(168)]
        with (
            patch("rag.migrate_fgp_to_vrs._make_client") as mock_client,
            patch("rag.migrate_fgp_to_vrs._scroll_all", return_value=fake_points),
            patch("rag.migrate_fgp_to_vrs._upsert_batched", return_value=168),
            patch("rag.migrate_fgp_to_vrs._verify", return_value=False),
        ):
            src = MagicMock(); tgt = MagicMock()
            mock_client.side_effect = [src, tgt]
            src.get_collection.return_value = _make_collection_info(168)
            tgt.get_collection.return_value = _make_collection_info(0)
            rc = m.run(dry_run=False, batch_size=64, force=False)
        assert rc == 2


# ---------------------------------------------------------------------------
# _verify — count parity and vector spot-check
# ---------------------------------------------------------------------------

class TestVerify:
    def _make_clients(self, src_vecs: dict[str, list[float]],
                      tgt_vecs: dict[str, list[float]]):
        source = MagicMock()
        target = MagicMock()

        sample_pts = [_make_point(pid, vec) for pid, vec in src_vecs.items()]
        source.scroll.return_value = (sample_pts, None)

        tgt_pts = [_make_point(pid, vec) for pid, vec in tgt_vecs.items()]
        target.retrieve.return_value = tgt_pts
        return source, target

    def test_all_match_returns_true(self):
        vecs = {f"p{i}": [float(i)] * 768 for i in range(5)}
        source, target = self._make_clients(vecs, vecs)
        assert m._verify(source, target, src_count=5, tgt_count=5) is True

    def test_count_mismatch_returns_false(self):
        vecs = {f"p{i}": [0.1] * 768 for i in range(5)}
        source, target = self._make_clients(vecs, vecs)
        assert m._verify(source, target, src_count=5, tgt_count=4) is False

    def test_vector_mismatch_returns_false(self):
        src_vecs = {"p0": [1.0] * 768}
        tgt_vecs = {"p0": [2.0] * 768}  # different vector
        source, target = self._make_clients(src_vecs, tgt_vecs)
        assert m._verify(source, target, src_count=1, tgt_count=1) is False

    def test_missing_point_on_target_returns_false(self):
        src_vecs = {"p0": [1.0] * 768}
        source, target = self._make_clients(src_vecs, {})  # target has no points
        assert m._verify(source, target, src_count=1, tgt_count=1) is False

    def test_identical_vectors_byte_exact(self):
        """Verify the comparison is strict equality, not approximate."""
        vec = [0.123456789] * 768
        src_vecs = {"p0": vec}
        tgt_vecs = {"p0": vec[:]}  # same values, different list object
        source, target = self._make_clients(src_vecs, tgt_vecs)
        assert m._verify(source, target, src_count=1, tgt_count=1) is True
