"use client";

import { Suspense, useEffect, useState, useRef } from "react";
import Link from "next/link";
import { useRouter, useSearchParams } from "next/navigation";
import { setToken } from "@/lib/api";
import { storeUser } from "@/lib/auth";
import { useAppStore } from "@/lib/store";
import { Mountain, Loader2, AlertCircle } from "lucide-react";

export default function SSOPage() {
  return (
    <Suspense fallback={
      <div className="flex min-h-screen items-center justify-center"><Loader2 className="h-8 w-8 animate-spin" /></div>
    }>
      <SSOContent />
    </Suspense>
  );
}

function SSOContent() {
  const router = useRouter();
  const searchParams = useSearchParams();
  const setUser = useAppStore((s) => s.setUser);
  const [error, setError] = useState<string | null>(null);
  const handledRef = useRef(false);

  useEffect(() => {
    if (handledRef.current) return;
    handledRef.current = true;

    const gatewayToken = searchParams.get("token");

    // Scrub the token from the URL immediately so it doesn't persist
    // in browser history, referrer headers, or server logs.
    if (typeof window !== "undefined" && gatewayToken) {
      window.history.replaceState({}, "", "/sso");
    }

    if (!gatewayToken) {
      setError(
        "No SSO token provided. Please access VRS through the Command Center."
      );
      return;
    }

    (async () => {
      try {
        const resp = await fetch(`/api/auth/sso`, {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ gateway_token: gatewayToken }),
        });

        if (!resp.ok) {
          const data = await resp.json().catch(() => null);
          throw new Error(data?.detail || "SSO authentication failed");
        }

        const data = await resp.json();
        setToken(data.access_token);
        storeUser(data.user);
        setUser(data.user);
        router.replace("/");
      } catch (err) {
        setError(
          err instanceof Error ? err.message : "SSO authentication failed"
        );
      }
    })();
  }, [searchParams, router, setUser]);

  if (error) {
    return (
      <div className="flex min-h-screen items-center justify-center bg-background">
        <div className="flex flex-col items-center gap-4 max-w-md text-center p-8">
          <div className="flex h-14 w-14 items-center justify-center rounded-xl bg-destructive/10">
            <AlertCircle className="h-7 w-7 text-destructive" />
          </div>
          <h2 className="text-lg font-semibold">Authentication Failed</h2>
          <p className="text-sm text-muted-foreground">{error}</p>
          <Link
            href="/"
            className="mt-2 inline-flex items-center gap-2 rounded-lg bg-primary px-6 py-2.5 text-sm font-medium text-primary-foreground hover:bg-primary/90 transition-colors"
          >
            Return to Command Center
          </Link>
        </div>
      </div>
    );
  }

  return (
    <div className="flex h-screen items-center justify-center bg-background">
      <div className="flex flex-col items-center gap-4">
        <div className="flex h-14 w-14 items-center justify-center rounded-xl bg-primary">
          <Mountain className="h-7 w-7 text-primary-foreground" />
        </div>
        <Loader2 className="h-6 w-6 animate-spin text-muted-foreground" />
        <p className="text-sm text-muted-foreground">
          Authenticating via Command Center...
        </p>
      </div>
    </div>
  );
}
