"use client";

import { useEffect, useState } from "react";
import {
  CardNumberElement,
  CardExpiryElement,
  CardCvcElement,
  Elements,
  useElements,
  useStripe,
} from "@stripe/react-stripe-js";
import { loadStripe, type Stripe } from "@stripe/stripe-js";
import { api } from "@/lib/api";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { toast } from "sonner";

const ELEMENT_OPTIONS = {
  style: {
    base: {
      fontSize: "16px",
      color: "#0f172a",
      fontFamily:
        'ui-sans-serif, system-ui, -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif',
      "::placeholder": { color: "#64748b" },
    },
  },
};

type ConfirmResponse = {
  reservation_id: string;
  confirmation_code: string;
  total_amount: number;
};

function PayForm({
  clientSecret,
  holdId,
  totalAmount,
  defaultName,
  onConfirmed,
}: {
  clientSecret: string;
  holdId: string;
  totalAmount: number;
  defaultName: string;
  onConfirmed: (c: ConfirmResponse) => void;
}) {
  const stripe = useStripe();
  const elements = useElements();
  const [processing, setProcessing] = useState(false);
  const [cardholderName, setCardholderName] = useState(defaultName);

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!stripe || !elements) return;
    const cardNumber = elements.getElement(CardNumberElement);
    if (!cardNumber) return;

    setProcessing(true);
    try {
      const { error, paymentIntent } = await stripe.confirmCardPayment(clientSecret, {
        payment_method: {
          card: cardNumber,
          billing_details: { name: cardholderName || undefined },
        },
      });

      if (error) {
        toast.error(error.message || "Payment failed");
        return;
      }
      if (paymentIntent?.status !== "succeeded") {
        toast.warning(`Payment status: ${paymentIntent?.status ?? "unknown"}`);
        return;
      }

      const confirmed = await api.post<ConfirmResponse>("/api/direct-booking/confirm-hold", {
        hold_id: holdId,
      });
      onConfirmed(confirmed);
      toast.success("Booking confirmed");
    } catch (err) {
      const message = err instanceof Error ? err.message : "Confirmation failed";
      toast.error(message);
    } finally {
      setProcessing(false);
    }
  };

  return (
    <form onSubmit={handleSubmit} className="space-y-4">
      <p className="text-sm text-slate-600">
        Total due: <span className="font-semibold text-slate-900">${totalAmount.toFixed(2)}</span>
      </p>
      <div className="space-y-2">
        <Label htmlFor="cardholder" className="text-slate-800">Name on card</Label>
        <Input
          id="cardholder"
          value={cardholderName}
          onChange={(e) => setCardholderName(e.target.value)}
          autoComplete="cc-name"
          className="border-slate-300 bg-white text-slate-900"
        />
      </div>
      <div className="space-y-2">
        <Label className="text-slate-800">Card number</Label>
        <div className="rounded-md border border-slate-300 bg-white px-3 py-3">
          <CardNumberElement options={ELEMENT_OPTIONS} />
        </div>
      </div>
      <div className="grid grid-cols-2 gap-4">
        <div className="space-y-2">
          <Label className="text-slate-800">Expiry</Label>
          <div className="rounded-md border border-slate-300 bg-white px-3 py-3">
            <CardExpiryElement options={ELEMENT_OPTIONS} />
          </div>
        </div>
        <div className="space-y-2">
          <Label className="text-slate-800">CVC</Label>
          <div className="rounded-md border border-slate-300 bg-white px-3 py-3">
            <CardCvcElement options={ELEMENT_OPTIONS} />
          </div>
        </div>
      </div>
      <Button
        type="submit"
        className="w-full bg-slate-900 text-white hover:bg-black"
        disabled={!stripe || processing}
      >
        {processing ? "Processing…" : "Pay and confirm"}
      </Button>
    </form>
  );
}

export function DirectBookingPayPanel({
  publishableKey,
  clientSecret,
  holdId,
  totalAmount,
  defaultCardholderName,
  onConfirmed,
}: {
  publishableKey: string;
  clientSecret: string;
  holdId: string;
  totalAmount: number;
  defaultCardholderName: string;
  onConfirmed: (c: ConfirmResponse) => void;
}) {
  const [stripePromise, setStripePromise] = useState<Promise<Stripe | null> | null>(null);

  useEffect(() => {
    if (publishableKey) {
      setStripePromise(loadStripe(publishableKey));
    }
  }, [publishableKey]);

  if (!publishableKey) {
    return (
      <p className="text-sm text-rose-700">
        Payments are not configured (missing Stripe publishable key).
      </p>
    );
  }

  if (!stripePromise) {
    return <p className="text-sm text-slate-600">Loading secure checkout…</p>;
  }

  return (
    <Elements stripe={stripePromise} options={{ clientSecret }}>
      <PayForm
        clientSecret={clientSecret}
        holdId={holdId}
        totalAmount={totalAmount}
        defaultName={defaultCardholderName}
        onConfirmed={onConfirmed}
      />
    </Elements>
  );
}
