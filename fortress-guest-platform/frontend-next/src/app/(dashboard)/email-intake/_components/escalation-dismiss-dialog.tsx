"use client";

import { useState } from "react";
import { Button } from "@/components/ui/button";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";
import { Textarea } from "@/components/ui/textarea";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import type { EmailIntakeEscalationItem, EmailIntakeMetadataResponse } from "@/lib/types";

type Props = {
  open: boolean;
  item?: EmailIntakeEscalationItem | null;
  metadata?: EmailIntakeMetadataResponse;
  onOpenChange: (open: boolean) => void;
  onSubmit: (payload: { status: "dismissed"; dismiss_reason: string; note?: string }) => void;
};

export function EscalationDismissDialog({
  open,
  item,
  metadata,
  onOpenChange,
  onSubmit,
}: Props) {
  const reasons = metadata?.dismiss_reasons ?? {
    classification_correct: "Classification is correct - no action needed",
  };
  const [reason, setReason] = useState(Object.keys(reasons)[0] ?? "classification_correct");
  const [note, setNote] = useState("");

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent>
        <DialogHeader>
          <DialogTitle>Dismiss Escalation</DialogTitle>
          <DialogDescription>
            Escalation #{item?.id} · {item?.subject}
          </DialogDescription>
        </DialogHeader>

        <div className="space-y-3">
          <Select value={reason} onValueChange={setReason}>
            <SelectTrigger>
              <SelectValue placeholder="Dismiss reason" />
            </SelectTrigger>
            <SelectContent>
              {Object.entries(reasons).map(([key, label]) => (
                <SelectItem key={key} value={key}>
                  {label}
                </SelectItem>
              ))}
            </SelectContent>
          </Select>

          <Textarea
            placeholder="Additional context (optional)"
            value={note}
            onChange={(e) => setNote(e.target.value)}
          />
        </div>

        <DialogFooter>
          <Button variant="outline" onClick={() => onOpenChange(false)}>
            Cancel
          </Button>
          <Button
            variant="destructive"
            onClick={() => {
              onSubmit({ status: "dismissed", dismiss_reason: reason, note: note || undefined });
              onOpenChange(false);
              setNote("");
            }}
          >
            Confirm Dismiss
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}

