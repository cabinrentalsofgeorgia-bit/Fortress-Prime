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
import type { EmailIntakeEscalationItem } from "@/lib/types";

type Props = {
  open: boolean;
  item?: EmailIntakeEscalationItem | null;
  onOpenChange: (open: boolean) => void;
  onSubmit: (payload: { status: "snoozed"; snooze_hours: number; note?: string }) => void;
};

export function EscalationSnoozeDialog({ open, item, onOpenChange, onSubmit }: Props) {
  const [hours, setHours] = useState("24");
  const [note, setNote] = useState("");

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent>
        <DialogHeader>
          <DialogTitle>Snooze Escalation</DialogTitle>
          <DialogDescription>
            Escalation #{item?.id} · {item?.subject}
          </DialogDescription>
        </DialogHeader>

        <div className="space-y-3">
          <Select value={hours} onValueChange={setHours}>
            <SelectTrigger>
              <SelectValue placeholder="Duration" />
            </SelectTrigger>
            <SelectContent>
              <SelectItem value="1">1 hour</SelectItem>
              <SelectItem value="4">4 hours</SelectItem>
              <SelectItem value="8">8 hours</SelectItem>
              <SelectItem value="24">24 hours</SelectItem>
              <SelectItem value="48">48 hours</SelectItem>
              <SelectItem value="72">72 hours</SelectItem>
              <SelectItem value="168">1 week</SelectItem>
            </SelectContent>
          </Select>

          <Textarea
            placeholder="Reminder note (optional)"
            value={note}
            onChange={(e) => setNote(e.target.value)}
          />
        </div>

        <DialogFooter>
          <Button variant="outline" onClick={() => onOpenChange(false)}>
            Cancel
          </Button>
          <Button
            onClick={() => {
              onSubmit({ status: "snoozed", snooze_hours: Number(hours), note: note || undefined });
              onOpenChange(false);
              setNote("");
            }}
          >
            Snooze
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}

