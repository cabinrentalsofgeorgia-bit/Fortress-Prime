"use client";

import { useEffect } from "react";

export default function GlobalError({
  error,
  reset,
}: {
  error: Error & { digest?: string };
  reset: () => void;
}) {
  useEffect(() => {
    console.error("[Global Error]", error);
  }, [error]);

  return (
    <div className="flex flex-col items-center justify-center min-h-screen gap-6 text-center px-4 bg-background text-foreground">
      <h1 className="text-3xl font-bold">Application Error</h1>
      <p className="text-muted-foreground max-w-md">
        {error.message || "An unexpected error occurred."}
      </p>
      <button
        onClick={reset}
        className="px-6 py-2.5 bg-primary text-primary-foreground rounded-md font-medium hover:bg-primary/90"
      >
        Retry
      </button>
    </div>
  );
}
