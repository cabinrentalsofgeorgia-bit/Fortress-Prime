import Image from "next/image";
import { cookies } from "next/headers";
import { redirect } from "next/navigation";
import {
  CalendarDays,
  ConciergeBell,
  DoorOpen,
  House,
  KeyRound,
  MapPinned,
  Wifi,
} from "lucide-react";
import { SovereignConciergeWidget } from "@/components/SovereignConciergeWidget";
import { buildBackendUrl } from "@/lib/server/backend-url";
import { GuestSessionBootstrap } from "./_components/guest-session-bootstrap";

const GUEST_COOKIE_NAME = "fgp_guest_token";

type SearchParams = Promise<Record<string, string | string[] | undefined>>;

interface GuestItineraryPayload {
  reservation: {
    id: string;
    confirmation_code: string;
    guest_name: string;
    guest_email: string;
    status: string;
    check_in_date: string;
    check_out_date: string;
    num_guests: number;
  };
  property: {
    id: string;
    name: string;
    address?: string | null;
    hero_image_url?: string | null;
  };
  knowledge: {
    wifi: {
      ssid?: string | null;
      password?: string | null;
    };
    access: {
      code?: string | null;
      code_valid_from?: string | null;
      code_valid_until?: string | null;
      access_code_type?: string | null;
      access_code_location?: string | null;
    };
    parking_instructions?: string | null;
    snippets: Array<{
      title: string;
      category: string;
      content: string;
    }>;
  };
  stay_phase: "pre_arrival" | "during_stay" | "post_checkout";
}

function readSingleValue(value: string | string[] | undefined): string {
  if (typeof value === "string") {
    return value;
  }
  return Array.isArray(value) ? value[0] || "" : "";
}

function formatDateLabel(value: string): string {
  const parsed = new Date(`${value}T12:00:00Z`);
  return new Intl.DateTimeFormat("en-US", {
    weekday: "short",
    month: "short",
    day: "numeric",
    year: "numeric",
  }).format(parsed);
}

function formatDateTimeLabel(value: string | null | undefined): string | null {
  if (!value) {
    return null;
  }
  const parsed = new Date(value);
  if (Number.isNaN(parsed.valueOf())) {
    return null;
  }
  return new Intl.DateTimeFormat("en-US", {
    month: "short",
    day: "numeric",
    hour: "numeric",
    minute: "2-digit",
  }).format(parsed);
}

function phaseLabel(phase: GuestItineraryPayload["stay_phase"]): string {
  if (phase === "pre_arrival") {
    return "Pre-arrival";
  }
  if (phase === "during_stay") {
    return "In stay";
  }
  return "Post-checkout";
}

async function fetchGuestItinerary(token: string): Promise<GuestItineraryPayload | null> {
  const response = await fetch(buildBackendUrl("/api/guest/itinerary"), {
    method: "GET",
    headers: {
      Authorization: `Bearer ${token}`,
    },
    cache: "no-store",
  });

  if ([401, 403, 404].includes(response.status)) {
    return null;
  }
  if (!response.ok) {
    throw new Error(`Guest itinerary request failed with status ${response.status}`);
  }
  return (await response.json()) as GuestItineraryPayload;
}

