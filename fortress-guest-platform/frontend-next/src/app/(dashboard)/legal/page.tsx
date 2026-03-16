import { Suspense } from "react";
import { ErrorBoundary } from "@/components/error-boundary";
import { Skeleton } from "@/components/ui/skeleton";
import { LegalCasesShell } from "./_components/legal-cases-shell";

function TableSkeleton() {
  return (
    <div className="space-y-3 p-6">
      {[1, 2, 3].map((i) => (
        <Skeleton key={i} className="h-24 w-full rounded-lg" />
      ))}
    </div>
  );
}

export default function LegalPage() {
  return (
    <ErrorBoundary>
      <Suspense fallback={<TableSkeleton />}>
        <LegalCasesShell />
      </Suspense>
    </ErrorBoundary>
  );
}
