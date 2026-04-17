import Link from "next/link";

import type { HeroPayload } from "@/lib/storefront-homepage-content";

interface StorefrontHeroProps {
  payload: HeroPayload;
}

export function StorefrontHero({ payload }: StorefrontHeroProps) {
  return (
    <section className="relative overflow-hidden bg-stone-950 text-white">
      <div
        className="absolute inset-0 bg-cover bg-center"
        style={{ backgroundImage: `url(${payload.backgroundImageUrl})` }}
        aria-hidden="true"
      />
      <div
        className="absolute inset-0 bg-gradient-to-r from-stone-950/90 via-stone-950/60 to-stone-950/30"
        aria-hidden="true"
      />

      <div className="relative mx-auto flex min-h-[520px] max-w-7xl items-end px-4 py-16 sm:px-6 lg:px-8 lg:py-24">
        <div className="max-w-3xl space-y-6">
          <p className="text-xs font-semibold uppercase tracking-[0.32em] text-amber-200">
            Blue Ridge, Georgia
          </p>
          <h1 className="text-4xl font-semibold tracking-tight sm:text-5xl lg:text-6xl">
            {payload.headline}
          </h1>
          <p className="max-w-2xl text-base leading-8 text-stone-200 sm:text-lg">
            {payload.subheadline}
          </p>
          <div className="pt-2">
            <Link
              href={payload.ctaTarget}
              className="inline-flex items-center rounded-full bg-amber-300 px-6 py-3 text-sm font-semibold uppercase tracking-[0.18em] text-stone-950 transition hover:bg-amber-200"
            >
              {payload.ctaText}
            </Link>
          </div>
        </div>
      </div>
    </section>
  );
}
