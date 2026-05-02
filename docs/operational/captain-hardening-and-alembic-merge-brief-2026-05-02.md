# Captain Hardening + Alembic Reconciliation — Execution Brief (2026-05-02 Saturday night)

**Operator:** Gary Knight
**Target:** Claude Code on spark-2, fresh `flos_phase_0a` tmux session (or new tmux if collisions exist)
**Scope:** Three fixes in one PR, three commits, phase-per-commit:
  - Commit 1: Issue #279 — alembic merge migration joining divergent heads
  - Commit 2: Issue #259 — `unknown-8bit` codec shim for Captain IMAP fetch
  - Commit 3: Issue #260 — Captain banded SEARCH (scope-by-date) for gary-gk
**Authority:** Operator authorized 2026-05-02 evening
**NOT in scope:** any other open issue, any other PR triage, any FLOS Phase 2 work

---

## 0. Standing constraints (non-negotiable)

- Branch from `origin/main` only. Never `--admin`, never `--force`, never self-merge.
- Single CC session per host. Verify spark-2 has only `email_pipeline` (Wave 7 Case II) and this session before starting.
- Cluster untouchable through 2026-05-08 except mission-critical. **These fixes are mission-critical pre-counsel-hire** (counsel hire 2026-05-08; these issues could surface in first 48 hours of counsel review).
- Frontier health (`http://10.10.10.3:8000/health`) MUST stay 200. Hands off spark-3/4.
- Captain is **a running production pipeline**. Every code change must preserve current ingestion behavior on the 3 healthy mailboxes (legal-cpanel, info-crog, plus whichever of gary-* is currently working). Do not break what works.
- legal_mail_ingester is **a separate running pipeline** also in production. Do not touch its files. The Captain fixes here do not affect legal_mail_ingester.
- Operator merges. CC surfaces PR URL and stops.

---

## 1. Pre-flight (5 min)

```bash
cd /home/admin/Fortress-Prime
git fetch origin
git status
git log --oneline origin/main..HEAD                   # must be empty
git checkout main
git reset --hard origin/main                          # only if local main has drift

tmux ls                                               # expect: email_pipeline, this session, no others
ps -ef | grep -i 'claude' | grep -v grep              # expect: 1-2 processes (this CC + email_pipeline's CC)
curl -fsS http://10.10.10.3:8000/health               # frontier 200
```

**HALT conditions:**
- Other tmux sessions with active CC besides email_pipeline
- Local main differs from origin/main
- Frontier non-200

```bash
git checkout -b fix/captain-hardening-and-alembic-merge-2026-05-02 origin/main
```

---

## 2. Commit 1 — Issue #279: alembic merge migration

### 2.1 Context

Two divergent heads on fortress_db per Issue #279:
- `q2b3c4d5e6f7`
- `r3c4d5e6f7g8`

Plus orphaned head `7a1b2c3d4e5f` from Issue #204 (separately tracked, do NOT touch in this PR).

Goal: join the two named heads into a single canonical head via `alembic merge`. Issue #204 orphan stays orphaned (it's a separate divergence with its own resolution path; merging it into this work expands scope).

### 2.2 Discover actual head IDs

The issue body uses placeholder IDs (`q2b3c4d5e6f7`, etc.). Confirm real IDs:

```bash
cd /home/admin/Fortress-Prime
source .venv/bin/activate 2>/dev/null || python3 -m venv .venv && source .venv/bin/activate
python3 -m alembic heads
```

Expected output: 2-3 head revision IDs. Capture the two that match Issue #279's description (NOT the Issue #204 orphan).

If the venv path differs or alembic isn't installed in it, search:

```bash
which alembic
find . -path ./node_modules -prune -o -name "alembic.ini" -print 2>/dev/null | head -5
```

The repo's `alembic.ini` location tells you which interpreter + venv config alembic uses.

### 2.3 Pre-merge schema snapshot

Before merging, snapshot the current schema for forensic comparison:

