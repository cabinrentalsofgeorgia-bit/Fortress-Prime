"use client";

import { useState } from "react";
import { useRouter } from "next/navigation";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { AlertCircle, ExternalLink, Loader2 } from "lucide-react";

interface Props {
  token: string;
  propertyId?: string;
  ownerEmail: string;
  propertyName: string | null;
}

export function AcceptInviteForm({ token, propertyId, ownerEmail, propertyName }: Props) {
  const router = useRouter();
  const [ownerName, setOwnerName] = useState("");
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  async function handleSubmit(e: React.FormEvent) {
    e.preventDefault();
    if (!ownerName.trim()) {
      setError("Please enter your full name.");
      return;
    }

    setLoading(true);
    setError(null);

    try {
      const returnUrl = `${window.location.origin}/owner/onboarding-complete`;
      const res = await fetch("/api/owner/invite/accept", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          token,
          property_id: propertyId ?? "",
          owner_name: ownerName.trim(),
          return_url: returnUrl,
        }),
      });

      const data = await res.json();

      if (!res.ok) {
        const msg =
          typeof data?.detail === "string"
            ? data.detail
            : data?.detail?.message ?? "Something went wrong. Please try again.";
        setError(msg);
        return;
      }

      // Redirect to Stripe's hosted Express onboarding page
      if (data.onboarding_url) {
        window.location.href = data.onboarding_url;
      } else {
        setError("No onboarding URL returned. Contact support.");
      }
    } catch {
      setError("Network error. Check your connection and try again.");
    } finally {
      setLoading(false);
    }
  }

  return (
    <form onSubmit={handleSubmit} className="space-y-5">
      <div className="space-y-1.5">
        <Label htmlFor="email" className="text-sm font-medium">
          Email
        </Label>
        <Input
          id="email"
          type="email"
          value={ownerEmail}
          disabled
          className="bg-muted text-muted-foreground cursor-not-allowed"
        />
      </div>

      <div className="space-y-1.5">
        <Label htmlFor="owner_name" className="text-sm font-medium">
          Your Full Name
        </Label>
        <Input
          id="owner_name"
          type="text"
          placeholder="Jane Smith"
          value={ownerName}
          onChange={(e) => setOwnerName(e.target.value)}
          required
          autoFocus
          disabled={loading}
        />
        <p className="text-xs text-muted-foreground">
          Enter the name to appear on your Stripe payout account.
        </p>
      </div>

      {error && (
        <div className="flex items-start gap-2 rounded-lg border border-destructive/40 bg-destructive/10 p-3 text-sm text-destructive">
          <AlertCircle className="h-4 w-4 shrink-0 mt-0.5" />
          <span>{error}</span>
        </div>
      )}

      <Button
        type="submit"
        disabled={loading}
        className="w-full bg-emerald-600 hover:bg-emerald-700 text-white"
      >
        {loading ? (
          <>
            <Loader2 className="h-4 w-4 mr-2 animate-spin" />
            Setting up your account…
          </>
        ) : (
          <>
            <ExternalLink className="h-4 w-4 mr-2" />
            Accept &amp; Connect Stripe Payouts
          </>
        )}
      </Button>

      <p className="text-xs text-center text-muted-foreground">
        You&apos;ll be redirected to Stripe to securely enter your banking details.
        {propertyName && (
          <> This sets up payouts for <strong>{propertyName}</strong>.</>
        )}
      </p>
    </form>
  );
}
