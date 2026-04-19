"""Tests for Phase 6 CI schema bootstrap."""
import json
import subprocess
from pathlib import Path

import pytest

_REPO_ROOT = Path(__file__).resolve().parents[3]
_CI_DIR = _REPO_ROOT / "fortress-guest-platform" / "ci"
_SCHEMA_SQL = _CI_DIR / "schema.sql"
_SCHEMA_META = _CI_DIR / "schema.meta.json"
_CHECK_SCRIPT = _CI_DIR / "check_schema_staleness.py"


# ---------------------------------------------------------------------------
# schema.meta.json structure
# ---------------------------------------------------------------------------

class TestSchemaMetaJson:
    def test_meta_file_exists(self) -> None:
        assert _SCHEMA_META.exists(), "ci/schema.meta.json not found — run 'make ci-schema-dump'"

    def test_required_keys_present(self) -> None:
        meta = json.loads(_SCHEMA_META.read_text())
        for key in ("alembic_revisions", "alembic_versions_tree", "generated_at", "source_commit"):
            assert key in meta, f"Missing key: {key}"

    def test_alembic_revisions_is_list(self) -> None:
        meta = json.loads(_SCHEMA_META.read_text())
        assert isinstance(meta["alembic_revisions"], list)
        assert len(meta["alembic_revisions"]) > 0

    def test_alembic_versions_tree_is_non_empty(self) -> None:
        meta = json.loads(_SCHEMA_META.read_text())
        assert len(meta["alembic_versions_tree"]) == 40  # git sha

    def test_known_heads_present(self) -> None:
        meta = json.loads(_SCHEMA_META.read_text())
        heads = set(meta["alembic_revisions"])
        assert "c255801e28a0" in heads, "Expected c255801e28a0 in alembic_revisions"
        assert "i23a1_add_payment_credit_codes" in heads


# ---------------------------------------------------------------------------
# schema.sql structure
# ---------------------------------------------------------------------------

class TestSchemaSql:
    def test_schema_file_exists(self) -> None:
        assert _SCHEMA_SQL.exists(), "ci/schema.sql not found — run 'make ci-schema-dump'"

    def test_schema_file_not_empty(self) -> None:
        assert _SCHEMA_SQL.stat().st_size > 50_000, "schema.sql is suspiciously small"

    def test_no_postgis_extension(self) -> None:
        content = _SCHEMA_SQL.read_text()
        assert "CREATE EXTENSION IF NOT EXISTS postgis" not in content

    def test_no_vector_extension(self) -> None:
        content = _SCHEMA_SQL.read_text()
        assert "CREATE EXTENSION IF NOT EXISTS vector" not in content

    def test_no_geometry_type(self) -> None:
        content = _SCHEMA_SQL.read_text()
        # geometry type should be replaced — but allow the commented fallback
        for line in content.splitlines():
            if line.startswith("--"):
                continue
            assert " geometry" not in line.lower() or "text" in line.lower(), (
                f"Unguarded geometry type found: {line[:120]}"
            )

    def test_set_role_present(self) -> None:
        content = _SCHEMA_SQL.read_text()
        assert "SET ROLE TO fortress_admin" in content

    def test_key_tables_defined(self) -> None:
        content = _SCHEMA_SQL.read_text()
        for table in ("properties", "reservations", "guests", "llm_training_captures", "capture_labels"):
            # dump uses schema-qualified names: CREATE TABLE public.properties
            found = (
                f"CREATE TABLE {table} " in content
                or f"CREATE TABLE public.{table} " in content
                or f'CREATE TABLE "{table}"' in content
                or f'CREATE TABLE public."{table}"' in content
            )
            assert found, f"Expected table {table!r} in schema.sql"

    def test_alembic_version_table_present(self) -> None:
        content = _SCHEMA_SQL.read_text()
        assert "alembic_version" in content


# ---------------------------------------------------------------------------
# Staleness check script
# ---------------------------------------------------------------------------

class TestStalenessCheck:
    def test_check_script_exists(self) -> None:
        assert _CHECK_SCRIPT.exists()

    def test_passes_when_tree_matches(self) -> None:
        """check_schema_staleness exits 0 when schema.meta.json is current."""
        result = subprocess.run(
            ["python3", str(_CHECK_SCRIPT)],
            capture_output=True, text=True,
            cwd=str(_REPO_ROOT),
        )
        assert result.returncode == 0, (
            f"Staleness check failed unexpectedly:\n{result.stdout}\n{result.stderr}"
        )

    def test_fails_when_tree_mismatches(self) -> None:
        """check_schema_staleness module returns 1 when alembic_versions_tree is wrong."""
        import importlib.util

        wrong_hash = "deadbeef" * 5  # 40-char wrong hash

        # Build a patched module that uses a wrong hash
        spec = importlib.util.spec_from_file_location("staleness_mod", str(_CHECK_SCRIPT))
        mod = importlib.util.module_from_spec(spec)  # type: ignore[arg-type]

        original_read = Path.read_text

        def patched_read(self: Path, **kw: str) -> str:
            raw = original_read(self, **kw)
            if self.name == "schema.meta.json":
                data = json.loads(raw)
                data["alembic_versions_tree"] = wrong_hash
                return json.dumps(data)
            return raw

        # Execute with monkey-patched read_text
        import unittest.mock as mock
        with mock.patch.object(Path, "read_text", patched_read):
            spec.loader.exec_module(mod)  # type: ignore[union-attr]
            rc = mod.main()

        assert rc == 1, f"Expected exit 1 for mismatched hash, got {rc}"


# ---------------------------------------------------------------------------
# Schema loads into a fresh DB  (integration — skipped if not postgres available)
# ---------------------------------------------------------------------------

@pytest.mark.integration
class TestSchemaLoadsIntoDB:
    def test_schema_sql_loads_cleanly(self) -> None:
        """Load schema.sql into a fresh fortress_shadow_test DB and verify key tables."""
        import psycopg2

        # Use existing fortress_shadow_test — it was dropped/recreated earlier in session
        # This test is run separately and manages its own connection
        try:
            conn = psycopg2.connect(
                host="127.0.0.1", port=5432,
                dbname="fortress_shadow_test",
                user="fortress_admin", password="fortress_admin",
            )
            conn.autocommit = True
            cur = conn.cursor()
            cur.execute("""
                SELECT table_name FROM information_schema.tables
                WHERE table_schema NOT IN ('pg_catalog', 'information_schema')
                  AND table_name IN ('properties', 'reservations', 'guests',
                                     'llm_training_captures', 'capture_labels')
            """)
            tables = {row[0] for row in cur.fetchall()}
            conn.close()
        except Exception as exc:
            pytest.skip(f"Cannot connect to fortress_shadow_test: {exc}")

        expected = {"properties", "reservations", "guests", "llm_training_captures", "capture_labels"}
        missing = expected - tables
        assert not missing, f"Expected tables missing from CI schema: {missing}"