```bash
DB_HOST=$(grep "^DB_HOST=" .env | cut -d= -f2 | tr -d '"')
DB_PORT=$(grep "^DB_PORT=" .env | cut -d= -f2 | tr -d '"')
DB_USER=$(grep "^DB_USER=" .env | cut -d= -f2 | tr -d '"')
DB_NAME=$(grep "^DB_NAME=" .env | cut -d= -f2 | tr -d '"')
DB_PASS=$(grep "^DB_PASS=" .env | cut -d= -f2- | tr -d '"')

PGPASSWORD="$DB_PASS" pg_dump -h "$DB_HOST" -p "$DB_PORT" -U "$DB_USER" -d "$DB_NAME" \
  --schema-only --no-owner --no-acl \
  > /tmp/fortress_db_schema_pre_merge_$(date +%Y%m%dT%H%M%SZ).sql

PGPASSWORD="$DB_PASS" psql -h "$DB_HOST" -p "$DB_PORT" -U "$DB_USER" -d "$DB_NAME" \
  -c "SELECT version_num FROM alembic_version;" > /tmp/alembic_version_pre_merge.txt
```

### 2.4 Generate merge migration

```bash
python3 -m alembic merge -m "merge divergent heads <head1_short> <head2_short>" <head1_id> <head2_id>
```

This creates a new revision file under `alembic/versions/` (or wherever the chain lives — `alembic.ini` says) with `down_revision = (<head1_id>, <head2_id>)` and an empty `upgrade()`/`downgrade()`. That's correct — a merge migration is structural, not data.

### 2.5 Verify before applying

```bash
python3 -m alembic heads
```

Expected: ONE head (the new merge revision) plus the Issue #204 orphan (`7a1b2c3d4e5f`). The two named heads from #279 are now ancestors of the merge revision.

If `alembic heads` shows more than 2 heads, stop and surface — there's a state we don't expect.

### 2.6 Apply migration

```bash
python3 -m alembic upgrade head 2>&1 | tee /tmp/alembic_upgrade_head_$(date +%Y%m%dT%H%M%SZ).log
```

Expected: fast (no DDL, just a row in `alembic_version`). Check:

```bash
PGPASSWORD="$DB_PASS" psql -h "$DB_HOST" -p "$DB_PORT" -U "$DB_USER" -d "$DB_NAME" \
  -c "SELECT version_num FROM alembic_version;"
```

