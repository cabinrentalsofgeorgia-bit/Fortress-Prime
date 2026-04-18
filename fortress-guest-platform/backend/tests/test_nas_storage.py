"""
Integration tests for NAS storage — work order photos and acquisition documents.

Tests exercise the local fallback path (since /mnt/fortress_nas is not present
in the test environment). The fallback logic is identical to the NAS path.

Tests:
1.  config has nas_work_orders_root and nas_acquisitions_root with correct defaults
2.  _resolve_wo_nas_dir creates fallback directory when NAS absent
3.  _resolve_acq_nas_dir creates fallback directory when NAS absent
4.  work order photo upload writes file to disk and stores path in photo_urls
5.  work order photo download returns file content
6.  work order photo download rejects path traversal (..)
7.  work order photo upload rejects unsupported content type
8.  work order photo upload rejects oversized file
9.  acquisition document upload writes file to disk and stores DB row
10. acquisition document list returns uploaded doc
11. acquisition document download returns file content
12. acquisition document upload rejects invalid doc_type
13. acquisition_documents table exists in crog_acquisition schema
14. acquisition document download returns 403 for path outside valid roots
"""
from __future__ import annotations

import io
import uuid
from pathlib import Path

import psycopg2
import pytest
from backend.tests.db_helpers import get_test_dsn

DSN = get_test_dsn()

# ── 1. Config ─────────────────────────────────────────────────────────────────

def test_config_has_nas_roots():
    from backend.core.config import settings
    assert hasattr(settings, "nas_work_orders_root")
    assert hasattr(settings, "nas_acquisitions_root")
    assert settings.nas_work_orders_root == "/mnt/fortress_nas/work_orders"
    assert settings.nas_acquisitions_root == "/mnt/fortress_nas/acquisitions"

# ── 2–3. Directory resolution (fallback) ─────────────────────────────────────

def test_wo_nas_dir_creates_fallback_when_nas_absent(tmp_path, monkeypatch):
    """When NAS root doesn't exist, fallback dir is created under _WO_NAS_FALLBACK."""
    import backend.api.workorders as wo_mod

    # Point fallback to a temp dir so we don't litter the real filesystem
    monkeypatch.setattr(wo_mod, "_WO_NAS_ROOT", Path("/nonexistent_nas_xyz"))
    monkeypatch.setattr(wo_mod, "_WO_NAS_FALLBACK", tmp_path / "wo_fallback")

    wo_id = uuid.uuid4().hex
    result_dir = wo_mod._resolve_wo_nas_dir(wo_id)

    assert result_dir.exists()
    assert result_dir.parent == tmp_path / "wo_fallback"
    assert result_dir.name == wo_id

def test_acq_nas_dir_creates_fallback_when_nas_absent(tmp_path, monkeypatch):
    import backend.api.acquisition_pipeline as acq_mod

    monkeypatch.setattr(acq_mod, "_ACQ_NAS_ROOT", Path("/nonexistent_nas_xyz"))
    monkeypatch.setattr(acq_mod, "_ACQ_NAS_FALLBACK", tmp_path / "acq_fallback")

    pid = uuid.uuid4().hex
    result_dir = acq_mod._resolve_acq_nas_dir(pid)

    assert result_dir.exists()
    assert result_dir.parent == tmp_path / "acq_fallback"
    assert result_dir.name == pid

# ── 4–8. Work order photo upload / download ───────────────────────────────────

