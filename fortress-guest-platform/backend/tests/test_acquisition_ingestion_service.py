from __future__ import annotations

import pytest

from backend.models.acquisition import MarketState
from backend.services.acquisition_ingestion import (
    AcquisitionIngestionRequest,
    _extract_qpublic_neighborhood_options,
    _market_state_from_company,
    _normalize_firecrawl_records,
    _parse_qpublic_results_markdown,
)


def test_acquisition_request_requires_source_inputs() -> None:
    with pytest.raises(ValueError):
        AcquisitionIngestionRequest(
            qpublic_url=None,
            str_permits_url=None,
            parcel_seed_records=[],
            str_seed_records=[],
        )


def test_market_state_derives_from_management_company() -> None:
    assert _market_state_from_company(None) == MarketState.UNMANAGED
    assert _market_state_from_company("Cabin Rentals of Georgia") == MarketState.CROG_MANAGED
    assert _market_state_from_company("Escape to Blue Ridge") == MarketState.COMPETITOR_MANAGED


def test_normalize_firecrawl_records_accepts_nested_records_key() -> None:
    payload = {
        "success": True,
        "data": {
            "records": [
                {"parcel_id": "123", "assessed_value": 100000},
                {"parcel_id": "456", "assessed_value": 200000},
            ]
        },
    }

    assert _normalize_firecrawl_records(payload) == [
        {"parcel_id": "123", "assessed_value": 100000},
        {"parcel_id": "456", "assessed_value": 200000},
    ]


def test_extract_qpublic_neighborhood_options_reads_select_values() -> None:
    html = """
    <select id="ctlBodyPane_ctl07_ctl01_ddlNeighborhoods">
      <option selected="selected" value="">&lt;ALL&gt;</option>
      <option value="BLUE RIDGE ESCAPE">BLUE RIDGE ESCAPE</option>
      <option value="ASKA OVERLOOK">ASKA OVERLOOK</option>
    </select>
    """

    assert _extract_qpublic_neighborhood_options(html) == [
        "BLUE RIDGE ESCAPE",
        "ASKA OVERLOOK",
    ]


def test_parse_qpublic_results_markdown_extracts_report_rows() -> None:
    markdown = """
|  | Parcel ID | Alternate ID | Owner | Property Address | City | Acres | Class | Map | B_RawParcelID |
| --- | :-- | :-- | :-- | :-- | :-- | --: | :-: | :-- | --- |
| [![](icon)](https://qpublic.schneidercorp.com/Application.aspx?AppID=714&LayerID=11449&PageTypeID=4&PageID=5401&Q=1&KeyValue=0036++++011C) | [0036 011C](https://qpublic.schneidercorp.com/Application.aspx?AppID=714&LayerID=11449&PageTypeID=4&PageID=5401&Q=1&KeyValue=0036++++011C \"View Parcel Report for, 0036    011C\") | 31492 | MACLANE ROBERT | 66 VALLEY OVERLOOK |  | 1.59 | Residential | [Map](https://qpublic.schneidercorp.com/Application.aspx?AppID=714&LayerID=11449&PageTypeID=1&PageID=0&Q=1&KeyValue=0036++++011C) | 0036 011C |
"""

    rows = _parse_qpublic_results_markdown(markdown)

    assert len(rows) == 1
    assert rows[0]["parcel_id"] == "0036    011C"
    assert rows[0]["alternate_id"] == "31492"
    assert rows[0]["property_address"] == "66 VALLEY OVERLOOK"
    assert str(rows[0]["acres"]) == "1.59"
