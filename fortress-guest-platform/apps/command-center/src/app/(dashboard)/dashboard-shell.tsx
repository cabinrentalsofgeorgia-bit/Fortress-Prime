"use client";

import { usePathname } from "next/navigation";
import { Sidebar } from "@/components/sidebar";
import { Topbar } from "@/components/topbar";
import { ErrorBoundary } from "@/components/error-boundary";
import { AuthGuard } from "@/components/auth-guard";
import { useWebSocket } from "@/lib/websocket";
import { useSystemHealthWebSocket } from "@/lib/system-health-websocket";

function DashboardRealtimeBridge() {
  useWebSocket();
  useSystemHealthWebSocket();
  return null;
}

export function DashboardShell({
  skipAuthGuard = false,
  children,
}: {
  skipAuthGuard?: boolean;
  children: React.ReactNode;
}) {
  const pathname = usePathname();
  const suppressRealtime = pathname === "/dashboard" || pathname.startsWith("/legal");

  const shell = (
    <div className="flex h-screen overflow-hidden">
      {!suppressRealtime ? <DashboardRealtimeBridge /> : null}
      <Sidebar />
      <div className="flex flex-1 flex-col overflow-hidden">
        <Topbar />
        <main className="flex-1 overflow-y-auto bg-background p-6">
          <ErrorBoundary>{children}</ErrorBoundary>
        </main>
      </div>
    </div>
  );

  if (skipAuthGuard) {
    return shell;
  }

  return <AuthGuard>{shell}</AuthGuard>;
}
