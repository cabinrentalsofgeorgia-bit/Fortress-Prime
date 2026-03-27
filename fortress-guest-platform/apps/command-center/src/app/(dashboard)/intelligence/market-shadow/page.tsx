import type { Metadata } from "next";
import { MarketShadowBoardShell } from "../_components/market-shadow-board-shell";

export const metadata: Metadata = {
  title: "Market Canary | Intelligence",
  description: "Shadow pricing board and market snapshot telemetry.",
};

export default function MarketShadowPage() {
  return <MarketShadowBoardShell />;
}
