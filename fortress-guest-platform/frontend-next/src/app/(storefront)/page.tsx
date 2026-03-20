import Link from "next/link";
import { ArrowRight, Mountain, ShieldCheck } from "lucide-react";

export default function StorefrontHomePage() {
  return (
    <main className="mx-auto flex max-w-6xl flex-col gap-12 px-6 py-16">
      <section className="grid gap-8 lg:grid-cols-[1.2fr_0.8fr] lg:items-center">
        <div className="space-y-6">
          <div className="inline-flex items-center gap-2 rounded-full border px-3 py-1 text-sm text-muted-foreground">
            <Mountain className="h-4 w-4 text-primary" />
            Blue Ridge direct booking
          </div>
          <div className="space-y-4">
            <h1 className="text-4xl font-bold tracking-tight sm:text-5xl">
              Book your next North Georgia cabin stay without hitting the staff Command Center.
            </h1>
            <p className="max-w-2xl text-lg text-muted-foreground">
              Public traffic is now isolated from internal operations. Browse cabin detail pages
              and complete checkout through the restored booking bridge while the native quote
              engine is rebuilt.
            </p>
          </div>
          <div className="flex flex-wrap items-center gap-3">
            <Link
              href="/book"
              className="inline-flex items-center gap-2 rounded-md bg-primary px-5 py-3 font-medium text-primary-foreground transition-colors hover:bg-primary/90"
            >
              Start Booking
              <ArrowRight className="h-4 w-4" />
            </Link>
          </div>
        </div>
        <div className="rounded-2xl border bg-card p-6 shadow-sm">
          <div className="flex items-start gap-3">
            <ShieldCheck className="mt-0.5 h-5 w-5 text-emerald-500" />
            <div className="space-y-2">
              <h2 className="font-semibold">Storefront zone active</h2>
              <p className="text-sm text-muted-foreground">
                This root route is public and no longer wrapped by the internal auth guard.
              </p>
            </div>
          </div>
        </div>
      </section>
    </main>
  );
}
