import type { Metadata } from "next";
import { Bath, BedDouble, CarFront, MapPinned, Users } from "lucide-react";
import { notFound } from "next/navigation";
import { LegacyBodyClasses } from "@/components/booking/legacy-body-classes";
import { PropertyGallery } from "@/components/property-gallery";
import { SovereignQuoteWidget } from "@/components/booking/sovereign-quote-widget";
import { SovereignConciergeWidget } from "@/components/SovereignConciergeWidget";
import {
  getLegacyStorefrontShell,
  LEGACY_SHELL_INLINE_CSS,
  LEGACY_STYLESHEETS,
} from "@/lib/legacy-storefront-shell";

type PageParams = { slug: string };
const FGP_BACKEND = process.env.FGP_BACKEND_URL || "http://127.0.0.1:8100";
const PROPERTY_REVALIDATE_SECONDS = 300;
const SEO_REVALIDATE_SECONDS = 300;

interface PropertyImagePayload {
  id: string;
  property_id: string;
  legacy_url: string;
  sovereign_url?: string | null;
  display_order: number;
  alt_text: string;
  is_hero: boolean;
  status: string;
}

interface PropertyPayload {
  id: string;
  name: string;
  slug: string;
  property_type: string;
  bedrooms: number;
  bathrooms: number;
  max_guests: number;
  address?: string | null;
  parking_instructions?: string | null;
  images: PropertyImagePayload[];
}

interface SeoLivePayload {
  property_slug: string;
  property_name: string;
  payload: {
    title?: string;
    meta_description?: string;
    h1?: string;
    intro?: string;
    faq?: Array<{ q?: string; a?: string }>;
    json_ld?: Record<string, unknown>;
  };
}

interface LiveSeoPayload {
  property_slug: string;
  property_name: string;
  page_path: string;
  payload: {
    title?: string;
    meta_description?: string;
    og_title?: string;
    og_description?: string;
    h1_suggestion?: string;
    jsonld?: Record<string, unknown>;
    canonical_url?: string;
    alt_tags?: Record<string, string>;
  };
  deployed_at: string | null;
  godhead_score: number | null;
}

async function fetchProperty(slug: string): Promise<PropertyPayload | null> {
  try {
    const res = await fetch(`${FGP_BACKEND}/api/direct-booking/property/${encodeURIComponent(slug)}`, {
      next: { revalidate: PROPERTY_REVALIDATE_SECONDS },
    });
    if (!res.ok) {
      return null;
    }
    return (await res.json()) as PropertyPayload;
  } catch {
    return null;
  }
}

async function fetchSeoOverlay(slug: string): Promise<SeoLivePayload | null> {
  try {
    const response = await fetch(
      `${FGP_BACKEND}/api/seo/live/property/${encodeURIComponent(slug)}`,
      {
        next: { revalidate: SEO_REVALIDATE_SECONDS },
      },
    );

    if (response.status === 404 || !response.ok) {
      return null;
    }
    return (await response.json()) as SeoLivePayload;
  } catch {
    return null;
  }
}

async function fetchLiveSeo(slug: string): Promise<LiveSeoPayload | null> {
  try {
    const response = await fetch(`${FGP_BACKEND}/api/seo/live/${encodeURIComponent(slug)}`, {
      next: {
        revalidate: SEO_REVALIDATE_SECONDS,
        tags: [`seo-patch-${slug}`],
      },
    });

    if (response.status === 404 || !response.ok) {
      return null;
    }
    return (await response.json()) as LiveSeoPayload;
  } catch {
    return null;
  }
}

async function loadCabinPageData(slug: string) {
  const [property, seo, liveSeo] = await Promise.all([
    fetchProperty(slug),
    fetchSeoOverlay(slug),
    fetchLiveSeo(slug),
  ]);

  if (!property) {
    return null;
  }

  return { property, seo, liveSeo };
}

