"use client";

import { useState, useEffect, useRef, Suspense } from "react";
import { useRouter, useSearchParams } from "next/navigation";
import {
  Card,
  CardHeader,
  CardTitle,
  CardContent,
  CardDescription,
} from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import { Button } from "@/components/ui/button";
import {
  Mail,
  Loader2,
  CheckCircle,
  ShieldAlert,
  KeyRound,
} from "lucide-react";

function OwnerLoginContent() {
  const router = useRouter();
  const searchParams = useSearchParams();
  const token = searchParams.get("token");

  const handledRef = useRef(false);

  const [email, setEmail] = useState("");
  const [status, setStatus] = useState<
    "idle" | "loading" | "success" | "error"
  >("idle");
  const [errorMessage, setErrorMessage] = useState("");

  useEffect(() => {
    if (!token) return;
    if (handledRef.current) return;
    handledRef.current = true;

    if (typeof window !== "undefined") {
      window.history.replaceState({}, "", "/owner-login");
    }

    const verifyToken = async () => {
      setStatus("loading");
      try {
        const res = await fetch("/api/auth/owner/verify-magic-link", {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ token }),
        });

        const data = await res.json();

        if (!res.ok) {
          throw new Error(data.detail || "Invalid or expired link.");
        }

        localStorage.setItem(
          "fgp_owner_profile",
          JSON.stringify(data.owner)
        );

        setStatus("success");
        setTimeout(() => router.push("/owner"), 1500);
      } catch (err: unknown) {
        setStatus("error");
        setErrorMessage(
          err instanceof Error ? err.message : "Verification failed."
        );
      }
    };

    verifyToken();
  }, [token, router]);

  const handleRequestLink = async (e: React.FormEvent) => {
    e.preventDefault();
    setStatus("loading");
    setErrorMessage("");

    try {
      const res = await fetch("/api/auth/owner/request-magic-link", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ email }),
      });

      if (!res.ok) throw new Error("Failed to request link.");

      setStatus("success");
    } catch (err: unknown) {
      setStatus("error");
      setErrorMessage(
        err instanceof Error ? err.message : "An error occurred."
      );
    }
  };

  return (
    <Card className="w-full max-w-md bg-slate-900 border-slate-800 text-slate-100 shadow-2xl">
      <CardHeader className="space-y-2 text-center pb-6">
        <div className="mx-auto bg-slate-800 h-12 w-12 rounded-full flex items-center justify-center mb-4 border border-slate-700">
          <KeyRound className="h-6 w-6 text-blue-400" />
        </div>
        <CardTitle className="text-2xl font-bold tracking-tight">
          Owner Access
        </CardTitle>
        <CardDescription className="text-slate-400">
          {token
            ? "Verifying cryptographic token..."
            : "Enter your email for a secure, passwordless login link."}
        </CardDescription>
      </CardHeader>

      <CardContent>
        {token ? (
          <div className="flex flex-col items-center justify-center py-6 space-y-4 text-center">
            {status === "loading" && (
              <Loader2 className="h-10 w-10 text-blue-500 animate-spin" />
            )}
            {status === "success" && (
              <>
                <CheckCircle className="h-10 w-10 text-emerald-500" />
                <p className="text-emerald-400 font-medium">
                  Authentication successful. Routing to ledger...
                </p>
              </>
            )}
            {status === "error" && (
              <>
                <ShieldAlert className="h-10 w-10 text-red-500" />
                <p className="text-red-400 font-medium">{errorMessage}</p>
                <Button
                  variant="outline"
                  className="mt-4 text-slate-300"
                  onClick={() => {
                    window.location.href = "/owner-login";
                  }}
                >
                  Request New Link
                </Button>
              </>
            )}
          </div>
        ) : (
          <>
            {status === "success" ? (
              <div className="flex flex-col items-center justify-center py-6 space-y-4 text-center">
                <Mail className="h-10 w-10 text-blue-400" />
                <h3 className="text-lg font-medium text-white">
                  Check your inbox
                </h3>
                <p className="text-sm text-slate-400">
                  If that email matches an active owner profile, we&apos;ve
                  sent a secure login link.
                </p>
                <Button
                  variant="ghost"
                  className="mt-4 text-blue-400"
                  onClick={() => setStatus("idle")}
                >
                  Try another email
                </Button>
              </div>
            ) : (
              <form onSubmit={handleRequestLink} className="space-y-4">
                <div className="space-y-2">
                  <Input
                    type="email"
                    placeholder="owner@example.com"
                    value={email}
                    onChange={(e) => setEmail(e.target.value)}
                    required
                    className="bg-slate-950 border-slate-800 text-white focus-visible:ring-blue-500 h-12"
                    disabled={status === "loading"}
                  />
                </div>
                {status === "error" && (
                  <p className="text-sm text-red-400">{errorMessage}</p>
                )}
                <Button
                  type="submit"
                  className="w-full h-12 bg-blue-600 hover:bg-blue-700 text-white font-semibold transition-all"
                  disabled={status === "loading" || !email}
                >
                  {status === "loading" ? (
                    <Loader2 className="mr-2 h-5 w-5 animate-spin" />
                  ) : (
                    "Send Magic Link"
                  )}
                </Button>
              </form>
            )}
          </>
        )}
      </CardContent>
    </Card>
  );
}

export default function OwnerLoginGateway() {
  return (
    <div className="min-h-screen bg-black flex items-center justify-center p-4">
      <Suspense
        fallback={
          <Loader2 className="h-10 w-10 text-blue-500 animate-spin" />
        }
      >
        <OwnerLoginContent />
      </Suspense>
    </div>
  );
}
