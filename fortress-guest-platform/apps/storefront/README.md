# CROG-VRS Storefront

This app is the public Next.js replacement layer for the legacy Drupal website at
`cabin-rentals-of-georgia.com`.

The migration pattern is Strangler Fig:

- Drupal remains the live fallback for routes that have not been migrated.
- Next.js owns only the routes that have been deliberately promoted.
- Revenue-sensitive paths stay on Drupal until quote, availability, checkout, payment, redirect,
  SEO, and analytics parity are proven.
- Public traffic must never be routed to `crog-ai.com`.
- Staff tools, agent orchestration, privileged APIs, and Command Center workflows belong only in
  `apps/command-center`.

## Current Boundary

The storefront app contains public guest-facing surfaces such as:

- Homepage and legacy homepage shell.
- Cabin/category/content route scaffolding.
- Availability and booking surfaces.
- Guest itinerary and agreement signing routes.
- Owner portal entry points.
- Redirect and legacy content mirrors.

The app also preserves legacy SEO behavior through:

- `src/proxy.ts` redirect handling.
- `src/data/legacy-redirects.ts`.
- `src/data/drupal_granular_blueprint.json`.
- Next.js rewrites in `next.config.ts` that send unpromoted routes back to the legacy origin.

## Promotion Rules

A Drupal route can move to Next.js only after all of the following are true:

1. The Next.js route renders production content from local CROG-VRS data or an approved static
   mirror.
2. Canonical URL, title, description, metadata, redirects, and structured content are verified
   against the Drupal route.
3. Quote, availability, checkout, and guest-intent behavior are verified when the route affects
   bookings.
4. Analytics and conversion events are present.
5. Staff has an explicit rollback path to the Drupal route.

## Safe Development

Use staging, beta, local hostnames, or direct Spark 2 ports for testing. Do not flip public DNS or
Cloudflare tunnel routing for `cabin-rentals-of-georgia.com` as part of normal development.

When adding a route, keep Drupal as fallback until parity is proven route-by-route.
