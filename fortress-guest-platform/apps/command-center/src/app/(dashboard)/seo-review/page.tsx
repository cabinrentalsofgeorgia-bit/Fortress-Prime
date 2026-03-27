import type { Metadata } from "next";

import { SeoReviewQueue } from "./_components/seo-review-queue";

export const metadata: Metadata = {
  title: "HITL SEO Review | Fortress Prime",
  description:
    "Internal Command Center queue for pending_human SEO patch approvals and operator edits.",
};

export default function SeoReviewPage() {
  return (
    <div className="space-y-6">
      <div className="space-y-1">
        <h1 className="text-2xl font-bold tracking-tight">HITL SEO Review</h1>
        <p className="text-sm text-muted-foreground">
          Review pending human SEO strikes, validate the God Head signal, and deploy
          approved payloads from Command Center.
        </p>
      </div>
      <SeoReviewQueue />
    </div>
  );
}
