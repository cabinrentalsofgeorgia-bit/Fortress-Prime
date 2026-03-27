import type { Metadata } from "next";
import { notFound } from "next/navigation";
import Link from "next/link";
import {
  ArrowLeft,
  ArrowRight,
  CalendarDays,
  Lock,
  Sparkles,
  Mountain,
  Users,
} from "lucide-react";
import { cn } from "@/lib/utils";
import { buildBackendUrl } from "@/lib/server/backend-url";

export const revalidate = 300;

interface FleetCalendarDay {
  date: string;
  status: "available" | "blocked";
  available: boolean;
  nightly_rate: number | null;
  season: string;
  multiplier: number;
}

interface FleetCalendarProperty {
  property_id: string;
  property_name: string;
  slug: string;
  property_type: string;
  bedrooms: number;
  bathrooms: number | null;
  max_guests: number;
  address?: string | null;
  month_grid: Record<string, FleetCalendarDay>;
  summary: {
    available_days: number;
    blocked_days: number;
    average_nightly_rate: number;
  };
}

interface FleetCalendarResponse {
  month: number;
  year: number;
  start_date: string;
  end_date: string;
  generated_at: string;
  property_count: number;
  pricing_source: string;
  availability_source: string;
  properties: FleetCalendarProperty[];
}

function formatMoney(amount: number) {
  return new Intl.NumberFormat("en-US", {
    style: "currency",
    currency: "USD",
    maximumFractionDigits: 0,
  }).format(amount);
}

function monthLabel(year: number, month: number) {
  return new Date(Date.UTC(year, month - 1, 1)).toLocaleDateString("en-US", {
    month: "long",
    year: "numeric",
    timeZone: "UTC",
  });
}

function monthWindow(year: number, month: number) {
  const start = new Date(Date.UTC(year, month - 1, 1));
  const end = new Date(Date.UTC(year, month, 0));
  return {
    startIso: start.toISOString().slice(0, 10),
    endIso: end.toISOString().slice(0, 10),
    daysInMonth: end.getUTCDate(),
  };
}

function adjacentMonth(year: number, month: number, delta: number) {
  const target = new Date(Date.UTC(year, month - 1 + delta, 1));
  return {
    year: target.getUTCFullYear(),
    month: target.getUTCMonth() + 1,
  };
}

async function fetchJson<T>(path: string): Promise<T> {
  const response = await fetch(buildBackendUrl(path), {
    next: { revalidate },
  });
  if (!response.ok) {
    throw new Error(`Backend request failed for ${path} (${response.status})`);
  }
  return response.json() as Promise<T>;
}

function formatRefreshLabel(value: string) {
  return new Intl.DateTimeFormat("en-US", {
    month: "short",
    day: "numeric",
    hour: "numeric",
    minute: "2-digit",
    timeZone: "UTC",
  }).format(new Date(value));
}

async function getAvailabilityData(year: number, month: number) {
  const { startIso, endIso, daysInMonth } = monthWindow(year, month);
  const fleet = await fetchJson<FleetCalendarResponse>(
    `/api/direct-booking/fleet/calendar-v2?year=${year}&month=${month}`,
  );
  return { fleet, startIso, endIso, daysInMonth };
}

export async function generateMetadata({
  params,
}: {
  params: Promise<{ year: string; month: string }>;
}): Promise<Metadata> {
  const { year, month } = await params;
  const yearNumber = Number.parseInt(year, 10);
  const monthNumber = Number.parseInt(month, 10);
  if (
    Number.isNaN(yearNumber) ||
    Number.isNaN(monthNumber) ||
    monthNumber < 1 ||
    monthNumber > 12
  ) {
    return {
      title: "Availability | Cabin Rentals of Georgia",
    };
  }

  const label = monthLabel(yearNumber, monthNumber);
  return {
    title: `${label} Availability | Cabin Rentals of Georgia`,
    description:
      "Browse the sovereign fleet grid for Blue Ridge cabin stays with local availability and nightly rate hints.",
  };
}

