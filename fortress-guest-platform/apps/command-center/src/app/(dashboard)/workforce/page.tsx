import type { Metadata } from "next";

export const metadata: Metadata = {
  title: "Workforce Matrix | Fortress Prime",
  description:
    "Sovereign workforce control plane embedded inside the Fortress Prime Command Center.",
};

export default function WorkforceDashboardPage() {
  return (
    <section className="-m-6 flex h-[calc(100vh-4rem)] min-h-[720px] flex-col overflow-hidden bg-black">
      <header className="border-b border-zinc-800 bg-black/95 px-6 py-4">
        <p className="text-[11px] font-medium uppercase tracking-[0.28em] text-zinc-500">
          Sovereign Workforce Matrix
        </p>
        <h1 className="mt-2 text-xl font-semibold uppercase tracking-[0.18em] text-zinc-100">
          Paperclip Control Plane
        </h1>
        <p className="mt-2 max-w-3xl text-sm text-zinc-400">
          Internal orchestration surface for workforce governance, task issuance, and operator oversight.
        </p>
      </header>

      <div className="flex-1 bg-black">
        <iframe
          src="/orchestrator/"
          title="Paperclip Control Plane"
          className="h-full w-full border-0 bg-black"
          loading="eager"
        />
      </div>
    </section>
  );
}
