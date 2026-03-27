"""
Pure-function schema.org JSON-LD builders for SEO patches.
"""
from __future__ import annotations

import re
from typing import Any

from pydantic import BaseModel, ConfigDict, Field

MAX_SCHEMA_AMENITIES = 18
VACATION_RENTAL_TYPES = {"cabin", "cottage", "house", "home", "vacation_rental"}


class GeoCoordinatesSchema(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    at_type: str = Field("GeoCoordinates", alias="@type")
    latitude: float
    longitude: float


class PostalAddressSchema(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    at_type: str = Field("PostalAddress", alias="@type")
    street_address: str | None = Field(default=None, alias="streetAddress")
    address_locality: str | None = Field(default=None, alias="addressLocality")
    address_region: str | None = Field(default=None, alias="addressRegion")
    postal_code: str | None = Field(default=None, alias="postalCode")
    address_country: str | None = Field(default="US", alias="addressCountry")


class PropertyValueSchema(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    at_type: str = Field("PropertyValue", alias="@type")
    property_id: str = Field(alias="propertyID")
    value: str


class LocationFeatureSpecificationSchema(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    at_type: str = Field("LocationFeatureSpecification", alias="@type")
    name: str
    value: bool = True


class QuantitativeValueSchema(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    at_type: str = Field("QuantitativeValue", alias="@type")
    value: int | float | None = None
    unit_text: str | None = Field(default=None, alias="unitText")


class OfferSchema(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    at_type: str = Field("Offer", alias="@type")
    url: str | None = None
    availability: str | None = None
    price: float | None = None
    price_currency: str | None = Field(default=None, alias="priceCurrency")
    eligible_quantity: QuantitativeValueSchema | None = Field(default=None, alias="eligibleQuantity")


class AggregateRatingSchema(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    at_type: str = Field("AggregateRating", alias="@type")
    rating_value: float = Field(alias="ratingValue")
    review_count: int = Field(alias="reviewCount")
    best_rating: int = Field(default=5, alias="bestRating")
    worst_rating: int = Field(default=1, alias="worstRating")


class VacationRentalSchema(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    at_context: str = Field("https://schema.org", alias="@context")
    at_type: str = Field("VacationRental", alias="@type")
    name: str
    description: str
    url: str | None = None
    image: list[str] | None = None
    identifier: list[PropertyValueSchema] | None = None
    address: PostalAddressSchema | None = None
    geo: GeoCoordinatesSchema | None = None
    number_of_rooms: int | None = Field(default=None, alias="numberOfRooms")
    number_of_bedrooms: int | None = Field(default=None, alias="numberOfBedrooms")
    number_of_bathrooms_total: float | None = Field(default=None, alias="numberOfBathroomsTotal")
    maximum_attendee_capacity: int | None = Field(default=None, alias="maximumAttendeeCapacity")
    pets_allowed: bool | None = Field(default=None, alias="petsAllowed")
    amenity_feature: list[LocationFeatureSpecificationSchema] = Field(default_factory=list, alias="amenityFeature")
    offers: OfferSchema | None = None
    aggregate_rating: AggregateRatingSchema | None = Field(default=None, alias="aggregateRating")


class LodgingBusinessSchema(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    at_context: str = Field("https://schema.org", alias="@context")
    at_type: str = Field("LodgingBusiness", alias="@type")
    name: str
    description: str
    url: str | None = None
    image: list[str] | None = None
    identifier: list[PropertyValueSchema] | None = None
    address: PostalAddressSchema | None = None
    geo: GeoCoordinatesSchema | None = None
    number_of_rooms: int | None = Field(default=None, alias="numberOfRooms")
    number_of_bathrooms_total: float | None = Field(default=None, alias="numberOfBathroomsTotal")
    maximum_attendee_capacity: int | None = Field(default=None, alias="maximumAttendeeCapacity")
    amenity_feature: list[LocationFeatureSpecificationSchema] = Field(default_factory=list, alias="amenityFeature")
    offers: OfferSchema | None = None
    aggregate_rating: AggregateRatingSchema | None = Field(default=None, alias="aggregateRating")


def _clean_text(value: Any) -> str | None:
    text = str(value or "").strip()
    return text or None


def _coerce_int(value: Any) -> int | None:
    try:
        return int(value) if value not in (None, "") else None
    except (TypeError, ValueError):
        return None


def _coerce_float(value: Any) -> float | None:
    try:
        return float(value) if value not in (None, "") else None
    except (TypeError, ValueError):
        return None


def _normalize_key(value: str) -> str:
    return re.sub(r"[^a-z0-9]+", "", value.lower())


def _find_first_scalar(payload: Any, aliases: set[str]) -> Any:
    if isinstance(payload, dict):
        for key, value in payload.items():
            if _normalize_key(str(key)) in aliases and value not in (None, "") and not isinstance(value, (dict, list)):
                return value
        for value in payload.values():
            found = _find_first_scalar(value, aliases)
            if found is not None:
                return found
    if isinstance(payload, list):
        for value in payload:
            found = _find_first_scalar(value, aliases)
            if found is not None:
                return found
    return None


def _prune_empty(value: Any) -> Any:
    if isinstance(value, dict):
        pruned = {key: _prune_empty(child) for key, child in value.items()}
        return {key: child for key, child in pruned.items() if child not in (None, "", [], {})}
    if isinstance(value, list):
        pruned = [_prune_empty(child) for child in value]
        return [child for child in pruned if child not in (None, "", [], {})]
    return value


def _absolute_url(raw_value: str, storefront_base_url: str) -> str:
    if raw_value.startswith(("http://", "https://")):
        return raw_value
    return f"{storefront_base_url.rstrip('/')}/{raw_value.lstrip('/')}"


def _resolve_storefront_base_url(property_data: dict[str, Any], patch_data: dict[str, Any]) -> str:
    return str(
        patch_data.get("storefront_base_url")
        or property_data.get("storefront_base_url")
        or "https://cabin-rentals-of-georgia.com"
    ).rstrip("/")


def _resolve_canonical_url(property_data: dict[str, Any], patch_data: dict[str, Any]) -> str:
    explicit_url = _clean_text(patch_data.get("canonical_url"))
    if explicit_url:
        return explicit_url
    page_path = _clean_text(patch_data.get("page_path")) or f"/cabins/{_clean_text(property_data.get('slug')) or ''}"
    if page_path.startswith(("http://", "https://")):
        return page_path
    return _absolute_url(page_path, _resolve_storefront_base_url(property_data, patch_data))


def _resolve_images(property_data: dict[str, Any], patch_data: dict[str, Any]) -> list[str]:
    storefront_base_url = _resolve_storefront_base_url(property_data, patch_data)
    images: list[str] = []
    hero_image_url = _clean_text(
        property_data.get("hero_image_url")
        or patch_data.get("hero_image_url")
    )
    if hero_image_url:
        images.append(_absolute_url(hero_image_url, storefront_base_url))
    raw_images = property_data.get("images") or property_data.get("media") or []
    if isinstance(raw_images, list):
        for item in raw_images:
            raw_url: str | None
            if isinstance(item, dict):
                raw_url = _clean_text(item.get("url") or item.get("src") or item.get("image_url"))
            else:
                raw_url = _clean_text(item)
            if raw_url:
                absolute_url = _absolute_url(raw_url, storefront_base_url)
                if absolute_url not in images:
                    images.append(absolute_url)
    default_image_path = _clean_text(property_data.get("default_image_path"))
    if default_image_path:
        default_image_url = _absolute_url(default_image_path, storefront_base_url)
        if default_image_url not in images:
            images.insert(0, default_image_url)
    return images[:10]


def _extract_amenity_names(amenities_payload: Any) -> list[str]:
    if not isinstance(amenities_payload, list):
        return []
    seen: set[str] = set()
    amenity_names: list[str] = []
    for item in amenities_payload:
        if isinstance(item, dict):
            raw_name = item.get("amenity_name") or item.get("name") or item.get("label")
        else:
            raw_name = item
        name = _clean_text(raw_name)
        if not name:
            continue
        normalized = name.lower()
        if normalized in seen:
            continue
        seen.add(normalized)
        amenity_names.append(name)
        if len(amenity_names) >= MAX_SCHEMA_AMENITIES:
            break
    return amenity_names


def _resolve_pets_allowed(property_data: dict[str, Any]) -> bool | None:
    max_pets = _coerce_int(property_data.get("max_pets"))
    if max_pets is not None:
        return max_pets > 0
    amenities_payload = property_data.get("amenities")
    if not isinstance(amenities_payload, list):
        return None
    for item in amenities_payload:
        if isinstance(item, dict):
            raw_name = item.get("amenity_name") or item.get("name")
        else:
            raw_name = item
        name = str(raw_name or "").strip().lower()
        if name in {"pets allowed", "pet friendly", "dog friendly"}:
            return True
        if name in {"pets not allowed", "no pets"}:
            return False
    return None


def _build_postal_address(property_data: dict[str, Any]) -> PostalAddressSchema | None:
    street_address = _clean_text(property_data.get("address"))
    address_locality = _clean_text(property_data.get("city"))
    address_region = _clean_text(property_data.get("state"))
    postal_code = _clean_text(property_data.get("postal_code") or property_data.get("zip_code") or property_data.get("zip"))
    address_country = _clean_text(property_data.get("country") or property_data.get("country_name")) or "US"
    if not any([street_address, address_locality, address_region, postal_code]):
        return None
    return PostalAddressSchema(
        street_address=street_address,
        address_locality=address_locality,
        address_region=address_region,
        postal_code=postal_code,
        address_country=address_country,
    )


def _build_geo_coordinates(property_data: dict[str, Any]) -> GeoCoordinatesSchema | None:
    latitude = _coerce_float(property_data.get("latitude"))
    longitude = _coerce_float(property_data.get("longitude"))
    if latitude is None or longitude is None:
        return None
    return GeoCoordinatesSchema(latitude=latitude, longitude=longitude)


def _build_identifiers(property_data: dict[str, Any]) -> list[PropertyValueSchema]:
    identifiers: list[PropertyValueSchema] = []
    property_id = _clean_text(property_data.get("id"))
    if property_id:
        identifiers.append(PropertyValueSchema(property_id="fortress_property_id", value=property_id))
    streamline_property_id = _clean_text(property_data.get("streamline_property_id"))
    if streamline_property_id:
        identifiers.append(PropertyValueSchema(property_id="streamline_property_id", value=streamline_property_id))
    return identifiers


def _build_offer(property_data: dict[str, Any], patch_data: dict[str, Any]) -> OfferSchema | None:
    rate_card = property_data.get("rate_card")
    price = _coerce_float(
        property_data.get("nightly_rate")
        or property_data.get("base_rate")
        or property_data.get("price")
        or _find_first_scalar(rate_card, {"nightlyrate", "baserate", "nightlyprice", "price", "avgnightlyrate"})
    )
    price_currency = _clean_text(
        property_data.get("price_currency")
        or property_data.get("currency")
        or _find_first_scalar(rate_card, {"currency", "pricecurrency", "currencycode"})
    )
    max_guests = _coerce_int(property_data.get("max_guests"))
    availability: str | None = None
    is_active = property_data.get("is_active")
    if isinstance(is_active, bool):
        availability = "https://schema.org/InStock" if is_active else "https://schema.org/SoldOut"

    if price is None and price_currency is None and availability is None and max_guests is None:
        return None

    eligible_quantity = (
        QuantitativeValueSchema(value=max_guests, unit_text="guests")
        if max_guests is not None
        else None
    )
    return OfferSchema(
        url=_resolve_canonical_url(property_data, patch_data),
        availability=availability,
        price=price,
        price_currency=price_currency,
        eligible_quantity=eligible_quantity,
    )


def _build_aggregate_rating(property_data: dict[str, Any]) -> AggregateRatingSchema | None:
    aggregate_payload = property_data.get("aggregate_rating") if isinstance(property_data.get("aggregate_rating"), dict) else property_data
    rating_value = _coerce_float(
        aggregate_payload.get("rating_value")
        or aggregate_payload.get("ratingValue")
        or aggregate_payload.get("rating_average")
        or aggregate_payload.get("average_rating")
        or aggregate_payload.get("overall_rating")
    )
    review_count = _coerce_int(
        aggregate_payload.get("review_count")
        or aggregate_payload.get("reviewCount")
        or aggregate_payload.get("rating_count")
    )
    if rating_value is None or review_count is None or rating_value <= 0 or review_count <= 0:
        return None
    return AggregateRatingSchema(rating_value=rating_value, review_count=review_count)


def _build_base_payload(property_data: dict[str, Any], patch_data: dict[str, Any]) -> dict[str, Any]:
    property_name = _clean_text(property_data.get("name")) or "Fortress Prime Cabin"
    description = _clean_text(
        patch_data.get("meta_description")
        or patch_data.get("og_description")
        or patch_data.get("intro")
        or property_data.get("description")
        or property_name
    ) or property_name
    return {
        "name": property_name,
        "description": description,
        "url": _resolve_canonical_url(property_data, patch_data),
        "image": _resolve_images(property_data, patch_data),
        "identifier": _build_identifiers(property_data),
        "address": _build_postal_address(property_data),
        "geo": _build_geo_coordinates(property_data),
        "number_of_rooms": _coerce_int(property_data.get("bedrooms")),
        "number_of_bedrooms": _coerce_int(property_data.get("bedrooms")),
        "number_of_bathrooms_total": _coerce_float(property_data.get("bathrooms")),
        "maximum_attendee_capacity": _coerce_int(property_data.get("max_guests")),
        "pets_allowed": _resolve_pets_allowed(property_data),
        "amenity_feature": [
            LocationFeatureSpecificationSchema(name=name, value=True)
            for name in _extract_amenity_names(property_data.get("amenities"))
        ],
        "offers": _build_offer(property_data, patch_data),
        "aggregate_rating": _build_aggregate_rating(property_data),
    }


def build_vacation_rental_jsonld(property_data: dict[str, Any], patch_data: dict[str, Any]) -> dict[str, Any]:
    payload = VacationRentalSchema(**_build_base_payload(property_data, patch_data))
    return _prune_empty(payload.model_dump(by_alias=True, exclude_none=True))


def build_lodging_business_jsonld(property_data: dict[str, Any], patch_data: dict[str, Any]) -> dict[str, Any]:
    base_payload = _build_base_payload(property_data, patch_data)
    lodging_payload = {
        key: value
        for key, value in base_payload.items()
        if key not in {"number_of_bedrooms", "pets_allowed"}
    }
    payload = LodgingBusinessSchema(**lodging_payload)
    return _prune_empty(payload.model_dump(by_alias=True, exclude_none=True))


def build_property_jsonld(property_data: dict[str, Any], patch_data: dict[str, Any]) -> dict[str, Any]:
    property_type = str(property_data.get("property_type") or "").strip().lower()
    if property_type in VACATION_RENTAL_TYPES:
        return build_vacation_rental_jsonld(property_data, patch_data)
    return build_lodging_business_jsonld(property_data, patch_data)


__all__ = [
    "build_property_jsonld",
    "build_lodging_business_jsonld",
    "build_vacation_rental_jsonld",
]
