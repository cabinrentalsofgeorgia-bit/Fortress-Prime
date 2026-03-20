"use client";

import { useEffect, useState } from "react";
import { useRouter } from "next/navigation";
import { isAuthenticated, fetchMe, storeUser } from "@/lib/auth";
import { useAppStore } from "@/lib/store";
import { Mountain, Loader2 } from "lucide-react";
import { clearToken } from "@/lib/api";
import { isStorefrontHost } from "@/lib/domain-boundaries";

export function AuthGuard({ children }: { children: React.ReactNode }) {
  const router = useRouter();
  const setUser = useAppStore((s) => s.setUser);
  const [ready, setReady] = useState(false);

  useEffect(() => {
    if (typeof window !== "undefined" && isStorefrontHost(window.location.hostname)) {
      router.replace("/");
      return;
    }

    if (!isAuthenticated()) {
      router.replace("/login");
      return;
    }

    fetchMe()
      .then((user) => {
        storeUser(user);
        setUser(user);
        setReady(true);
      })
      .catch(() => {
        clearToken();
        localStorage.removeItem("fgp_user");
        router.replace("/login");
      });
  }, [router, setUser]);

  if (!ready) {
    return (
      <div className="flex h-screen items-center justify-center bg-background">
        <div className="flex flex-col items-center gap-4">
          <div className="flex h-14 w-14 items-center justify-center rounded-xl bg-primary">
            <Mountain className="h-7 w-7 text-primary-foreground" />
          </div>
          <Loader2 className="h-6 w-6 animate-spin text-muted-foreground" />
          <p className="text-sm text-muted-foreground">Verifying session…</p>
        </div>
      </div>
    );
  }

  return <>{children}</>;
}