@pytest.mark.asyncio
async def test_work_order_photo_upload_writes_to_disk(tmp_path, monkeypatch):
    import backend.api.workorders as wo_mod
    from backend.core.database import AsyncSessionLocal
    from backend.models.workorder import WorkOrder

    # Use tmp_path as fallback so files are cleaned up after test
    monkeypatch.setattr(wo_mod, "_WO_NAS_ROOT", Path("/nonexistent_nas_xyz"))
    monkeypatch.setattr(wo_mod, "_WO_NAS_FALLBACK", tmp_path / "wo")
    monkeypatch.setattr(wo_mod, "_WO_VALID_ROOTS", (
        str(Path("/nonexistent_nas_xyz")), str(tmp_path / "wo")
    ))

    # Create a real work order
    conn = psycopg2.connect(DSN)
    cur = conn.cursor()
    cur.execute("SELECT id FROM properties WHERE is_active=true LIMIT 1")
    prop_id = cur.fetchone()[0]
    conn.close()

    async with AsyncSessionLocal() as db:
        wo = WorkOrder(
            ticket_number=f"WO-NAS-{uuid.uuid4().hex[:6]}",
            property_id=prop_id,
            title="NAS test work order",
            description="Test",
            category="other",
            priority="medium",
            status="open",
            created_by="test",
        )
        db.add(wo)
        await db.commit()
        wo_id = wo.id

    # Build a fake UploadFile
    from fastapi import UploadFile
    from unittest.mock import AsyncMock, MagicMock
    fake_file = MagicMock(spec=UploadFile)
    fake_file.content_type = "image/jpeg"
    fake_file.filename = "test_photo.jpg"
    fake_file.read = AsyncMock(return_value=b"\xff\xd8\xff" + b"\x00" * 100)

    async with AsyncSessionLocal() as db:
        result = await wo_mod.upload_work_order_photo(
            work_order_id=wo_id,
            file=fake_file,
            db=db,
        )

    assert "photo_url" in result
    assert "nfs_path" in result
    assert result["total_photos"] == 1

    # File should exist on disk
    nfs_path = Path(result["nfs_path"])
    assert nfs_path.exists()
    assert nfs_path.stat().st_size == 103  # 3 + 100 bytes

    # photo_urls should contain the path
    async with AsyncSessionLocal() as db:
        wo = await db.get(WorkOrder, wo_id)
        assert len(wo.photo_urls) == 1
        assert wo.photo_urls[0] == str(nfs_path)

@pytest.mark.asyncio
async def test_work_order_photo_download_serves_file(tmp_path, monkeypatch):
    import backend.api.workorders as wo_mod
    from backend.core.database import AsyncSessionLocal
    from backend.models.workorder import WorkOrder

    monkeypatch.setattr(wo_mod, "_WO_NAS_ROOT", Path("/nonexistent_nas_xyz"))
    monkeypatch.setattr(wo_mod, "_WO_NAS_FALLBACK", tmp_path / "wo")
    monkeypatch.setattr(wo_mod, "_WO_VALID_ROOTS", (
        str(Path("/nonexistent_nas_xyz")), str(tmp_path / "wo")
    ))

    conn = psycopg2.connect(DSN)
    cur = conn.cursor()
    cur.execute("SELECT id FROM properties WHERE is_active=true LIMIT 1")
    prop_id = cur.fetchone()[0]
    conn.close()

    file_content = b"\xff\xd8\xff" + b"\xAB" * 50
    file_name = "download_test.jpg"

    # Write file directly to fallback dir
    wo_uuid = uuid.uuid4()
    file_dir = tmp_path / "wo" / str(wo_uuid)
    file_dir.mkdir(parents=True)
    stored_name = f"abc12345_{file_name}"
    (file_dir / stored_name).write_bytes(file_content)

    async with AsyncSessionLocal() as db:
        wo = WorkOrder(
            ticket_number=f"WO-DL-{uuid.uuid4().hex[:6]}",
            property_id=prop_id,
            title="Download test",
            description="Test",
            category="other",
            priority="medium",
            status="open",
            created_by="test",
            photo_urls=[str(file_dir / stored_name)],
        )
        db.add(wo)
        await db.commit()
        wo_id = wo.id

    async with AsyncSessionLocal() as db:
        response = await wo_mod.download_work_order_photo(
            work_order_id=wo_id,
            filename=stored_name,
            db=db,
        )

    from fastapi.responses import FileResponse
    assert isinstance(response, FileResponse)
    assert response.path == str((file_dir / stored_name).resolve())

@pytest.mark.asyncio
async def test_work_order_photo_rejects_path_traversal(tmp_path, monkeypatch):
    import backend.api.workorders as wo_mod
    from backend.core.database import AsyncSessionLocal
    from backend.models.workorder import WorkOrder
    from fastapi import HTTPException

    conn = psycopg2.connect(DSN)
    cur = conn.cursor()
    cur.execute("SELECT id FROM properties WHERE is_active=true LIMIT 1")
    prop_id = cur.fetchone()[0]
    conn.close()

    async with AsyncSessionLocal() as db:
        wo = WorkOrder(
            ticket_number=f"WO-TRAV-{uuid.uuid4().hex[:6]}",
            property_id=prop_id,
            title="Traversal test",
            description="Test",
            category="other",
            priority="medium",
            status="open",
            created_by="test",
        )
        db.add(wo)
        await db.commit()
        wo_id = wo.id

    async with AsyncSessionLocal() as db:
        with pytest.raises(HTTPException) as exc_info:
            await wo_mod.download_work_order_photo(
                work_order_id=wo_id,
                filename="../../etc/passwd",
                db=db,
            )
    assert exc_info.value.status_code == 400

