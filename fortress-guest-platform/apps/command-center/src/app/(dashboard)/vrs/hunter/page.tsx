import type { Metadata } from "next";
import { VrsHunterShell } from "../_components/vrs-hunter-shell";

export const metadata: Metadata = {
  title: "Hunter Ops Terminal | VRS",
  description: "Recovery ops queue, AI draft approval, and direct matrix dispatch.",
};

export default function VrsHunterPage() {
  return <VrsHunterShell />;
}
