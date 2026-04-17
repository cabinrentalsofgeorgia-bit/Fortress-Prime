from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field
from sqlalchemy import func, or_, select
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from backend.core.database import get_db
from backend.models.content import MarketingArticle, TaxonomyCategory
from backend.models.guest import Guest
from backend.models.guest_review import GuestReview
from backend.models.guestbook import GuestbookGuide
from backend.models.knowledge import KnowledgeBaseEntry
from backend.models.property import Property

router = APIRouter()


def _iso(value: datetime | None) -> str | None:
    return value.isoformat() if value else None


def _money_to_float(value: Any) -> float | None:
    if value is None:
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _extract_today_rate(rate_card: Any) -> float | None:
    if not isinstance(rate_card, dict):
        return None

    for key in ("today_rate", "nightly_rate", "nightly"):
        if rate_card.get(key) is not None:
            return _money_to_float(rate_card[key])

    today_str = date.today().isoformat()
    rates = rate_card.get("rates")
    if isinstance(rates, list):
        for entry in rates:
            if not isinstance(entry, dict):
                continue
            if entry.get("start_date") == today_str:
                val = entry.get("nightly") or entry.get("nightly_rate") or entry.get("rate")
                if val is not None:
                    return _money_to_float(val)
        for entry in rates:
            if not isinstance(entry, dict):
                continue
            val = entry.get("nightly") or entry.get("nightly_rate") or entry.get("rate")
            if val is not None:
                return _money_to_float(val)
    return None


def _normalize_amenities(amenities: Any) -> list[dict[str, str]]:
    """Return the website-visible amenity list with humanised, deduplicated names."""
    from backend.services.amenity_mapper import humanise_amenity

    if not amenities:
        return []

    seen: set[str] = set()
    normalized: list[dict[str, str]] = []

    def _add(raw_name: str) -> None:
        human = humanise_amenity(raw_name)
        key = human.lower()
        if key not in seen:
            seen.add(key)
            normalized.append({"name": human})

    if isinstance(amenities, list):
        for amenity in amenities:
            if isinstance(amenity, str) and amenity.strip():
                _add(amenity.strip())
            elif isinstance(amenity, dict):
                show = str(amenity.get("amenity_show_on_website") or "").lower()
                if show != "yes":
                    continue
                name = str(
                    amenity.get("amenity_name")
                    or amenity.get("name")
                    or amenity.get("group_name")
                    or amenity.get("label")
                    or ""
                ).strip()
                if name:
                    _add(name)
    elif isinstance(amenities, dict):
        for key, value in amenities.items():
            if value:
                _add(str(key).strip())

    return normalized


def _serialize_images(prop: Property) -> tuple[str | None, str | None, str | None, list[dict[str, Any]]]:
    ordered_images = sorted(
        list(prop.images or []),
        key=lambda image: (
            0 if getattr(image, "is_hero", False) else 1,
            getattr(image, "display_order", 0),
        ),
    )
    gallery_images: list[dict[str, Any]] = []
    for image in ordered_images:
        url = image.sovereign_url or image.legacy_url
        if not url:
            continue
        gallery_images.append(
            {
                "url": url,
                "legacy_url": image.legacy_url,
                "sovereign_url": image.sovereign_url,
                "title": image.alt_text or "",
                "alt": image.alt_text or "",
            }
        )

    featured = gallery_images[0] if gallery_images else None
    return (
        featured["url"] if featured else None,
        featured["alt"] if featured else None,
        featured["title"] if featured else None,
        gallery_images,
    )


