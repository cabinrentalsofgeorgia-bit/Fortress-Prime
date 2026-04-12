import { ShieldCheck } from "lucide-react";

function formatCurrency(amount: number): string {
  return new Intl.NumberFormat("en-US", {
    style: "currency",
    currency: "USD",
  }).format(amount);
}

interface QuotePricingBreakdownProps {
  baseRent: number;
  taxes: number;
  fees: number;
  totalAmount: number;
  nights: number | null;
}

export function QuotePricingBreakdown({
  baseRent,
  taxes,
  fees,
  totalAmount,
  nights,
}: QuotePricingBreakdownProps) {
  const rentLabel = nights ? `Cabin rental · ${nights} night${nights !== 1 ? "s" : ""}` : "Cabin rental";

  return (
    <div>
      <div className="space-y-3 text-sm text-slate-700">
        <div className="flex items-center justify-between">
          <span>{rentLabel}</span>
          <span className="font-medium text-slate-900">{formatCurrency(baseRent)}</span>
        </div>

        {fees > 0 && (
          <div className="flex items-center justify-between">
            <span>Cleaning &amp; service fees</span>
            <span className="font-medium text-slate-900">{formatCurrency(fees)}</span>
          </div>
        )}

        {taxes > 0 && (
          <div className="flex items-center justify-between">
            <span>Local taxes</span>
            <span className="font-medium text-slate-900">{formatCurrency(taxes)}</span>
          </div>
        )}

        <div className="h-px bg-slate-200" />

        <div className="flex items-center justify-between text-base font-semibold text-slate-900">
          <span>Total</span>
          <span>{formatCurrency(totalAmount)}</span>
        </div>
      </div>

      <div className="mt-4 inline-flex items-center gap-1.5 text-xs font-medium uppercase tracking-[0.18em] text-emerald-700">
        <ShieldCheck className="h-3.5 w-3.5" />
        Ledger verified
      </div>
    </div>
  );
}
