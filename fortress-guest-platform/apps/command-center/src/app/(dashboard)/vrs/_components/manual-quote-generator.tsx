"use client";

import { useEffect, useMemo, useState } from "react";
import {
  Calculator,
  Copy,
  Loader2,
  Mail,
  Radar,
  RefreshCw,
  ShieldCheck,
} from "lucide-react";
import { toast } from "sonner";
import { ApiError, api } from "@/lib/api";
import {
  useRefreshStreamlineQuoteCache,
  useStreamlineDeterministicQuote,
  useStreamlineMasterCalendar,
  useStreamlineQuoteProperties,
  useVrsAddOns,
} from "@/lib/hooks";
import { AddOnSelector } from "@/components/booking/add-on-selector";
import { Button } from "@/components/ui/button";
import { StreamlineMasterCalendar } from "@/components/calendar/streamline-master-calendar";
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
import { Badge } from "@/components/ui/badge";

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
const CALENDAR_WINDOW_DAYS = 42;

function buildDefaultDate(daysFromNow: number) {
  const target = new Date();
  target.setDate(target.getDate() + daysFromNow);
  return target.toISOString().slice(0, 10);
}

function shiftIsoDate(isoDate: string, days: number) {
  const target = new Date(`${isoDate}T00:00:00`);
  target.setDate(target.getDate() + days);
  return target.toISOString().slice(0, 10);
}

function formatCurrency(amount: number) {
  return new Intl.NumberFormat("en-US", {
    style: "currency",
    currency: "USD",
  }).format(amount);
}