@pytest.mark.asyncio
async def test_work_order_photo_rejects_bad_content_type(tmp_path, monkeypatch):
    import backend.api.workorders as wo_mod
    from backend.core.database import AsyncSessionLocal
    from backend.models.workorder import WorkOrder
    from fastapi import HTTPException, UploadFile
    from unittest.mock import AsyncMock, MagicMock

    conn = psycopg2.connect(DSN)
    cur = conn.cursor()
    cur.execute("SELECT id FROM properties WHERE is_active=true LIMIT 1")
    prop_id = cur.fetchone()[0]
    conn.close()

    async with AsyncSessionLocal() as db:
        wo = WorkOrder(
            ticket_number=f"WO-CT-{uuid.uuid4().hex[:6]}",
            property_id=prop_id,
            title="Content type test",
            description="Test",
            category="other",
            priority="medium",
            status="open",
            created_by="test",
        )
        db.add(wo)
        await db.commit()
        wo_id = wo.id

    fake_file = MagicMock(spec=UploadFile)
    fake_file.content_type = "application/executable"
    fake_file.filename = "bad.exe"
    fake_file.read = AsyncMock(return_value=b"MZ\x00" * 10)

    async with AsyncSessionLocal() as db:
        with pytest.raises(HTTPException) as exc_info:
            await wo_mod.upload_work_order_photo(work_order_id=wo_id, file=fake_file, db=db)
    assert exc_info.value.status_code == 415

@pytest.mark.asyncio
async def test_work_order_photo_rejects_oversized_file(tmp_path, monkeypatch):
    import backend.api.workorders as wo_mod
    from backend.core.database import AsyncSessionLocal
    from backend.models.workorder import WorkOrder
    from fastapi import HTTPException, UploadFile
    from unittest.mock import AsyncMock, MagicMock

    conn = psycopg2.connect(DSN)
    cur = conn.cursor()
    cur.execute("SELECT id FROM properties WHERE is_active=true LIMIT 1")
    prop_id = cur.fetchone()[0]
    conn.close()

    async with AsyncSessionLocal() as db:
        wo = WorkOrder(
            ticket_number=f"WO-SZ-{uuid.uuid4().hex[:6]}",
            property_id=prop_id,
            title="Size test",
            description="Test",
            category="other",
            priority="medium",
            status="open",
            created_by="test",
        )
        db.add(wo)
        await db.commit()
        wo_id = wo.id

    fake_file = MagicMock(spec=UploadFile)
    fake_file.content_type = "image/jpeg"
    fake_file.filename = "huge.jpg"
    # 21 MB — over the 20 MB limit
    fake_file.read = AsyncMock(return_value=b"\xff" * (21 * 1024 * 1024))

    async with AsyncSessionLocal() as db:
        with pytest.raises(HTTPException) as exc_info:
            await wo_mod.upload_work_order_photo(work_order_id=wo_id, file=fake_file, db=db)
    assert exc_info.value.status_code == 413

# ── 9–12. Acquisition document upload / list / download ──────────────────────

def _make_pipeline(db_conn):
    """Helper: create minimal pipeline entry, return pipeline_id as UUID."""
    import psycopg2.extras
    with psycopg2.connect(DSN) as conn:
        with conn.cursor() as cur:
            # Create parcel + property + pipeline
            cur.execute("""
                INSERT INTO crog_acquisition.parcels
                    (parcel_id, county_name, assessed_value)
                VALUES (%s, 'Fannin', 100000)
                RETURNING id
            """, (f"NAS-TEST-{uuid.uuid4().hex[:8]}",))
            parcel_id = cur.fetchone()[0]

            cur.execute("""
                INSERT INTO crog_acquisition.properties (parcel_id)
                VALUES (%s) RETURNING id
            """, (str(parcel_id),))
            prop_id = cur.fetchone()[0]

            cur.execute("""
                INSERT INTO crog_acquisition.acquisition_pipeline (property_id, stage)
                VALUES (%s, 'RADAR') RETURNING id
            """, (str(prop_id),))
            pipeline_id = cur.fetchone()[0]
            conn.commit()
    return pipeline_id

