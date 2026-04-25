"""
Tests for backend.scripts.ingest_courtlistener_11th_cir.

CourtListener API is fully stubbed via http_get injection; embedder
and Qdrant sink are stubbed; sqlite state goes to tmp_path. No real
network, no real Qdrant, no real Ollama.
"""
from __future__ import annotations

import asyncio
import json
from pathlib import Path

from backend.scripts.ingest_courtlistener_11th_cir import (
    COLLECTION_NAME,
    DEFAULT_SINCE,
    JURISDICTION_TAG,
    VECTOR_DIM,
    IngestConfig,
    IngestState,
    build_point,
    fetch_ca11_to_jsonl,
    run_ingest,
)


# ─────────────────────────────────────────────────────────────────────────────
# Fixtures / fakes
# ─────────────────────────────────────────────────────────────────────────────

def _ca11_opinion(
    opinion_id: str = "OP1",
    case_name: str = "Smith v. Jones",
    text: str | None = None,
    judge: str = "Hon. Jane Doe",
) -> dict:
    if text is None:
        # 4000 words → multiple chunks at default 1500/150 tokens
        text = " ".join(f"word{n:04d}" for n in range(4000))
    return {
        "opinion_id":       opinion_id,
        "cluster_id":       f"c-{opinion_id}",
        "case_name":        case_name,
        "court":            "United States Court of Appeals for the Eleventh Circuit",
        "court_id":         "ca11",
        "date_filed":       "2024-06-15",
        "citation":         ["20 F.4th 999"],
        "plain_text":       text,
        "plain_text_chars": len(text),
        "authored_judge":   judge,
        "fetched_at":       "2026-04-24T00:00:00+00:00",
    }


def _write_source(path: Path, opinions: list[dict]) -> Path:
    with path.open("w", encoding="utf-8") as fh:
        for op in opinions:
            fh.write(json.dumps(op) + "\n")
    return path


class _RecordingEmbedder:
    def __init__(self) -> None:
        self.calls: list[str] = []

    async def embed(self, text: str) -> list[float]:
        self.calls.append(text)
        return [0.0001 * (len(text) % 1000)] * VECTOR_DIM


class _RecordingSink:
    def __init__(self) -> None:
        self.ensure_calls: list[int] = []
        self.reset_calls = 0
        self.upsert_batches: list[list[dict]] = []

    def ensure_collection(self, dim: int) -> None:
        self.ensure_calls.append(dim)

    def reset(self) -> None:
        self.reset_calls += 1

    def upsert(self, points: list[dict]) -> None:
        self.upsert_batches.append(list(points))


# ─────────────────────────────────────────────────────────────────────────────
# 1. New collection name + payload schema
# ─────────────────────────────────────────────────────────────────────────────

class TestPayloadSchema:
    def test_collection_name_is_legal_caselaw_federal(self):
        assert COLLECTION_NAME == "legal_caselaw_federal"

    def test_jurisdiction_tag_is_ca11(self):
        assert JURISDICTION_TAG == "ca11"

    def test_payload_carries_all_required_fields(self):
        op = _ca11_opinion()
        vec = [0.0] * VECTOR_DIM
        p = build_point(op, chunk_index=2, chunk_text="chunked", vector=vec, run_id="r1")
        required = {
            "opinion_id", "cluster_id", "case_name", "court", "date_filed",
            "citation", "chunk_index", "text_chunk", "plain_text_chars_total",
            "jurisdiction", "authored_judge", "ingested_at", "ingestion_run_id",
        }
        assert set(p["payload"].keys()) == required
        assert p["payload"]["jurisdiction"] == "ca11"
        assert p["payload"]["authored_judge"] == "Hon. Jane Doe"
        assert p["payload"]["chunk_index"] == 2
        assert p["payload"]["text_chunk"] == "chunked"
        assert p["vector"] is vec

    def test_point_id_is_deterministic_per_opinion_chunk(self):
        op = _ca11_opinion("STABLE")
        v = [0.0] * VECTOR_DIM
        a = build_point(op, 0, "c0", v, "run1")
        b = build_point(op, 0, "c0", v, "run2")           # different run_id
        c = build_point(op, 1, "c1", v, "run1")           # different chunk_index
        assert a["id"] == b["id"]
        assert a["id"] != c["id"]


# ─────────────────────────────────────────────────────────────────────────────
# 2. Idempotent re-run
# ─────────────────────────────────────────────────────────────────────────────