export async function generateMetadata({
  params,
}: {
  params: Promise<PageParams> | PageParams;
}): Promise<Metadata> {
  const { slug } = await Promise.resolve(params);
  const data = await loadCabinPageData(slug);

  if (!data) {
    return { title: "Cabin Not Found" };
  }

  const fallbackTitle = `${data.property.name} | Cabin Rentals of Georgia`;
  const fallbackDesc = `Discover ${data.property.name}, a refined North Georgia cabin stay for up to ${data.property.max_guests} guests.`;
  const liveSeo = data.liveSeo?.payload;
  const title = liveSeo?.title || fallbackTitle;
  const description = liveSeo?.meta_description || fallbackDesc;
  const canonical = liveSeo?.canonical_url || `/cabins/${data.property.slug}`;

  return {
    title,
    description,
    alternates: {
      canonical,
    },
    openGraph: {
      title: liveSeo?.og_title || title,
      description: liveSeo?.og_description || description,
      type: "website",
      url: canonical,
    },
  };
}

export default async function CabinPage({
  params,
}: {
  params: Promise<PageParams> | PageParams;
}) {
  const { slug } = await Promise.resolve(params);
  const data = await loadCabinPageData(slug);

  if (!data) {
    notFound();
  }

  const { property, seo, liveSeo } = data;
  const gh = liveSeo?.payload;
  const legacy = seo?.payload;

  const heading = gh?.h1_suggestion || legacy?.h1 || property.name;
  const intro =
    legacy?.intro ||
    `${property.name} is a refined ${property.bedrooms} bedroom North Georgia cabin designed for up to ${property.max_guests} guests.`;
  const faq = legacy?.faq ?? [];
  const shell = await getLegacyStorefrontShell();
  const jsonLd = gh?.jsonld || legacy?.json_ld || {
    "@context": "https://schema.org",
    "@type": "LodgingBusiness",
    name: property.name,
    address: property.address || undefined,
  };

  return (
    <>
      <LegacyBodyClasses />
      {LEGACY_STYLESHEETS.map((href) => (
        <link key={href} rel="stylesheet" href={href} />
      ))}
      <style dangerouslySetInnerHTML={{ __html: LEGACY_SHELL_INLINE_CSS }} />
      <script
        type="application/ld+json"
        dangerouslySetInnerHTML={{ __html: JSON.stringify(jsonLd) }}
      />
      <div className="legacy-homepage">
        {shell ? (
          <div dangerouslySetInnerHTML={{ __html: shell.top }} />
        ) : (
          <div className="legacy-shell-fallback">
            <h1>{property.name}</h1>
            <p>Explore details, pricing, and live booking context for this Blue Ridge cabin.</p>
          </div>
        )}

        <div className="legacy-shell-content">
          <main className="bg-white text-slate-900">
            <PropertyGallery images={property.images} />

            <section className="border-b border-slate-200 bg-slate-50">
              <div className="mx-auto max-w-7xl px-4 py-16 sm:px-6 lg:px-8 lg:py-20">
                <div className="grid gap-10 lg:grid-cols-[1.1fr_0.9fr] lg:items-start">
                  <div className="space-y-6">
                    <div className="inline-flex items-center rounded-full border border-slate-200 bg-white px-3 py-1 text-xs font-medium uppercase tracking-[0.22em] text-slate-600">
                      {property.property_type} in North Georgia
                    </div>
                    <div className="space-y-4">
                      <h1 className="max-w-3xl text-4xl font-light tracking-tight text-slate-900 sm:text-5xl">
                        {heading}
                      </h1>
                      <p className="max-w-2xl text-lg leading-8 text-slate-600">{intro}</p>
                    </div>

                    <div className="grid gap-4 sm:grid-cols-3">
                      <div className="rounded-2xl border border-slate-200 bg-white p-5 shadow-sm">
                        <div className="flex items-center gap-3">
                          <BedDouble className="h-5 w-5 text-slate-500" />
                          <div>
                            <p className="text-xs uppercase tracking-[0.18em] text-slate-500">
                              Bedrooms
                            </p>
                            <p className="mt-1 text-xl font-semibold text-slate-900">
                              {property.bedrooms}
                            </p>
                          </div>
                        </div>
                      </div>

                      <div className="rounded-2xl border border-slate-200 bg-white p-5 shadow-sm">
                        <div className="flex items-center gap-3">
                          <Bath className="h-5 w-5 text-slate-500" />
                          <div>
                            <p className="text-xs uppercase tracking-[0.18em] text-slate-500">
                              Bathrooms
                            </p>
                            <p className="mt-1 text-xl font-semibold text-slate-900">
                              {property.bathrooms}
                            </p>
                          </div>
                        </div>
                      </div>

                      <div className="rounded-2xl border border-slate-200 bg-white p-5 shadow-sm">
                        <div className="flex items-center gap-3">
                          <Users className="h-5 w-5 text-slate-500" />
                          <div>
                            <p className="text-xs uppercase tracking-[0.18em] text-slate-500">
                              Guests
                            </p>
                            <p className="mt-1 text-xl font-semibold text-slate-900">
                              Sleeps {property.max_guests}
                            </p>
                          </div>
                        </div>
                      </div>
                    </div>
                  </div>

                  <SovereignQuoteWidget
                    propertyId={property.id}
                    propertyName={property.name}
                    maxGuests={property.max_guests}
                  />
                </div>
              </div>
            </section>

            <section className="mx-auto max-w-7xl px-4 py-16 sm:px-6 lg:px-8">
              <div className="grid gap-6 lg:grid-cols-2">
                {property.address ? (
                  <article className="rounded-[2rem] border border-slate-200 bg-white p-8 shadow-sm">
                    <div className="flex items-start gap-3">
                      <MapPinned className="mt-1 h-5 w-5 text-slate-500" />
                      <div className="space-y-3">
                        <h2 className="text-2xl font-semibold tracking-tight text-slate-900">
                          Location
                        </h2>
                        <p className="leading-8 text-slate-600">{property.address}</p>
                      </div>
                    </div>
                  </article>
                ) : null}

                {property.parking_instructions ? (
                  <article className="rounded-[2rem] border border-slate-200 bg-white p-8 shadow-sm">
                    <div className="flex items-start gap-3">
                      <CarFront className="mt-1 h-5 w-5 text-slate-500" />
                      <div className="space-y-3">
                        <h2 className="text-2xl font-semibold tracking-tight text-slate-900">
                          Arrival Details
                        </h2>
                        <p className="leading-8 text-slate-600">{property.parking_instructions}</p>
                      </div>
                    </div>
                  </article>
                ) : null}
              </div>
            </section>

            <section className="mx-auto max-w-7xl px-4 pb-16 sm:px-6 lg:px-8">
              <SovereignConciergeWidget propertyId={property.id} />
            </section>

            {faq.length > 0 ? (
              <section className="border-t border-slate-200 bg-slate-50">
                <div className="mx-auto max-w-5xl px-4 py-16 sm:px-6 lg:px-8">
                  <div className="space-y-8">
                    <div className="space-y-3 text-center">
                      <h2 className="text-3xl font-light tracking-tight text-slate-900">
                        Frequently Asked Questions
                      </h2>
                      <p className="text-slate-600">
                        Clear answers for planning a smooth, well-paced stay.
                      </p>
                    </div>

                    <div className="space-y-4">
                      {faq.map((item, idx) => (
                        <article
                          key={`${idx}-${item.q || "question"}`}
                          className="rounded-[1.5rem] border border-slate-200 bg-white p-6 shadow-sm"
                        >
                          <h3 className="text-lg font-semibold text-slate-900">
                            {item.q || "Question"}
                          </h3>
                          <p className="mt-3 leading-8 text-slate-600">{item.a || ""}</p>
                        </article>
                      ))}
                    </div>
                  </div>
                </div>
              </section>
            ) : null}
          </main>
        </div>

        {shell ? <div dangerouslySetInnerHTML={{ __html: shell.bottom }} /> : null}
      </div>
    </>
  );
}
