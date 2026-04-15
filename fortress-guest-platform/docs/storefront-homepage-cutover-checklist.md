# Storefront Homepage Cutover Checklist

This document turns the homepage drift audit into an execution checklist for
replacing the current proxy-backed Drupal front door with a trustworthy Next.js
homepage.

The current public `/` route should remain proxied to Drupal until every
critical section below is either rebuilt from live data or intentionally
deferred.

## Current State

Today the in-repo homepage implementation is a hybrid:

- route entry: `apps/storefront/src/app/page.tsx`
- actual page: `apps/storefront/src/app/(storefront)/page.tsx`
- root shell: `apps/storefront/src/app/layout.tsx`
- archived source snapshot:
  `apps/storefront/src/data/legacy/legacy-home-20180820.html`

The current Next homepage:

- injects slices of a frozen 2018 Drupal HTML file
- strips scripts from that archive
- swaps the original Drupal search form for `HomepageBookingWidget`
- fetches live property data, but does not rebuild the rest of the homepage
  from live structured content

## Release Rule

Do not remove the `/` proxy until all items marked `required for cutover` are
complete and validated.

## Section Strategy Matrix

| Section | Current status | Strategy | Required for cutover |
| --- | --- | --- | --- |
| Root metadata / SEO | wrong | rebuild from live data | yes |
| Global shell / theme | wrong | rebuild | yes |
| Header navigation | approximated | rebuild from live data | yes |
| Hero / banner | approximated | rebuild from live data | yes |
| Search / booking form | replaced | validate or rebuild intentionally | yes |
| Featured cabins | stale | rebuild from live data | yes |
| Category / revenue links | stale | rebuild from structured config | yes |
| Promo / CTA blocks | stale or missing | rebuild only current promos | yes |
| Reviews / testimonials | stale | rebuild from live data | no |
| Footer / social links | stale | rebuild from live data | yes |
| Archived homepage HTML snapshot | active dependency | delete after parity | yes |

## Checklist

### 1. Metadata And Branding

- [ ] Replace homepage metadata derived from `apps/storefront/src/app/layout.tsx`
      with CROG-specific metadata at the homepage route level.
- [ ] Use the live CROG title, description, canonical URL, and Open Graph fields.
- [ ] Remove `Fortress Guest Platform` branding from the public homepage path.
- [ ] Verify the homepage does not inherit the dark slate shell styling.

Definition of done:

- `view-source:` for the Next homepage matches CROG branding and SEO intent.

### 2. Header Navigation

- [ ] Identify the long-term source of truth for homepage nav:
      Drupal API, backend JSON, or app-managed config.
- [ ] Rebuild the primary nav from structured data instead of archived HTML.
- [ ] Rebuild the secondary nav from structured data instead of archived HTML.
- [ ] Confirm phone number and utility links match the live site.

Definition of done:

- Header labels and destinations match the live Drupal homepage.

### 3. Hero And Banner

- [ ] Replace archived hero markup injection with a real React section.
- [ ] Source hero slides, copy, CTAs, and images from live structured content.
- [ ] Remove the inline CSS hack that only shows the first banner slide.
- [ ] Decide whether the carousel returns or whether a static hero is the new
      approved product design.

Definition of done:

- The hero is not sourced from `legacy-home-20180820.html`.

### 4. Search And Booking

- [ ] Decide whether `HomepageBookingWidget` is the long-term homepage search.
- [ ] If yes, map every field and CTA against the legacy Drupal form behavior.
- [ ] Preserve or intentionally replace the `Master Calendar` and property
      management CTAs.
- [ ] Verify quote flow, availability flow, and booking continuation path
      against live backend behavior.
- [ ] Remove any disabled or placeholder interaction states before cutover.

Definition of done:

- Homepage search behavior is intentionally equivalent or intentionally improved,
  with working end-to-end booking entry points.

### 5. Featured Cabins

- [ ] Define the source of truth for featured properties.
- [ ] Rebuild the featured cabin section from structured live data.
- [ ] Preserve live cabin attributes that matter for merchandising:
      bedrooms, sleeps, nightly starting price, image, and link target.
- [ ] Confirm merchandising can be changed without editing archived HTML.

Definition of done:

- Featured listings are live, current, and merchandisable.

### 6. Category And Revenue Links

- [ ] Inventory all live homepage category links:
      family reunion, mountain view, lake view, pet friendly, and others.
- [ ] Move those links into structured config or CMS-fed data.
- [ ] Validate every destination against the current proxy strategy and future
      Next routing plan.
- [ ] Remove outdated category labels from the archived homepage implementation.

Definition of done:

- Revenue-driving category links are current and intentionally managed.

### 7. Promo And CTA Blocks

- [ ] Inventory active homepage promos on the live Drupal site.
- [ ] Remove stale archived promos that are no longer current.
- [ ] Rebuild only currently approved promos in React.
- [ ] Confirm ownership for marketing updates after cutover.

Definition of done:

- No homepage promo depends on the archived 2018 HTML snapshot.

### 8. Reviews And Social Proof

- [ ] Decide whether reviews belong on the homepage cutover path or a later
      phase.
- [ ] If needed for cutover, rebuild from live review data or curated records.
- [ ] If not needed for cutover, explicitly defer and keep proxied homepage live
      until omission is approved.

Definition of done:

- Review content is either intentionally rebuilt or explicitly omitted.

### 9. Footer And Social Links

- [ ] Rebuild footer navigation and social links from live structured data.
- [ ] Verify owner login, privacy policy, business address, and phone data.
- [ ] Remove footer dependency on the archived snapshot.

Definition of done:

- Footer matches the live CROG front door without archived HTML injection.

### 10. Legacy Snapshot Removal

- [ ] Remove `legacy-home-20180820.html` as a runtime dependency.
- [ ] Remove homepage archive slicing logic from
      `apps/storefront/src/app/(storefront)/page.tsx`.
- [ ] Remove legacy homepage stylesheet injection from that file.
- [ ] Remove inline CSS patching used to stabilize the archived markup.
- [ ] Remove dead homepage fallback copy paths.

Definition of done:

- The Next homepage renders entirely from explicit React sections and live
  structured content.

## Suggested Implementation Order

1. Fix homepage metadata and shell.
2. Rebuild navigation.
3. Rebuild hero.
4. Validate or rebuild search / booking.
5. Rebuild featured cabins and category links.
6. Rebuild footer.
7. Rebuild promos and optional reviews.
8. Remove archived HTML dependency.
9. Run parity QA in preview.
10. Remove the `/` proxy only after approval.

## QA Checklist Before Cutover

- [ ] `/` matches approved CROG branding and SEO.
- [ ] Header and footer links are correct.
- [ ] Hero copy and imagery are current.
- [ ] Search submits correctly and leads into booking.
- [ ] `/availability` path behavior is correct.
- [ ] Featured cabin cards match live merchandising expectations.
- [ ] Category links route to the correct destinations.
- [ ] Homepage performance is acceptable on desktop and mobile.
- [ ] No archived 2018-only content remains.
- [ ] Business stakeholder signoff is recorded.

## Immediate Next Step

Start with homepage metadata, shell isolation, and a structured navigation
source. Those changes reduce the biggest branding drift without touching booking
conversion flows yet.
