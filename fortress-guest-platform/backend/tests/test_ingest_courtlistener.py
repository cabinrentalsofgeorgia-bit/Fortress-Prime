"""
Tests for backend.scripts.ingest_courtlistener.

All tests use temporary JSONL fixtures + an in-memory (tmp-path-backed)
sqlite state DB. The embedder and Qdrant sink are stubbed — no network
I/O, no real Qdrant, no real Ollama.
"""
from __future__ import annotations

import asyncio
import json
from pathlib import Path

from backend.scripts.ingest_courtlistener import (
    DryRunEmbedder,
    DryRunSink,
    IngestConfig,
    IngestState,
    VECTOR_DIM,
    build_point,
    chunk_by_words,
    iter_opinions,
    run_ingest,
)


# ─────────────────────────────────────────────────────────────────────────────
# Fixtures
# ─────────────────────────────────────────────────────────────────────────────

def _opinion(opinion_id: str, text: str = "", case_name: str | None = None) -> dict:
    # Default opinion body long enough to produce at least a handful of
    # chunks when split at 1500-token chunks with 150-token overlap.
    if not text:
        text = " ".join(f"word{n:04d}" for n in range(4000))
    return {
        "opinion_id":      opinion_id,
        "cluster_id":      f"c{opinion_id}",
        "case_name":       case_name or f"Case {opinion_id}",
        "court":           "Court of Appeals of Georgia",
        "date_filed":      "2024-01-01",
        "citation":        [f"123 S.E.2d {opinion_id}"],
        "plain_text":      text,
        "plain_text_chars": len(text),
    }


def _write_jsonl(path: Path, opinions: list[dict]) -> Path:
    with path.open("w", encoding="utf-8") as fh:
        for op in opinions:
            fh.write(json.dumps(op) + "\n")
    return path


class _RecordingEmbedder:
    """Returns a deterministic dummy 768-vector; records every call."""
    def __init__(self) -> None:
        self.calls: list[str] = []

    async def embed(self, text: str) -> list[float]:
        self.calls.append(text)
        return [0.0001 * (len(text) % 1000)] * VECTOR_DIM


class _RecordingSink:
    """Collect upserts without hitting Qdrant."""
    def __init__(self) -> None:
        self.ensure_calls: list[int] = []
        self.reset_calls: int = 0
        self.upsert_batches: list[list[dict]] = []

    def ensure_collection(self, dim: int) -> None:
        self.ensure_calls.append(dim)

    def reset(self) -> None:
        self.reset_calls += 1

    def upsert(self, points: list[dict]) -> None:
        self.upsert_batches.append(list(points))


# ─────────────────────────────────────────────────────────────────────────────
# 1. Dedup across full + expanded
# ─────────────────────────────────────────────────────────────────────────────

class TestIngestDedupByOpinionId:
    def test_ingest_dedup_by_opinion_id(self, tmp_path: Path):
        """
        opinions-full lists an opinion; opinions-expanded lists the same
        opinion_id plus a new one. iter_opinions must yield each
        opinion_id at most once, with the 'full' copy winning.
        """
        full = _write_jsonl(tmp_path / "opinions-full.jsonl", [
            _opinion("A1", case_name="Full version A1"),
            _opinion("A2"),
        ])
        expanded = _write_jsonl(tmp_path / "opinions-expanded.jsonl", [
            _opinion("A1", case_name="Expanded version A1 (should be dropped)"),
            _opinion("A3"),
        ])

        results = list(iter_opinions([full, expanded]))
        ids = [op["opinion_id"] for op, _ in results]
        labels_by_id = {op["opinion_id"]: label for op, label in results}

        assert ids == ["A1", "A2", "A3"]
        # Dedup kept the 'full' copy of the overlapping id.
        assert labels_by_id["A1"] == "opinions-full"
        assert labels_by_id["A3"] == "opinions-expanded"
        first_a1 = next(op for op, _ in results if op["opinion_id"] == "A1")
        assert first_a1["case_name"] == "Full version A1"


