import type { Metadata } from "next";

import { RedirectRemapShell } from "./_components/redirect-remap-shell";

export const metadata: Metadata = {
  title: "Redirect Remaps | Fortress Prime",
  description:
    "Review and seal swarm-generated redirect remaps that passed the God Head grading gate.",
};

export default function RedirectRemapsPage() {
  return (
    <div className="space-y-6">
      <div className="space-y-1">
        <h2 className="text-2xl font-bold tracking-tight">
          Redirect Remap War Room
        </h2>
        <p className="text-muted-foreground">
          Inspect quarantined fallback remaps, review promoted candidates, and
          seal only the redirects that cleared the grading gate.
        </p>
      </div>
      <RedirectRemapShell />
    </div>
  );
}
