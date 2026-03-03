"use client";

import { useFieldArray, useFormContext, Controller } from "react-hook-form";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import { Plus, Trash2 } from "lucide-react";
import type { AutomationFormValues } from "@/lib/schemas/automations";

const OPERATORS = [
  { value: "eq", label: "equals" },
  { value: "neq", label: "not equals" },
  { value: "gt", label: "greater than" },
  { value: "lt", label: "less than" },
  { value: "contains", label: "contains" },
] as const;

const ENTITY_FIELDS: Record<string, string[]> = {
  reservation: [
    "status",
    "num_guests",
    "total_amount",
    "booking_source",
    "check_in_date",
    "check_out_date",
    "balance_due",
  ],
  work_order: ["status", "priority", "category", "assigned_to"],
  guest: ["total_stays", "language_preference", "opt_in_marketing"],
  message: ["direction", "intent", "sentiment", "is_auto_response"],
};

interface ConditionBuilderProps {
  targetEntity: string;
}

export function ConditionBuilder({ targetEntity }: ConditionBuilderProps) {
  const { control, register, setValue, watch } =
    useFormContext<AutomationFormValues>();

  const { fields, append, remove } = useFieldArray({
    control,
    name: "conditions.rules",
  });

  const boolOp = watch("conditions.operator");
  const availableFields = ENTITY_FIELDS[targetEntity] ?? [];

  return (
    <div className="space-y-3">
      <div className="flex items-center justify-end">
        <div className="flex items-center gap-1 rounded-md border p-0.5 text-xs">
          <button
            type="button"
            onClick={() => setValue("conditions.operator", "AND")}
            className={`rounded px-2 py-0.5 transition-colors ${
              boolOp === "AND"
                ? "bg-primary text-primary-foreground"
                : "text-muted-foreground hover:text-foreground"
            }`}
          >
            AND
          </button>
          <button
            type="button"
            onClick={() => setValue("conditions.operator", "OR")}
            className={`rounded px-2 py-0.5 transition-colors ${
              boolOp === "OR"
                ? "bg-primary text-primary-foreground"
                : "text-muted-foreground hover:text-foreground"
            }`}
          >
            OR
          </button>
        </div>
      </div>

      {fields.length === 0 && (
        <p className="text-xs text-muted-foreground italic">
          No conditions — rule will fire on every matching event.
        </p>
      )}

      {fields.map((field, index) => (
        <div key={field.id} className="flex items-end gap-2">
          <div className="flex-1 min-w-0">
            {index === 0 && (
              <Label className="text-xs text-muted-foreground">Field</Label>
            )}
            <Controller
              control={control}
              name={`conditions.rules.${index}.field`}
              render={({ field: fld }) => (
                <Select value={fld.value} onValueChange={fld.onChange}>
                  <SelectTrigger className="w-full">
                    <SelectValue placeholder="Field" />
                  </SelectTrigger>
                  <SelectContent>
                    {availableFields.map((f) => (
                      <SelectItem key={f} value={f}>
                        {f}
                      </SelectItem>
                    ))}
                  </SelectContent>
                </Select>
              )}
            />
          </div>

          <div className="w-32 shrink-0">
            {index === 0 && (
              <Label className="text-xs text-muted-foreground">Operator</Label>
            )}
            <Controller
              control={control}
              name={`conditions.rules.${index}.operator`}
              render={({ field: fld }) => (
                <Select value={fld.value} onValueChange={fld.onChange}>
                  <SelectTrigger className="w-full">
                    <SelectValue placeholder="Op" />
                  </SelectTrigger>
                  <SelectContent>
                    {OPERATORS.map((op) => (
                      <SelectItem key={op.value} value={op.value}>
                        {op.label}
                      </SelectItem>
                    ))}
                  </SelectContent>
                </Select>
              )}
            />
          </div>

          <div className="flex-1 min-w-0">
            {index === 0 && (
              <Label className="text-xs text-muted-foreground">Value</Label>
            )}
            <Input
              placeholder="Value"
              {...register(`conditions.rules.${index}.value`)}
            />
          </div>

          <Button
            type="button"
            variant="ghost"
            size="icon"
            className="h-9 w-9 shrink-0 text-muted-foreground hover:text-destructive"
            onClick={() => remove(index)}
          >
            <Trash2 className="h-4 w-4" />
          </Button>
        </div>
      ))}

      <Button
        type="button"
        variant="outline"
        size="sm"
        className="w-full"
        onClick={() => append({ field: "", operator: "eq", value: "" })}
      >
        <Plus className="mr-1 h-3 w-3" />
        Add Condition
      </Button>
    </div>
  );
}
