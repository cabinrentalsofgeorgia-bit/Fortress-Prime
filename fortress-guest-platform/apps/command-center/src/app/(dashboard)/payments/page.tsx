"use client";

import { useState, useCallback, useEffect } from "react";
import { api } from "@/lib/api";
import { RoleGatedAction } from "@/components/access/role-gated-action";
import { useAppStore } from "@/lib/store";
import { canManagePayments } from "@/lib/roles";
import { toast } from "sonner";
import { loadStripe, type Stripe } from "@stripe/stripe-js";
import {
  Elements,
  CardNumberElement,
  CardExpiryElement,
  CardCvcElement,
  useStripe,
  useElements,
} from "@stripe/react-stripe-js";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import {
  Card,
  CardContent,
  CardHeader,
  CardTitle,
  CardDescription,
} from "@/components/ui/card";
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@/components/ui/table";
import { Separator } from "@/components/ui/separator";
import { ScrollArea } from "@/components/ui/scroll-area";
import {
  CreditCard,
  Search,
  Phone,
  ShieldCheck,
  DollarSign,
  Loader2,
  Receipt,
  Lock,
} from "lucide-react";

interface ReservationResult {
  id: string;
  confirmation_code: string;
  guest_name: string;
  property_name: string;
  check_in: string;
  check_out: string;
  total_amount: string;
  paid_amount: string;
  balance_due: string;
  status: string;
}

interface MOTOIntentResponse {
  payment_intent_id: string;
  client_secret: string;
  amount_cents: number;
  reservation_id: string;
  confirmation_code: string;
  guest_name: string;
  property_name: string;
}

interface PaymentEvent {
  id: string;
  event_type: string;
  data: Record<string, unknown> | string;
  created_at: string;
}

const ELEMENT_OPTIONS = {
  style: {
    base: {
      fontSize: "16px",
      color: "#fff",
      fontFamily: "Inter, system-ui, sans-serif",
      "::placeholder": { color: "#6b7280" },
    },
    invalid: { color: "#ef4444" },
  },
};

