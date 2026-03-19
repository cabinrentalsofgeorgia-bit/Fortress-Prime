import type { Metadata } from "next";
import { notFound } from "next/navigation";

type PageParams = { slug: string };

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

function getBaseUrl(): string {
  const appUrl = process.env.NEXT_PUBLIC_APP_URL?.trim();
  if (appUrl) return appUrl.replace(/\/$/, "");

  const vercelUrl = process.env.VERCEL_URL?.trim();
  if (vercelUrl) return `https://${vercelUrl.replace(/\/$/, "")}`;

  return "http://127.0.0.1:3000";
}

async function fetchJson<T>(path: string, allow404 = false): Promise<T | null> {
  const res = await fetch(`${getBaseUrl()}${path}`, {
    next: { revalidate: 300 },
  });

  if (allow404 && res.status === 404) return null;
  if (!res.ok) return null;

  return (await res.json()) as T;
}

async function loadCabinPageData(slug: string) {
  const property = await fetchJson<PropertyPayload>(`/api/direct-booking/property/${slug}`);
  if (!property) return null;

  const seo = await fetchJson<SeoLivePayload>(`/api/seo-patches/live/property/${slug}`, true);
  return { property, seo };
}

export async function generateMetadata(
  { params }: { params: Promise<PageParams> | PageParams },
): Promise<Metadata> {
  const { slug } = await Promise.resolve(params);
  const data = await loadCabinPageData(slug);
  if (!data) {
    return { title: "Cabin Not Found" };
  }

  const title = data.seo?.payload.title || `${data.property.name} | Cabin Rentals`;
  const description =
    data.seo?.payload.meta_description ||
    `Book ${data.property.name}, a ${data.property.bedrooms}-bedroom cabin in the Blue Ridge area.`;
  const canonical = `/cabins/${data.property.slug}`;

  return {
    title,
    description,
    alternates: {
      canonical,
    },
    openGraph: {
      title,
      description,
      type: "website",
      url: canonical,
    },
  };
}

export default async function CabinPage(
  { params }: { params: Promise<PageParams> | PageParams },
) {
  const { slug } = await Promise.resolve(params);
  const data = await loadCabinPageData(slug);
  if (!data) notFound();

  const { property, seo } = data;
  const heading = seo?.payload.h1 || property.name;
  const intro =
    seo?.payload.intro ||
    `${property.name} is a ${property.bedrooms} bedroom cabin that sleeps up to ${property.max_guests} guests.`;
  const faq = seo?.payload.faq ?? [];
  const jsonLd = seo?.payload.json_ld ?? {
    "@context": "https://schema.org",
    "@type": "LodgingBusiness",
    name: property.name,
    address: property.address || undefined,
  };

  return (
    <main className="mx-auto max-w-4xl px-6 py-10 space-y-8">
      <script
        type="application/ld+json"
        dangerouslySetInnerHTML={{ __html: JSON.stringify(jsonLd) }}
      />

      <header className="space-y-3">
        <p className="text-sm text-muted-foreground">
          {property.property_type} · Sleeps {property.max_guests}
        </p>
        <h1 className="text-4xl font-bold tracking-tight">{heading}</h1>
        <p className="text-lg text-muted-foreground">{intro}</p>
      </header>

      <section className="grid gap-4 sm:grid-cols-3">
        <div className="rounded-lg border p-4">
          <p className="text-xs text-muted-foreground">Bedrooms</p>
          <p className="text-xl font-semibold">{property.bedrooms}</p>
        </div>
        <div className="rounded-lg border p-4">
          <p className="text-xs text-muted-foreground">Bathrooms</p>
          <p className="text-xl font-semibold">{property.bathrooms}</p>
        </div>
        <div className="rounded-lg border p-4">
          <p className="text-xs text-muted-foreground">Max Guests</p>
          <p className="text-xl font-semibold">{property.max_guests}</p>
        </div>
      </section>

      {property.address ? (
        <section className="rounded-lg border p-5">
          <h2 className="text-lg font-semibold">Location</h2>
          <p className="mt-2 text-muted-foreground">{property.address}</p>
        </section>
      ) : null}

      {property.parking_instructions ? (
        <section className="rounded-lg border p-5">
          <h2 className="text-lg font-semibold">Parking</h2>
          <p className="mt-2 text-muted-foreground">{property.parking_instructions}</p>
        </section>
      ) : null}

      {faq.length > 0 ? (
        <section className="space-y-4">
          <h2 className="text-2xl font-semibold">Frequently Asked Questions</h2>
          {faq.map((item, idx) => (
            <article key={`${idx}-${item.q || "question"}`} className="rounded-lg border p-5">
              <h3 className="font-medium">{item.q || "Question"}</h3>
              <p className="mt-2 text-muted-foreground">{item.a || ""}</p>
            </article>
          ))}
        </section>
      ) : null}
    </main>
  );
}