_TAXONOMY_DESCRIPTIONS: dict[str, str] = {
    "blue-ridge-cabins": "<p>Browse our complete collection of luxury cabin rentals in Blue Ridge, GA. From cozy 2-bedrooms to spacious 5-bedroom lodges, find your perfect mountain getaway with hot tubs, game rooms, river access, and stunning mountain views.</p>",
    "blue-ridge-experience": "<p>Discover the best of Blue Ridge, Georgia. From hiking and fishing to shopping and dining, explore the activities and attractions that make the North Georgia mountains a premier vacation destination.</p>",
    "blue-ridge-memories": "<p>Read what our guests are saying about their stays at Cabin Rentals of Georgia. Real reviews from real families who have experienced our luxury Blue Ridge cabin rentals.</p>",
    "mountain-view": "<p>Wake up to breathtaking mountain vistas. Our mountain view cabins offer panoramic views of the Blue Ridge Mountains from private decks, hot tubs, and floor-to-ceiling windows.</p>",
    "pet-friendly": "<p>Bring your furry family members along! Our pet-friendly cabins welcome well-behaved pets so the whole family can enjoy a Blue Ridge mountain getaway together.</p>",
    "river-front": "<p>Listen to the sounds of rushing water from your private deck. Our riverfront and creekside cabins offer direct access to the Toccoa River and mountain streams.</p>",
    "river-view": "<p>Enjoy stunning river views from the comfort of your cabin. Our river view properties overlook the Toccoa River and its tributaries in the North Georgia mountains.</p>",
    "lake-view": "<p>Relax with views of Lake Blue Ridge. Our lake view cabins provide easy access to boating, fishing, and swimming on one of North Georgia's most beautiful mountain lakes.</p>",
    "family-reunion": "<p>Plan your next family reunion in the Blue Ridge mountains. Our spacious cabins accommodate large groups with multiple bedrooms, game rooms, and outdoor entertainment areas.</p>",
    "blue-ridge-luxury": "<p>Experience the finest in Blue Ridge luxury cabin living. Premium amenities, designer furnishings, and exceptional mountain settings define our luxury collection.</p>",
    "corporate-retreats": "<p>Host your next corporate retreat in the serene Blue Ridge mountains. Our large cabins offer the perfect blend of meeting space, team-building activities, and relaxation.</p>",
    "cabin-in-the-woods": "<p>Escape to seclusion in our cabins nestled deep in the North Georgia woods. These private retreats offer peace, quiet, and a true connection with nature.</p>",
}


_ACTIVITY_TYPE_TIDS: dict[str, int] = {
    "arts-entertainment": 1001,
    "attractions": 1002,
    "bicycling": 1003,
    "boating": 1004,
    "breweries": 1005,
    "concierge": 1006,
    "day-trips": 1007,
    "family-fun": 1008,
    "farmers-markets": 1009,
    "festivals-events": 1010,
    "fishing": 1011,
    "golf": 1012,
    "group-activities": 1013,
    "hiking": 1014,
    "hiking-picnics": 1015,
    "horseback-riding": 1016,
    "mountain-biking": 1017,
    "orchards": 1018,
    "restaurants": 1019,
    "scenic-drives": 1020,
    "seasonal-activities": 1021,
    "shopping": 1022,
    "spas-wellness": 1023,
    "trip-itineraries": 1024,
    "tubing-kayaking": 1025,
    "waterfalls": 1026,
    "whitewater-rafting": 1027,
    "wineries-vineyards": 1028,
    "zip-lining": 1029,
}

