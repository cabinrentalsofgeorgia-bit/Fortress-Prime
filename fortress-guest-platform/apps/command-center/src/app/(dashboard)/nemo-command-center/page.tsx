import type { Metadata } from "next";
import { NemoCommandShell } from "./_components/nemo-command-shell";

export const metadata: Metadata = {
  title: "NeMo Command Center | Fortress Prime",
  description: "Sovereign trust ledger hash-chain health and recent transaction feed.",
};

export default function NemoCommandCenterPage() {
  return (
    <div className="space-y-6">
      <div className="space-y-1">
        <h1 className="text-2xl font-bold tracking-tight">NeMo Command Center</h1>
        <p className="text-muted-foreground">
          Immutable ledger monitoring — Hermes hash-chain verification and trust transaction explorer.
        </p>
      </div>
      <NemoCommandShell />
    </div>
  );
}
