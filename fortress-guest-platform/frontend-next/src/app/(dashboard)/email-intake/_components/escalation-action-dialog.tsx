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
import { Input } from "@/components/ui/input";
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
  onSubmit: (payload: {
    status: "actioned";
    action_type: string;
    delegate_to?: string;
    follow_up_date?: string | null;
    note?: string;
  }) => void;
};

export function EscalationActionDialog({
  open,
  item,
  metadata,
  onOpenChange,
  onSubmit,
}: Props) {
  const [actionType, setActionType] = useState("other");
  const [delegateTo, setDelegateTo] = useState("");
  const [followUpDate, setFollowUpDate] = useState("");
  const [note, setNote] = useState("");

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent>
        <DialogHeader>
          <DialogTitle>Action Taken</DialogTitle>
          <DialogDescription>
            Escalation #{item?.id} · {item?.subject}
          </DialogDescription>
        </DialogHeader>

        <div className="space-y-3">
          <Select value={actionType} onValueChange={setActionType}>
            <SelectTrigger>
              <SelectValue placeholder="Action type" />
            </SelectTrigger>
            <SelectContent>
              {Object.entries(metadata?.action_types ?? { other: "Other" }).map(([key, label]) => (
                <SelectItem key={key} value={key}>
                  {label}
                </SelectItem>
              ))}
            </SelectContent>
          </Select>

          <Input
            placeholder="Delegate to (optional)"
            value={delegateTo}
            onChange={(e) => setDelegateTo(e.target.value)}
          />
          <Input
            type="date"
            value={followUpDate}
            onChange={(e) => setFollowUpDate(e.target.value)}
          />
          <Textarea
            placeholder="Notes"
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
              onSubmit({
                status: "actioned",
                action_type: actionType,
                delegate_to: delegateTo || undefined,
                follow_up_date: followUpDate || null,
                note: note || undefined,
              });
              onOpenChange(false);
              setDelegateTo("");
              setFollowUpDate("");
              setNote("");
            }}
          >
            Confirm Action
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}

