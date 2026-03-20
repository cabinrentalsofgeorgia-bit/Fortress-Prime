import type { Metadata } from "next";
import Link from "next/link";
import { notFound } from "next/navigation";
import {
  ArrowLeft,
  ArrowRight,
  CalendarDays,
  Lock,
  Mountain,
  Users,
} from "lucide-react";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import {
  Card,
  CardContent,
  CardDescription,
  CardHeader,
  CardTitle,
} from "@/components/ui/card";
import { cn } from "@/lib/utils";

const FGP_BACKEND = process.env.FGP_BACKEND_URL || "http://127.0.0.1:8100";

export const revalidate = 300;

interface AvailabilityProperty {
  id: string;
  name: string;
  slug: string;
  streamline_property_id: string;
  bedrooms: number;
  bathrooms: number;
  max_guests: number;
  address?: string | null;
  is_active: boolean;
  source: string;
}

interface PropertyCatalogResponse {
  properties: AvailabilityProperty[];
}

interface CalendarDay {
  status: "available" | "booked" | "blocked";
  nightly_rate: number;
  is_peak: boolean;
  confirmation_id?: string | null;
  block_type?: string | null;
  source?: string | null;
  pricing_source?: string | null;
}

interface MasterCalendarResponse {
  property_id: string;
  property_name: string;
  streamline_property_id: string;
  start_date: string;
  end_date: string;
  days: Record<string, CalendarDay>;
  summary: {
    available_days: number;
    booked_days: number;
    blocked_days: number;
    average_nightly_rate: number;
  };
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
  const response = await fetch(`${FGP_BACKEND}${path}`, {
    next: { revalidate },
  });
  if (!response.ok) {
    throw new Error(`Backend request failed for ${path} (${response.status})`);
  }
  return response.json() as Promise<T>;
}

