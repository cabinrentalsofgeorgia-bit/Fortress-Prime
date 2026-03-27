"use client";

import { Sidebar } from "@/components/sidebar";
import { Topbar } from "@/components/topbar";
import { ErrorBoundary } from "@/components/error-boundary";
import { AuthGuard } from "@/components/auth-guard";
import { useWebSocket } from "@/lib/websocket";
import { useSystemHealthWebSocket } from "@/lib/system-health-websocket";

export function DashboardShell({
  skipAuthGuard = false,
  children,
}: {
  skipAuthGuard?: boolean;
  children: React.ReactNode;
}) {
  useWebSocket();
  useSystemHealthWebSocket();

  const shell = (
    <div className="flex h-screen overflow-hidden">
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
