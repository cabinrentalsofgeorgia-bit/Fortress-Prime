"use client";

import { useState, useEffect, type FormEvent } from "react";
import { useRouter } from "next/navigation";
import { Mountain, Loader2, AlertCircle } from "lucide-react";
import { bootstrapSession, storeUser } from "@/lib/auth";
import { clearToken, setToken } from "@/lib/api";
import { isStorefrontHost } from "@/lib/domain-boundaries";
import { useAppStore } from "@/lib/store";

export const dynamic = "force-dynamic";

export default function LoginPage() {
  const router = useRouter();
  const setUser = useAppStore((s) => s.setUser);

  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(false);

  useEffect(() => {
    if (typeof window !== "undefined" && isStorefrontHost(window.location.hostname)) {
      router.replace("/");
      return;
    }

    void bootstrapSession()
      .then((user) => {
        setUser(user);
        router.replace("/");
      })
      .catch(() => {
        clearToken();
        localStorage.removeItem("fgp_user");
      });
  }, [router, setUser]);

  async function handleSubmit(e: FormEvent) {
    e.preventDefault();
    setError(null);
    setLoading(true);

    try {
      const res = await fetch("/api/auth/login", {
        method: "POST",
        headers: {
          "Content-Type": "application/json",
          Accept: "application/json",
        },
        body: JSON.stringify({ email, password }),
      });

      if (!res.ok) {
        const data = await res.json().catch(() => null);
        const raw = data?.detail ?? data?.error ?? data?.message ?? "Invalid credentials";
        const msg = typeof raw === "string" ? raw : JSON.stringify(raw);
        const hint = typeof data?.hint === "string" ? data.hint.trim() : "";
        throw new Error(hint ? `${msg}\n\n${hint}` : msg);
      }

      const data = await res.json();
      setToken(data.access_token);
      storeUser(data.user);
      setUser(data.user);
      router.replace("/");
    } catch (err) {
      setError(err instanceof Error ? err.message : "Login failed");
    } finally {
      setLoading(false);
    }
  }

  return (
    <div className="relative flex min-h-screen items-center justify-center overflow-hidden bg-slate-950 px-6 py-10 text-white">
      <div className="absolute inset-0 bg-[radial-gradient(circle_at_top,rgba(16,185,129,0.18),transparent_38%),radial-gradient(circle_at_bottom,rgba(15,23,42,0.72),transparent_30%)]" />
      <div className="absolute inset-0 bg-[linear-gradient(rgba(255,255,255,0.03)_1px,transparent_1px),linear-gradient(90deg,rgba(255,255,255,0.03)_1px,transparent_1px)] bg-[size:32px_32px] opacity-20" />

      <div className="relative w-full max-w-md rounded-3xl border border-white/10 bg-zinc-950/92 p-8 shadow-[0_0_0_1px_rgba(255,255,255,0.04),0_30px_120px_rgba(0,0,0,0.65)] backdrop-blur-xl">
        <div className="mb-8 flex flex-col items-center gap-4 text-center">
          <div className="flex h-16 w-16 items-center justify-center rounded-2xl border border-emerald-500/20 bg-emerald-500/10 shadow-[0_12px_30px_rgba(0,0,0,0.45)]">
            <Mountain className="h-8 w-8 text-emerald-300" />
          </div>
          <div className="space-y-2">
            <p className="text-xs font-medium uppercase tracking-[0.32em] text-emerald-300">
              Fortress Prime
            </p>
            <h1 className="text-2xl font-semibold tracking-tight text-emerald-400">
              Command Center
            </h1>
            <p className="text-sm text-zinc-400">
              Secure staff access for Command Center, System Health, Crog VRS, and Fortress Legal.
            </p>
          </div>
        </div>

        <form onSubmit={handleSubmit} className="space-y-4">
          {error && (
            <div className="flex items-start gap-3 rounded-2xl border border-red-500/25 bg-red-500/10 p-3 text-sm text-red-200">
              <AlertCircle className="mt-0.5 h-4 w-4 shrink-0" />
              <span>{error}</span>
            </div>
          )}

          <div className="space-y-2">
            <label
              htmlFor="email"
              className="text-sm font-medium text-zinc-200"
            >
              Email
            </label>
            <input
              id="email"
              type="email"
              autoComplete="email"
              required
              autoFocus
              value={email}
              onChange={(e) => setEmail(e.target.value)}
              className="flex h-11 w-full rounded-xl border border-white/10 bg-black/50 px-3 py-2 text-sm text-white placeholder:text-zinc-500 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-white/30"
              placeholder="you@example.com"
            />
          </div>

          <div className="space-y-2">
            <label
              htmlFor="password"
              className="text-sm font-medium text-zinc-200"
            >
              Password
            </label>
            <input
              id="password"
              type="password"
              autoComplete="current-password"
              required
              value={password}
              onChange={(e) => setPassword(e.target.value)}
              className="flex h-11 w-full rounded-xl border border-white/10 bg-black/50 px-3 py-2 text-sm text-white placeholder:text-zinc-500 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-white/30"
              placeholder="••••••••"
            />
          </div>

          <button
            type="submit"
            disabled={loading}
            className="flex h-11 w-full items-center justify-center gap-2 rounded-xl bg-emerald-500 text-sm font-medium text-slate-950 transition-colors hover:bg-emerald-400 disabled:opacity-50"
          >
            {loading ? (
              <>
                <Loader2 className="h-4 w-4 animate-spin" />
                Signing in…
              </>
            ) : (
              "Enter Command Center"
            )}
          </button>
        </form>

        <p className="mt-8 border-t border-white/10 pt-4 text-center text-xs text-zinc-500">
          Authorized Fortress Prime staff only. Sessions are audited.
        </p>
      </div>
    </div>
  );
}