function CardForm({
  clientSecret,
  intentMeta,
  onSuccess,
  onCancel,
  canOperate,
}: {
  clientSecret: string;
  intentMeta: MOTOIntentResponse;
  onSuccess: () => void;
  onCancel: () => void;
  canOperate: boolean;
}) {
  const stripe = useStripe();
  const elements = useElements();
  const [processing, setProcessing] = useState(false);
  const [cardholderName, setCardholderName] = useState("");

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!stripe || !elements) return;

    const cardNumber = elements.getElement(CardNumberElement);
    if (!cardNumber) return;

    setProcessing(true);
    try {
      const { error, paymentIntent } = await stripe.confirmCardPayment(
        clientSecret,
        {
          payment_method: {
            card: cardNumber,
            billing_details: { name: cardholderName || undefined },
          },
        }
      );

      if (error) {
        toast.error(error.message || "Payment failed");
      } else if (paymentIntent?.status === "succeeded") {
        toast.success(
          `Payment of $${(intentMeta.amount_cents / 100).toFixed(2)} succeeded`
        );
        onSuccess();
      } else {
        toast.warning(`Payment status: ${paymentIntent?.status}`);
      }
    } catch {
      toast.error("Payment processing error");
    } finally {
      setProcessing(false);
    }
  };

  return (
    <form onSubmit={handleSubmit} className="space-y-6">
      <div className="rounded-lg border border-emerald-500/20 bg-emerald-500/5 p-4">
        <div className="flex items-center justify-between">
          <div>
            <p className="text-sm text-muted-foreground">Charging</p>
            <p className="text-2xl font-bold text-emerald-400">
              ${(intentMeta.amount_cents / 100).toFixed(2)}
            </p>
          </div>
          <div className="text-right">
            <p className="text-sm font-medium">{intentMeta.guest_name}</p>
            <p className="text-xs text-muted-foreground">
              {intentMeta.confirmation_code} &mdash; {intentMeta.property_name}
            </p>
          </div>
        </div>
      </div>

      <div className="space-y-4">
        <div>
          <Label htmlFor="cardholder">Cardholder Name</Label>
          <Input
            id="cardholder"
            placeholder="Name on card"
            value={cardholderName}
            onChange={(e) => setCardholderName(e.target.value)}
            className="mt-1"
          />
        </div>

        <div>
          <Label>Card Number</Label>
          <div className="mt-1 rounded-md border border-input bg-background px-3 py-3">
            <CardNumberElement options={ELEMENT_OPTIONS} />
          </div>
        </div>

        <div className="grid grid-cols-2 gap-4">
          <div>
            <Label>Expiry</Label>
            <div className="mt-1 rounded-md border border-input bg-background px-3 py-3">
              <CardExpiryElement options={ELEMENT_OPTIONS} />
            </div>
          </div>
          <div>
            <Label>CVC</Label>
            <div className="mt-1 rounded-md border border-input bg-background px-3 py-3">
              <CardCvcElement options={ELEMENT_OPTIONS} />
            </div>
          </div>
        </div>
      </div>

      <div className="flex items-start gap-2 rounded-md border border-yellow-500/20 bg-yellow-500/5 p-3">
        <ShieldCheck className="mt-0.5 h-4 w-4 text-yellow-400 shrink-0" />
        <p className="text-xs text-yellow-200/80">
          MOTO transaction &mdash; cardholder not present. This charge bypasses
          3D Secure. You are responsible for verifying the caller&apos;s identity
          before processing.
        </p>
      </div>

      <div className="flex gap-3">
        <RoleGatedAction allowed={canOperate} reason="Manager or admin role required.">
          <Button
            type="submit"
            disabled={!canOperate || processing || !stripe}
            className="flex-1 bg-emerald-600 hover:bg-emerald-700"
          >
            {processing ? (
              <>
                <Loader2 className="mr-2 h-4 w-4 animate-spin" />
                Processing...
              </>
            ) : (
              <>
                <Lock className="mr-2 h-4 w-4" />
                Charge ${(intentMeta.amount_cents / 100).toFixed(2)}
              </>
            )}
          </Button>
        </RoleGatedAction>
        <Button type="button" variant="outline" onClick={onCancel}>
          Cancel
        </Button>
      </div>
    </form>
  );
}

function formatMoney(v: string | number) {
  const n = typeof v === "string" ? parseFloat(v) : v;
  if (isNaN(n)) return "\u2013";
  return `$${n.toLocaleString("en-US", {
    minimumFractionDigits: 2,
    maximumFractionDigits: 2,
  })}`;
}

