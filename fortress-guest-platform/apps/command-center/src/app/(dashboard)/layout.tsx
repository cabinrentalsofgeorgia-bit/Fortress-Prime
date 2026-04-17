import type { Metadata } from "next";
import { DashboardShell } from "./dashboard-shell";

export const dynamic = "force-dynamic";
export const revalidate = 0;

export const metadata: Metadata = {
  robots: { index: false, follow: false },
  title: "Command Center",
};

export default function DashboardSegmentLayout({
  children,
}: {
  children: React.ReactNode;
}) {
  return <DashboardShell>{children}</DashboardShell>;
}
