"use client";

import { useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { AlertTriangle, CheckCircle, Clock3, Loader2, RefreshCw, Target } from "lucide-react";
import { toast } from "sonner";

import { Button } from "@/components/ui/button";
import {
  Dialog,
  DialogContent,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";
import { ScrollArea } from "@/components/ui/scroll-area";
import { api, ApiError } from "@/lib/api";

type HunterRecoveryOperation = {
  id: string;
  cart_id: string;
  guest_name: string | null;
  cabin_name: string | null;
  cart_value: number | null;
  status: "QUEUED" | "EXECUTING" | "DRAFT_READY" | "DISPATCHED" | "REJECTED" | string;
  ai_draft_body: string | null;
  assigned_worker: string | null;
  created_at: string;
};

type HunterApproveResponse = {
  status: string;
  message: string;
  channel: string;
};

const currencyFormatter = new Intl.NumberFormat("en-US", {
  style: "currency",
  currency: "USD",
  maximumFractionDigits: 2,
});

function statusBadgeClassName(status: HunterRecoveryOperation["status"]): string {
  switch (status) {
    case "DRAFT_READY":
      return "bg-amber-500/10 text-amber-300";
    case "DISPATCHED":
      return "bg-emerald-500/10 text-emerald-300";
    case "EXECUTING":
      return "bg-cyan-500/10 text-cyan-300";
    case "REJECTED":
      return "bg-rose-500/10 text-rose-300";
    case "QUEUED":
    default:
      return "bg-cyan-500/10 text-cyan-300";
  }
}

function formatCartValue(value: number | null): string {
  if (value == null || Number.isNaN(value)) return "--";
  return currencyFormatter.format(value);
}

function statusIcon(status: HunterRecoveryOperation["status"]) {
  switch (status) {
    case "DRAFT_READY":
      return <AlertTriangle className="h-3.5 w-3.5" />;
    case "DISPATCHED":
      return <CheckCircle className="h-3.5 w-3.5" />;
    case "QUEUED":
    case "EXECUTING":
      return <Clock3 className="h-3.5 w-3.5" />;
    default:
      return null;
  }
}

function errorMessage(error: unknown, fallback: string): string {
  if (error instanceof ApiError) {
    return `${error.status}: ${error.message}`;
  }
  if (error instanceof Error) {
    return error.message;
  }
  return fallback;
}

export function HunterOpsQueue() {
  const queryClient = useQueryClient();
  const [selectedOperation, setSelectedOperation] = useState<HunterRecoveryOperation | null>(null);

  const operations = useQuery<HunterRecoveryOperation[]>({
    queryKey: ["hunter-recovery-operations"],
    queryFn: () => api.get("/api/hunter/operations", { limit: 100 }),
    refetchInterval: 5_000,
    staleTime: 5_000,
    retry: 1,
  });

  const approve = useMutation({
    mutationFn: (opId: string) => api.post<HunterApproveResponse>(`/api/hunter/approve/${opId}`),
    onSuccess: (response) => {
      toast.success(`${response.message} Channel: ${response.channel}.`);
      void queryClient.invalidateQueries({ queryKey: ["hunter-recovery-operations"] });
      setSelectedOperation(null);
    },
    onError: (error) => {
      toast.error(errorMessage(error, "Dispatch failed"));
    },
  });

  const rows = operations.data ?? [];

  if (operations.isLoading) {
    return (
      <div className="flex h-full min-h-[420px] flex-col rounded-sm border border-zinc-800 bg-[#111827] p-4 font-mono text-sm">
        <div className="mb-4 flex items-center gap-2 border-b border-zinc-800 pb-2">
          <Target className="h-5 w-5 text-amber-400" />
          <h2 className="font-bold tracking-wide text-white">HUNTER OPS QUEUE</h2>
        </div>
        <div className="text-emerald-400">SCANNING QUEUE...</div>
      </div>
    );
  }

  return (
    <>
      <div className="flex h-full min-h-[560px] flex-col rounded-sm border border-zinc-800 bg-[#111827] p-4 font-mono text-sm shadow-[0_0_0_1px_rgba(17,24,39,0.6)]">
        <div className="mb-4 flex items-center justify-between gap-3 border-b border-zinc-800 pb-2">
          <div className="flex items-center gap-2">
            <Target className="h-5 w-5 text-amber-400" />
            <h2 className="font-bold tracking-wide text-white">HUNTER OPS QUEUE</h2>
          </div>
          <Button
            type="button"
            variant="outline"
            size="sm"
            className="h-8 rounded-none border-zinc-700 bg-zinc-900 px-3 font-mono text-[11px] text-zinc-100 hover:bg-zinc-800"
            disabled={operations.isFetching}
            onClick={() => {
              void operations.refetch();
            }}
          >
            <RefreshCw className={`mr-2 h-3.5 w-3.5 ${operations.isFetching ? "animate-spin" : ""}`} />
            REFRESH
          </Button>
        </div>

        {operations.isError ? (
          <div className="border border-rose-500/30 bg-rose-950/30 px-4 py-3 text-rose-200">
            {errorMessage(operations.error, "Recovery queue unavailable")}
          </div>
        ) : rows.length === 0 ? (
          <div className="border border-zinc-800 bg-[#050505] px-4 py-6 text-zinc-400">
            No staged recovery operations detected.
          </div>
        ) : (
          <div className="flex flex-1 flex-col gap-2 overflow-hidden pr-1">
            <ScrollArea className="flex-1 pr-3">
              <div className="space-y-2">
                {rows.map((row) => {
                  const draftReady = row.status === "DRAFT_READY";
                  return (
                    <div
                      key={row.id}
                      className="flex flex-col justify-between gap-3 border border-zinc-800 bg-[#050505] p-3 transition-colors hover:border-zinc-600 xl:flex-row xl:items-center"
                    >
                      <div className="min-w-0">
                        <div className="truncate font-bold text-zinc-200">
                          {row.guest_name || "Unknown guest"} <span className="text-zinc-600">//</span>{" "}
                          {row.cabin_name || "Unmapped cabin"}
                        </div>
                        <div className="mt-1 break-all text-xs text-zinc-500">
                          Cart: {row.cart_id} | Value: {formatCartValue(row.cart_value)}
                        </div>
                      </div>

                      <div className="flex items-center justify-between gap-4 xl:justify-end">
                        <span
                          className={`inline-flex items-center gap-1 rounded-sm px-2 py-1 text-xs whitespace-nowrap ${statusBadgeClassName(row.status)}`}
                        >
                          {statusIcon(row.status)}
                          {row.status}
                          {row.assigned_worker ? ` (${row.assigned_worker})` : ""}
                        </span>

                        {draftReady ? (
                          <button
                            type="button"
                            onClick={() => setSelectedOperation(row)}
                            className="bg-zinc-800 px-3 py-1 text-xs text-white transition-colors hover:bg-zinc-700"
                          >
                            REVIEW
                          </button>
                        ) : (
                          <button
                            type="button"
                            onClick={() => setSelectedOperation(row)}
                            className="bg-zinc-950 px-3 py-1 text-xs text-zinc-400 transition-colors hover:bg-zinc-900 hover:text-zinc-200"
                          >
                            INSPECT
                          </button>
                        )}
                      </div>
                    </div>
                  );
                })}
              </div>
            </ScrollArea>
          </div>
        )}
      </div>

      <Dialog
        open={selectedOperation !== null}
        onOpenChange={(open) => {
          if (!open) {
            setSelectedOperation(null);
          }
        }}
      >
        <DialogContent className="max-w-3xl rounded-none border-zinc-700 bg-[#111827] font-mono text-zinc-100">
          <DialogHeader>
            <DialogTitle className="text-sm font-bold tracking-wide text-emerald-400">
              REVIEW RECOVERY ASSET // {selectedOperation?.assigned_worker || "UNASSIGNED"}
            </DialogTitle>
          </DialogHeader>

          {selectedOperation ? (
            <div className="space-y-4">
              <div className="border border-zinc-800 bg-[#050505] p-3 text-xs text-zinc-500">
                {selectedOperation.guest_name || "Unknown guest"} // {selectedOperation.cabin_name || "Unmapped cabin"} //{" "}
                {formatCartValue(selectedOperation.cart_value)} // {selectedOperation.status}
              </div>

              <div className="border border-zinc-800 bg-[#050505]">
                <ScrollArea className="h-64 px-4 py-4">
                  <pre className="whitespace-pre-wrap text-sm text-zinc-300">
                    {selectedOperation.ai_draft_body || "No draft body returned yet."}
                  </pre>
                </ScrollArea>
              </div>

              <div className="flex justify-end gap-3">
                <button
                  type="button"
                  onClick={() => setSelectedOperation(null)}
                  className="px-4 py-2 text-sm text-zinc-400 transition-colors hover:text-white"
                >
                  CANCEL
                </button>
                <button
                  type="button"
                  disabled={
                    selectedOperation.status !== "DRAFT_READY" ||
                    approve.isPending ||
                    !selectedOperation.ai_draft_body?.trim()
                  }
                  className="bg-emerald-400 px-4 py-2 text-sm font-bold text-black transition-colors hover:bg-sky-400 disabled:cursor-not-allowed disabled:opacity-50"
                  onClick={() => {
                    void approve.mutateAsync(selectedOperation.id);
                  }}
                >
                  {approve.isPending ? (
                    <span className="inline-flex items-center gap-2">
                      <Loader2 className="h-4 w-4 animate-spin" />
                      TRANSMITTING...
                    </span>
                  ) : (
                    "APPROVE & SEND"
                  )}
                </button>
              </div>
            </div>
          ) : null}
        </DialogContent>
      </Dialog>
    </>
  );
}