Expected: TWO rows (the new merge head + the Issue #204 orphan). Or one row if alembic somehow consolidated — verify against `alembic heads` output.

### 2.7 Post-merge schema diff

```bash
PGPASSWORD="$DB_PASS" pg_dump -h "$DB_HOST" -p "$DB_PORT" -U "$DB_USER" -d "$DB_NAME" \
  --schema-only --no-owner --no-acl \
  > /tmp/fortress_db_schema_post_merge_$(date +%Y%m%dT%H%M%SZ).sql

diff /tmp/fortress_db_schema_pre_merge_*.sql /tmp/fortress_db_schema_post_merge_*.sql
```

Expected: NO schema diff (a merge migration has empty upgrade()). Only the `alembic_version` row count differs. If schema differs, halt and surface.

### 2.8 Refresh spark-1 schema dump

Per Issue #279 body: "Resolution: alembic merge migration on spark-2 fortress_db that joins the two heads into a single canonical head. Then refresh the spark-1 schema dump."

Find the spark-1 schema dump location:

```bash
find . -name "spark1*schema*" -o -name "spark-1*schema*" -o -name "*spark1*.sql" 2>/dev/null | grep -v __pycache__ | head -10
```

If found, re-generate with the post-merge schema. If the dump is in `docs/` or `legal/` per Phase A1 lineage, regenerate via the same process used to create the original.

### 2.9 Commit 1

```bash
git add alembic/versions/*merge*.py docs/ legal/   # adjust paths to whatever changed
git status                                         # verify staged files
git commit -m "fix(alembic): merge divergent fortress_db heads (#279)

Closes #279.

Two divergent heads existed on fortress_db (per Phase A1 spark-1 diagnostic
2026-04-29). This merge migration joins them into a single canonical head,
unblocking M3 activation step 4 (alembic upgrade head against
SPARK1_DATABASE_URL).

Heads merged:
- <head1_full_id>
- <head2_full_id>

Issue #204 orphan head (7a1b2c3d4e5f) NOT included — separate divergence,
separate resolution path.

Verification:
- pg_dump schema-only diff before/after merge: no schema changes (empty
  upgrade migration as expected)
- alembic_version table now has merged head + Issue #204 orphan
- Pre-merge snapshot: /tmp/fortress_db_schema_pre_merge_<ts>.sql
- Post-merge snapshot: /tmp/fortress_db_schema_post_merge_<ts>.sql

Refs: #279, #204 (separate), Phase A1 spark-1 diagnostic"
```

**Commit 1 exit criterion:** `python3 -m alembic heads` shows merged head + Issue #204 orphan only. No schema drift. Pre-counsel-hire alembic state is clean.

---

## 3. Commit 2 — Issue #259: `unknown-8bit` codec shim

### 3.1 Locate Captain's IMAP fetch path

```bash
grep -rn "unknown-8bit\|captain_imap_fetch_error\|imap_fetch" backend/ 2>/dev/null | grep -v __pycache__ | head -20
grep -rn "captain_multi_mailbox\|class Captain" backend/ 2>/dev/null | grep -v __pycache__ | head -10
```

Find the file + function where the message body is parsed and `LookupError` would surface. Typical pattern: somewhere in the email-parsing path, `email.message_from_bytes()` followed by `.get_payload(decode=True)` or a `.decode(encoding)` call.

### 3.2 Implementation pattern

The operator's preferred fix from the issue body is a codec shim. Two viable patterns; pick whichever fits Captain's existing import structure:

**Pattern A — codecs.register shim (preferred, registers globally for the worker process):**

```python
import codecs

def _unknown_8bit_search(name: str):
    """Map MIME 'unknown-8bit' encoding declaration to latin-1 codec.
    
    RFC 1428/1652 'unknown-8bit' means '8-bit content of unknown character set'.
    Python's codecs registry has no entry for it. latin-1 is the safe permissive
    fallback because it round-trips any byte 0x00-0xff without error.
    """
    if name.lower().replace('_', '-') == 'unknown-8bit':
        return codecs.lookup('latin-1')
    return None

codecs.register(_unknown_8bit_search)
```

Place this at module-import time in Captain's main entry point (e.g. `backend/services/captain_multi_mailbox.py` near the top, after the `import codecs` line). Register-once-at-import semantics mean it's active for every IMAP fetch the worker does.

**Pattern B — try/except wrapper at the fetch site (more surgical):**

```python
try:
    body = msg.get_payload(decode=True).decode(encoding)
except LookupError as e:
    if 'unknown-8bit' in str(e).lower():
        # RFC 1428/1652 fallback to latin-1
        body = msg.get_payload(decode=True).decode('latin-1', errors='replace')
        log.warning(
            "captain_imap_fetch_unknown_8bit_fallback",
            mailbox=mailbox_alias,
            mid=msg_id,
            fallback="latin-1",
        )
    else:
        raise
```

**Recommendation:** Pattern A. It's the same fix the issue body describes, it's centralized, and it doesn't require touching every decode call site. If Captain has multiple decode call sites, Pattern A covers all of them. If Pattern A introduces unforeseen side effects in tests, fall back to Pattern B.

### 3.3 Tests

Create `backend/tests/services/test_captain_unknown_8bit.py`:

```python
"""Issue #259 — captain unknown-8bit codec shim.

RFC 1428/1652 'unknown-8bit' is a MIME encoding declaration meaning '8-bit
content of unknown character set'. Python's stdlib codecs lookup has no
registered entry for it; raw decode raises LookupError. Captain's IMAP
fetch path needs to map this to latin-1 (permissive 8-bit fallback).
"""
import codecs

def test_unknown_8bit_codec_resolves_to_latin1():
    """After Captain module import, codecs.lookup('unknown-8bit') succeeds."""
    # Trigger Captain module import to register the codec
    import backend.services.captain_multi_mailbox  # noqa: F401
    
    info = codecs.lookup('unknown-8bit')
    assert info.name == 'iso8859-1'  # latin-1's canonical Python codec name


def test_unknown_8bit_decodes_arbitrary_bytes():
    """Every byte 0x00-0xff round-trips through the unknown-8bit codec."""
    import backend.services.captain_multi_mailbox  # noqa: F401
    
    raw = bytes(range(256))
    decoded = raw.decode('unknown-8bit')
    assert len(decoded) == 256
    assert decoded.encode('unknown-8bit') == raw


def test_unknown_8bit_case_variants():
    """Codec name lookup is case-insensitive and tolerates underscore variant."""
    import backend.services.captain_multi_mailbox  # noqa: F401
    
    assert codecs.lookup('unknown-8bit').name == codecs.lookup('UNKNOWN-8BIT').name
    assert codecs.lookup('unknown_8bit').name == codecs.lookup('unknown-8bit').name


def test_email_parse_with_unknown_8bit_charset():
    """Real-world: parse a message claiming charset='unknown-8bit'."""
    import backend.services.captain_multi_mailbox  # noqa: F401
    from email import message_from_bytes
    
    raw_msg = (
        b"From: test@example.com\r\n"
        b"Subject: Test\r\n"
        b"Content-Type: text/plain; charset=\"unknown-8bit\"\r\n"
        b"Content-Transfer-Encoding: 8bit\r\n"
        b"\r\n"
        b"Hello \xe9\xe8\xe0 world\r\n"  # bytes that fail strict utf-8
    )
    msg = message_from_bytes(raw_msg)
    payload = msg.get_payload(decode=True).decode(msg.get_content_charset())
    assert "Hello" in payload
    assert "world" in payload
```

### 3.4 Smoke test against journalctl

After applying the fix, the next Captain patrol should NOT log `captain_imap_fetch_error error='unknown encoding: unknown-8bit'`. We can't verify this until cutover (which is post-merge), so it's a follow-up check, not a CI gate.

Add a one-liner to the PR body: "post-merge verification: tail Captain journalctl for 1 patrol cycle, confirm zero `unknown-8bit` errors."

### 3.5 Commit 2

```bash
git add backend/services/captain_multi_mailbox.py backend/tests/services/test_captain_unknown_8bit.py
git status
git commit -m "fix(captain): register codecs shim for MIME 'unknown-8bit' (#259)

Closes #259.

RFC 1428/1652 'unknown-8bit' is a legitimate MIME encoding declaration meaning
'8-bit content of unknown character set'. Python's stdlib codecs registry has
no entry for it, causing LookupError on parse. Captain's IMAP fetch path was
silently dropping ~10 messages per patrol on the gary-crog mailbox.

Fix: register a codecs.register search function at Captain module import time
that maps 'unknown-8bit' (and case/underscore variants) to the latin-1 codec.
latin-1 is the safe permissive fallback because every byte 0x00-0xff
round-trips without error.

Affected mailbox: gary-crog (Captain pipeline only).
legal_mail_ingester is unaffected (it uses BODY.PEEK[] + permissive decode
already; it does not share Captain's parse path).

Verification:
- 4 unit tests covering codec lookup, byte round-trip, case variants,
  email.message_from_bytes parse with charset='unknown-8bit'
- Post-merge: tail Captain journalctl for next patrol cycle; expect zero
  'unknown encoding: unknown-8bit' errors

Refs: #259, RFC 1428, RFC 1652"
```

**Commit 2 exit criterion:** Tests pass. Captain module imports cleanly. No regression on other Captain tests.

---

## 4. Commit 3 — Issue #260: Captain banded SEARCH for gary-gk

### 4.1 Locate Captain's IMAP SEARCH call

```bash
grep -rn "SEARCH UNSEEN\|SEARCH ALL\|imap.*search\|conn.search\|conn.uid.*SEARCH" \
  backend/services/captain_multi_mailbox.py 2>/dev/null
grep -rn "SEARCH" backend/services/captain_multi_mailbox.py 2>/dev/null | head -10
```

Find the function that does the IMAP SEARCH against each mailbox's UNSEEN range. Likely named `_search_new_mail`, `_fetch_unseen`, or similar.

### 4.2 Implementation pattern (mirror legal_mail_ingester §3.2)

The legal_mail_ingester banded pattern from FLOS Phase 0a v1.1 §3.2 (already in production on this same cluster):

```python
since_date = (today - timedelta(days=mailbox.search_band_days)).strftime("%d-%b-%Y")
typ, data = conn.uid("SEARCH", f"UNSEEN SINCE {since_date}")
```

Captain's current Search is unbounded, so apply the same `SINCE <date>` floor. Recommended scope per the issue body: **`SINCE <last_patrol_at - 1d>`** for incremental polling. For the cold-start case (no `last_patrol_at`), fall back to a hardcoded 30-day floor.

```python
# In Captain's SEARCH function:

def _search_unseen_banded(self, conn, mailbox_alias: str) -> list[bytes]:
    """Issue #260 — banded SEARCH to defend against >1MB result overflow.
    
    Mirrors legal_mail_ingester FLOS Phase 0a v1.1 §3.2 pattern. An unbounded
    SEARCH UNSEEN against gary-gk overflowed the 1MB IMAP client buffer because
    of the mailbox's long history. Pair UNSEEN with a SINCE floor.
    
    Floor logic:
      - If we have a last_patrol_at for this mailbox, SINCE = last_patrol_at - 1d
        (1-day overlap absorbs clock drift / late-arriving mail)
      - Otherwise (cold start), SINCE = today - 30 days
    """
    last_patrol = self._get_last_patrol_at(mailbox_alias)  # may return None
    if last_patrol is not None:
        since_dt = last_patrol - timedelta(days=1)
    else:
        since_dt = datetime.now(timezone.utc) - timedelta(days=30)
    
    since_str = since_dt.strftime("%d-%b-%Y")
    typ, data = conn.uid("SEARCH", "UNSEEN", "SINCE", since_str)
    
    if typ != "OK":
        log.warning(
            "captain_imap_search_failed",
            mailbox=mailbox_alias,
            since=since_str,
            response_type=typ,
        )
        return []
    
    return data[0].split() if data and data[0] else []
```

### 4.3 Where does Captain track `last_patrol_at`?

Captain's per-mailbox state is the open question. Two paths:

**Path A:** Captain already has per-mailbox state (table-backed or file-backed). Find it:

```bash
grep -rn "last_patrol_at\|last_seen_uid\|patrol_state" backend/services/captain_multi_mailbox.py 2>/dev/null
```

**Path B:** Captain has no persistent state. In that case, this fix introduces a hardcoded 30-day floor as the simpler-but-correct choice. Don't add a new state table to Captain in this commit — that's scope creep. The 30-day floor solves the overflow for gary-gk; per-patrol freshness can be a follow-up issue.

**Recommendation:** if Path A exists, use it. If Path B (no state), use hardcoded 30-day floor and leave a comment: `# TODO: per-mailbox last_patrol_at tracking would tighten this; tracked separately`.

### 4.4 Tests

`backend/tests/services/test_captain_banded_search.py`:

```python
"""Issue #260 — Captain banded SEARCH for gary-gk overflow.

Unbounded UNSEEN SEARCH against gary-gk returned >1MB UID list, overflowing
the IMAP client buffer. Banded SEARCH (UNSEEN + SINCE date) bounds the
result set per FLOS Phase 0a v1.1 §3.2 (legal_mail_ingester precedent).
"""
from unittest.mock import MagicMock
from datetime import datetime, timedelta, timezone

def test_banded_search_uses_since_clause(captain_with_mock_conn):
    """SEARCH command always pairs UNSEEN with SINCE."""
    captain, mock_conn = captain_with_mock_conn
    mock_conn.uid.return_value = ("OK", [b""])
    
    captain._search_unseen_banded(mock_conn, "gary-gk")
    
    args = mock_conn.uid.call_args[0]
    assert args[0] == "SEARCH"
    assert "UNSEEN" in args
    assert "SINCE" in args


def test_banded_search_cold_start_uses_30_day_floor(captain_with_mock_conn_cold):
    """When no last_patrol_at exists, SINCE = today - 30 days."""
    captain, mock_conn = captain_with_mock_conn_cold
    mock_conn.uid.return_value = ("OK", [b""])
    
    captain._search_unseen_banded(mock_conn, "gary-gk")
    
    args = mock_conn.uid.call_args[0]
    since_idx = args.index("SINCE")
    since_str = args[since_idx + 1]
    since_dt = datetime.strptime(since_str, "%d-%b-%Y").replace(tzinfo=timezone.utc)
    expected_floor = datetime.now(timezone.utc) - timedelta(days=30)
    
    # Within 1 day of expected floor (date precision, not timestamp)
    assert abs((since_dt - expected_floor).total_seconds()) < 86400


def test_banded_search_with_last_patrol_uses_overlap(captain_with_mock_conn):
    """When last_patrol_at exists, SINCE = last_patrol_at - 1d (overlap absorbs drift)."""
    captain, mock_conn = captain_with_mock_conn
    mock_conn.uid.return_value = ("OK", [b""])
    last_patrol = datetime.now(timezone.utc) - timedelta(hours=2)
    captain._set_last_patrol_at_for_test("gary-gk", last_patrol)
    
    captain._search_unseen_banded(mock_conn, "gary-gk")
    
    args = mock_conn.uid.call_args[0]
    since_idx = args.index("SINCE")
    since_str = args[since_idx + 1]
    since_dt = datetime.strptime(since_str, "%d-%b-%Y").replace(tzinfo=timezone.utc)
    expected_floor = last_patrol - timedelta(days=1)
    
    assert abs((since_dt - expected_floor).total_seconds()) < 86400


def test_banded_search_returns_empty_on_search_failure(captain_with_mock_conn):
    """If SEARCH returns non-OK, log warning and return []. Patrol continues."""
    captain, mock_conn = captain_with_mock_conn
    mock_conn.uid.return_value = ("NO", [b"some error"])
    
    result = captain._search_unseen_banded(mock_conn, "gary-gk")
    
    assert result == []


def test_no_unbounded_search_path_remains(monkeypatch):
    """Regression guard: there is no code path that issues SEARCH without SINCE."""
    import backend.services.captain_multi_mailbox as captain_module
    import inspect
    
    src = inspect.getsource(captain_module)
    # Allowed: 'SEARCH UNSEEN SINCE' or 'SEARCH', 'UNSEEN', 'SINCE' as separate args
    # Forbidden: 'SEARCH UNSEEN' without 'SINCE' nearby, or 'SEARCH ALL'
    assert "SEARCH ALL" not in src.upper()
    # If 'SEARCH UNSEEN' appears as a single literal, 'SINCE' must appear within 100 chars
    idx = src.upper().find("SEARCH UNSEEN")
    if idx != -1:
        window = src[idx:idx+200].upper()
        assert "SINCE" in window, "SEARCH UNSEEN found without nearby SINCE clause"
```

(Fixtures `captain_with_mock_conn` / `captain_with_mock_conn_cold` go in `conftest.py` under the test dir; pattern depends on Captain's existing test infrastructure — adapt to whatever's already there.)

### 4.5 Commit 3

```bash
git add backend/services/captain_multi_mailbox.py backend/tests/services/test_captain_banded_search.py
git status
git commit -m "fix(captain): banded SEARCH for gary-gk overflow defense (#260)

Closes #260.

Captain's unbounded UNSEEN SEARCH against gary-gk returned >1MB UID list,
overflowing the IMAP client buffer (got more than 1000000 bytes). Mailbox
disconnected per cycle.

Fix: pair UNSEEN with a SINCE date floor, mirroring legal_mail_ingester's
FLOS Phase 0a v1.1 §3.2 banded SEARCH pattern (already in production on
this cluster).

Floor logic:
- If last_patrol_at exists for the mailbox: SINCE = last_patrol_at - 1d
  (1-day overlap absorbs clock drift / late-arriving mail)
- Cold start: SINCE = today - 30 days

Affected mailbox: gary-gk (Captain pipeline only).
legal_mail_ingester is unaffected — it has been using this pattern since
Phase 0a-2 (sub-phase 2B, commit bb8aecd27).

Verification:
- 5 unit tests covering banded SINCE clause, cold-start floor, last_patrol
  overlap logic, search-failure graceful degradation, regression guard
  against unbounded SEARCH
- Post-merge: tail Captain journalctl for gary-gk patrol cycle; expect zero
  'got more than 1000000 bytes' errors

Refs: #260, FLOS Phase 0a v1.1 §3.2, legal_mail_ingester sub-phase 2B"
```

**Commit 3 exit criterion:** Tests pass. Captain still ingests on the 3 currently-working mailboxes (regression check below).

---

## 5. Pre-PR full-suite regression

```bash
python3 -m pytest backend/tests/ -x --tb=short 2>&1 | tail -50
```

If anything breaks beyond the 3 new test files, halt and surface. The fixes are surgical; broad regressions mean Captain has hidden coupling we missed.

Specifically check:
- legal_mail_ingester tests still pass (they should — we didn't touch its files)
- Captain's existing tests still pass on the 3 working mailboxes
- alembic migration tests (if any exist) still pass

---

## 6. Push + PR

```bash
git push -u origin fix/captain-hardening-and-alembic-merge-2026-05-02

gh pr create --base main --head fix/captain-hardening-and-alembic-merge-2026-05-02 \
  --title "Captain hardening + alembic reconciliation (#259, #260, #279)" \
  --body "$(cat <<'EOF'
## Summary

Three pre-counsel-hire fixes in a single PR, three commits:

1. **#279** — alembic merge migration joining divergent fortress_db heads. Unblocks M3 activation step 4. No schema drift.
2. **#259** — codec shim for MIME 'unknown-8bit' on Captain. ~10 messages/patrol on gary-crog were dropping; now decoded via latin-1 fallback per RFC 1428/1652.
3. **#260** — banded SEARCH (UNSEEN + SINCE) for Captain. gary-gk's >1MB SEARCH overflow defended by mirroring legal_mail_ingester's FLOS Phase 0a v1.1 §3.2 pattern.

## Why now

Counsel hire is 2026-05-08. These three issues could surface in the first 48 hours of counsel review:
- Divergent alembic heads block any future schema work counsel's eDiscovery tools might need
- Captain dropping ~10 messages/patrol on gary-crog is a preservation gap worth closing
- gary-gk Captain disconnect per cycle means the `llm_training_captures` substrate is degraded for one custodian's mailbox

## Scope discipline

- legal_mail_ingester is **untouched**. It's a separate pipeline already using the right patterns.
- Issue #204 alembic orphan head is **untouched**. Separate divergence, separate resolution path.
- Issue #261 (.env stale keys) is **untouched** beyond noting MAILPLUS_PASSWORD_GARY appears unreferenced. Separate cleanup.
- No new state tables on Captain. If Captain has no persistent last_patrol_at, the fix uses a hardcoded 30-day floor with a TODO marker.

## Verification

- 9 new unit tests across the three commits
- pg_dump schema-only diff before/after alembic merge: no schema drift
- alembic_version table verified post-merge
- Existing test suite passes (no regression)

## Post-merge follow-up (operator-driven)

- Tail Captain journalctl for 1-2 patrol cycles after merge:
  - Confirm zero `unknown encoding: unknown-8bit` errors (#259)
  - Confirm zero `got more than 1000000 bytes` errors (#260)
- Verify gary-crog ingestion volume returns to normal for next 7 days
- Verify gary-gk ingestion via Captain resumes (was 0/patrol due to overflow)

## Standing constraints respected

- Branched from origin/main
- No --admin, no --force, no self-merge
- Single CC session on spark-2 (email_pipeline + this session only)
- Frontier 200 throughout
- Phase-per-commit discipline

EOF
)"
```

**Surface PR URL and stop.** Do not merge. Operator merges from iMac.

---

## 7. Hard stops

Halt and surface to operator if any of these fire:

1. Frontier health degrades (non-200 sustained >60s)
2. `alembic merge` produces unexpected output (more than 2 named heads beyond the Issue #204 orphan, or schema drift in pre/post pg_dump diff)
3. `alembic upgrade head` fails or takes longer than 10 seconds
4. Test suite regression beyond the 3 new test files
5. Captain module import breaks after codec shim addition
6. PR creation fails (auth, branch protection)
7. Branch contamination detected (local main differs from origin/main)
8. Wave 7 Case II briefing pipeline interference (other tmux session crashes, fortress-arq-worker restarts unexpectedly)

If a hard stop fires: stop, do not retry, surface failure with full context.

---

## 8. Time budget

- Pre-flight: 5 min
- Commit 1 (#279 alembic merge): 30-45 min including pg_dump snapshots and verification
- Commit 2 (#259 codec shim): 30-45 min including 4 tests
- Commit 3 (#260 banded SEARCH): 45-60 min including 5 tests and Captain state discovery
- Pre-PR regression: 5-10 min
- PR creation: 10 min
- **Total: 2-3 hours.**

If at the 3-hour mark Commit 3 is still in progress, stop, push commits 1+2 only as a partial PR, surface to operator. Don't ship Commit 3 half-done at 1am.

---

## 9. Reference

- Issues: #259, #260, #279
- FLOS Phase 0a v1.1 §3.2 (banded SEARCH precedent): `docs/architecture/cross-division/FLOS-phase-0a-legal-email-ingester-design-v1.1.md`
- legal_mail_ingester sub-phase 2B (banded SEARCH implementation): commit bb8aecd27
- Issue #204 (alembic orphan, separate): noted in #279 body
- RFC 1428 / RFC 1652: 'unknown-8bit' MIME encoding declaration

---

**End of brief.** Single PR, three commits, operator merges, three issues closed.
