"""
Tests for the IngestRunTracker.

Uses a `_FakeConn` injected via `connection_factory=` to avoid touching
a real database. The fake speaks just enough psycopg2-shaped API to
exercise the cursor + fetchone + close flows.
"""
from __future__ import annotations

import threading
import time
from contextlib import contextmanager
from typing import Any
from unittest.mock import patch
from uuid import uuid4

import pytest

from backend.services.ingest_run_tracker import IngestRunTracker


# ─────────────────────────────────────────────────────────────────────────────
# Fake psycopg2 connection
# ─────────────────────────────────────────────────────────────────────────────

class _FakeCursor:
    def __init__(self, conn: "_FakeConn") -> None:
        self._conn = conn
        self._last_row = None

    def execute(self, sql: str, params: tuple = ()) -> None:
        self._conn.calls.append((sql, params))
        # Drive optional behaviour from the parent connection
        if self._conn.fail_next:
            self._conn.fail_next -= 1
            raise RuntimeError("simulated DB disconnect")
        if "RETURNING id" in sql:
            self._last_row = (uuid4(),)
        else:
            self._last_row = None
        if self._conn.on_execute:
            self._conn.on_execute(sql, params)

    def fetchone(self):
        return self._last_row

    def __enter__(self): return self

    def __exit__(self, exc_type, exc, tb): return False


class _FakeConn:
    """Tiny psycopg2 stand-in. Tracks every call; fail_next forces N raises."""
    def __init__(self, fail_next: int = 0,
                 on_execute=None) -> None:
        self.autocommit = True
        self.calls: list[tuple[str, tuple]] = []
        self.fail_next = fail_next
        self.on_execute = on_execute
        self.closed = False

    def cursor(self) -> _FakeCursor:
        return _FakeCursor(self)

    def close(self) -> None:
        self.closed = True


def _factory(initial_fail: int = 0, on_execute=None):
    """Build a connection_factory closure that returns a fresh _FakeConn each call."""
    state = {"connections": []}

    def make() -> _FakeConn:
        # Only the first connection's `fail_next` matters for the
        # 'fail-then-recover' tests because each retry re-connects.
        # We therefore allocate the failure budget across attempts via
        # the shared counter.
        c = _FakeConn(fail_next=state.get("fail_remaining", initial_fail),
                      on_execute=on_execute)
        state["connections"].append(c)
        return c

    state["fail_remaining"] = initial_fail
    return make, state


# ─────────────────────────────────────────────────────────────────────────────
# Tests
# ─────────────────────────────────────────────────────────────────────────────

class TestCleanRunMarksComplete:
    def test_clean_run_marks_complete(self):
        make, state = _factory()
        with IngestRunTracker(
            "fish-trap-suv2026000013", "ocr_legal_case",
            args={"jobs": 6}, connection_factory=make,
        ) as run:
            run.set_total_files(10)
            for _ in range(8):
                run.inc_processed()
            run.set_manifest_path("/tmp/manifest.json")

        assert not run.degraded
        # Last UPDATE must set status='complete'
        last_status_set = next(
            (call for c in reversed(state["connections"])
             for call in reversed(c.calls)
             if "SET status = %s" in call[0]),
            None,
        )
        assert last_status_set is not None
        assert last_status_set[1][0] == "complete"


class TestExceptionMarksError:
    def test_exception_marks_error_and_reraises(self):
        make, state = _factory()
        with pytest.raises(ValueError, match="boom"):
            with IngestRunTracker(
                "fish-trap-suv2026000013", "ocr_legal_case",
                connection_factory=make,
            ) as run:
                raise ValueError("boom")

        # Exception bubbled out of the with-block; tracker wrote 'error'.
        # find the last SET status statement
        all_calls = [c for conn in state["connections"] for c in conn.calls]
        status_writes = [c for c in all_calls if "SET status = %s" in c[0]]
        assert status_writes
        last = status_writes[-1]
        assert last[1][0] == "error"
        # error_summary param present and contains the exception name
        assert any("ValueError" in str(p) for p in last[1])