# ─────────────────────────────────────────────────────────────────────────────
# 2. Chunking preserves citation context (overlap)
# ─────────────────────────────────────────────────────────────────────────────

class TestChunkingPreservesCitationContext:
    def test_chunking_preserves_citation_context(self):
        """
        Consecutive chunks must share >= 100 tokens of overlap so a
        citation spanning the boundary is visible to both neighbours.
        """
        text = " ".join(f"t{n:05d}" for n in range(4000))
        chunks = chunk_by_words(text, size=1500, overlap=150)
        assert len(chunks) >= 3, "need at least 3 chunks to check multiple overlaps"

        for left, right in zip(chunks, chunks[1:]):
            left_tail = left.split()[-150:]
            right_head = right.split()[:150]
            # Overlap is the intersection of adjacent slice sets.
            # For a deterministic contiguous sequence they should match.
            overlap_tokens = set(left_tail) & set(right_head)
            assert len(overlap_tokens) >= 100, (
                f"overlap between adjacent chunks is {len(overlap_tokens)} "
                f"tokens, want >= 100"
            )

    def test_chunking_single_chunk_when_short(self):
        """Short text produces exactly one chunk, no overlap needed."""
        chunks = chunk_by_words("hello world", size=1500, overlap=150)
        assert chunks == ["hello world"]

    def test_chunking_empty_returns_empty(self):
        assert chunk_by_words("") == []
        assert chunk_by_words("   ") == []


# ─────────────────────────────────────────────────────────────────────────────
# 3. Idempotent re-run — second pass skips completed opinion_ids
# ─────────────────────────────────────────────────────────────────────────────

class TestIngestionIdempotent:
    def test_ingestion_idempotent(self, tmp_path: Path):
        full = _write_jsonl(tmp_path / "opinions-full.jsonl", [
            _opinion("OP1", text="body one " * 200),
            _opinion("OP2", text="body two " * 200),
        ])
        state_path = tmp_path / ".state.db"
        cfg = IngestConfig(
            sources=[full], state_db=state_path, batch_size=4,
            chunk_tokens=500, overlap_tokens=50, log_every=1000,
        )

        # Run 1: fresh state — both opinions processed.
        state1 = IngestState(state_path)
        emb1 = _RecordingEmbedder()
        sink1 = _RecordingSink()
        stats1 = asyncio.run(run_ingest(cfg, state1, emb1, sink1))
        state1.close()
        assert stats1.opinions_processed == 2
        assert stats1.opinions_skipped_completed == 0
        first_run_chunks = stats1.chunks_written
        assert first_run_chunks >= 2

        # Run 2: same state DB, no --reset. Both opinions skipped,
        # no embed calls, no upserts.
        state2 = IngestState(state_path)
        emb2 = _RecordingEmbedder()
        sink2 = _RecordingSink()
        stats2 = asyncio.run(run_ingest(cfg, state2, emb2, sink2))
        state2.close()
        assert stats2.opinions_seen == 2
        assert stats2.opinions_processed == 0
        assert stats2.opinions_skipped_completed == 2
        assert stats2.chunks_written == 0
        assert emb2.calls == []
        assert sink2.upsert_batches == []

    def test_reset_flag_reprocesses_everything(self, tmp_path: Path):
        full = _write_jsonl(tmp_path / "opinions-full.jsonl", [
            _opinion("OP1", text="body one " * 200),
        ])
        state_path = tmp_path / ".state.db"
        cfg = IngestConfig(
            sources=[full], state_db=state_path, batch_size=4,
            chunk_tokens=500, overlap_tokens=50, log_every=1000,
        )

        # Pre-populate state with OP1 to simulate a prior run.
        st = IngestState(state_path)
        st.mark_completed("OP1", 3, "prior-run")
        st.close()

        state2 = IngestState(state_path)
        emb = _RecordingEmbedder()
        sink = _RecordingSink()
        cfg_reset = IngestConfig(**{**cfg.__dict__, "reset": True})
        stats = asyncio.run(run_ingest(cfg_reset, state2, emb, sink))
        state2.close()

        assert sink.reset_calls == 1, "reset must drop the qdrant collection"
        assert stats.opinions_processed == 1, "reset must reprocess everything"
        assert stats.opinions_skipped_completed == 0