export function ManualQuoteGenerator() {
  const {
    data: propertyCatalog,
    isLoading: propertiesLoading,
  } = useStreamlineQuoteProperties();
  const [propertyId, setPropertyId] = useState("");
  const [viewStart, setViewStart] = useState(buildDefaultDate(0));
  const [checkIn, setCheckIn] = useState(buildDefaultDate(30));
  const [checkOut, setCheckOut] = useState(buildDefaultDate(35));
  const [guestCount, setGuestCount] = useState(DEFAULT_GUEST_COUNT);
  const [childrenCount, setChildrenCount] = useState("0");
  const [petsCount, setPetsCount] = useState("0");
  const [selectedAddOnIds, setSelectedAddOnIds] = useState<string[]>([]);
  const [checkoutQuote, setCheckoutQuote] = useState<QuoteResponse | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [guestEmail, setGuestEmail] = useState("");
  const [isSendingQuote, setIsSendingQuote] = useState(false);
  const quoteEngine = useStreamlineDeterministicQuote();
  const refreshCache = useRefreshStreamlineQuoteCache();
  const { data: addOns = [], isLoading: addOnsLoading } = useVrsAddOns(propertyId || undefined);
  const calendarEnd = useMemo(
    () => shiftIsoDate(viewStart, CALENDAR_WINDOW_DAYS - 1),
    [viewStart],
  );
  const {
    data: calendar,
    isLoading: calendarLoading,
    refetch: refetchCalendar,
  } = useStreamlineMasterCalendar(propertyId, viewStart, calendarEnd);

  const sortedProperties = useMemo(
    () =>
      [...(propertyCatalog?.properties ?? [])].sort((a, b) =>
        a.name.localeCompare(b.name),
      ),
    [propertyCatalog],
  );

  const selectedProperty = useMemo(
    () => sortedProperties.find((property) => property.id === propertyId) ?? null,
    [propertyId, sortedProperties],
  );
  const deterministicQuote =
    quoteEngine.data?.property_id === propertyId ? quoteEngine.data : null;

  useEffect(() => {
    if (!propertyId && sortedProperties.length > 0) {
      setPropertyId(sortedProperties[0].id);
    }
  }, [propertyId, sortedProperties]);

  useEffect(() => {
    setCheckoutQuote(null);
    setError(null);
    setSelectedAddOnIds([]);
  }, [propertyId]);

  const canSubmit =
    Boolean(propertyId) &&
    Boolean(checkIn) &&
    Boolean(checkOut) &&
    Number(guestCount) > 0 &&
    !quoteEngine.isPending;

  const requestDeterministicQuote = async (addOnIds: string[]) => {
    if (!propertyId) {
      setError("Select a property before generating a quote.");
      return;
    }

    if (!checkIn || !checkOut || checkOut <= checkIn) {
      setError("Choose a valid stay window with checkout after check-in.");
      return;
    }

    setError(null);
    setCheckoutQuote(null);

    try {
      await quoteEngine.mutateAsync({
        property_id: propertyId,
        check_in: checkIn,
        check_out: checkOut,
        adults: Number(guestCount),
        children: Number(childrenCount),
        pets: Number(petsCount),
        selected_add_on_ids: addOnIds,
      });
      toast.success("Deterministic quote generated");
    } catch (err) {
      const message =
        err instanceof ApiError
          ? err.message
          : err instanceof Error
            ? err.message
            : "Failed to generate deterministic quote.";
      setError(message);
      toast.error(message);
    }
  };

  const handleGenerateQuote = async () => {
    await requestDeterministicQuote(selectedAddOnIds);
  };

  const handleCreateCheckoutQuote = async () => {
    if (!deterministicQuote) {
      return;
    }

    try {
      const result = await api.post<QuoteResponse>("/api/quotes/generate", {
        property_id: propertyId,
        check_in: checkIn,
        check_out: checkOut,
        adults: Number(guestCount),
        children: Number(childrenCount),
        pets: Number(petsCount),
        base_rent: deterministicQuote.base_rent,
        taxes: deterministicQuote.taxes,
        fees:
          deterministicQuote.fees + (deterministicQuote.ancillary_total ?? 0),
        campaign: "deterministic_streamline",
      });
      setCheckoutQuote(result);
      toast.success("Checkout quote created");
    } catch (err) {
      const message =
        err instanceof ApiError
          ? err.message
          : err instanceof Error
            ? err.message
            : "Failed to create checkout quote.";
      toast.error(message);
    }
  };

  const handleCopyCheckoutLink = async () => {
    if (!checkoutQuote) {
      return;
    }

    const absoluteUrl = new URL(
      checkoutQuote.checkout_url,
      window.location.origin,
    ).toString();
    try {
      await navigator.clipboard.writeText(absoluteUrl);
      toast.success("Checkout link copied");
    } catch {
      toast.error("Failed to copy checkout link");
    }
  };

  const handleSendQuote = async () => {
    if (!checkoutQuote) {
      return;
    }

    if (!guestEmail.trim()) {
      toast.error("Enter a guest email address before dispatching the quote.");
      return;
    }

    setIsSendingQuote(true);
    try {
      const absoluteUrl = new URL(
        checkoutQuote.checkout_url,
        window.location.origin,
      ).toString();
      await api.post<QuoteDispatchResponse>("/api/quotes/send", {
        guest_email: guestEmail.trim(),
        property_name: checkoutQuote.property_name,
        total_amount: checkoutQuote.total_amount,
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

  const handleSelectCalendarDay = (isoDate: string) => {
    if (!checkIn || (checkIn && checkOut)) {
      setCheckIn(isoDate);
      setCheckOut("");
      setCheckoutQuote(null);
      return;
    }

    if (isoDate <= checkIn) {
      setCheckIn(isoDate);
      return;
    }

    setCheckOut(isoDate);
    setCheckoutQuote(null);
  };

  const handleRefreshCache = async () => {
    if (!propertyId) {
      return;
    }

    try {
      await refreshCache.mutateAsync({
        property_id: propertyId,
        start_date: viewStart,
        end_date: calendarEnd,
      });
      await refetchCalendar();
    } catch {
      // Toast is handled in the mutation.
    }
  };

  const handleToggleAddOn = async (addOnId: string, checked: boolean) => {
    const nextSelectedIds = checked
      ? [...selectedAddOnIds, addOnId]
      : selectedAddOnIds.filter((id) => id !== addOnId);
    setSelectedAddOnIds(nextSelectedIds);
    setCheckoutQuote(null);

    if (propertyId && checkIn && checkOut && checkOut > checkIn) {
      await requestDeterministicQuote(nextSelectedIds);
    }
  };

  return (
    <div className="space-y-6">
      <div className="flex items-start justify-between gap-4">
        <div>
          <h1 className="flex items-center gap-2 text-2xl font-bold tracking-tight">
            <Calculator className="h-6 w-6 text-primary" />
            Deterministic Quote Engine
          </h1>
          <p className="text-muted-foreground">
            Live Streamline pricing and availability with a native Next.js command-center surface.
          </p>
        </div>
        <div className="flex flex-wrap gap-2">
          <Badge variant="outline" className="gap-1">
            <ShieldCheck className="h-3.5 w-3.5" />
            Server-side pricing
          </Badge>
          <Badge variant="outline" className="gap-1">
            <Radar className="h-3.5 w-3.5" />
            Redis-backed cache
          </Badge>
        </div>
      </div>

      <div className="grid gap-6 xl:grid-cols-[minmax(0,1.15fr)_minmax(320px,0.85fr)]">
        <Card>
          <CardHeader>
            <CardTitle>Execution Inputs</CardTitle>
            <CardDescription>
              Select a property, lock the stay window, and pull deterministic pricing directly from Streamline.
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
                  UUID: {selectedProperty.id} · Streamline ID:{" "}
                  {selectedProperty.streamline_property_id}
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

            <div className="space-y-2">
              <Label htmlFor="children_count">Children</Label>
              <Input
                id="children_count"
                type="number"
                min="0"
                max="24"
                value={childrenCount}
                onChange={(event) => setChildrenCount(event.target.value)}
              />
            </div>

            <div className="space-y-2">
              <Label htmlFor="pets_count">Pets</Label>
              <Input
                id="pets_count"
                type="number"
                min="0"
                max="12"
                value={petsCount}
                onChange={(event) => setPetsCount(event.target.value)}
              />
            </div>

            <div className="rounded-lg border bg-muted/30 p-4 text-sm text-muted-foreground md:col-span-2">
              The quote engine pulls live Streamline rate and block data on the server,
              caches the normalized payload in Redis, then creates an internal checkout
              quote only after pricing is deterministic.
            </div>
            <div className="md:col-span-2">
              {addOnsLoading ? (
                <div className="rounded-lg border border-dashed p-4 text-sm text-muted-foreground">
                  Loading ancillary services...
                </div>
              ) : (
                <AddOnSelector
                  addOns={addOns}
                  selectedIds={selectedAddOnIds}
                  disabled={quoteEngine.isPending}
                  onToggle={handleToggleAddOn}
                />
              )}
            </div>
          </CardContent>
          <CardFooter className="flex flex-col items-start gap-3 border-t">
            <div className="flex flex-wrap gap-3">
              <Button type="button" disabled={!canSubmit} onClick={handleGenerateQuote}>
                {quoteEngine.isPending ? (
                  <>
                    <Loader2 className="h-4 w-4 animate-spin" />
                    Pulling Live Quote...
                  </>
                ) : (
                  <>
                    <Calculator className="h-4 w-4" />
                    Generate Deterministic Quote
                  </>
                )}
              </Button>
              <Button
                type="button"
                variant="outline"
                onClick={handleRefreshCache}
                disabled={!propertyId || refreshCache.isPending}
              >
                {refreshCache.isPending ? (
                  <>
                    <Loader2 className="h-4 w-4 animate-spin" />
                    Refreshing Cache...
                  </>
                ) : (
                  <>
                    <RefreshCw className="h-4 w-4" />
                    Refresh Property Cache
                  </>
                )}
              </Button>
            </div>
            {checkIn && !checkOut ? (
              <p className="text-sm text-muted-foreground">
                Check-in anchored at {checkIn}. Select a later available date on the
                calendar or use the date inputs to set checkout.
              </p>
            ) : null}
            {error && <p className="text-sm text-destructive">{error}</p>}
          </CardFooter>
        </Card>

        <Card className={deterministicQuote ? "border-primary/30" : ""}>
          <CardHeader>
            <CardTitle>Deterministic Output</CardTitle>
            <CardDescription>
              Exact itemized pricing from live Streamline data, then optional checkout
              payload creation for direct booking.
            </CardDescription>
          </CardHeader>
          <CardContent className="space-y-4">
            {deterministicQuote ? (
              <>
                <div className="rounded-xl border bg-accent/30 p-4">
                  <div className="flex items-start justify-between gap-3">
                    <div>
                      <p className="text-xs uppercase tracking-[0.2em] text-muted-foreground">
                        Total Price
                      </p>
                      <p className="mt-2 text-4xl font-bold tracking-tight">
                        {formatCurrency(deterministicQuote.total_amount)}
                      </p>
                      <p className="mt-2 text-sm text-muted-foreground">
                        {deterministicQuote.property_name} · Source:{" "}
                        {deterministicQuote.pricing_source ?? "streamline_live"}
                      </p>
                    </div>
                    <Badge
                      variant={
                        deterministicQuote.availability_status === "available"
                          ? "outline"
                          : "secondary"
                      }
                    >
                      {deterministicQuote.availability_status === "available"
                        ? "Inventory Open"
                        : "Inventory Blocked"}
                    </Badge>
                  </div>
                </div>

                <div className="grid gap-3 sm:grid-cols-3">
                  <div className="rounded-lg border p-4">
                    <p className="text-xs uppercase tracking-wider text-muted-foreground">
                      Base Rent
                    </p>
                    <p className="mt-2 text-xl font-semibold">
                      {formatCurrency(deterministicQuote.base_rent)}
                    </p>
                  </div>
                  <div className="rounded-lg border p-4">
                    <p className="text-xs uppercase tracking-wider text-muted-foreground">
                      Taxes
                    </p>
                    <p className="mt-2 text-xl font-semibold">
                      {formatCurrency(deterministicQuote.taxes)}
                    </p>
                  </div>
                  <div className="rounded-lg border p-4">
                    <p className="text-xs uppercase tracking-wider text-muted-foreground">
                      Fees
                    </p>
                    <p className="mt-2 text-xl font-semibold">
                      {formatCurrency(deterministicQuote.fees)}
                    </p>
                  </div>
                </div>

                {deterministicQuote.add_ons && deterministicQuote.add_ons.length > 0 ? (
                  <div className="rounded-lg border bg-muted/20 p-4 text-sm">
                    <p className="font-medium">Ancillary Services</p>
                    <div className="mt-3 grid gap-2">
                      {deterministicQuote.add_ons.map((addOn) => (
                        <div
                          key={addOn.id}
                          className="flex items-center justify-between rounded-md border px-3 py-2"
                        >
                          <div>
                            <p className="font-medium">{addOn.name}</p>
                            <p className="text-xs text-muted-foreground">
                              {addOn.pricing_model}
                            </p>
                          </div>
                          <p className="font-semibold">
                            {formatCurrency(addOn.amount)}
                          </p>
                        </div>
                      ))}
                    </div>
                  </div>
                ) : null}

                {deterministicQuote.unavailable_dates.length > 0 ? (
                  <div className="rounded-lg border border-amber-500/30 bg-amber-500/10 p-4 text-sm text-amber-200">
                    Unavailable dates detected:{" "}
                    {deterministicQuote.unavailable_dates.join(", ")}
                  </div>
                ) : null}

                <div className="rounded-lg border bg-muted/20 p-4 text-sm">
                  <p className="font-medium">Nightly Breakdown</p>
                  <div className="mt-3 grid gap-2">
                    {deterministicQuote.nightly_breakdown.map((night) => (
                      <div
                        key={night.date}
                        className="flex items-center justify-between rounded-md border px-3 py-2"
                      >
                        <div>
                          <p className="font-medium">{night.date}</p>
                          <p className="text-xs text-muted-foreground">{night.source}</p>
                        </div>
                        <div className="text-right">
                          <p className="font-semibold">{formatCurrency(night.rate)}</p>
                          {night.is_peak ? (
                            <p className="text-[11px] uppercase tracking-wider text-red-400">
                              Peak
                            </p>
                          ) : null}
                        </div>
                      </div>
                    ))}
                  </div>
                </div>

                <div className="rounded-lg border bg-muted/20 p-4">
                  <div className="flex items-center justify-between text-sm">
                    <span className="text-muted-foreground">Streamline Total</span>
                    <span className="font-medium">
                      {formatCurrency(
                        deterministicQuote.streamline_total ??
                          deterministicQuote.base_rent +
                            deterministicQuote.taxes +
                            deterministicQuote.fees,
                      )}
                    </span>
                  </div>
                  <div className="mt-2 flex items-center justify-between text-sm">
                    <span className="text-muted-foreground">Ancillary Total</span>
                    <span className="font-medium">
                      {formatCurrency(deterministicQuote.ancillary_total ?? 0)}
                    </span>
                  </div>
                  <div className="mt-3 flex items-center justify-between border-t pt-3">
                    <span className="font-semibold">Grand Total</span>
                    <span className="text-xl font-semibold">
                      {formatCurrency(
                        deterministicQuote.grand_total ??
                          deterministicQuote.total_amount,
                      )}
                    </span>
                  </div>
                </div>
              </>
            ) : (
              <div className="rounded-lg border border-dashed p-8 text-sm text-muted-foreground">
                Generate a deterministic quote to inspect live pricing, availability,
                and nightly composition before creating a checkout link.
              </div>
            )}
          </CardContent>
          <CardFooter className="border-t">
            <div className="flex w-full flex-col gap-3">
              <Button
                type="button"
                disabled={
                  !deterministicQuote ||
                  quoteEngine.isPending ||
                  deterministicQuote.availability_status !== "available"
                }
                onClick={handleCreateCheckoutQuote}
              >
                {quoteEngine.isPending ? (
                  <>
                    <Loader2 className="h-4 w-4 animate-spin" />
                    Waiting For Quote...
                  </>
                ) : (
                  <>
                    <ShieldCheck className="h-4 w-4" />
                    Create Checkout Quote
                  </>
                )}
              </Button>

              {checkoutQuote ? (
                <>
                  <div className="rounded-lg border bg-muted/20 p-4 text-sm">
                    <p className="font-medium">Checkout URL</p>
                    <p className="mt-2 break-all font-mono text-xs text-muted-foreground">
                      {checkoutQuote.checkout_url}
                    </p>
                  </div>

                  <Button
                    type="button"
                    variant="outline"
                    onClick={handleCopyCheckoutLink}
                  >
                    <Copy className="h-4 w-4" />
                    Copy Checkout Link
                  </Button>

                  <div className="grid gap-3 md:grid-cols-[minmax(0,1fr)_auto]">
                    <Input
                      type="email"
                      placeholder="Guest Email Address"
                      value={guestEmail}
                      onChange={(event) => setGuestEmail(event.target.value)}
                      disabled={isSendingQuote}
                    />
                    <Button
                      type="button"
                      disabled={isSendingQuote || !guestEmail.trim()}
                      onClick={handleSendQuote}
                    >
                      {isSendingQuote ? (
                        <>
                          <Loader2 className="h-4 w-4 animate-spin" />
                          Sending Quote...
                        </>
                      ) : (
                        <>
                          <Mail className="h-4 w-4" />
                          Send Quote to Guest
                        </>
                      )}
                    </Button>
                  </div>
                </>
              ) : (
                <p className="text-sm text-muted-foreground">
                  Once deterministic pricing is verified, create the checkout quote to
                  generate the direct-booking link and guest email payload.
                </p>
              )}
            </div>
          </CardFooter>
        </Card>
      </div>

      <StreamlineMasterCalendar
        calendar={calendar}
        isLoading={calendarLoading}
        selectedStart={checkIn || undefined}
        selectedEnd={checkOut || undefined}
        onSelectDay={handleSelectCalendarDay}
        onPreviousWindow={() => setViewStart((current) => shiftIsoDate(current, -14))}
        onNextWindow={() => setViewStart((current) => shiftIsoDate(current, 14))}
        onJumpToToday={() => setViewStart(buildDefaultDate(0))}
        onRefresh={handleRefreshCache}
        isRefreshing={refreshCache.isPending}
      />
    </div>
  );
}