_ACTIVITY_TYPE_DESCRIPTIONS: dict[str, str] = {
    "fishing": "<p>Cast a line in the pristine waters of North Georgia. From fly fishing on the Toccoa River to lake fishing on Blue Ridge Lake, discover the best fishing spots near our luxury cabin rentals.</p>",
    "hiking": "<p>Explore miles of scenic trails through the Blue Ridge Mountains. From easy nature walks to challenging summit hikes, discover the best hiking near Blue Ridge, GA.</p>",
    "hiking-picnics": "<p>Combine a scenic hike with a perfect picnic in the North Georgia mountains. Discover trails with stunning overlooks ideal for a relaxing outdoor meal.</p>",
    "waterfalls": "<p>Discover the stunning waterfalls of North Georgia. From Amicalola Falls to hidden cascades, explore the most beautiful waterfall hikes near Blue Ridge.</p>",
    "whitewater-rafting": "<p>Experience the thrill of whitewater rafting on the Ocoee River and other North Georgia waterways. Adventures for beginners and experts alike.</p>",
    "restaurants": "<p>Savor the flavors of Blue Ridge, GA. From farm-to-table dining to Southern comfort food, explore the best restaurants near our luxury cabin rentals.</p>",
    "shopping": "<p>Browse the charming shops of downtown Blue Ridge. From antique stores to artisan boutiques, discover unique finds in the North Georgia mountains.</p>",
    "attractions": "<p>Explore the top attractions near Blue Ridge, GA. From the Blue Ridge Scenic Railway to local museums, there's something for everyone.</p>",
    "wineries-vineyards": "<p>Tour the vineyards and wineries of North Georgia wine country. Sample award-winning wines just minutes from our luxury cabin rentals.</p>",
    "breweries": "<p>Discover the craft beer scene in Blue Ridge, GA. Visit local breweries and taprooms for unique brews in the North Georgia mountains.</p>",
    "arts-entertainment": "<p>Experience the vibrant arts and entertainment scene in Blue Ridge. From live theatre to galleries and music venues, creativity thrives in the mountains.</p>",
    "family-fun": "<p>Create unforgettable family memories in Blue Ridge, GA. From mini golf to gem mining, discover activities the whole family will love.</p>",
    "festivals-events": "<p>Join the celebration at Blue Ridge's festivals and events. From the Apple Festival to Arts in the Park, there's always something happening.</p>",
    "day-trips": "<p>Venture beyond Blue Ridge on exciting day trips. Explore nearby towns, state parks, and hidden gems throughout the North Georgia mountains.</p>",
    "golf": "<p>Tee off on championship courses surrounded by mountain scenery. The North Georgia mountains offer some of the most scenic golf in the Southeast.</p>",
    "horseback-riding": "<p>Saddle up for a horseback riding adventure through the Blue Ridge Mountains. Guided trail rides offer stunning mountain views.</p>",
    "mountain-biking": "<p>Hit the trails on two wheels. The Blue Ridge mountains offer world-class mountain biking from beginner-friendly paths to expert single-track.</p>",
    "tubing-kayaking": "<p>Float down the Toccoa River or kayak on Lake Blue Ridge. Water adventures await just minutes from our luxury cabin rentals.</p>",
    "zip-lining": "<p>Soar through the treetops on a zip line adventure in the North Georgia mountains. An unforgettable experience for thrill-seekers.</p>",
    "orchards": "<p>Pick your own apples, peaches, and berries at North Georgia's beloved orchards. A must-do activity during every season in Blue Ridge.</p>",
    "scenic-drives": "<p>Wind through the Blue Ridge Mountains on some of the most scenic drives in the Southeast. Fall foliage and mountain vistas await.</p>",
    "concierge": "<p>Let our concierge team plan the perfect Blue Ridge experience. From private chefs to guided adventures, we'll handle every detail.</p>",
    "seasonal-activities": "<p>Discover what's happening in Blue Ridge this season. From spring wildflowers to winter wonderlands, every season brings new adventures.</p>",
    "spas-wellness": "<p>Relax and rejuvenate at spas and wellness centers near Blue Ridge. Treat yourself to massages, facials, and mountain tranquility.</p>",
    "trip-itineraries": "<p>Plan your perfect Blue Ridge getaway with our curated trip itineraries. From romantic weekends to family adventures, we've mapped it all out.</p>",
    "farmers-markets": "<p>Shop fresh and local at North Georgia's farmers markets. Find seasonal produce, artisan goods, and homemade treats.</p>",
    "boating": "<p>Take to the water on Lake Blue Ridge. Rent a pontoon, kayak, or paddleboard and enjoy a day on one of North Georgia's most beautiful lakes.</p>",
    "bicycling": "<p>Pedal through the scenic countryside around Blue Ridge. From paved paths to gravel roads, cycling is a great way to explore North Georgia.</p>",
    "group-activities": "<p>Planning a group outing in Blue Ridge? Discover activities perfect for family reunions, corporate retreats, and large gatherings.</p>",
}


