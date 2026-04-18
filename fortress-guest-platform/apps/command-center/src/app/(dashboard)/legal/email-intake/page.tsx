import { Suspense } from "react";
import { ErrorBoundary } from "@/components/error-boundary";
import { Skeleton } from "@/components/ui/skeleton";
import { EmailIntakeShell } from "./_components/email-intake-shell";

function TableSkeleton() {
  return (
    <div className="space-y-3 p-6">
      {[1, 2, 3, 4].map((i) => (
        <Skeleton key={i} className="h-16 w-full rounded-lg" />
      ))}
    </div>
  );
}

export default function LegalEmailIntakePage() {
  return (
    <ErrorBoundary>
      <Suspense fallback={<TableSkeleton />}>
        <EmailIntakeShell />
      </Suspense>
    </ErrorBoundary>
  );
}
