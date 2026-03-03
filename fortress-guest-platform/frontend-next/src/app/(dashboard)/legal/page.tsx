import { Suspense } from "react";
import Link from "next/link";
import { Scale, ChevronRight } from "lucide-react";
import { ErrorBoundary } from "@/components/error-boundary";
import { LegalCasesTable } from "./_components/legal-cases-table";
import { Skeleton } from "@/components/ui/skeleton";

function TableSkeleton() {
  return (
    <div className="space-y-3">
      {[1, 2, 3].map((i) => (
        <Skeleton key={i} className="h-24 w-full rounded-lg" />
      ))}
    </div>
  );
}

/**
 * Legal Command Center page.
 *
 * The shell (title, description, Council button) is a server component
 * rendered outside any error boundary — it is indestructible.
 * The data table is isolated inside ErrorBoundary + Suspense so a
 * data-fetch failure or render crash never takes down the page chrome.
 */
export default function LegalPage() {
  return (
    <div className="p-6 space-y-6">
      {/* ── INDESTRUCTIBLE SHELL — always renders ── */}
      <div className="flex items-center justify-between">
        <div>
          <h1 className="text-2xl font-bold flex items-center gap-2">
            <Scale className="h-6 w-6 text-primary" />
            Legal Command Center
          </h1>
          <p className="text-sm text-muted-foreground mt-1">
            Active litigation, deadlines, and AI extraction intelligence.
          </p>
        </div>
        <Link
          href="/legal/council"
          className="inline-flex items-center gap-2 rounded-md bg-emerald-600 px-4 py-2 text-sm font-medium text-white hover:bg-emerald-700 transition-colors"
        >
          Council of 9
          <ChevronRight className="h-4 w-4" />
        </Link>
      </div>

      {/* ── ISOLATED DATA ZONE — crashes here stay here ── */}
      <ErrorBoundary>
        <Suspense fallback={<TableSkeleton />}>
          <LegalCasesTable />
        </Suspense>
      </ErrorBoundary>
    </div>
  );
}