def _fallback_term_from_slug(slug: str, vid: int | None) -> "StorefrontTaxonomyTerm":
    humanized = slug.replace("-", " ").strip().title() or "Storefront"

    # Activity vocabulary (vid=10): return deterministic tid so the
    # activities API can filter by activity_type_tid.
    if vid == 10 and slug.lower() in _ACTIVITY_TYPE_TIDS:
        description = _ACTIVITY_TYPE_DESCRIPTIONS.get(slug.lower()) or _TAXONOMY_DESCRIPTIONS.get(slug.lower())
        return StorefrontTaxonomyTerm(
            tid=_ACTIVITY_TYPE_TIDS[slug.lower()],
            vid=10,
            name=humanized,
            description=description,
            page_title=humanized,
        )

    description = _TAXONOMY_DESCRIPTIONS.get(slug.lower())
    return StorefrontTaxonomyTerm(
        tid=0,
        vid=vid or 0,
        name=humanized,
        description=description,
        page_title=humanized,
    )


class StorefrontReview(BaseModel):
    title: str
    body: str


class StorefrontProperty(BaseModel):
    id: str
    title: str
    cabin_slug: str
    body: str | None = None
    bedrooms: str | None = None
    bathrooms: float | None = None
    sleeps: int | None = None
    property_type: list[dict[str, str]] | None = None
    amenities: list[dict[str, str]] | None = None
    amenity_matrix: dict[str, list[str]] | None = None
    features: list[str] | None = None
    featured_image_url: str | None = None
    featured_image_alt: str | None = None
    featured_image_title: str | None = None
    gallery_images: list[dict[str, Any]] | None = None
    latitude: float | None = None
    longitude: float | None = None
    streamline_id: str | None = None
    phone: str | None = None
    matterport_url: str | None = None
    tagline: str | None = None
    location: str | None = None
    rates_description: str | None = None
    analytics_code: str | None = None
    video: list[dict[str, Any]] | None = None
    address: dict[str, Any] | None = None
    author_name: str | None = None
    status: str
    created_at: str | None = None
    updated_at: str | None = None
    published_at: str | None = None
    today_rate: float | None = None
    reviews: list[StorefrontReview] | None = None


class StorefrontPropertiesResponse(BaseModel):
    properties: list[StorefrontProperty] = Field(default_factory=list)


class StorefrontTaxonomyTerm(BaseModel):
    tid: int
    vid: int
    name: str
    description: str | None = None
    format: str | None = "full_html"
    weight: int = 0
    page_title: str | None = None
    video_url: str | None = None


class StorefrontActivity(BaseModel):
    id: str
    title: str
    slug: str
    activity_slug: str | None = None
    body: str | None = None
    body_summary: str | None = None
    address: str | None = None
    activity_type: str | None = None
    activity_type_tid: int | None = None
    area: str | None = None
    area_tid: int | None = None
    people: str | None = None
    people_tid: int | None = None
    difficulty_level: str | None = None
    difficulty_level_tid: int | None = None
    season: str | None = None
    season_tid: int | None = None
    featured_image_url: str | None = None
    featured_image_alt: str | None = None
    featured_image_title: str | None = None
    video_urls: list[str] | None = None
    latitude: float | None = None
    longitude: float | None = None
    status: str = "published"
    is_featured: bool = False
    display_order: int = 0
    drupal_nid: int | None = None
    drupal_vid: int | None = None
    created_at: str | None = None
    updated_at: str | None = None
    published_at: str | None = None