export default async function GuestItineraryPage({
  searchParams,
}: {
  searchParams?: SearchParams;
}) {
  const resolvedSearchParams = (await searchParams) ?? {};
  const searchToken = readSingleValue(resolvedSearchParams.token).trim();
  const cookieStore = await cookies();
  const cookieToken = cookieStore.get(GUEST_COOKIE_NAME)?.value?.trim() || "";
  const token = searchToken || cookieToken;

  if (!token) {
    redirect("/itinerary/invalid-link?reason=missing");
  }

  const itinerary = await fetchGuestItinerary(token);
  if (!itinerary) {
    redirect("/itinerary/invalid-link?reason=expired");
  }

  const checkInLabel = formatDateLabel(itinerary.reservation.check_in_date);
  const checkOutLabel = formatDateLabel(itinerary.reservation.check_out_date);
  const accessWindowStart = formatDateTimeLabel(itinerary.knowledge.access.code_valid_from);
  const accessWindowEnd = formatDateTimeLabel(itinerary.knowledge.access.code_valid_until);

  return (
    <main className="min-h-screen bg-[#f6f0e7] text-slate-900">
      {searchToken ? <GuestSessionBootstrap token={searchToken} /> : null}

      <section className="border-b border-black/5 bg-[radial-gradient(circle_at_top,_rgba(15,23,42,0.08),_transparent_52%),linear-gradient(135deg,#fffdf8_0%,#efe2cf_100%)]">
        <div className="mx-auto max-w-6xl px-4 py-12 sm:px-6 lg:px-8 lg:py-16">
          <div className="grid gap-8 lg:grid-cols-[1.15fr_0.85fr] lg:items-center">
            <div className="space-y-6">
              <div className="inline-flex items-center gap-2 rounded-full border border-slate-300/70 bg-white/80 px-4 py-2 text-xs font-medium uppercase tracking-[0.24em] text-slate-600">
                <ConciergeBell className="h-3.5 w-3.5" />
                Sovereign Guest Portal
              </div>
              <div className="space-y-4">
                <p className="text-sm uppercase tracking-[0.24em] text-slate-500">
                  {phaseLabel(itinerary.stay_phase)} · {itinerary.reservation.confirmation_code}
                </p>
                <h1 className="max-w-3xl text-4xl font-semibold tracking-tight text-slate-950 sm:text-5xl">
                  Welcome, {itinerary.reservation.guest_name}
                </h1>
                <p className="max-w-2xl text-base leading-8 text-slate-600 sm:text-lg">
                  Your stay at {itinerary.property.name} is now grounded to the local
                  Fortress ledger, including arrival details, access context, and a
                  property-scoped concierge.
                </p>
              </div>

              <div className="grid gap-4 sm:grid-cols-3">
                <article className="rounded-[1.75rem] border border-white/70 bg-white/80 p-5 shadow-sm backdrop-blur">
                  <div className="flex items-center gap-3">
                    <CalendarDays className="h-5 w-5 text-slate-500" />
                    <div>
                      <p className="text-xs uppercase tracking-[0.18em] text-slate-500">
                        Check-in
                      </p>
                      <p className="mt-1 text-sm font-semibold text-slate-900">
                        {checkInLabel}
                      </p>
                    </div>
                  </div>
                </article>
                <article className="rounded-[1.75rem] border border-white/70 bg-white/80 p-5 shadow-sm backdrop-blur">
                  <div className="flex items-center gap-3">
                    <CalendarDays className="h-5 w-5 text-slate-500" />
                    <div>
                      <p className="text-xs uppercase tracking-[0.18em] text-slate-500">
                        Check-out
                      </p>
                      <p className="mt-1 text-sm font-semibold text-slate-900">
                        {checkOutLabel}
                      </p>
                    </div>
                  </div>
                </article>
                <article className="rounded-[1.75rem] border border-white/70 bg-white/80 p-5 shadow-sm backdrop-blur">
                  <div className="flex items-center gap-3">
                    <House className="h-5 w-5 text-slate-500" />
                    <div>
                      <p className="text-xs uppercase tracking-[0.18em] text-slate-500">
                        Guests
                      </p>
                      <p className="mt-1 text-sm font-semibold text-slate-900">
                        {itinerary.reservation.num_guests}
                      </p>
                    </div>
                  </div>
                </article>
              </div>
            </div>

            <div className="overflow-hidden rounded-[2rem] border border-white/70 bg-white/70 shadow-xl shadow-amber-950/10 backdrop-blur">
              {itinerary.property.hero_image_url ? (
                <div className="relative aspect-[16/10]">
                  <Image
                    src={itinerary.property.hero_image_url}
                    alt={`${itinerary.property.name} hero image`}
                    fill
                    priority
                    sizes="(max-width: 1024px) 100vw, 42vw"
                    className="object-cover"
                  />
                </div>
              ) : (
                <div className="flex aspect-[16/10] items-center justify-center bg-slate-100 text-sm uppercase tracking-[0.24em] text-slate-500">
                  Sovereign media pending
                </div>
              )}
              <div className="space-y-3 p-6">
                <p className="text-xs uppercase tracking-[0.22em] text-slate-500">
                  Property
                </p>
                <h2 className="text-2xl font-semibold tracking-tight text-slate-950">
                  {itinerary.property.name}
                </h2>
                {itinerary.property.address ? (
                  <div className="flex items-start gap-3 text-sm leading-7 text-slate-600">
                    <MapPinned className="mt-1 h-4 w-4 shrink-0 text-slate-500" />
                    <p>{itinerary.property.address}</p>
                  </div>
                ) : null}
              </div>
            </div>
          </div>
        </div>
      </section>

      <section className="mx-auto max-w-6xl px-4 py-10 sm:px-6 lg:px-8">
        <div className="grid gap-6 lg:grid-cols-[0.92fr_1.08fr]">
          <article className="rounded-[2rem] border border-slate-200 bg-white p-6 shadow-sm sm:p-8">
            <div className="space-y-2">
              <p className="text-xs uppercase tracking-[0.24em] text-slate-500">
                Arrival ledger
              </p>
              <h2 className="text-2xl font-semibold tracking-tight text-slate-950">
                Access and connectivity
              </h2>
            </div>

            <div className="mt-6 grid gap-4">
              <div className="rounded-[1.5rem] border border-slate-200 bg-slate-50 p-5">
                <div className="flex items-center gap-3">
                  <Wifi className="h-5 w-5 text-slate-500" />
                  <div>
                    <p className="text-xs uppercase tracking-[0.18em] text-slate-500">
                      Wi-Fi
                    </p>
                    <p className="mt-2 text-sm font-medium text-slate-900">
                      Network: {itinerary.knowledge.wifi.ssid || "Unavailable"}
                    </p>
                    <p className="mt-1 text-sm text-slate-700">
                      Password: {itinerary.knowledge.wifi.password || "Unavailable"}
                    </p>
                  </div>
                </div>
              </div>

              <div className="rounded-[1.5rem] border border-slate-200 bg-slate-50 p-5">
                <div className="flex items-center gap-3">
                  <KeyRound className="h-5 w-5 text-slate-500" />
                  <div>
                    <p className="text-xs uppercase tracking-[0.18em] text-slate-500">
                      Door code
                    </p>
                    <p className="mt-2 text-sm font-medium text-slate-900">
                      {itinerary.knowledge.access.code || "Not issued yet"}
                    </p>
                    {itinerary.knowledge.access.access_code_type ? (
                      <p className="mt-1 text-sm text-slate-700">
                        Access type: {itinerary.knowledge.access.access_code_type}
                      </p>
                    ) : null}
                    {itinerary.knowledge.access.access_code_location ? (
                      <p className="mt-1 text-sm leading-7 text-slate-700">
                        {itinerary.knowledge.access.access_code_location}
                      </p>
                    ) : null}
                    {accessWindowStart || accessWindowEnd ? (
                      <p className="mt-2 text-xs uppercase tracking-[0.16em] text-slate-500">
                        {accessWindowStart ? `Active ${accessWindowStart}` : "Activation pending"}
                        {accessWindowEnd ? ` to ${accessWindowEnd}` : ""}
                      </p>
                    ) : null}
                  </div>
                </div>
              </div>

              {itinerary.knowledge.parking_instructions ? (
                <div className="rounded-[1.5rem] border border-slate-200 bg-slate-50 p-5">
                  <div className="flex items-start gap-3">
                    <DoorOpen className="mt-1 h-5 w-5 text-slate-500" />
                    <div>
                      <p className="text-xs uppercase tracking-[0.18em] text-slate-500">
                        Arrival notes
                      </p>
                      <p className="mt-2 text-sm leading-7 text-slate-700">
                        {itinerary.knowledge.parking_instructions}
                      </p>
                    </div>
                  </div>
                </div>
              ) : null}
            </div>
          </article>

          <article className="rounded-[2rem] border border-slate-200 bg-white p-6 shadow-sm sm:p-8">
            <div className="space-y-2">
              <p className="text-xs uppercase tracking-[0.24em] text-slate-500">
                Local knowledge
              </p>
              <h2 className="text-2xl font-semibold tracking-tight text-slate-950">
                Property-specific guidance
              </h2>
            </div>

            <div className="mt-6 space-y-4">
              {itinerary.knowledge.snippets.length > 0 ? (
                itinerary.knowledge.snippets.map((snippet) => (
                  <article
                    key={`${snippet.category}-${snippet.title}`}
                    className="rounded-[1.5rem] border border-slate-200 bg-slate-50 p-5"
                  >
                    <p className="text-xs uppercase tracking-[0.18em] text-slate-500">
                      {snippet.category}
                    </p>
                    <h3 className="mt-2 text-lg font-semibold text-slate-900">
                      {snippet.title}
                    </h3>
                    <p className="mt-3 whitespace-pre-wrap text-sm leading-7 text-slate-700">
                      {snippet.content}
                    </p>
                  </article>
                ))
              ) : (
                <div className="rounded-[1.5rem] border border-dashed border-slate-300 bg-slate-50 p-5 text-sm leading-7 text-slate-600">
                  No localized guestbook entries have been published for this reservation yet.
                </div>
              )}
            </div>
          </article>
        </div>
      </section>

      <section className="mx-auto max-w-6xl px-4 pb-14 sm:px-6 lg:px-8">
        <SovereignConciergeWidget propertyId={itinerary.property.id} />
      </section>
    </main>
  );
}
