"use client";

import { useMemo, useState } from "react";
import { Calculator, Copy, Loader2, Sparkles } from "lucide-react";
import { toast } from "sonner";
import { ApiError, api } from "@/lib/api";
import { useVrsProperties } from "@/lib/hooks";
import { Button } from "@/components/ui/button";
import {
  Card,
  CardContent,
  CardDescription,
  CardFooter,
  CardHeader,
  CardTitle,
} from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";

type QuoteResponse = {
  id: string;
  status: string;
  checkout_url: string;
  property_id: string;
  property_name: string;
  base_rent: number;
  taxes: number;
  fees: number;
  total_amount: number;
  pricing_source: string;
};

type QuoteDispatchResponse = {
  status: string;
  guest_email: string;
};

const DEFAULT_GUEST_COUNT = "2";

function buildDefaultDate(daysFromNow: number) {
  const target = new Date();
  target.setDate(target.getDate() + daysFromNow);
  return target.toISOString().slice(0, 10);
}

function formatCurrency(amount: number) {
  return new Intl.NumberFormat("en-US", {
    style: "currency",
    currency: "USD",
  }).format(amount);
}

export function ManualQuoteGenerator() {
  const { data: properties, isLoading: propertiesLoading } = useVrsProperties();
  const [propertyId, setPropertyId] = useState("");
  const [checkIn, setCheckIn] = useState(buildDefaultDate(30));
  const [checkOut, setCheckOut] = useState(buildDefaultDate(35));
  const [guestCount, setGuestCount] = useState(DEFAULT_GUEST_COUNT);
  const [quote, setQuote] = useState<QuoteResponse | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [isSubmitting, setIsSubmitting] = useState(false);
  const [guestEmail, setGuestEmail] = useState("");
  const [isSendingQuote, setIsSendingQuote] = useState(false);

  const sortedProperties = useMemo(
    () => [...(properties ?? [])].sort((a, b) => a.name.localeCompare(b.name)),
    [properties],
  );

  const selectedProperty = useMemo(
    () => sortedProperties.find((property) => property.id === propertyId) ?? null,
    [propertyId, sortedProperties],
  );

  const canSubmit =
    Boolean(propertyId) &&
    Boolean(checkIn) &&
    Boolean(checkOut) &&
    Number(guestCount) > 0 &&
    !isSubmitting;

  const handleGenerateQuote = async () => {
    if (!propertyId) {
      setError("Select a property before generating a quote.");
      return;
    }

    if (!checkIn || !checkOut || checkOut <= checkIn) {
      setError("Choose a valid stay window with checkout after check-in.");
      return;
    }

    setIsSubmitting(true);
    setError(null);
    setQuote(null);

    try {
      const result = await api.post<QuoteResponse>("/api/quotes/generate", {
        property_id: propertyId,
        check_in: checkIn,
        check_out: checkOut,
        adults: Number(guestCount),
      });
      setQuote(result);
      toast.success("Quote generated");
    } catch (err) {
      const message =
        err instanceof ApiError
          ? err.message
          : err instanceof Error
            ? err.message
            : "Failed to generate quote.";
      setError(message);
      toast.error(message);
    } finally {
      setIsSubmitting(false);
    }
  };

  const handleCopyCheckoutLink = async () => {
    if (!quote) {
      return;
    }

    const absoluteUrl = new URL(quote.checkout_url, window.location.origin).toString();
    try {
      await navigator.clipboard.writeText(absoluteUrl);
      toast.success("Checkout link copied");
    } catch {
      toast.error("Failed to copy checkout link");
    }
  };

  const handleSendQuote = async () => {
    if (!quote) {
      return;
    }

    if (!guestEmail.trim()) {
      toast.error("Enter a guest email address before dispatching the quote.");
      return;
    }

    setIsSendingQuote(true);
    try {
      const absoluteUrl = new URL(quote.checkout_url, window.location.origin).toString();
      await api.post<QuoteDispatchResponse>("/api/quotes/send", {
        guest_email: guestEmail.trim(),
        property_name: quote.property_name,
        total_amount: quote.total_amount,
        checkout_url: absoluteUrl,
      });
      toast.success(`Quote emailed to ${guestEmail.trim()}`);
    } catch (err) {
      const message =
        err instanceof ApiError
          ? err.message
          : err instanceof Error
            ? err.message
            : "Failed to send quote email.";
      toast.error(message);
    } finally {
      setIsSendingQuote(false);
    }
  };

  return (
    <div className="space-y-6">
      <div className="flex items-start justify-between gap-4">
        <div>
          <h1 className="flex items-center gap-2 text-2xl font-bold tracking-tight">
            <Calculator className="h-6 w-6 text-primary" />
            Manual Quote Generator
          </h1>
          <p className="text-muted-foreground">
            Generate a SOTA quote and copy the checkout link for VIP direct-booking outreach.
          </p>
        </div>
      </div>

      <div className="grid gap-6 xl:grid-cols-[minmax(0,1.15fr)_minmax(320px,0.85fr)]">
        <Card>
          <CardHeader>
            <CardTitle>Quote Inputs</CardTitle>
            <CardDescription>
              Select a property, choose the stay window, and generate a direct-booking checkout payload.
            </CardDescription>
          </CardHeader>
          <CardContent className="grid gap-5 md:grid-cols-2">
            <div className="space-y-2 md:col-span-2">
              <Label htmlFor="property_id">Property Selector</Label>
              <Select value={propertyId} onValueChange={setPropertyId}>
                <SelectTrigger id="property_id" className="w-full">
                  <SelectValue
                    placeholder={propertiesLoading ? "Loading properties..." : "Select a property"}
                  />
                </SelectTrigger>
                <SelectContent>
                  {sortedProperties.map((property) => (
                    <SelectItem key={property.id} value={property.id}>
                      {property.name}
                    </SelectItem>
                  ))}
                </SelectContent>
              </Select>
              {selectedProperty && (
                <p className="text-xs text-muted-foreground">
                  UUID: {selectedProperty.id} · Streamline ID: {selectedProperty.streamline_property_id ?? "n/a"}
                </p>
              )}
            </div>

            <div className="space-y-2">
              <Label htmlFor="check_in">Check-in Date</Label>
              <Input id="check_in" type="date" value={checkIn} onChange={(event) => setCheckIn(event.target.value)} />
            </div>

            <div className="space-y-2">
              <Label htmlFor="check_out">Check-out Date</Label>
              <Input id="check_out" type="date" value={checkOut} onChange={(event) => setCheckOut(event.target.value)} />
            </div>

            <div className="space-y-2">
              <Label htmlFor="guest_count">Guest Count</Label>
              <Input
                id="guest_count"
                type="number"
                min="1"
                max="24"
                value={guestCount}
                onChange={(event) => setGuestCount(event.target.value)}
              />
            </div>

            <div className="rounded-lg border bg-muted/30 p-4 text-sm text-muted-foreground">
              The quote engine calculates the stay server-side and inserts the generated quote into `guest_quotes`.
            </div>
          </CardContent>
          <CardFooter className="flex flex-col items-start gap-3 border-t">
            <Button type="button" disabled={!canSubmit} onClick={handleGenerateQuote}>
              {isSubmitting ? (
                <>
                  <Loader2 className="h-4 w-4 animate-spin" />
                  Generating Quote...
                </>
              ) : (
                <>
                  <Sparkles className="h-4 w-4" />
                  Generate Quote
                </>
              )}
            </Button>
            {error && <p className="text-sm text-destructive">{error}</p>}
          </CardFooter>
        </Card>

        <Card className={quote ? "border-primary/30" : ""}>
          <CardHeader>
            <CardTitle>Results Card</CardTitle>
            <CardDescription>
              Itemized pricing and a ready-to-copy checkout link for guest outreach.
            </CardDescription>
          </CardHeader>
          <CardContent className="space-y-4">
            {quote ? (
              <>
                <div className="rounded-xl border bg-accent/30 p-4">
                  <p className="text-xs uppercase tracking-[0.2em] text-muted-foreground">
                    Total Price
                  </p>
                  <p className="mt-2 text-4xl font-bold tracking-tight">
                    {formatCurrency(quote.total_amount)}
                  </p>
                  <p className="mt-2 text-sm text-muted-foreground">
                    {quote.property_name} · Source: {quote.pricing_source}
                  </p>
                </div>

                <div className="grid gap-3 sm:grid-cols-3">
                  <div className="rounded-lg border p-4">
                    <p className="text-xs uppercase tracking-wider text-muted-foreground">Base Rent</p>
                    <p className="mt-2 text-xl font-semibold">{formatCurrency(quote.base_rent)}</p>
                  </div>
                  <div className="rounded-lg border p-4">
                    <p className="text-xs uppercase tracking-wider text-muted-foreground">Taxes</p>
                    <p className="mt-2 text-xl font-semibold">{formatCurrency(quote.taxes)}</p>
                  </div>
                  <div className="rounded-lg border p-4">
                    <p className="text-xs uppercase tracking-wider text-muted-foreground">Fees</p>
                    <p className="mt-2 text-xl font-semibold">{formatCurrency(quote.fees)}</p>
                  </div>
                </div>

                <div className="rounded-lg border bg-muted/20 p-4 text-sm">
                  <p className="font-medium">Checkout URL</p>
                  <p className="mt-2 break-all font-mono text-xs text-muted-foreground">
                    {quote.checkout_url}
                  </p>
                </div>
              </>
            ) : (
              <div className="rounded-lg border border-dashed p-8 text-sm text-muted-foreground">
                Generate a quote to see the itemized pricing and checkout link.
              </div>
            )}
          </CardContent>
          <CardFooter className="border-t">
            <div className="flex w-full flex-col gap-3">
              <Button type="button" variant="outline" disabled={!quote} onClick={handleCopyCheckoutLink}>
                <Copy className="h-4 w-4" />
                Copy Checkout Link
              </Button>

              <div className="grid gap-3 md:grid-cols-[minmax(0,1fr)_auto]">
                <Input
                  type="email"
                  placeholder="Guest Email Address"
                  value={guestEmail}
                  onChange={(event) => setGuestEmail(event.target.value)}
                  disabled={!quote || isSendingQuote}
                />
                <Button type="button" disabled={!quote || isSendingQuote || !guestEmail.trim()} onClick={handleSendQuote}>
                  {isSendingQuote ? (
                    <>
                      <Loader2 className="h-4 w-4 animate-spin" />
                      Sending Quote...
                    </>
                  ) : (
                    "Send Quote to Guest"
                  )}
                </Button>
              </div>
            </div>
          </CardFooter>
        </Card>
      </div>
    </div>
  );
}