class StorefrontCustomerImage(BaseModel):
    url: str
    title: str | None = None
    width: int | None = None
    height: int | None = None


class StorefrontTestimonial(BaseModel):
    id: str
    title: str | None = None
    body: str | None = None
    cabin_name: str | None = None
    cabin_slug: str | None = None
    customer_image: StorefrontCustomerImage | None = None
    author_name: str | None = None
    status: str
    is_featured: bool = False
    is_sticky: bool = False
    display_order: int = 0
    created_at: str | None = None
    updated_at: str | None = None
    published_at: str | None = None


class StorefrontTestimonialListResponse(BaseModel):
    testimonials: list[StorefrontTestimonial] = Field(default_factory=list)
    total: int
    page: int
    page_size: int
    total_pages: int


class StorefrontFAQ(BaseModel):
    id: str
    question: str
    answer: str
    slug: str
    category: str | None = None
    tags: list[str] | None = None
    display_order: int = 0
    status: str = "published"
    is_featured: bool = False
    created_at: str | None = None
    updated_at: str | None = None
    published_at: str | None = None
    meta_title: str | None = None
    meta_description: str | None = None


class StorefrontFAQListResponse(BaseModel):
    faqs: list[StorefrontFAQ] = Field(default_factory=list)
    total: int
    page: int
    page_size: int
    total_pages: int


def _extract_description(prop: Property) -> str | None:
    meta = prop.ota_metadata
    if isinstance(meta, dict):
        legacy = meta.get("legacy_body")
        if legacy and isinstance(legacy, str) and len(legacy.strip()) > 50:
            return legacy.strip()
        desc = meta.get("description")
        if desc and isinstance(desc, str) and len(desc.strip()) > 10:
            return desc.strip()
    return None


def _extract_features(prop: Property) -> list[str] | None:
    meta = prop.ota_metadata
    if isinstance(meta, dict):
        feats = meta.get("legacy_features")
        if feats and isinstance(feats, list) and len(feats) > 0:
            return feats
    return None


def _extract_reviews(prop: Property) -> list[dict[str, str]] | None:
    meta = prop.ota_metadata
    if isinstance(meta, dict):
        reviews = meta.get("legacy_reviews")
        if reviews and isinstance(reviews, list) and len(reviews) > 0:
            return reviews
    return None


def _extract_rates_description(prop: Property) -> str | None:
    if prop.rates_notes and isinstance(prop.rates_notes, str) and len(prop.rates_notes.strip()) > 5:
        return prop.rates_notes.strip()
    meta = prop.ota_metadata
    if isinstance(meta, dict):
        for key in ("rates_description", "rates_notes", "rate_notes"):
            val = meta.get(key)
            if val and isinstance(val, str) and len(val.strip()) > 5:
                return val.strip()
    return None


def _extract_video(prop: Property) -> list[dict[str, Any]] | None:
    if prop.video_urls and isinstance(prop.video_urls, list) and len(prop.video_urls) > 0:
        return [
            {"video_url": v.get("url") or v.get("video_url") or v, "description": v.get("description", "")}
            if isinstance(v, dict) else {"video_url": v, "description": ""}
            for v in prop.video_urls
        ]
    meta = prop.ota_metadata
    if isinstance(meta, dict):
        for key in ("video", "videos", "video_urls"):
            val = meta.get(key)
            if val and isinstance(val, list) and len(val) > 0:
                return [
                    {"video_url": v.get("url") or v.get("video_url") or v, "description": v.get("description", "")}
                    if isinstance(v, dict) else {"video_url": v, "description": ""}
                    for v in val
                ]
    return None


