import type { Metadata } from "next";
import { HedgeFundSignalsShell } from "./_components/hedge-fund-signals-shell";

export const metadata: Metadata = {
  title: "Hedge Fund Signals | Fortress Prime",
  description: "Dochia daily, weekly, and monthly signal cockpit.",
};

export default function HedgeFundSignalsPage() {
  return <HedgeFundSignalsShell />;
}