export default async function AvailabilityMonthPage({
  params,
}: {
  params: Promise<{ year: string; month: string }>;
}) {
  const { year, month } = await params;
  const yearNumber = Number.parseInt(year, 10);
  const monthNumber = Number.parseInt(month, 10);

  if (
    Number.isNaN(yearNumber) ||
    Number.isNaN(monthNumber) ||
    monthNumber < 1 ||
    monthNumber > 12 ||
    yearNumber < 2024 ||
    yearNumber > 2035
  ) {
    notFound();
  }

  const currentMonthLabel = monthLabel(yearNumber, monthNumber);
  const previous = adjacentMonth(yearNumber, monthNumber, -1);
  const next = adjacentMonth(yearNumber, monthNumber, 1);

  const { fleet, startIso, endIso, daysInMonth } = await getAvailabilityData(
    yearNumber,
    monthNumber,
  );

  return (
    <main className="mx-auto flex max-w-7xl flex-col gap-8 bg-white px-6 py-10 text-slate-900">
      <section className="grid gap-6 rounded-[2rem] border border-slate-200 bg-slate-50 p-8 shadow-sm lg:grid-cols-[1.1fr_0.9fr]">
        <div className="space-y-5">
          <div className="inline-flex items-center gap-2 rounded-full border border-slate-200 bg-white px-3 py-1 text-sm text-slate-600">
            <Mountain className="h-4 w-4 text-slate-500" />
            Sovereign Fleet Grid
          </div>
          <div className="space-y-3">
            <h1 className="text-4xl font-light tracking-tight text-slate-900 sm:text-5xl">
              {currentMonthLabel} Availability
            </h1>
            <p className="max-w-2xl text-lg leading-8 text-slate-600">
              Scan the full portfolio in one sovereign render and spot the open $199 nights
              without touching a legacy iframe or external calendar bundle.
            </p>
          </div>
          <div className="flex flex-wrap gap-3">
            <Link
              href="/book"
              className="inline-flex items-center gap-2 rounded-sm bg-slate-900 px-5 py-3 text-sm font-semibold uppercase tracking-[0.18em] text-white transition hover:bg-black"
            >
              Search Available Cabins
              <ArrowRight className="h-4 w-4" />
            </Link>
            <Link
              href={`/availability/${previous.year}/${String(previous.month).padStart(2, "0")}`}
              className="inline-flex items-center gap-2 rounded-sm border border-slate-300 bg-white px-5 py-3 text-sm font-medium text-slate-700 transition hover:border-slate-900 hover:text-slate-900"
            >
              <ArrowLeft className="h-4 w-4" />
              Previous Month
            </Link>
            <Link
              href={`/availability/${next.year}/${String(next.month).padStart(2, "0")}`}
              className="inline-flex items-center gap-2 rounded-sm border border-slate-300 bg-white px-5 py-3 text-sm font-medium text-slate-700 transition hover:border-slate-900 hover:text-slate-900"
            >
              Next Month
              <ArrowRight className="h-4 w-4" />
            </Link>
          </div>
        </div>

        <div className="rounded-[2rem] border border-slate-200 bg-white p-6 shadow-sm">
          <div className="space-y-2">
            <h2 className="flex items-center gap-2 text-xl font-semibold text-slate-900">
              <CalendarDays className="h-5 w-5 text-slate-500" />
              Fleet Horizon
            </h2>
            <p className="text-sm text-slate-600">
              Window: {startIso} through {endIso}
            </p>
          </div>
          <div className="mt-5 space-y-3 text-sm text-slate-600">
            <div className="flex items-center justify-between rounded-xl border border-slate-200 px-4 py-3">
              <span>Active cabins</span>
              <span className="font-medium text-slate-900">{fleet.property_count}</span>
            </div>
            <div className="flex items-center justify-between rounded-xl border border-slate-200 px-4 py-3">
              <span>Days in month</span>
              <span className="font-medium text-slate-900">{daysInMonth}</span>
            </div>
            <div className="flex items-center justify-between rounded-xl border border-slate-200 px-4 py-3">
              <span>Last updated</span>
              <span className="font-medium text-slate-900">
                {formatRefreshLabel(fleet.generated_at)} UTC
              </span>
            </div>
            <div className="flex flex-wrap gap-2 pt-2">
              <span className="rounded-full border border-emerald-200 bg-emerald-50 px-3 py-1 text-xs font-medium uppercase tracking-[0.18em] text-emerald-700">
                Available
              </span>
              <span className="rounded-full border border-amber-200 bg-amber-50 px-3 py-1 text-xs font-medium uppercase tracking-[0.18em] text-amber-700">
                Blocked
              </span>
              <span className="rounded-full border border-slate-200 bg-white px-3 py-1 text-xs font-medium uppercase tracking-[0.18em] text-slate-700">
                Rates {fleet.pricing_source.replaceAll("_", " ")}
              </span>
            </div>
          </div>
        </div>
      </section>

      <section className="grid gap-6">
        {fleet.properties.map((property) => {
          const entries = Object.entries(property.month_grid);
          return (
            <article
              key={property.property_id}
              className="rounded-[2rem] border border-slate-200 bg-white shadow-sm"
            >
              <div className="space-y-3 border-b border-slate-200 px-6 py-6">
                <div className="flex flex-col gap-3 lg:flex-row lg:items-start lg:justify-between">
                  <div className="space-y-2">
                    <h2 className="text-2xl font-semibold text-slate-900">{property.property_name}</h2>
                    <p className="text-sm text-slate-600">
                      {property.bedrooms} bedrooms · {property.bathrooms} baths · Sleeps{" "}
                      {property.max_guests}
                    </p>
                    {property.address ? (
                      <p className="text-sm text-slate-500">{property.address}</p>
                    ) : null}
                  </div>
                  <div className="flex flex-wrap gap-2">
                    <span className="rounded-full border border-emerald-200 bg-emerald-50 px-3 py-1 text-xs font-medium uppercase tracking-[0.16em] text-emerald-700">
                      Open {property.summary.available_days}
                    </span>
                    <span className="rounded-full border border-slate-200 bg-slate-50 px-3 py-1 text-xs font-medium uppercase tracking-[0.16em] text-slate-700">
                      Blocked {property.summary.blocked_days}
                    </span>
                    <span className="rounded-full border border-slate-200 bg-white px-3 py-1 text-xs font-medium uppercase tracking-[0.16em] text-slate-700">
                      Avg {formatMoney(property.summary.average_nightly_rate)}
                    </span>
                  </div>
                </div>
              </div>
              <div className="space-y-4 px-6 py-6">
                <div className="overflow-x-auto rounded-2xl border border-slate-200">
                  <div
                    className="grid min-w-[1200px]"
                    style={{
                      gridTemplateColumns: `repeat(${entries.length}, minmax(0, 1fr))`,
                    }}
                  >
                    {entries.map(([isoDate, day]) => {
                      const dayNumber = isoDate.slice(-2);
                      const stateClass =
                        day.status === "blocked" ? "bg-amber-500/12" : "bg-emerald-500/8";
                      return (
                        <div
                          key={isoDate}
                          className={cn(
                            "flex min-h-28 flex-col justify-between border-b border-r border-slate-200 px-2 py-2 text-center text-slate-900 last:border-r-0",
                            stateClass,
                          )}
                        >
                          <div className="space-y-1">
                            <p className="text-xs font-semibold tracking-wide text-slate-500">
                              {dayNumber}
                            </p>
                            <p className="text-[11px] uppercase tracking-wide text-slate-500">
                              {day.available ? "open" : "blocked"}
                            </p>
                          </div>
                          <div className="space-y-1">
                            <p className="text-sm font-semibold text-slate-900">
                              {day.nightly_rate ? formatMoney(day.nightly_rate) : "Blocked"}
                            </p>
                            {day.available ? (
                              <span className="mx-auto inline-flex rounded-full border border-slate-200 bg-white px-2 py-0.5 text-[10px] font-medium uppercase tracking-[0.16em] text-slate-700">
                                {day.season.replaceAll("_", " ")}
                              </span>
                            ) : (
                              <Lock className="mx-auto h-3.5 w-3.5 text-amber-500" />
                            )}
                          </div>
                        </div>
                      );
                    })}
                  </div>
                </div>

                <div className="flex flex-wrap items-center gap-3">
                  <Link
                    href={`/cabins/${property.slug}`}
                    className="inline-flex items-center rounded-sm border border-slate-300 bg-white px-4 py-2 text-sm font-medium text-slate-700 transition hover:border-slate-900 hover:text-slate-900"
                  >
                    View Cabin
                  </Link>
                  <Link
                    href="/book"
                    className="inline-flex items-center rounded-sm bg-slate-900 px-4 py-2 text-sm font-semibold text-white transition hover:bg-black"
                  >
                    Book This Cabin
                  </Link>
                  <div className="ml-auto flex items-center gap-2 text-sm text-slate-500">
                    <Sparkles className="h-4 w-4" />
                    Live local rates
                  </div>
                  <div className="flex items-center gap-2 text-sm text-slate-500">
                    <Users className="h-4 w-4" />
                    Sleeps {property.max_guests}
                  </div>
                </div>
              </div>
            </article>
          );
        })}
      </section>
    </main>
  );
}