async function getAvailabilityData(year: number, month: number) {
  const { startIso, endIso, daysInMonth } = monthWindow(year, month);
  const catalog = await fetchJson<PropertyCatalogResponse>(
    "/api/quotes/streamline/properties",
  );

  const properties = catalog.properties
    .filter((property) => property.is_active)
    .sort((a, b) => a.name.localeCompare(b.name));

  const calendars = await Promise.all(
    properties.map(async (property) => {
      const calendar = await fetchJson<MasterCalendarResponse>(
        `/api/quotes/streamline/calendar/${property.id}?start=${startIso}&end=${endIso}`,
      );
      return { property, calendar };
    }),
  );

  return { calendars, startIso, endIso, daysInMonth };
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
      "Browse the live master calendar for Blue Ridge cabin stays with deterministic availability and nightly rates.",
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

  const { calendars, startIso, endIso, daysInMonth } = await getAvailabilityData(
    yearNumber,
    monthNumber,
  );

  return (
    <main className="mx-auto flex max-w-7xl flex-col gap-8 px-6 py-10">
      <section className="grid gap-6 rounded-3xl border bg-card p-8 shadow-sm lg:grid-cols-[1.1fr_0.9fr]">
        <div className="space-y-5">
          <div className="inline-flex items-center gap-2 rounded-full border px-3 py-1 text-sm text-muted-foreground">
            <Mountain className="h-4 w-4 text-primary" />
            Blue Ridge master availability
          </div>
          <div className="space-y-3">
            <h1 className="text-4xl font-bold tracking-tight sm:text-5xl">
              {currentMonthLabel} Availability
            </h1>
            <p className="max-w-2xl text-lg text-muted-foreground">
              Search live inventory and nightly pricing across the Cabin Rentals of
              Georgia portfolio without waiting on a client-side calendar loader.
            </p>
          </div>
          <div className="flex flex-wrap gap-3">
            <Button asChild>
              <Link href="/book">
                Search Available Cabins
                <ArrowRight className="h-4 w-4" />
              </Link>
            </Button>
            <Button asChild variant="outline">
              <Link href={`/availability/${previous.year}/${String(previous.month).padStart(2, "0")}`}>
                <ArrowLeft className="h-4 w-4" />
                Previous Month
              </Link>
            </Button>
            <Button asChild variant="outline">
              <Link href={`/availability/${next.year}/${String(next.month).padStart(2, "0")}`}>
                Next Month
                <ArrowRight className="h-4 w-4" />
              </Link>
            </Button>
          </div>
        </div>

        <Card className="border-primary/20 bg-background/70">
          <CardHeader>
            <CardTitle className="flex items-center gap-2">
              <CalendarDays className="h-5 w-5 text-primary" />
              Master Calendar
            </CardTitle>
            <CardDescription>
              Window: {startIso} through {endIso}
            </CardDescription>
          </CardHeader>
          <CardContent className="space-y-3 text-sm text-muted-foreground">
            <div className="flex items-center justify-between rounded-lg border px-3 py-2">
              <span>Active cabins</span>
              <span className="font-medium text-foreground">{calendars.length}</span>
            </div>
            <div className="flex items-center justify-between rounded-lg border px-3 py-2">
              <span>Days in month</span>
              <span className="font-medium text-foreground">{daysInMonth}</span>
            </div>
            <div className="flex flex-wrap gap-2 pt-2">
              <Badge variant="outline">Available</Badge>
              <Badge variant="outline">Booked</Badge>
              <Badge variant="outline">Blocked</Badge>
            </div>
          </CardContent>
        </Card>
      </section>

      <section className="grid gap-6">
        {calendars.map(({ property, calendar }) => {
          const entries = Object.entries(calendar.days);
          return (
            <Card key={property.id}>
              <CardHeader className="gap-3">
                <div className="flex flex-col gap-3 lg:flex-row lg:items-start lg:justify-between">
                  <div className="space-y-2">
                    <CardTitle className="text-2xl">{property.name}</CardTitle>
                    <CardDescription>
                      {property.bedrooms} bedrooms · {property.bathrooms} baths · Sleeps{" "}
                      {property.max_guests}
                    </CardDescription>
                    {property.address ? (
                      <p className="text-sm text-muted-foreground">{property.address}</p>
                    ) : null}
                  </div>
                  <div className="flex flex-wrap gap-2">
                    <Badge variant="outline">
                      Open {calendar.summary.available_days}
                    </Badge>
                    <Badge variant="outline">
                      Booked {calendar.summary.booked_days}
                    </Badge>
                    <Badge variant="outline">
                      Avg {formatMoney(calendar.summary.average_nightly_rate)}
                    </Badge>
                  </div>
                </div>
              </CardHeader>
              <CardContent className="space-y-4">
                <div className="overflow-x-auto rounded-xl border">
                  <div
                    className="grid min-w-[1200px]"
                    style={{
                      gridTemplateColumns: `repeat(${entries.length}, minmax(0, 1fr))`,
                    }}
                  >
                    {entries.map(([isoDate, day]) => {
                      const dayNumber = isoDate.slice(-2);
                      const stateClass =
                        day.status === "booked"
                          ? "bg-sky-500/12"
                          : day.status === "blocked"
                            ? "bg-amber-500/12"
                            : "bg-emerald-500/8";
                      return (
                        <div
                          key={isoDate}
                          className={cn(
                            "flex min-h-28 flex-col justify-between border-r border-b px-2 py-2 text-center last:border-r-0",
                            stateClass,
                          )}
                        >
                          <div className="space-y-1">
                            <p className="text-xs font-semibold tracking-wide text-muted-foreground">
                              {dayNumber}
                            </p>
                            <p className="text-[11px] uppercase tracking-wide text-muted-foreground">
                              {day.status}
                            </p>
                          </div>
                          <div className="space-y-1">
                            <p className="text-sm font-semibold">
                              {formatMoney(day.nightly_rate)}
                            </p>
                            {day.is_peak ? (
                              <Badge variant="outline" className="text-[10px]">
                                Peak
                              </Badge>
                            ) : day.status === "blocked" ? (
                              <Lock className="mx-auto h-3.5 w-3.5 text-amber-500" />
                            ) : null}
                          </div>
                        </div>
                      );
                    })}
                  </div>
                </div>

                <div className="flex flex-wrap items-center gap-3">
                  <Button asChild variant="outline">
                    <Link href={`/cabins/${property.slug}`}>View Cabin</Link>
                  </Button>
                  <Button asChild>
                    <Link href="/book">Book This Cabin</Link>
                  </Button>
                  <div className="ml-auto flex items-center gap-2 text-sm text-muted-foreground">
                    <Users className="h-4 w-4" />
                    Sleeps {property.max_guests}
                  </div>
                </div>
              </CardContent>
            </Card>
          );
        })}
      </section>
    </main>
  );
}
