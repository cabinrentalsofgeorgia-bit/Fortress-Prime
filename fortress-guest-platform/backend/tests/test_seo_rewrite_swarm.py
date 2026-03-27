from __future__ import annotations

from backend.services.seo_rewrite_swarm import _extract_json_object


def test_extract_json_object_handles_code_fence_and_trailing_comma() -> None:
    payload = _extract_json_object(
        """```json
        {
          "title": "Cabin rewrite",
          "meta_description": "Fresh metadata",
          "jsonld_payload": {
            "@context": "https://schema.org",
            "@type": "LodgingBusiness",
          },
          "alt_tags": {
            "hero": "Mountain view",
          },
        }
        ```"""
    )

    assert payload["title"] == "Cabin rewrite"
    assert payload["jsonld_payload"]["@type"] == "LodgingBusiness"
    assert payload["alt_tags"]["hero"] == "Mountain view"


def test_extract_json_object_ignores_preface_and_stops_at_balanced_object() -> None:
    payload = _extract_json_object(
        """Here is the corrected payload:
        {
          "title": "Repaired title",
          "meta_description": "Repaired description",
          "jsonld_payload": {
            "@context": "https://schema.org",
            "@type": "VacationRental"
          },
          "alt_tags": {
            "kitchen": "Modern kitchen"
          }
        }

        Additional notes that should be ignored.
        """
    )

    assert payload["title"] == "Repaired title"
    assert payload["jsonld_payload"]["@type"] == "VacationRental"
