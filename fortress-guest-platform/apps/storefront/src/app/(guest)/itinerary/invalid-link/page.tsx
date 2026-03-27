import Link from "next/link";
import { AlertTriangle, ArrowLeft, ShieldX } from "lucide-react";

type InvalidLinkPageProps = {
  searchParams?: Promise<Record<string, string | string[] | undefined>>;
};

function readSingleValue(value: string | string[] | undefined): string {
  if (typeof value === "string") {
    return value;
  }
  return Array.isArray(value) ? value[0] || "" : "";
}

export default async function InvalidLinkPage({
  searchParams,
}: InvalidLinkPageProps) {
  const resolvedSearchParams = (await searchParams) ?? {};
  const reason = readSingleValue(resolvedSearchParams.reason).trim().toLowerCase();
  const message = reason === "missing"
    ? "Your guest portal link is missing the secure access token."
    : "This guest portal link is invalid, expired, or no longer available.";

  return (
    <main className="min-h-screen bg-stone-950 px-6 py-16 text-stone-50">
      <div className="mx-auto flex max-w-xl flex-col gap-8">
        <div className="inline-flex h-14 w-14 items-center justify-center rounded-2xl border border-red-500/30 bg-red-500/10 text-red-200">
          <ShieldX className="h-7 w-7" />
        </div>
        <div className="space-y-4">
          <p className="text-sm uppercase tracking-[0.28em] text-stone-400">
            Sovereign Guest Portal
          </p>
          <h1 className="text-4xl font-semibold tracking-tight text-white">
            Invalid Link
          </h1>
          <p className="max-w-lg text-base leading-7 text-stone-300">
            {message}
          </p>
        </div>

        <section className="rounded-[2rem] border border-stone-800 bg-stone-900/70 p-6 shadow-2xl shadow-black/30">
          <div className="flex items-start gap-3">
            <AlertTriangle className="mt-0.5 h-5 w-5 text-amber-300" />
            <p className="text-sm leading-7 text-stone-300">
              Request a fresh arrival link from Cabin Rentals of Georgia support if
              you still need access to your itinerary, check-in details, or concierge.
            </p>
          </div>
        </section>

        <div>
          <Link
            href="/"
            className="inline-flex items-center gap-2 rounded-full border border-stone-700 px-5 py-3 text-sm font-medium text-stone-100 transition hover:border-stone-500 hover:bg-stone-900"
          >
            <ArrowLeft className="h-4 w-4" />
            Return to storefront
          </Link>
        </div>
      </div>
    </main>
  );
}
