"use client";

import { useEffect, useMemo, useState } from "react";
import { Button } from "@/components/ui/button";
import { api } from "@/lib/api";

type CaseDetailResponse = {
  case?: {
    case_name?: string;
    case_number?: string;
    court?: string;
  };
};

type Funnel = {
  id: string;
  topic: string;
  contradiction_edge_id?: string;
  lock_in_questions: string[];
  the_strike_document: string;
  strike_script?: string;
};

type Target = {
  id: string;
  entity_name: string;
  role: string;
  status: "drafting" | "ready" | "completed";
  funnels: Funnel[];
};

type TargetsResponse = {
  case_slug: string;
  targets: Target[];
};

export default function PrintDepositionPacketPage({
  params,
}: {
  params: { slug: string; targetId: string };
}) {
  const [caseData, setCaseData] = useState<CaseDetailResponse["case"] | null>(null);
  const [targets, setTargets] = useState<Target[]>([]);
  const [isLoading, setIsLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    let cancelled = false;
    const load = async () => {
      setIsLoading(true);
      setError(null);
      try {
        const [caseResp, targetsResp] = await Promise.all([
          api.get<CaseDetailResponse>(`/api/internal/legal/cases/${params.slug}`),
          api.get<TargetsResponse>(`/api/internal/legal/cases/${params.slug}/deposition/targets`),
        ]);
        if (cancelled) return;
        setCaseData(caseResp?.case ?? null);
        setTargets(Array.isArray(targetsResp?.targets) ? targetsResp.targets : []);
      } catch (err) {
        if (cancelled) return;
        setError(err instanceof Error ? err.message : "Failed to load deposition packet data");
      } finally {
        if (!cancelled) setIsLoading(false);
      }
    };
    load();
    return () => {
      cancelled = true;
    };
  }, [params.slug]);

  const target = useMemo(
    () => targets.find((t) => t.id === params.targetId) ?? null,
    [targets, params.targetId],
  );

  const today = new Date().toLocaleDateString();

  if (isLoading) {
    return <div className="p-6">Loading courtroom packet...</div>;
  }

  if (error || !target) {
    return (
      <div className="p-6 text-red-500">
        {error ?? "Target not found for this case."}
      </div>
    );
  }

  return (
    <div className="print-packet-root min-h-screen bg-background text-foreground print:bg-white print:text-black">
      <style jsx global>{`
        @media print {
          aside,
          nav,
          [role="navigation"],
          .print-hidden,
          button {
            display: none !important;
          }
          main {
            overflow: visible !important;
            padding: 0 !important;
          }
          @page {
            size: auto;
            margin: 16mm;
          }
        }
      `}</style>

      <div className="mx-auto w-full max-w-5xl space-y-8 p-6 print:p-0">
        <div className="print-hidden flex items-center justify-end gap-2">
          <Button type="button" variant="outline" onClick={() => window.print()}>
            🖨️ Print Courtroom Packet
          </Button>
        </div>

        <section className="rounded-lg border border-border bg-card p-10 print:rounded-none print:border-black print:bg-white print:text-black print:shadow-none print:break-after-page">
          <p className="text-sm uppercase tracking-[0.2em] text-muted-foreground print:text-black">
            Confidential Attorney Work Product
          </p>
          <h1 className="mt-8 text-5xl font-bold tracking-tight print:text-black">
            DEPOSITION KILL-SHEET
          </h1>
          <div className="mt-10 space-y-2 text-lg">
            <p>
              <span className="font-semibold">Case Name:</span> {caseData?.case_name ?? "N/A"}
            </p>
            <p>
              <span className="font-semibold">Case Number:</span> {caseData?.case_number ?? "N/A"}
            </p>
            <p>
              <span className="font-semibold">Court:</span> {caseData?.court ?? "N/A"}
            </p>
            <p>
              <span className="font-semibold">Deposition of:</span> {target.entity_name}
            </p>
            <p>
              <span className="font-semibold">Date:</span> {today}
            </p>
          </div>
          <p className="mt-16 text-2xl font-extrabold uppercase tracking-[0.25em] print:text-black">
            CONFIDENTIAL ATTORNEY WORK PRODUCT
          </p>
        </section>

        <section className="space-y-8">
          {target.funnels.map((funnel, index) => (
            <article
              key={funnel.id}
              className="break-inside-avoid rounded-lg border border-border bg-card p-6 print:border-black print:bg-white print:text-black"
            >
              <header className="mb-6 border-b border-border pb-4 print:border-black">
                <p className="text-xs uppercase tracking-[0.2em] text-muted-foreground print:text-black">
                  Funnel {index + 1}
                </p>
                <h2 className="mt-2 text-2xl font-bold">{funnel.topic}</h2>
                <p className="mt-1 text-sm text-muted-foreground print:text-black">
                  Contradiction Edge Reference: {funnel.contradiction_edge_id ?? "N/A"}
                </p>
              </header>

              <div className="space-y-4">
                {funnel.lock_in_questions.map((question, qIndex) => (
                  <div
                    key={`${funnel.id}-q-${qIndex}`}
                    className="flex items-start gap-3 border-l-4 border-slate-700 pl-4 print:border-black"
                  >
                    <span className="mt-1 inline-flex h-6 w-6 items-center justify-center border border-current text-sm font-semibold">
                      [ ]
                    </span>
                    <div>
                      <p className="text-xs font-semibold uppercase tracking-[0.15em] text-muted-foreground print:text-black">
                        Q{qIndex + 1}
                      </p>
                      <p className="text-2xl font-serif leading-tight">{question}</p>
                    </div>
                  </div>
                ))}
              </div>

              <div className="mt-8 rounded-md border border-red-500/60 bg-red-950/20 p-5 print:border-black print:bg-white">
                <p className="text-sm font-bold uppercase tracking-[0.2em] text-red-300 print:text-black">
                  EXHIBIT / EVIDENCE
                </p>
                <p className="mt-2 text-xl font-semibold print:text-black">
                  {funnel.the_strike_document}
                </p>
                <p className="mt-3 text-lg print:text-black">
                  {funnel.strike_script ?? "Read the highlighted contradiction into the record."}
                </p>
              </div>
            </article>
          ))}
        </section>
      </div>
    </div>
  );
}