@pytest.mark.asyncio
async def test_acquisition_document_upload_writes_to_disk(tmp_path, monkeypatch):
    import backend.api.acquisition_pipeline as acq_mod
    from backend.core.database import AsyncSessionLocal
    from fastapi import UploadFile
    from unittest.mock import AsyncMock, MagicMock

    monkeypatch.setattr(acq_mod, "_ACQ_NAS_ROOT", Path("/nonexistent_nas_xyz"))
    monkeypatch.setattr(acq_mod, "_ACQ_NAS_FALLBACK", tmp_path / "acq")
    monkeypatch.setattr(acq_mod, "_ACQ_VALID_ROOTS", (
        str(Path("/nonexistent_nas_xyz")), str(tmp_path / "acq")
    ))

    pipeline_id = str(_make_pipeline(None))

    fake_pdf = MagicMock(spec=UploadFile)
    fake_pdf.content_type = "application/pdf"
    fake_pdf.filename = "inspection_report.pdf"
    pdf_content = b"%PDF-1.4 fake content"
    fake_pdf.read = AsyncMock(return_value=pdf_content)

    async with AsyncSessionLocal() as db:
        result = await acq_mod.upload_acquisition_document(
            pipeline_id=pipeline_id,
            file=fake_pdf,
            doc_type="inspection",
            uploaded_by="Gary Knight",
            db=db,
        )

    assert "document_id" in result
    assert result["file_name"] == "inspection_report.pdf"
    assert result["doc_type"] == "inspection"
    assert "nfs_path" in result
    assert "download_url" in result

    # File should exist on disk
    nfs_path = Path(result["nfs_path"])
    assert nfs_path.exists()
    assert nfs_path.read_bytes() == pdf_content

    # DB row should exist
    conn = psycopg2.connect(DSN)
    cur = conn.cursor()
    cur.execute(
        "SELECT file_name, doc_type, uploaded_by, file_size_bytes "
        "FROM crog_acquisition.acquisition_documents WHERE id=%s",
        (result["document_id"],)
    )
    row = cur.fetchone()
    conn.close()
    assert row is not None
    assert row[0] == "inspection_report.pdf"
    assert row[1] == "inspection"
    assert row[2] == "Gary Knight"
    assert row[3] == len(pdf_content)

@pytest.mark.asyncio
async def test_acquisition_document_list(tmp_path, monkeypatch):
    import backend.api.acquisition_pipeline as acq_mod
    from backend.core.database import AsyncSessionLocal
    from fastapi import UploadFile
    from unittest.mock import AsyncMock, MagicMock

    monkeypatch.setattr(acq_mod, "_ACQ_NAS_ROOT", Path("/nonexistent_nas_xyz"))
    monkeypatch.setattr(acq_mod, "_ACQ_NAS_FALLBACK", tmp_path / "acq_list")

    pipeline_id = str(_make_pipeline(None))

    # Upload a doc first
    fake_pdf = MagicMock(spec=UploadFile)
    fake_pdf.content_type = "text/plain"
    fake_pdf.filename = "notes.txt"
    fake_pdf.read = AsyncMock(return_value=b"meeting notes")

    async with AsyncSessionLocal() as db:
        await acq_mod.upload_acquisition_document(
            pipeline_id=pipeline_id, file=fake_pdf, doc_type="general",
            uploaded_by="", db=db,
        )
        result = await acq_mod.list_acquisition_documents(pipeline_id=pipeline_id, db=db)

    assert result["pipeline_id"] == pipeline_id
    assert result["total"] >= 1
    doc = next(d for d in result["documents"] if d["file_name"] == "notes.txt")
    assert doc["doc_type"] == "general"
    assert "download_url" in doc

