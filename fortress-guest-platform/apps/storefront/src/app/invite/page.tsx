"use client";

import { Suspense, useEffect, useState } from "react";
import { useSearchParams, useRouter } from "next/navigation";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Badge } from "@/components/ui/badge";
import {
  Card,
  CardContent,
  CardDescription,
  CardHeader,
  CardTitle,
} from "@/components/ui/card";
import { Mountain, Loader2, CheckCircle, XCircle, AlertTriangle } from "lucide-react";
import { API_BASE } from "@/lib/api";

interface InviteInfo {
  email: string;
  first_name: string;
  last_name: string;
  role: string;
  expires_at: string;
}

type PageState = "loading" | "ready" | "submitting" | "success" | "error";

export default function InviteAcceptPage() {
  return (
    <Suspense fallback={
      <div className="flex min-h-screen items-center justify-center"><Loader2 className="h-8 w-8 animate-spin" /></div>
    }>
      <InviteAcceptContent />
    </Suspense>
  );
}

function InviteAcceptContent() {
  const searchParams = useSearchParams();
  const router = useRouter();
  const token = searchParams.get("token");

  const [state, setState] = useState<PageState>("loading");
  const [invite, setInvite] = useState<InviteInfo | null>(null);
  const [errorMsg, setErrorMsg] = useState("");

  const [password, setPassword] = useState("");
  const [confirmPassword, setConfirmPassword] = useState("");
  const [fieldError, setFieldError] = useState("");

  useEffect(() => {
    if (!token) {
      setState("error");
      setErrorMsg("No invitation token provided. Check your email for the correct link.");
      return;
    }
    fetch(`${API_BASE}/api/invites/validate/${token}`)
      .then(async (res) => {
        if (!res.ok) {
          const data = await res.json().catch(() => null);
          throw new Error(data?.detail || "Invalid or expired invitation");
        }
        return res.json();
      })
      .then((data: InviteInfo) => {
        setInvite(data);
        setState("ready");
      })
      .catch((err) => {
        setState("error");
        setErrorMsg(err.message);
      });
  }, [token]);

  async function handleSubmit(e: React.FormEvent) {
    e.preventDefault();
    setFieldError("");

    if (password.length < 8) {
      setFieldError("Password must be at least 8 characters");
      return;
    }
    if (password !== confirmPassword) {
      setFieldError("Passwords do not match");
      return;
    }

    setState("submitting");
    try {
      const res = await fetch(`${API_BASE}/api/invites/accept`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ token, password }),
      });
      if (!res.ok) {
        const data = await res.json().catch(() => null);
        throw new Error(data?.detail || "Failed to accept invitation");
      }
      setState("success");
    } catch (err) {
      setState("error");
      setErrorMsg(err instanceof Error ? err.message : "Something went wrong");
    }
  }

  return (
    <div className="flex min-h-screen items-center justify-center bg-background p-4">
      <Card className="w-full max-w-md">
        <CardHeader className="text-center">
          <div className="mx-auto mb-2 flex h-12 w-12 items-center justify-center rounded-xl bg-primary">
            <Mountain className="h-6 w-6 text-primary-foreground" />
          </div>
          <CardTitle className="text-xl">Fortress Guest Platform</CardTitle>
          <CardDescription>Accept your invitation</CardDescription>
        </CardHeader>
        <CardContent>
          {/* Loading */}
          {state === "loading" && (
            <div className="flex flex-col items-center gap-3 py-8">
              <Loader2 className="h-8 w-8 animate-spin text-muted-foreground" />
              <p className="text-sm text-muted-foreground">Validating your invitation...</p>
            </div>
          )}

          {/* Error */}
          {state === "error" && (
            <div className="flex flex-col items-center gap-4 py-6 text-center">
              <div className="flex h-12 w-12 items-center justify-center rounded-full bg-destructive/10">
                <XCircle className="h-6 w-6 text-destructive" />
              </div>
              <div>
                <p className="font-medium text-destructive">Invitation Invalid</p>
                <p className="mt-1 text-sm text-muted-foreground">{errorMsg}</p>
              </div>
              <Button variant="outline" onClick={() => router.push("/login")}>
                Go to Login
              </Button>
            </div>
          )}

          {/* Success */}
          {state === "success" && (
            <div className="flex flex-col items-center gap-4 py-6 text-center">
              <div className="flex h-12 w-12 items-center justify-center rounded-full bg-green-500/10">
                <CheckCircle className="h-6 w-6 text-green-600" />
              </div>
              <div>
                <p className="font-medium text-green-700 dark:text-green-400">Account Created!</p>
                <p className="mt-1 text-sm text-muted-foreground">
                  Welcome, {invite?.first_name}. Your account is ready.
                </p>
              </div>
              <Button onClick={() => router.push("/login")} className="w-full">
                Sign In Now
              </Button>
            </div>
          )}

          {/* Ready / Submitting — the form */}
          {(state === "ready" || state === "submitting") && invite && (
            <div className="space-y-5">
              <div className="rounded-lg border bg-muted/30 p-4 space-y-2">
                <div className="flex items-center justify-between">
                  <span className="text-sm font-medium">
                    {invite.first_name} {invite.last_name}
                  </span>
                  <Badge variant="outline" className="capitalize text-xs">
                    {invite.role}
                  </Badge>
                </div>
                <p className="text-xs text-muted-foreground">{invite.email}</p>
                <div className="flex items-center gap-1.5 text-xs text-muted-foreground">
                  <AlertTriangle className="h-3 w-3" />
                  Expires {new Date(invite.expires_at).toLocaleDateString()} at{" "}
                  {new Date(invite.expires_at).toLocaleTimeString()}
                </div>
              </div>

              <form onSubmit={handleSubmit} className="space-y-4">
                <div className="space-y-2">
                  <Label htmlFor="pw">Create Password</Label>
                  <Input
                    id="pw"
                    type="password"
                    placeholder="Minimum 8 characters"
                    value={password}
                    onChange={(e) => setPassword(e.target.value)}
                    required
                    minLength={8}
                    disabled={state === "submitting"}
                  />
                </div>
                <div className="space-y-2">
                  <Label htmlFor="pw2">Confirm Password</Label>
                  <Input
                    id="pw2"
                    type="password"
                    placeholder="Re-enter your password"
                    value={confirmPassword}
                    onChange={(e) => setConfirmPassword(e.target.value)}
                    required
                    minLength={8}
                    disabled={state === "submitting"}
                  />
                </div>
                {fieldError && (
                  <p className="text-sm text-destructive">{fieldError}</p>
                )}
                <Button type="submit" className="w-full" disabled={state === "submitting"}>
                  {state === "submitting" ? (
                    <>
                      <Loader2 className="mr-2 h-4 w-4 animate-spin" />
                      Creating Account...
                    </>
                  ) : (
                    "Create Account"
                  )}
                </Button>
              </form>
            </div>
          )}
        </CardContent>
      </Card>
    </div>
  );
}
