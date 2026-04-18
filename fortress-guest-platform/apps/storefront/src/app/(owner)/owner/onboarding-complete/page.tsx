import Link from "next/link";
import { CheckCircle2, Clock, ArrowRight } from "lucide-react";
import {
  Card,
  CardContent,
  CardDescription,
  CardHeader,
  CardTitle,
} from "@/components/ui/card";
import { Button } from "@/components/ui/button";

export const metadata = {
  title: "Onboarding Complete | Cabin Rentals of Georgia",
  description: "Your payout account is being set up.",
  robots: { index: false, follow: false },
};

interface PageProps {
  searchParams: Promise<{ refresh?: string }>;
}

export default async function OnboardingCompletePage({ searchParams }: PageProps) {
  const params = await searchParams;
  const isRefresh = params.refresh === "true";

  return (
    <div className="min-h-screen flex items-center justify-center p-4 bg-gradient-to-b from-background to-muted/30">
      <div className="w-full max-w-md">
        <div className="mb-6 text-center">
          <p className="text-sm text-muted-foreground">Cabin Rentals of Georgia</p>
          <h1 className="text-2xl font-bold mt-1">Owner Portal</h1>
        </div>

        <Card className={isRefresh ? "border-amber-500/30" : "border-emerald-500/30"}>
          <CardHeader className="text-center pb-3">
            <div
              className={`mx-auto mb-3 flex h-14 w-14 items-center justify-center rounded-full ${
                isRefresh ? "bg-amber-500/10" : "bg-emerald-500/10"
              }`}
            >
              {isRefresh ? (
                <Clock className="h-7 w-7 text-amber-500" />
              ) : (
                <CheckCircle2 className="h-7 w-7 text-emerald-600" />
              )}
            </div>

            <CardTitle>
              {isRefresh ? "Session Expired" : "You're Almost There"}
            </CardTitle>

            <CardDescription>
              {isRefresh
                ? "Your Stripe onboarding session timed out."
                : "Your payout account setup is underway."}
            </CardDescription>
          </CardHeader>

          <CardContent className="space-y-4">
            {isRefresh ? (
              <>
                <p className="text-sm text-muted-foreground text-center">
                  Stripe onboarding sessions expire after a period of inactivity.
                  Please return to your invitation email and click the link again to
                  restart the process.
                </p>
                <p className="text-sm text-muted-foreground text-center">
                  If your link has expired, contact your property manager to request a
                  new invitation.
                </p>
              </>
            ) : (
              <>
                <div className="rounded-lg bg-muted/50 p-4 space-y-2 text-sm text-muted-foreground">
                  <p className="font-medium text-foreground">What happens next:</p>
                  <ul className="space-y-1.5 list-inside">
                    <li className="flex items-start gap-2">
                      <CheckCircle2 className="h-4 w-4 text-emerald-500 shrink-0 mt-0.5" />
                      <span>Stripe will verify your identity and banking details (usually within minutes)</span>
                    </li>
                    <li className="flex items-start gap-2">
                      <CheckCircle2 className="h-4 w-4 text-emerald-500 shrink-0 mt-0.5" />
                      <span>You&apos;ll receive an email confirmation when your payout account is active</span>
                    </li>
                    <li className="flex items-start gap-2">
                      <CheckCircle2 className="h-4 w-4 text-emerald-500 shrink-0 mt-0.5" />
                      <span>Your 65% revenue share will begin transferring automatically with each booking</span>
                    </li>
                  </ul>
                </div>

                <Button asChild className="w-full">
                  <Link href="/owner">
                    Go to Owner Portal
                    <ArrowRight className="h-4 w-4 ml-2" />
                  </Link>
                </Button>
              </>
            )}
          </CardContent>
        </Card>
      </div>
    </div>
  );
}