# ─────────────────────────────────────────────────────────────────────────────
# 4. Payload shape matches spec
# ─────────────────────────────────────────────────────────────────────────────

REQUIRED_PAYLOAD_FIELDS = frozenset({
    "opinion_id",
    "cluster_id",
    "case_name",
    "court",
    "date_filed",
    "citation",
    "chunk_index",
    "text_chunk",
    "plain_text_chars_total",
    "source_file",
    "ingested_at",
    "ingestion_run_id",
})


class TestPayloadShapeMatchesSpec:
    def test_build_point_payload_carries_every_spec_field(self):
        opinion = _opinion("OP42", text="some body text")
        vec = [0.1] * VECTOR_DIM
        point = build_point(
            opinion=opinion, chunk_index=2, chunk_text="chunked body",
            vector=vec, source_label="opinions-full", run_id="run-xyz",
        )
        assert set(point["payload"].keys()) == REQUIRED_PAYLOAD_FIELDS
        p = point["payload"]
        assert p["opinion_id"] == "OP42"
        assert p["cluster_id"] == "cOP42"
        assert p["case_name"] == "Case OP42"
        assert p["court"] == "Court of Appeals of Georgia"
        assert p["date_filed"] == "2024-01-01"
        assert p["citation"] == ["123 S.E.2d OP42"]
        assert p["chunk_index"] == 2
        assert p["text_chunk"] == "chunked body"
        assert p["plain_text_chars_total"] == len("some body text")
        assert p["source_file"] == "opinions-full"
        assert p["ingestion_run_id"] == "run-xyz"
        assert point["vector"] is vec

    def test_build_point_id_is_deterministic_uuid5(self):
        opinion = _opinion("STABLE_OP")
        v = [0.0] * VECTOR_DIM
        p_a = build_point(opinion, 0, "chunk0", v, "opinions-full", "run1")
        p_b = build_point(opinion, 0, "chunk0", v, "opinions-full", "run2")
        p_c = build_point(opinion, 1, "chunk1", v, "opinions-full", "run1")
        # Same (opinion_id, chunk_index) -> same id regardless of run_id.
        assert p_a["id"] == p_b["id"]
        # Different chunk_index -> different id.
        assert p_a["id"] != p_c["id"]


# ─────────────────────────────────────────────────────────────────────────────
# 5. Dry-run does not call Qdrant or embed
# ─────────────────────────────────────────────────────────────────────────────

class TestDryRunDoesNotCallQdrantOrEmbed:
    def test_dry_run_does_not_call_qdrant_or_embed(self, tmp_path: Path):
        """
        Dry-run must parse + chunk + count, and MUST NOT invoke the
        embedder or the Qdrant sink. We install the explosive dry-run
        stubs shipped with the module; any invocation raises
        AssertionError, which would surface through run_ingest.errors.
        """
        full = _write_jsonl(tmp_path / "opinions-full.jsonl", [
            _opinion("DR1", text="body one " * 200),
            _opinion("DR2", text="body two " * 200),
        ])
        state = IngestState(tmp_path / ".state.db")
        cfg = IngestConfig(
            sources=[full],
            state_db=tmp_path / ".state.db",
            batch_size=4,
            chunk_tokens=500,
            overlap_tokens=50,
            dry_run=True,
            log_every=1000,
        )
        stats = asyncio.run(run_ingest(
            cfg, state, DryRunEmbedder(), DryRunSink(),
        ))
        state.close()

        assert stats.errors == 0, (
            "dry-run must not raise — stubs would have fired AssertionError"
        )
        assert stats.opinions_processed == 2
        assert stats.chunks_written >= 2
        # Dry-run intentionally does NOT write state, so future real
        # runs don't think these opinions are already done.
        state_reopen = IngestState(tmp_path / ".state.db")
        assert not state_reopen.already_completed("DR1")
        assert not state_reopen.already_completed("DR2")
        state_reopen.close()
