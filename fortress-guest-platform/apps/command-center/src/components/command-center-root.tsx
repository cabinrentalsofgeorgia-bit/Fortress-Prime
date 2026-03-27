"use client";

import { startTransition, useEffect, useState } from "react";

import CommandCenterPage from "@/app/(dashboard)/command/page";
import { DashboardShell } from "@/app/(dashboard)/dashboard-shell";
import LoginPage from "@/app/login/page";
import { bootstrapSession } from "@/lib/auth";
import { clearToken, getToken } from "@/lib/api";
import { useAppStore } from "@/lib/store";

type RootStatus = "checking" | "unauthenticated" | "authenticated";

export function CommandCenterRoot() {
  const user = useAppStore((state) => state.user);
  const setUser = useAppStore((state) => state.setUser);
  const accessToken = getToken();
  const [status, setStatus] = useState<RootStatus>(() =>
    accessToken ? "checking" : "unauthenticated",
  );

  useEffect(() => {
    if (!accessToken) {
      startTransition(() => {
        setUser(null);
        setStatus("unauthenticated");
      });
      return;
    }

    let active = true;
    startTransition(() => setStatus("checking"));

    void bootstrapSession()
      .then((staffUser) => {
        if (!active) {
          return;
        }
        setUser(staffUser);
        setStatus("authenticated");
      })
      .catch(() => {
        if (!active) {
          return;
        }
        clearToken();
        localStorage.removeItem("fgp_user");
        setUser(null);
        setStatus("unauthenticated");
      });

    return () => {
      active = false;
    };
  }, [accessToken, setUser]);

  if ((status === "authenticated" || (user && accessToken)) && user) {
    return (
      <DashboardShell skipAuthGuard>
        <CommandCenterPage />
      </DashboardShell>
    );
  }

  if (status === "checking" && accessToken) {
    return (
      <div className="flex min-h-screen items-center justify-center bg-slate-950 text-slate-50">
        <div className="text-sm text-zinc-400">Restoring Command Center session...</div>
      </div>
    );
  }

  return <LoginPage />;
}