class TestKeyboardInterruptMarksInterrupted:
    def test_keyboard_interrupt_marks_interrupted_and_reraises(self):
        make, state = _factory()
        with pytest.raises(KeyboardInterrupt):
            with IngestRunTracker(
                "fish-trap-suv2026000013", "ocr_legal_case",
                connection_factory=make,
            ) as run:
                raise KeyboardInterrupt()

        all_calls = [c for conn in state["connections"] for c in conn.calls]
        status_writes = [c for c in all_calls if "SET status = %s" in c[0]]
        assert status_writes
        assert status_writes[-1][1][0] == "interrupted"


class TestIncCountersAtomic:
    def test_inc_counters_emit_correct_running_totals(self):
        make, state = _factory()
        with IngestRunTracker(
            "fish-trap-suv2026000013", "ocr_legal_case",
            connection_factory=make,
        ) as run:
            run.inc_processed()
            run.inc_processed(5)
            run.inc_errored()
            run.inc_skipped(3)
            assert run._counters.processed == 6
            assert run._counters.errored == 1
            assert run._counters.skipped == 3

        # Inspect the last UPDATE for each counter — should reflect the
        # cumulative running total, not the delta.
        all_calls = [c for conn in state["connections"] for c in conn.calls]
        proc_updates = [c for c in all_calls if "SET processed = %s" in c[0]]
        # Last processed-update should carry the total (6).
        assert proc_updates and proc_updates[-1][1][0] == 6

        locked_counter_updates = [
            c for c in all_calls
            if "files_processed = %s" in c[0]
            and "files_succeeded = %s" in c[0]
            and "files_failed = %s" in c[0]
        ]
        assert locked_counter_updates
        last_locked_sql, last_locked_params = locked_counter_updates[-1]
        locked_fields = [
            part.strip().split(" = ")[0]
            for part in last_locked_sql.split("SET", 1)[1].split("WHERE", 1)[0].split(",")
        ]
        locked_values = dict(zip(locked_fields, last_locked_params))
        assert locked_values["files_processed"] == 10
        assert locked_values["files_succeeded"] == 6
        assert locked_values["files_failed"] == 1


class TestSetManifestPath:
    def test_set_manifest_path_writes_path(self):
        make, state = _factory()
        path = "/mnt/fortress_nas/audits/foo.json"
        with IngestRunTracker(
            "fish-trap-suv2026000013", "ocr_legal_case",
            connection_factory=make,
        ) as run:
            run.set_manifest_path(path)

        all_calls = [c for conn in state["connections"] for c in conn.calls]
        manifest_writes = [c for c in all_calls if "manifest_path = %s" in c[0]]
        assert manifest_writes
        assert manifest_writes[-1][1][0] == path


class TestConcurrentTrackersDontCollide:
    def test_two_trackers_get_distinct_run_ids(self):
        make, _ = _factory()
        t1 = IngestRunTracker("a", "s", connection_factory=make)
        t2 = IngestRunTracker("b", "s", connection_factory=make)
        with t1, t2:
            assert t1.run_id is not None
            assert t2.run_id is not None
            assert t1.run_id != t2.run_id

    def test_concurrent_threads_dont_share_state(self):
        # Each tracker has its own _counters dataclass + run_id.
        make, _ = _factory()
        run_ids = []
        errors = []

        def worker():
            try:
                with IngestRunTracker("a", "s", connection_factory=make) as r:
                    r.inc_processed(7)
                    run_ids.append(r.run_id)
                    assert r._counters.processed == 7
            except Exception as e:
                errors.append(e)

        threads = [threading.Thread(target=worker) for _ in range(4)]
        for t in threads: t.start()
        for t in threads: t.join()
        assert not errors
        assert len(run_ids) == 4
        assert len(set(run_ids)) == 4


