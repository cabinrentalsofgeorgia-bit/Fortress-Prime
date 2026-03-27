"""Redirect Vanguard KV slug resolution."""

from backend.services.redirect_vanguard_kv import cabin_slug_from_patch_targets


def test_cabin_slug_prefers_property_slug() -> None:
    assert cabin_slug_from_patch_targets(property_slug="The-Rivers-Edge", page_path="/cabins/ignored") == "the-rivers-edge"


def test_cabin_slug_from_page_path() -> None:
    assert cabin_slug_from_patch_targets(property_slug=None, page_path="/cabins/the-rivers-edge") == "the-rivers-edge"
    assert cabin_slug_from_patch_targets(property_slug=None, page_path="/cabins/foo/") == "foo"


def test_cabin_slug_rejects_nested_paths() -> None:
    assert cabin_slug_from_patch_targets(property_slug=None, page_path="/cabins/foo/bar") is None
    assert cabin_slug_from_patch_targets(property_slug=None, page_path="/other") is None
