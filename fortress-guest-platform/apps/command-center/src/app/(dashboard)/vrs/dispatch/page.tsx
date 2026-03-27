import type { Metadata } from "next";
import { VrsDispatchShell } from "../_components/vrs-dispatch-shell";

export const metadata: Metadata = {
  title: "Dispatch Radar | VRS",
  description: "Funnel HQ telemetry and recovery queue for VRS dispatch.",
};

export default function VrsDispatchPage() {
  return <VrsDispatchShell />;
}