def _serialize_property(prop: Property) -> StorefrontProperty:
    from backend.services.amenity_mapper import build_amenity_matrix

    featured_image_url, featured_image_alt, featured_image_title, gallery_images = _serialize_images(prop)
    amenities = _normalize_amenities(prop.amenities)
    matrix = build_amenity_matrix(prop.amenities) or None
    return StorefrontProperty(
        id=str(prop.id),
        title=prop.name,
        cabin_slug=prop.slug,
        body=_extract_description(prop),
        bedrooms=str(prop.bedrooms) if prop.bedrooms is not None else None,
        bathrooms=float(prop.bathrooms) if prop.bathrooms is not None else None,
        sleeps=prop.max_guests,
        property_type=[{"name": prop.property_type}] if prop.property_type else None,
        amenities=amenities or None,
        amenity_matrix=matrix,
        features=_extract_features(prop),
        featured_image_url=featured_image_url,
        featured_image_alt=featured_image_alt,
        featured_image_title=featured_image_title,
        gallery_images=gallery_images,
        latitude=float(prop.latitude) if prop.latitude is not None else None,
        longitude=float(prop.longitude) if prop.longitude is not None else None,
        streamline_id=prop.streamline_property_id,
        phone=None,
        matterport_url=None,
        tagline=None,
        location=None,
        rates_description=_extract_rates_description(prop),
        analytics_code=None,
        video=_extract_video(prop),
        address={"address1": prop.address} if prop.address else None,
        author_name=None,
        status="published" if prop.is_active else "archived",
        created_at=_iso(prop.created_at),
        updated_at=_iso(prop.updated_at),
        published_at=_iso(prop.created_at if prop.is_active else None),
        today_rate=_extract_today_rate(prop.rate_card),
        reviews=_extract_reviews(prop),
    )


@router.get("/cabins", response_model=StorefrontPropertiesResponse)
async def list_storefront_cabins(
    category: str | None = Query(default=None),
    amenity: str | None = Query(default=None),
    bedrooms: int | None = Query(default=None),
    status: str | None = Query(default=None),
    tid: int | None = Query(default=None),
    search: str | None = Query(default=None),
    db: AsyncSession = Depends(get_db),
) -> StorefrontPropertiesResponse:
    query = (
        select(Property)
        .where(Property.is_active.is_(True))
        .options(selectinload(Property.images))
    )

    if category:
        from sqlalchemy import Text, cast as sa_cast

        _CATEGORY_SEARCH_MAP: dict[str, list[str]] = {
            "river-front": ["river", "waterfront", "river access"],
            "river-view": ["river", "river view"],
            "family-reunion": ["family"],
            "blue-ridge-luxury": ["luxury"],
            "corporate-retreats": ["family", "luxury"],
            "cabin-in-the-woods": ["mountain", "secluded"],
            "toccoa-river-luxury-cabin-rentals": ["toccoa river", "river access"],
        }

        search_terms = _CATEGORY_SEARCH_MAP.get(category.lower())
        if search_terms:
            conditions = [sa_cast(Property.amenities, Text).ilike(f"%{term}%") for term in search_terms]
            query = query.where(or_(*conditions))
        else:
            normalized = category.lower().replace("-", " ").replace("_", " ")
            query = query.where(sa_cast(Property.amenities, Text).ilike(f"%{normalized}%"))

    if bedrooms is not None:
        query = query.where(Property.bedrooms == bedrooms)

    if amenity:
        from sqlalchemy import Text, cast as sa_cast
        normalized_amenity = amenity.lower().replace("-", " ")
        query = query.where(sa_cast(Property.amenities, Text).ilike(f"%{normalized_amenity}%"))

    if search:
        like = f"%{search.strip()}%"
        query = query.where(or_(Property.name.ilike(like), Property.slug.ilike(like)))

    query = query.order_by(Property.name.asc())
    result = await db.execute(query)
    properties = result.scalars().unique().all()
    return StorefrontPropertiesResponse(properties=[_serialize_property(p) for p in properties])


