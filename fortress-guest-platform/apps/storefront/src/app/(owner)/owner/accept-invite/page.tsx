import { Suspense } from "react";
import { Building2, CheckCircle, Clock, XCircle } from "lucide-react";
import {
  Card,
  CardContent,
  CardDescription,
  CardHeader,
  CardTitle,
} from "@/components/ui/card";
import { AcceptInviteForm } from "./_components/accept-invite-form";

export const metadata = {
  title: "Accept Owner Invitation | Cabin Rentals of Georgia",
  description: "Accept your property owner invitation and set up Stripe payouts.",
  robots: { index: false, follow: false },
};

interface PageProps {
  searchParams: Promise<{ token?: string; email?: string; property_id?: string }>;
}

async function InviteContent({ token, email, propertyId }: {
  token: string;
  email?: string;
  propertyId?: string;
}) {
  // Validate the token server-side
  let tokenData: {
    valid: boolean;
    owner_email?: string;
    property_name?: string | null;
    expires_at?: string;
  } | null = null;

  try {
    const backendUrl = process.env.BACKEND_URL ?? process.env.NEXT_PUBLIC_API_URL ?? "http://127.0.0.1:8100";
    const res = await fetch(
      `${backendUrl}/api/owner/invite/validate?token=${encodeURIComponent(token)}`,
      { cache: "no-store" }
    );
    if (res.ok) {
      tokenData = await res.json();
    }
  } catch {
    // Network error — fall through to error state
  }

  if (!tokenData?.valid) {
    return (
      <Card className="border-destructive/30">
        <CardHeader className="text-center pb-3">
          <div className="mx-auto mb-3 flex h-14 w-14 items-center justify-center rounded-full bg-destructive/10">
            <XCircle className="h-7 w-7 text-destructive" />
          </div>
          <CardTitle>Invite Link Expired</CardTitle>
          <CardDescription>
            This invitation link is no longer valid. It may have already been used
            or it has expired (invites are valid for 72 hours).
          </CardDescription>
        </CardHeader>
        <CardContent className="text-center">
          <p className="text-sm text-muted-foreground">
            Please contact your property manager to request a new invite.
          </p>
        </CardContent>
      </Card>
    );
  }

  const ownerEmail = tokenData.owner_email ?? email ?? "";
  const propertyName = tokenData.property_name ?? null;

  return (
    <Card className="border-emerald-500/30">
      <CardHeader className="text-center pb-3">
        <div className="mx-auto mb-3 flex h-14 w-14 items-center justify-center rounded-full bg-emerald-500/10">
          <Building2 className="h-7 w-7 text-emerald-600" />
        </div>
        <CardTitle>Owner Portal Invitation</CardTitle>
        <CardDescription>
          {propertyName
            ? `You've been invited to manage ${propertyName} on the Cabin Rentals of Georgia owner portal.`
            : "You've been invited to join the Cabin Rentals of Georgia owner portal."}
        </CardDescription>
      </CardHeader>

      <CardContent className="space-y-4">
        <div className="flex items-center gap-2 rounded-lg bg-muted/50 px-3 py-2 text-sm text-muted-foreground">
          <CheckCircle className="h-4 w-4 text-emerald-500 shrink-0" />
          <span>Secure payout setup via Stripe Connect</span>
        </div>
        <div className="flex items-center gap-2 rounded-lg bg-muted/50 px-3 py-2 text-sm text-muted-foreground">
          <CheckCircle className="h-4 w-4 text-emerald-500 shrink-0" />
          <span>65% revenue share deposited directly to your bank</span>
        </div>
        {tokenData.expires_at && (
          <div className="flex items-center gap-2 rounded-lg bg-amber-500/10 px-3 py-2 text-sm text-amber-700 dark:text-amber-400">
            <Clock className="h-4 w-4 shrink-0" />
            <span>
              Offer expires{" "}
              {new Date(tokenData.expires_at).toLocaleDateString("en-US", {
                month: "long",
                day: "numeric",
                hour: "numeric",
                minute: "2-digit",
              })}
            </span>
          </div>
        )}

        <div className="border-t pt-4">
          <AcceptInviteForm
            token={token}
            propertyId={propertyId}
            ownerEmail={ownerEmail}
            propertyName={propertyName}
          />
        </div>
      </CardContent>
    </Card>
  );
}

export default async function AcceptInvitePage({ searchParams }: PageProps) {
  const params = await searchParams;
  const token = params.token ?? "";
  const email = params.email;
  const propertyId = params.property_id;

  return (
    <div className="min-h-screen flex items-center justify-center p-4 bg-gradient-to-b from-background to-muted/30">
      <div className="w-full max-w-md">
        <div className="mb-6 text-center">
          <p className="text-sm text-muted-foreground">Cabin Rentals of Georgia</p>
          <h1 className="text-2xl font-bold mt-1">Owner Portal</h1>
        </div>

        {!token ? (
          <Card>
            <CardContent className="pt-6 text-center">
              <p className="text-muted-foreground text-sm">
                No invite token found. Please use the link from your invitation email.
              </p>
            </CardContent>
          </Card>
        ) : (
          <Suspense
            fallback={
              <Card>
                <CardContent className="pt-6 text-center">
                  <div className="h-6 w-32 bg-muted animate-pulse rounded mx-auto" />
                </CardContent>
              </Card>
            }
          >
            <InviteContent token={token} email={email} propertyId={propertyId} />
          </Suspense>
        )}
      </div>
    </div>
  );
}
