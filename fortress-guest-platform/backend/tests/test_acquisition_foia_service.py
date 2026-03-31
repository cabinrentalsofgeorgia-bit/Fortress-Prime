from __future__ import annotations

from backend.services.acquisition_foia import parse_foia_rows


def test_parse_foia_rows_csv_maps_common_columns() -> None:
    payload = (
        "Parcel Number,Owner Name,Mailing Address,Property Address,Certificate Number\n"
        "0036 011C,Owner One,\"123 Main St, Blue Ridge, GA 30513\",66 Valley Overlook,CERT-1\n"
    ).encode("utf-8")

    rows = parse_foia_rows("fannin.csv", payload)

    assert len(rows) == 1
    assert rows[0].parcel_id == "0036 011C"
    assert rows[0].owner_legal_name == "Owner One"
    assert rows[0].property_address == "66 Valley Overlook"
    assert rows[0].fannin_str_cert_id == "CERT-1"
    assert rows[0].primary_residence_state == "GA"