@router.get("/cabins/{cabin_id:path}", response_model=StorefrontProperty)
async def get_storefront_cabin(cabin_id: str, db: AsyncSession = Depends(get_db)) -> StorefrontProperty:
    from uuid import UUID as _UUID

    candidates = [cabin_id]
    last_segment = cabin_id.rsplit("/", 1)[-1] if "/" in cabin_id else None
    if last_segment and last_segment != cabin_id:
        candidates.append(last_segment)

    filters = []
    for candidate in candidates:
        try:
            filters.append(Property.id == _UUID(candidate))
        except ValueError:
            pass
        filters.append(Property.slug == candidate)
        filters.append(Property.streamline_property_id == candidate)

    result = await db.execute(
        select(Property)
        .where(or_(*filters))
        .options(selectinload(Property.images))
        .limit(1)
    )
    prop = result.scalars().first()
    if prop is None:
        raise HTTPException(status_code=404, detail="Cabin not found")
    return _serialize_property(prop)


@router.get("/taxonomy", response_model=StorefrontTaxonomyTerm)
async def get_storefront_taxonomy_term(
    slug: str = Query(..., min_length=1),
    vid: int | None = Query(default=None),
    category: str | None = Query(default=None),
    db: AsyncSession = Depends(get_db),
) -> StorefrontTaxonomyTerm:
    try:
        category = (
            await db.execute(select(TaxonomyCategory).where(TaxonomyCategory.slug == slug))
        ).scalar_one_or_none()
        if category is not None:
            return StorefrontTaxonomyTerm(
                tid=0,
                vid=vid or 0,
                name=category.name,
                description=category.description,
                page_title=category.meta_title,
            )

        article = (
            await db.execute(select(MarketingArticle).where(MarketingArticle.slug == slug))
        ).scalar_one_or_none()
        if article is not None:
            return StorefrontTaxonomyTerm(
                tid=0,
                vid=vid or 0,
                name=article.title,
                description=article.content_body_html,
                page_title=article.title,
            )
    except SQLAlchemyError:
        pass

    return _fallback_term_from_slug(slug, vid)


@router.get("/activities", response_model=list[StorefrontActivity])
async def list_storefront_activities(db: AsyncSession = Depends(get_db)) -> list[StorefrontActivity]:
    result = await db.execute(
        select(GuestbookGuide)
        .where(GuestbookGuide.is_visible.is_(True))
        .where(or_(GuestbookGuide.guide_type == "activity", GuestbookGuide.guide_type == "area_guide"))
        .order_by(GuestbookGuide.display_order.asc(), GuestbookGuide.title.asc())
    )
    guides = result.scalars().all()

    return [
        StorefrontActivity(
            id=str(guide.id),
            title=guide.title,
            slug=guide.slug,
            activity_slug=guide.slug,
            body=guide.content,
            body_summary=None,
            address=None,
            activity_type=guide.category or guide.guide_type,
            featured_image_url=None,
            featured_image_alt=None,
            featured_image_title=guide.title,
            video_urls=None,
            status="published" if guide.is_visible else "draft",
            is_featured=False,
            display_order=guide.display_order or 0,
            created_at=_iso(guide.created_at),
            updated_at=_iso(guide.updated_at),
            published_at=_iso(guide.created_at if guide.is_visible else None),
        )
        for guide in guides
    ]