export default function PaymentsPage() {
  const user = useAppStore((state) => state.user);
  const canOperate = canManagePayments(user);
  const [stripePromise, setStripePromise] =
    useState<Promise<Stripe | null> | null>(null);

  const [searchQuery, setSearchQuery] = useState("");
  const [searching, setSearching] = useState(false);
  const [results, setResults] = useState<ReservationResult[]>([]);

  const [selected, setSelected] = useState<ReservationResult | null>(null);
  const [chargeAmount, setChargeAmount] = useState("");
  const [chargeDescription, setChargeDescription] = useState("");

  const [clientSecret, setClientSecret] = useState<string | null>(null);
  const [intentMeta, setIntentMeta] = useState<MOTOIntentResponse | null>(null);
  const [creatingIntent, setCreatingIntent] = useState(false);

  const [history, setHistory] = useState<PaymentEvent[]>([]);
  const [historyLoading, setHistoryLoading] = useState(false);

  const loadHistory = useCallback(async () => {
    setHistoryLoading(true);
    try {
      const resp = await api.get<{
        data: PaymentEvent[];
        pagination: { total: number };
      }>("/api/payments/history");
      setHistory(resp.data);
    } catch {
      /* empty */
    } finally {
      setHistoryLoading(false);
    }
  }, []);

  useEffect(() => {
    api
      .get<{ publishable_key: string }>("/api/payments/stripe-key")
      .then(({ publishable_key }) => {
        if (publishable_key) setStripePromise(loadStripe(publishable_key));
      })
      .catch(() => {});

    loadHistory();
  }, [loadHistory]);

  const searchReservations = useCallback(async () => {
    if (!searchQuery.trim()) return;
    setSearching(true);
    try {
      const data = await api.get<ReservationResult[]>(
        "/api/payments/search-reservations",
        { q: searchQuery }
      );
      setResults(data);
      if (data.length === 0) toast.info("No reservations found");
    } catch {
      toast.error("Search failed");
    } finally {
      setSearching(false);
    }
  }, [searchQuery]);

  const selectReservation = (r: ReservationResult) => {
    setSelected(r);
    const balance = parseFloat(r.balance_due);
    setChargeAmount(balance > 0 ? balance.toFixed(2) : "");
    setChargeDescription(`Payment for ${r.confirmation_code}`);
    setClientSecret(null);
    setIntentMeta(null);
  };

  const createIntent = async () => {
    if (!selected || !chargeAmount) return;
    const amount = parseFloat(chargeAmount);
    if (isNaN(amount) || amount <= 0) {
      toast.error("Enter a valid amount");
      return;
    }

    setCreatingIntent(true);
    try {
      const resp = await api.post<MOTOIntentResponse>(
        "/api/payments/moto/create-intent",
        {
          reservation_id: selected.id,
          amount: amount.toFixed(2),
          description: chargeDescription || undefined,
        }
      );
      setClientSecret(resp.client_secret);
      setIntentMeta(resp);
      toast.success("Payment intent created \u2014 enter card details");
    } catch (err: unknown) {
      const msg =
        err instanceof Error ? err.message : "Failed to create payment intent";
      toast.error(msg);
    } finally {
      setCreatingIntent(false);
    }
  };

  const handlePaymentSuccess = () => {
    setClientSecret(null);
    setIntentMeta(null);
    setSelected(null);
    setResults([]);
    setSearchQuery("");
    loadHistory();
  };

  const handleCancel = () => {
    setClientSecret(null);
    setIntentMeta(null);
  };

  return (
    <div className="mx-auto max-w-7xl space-y-6">
      <div className="flex items-center justify-between">
        <div>
          <h1 className="text-2xl font-bold tracking-tight flex items-center gap-2">
            <Phone className="h-6 w-6 text-emerald-400" />
            Virtual Terminal
          </h1>
          <p className="text-sm text-muted-foreground mt-1">
            MOTO payment processing &mdash; phone &amp; mail orders
          </p>
          {!canOperate ? (
            <Badge variant="outline" className="mt-2 text-xs">
              View-only role
            </Badge>
          ) : null}
        </div>
        <Badge
          variant="outline"
          className="border-emerald-500/30 text-emerald-400"
        >
          <ShieldCheck className="mr-1 h-3 w-3" />
          PCI Compliant
        </Badge>
      </div>

      <div className="grid grid-cols-1 lg:grid-cols-3 gap-6">
        <div className="lg:col-span-2 space-y-4">
          <Card>
            <CardHeader className="pb-3">
              <CardTitle className="text-base flex items-center gap-2">
                <Search className="h-4 w-4" />
                Find Reservation
              </CardTitle>
              <CardDescription>
                Search by confirmation code, guest name, or property
              </CardDescription>
            </CardHeader>
            <CardContent>
              <div className="flex gap-2">
                <Input
                  placeholder="e.g. SC-12345 or John Smith"
                  value={searchQuery}
                  onChange={(e) => setSearchQuery(e.target.value)}
                  onKeyDown={(e) => e.key === "Enter" && searchReservations()}
                />
                <Button
                  onClick={searchReservations}
                  disabled={searching || !searchQuery.trim()}
                >
                  {searching ? (
                    <Loader2 className="h-4 w-4 animate-spin" />
                  ) : (
                    "Search"
                  )}
                </Button>
              </div>

              {results.length > 0 && (
                <ScrollArea className="mt-4 max-h-[320px]">
                  <Table>
                    <TableHeader>
                      <TableRow>
                        <TableHead>Code</TableHead>
                        <TableHead>Guest</TableHead>
                        <TableHead>Property</TableHead>
                        <TableHead>Dates</TableHead>
                        <TableHead className="text-right">Balance</TableHead>
                        <TableHead />
                      </TableRow>
                    </TableHeader>
                    <TableBody>
                      {results.map((r) => (
                        <TableRow
                          key={r.id}
                          className={
                            selected?.id === r.id
                              ? "bg-emerald-500/10"
                              : "cursor-pointer hover:bg-muted/50"
                          }
                          onClick={() => selectReservation(r)}
                        >
                          <TableCell className="font-mono text-xs">
                            {r.confirmation_code}
                          </TableCell>
                          <TableCell>{r.guest_name}</TableCell>
                          <TableCell className="max-w-[140px] truncate">
                            {r.property_name}
                          </TableCell>
                          <TableCell className="text-xs">
                            {r.check_in} &rarr; {r.check_out}
                          </TableCell>
                          <TableCell className="text-right font-medium">
                            {parseFloat(r.balance_due) > 0 ? (
                              <span className="text-amber-400">
                                {formatMoney(r.balance_due)}
                              </span>
                            ) : (
                              <span className="text-emerald-400">Paid</span>
                            )}
                          </TableCell>
                          <TableCell>
                            <Button
                              size="sm"
                              variant="ghost"
                              onClick={(e) => {
                                e.stopPropagation();
                                selectReservation(r);
                              }}
                            >
                              Select
                            </Button>
                          </TableCell>
                        </TableRow>
                      ))}
                    </TableBody>
                  </Table>
                </ScrollArea>
              )}
            </CardContent>
          </Card>

          <Card>
            <CardHeader className="pb-3">
              <CardTitle className="text-base flex items-center gap-2">
                <Receipt className="h-4 w-4" />
                Recent MOTO Transactions
              </CardTitle>
            </CardHeader>
            <CardContent>
              {historyLoading ? (
                <div className="flex items-center justify-center py-8">
                  <Loader2 className="h-5 w-5 animate-spin text-muted-foreground" />
                </div>
              ) : history.length === 0 ? (
                <p className="text-sm text-muted-foreground text-center py-6">
                  No MOTO transactions yet
                </p>
              ) : (
                <ScrollArea className="max-h-[280px]">
                  <Table>
                    <TableHeader>
                      <TableRow>
                        <TableHead>Event</TableHead>
                        <TableHead>Details</TableHead>
                        <TableHead>Time</TableHead>
                      </TableRow>
                    </TableHeader>
                    <TableBody>
                      {history.map((h) => {
                        const d =
                          typeof h.data === "string"
                            ? JSON.parse(h.data)
                            : h.data;
                        return (
                          <TableRow key={h.id}>
                            <TableCell>
                              <Badge
                                variant={
                                  h.event_type.includes("succeeded")
                                    ? "default"
                                    : "outline"
                                }
                              >
                                {h.event_type.replace("moto_", "")}
                              </Badge>
                            </TableCell>
                            <TableCell className="text-xs">
                              {d?.confirmation_code} &mdash; {d?.guest_name}
                              {d?.amount_cents && (
                                <span className="ml-2 font-medium">
                                  {formatMoney(Number(d.amount_cents) / 100)}
                                </span>
                              )}
                            </TableCell>
                            <TableCell className="text-xs text-muted-foreground">
                              {new Date(h.created_at).toLocaleString()}
                            </TableCell>
                          </TableRow>
                        );
                      })}
                    </TableBody>
                  </Table>
                </ScrollArea>
              )}
            </CardContent>
          </Card>
        </div>

        <div className="space-y-4">
          <Card className="border-emerald-500/20">
            <CardHeader className="pb-3">
              <CardTitle className="text-base flex items-center gap-2">
                <CreditCard className="h-4 w-4 text-emerald-400" />
                Charge Card
              </CardTitle>
            </CardHeader>
            <CardContent>
              {!selected ? (
                <div className="text-center py-12">
                  <DollarSign className="mx-auto h-10 w-10 text-muted-foreground/30" />
                  <p className="mt-3 text-sm text-muted-foreground">
                    Search and select a reservation to begin
                  </p>
                </div>
              ) : clientSecret && intentMeta && stripePromise ? (
                <Elements stripe={stripePromise} options={{ clientSecret }}>
                  <CardForm
                    clientSecret={clientSecret}
                    intentMeta={intentMeta}
                    onSuccess={handlePaymentSuccess}
                    onCancel={handleCancel}
                    canOperate={canOperate}
                  />
                </Elements>
              ) : (
                <div className="space-y-4">
                  <div className="rounded-lg border bg-muted/30 p-3 space-y-2">
                    <div className="flex justify-between">
                      <span className="text-sm text-muted-foreground">Reservation</span>
                      <span className="text-sm font-mono">{selected.confirmation_code}</span>
                    </div>
                    <div className="flex justify-between">
                      <span className="text-sm text-muted-foreground">Guest</span>
                      <span className="text-sm">{selected.guest_name}</span>
                    </div>
                    <div className="flex justify-between">
                      <span className="text-sm text-muted-foreground">Property</span>
                      <span className="text-sm truncate ml-4 max-w-[160px]">{selected.property_name}</span>
                    </div>
                    <Separator />
                    <div className="flex justify-between">
                      <span className="text-sm text-muted-foreground">Total</span>
                      <span className="text-sm">{formatMoney(selected.total_amount)}</span>
                    </div>
                    <div className="flex justify-between">
                      <span className="text-sm text-muted-foreground">Paid</span>
                      <span className="text-sm text-emerald-400">{formatMoney(selected.paid_amount)}</span>
                    </div>
                    <div className="flex justify-between font-medium">
                      <span className="text-sm">Balance Due</span>
                      <span className={`text-sm ${parseFloat(selected.balance_due) > 0 ? "text-amber-400" : "text-emerald-400"}`}>
                        {formatMoney(selected.balance_due)}
                      </span>
                    </div>
                  </div>

                  <div>
                    <Label htmlFor="amount">Charge Amount (USD)</Label>
                    <div className="relative mt-1">
                      <span className="absolute left-3 top-1/2 -translate-y-1/2 text-muted-foreground">$</span>
                      <Input
                        id="amount"
                        type="number"
                        step="0.01"
                        min="0.50"
                        max="999999.99"
                        placeholder="0.00"
                        value={chargeAmount}
                        onChange={(e) => setChargeAmount(e.target.value)}
                        className="pl-7"
                      />
                    </div>
                  </div>

                  <div>
                    <Label htmlFor="desc">Description (optional)</Label>
                    <Input
                      id="desc"
                      placeholder="e.g. Remaining balance"
                      value={chargeDescription}
                      onChange={(e) => setChargeDescription(e.target.value)}
                      className="mt-1"
                    />
                  </div>

                  <RoleGatedAction allowed={canOperate} reason="Manager or admin role required.">
                    <Button
                      onClick={createIntent}
                      disabled={!canOperate || creatingIntent || !chargeAmount || parseFloat(chargeAmount) <= 0}
                      className="w-full bg-emerald-600 hover:bg-emerald-700"
                    >
                      {creatingIntent ? (
                        <>
                          <Loader2 className="mr-2 h-4 w-4 animate-spin" />
                          Creating...
                        </>
                      ) : (
                        <>
                          <CreditCard className="mr-2 h-4 w-4" />
                          Enter Card Details
                        </>
                      )}
                    </Button>
                  </RoleGatedAction>

                  <Button variant="ghost" className="w-full" onClick={() => setSelected(null)}>
                    Clear Selection
                  </Button>
                </div>
              )}
            </CardContent>
          </Card>

          <Card className="border-blue-500/20">
            <CardContent className="pt-4">
              <div className="flex items-start gap-3">
                <ShieldCheck className="h-5 w-5 text-blue-400 shrink-0 mt-0.5" />
                <div>
                  <p className="text-sm font-medium">SOC2 Audit Trail</p>
                  <p className="text-xs text-muted-foreground mt-1">
                    Every MOTO transaction is logged with staff identity, timestamp, and reservation
                    context. Card data never touches our servers &mdash; Stripe Elements handles
                    PCI-DSS compliance.
                  </p>
                </div>
              </div>
            </CardContent>
          </Card>
        </div>
      </div>
    </div>
  );
}
