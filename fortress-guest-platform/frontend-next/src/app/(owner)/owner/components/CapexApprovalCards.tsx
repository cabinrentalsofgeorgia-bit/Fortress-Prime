"use client";

import { useState } from "react";
import {
  AlertTriangle,
  CheckCircle2,
  XCircle,
  Wrench,
  DollarSign,
  Clock,
} from "lucide-react";
import { useCapexPending, useApproveCapex, useRejectCapex } from "@/lib/hooks";
import { Button } from "@/components/ui/button";
import {
  Dialog,
  DialogContent,
  DialogHeader,
  DialogTitle,
  DialogDescription,
  DialogFooter,
} from "@/components/ui/dialog";
import { Input } from "@/components/ui/input";

interface Props {
  propertyId: string;
}

export function CapexApprovalCards({ propertyId }: Props) {
  const { data, isLoading } = useCapexPending(propertyId);
  const approveMutation = useApproveCapex(propertyId);
  const rejectMutation = useRejectCapex(propertyId);

  const [rejectDialog, setRejectDialog] = useState<number | null>(null);
  const [rejectReason, setRejectReason] = useState("");

  const pending = data?.pending ?? [];

  if (isLoading) {
    return (
      <div className="animate-pulse space-y-3">
        {[1, 2].map((i) => (
          <div key={i} className="h-24 bg-slate-800 rounded-lg" />
        ))}
      </div>
    );
  }

  if (pending.length === 0) {
    return (
      <div className="flex items-center gap-2 text-slate-500 text-sm p-4 border border-slate-800 rounded-lg">
        <CheckCircle2 className="h-4 w-4 text-green-500" />
        No pending CapEx approvals
      </div>
    );
  }

  return (
    <div className="space-y-3">
      <div className="flex items-center gap-2 mb-2">
        <AlertTriangle className="h-4 w-4 text-amber-500" />
        <span className="text-sm font-medium text-amber-400">
          {pending.length} invoice{pending.length > 1 ? "s" : ""} awaiting your approval
        </span>
      </div>

      {pending.map((item) => (
        <div
          key={item.id}
          className="border border-amber-900/50 bg-amber-950/20 rounded-lg p-4 space-y-3"
        >
          <div className="flex items-start justify-between">
            <div className="flex items-center gap-3">
              <div className="w-10 h-10 rounded-full bg-amber-900/30 flex items-center justify-center">
                <Wrench className="h-5 w-5 text-amber-400" />
              </div>
              <div>
                <p className="font-medium text-white">{item.vendor}</p>
                <p className="text-xs text-slate-400">{item.description || "Maintenance invoice"}</p>
              </div>
            </div>
            <div className="text-right">
              <p className="text-lg font-mono font-bold text-amber-400 flex items-center gap-1">
                <DollarSign className="h-4 w-4" />
                {item.total_owner_charge.toLocaleString("en-US", {
                  minimumFractionDigits: 2,
                  maximumFractionDigits: 2,
                })}
              </p>
              {item.created_at && (
                <p className="text-xs text-slate-500 flex items-center gap-1 justify-end mt-1">
                  <Clock className="h-3 w-3" />
                  {new Date(item.created_at).toLocaleDateString()}
                </p>
              )}
            </div>
          </div>

          <div className="flex gap-2 justify-end">
            <Button
              variant="outline"
              size="sm"
              className="border-red-800 text-red-400 hover:bg-red-950"
              onClick={() => {
                setRejectReason("");
                setRejectDialog(item.id);
              }}
              disabled={rejectMutation.isPending}
            >
              <XCircle className="h-4 w-4 mr-1" />
              Reject
            </Button>
            <Button
              size="sm"
              className="bg-green-700 hover:bg-green-600 text-white"
              onClick={() => approveMutation.mutate(item.id)}
              disabled={approveMutation.isPending}
            >
              <CheckCircle2 className="h-4 w-4 mr-1" />
              {approveMutation.isPending ? "Committing..." : "Authorize Dispatch"}
            </Button>
          </div>
        </div>
      ))}

      <Dialog open={rejectDialog !== null} onOpenChange={() => setRejectDialog(null)}>
        <DialogContent className="bg-slate-900 border-slate-800 text-white sm:max-w-md">
          <DialogHeader>
            <DialogTitle className="text-red-400">Reject Invoice</DialogTitle>
            <DialogDescription className="text-slate-400">
              Provide a reason for rejecting this CapEx invoice. The vendor will not be paid.
            </DialogDescription>
          </DialogHeader>
          <Input
            placeholder="Reason for rejection..."
            value={rejectReason}
            onChange={(e) => setRejectReason(e.target.value)}
            className="bg-slate-800 border-slate-700"
          />
          <DialogFooter>
            <Button variant="ghost" onClick={() => setRejectDialog(null)}>
              Cancel
            </Button>
            <Button
              variant="destructive"
              onClick={() => {
                if (rejectDialog !== null) {
                  rejectMutation.mutate(
                    { stagingId: rejectDialog, reason: rejectReason || "Owner declined" },
                    { onSuccess: () => setRejectDialog(null) },
                  );
                }
              }}
              disabled={rejectMutation.isPending}
            >
              Confirm Rejection
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>
    </div>
  );
}