@router.get("/testimonials", response_model=StorefrontTestimonialListResponse)
async def list_storefront_testimonials(
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=20, ge=1, le=200),
    status: str | None = Query(default=None),
    featured: bool | None = Query(default=None),
    cabin_name: str | None = Query(default=None),
    search: str | None = Query(default=None),
    db: AsyncSession = Depends(get_db),
) -> StorefrontTestimonialListResponse:
    filters = [GuestReview.direction == "guest_to_property"]
    if status == "published":
        filters.append(GuestReview.is_published.is_(True))
    elif status == "draft":
        filters.append(GuestReview.is_published.is_(False))

    if featured is True:
        filters.append(GuestReview.overall_rating >= 4)

    if search:
        like = f"%{search.strip()}%"
        filters.append(or_(GuestReview.title.ilike(like), GuestReview.body.ilike(like)))

    if cabin_name:
        filters.append(Property.name.ilike(f"%{cabin_name.strip()}%"))

    total = await db.scalar(
        select(func.count())
        .select_from(GuestReview)
        .join(Property, GuestReview.property_id == Property.id)
        .where(*filters)
    )

    result = await db.execute(
        select(GuestReview, Guest, Property)
        .join(Guest, GuestReview.guest_id == Guest.id)
        .join(Property, GuestReview.property_id == Property.id)
        .where(*filters)
        .order_by(GuestReview.published_at.desc().nullslast(), GuestReview.created_at.desc())
        .offset((page - 1) * page_size)
        .limit(page_size)
    )
    rows = result.all()

    testimonials = [
        StorefrontTestimonial(
            id=str(review.id),
            title=review.title,
            body=review.body,
            cabin_name=prop.name,
            cabin_slug=prop.slug,
            customer_image=None,
            author_name=guest.full_name,
            status="published" if review.is_published else "draft",
            is_featured=review.overall_rating >= 4,
            is_sticky=False,
            display_order=0,
            created_at=_iso(review.created_at),
            updated_at=_iso(review.updated_at),
            published_at=_iso(review.published_at),
        )
        for review, guest, prop in rows
    ]

    total_items = int(total or 0)
    total_pages = (total_items + page_size - 1) // page_size if total_items else 0
    return StorefrontTestimonialListResponse(
        testimonials=testimonials,
        total=total_items,
        page=page,
        page_size=page_size,
        total_pages=total_pages,
    )


@router.get("/faqs", response_model=StorefrontFAQListResponse)
async def list_storefront_faqs(
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=20, ge=1, le=200),
    status: str | None = Query(default=None),
    featured: bool | None = Query(default=None),
    category: str | None = Query(default=None),
    search: str | None = Query(default=None),
    db: AsyncSession = Depends(get_db),
) -> StorefrontFAQListResponse:
    filters = [KnowledgeBaseEntry.category == "faq"]
    if status == "published":
        filters.append(KnowledgeBaseEntry.is_active.is_(True))
    elif status == "draft":
        filters.append(KnowledgeBaseEntry.is_active.is_(False))

    if category:
        filters.append(KnowledgeBaseEntry.category == category)

    if search:
        like = f"%{search.strip()}%"
        filters.append(or_(KnowledgeBaseEntry.question.ilike(like), KnowledgeBaseEntry.answer.ilike(like)))

    total = await db.scalar(
        select(func.count()).select_from(KnowledgeBaseEntry).where(*filters)
    )
    result = await db.execute(
        select(KnowledgeBaseEntry)
        .where(*filters)
        .order_by(KnowledgeBaseEntry.created_at.desc())
        .offset((page - 1) * page_size)
        .limit(page_size)
    )
    entries = result.scalars().all()

    faqs = [
        StorefrontFAQ(
            id=str(entry.id),
            question=entry.question or "",
            answer=entry.answer,
            slug=str(entry.id),
            category=entry.category,
            tags=entry.keywords,
            display_order=0,
            status="published" if entry.is_active else "draft",
            is_featured=bool(featured and False),
            created_at=_iso(entry.created_at),
            updated_at=_iso(entry.updated_at),
            published_at=_iso(entry.created_at if entry.is_active else None),
            meta_title=None,
            meta_description=None,
        )
        for entry in entries
    ]

    total_items = int(total or 0)
    total_pages = (total_items + page_size - 1) // page_size if total_items else 0
    return StorefrontFAQListResponse(
        faqs=faqs,
        total=total_items,
        page=page,
        page_size=page_size,
        total_pages=total_pages,
    )
