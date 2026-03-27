import type { Metadata } from "next";

import { SeoApprovalShell } from "./_components/seo-approval-shell";

export const metadata: Metadata = {
  title: "SEO Approval | Fortress Prime",
  description:
    "Human-in-the-loop review dashboard for AI-generated SEO patches before they go live.",
};

export default function SeoApprovalPage() {
  return (
    <div className="space-y-6">
      <div className="space-y-1">
        <h2 className="text-2xl font-bold tracking-tight">
          HITL SEO Approval Dashboard
        </h2>
        <p className="text-muted-foreground">
          Review queued SEO proposals, compare them against the legacy snapshot,
          and approve or reject in bulk.
        </p>
      </div>
      <SeoApprovalShell />
    </div>
  );
}