@pytest.mark.asyncio
async def test_acquisition_document_download_serves_file(tmp_path, monkeypatch):
    import backend.api.acquisition_pipeline as acq_mod
    from backend.core.database import AsyncSessionLocal
    from fastapi import UploadFile
    from fastapi.responses import FileResponse
    from unittest.mock import AsyncMock, MagicMock

    monkeypatch.setattr(acq_mod, "_ACQ_NAS_ROOT", Path("/nonexistent_nas_xyz"))
    monkeypatch.setattr(acq_mod, "_ACQ_NAS_FALLBACK", tmp_path / "acq_dl")
    monkeypatch.setattr(acq_mod, "_ACQ_VALID_ROOTS", (
        str(Path("/nonexistent_nas_xyz")), str(tmp_path / "acq_dl")
    ))

    pipeline_id = str(_make_pipeline(None))
    csv_content = b"id,address,value\n1,123 Main St,500000"

    fake_csv = MagicMock(spec=UploadFile)
    fake_csv.content_type = "text/csv"
    fake_csv.filename = "comps.csv"
    fake_csv.read = AsyncMock(return_value=csv_content)

    async with AsyncSessionLocal() as db:
        upload_result = await acq_mod.upload_acquisition_document(
            pipeline_id=pipeline_id, file=fake_csv, doc_type="revenue_history",
            uploaded_by="", db=db,
        )
        doc_id = upload_result["document_id"]

        response = await acq_mod.download_acquisition_document(
            pipeline_id=pipeline_id,
            doc_id=doc_id,
            db=db,
        )

    assert isinstance(response, FileResponse)
    assert response.media_type == "text/csv"

@pytest.mark.asyncio
async def test_acquisition_document_rejects_invalid_doc_type(tmp_path, monkeypatch):
    import backend.api.acquisition_pipeline as acq_mod
    from backend.core.database import AsyncSessionLocal
    from fastapi import HTTPException, UploadFile
    from unittest.mock import AsyncMock, MagicMock

    monkeypatch.setattr(acq_mod, "_ACQ_NAS_ROOT", Path("/nonexistent_nas_xyz"))
    monkeypatch.setattr(acq_mod, "_ACQ_NAS_FALLBACK", tmp_path / "acq_bad")

    pipeline_id = str(_make_pipeline(None))

    fake_file = MagicMock(spec=UploadFile)
    fake_file.content_type = "application/pdf"
    fake_file.filename = "file.pdf"
    fake_file.read = AsyncMock(return_value=b"%PDF fake")

    async with AsyncSessionLocal() as db:
        with pytest.raises(HTTPException) as exc_info:
            await acq_mod.upload_acquisition_document(
                pipeline_id=pipeline_id,
                file=fake_file,
                doc_type="invalid_type_xyz",
                uploaded_by="",
                db=db,
            )
    assert exc_info.value.status_code == 422

# ── 13. Schema check ──────────────────────────────────────────────────────────

def test_acquisition_documents_table_exists():
    conn = psycopg2.connect(DSN)
    cur = conn.cursor()
    cur.execute("""
        SELECT column_name FROM information_schema.columns
        WHERE table_schema = 'crog_acquisition' AND table_name = 'acquisition_documents'
        ORDER BY ordinal_position
    """)
    cols = {r[0] for r in cur.fetchall()}
    conn.close()
    required = {"id", "pipeline_id", "file_name", "nfs_path", "mime_type",
                "file_hash", "file_size_bytes", "doc_type", "uploaded_by", "created_at"}
    assert required.issubset(cols), f"Missing columns: {required - cols}"

# ── 14. Path-outside-valid-roots returns 403 ─────────────────────────────────

@pytest.mark.asyncio
async def test_acquisition_document_download_403_outside_roots(tmp_path, monkeypatch):
    """Manually craft a DB row with an nfs_path outside valid roots → 403."""
    import backend.api.acquisition_pipeline as acq_mod
    from backend.core.database import AsyncSessionLocal
    from backend.models.acquisition import AcquisitionDocument
    from fastapi import HTTPException

    monkeypatch.setattr(acq_mod, "_ACQ_NAS_ROOT", Path("/nonexistent_nas_xyz"))
    monkeypatch.setattr(acq_mod, "_ACQ_NAS_FALLBACK", tmp_path / "acq_403")
    monkeypatch.setattr(acq_mod, "_ACQ_VALID_ROOTS", (
        str(Path("/nonexistent_nas_xyz")), str(tmp_path / "acq_403")
    ))

    pipeline_id = str(_make_pipeline(None))

    async with AsyncSessionLocal() as db:
        pid = __import__("uuid").UUID(pipeline_id)
        # Write a doc row whose nfs_path points outside the valid roots
        doc = AcquisitionDocument(
            pipeline_id=pid,
            file_name="evil.txt",
            nfs_path="/tmp/evil.txt",  # outside both valid roots
            mime_type="text/plain",
            doc_type="general",
        )
        db.add(doc)
        await db.commit()
        doc_id = str(doc.id)

        with pytest.raises(HTTPException) as exc_info:
            await acq_mod.download_acquisition_document(
                pipeline_id=pipeline_id, doc_id=doc_id, db=db,
            )
    assert exc_info.value.status_code == 403
