import type { Metadata } from "next";
import { ArrowRight, Building2, ShieldCheck, Sparkles } from "lucide-react";
import Link from "next/link";

import { ManagementInquiryForm } from "@/components/storefront/management-inquiry-form";

export const metadata: Metadata = {
  title: "Property Management Inquiry | Cabin Rentals of Georgia",
  description:
    "Connect with Cabin Rentals of Georgia about property management services through the Sovereign storefront inquiry bridge.",
};

const capabilityItems = [
  {
    title: "Validated intake",
    body: "The public form mirrors the backend contract so only clean, typed inquiries enter the dispatch lane.",
    icon: ShieldCheck,
  },
  {
    title: "Shadow Path linkage",
    body: "Each submission carries a storefront session identifier so anonymous discovery can be connected to a real lead.",
    icon: Sparkles,
  },
  {
    title: "Direct operator routing",
    body: "Management inquiries route straight to the existing CRG recipients without the legacy Drupal webform hop.",
    icon: Building2,
  },
] as const;

export default function PropertyManagementInquiryPage() {
  return (
    <div className="min-h-screen bg-slate-950 text-white">
      <section className="border-b border-slate-800 bg-[radial-gradient(circle_at_top,_rgba(56,189,248,0.18),_transparent_35%),linear-gradient(180deg,_#020617_0%,_#0f172a_56%,_#020617_100%)]">
        <div className="mx-auto grid max-w-7xl gap-12 px-4 py-16 sm:px-6 lg:grid-cols-[1.1fr_0.9fr] lg:px-8 lg:py-24">
          <div className="space-y-8">
            <div className="space-y-4">
              <div className="inline-flex items-center rounded-full border border-sky-400/30 bg-sky-400/10 px-3 py-1 text-[11px] font-semibold uppercase tracking-[0.28em] text-sky-100">
                Sovereign Property Management Bridge
              </div>
              <h1 className="max-w-3xl text-4xl font-semibold tracking-tight text-white sm:text-5xl">
                Replace the legacy inquiry lane with a faster path into the management ledger.
              </h1>
              <p className="max-w-2xl text-base leading-8 text-slate-300 sm:text-lg">
                This public-facing bridge for node 2719 restores the management inquiry workflow on sovereign
                infrastructure, preserves the legacy confirmation language, and links each inquiry to the visitor’s
                Shadow Path session when available.
              </p>
            </div>

            <div className="grid gap-4 sm:grid-cols-3">
              {capabilityItems.map(({ title, body, icon: Icon }) => (
                <article
                  key={title}
                  className="rounded-3xl border border-slate-800 bg-slate-900/70 p-5 shadow-lg shadow-slate-950/30"
                >
                  <div className="mb-4 inline-flex rounded-2xl border border-sky-500/20 bg-sky-500/10 p-2 text-sky-200">
                    <Icon className="h-5 w-5" />
                  </div>
                  <h2 className="text-lg font-semibold text-white">{title}</h2>
                  <p className="mt-2 text-sm leading-6 text-slate-300">{body}</p>
                </article>
              ))}
            </div>

            <div className="rounded-3xl border border-slate-800 bg-slate-900/60 p-6">
              <p className="text-sm font-semibold uppercase tracking-[0.24em] text-sky-200">Operational continuity</p>
              <div className="mt-4 grid gap-6 md:grid-cols-2">
                <div>
                  <p className="text-sm text-slate-400">Legacy confirmation</p>
                  <p className="mt-2 text-lg font-medium text-white">“Thank you! Your message has been sent!”</p>
                </div>
                <div>
                  <p className="text-sm text-slate-400">Throttle policy</p>
                  <p className="mt-2 text-lg font-medium text-white">4 inquiries per hour per visitor/email lane</p>
                </div>
              </div>
            </div>

            <div className="flex flex-wrap items-center gap-4 text-sm text-slate-300">
              <Link
                href="/"
                className="inline-flex items-center gap-2 rounded-full border border-slate-700 px-4 py-2 transition hover:border-sky-400/40 hover:text-sky-100"
              >
                Return to storefront
                <ArrowRight className="h-4 w-4" />
              </Link>
              <span className="rounded-full border border-slate-800 bg-slate-900/80 px-4 py-2">
                Public route preserved at <code>/your-home-vacation-prosperity</code>
              </span>
            </div>
          </div>

          <div className="lg:pt-2">
            <ManagementInquiryForm />
          </div>
        </div>
      </section>
    </div>
  );
}