class TestStatusCheckConstraint:
    """The CHECK constraint lives in the DB. Verify the tracker only
    writes the four allowed values."""
    def test_tracker_only_writes_allowed_status_values(self):
        # Every code path that calls _update_status uses one of the four
        # accepted values; we enumerate them via a fake on_execute hook.
        seen: list[str] = []

        def hook(sql, params):
            if "SET status = %s" in sql and params:
                seen.append(params[0])

        make, _ = _factory(on_execute=hook)
        # complete
        with IngestRunTracker("a", "s", connection_factory=make):
            pass
        # interrupted
        with pytest.raises(KeyboardInterrupt):
            with IngestRunTracker("a", "s", connection_factory=make):
                raise KeyboardInterrupt()
        # error
        with pytest.raises(RuntimeError):
            with IngestRunTracker("a", "s", connection_factory=make):
                raise RuntimeError("x")

        assert set(seen) == {"complete", "interrupted", "error"}
        assert all(v in {"running", "complete", "error", "interrupted"}
                   for v in seen)


class TestDbDisconnectRetryThenDegrade:
    def test_three_failures_then_degrade(self, monkeypatch):
        """Inject 99 failures so even the start-row INSERT exhausts retries."""
        # Speed up backoffs in tests
        monkeypatch.setattr(
            "backend.services.ingest_run_tracker._RETRY_BACKOFFS_S",
            (0.0, 0.0, 0.0),
        )

        def make_failing():
            return _FakeConn(fail_next=99)

        # No exception in the with-block — tracker degradation alone
        # must NOT abort the parent.
        with IngestRunTracker(
            "fish-trap-suv2026000013", "ocr_legal_case",
            connection_factory=make_failing,
        ) as run:
            run.set_total_files(5)
            run.inc_processed()
            run.set_manifest_path("/tmp/x.json")

        assert run.degraded is True
        assert run.run_id is None

    def test_retry_succeeds_on_third_attempt(self, monkeypatch):
        monkeypatch.setattr(
            "backend.services.ingest_run_tracker._RETRY_BACKOFFS_S",
            (0.0, 0.0, 0.0),
        )
        # First two attempts fail, third succeeds.
        attempt = {"i": 0}

        def make():
            attempt["i"] += 1
            return _FakeConn(fail_next=1 if attempt["i"] <= 2 else 0)

        tracker = IngestRunTracker(
            "fish-trap-suv2026000013", "ocr_legal_case",
            connection_factory=make,
        )
        with tracker as run:
            pass

        assert run.degraded is False
        assert run.run_id is not None


class TestDegradedTrackerDoesNotAbort:
    def test_parent_script_completes_when_tracker_dies_at_start(self, monkeypatch):
        monkeypatch.setattr(
            "backend.services.ingest_run_tracker._RETRY_BACKOFFS_S",
            (0.0, 0.0, 0.0),
        )

        def make_failing():
            return _FakeConn(fail_next=99)

        # Simulate parent script body that does real work after tracker setup.
        work_done = []
        with IngestRunTracker(
            "fish-trap-suv2026000013", "ocr_legal_case",
            connection_factory=make_failing,
        ) as run:
            for i in range(5):
                # Counter calls return None silently when degraded
                run.inc_processed()
                work_done.append(i)
        assert work_done == [0, 1, 2, 3, 4]
        assert run.degraded is True


class TestInvalidCaseSlugFailsFast:
    """
    The CHECK lives on the FK in the real DB; with the fake we verify the
    INSERT round-trip semantics. Real-DB FK violation is exercised via
    the integration smoke in PR D.
    """
    def test_tracker_passes_case_slug_through_to_insert(self):
        seen: list[tuple] = []
        def hook(sql, params):
            if sql.lstrip().startswith("INSERT INTO legal.ingest_runs"):
                seen.append(params)

        make, _ = _factory(on_execute=hook)
        with IngestRunTracker(
            "ghost-case", "ocr_legal_case", connection_factory=make,
        ):
            pass

        assert seen and seen[0][0] == "ghost-case"
        assert seen[0][2] == seen[0][3]
