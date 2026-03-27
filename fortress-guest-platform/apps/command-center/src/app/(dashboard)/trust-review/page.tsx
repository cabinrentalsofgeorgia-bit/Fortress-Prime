import type { Metadata } from "next";

import { TrustReviewQueue } from "./_components/trust-review-queue";

export const metadata: Metadata = {
  title: "Trust Review | Fortress Prime",
  description:
    "Internal HITL Trust Swarm dashboard for reviewing blocked financial agent decisions and sealing operator overrides.",
};

export default function TrustReviewPage() {
  return (
    <div className="space-y-6">
      <div className="space-y-1">
        <h1 className="text-2xl font-bold tracking-tight">Trust Swarm Review</h1>
        <p className="text-sm text-muted-foreground">
          Review blocked Trust Decisions, inspect deterministic policy failures, and execute
          operator overrides from Command Center.
        </p>
      </div>
      <TrustReviewQueue />
    </div>
  );
}