class TestIdempotency:
    def test_rerun_skips_completed_opinion_ids(self, tmp_path: Path):
        src = _write_source(tmp_path / "ca11.jsonl", [
            _ca11_opinion("CA11-A"), _ca11_opinion("CA11-B"),
        ])
        state_path = tmp_path / ".state.db"
        cfg = IngestConfig(
            source=src, state_db=state_path,
            batch_size=4, chunk_tokens=500, overlap_tokens=50, log_every=999,
            skip_fetch=True,
        )

        st1 = IngestState(state_path)
        emb1 = _RecordingEmbedder(); sink1 = _RecordingSink()
        s1 = asyncio.run(run_ingest(cfg, st1, emb1, sink1))
        st1.close()
        assert s1.opinions_processed == 2
        assert s1.opinions_skipped_completed == 0
        first_chunks = s1.chunks_written
        assert first_chunks >= 2

        st2 = IngestState(state_path)
        emb2 = _RecordingEmbedder(); sink2 = _RecordingSink()
        s2 = asyncio.run(run_ingest(cfg, st2, emb2, sink2))
        st2.close()
        assert s2.opinions_processed == 0
        assert s2.opinions_skipped_completed == 2
        assert s2.chunks_written == 0
        assert emb2.calls == []
        assert sink2.upsert_batches == []

    def test_reset_drops_collection_and_reprocesses(self, tmp_path: Path):
        src = _write_source(tmp_path / "ca11.jsonl", [_ca11_opinion("CA11-X")])
        state_path = tmp_path / ".state.db"
        cfg = IngestConfig(
            source=src, state_db=state_path,
            batch_size=4, chunk_tokens=500, overlap_tokens=50, log_every=999,
            skip_fetch=True,
        )
        # Pre-populate state to simulate a prior run
        st = IngestState(state_path)
        st.mark_completed("CA11-X", 3, "prior")
        st.close()

        st2 = IngestState(state_path)
        emb = _RecordingEmbedder(); sink = _RecordingSink()
        cfg_reset = IngestConfig(**{**cfg.__dict__, "reset": True})
        stats = asyncio.run(run_ingest(cfg_reset, st2, emb, sink))
        st2.close()

        assert sink.reset_calls == 1
        assert stats.opinions_processed == 1
        assert stats.opinions_skipped_completed == 0


# ─────────────────────────────────────────────────────────────────────────────
# 3. Dry-run no-side-effects
# ─────────────────────────────────────────────────────────────────────────────

class TestDryRun:
    def test_dry_run_does_not_call_embed_or_qdrant(self, tmp_path: Path):
        from backend.scripts.ingest_courtlistener_11th_cir import (
            DryRunEmbedder, DryRunSink,
        )
        src = _write_source(tmp_path / "ca11.jsonl", [
            _ca11_opinion("D1"), _ca11_opinion("D2"),
        ])
        state = IngestState(tmp_path / ".state.db")
        cfg = IngestConfig(
            source=src, state_db=tmp_path / ".state.db",
            batch_size=4, chunk_tokens=500, overlap_tokens=50,
            dry_run=True, log_every=999, skip_fetch=True,
        )
        stats = asyncio.run(run_ingest(cfg, state, DryRunEmbedder(), DryRunSink()))
        state.close()
        assert stats.errors == 0
        assert stats.opinions_processed == 2
        assert stats.chunks_written >= 2
        # Dry-run intentionally does NOT write state
        st2 = IngestState(tmp_path / ".state.db")
        assert not st2.already_completed("D1")
        assert not st2.already_completed("D2")
        st2.close()


# ─────────────────────────────────────────────────────────────────────────────
# 4. Collection creation goes through the existing QdrantSink path
# ─────────────────────────────────────────────────────────────────────────────

class TestCollectionEnsure:
    def test_ensure_collection_called_with_768_dim(self, tmp_path: Path):
        src = _write_source(tmp_path / "ca11.jsonl", [_ca11_opinion("C1")])
        state = IngestState(tmp_path / ".state.db")
        cfg = IngestConfig(
            source=src, state_db=tmp_path / ".state.db",
            batch_size=4, chunk_tokens=500, overlap_tokens=50, log_every=999,
            skip_fetch=True,
        )
        sink = _RecordingSink()
        emb = _RecordingEmbedder()
        asyncio.run(run_ingest(cfg, state, emb, sink))
        state.close()
        assert sink.ensure_calls == [VECTOR_DIM]


# ─────────────────────────────────────────────────────────────────────────────
# 5. CourtListener API client — paginates + dedups + writes JSONL
# ─────────────────────────────────────────────────────────────────────────────

