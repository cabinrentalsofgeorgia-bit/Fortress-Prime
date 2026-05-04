from __future__ import annotations

from io import BytesIO

import run  # noqa: F401  (registers settings + paths)
from openpyxl import Workbook

from backend.services.legal_ediscovery import _extract_text


def _workbook_bytes() -> bytes:
    workbook = Workbook()
    worksheet = workbook.active
    worksheet.title = "Inspection Comments"
    worksheet.append(["Item", "Observation", "Responsible Party"])
    worksheet.append(["Driveway", "Repair gravel apron", "Seller"])
    worksheet.append(["Easement", "Confirm foot path access", "Counsel review"])
    workbook.create_sheet("Empty Sheet")

    output = BytesIO()
    workbook.save(output)
    workbook.close()
    return output.getvalue()


def test_extract_text_uses_clean_xlsx_cell_values() -> None:
    text = _extract_text(
        _workbook_bytes(),
        "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        "Inspection Comments(89340812.1).xlsx",
    )

    assert "Sheet: Inspection Comments" in text
    assert "Item\tObservation\tResponsible Party" in text
    assert "Driveway\tRepair gravel apron\tSeller" in text
    assert "Easement\tConfirm foot path access\tCounsel review" in text
    assert "Empty Sheet" not in text


def test_extract_text_does_not_decode_xlsx_zip_internals() -> None:
    text = _extract_text(
        _workbook_bytes(),
        "application/octet-stream",
        "inspection-comments.xlsx",
    )

    assert "[Content_Types].xml" not in text
    assert "xl/worksheets" not in text
    assert "PK" not in text[:40]
    assert "Repair gravel apron" in text
