"""
Tests for SentMailRetriever.

Covers:
  - Recency boost math (pure unit test, no network)
  - Two-collection merge with dedup
  - Qdrant timeout → empty list, no exception
  - Min-score filter
  - Empty / whitespace query → empty list
"""
from __future__ import annotations

import time
import pytest
from unittest.mock import AsyncMock, patch, MagicMock

from backend.services.sent_mail_retriever import (
    SentMailRetriever,
    SentMailExemplar,
    _recency_boost,
    _point_to_exemplar,
    RECENCY_COEFF,
    RECENCY_WINDOW_SECONDS,
    COLLECTION_SENT_MAIL,
    COLLECTION_GOLDEN,
)


# ---------------------------------------------------------------------------
# Recency boost math
# ---------------------------------------------------------------------------

class TestRecencyBoost:
    def test_zero_age_returns_max_boost(self):
        # A message sent right now should get the full coefficient boost
        now_epoch = int(time.time())
        multiplier = _recency_boost(now_epoch)
        assert multiplier == pytest.approx(1.0 + RECENCY_COEFF, abs=0.01)

    def test_full_window_age_returns_no_boost(self):
        # A message sent exactly RECENCY_WINDOW_SECONDS ago gets no boost
        old_epoch = int(time.time() - RECENCY_WINDOW_SECONDS)
        multiplier = _recency_boost(old_epoch)
        assert multiplier == pytest.approx(1.0, abs=0.02)

    def test_older_than_window_clamped_at_no_boost(self):
        # Messages older than the window never go below 1.0
        very_old_epoch = int(time.time() - RECENCY_WINDOW_SECONDS * 2)
        assert _recency_boost(very_old_epoch) == pytest.approx(1.0, abs=0.01)

    def test_none_epoch_returns_no_boost(self):
        assert _recency_boost(None) == 1.0

    def test_midpoint_roughly_half_boost(self):
        # Halfway through the window → ~half the coefficient
        mid_epoch = int(time.time() - RECENCY_WINDOW_SECONDS / 2)
        mult = _recency_boost(mid_epoch)
        expected = 1.0 + RECENCY_COEFF * 0.5
        assert mult == pytest.approx(expected, abs=0.02)


# ---------------------------------------------------------------------------
# Point conversion helpers
# ---------------------------------------------------------------------------

class TestPointToExemplar:
    def _sent_pt(self, body="Hello guest", score=0.75, topic="availability",
                 sent_at_epoch=None):
        return {
            "score": score,
            "payload": {
                "body": body,
                "subject": "Re: cabin inquiry",
                "detected_topic": topic,
                "sent_at": "2024-06-01T10:00:00+00:00",
                "sent_at_epoch": sent_at_epoch or int(time.time()),
                "source": "taylor_sent_tarball_2022_2026",
            },
        }

    def _golden_pt(self, ai_output="Hi there!", score=0.80, topic="pricing"):
        return {
            "score": score,
            "payload": {
                "ai_output": ai_output,
                "topic": topic,
                "cabin": "Cohutta Sunset",
                "quality_score": 5,
            },
        }

    def test_sent_mail_point_converts(self):
        ex = _point_to_exemplar(self._sent_pt(), COLLECTION_SENT_MAIL)
        assert ex is not None
        assert ex.body == "Hello guest"
        assert ex.detected_topic == "availability"
        assert ex.source == "taylor_sent_tarball_2022_2026"

    def test_golden_point_converts(self):
        ex = _point_to_exemplar(self._golden_pt(), COLLECTION_GOLDEN)
        assert ex is not None
        assert ex.body == "Hi there!"
        assert ex.detected_topic == "pricing"
        assert ex.source == "guest_golden_responses"
        assert "Cohutta Sunset" in ex.subject

    def test_empty_body_returns_none(self):
        pt = {"score": 0.9, "payload": {"body": "", "ai_output": ""}}
        assert _point_to_exemplar(pt, COLLECTION_SENT_MAIL) is None
        assert _point_to_exemplar(pt, COLLECTION_GOLDEN) is None

    def test_recency_boosted_score_applied(self):
        now_epoch = int(time.time())
        pt = self._sent_pt(score=0.80, sent_at_epoch=now_epoch)
        ex = _point_to_exemplar(pt, COLLECTION_SENT_MAIL)
        assert ex is not None
        assert ex.score > 0.80  # boost applied


# ---------------------------------------------------------------------------
# SentMailRetriever integration (mocked Qdrant + embed)
# ---------------------------------------------------------------------------

def _make_qdrant_pt(body, score, topic="availability", collection=COLLECTION_SENT_MAIL,
                    sent_at_epoch=None):
    if collection == COLLECTION_SENT_MAIL:
        payload = {
            "body": body,
            "subject": "Re: inquiry",
            "detected_topic": topic,
            "sent_at": "2024-01-01T00:00:00+00:00",
            "sent_at_epoch": sent_at_epoch or int(time.time() - 86400 * 100),
            "source": "taylor_sent_tarball_2022_2026",
        }
    else:
        payload = {"ai_output": body, "topic": topic, "cabin": "Test Cabin"}
    return {"score": score, "payload": payload}