class TestFetchCa11ToJsonl:
    def _fake_http(self):
        """Return an http_get that simulates 2 pages of clusters + sub-opinion fetches."""
        cluster_pages = [
            {
                "next": "http://fake/clusters/?cursor=p2",
                "results": [
                    {
                        "id": 100, "case_name": "United States v. Alpha",
                        "date_filed": "2024-05-01",
                        "citations": [{"volume": "1", "reporter": "F.4th", "page": "11"}],
                        "sub_opinions": ["http://fake/opinions/1001/"],
                    },
                    {
                        "id": 101, "case_name": "United States v. Bravo",
                        "date_filed": "2024-05-02",
                        "citations": [{"volume": "2", "reporter": "F.4th", "page": "22"}],
                        "sub_opinions": ["http://fake/opinions/1002/"],
                    },
                ],
            },
            {
                "next": None,
                "results": [
                    {
                        "id": 102, "case_name": "United States v. Charlie",
                        "date_filed": "2024-05-03",
                        "citations": [],
                        "sub_opinions": ["http://fake/opinions/1003/"],
                    },
                ],
            },
        ]
        opinion_data = {
            "http://fake/opinions/1001/": {
                "id": 1001, "plain_text": "Alpha opinion text body. " * 100,
                "author_str": "J. Marcus",
            },
            "http://fake/opinions/1002/": {
                "id": 1002, "plain_text": "Bravo opinion text body. " * 100,
                "author_str": "J. Wilson",
            },
            "http://fake/opinions/1003/": {
                "id": 1003, "plain_text": "Charlie opinion text body. " * 100,
                "author_str": "J. Hull",
            },
        }
        page_idx = {"i": 0}

        def http_get(url: str, token: str) -> dict:
            assert token == "test-token"
            if "/clusters/" in url and "cursor=p2" in url:
                return cluster_pages[1]
            if "/clusters/" in url:
                return cluster_pages[0]
            return opinion_data[url]
        return http_get

    def test_fetch_paginates_and_writes_three_records(self, tmp_path: Path, monkeypatch):
        monkeypatch.setenv("COURTLISTENER_API_TOKEN", "test-token")
        jsonl = tmp_path / "ca11.jsonl"
        new, total = fetch_ca11_to_jsonl(
            jsonl, since="2024-01-01",
            http_get=self._fake_http(),
            rate_limit_s=0,
        )
        assert new == 3
        assert total == 3
        records = [json.loads(line) for line in jsonl.read_text().splitlines() if line]
        assert {r["opinion_id"] for r in records} == {"1001", "1002", "1003"}
        first = records[0]
        assert first["court_id"] == "ca11"
        assert first["court"].startswith("United States Court of Appeals")
        assert first["authored_judge"] in {"J. Marcus", "J. Wilson", "J. Hull"}
        assert first["plain_text_chars"] > 0

    def test_fetch_is_idempotent_skips_existing_opinion_ids(self, tmp_path: Path, monkeypatch):
        monkeypatch.setenv("COURTLISTENER_API_TOKEN", "test-token")
        jsonl = tmp_path / "ca11.jsonl"
        # Pre-populate JSONL with 1001
        with jsonl.open("w") as fh:
            fh.write(json.dumps({"opinion_id": "1001", "plain_text": "x"}) + "\n")
        new, total = fetch_ca11_to_jsonl(
            jsonl, since="2024-01-01",
            http_get=self._fake_http(),
            rate_limit_s=0,
        )
        # Only 1002 and 1003 are new
        assert new == 2
        # Total is len(seen at end) — but count is the size of the seen set which started with 1
        assert total == 3
        records = [json.loads(line) for line in jsonl.read_text().splitlines() if line]
        # Original line for 1001 + appended 1002/1003 = 3
        ids = [r["opinion_id"] for r in records]
        assert ids.count("1001") == 1
        assert "1002" in ids and "1003" in ids

    def test_fetch_max_caps_api_pull(self, tmp_path: Path, monkeypatch):
        monkeypatch.setenv("COURTLISTENER_API_TOKEN", "test-token")
        jsonl = tmp_path / "ca11.jsonl"
        new, _ = fetch_ca11_to_jsonl(
            jsonl, since="2024-01-01", fetch_max=2,
            http_get=self._fake_http(), rate_limit_s=0,
        )
        assert new == 2
        records = [json.loads(line) for line in jsonl.read_text().splitlines() if line]
        assert len(records) == 2

    def test_fetch_raises_when_token_missing(self, tmp_path: Path, monkeypatch):
        monkeypatch.delenv("COURTLISTENER_API_TOKEN", raising=False)
        try:
            fetch_ca11_to_jsonl(tmp_path / "ca11.jsonl", since="2024-01-01")
        except RuntimeError as exc:
            assert "COURTLISTENER_API_TOKEN" in str(exc)
        else:
            raise AssertionError("expected RuntimeError when token unset")
