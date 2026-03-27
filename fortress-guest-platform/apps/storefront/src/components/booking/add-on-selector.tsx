"use client";

import { Badge } from "@/components/ui/badge";
import { Checkbox } from "@/components/ui/checkbox";
import { Separator } from "@/components/ui/separator";
import type { VrsAddOn } from "@/lib/types";

function formatCurrency(amount: number) {
  return new Intl.NumberFormat("en-US", {
    style: "currency",
    currency: "USD",
  }).format(amount);
}

function pricingModelLabel(model: VrsAddOn["pricing_model"]) {
  switch (model) {
    case "per_guest":
      return "Per Guest";
    case "per_night":
      return "Per Night";
    default:
      return "Flat Fee";
  }
}

interface AddOnSelectorProps {
  addOns: VrsAddOn[];
  selectedIds: string[];
  disabled?: boolean;
  onToggle: (addOnId: string, checked: boolean) => void;
}

export function AddOnSelector({
  addOns,
  selectedIds,
  disabled = false,
  onToggle,
}: AddOnSelectorProps) {
  if (addOns.length === 0) {
    return (
      <div className="rounded-lg border border-dashed p-4 text-sm text-muted-foreground">
        No active ancillary services are configured for this property yet.
      </div>
    );
  }

  return (
    <div className="rounded-xl border">
      <div className="space-y-1 px-4 py-4">
        <h3 className="font-semibold">Ancillary Services</h3>
        <p className="text-sm text-muted-foreground">
          Fortress-controlled add-ons stacked on top of the Streamline baseline.
        </p>
      </div>
      <Separator />
      <div className="space-y-3 px-4 py-4">
        {addOns.map((addOn) => {
          const checked = selectedIds.includes(addOn.id);
          const onCheckedChange = (next: boolean | "indeterminate") => {
            onToggle(addOn.id, next === true);
          };
          return (
            <label
              key={addOn.id}
              className="flex cursor-pointer items-start gap-3 rounded-lg border p-4 transition-colors hover:bg-accent/20"
            >
              <Checkbox
                checked={checked}
                onCheckedChange={onCheckedChange}
                disabled={disabled}
                className="mt-0.5"
              />
              <div className="min-w-0 flex-1 space-y-1">
                <div className="flex flex-wrap items-center gap-2">
                  <p className="font-medium">{addOn.name}</p>
                  <Badge variant="outline">{pricingModelLabel(addOn.pricing_model)}</Badge>
                </div>
                <p className="text-sm text-muted-foreground">{addOn.description}</p>
              </div>
              <div className="text-right">
                <p className="font-semibold">
                  {formatCurrency(Number.parseFloat(addOn.price))}
                </p>
              </div>
            </label>
          );
        })}
      </div>
    </div>
  );
}