class TestSentMailRetriever:
    @pytest.mark.asyncio
    async def test_empty_query_returns_empty(self):
        retriever = SentMailRetriever()
        assert await retriever.find_similar_replies("") == []
        assert await retriever.find_similar_replies("   ") == []

    @pytest.mark.asyncio
    async def test_embed_failure_returns_empty(self):
        retriever = SentMailRetriever()
        with patch(
            "backend.services.sent_mail_retriever._embed",
            new_callable=AsyncMock,
            return_value=None,
        ):
            result = await retriever.find_similar_replies("Looking for a cabin")
        assert result == []

    @pytest.mark.asyncio
    async def test_qdrant_timeout_returns_empty_no_exception(self):
        retriever = SentMailRetriever()
        fake_vector = [0.1] * 768
        with patch(
            "backend.services.sent_mail_retriever._embed",
            new_callable=AsyncMock,
            return_value=fake_vector,
        ), patch(
            "backend.services.sent_mail_retriever._search_collection",
            new_callable=AsyncMock,
            side_effect=Exception("connection timeout"),
        ):
            result = await retriever.find_similar_replies("test inquiry")
        assert result == []

    @pytest.mark.asyncio
    async def test_min_score_filter_applied(self):
        retriever = SentMailRetriever()
        fake_vector = [0.1] * 768
        # One result below threshold, one above
        low_pt = _make_qdrant_pt("Low score reply", score=0.50)
        high_pt = _make_qdrant_pt("High score reply", score=0.90)

        async def _mock_search(collection, vector, limit):
            if collection == COLLECTION_SENT_MAIL:
                return [high_pt, low_pt]
            return []

        with patch("backend.services.sent_mail_retriever._embed",
                   new_callable=AsyncMock, return_value=fake_vector), \
             patch("backend.services.sent_mail_retriever._search_collection",
                   side_effect=_mock_search):
            results = await retriever.find_similar_replies("test", min_score=0.65)

        assert len(results) == 1
        assert results[0].body == "High score reply"

    @pytest.mark.asyncio
    async def test_two_collection_merge_and_dedup(self):
        retriever = SentMailRetriever()
        fake_vector = [0.1] * 768
        # Same body in both collections → deduped to one
        same_body = "Duplicate body text"
        pt_sent = _make_qdrant_pt(same_body, score=0.80)
        pt_golden = _make_qdrant_pt(same_body, score=0.85, collection=COLLECTION_GOLDEN)
        unique_pt = _make_qdrant_pt("Unique reply from sent", score=0.75)

        async def _mock_search(collection, vector, limit):
            if collection == COLLECTION_SENT_MAIL:
                return [pt_sent, unique_pt]
            return [pt_golden]

        with patch("backend.services.sent_mail_retriever._embed",
                   new_callable=AsyncMock, return_value=fake_vector), \
             patch("backend.services.sent_mail_retriever._search_collection",
                   side_effect=_mock_search):
            results = await retriever.find_similar_replies("test inquiry", k=5, min_score=0.0)

        bodies = [r.body for r in results]
        # Duplicate deduped — should appear only once
        assert bodies.count(same_body) == 1
        assert len(results) == 2

    @pytest.mark.asyncio
    async def test_results_sorted_by_boosted_score_descending(self):
        retriever = SentMailRetriever()
        fake_vector = [0.1] * 768
        now = int(time.time())
        recent_pt = _make_qdrant_pt("Recent reply", score=0.70,
                                     sent_at_epoch=now - 86400 * 30)   # 30 days old
        old_pt = _make_qdrant_pt("Old reply", score=0.75,
                                  sent_at_epoch=now - int(RECENCY_WINDOW_SECONDS * 0.9))

        async def _mock_search(collection, vector, limit):
            if collection == COLLECTION_SENT_MAIL:
                return [old_pt, recent_pt]
            return []

        with patch("backend.services.sent_mail_retriever._embed",
                   new_callable=AsyncMock, return_value=fake_vector), \
             patch("backend.services.sent_mail_retriever._search_collection",
                   side_effect=_mock_search):
            results = await retriever.find_similar_replies("test", k=5, min_score=0.0)

        # Recent gets boosted enough to outrank older despite lower raw score
        assert len(results) == 2
        assert results[0].body == "Recent reply"

    @pytest.mark.asyncio
    async def test_returns_at_most_k_results(self):
        retriever = SentMailRetriever()
        fake_vector = [0.1] * 768
        many_pts = [_make_qdrant_pt(f"Reply {i}", score=0.9 - i * 0.01) for i in range(10)]

        async def _mock_search(collection, vector, limit):
            if collection == COLLECTION_SENT_MAIL:
                return many_pts[:limit]
            return []

        with patch("backend.services.sent_mail_retriever._embed",
                   new_callable=AsyncMock, return_value=fake_vector), \
             patch("backend.services.sent_mail_retriever._search_collection",
                   side_effect=_mock_search):
            results = await retriever.find_similar_replies("test", k=3, min_score=0.0)

        assert len(results) <= 3
