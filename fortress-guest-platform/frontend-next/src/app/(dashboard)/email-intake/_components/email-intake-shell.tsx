"use client";

import { useState } from "react";
import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query";
import { toast } from "sonner";
import { api } from "@/lib/api";
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/tabs";
import { Inbox } from "lucide-react";
import type {
  EmailIntakeDashboardResponse,
  EmailIntakeEscalationListResponse,
  EmailIntakeEscalationItem,
  EmailIntakeQuarantineResponse,
  EmailIntakeQuarantineItem,
  EmailIntakeRulesResponse,
  EmailIntakeLearningResponse,
  EmailIntakeHealthResponse,
  EmailIntakeSlaResponse,
  EmailIntakeDlqResponse,
  EmailIntakeDlqItem,
  EmailIntakeMetadataResponse,
} from "@/lib/types";

import { OverviewTab } from "./overview-tab";
import { QuarantineTab } from "./quarantine-tab";
import { RulesTab } from "./rules-tab";
import { LearningTab } from "./learning-tab";
import { HealthTab } from "./health-tab";
import { DlqTab } from "./dlq-tab";
import { EscalationActionDialog } from "./escalation-action-dialog";
import { EscalationDismissDialog } from "./escalation-dismiss-dialog";
import { EscalationSnoozeDialog } from "./escalation-snooze-dialog";

const BASE = "/api/email-intake";

export function EmailIntakeShell() {
  const qc = useQueryClient();
  const [actionItem, setActionItem] = useState<EmailIntakeEscalationItem | null>(null);
  const [dismissItem, setDismissItem] = useState<EmailIntakeEscalationItem | null>(null);
  const [snoozeItem, setSnoozeItem] = useState<EmailIntakeEscalationItem | null>(null);

  /* ── Queries ───────────────────────────────────────────── */

  const dashboard = useQuery({
    queryKey: ["email-intake", "dashboard"],
    queryFn: () => api.get<EmailIntakeDashboardResponse>(`${BASE}/dashboard`),
  });

  const escalations = useQuery({
    queryKey: ["email-intake", "escalations"],
    queryFn: () =>
      api.get<EmailIntakeEscalationListResponse>(`${BASE}/escalation`),
  });

  const quarantine = useQuery({
    queryKey: ["email-intake", "quarantine"],
    queryFn: () =>
      api.get<EmailIntakeQuarantineResponse>(`${BASE}/quarantine`),
  });

  const rules = useQuery({
    queryKey: ["email-intake", "rules"],
    queryFn: () => api.get<EmailIntakeRulesResponse>(`${BASE}/rules`),
  });

  const learning = useQuery({
    queryKey: ["email-intake", "learning"],
    queryFn: () => api.get<EmailIntakeLearningResponse>(`${BASE}/learning`),
  });

  const health = useQuery({
    queryKey: ["email-intake", "health"],
    queryFn: () => api.get<EmailIntakeHealthResponse>(`${BASE}/health`),
  });

  const sla = useQuery({
    queryKey: ["email-intake", "sla"],
    queryFn: () => api.get<EmailIntakeSlaResponse>(`${BASE}/sla`),
  });

  const dlq = useQuery({
    queryKey: ["email-intake", "dlq"],
    queryFn: () => api.get<EmailIntakeDlqResponse>(`${BASE}/dlq`),
  });

  const metadata = useQuery({
    queryKey: ["email-intake", "metadata"],
    queryFn: () => api.get<EmailIntakeMetadataResponse>(`${BASE}/metadata`),
  });

  /* ── Mutations ─────────────────────────────────────────── */

  const invalidateAll = () => {
    qc.invalidateQueries({ queryKey: ["email-intake"] });
  };

  const escalationAction = useMutation({
    mutationFn: (args: { id: number; payload: Record<string, unknown> }) =>
      api.post(`${BASE}/escalation/${args.id}/action`, args.payload),
    onSuccess: () => { toast.success("Action recorded"); invalidateAll(); },
    onError: (e) => toast.error(`Action failed: ${e.message}`),
  });

  const releaseQuarantine = useMutation({
    mutationFn: (id: number) =>
      api.post(`${BASE}/quarantine/${id}/release`),
    onSuccess: () => { toast.success("Released from quarantine"); invalidateAll(); },
  });

  const deleteQuarantine = useMutation({
    mutationFn: (id: number) =>
      api.post(`${BASE}/quarantine/${id}/delete`),
    onSuccess: () => { toast.success("Deleted from quarantine"); invalidateAll(); },
  });

  const toggleRule = useMutation({
    mutationFn: (args: { type: string; id: number }) =>
      api.post(`${BASE}/rules/${args.type}/${args.id}/toggle`),
    onSuccess: () => { toast.success("Rule toggled"); invalidateAll(); },
  });

  const createRoutingRule = useMutation({
    mutationFn: (body: Record<string, unknown>) =>
      api.post(`${BASE}/rules/routing`, body),
    onSuccess: () => { toast.success("Routing rule created"); invalidateAll(); },
  });

  const createClassificationRule = useMutation({
    mutationFn: (body: Record<string, unknown>) =>
      api.post(`${BASE}/rules/classification`, body),
    onSuccess: () => { toast.success("Classification rule created"); invalidateAll(); },
  });

  const createEscalationRule = useMutation({
    mutationFn: (body: Record<string, unknown>) =>
      api.post(`${BASE}/rules/escalation`, body),
    onSuccess: () => { toast.success("Escalation rule created"); invalidateAll(); },
  });

  const wakeSnoozed = useMutation({
    mutationFn: () => api.post(`${BASE}/wake-snoozed`),
    onSuccess: () => { toast.success("Snoozed items woken"); invalidateAll(); },
  });

  const reprocessDlq = useMutation({
    mutationFn: () => api.post(`${BASE}/dlq/reprocess`),
    onSuccess: () => { toast.success("Reprocessing started"); invalidateAll(); },
  });

  const retryDlq = useMutation({
    mutationFn: (id: number) => api.post(`${BASE}/dlq/${id}/retry`),
    onSuccess: () => { toast.success("Retrying"); invalidateAll(); },
  });

  const discardDlq = useMutation({
    mutationFn: (id: number) => api.post(`${BASE}/dlq/${id}/discard`),
    onSuccess: () => { toast.success("Discarded"); invalidateAll(); },
  });

  /* ── Escalation items list (from dedicated endpoint) ──── */

  const escItems = escalations.data?.items ?? [];

  return (
    <div className="flex-1 p-6 space-y-6">
      <div>
        <h1 className="text-2xl font-bold flex items-center gap-2">
          <Inbox className="h-6 w-6 text-primary" />
          Email Intake
        </h1>
        <p className="text-sm text-muted-foreground mt-1">
          Triage, escalation, quarantine, and learning loop.
        </p>
      </div>

      <Tabs defaultValue="overview">
        <TabsList>
          <TabsTrigger value="overview">Overview</TabsTrigger>
          <TabsTrigger value="escalation">
            Escalation
            {escItems.filter((i) => i.status === "pending").length > 0 && (
              <span className="ml-1.5 inline-flex items-center justify-center h-4 min-w-4 rounded-full bg-destructive text-destructive-foreground text-[10px] px-1">
                {escItems.filter((i) => i.status === "pending").length}
              </span>
            )}
          </TabsTrigger>
          <TabsTrigger value="quarantine">Quarantine</TabsTrigger>
          <TabsTrigger value="rules">Rules</TabsTrigger>
          <TabsTrigger value="learning">Learning</TabsTrigger>
          <TabsTrigger value="health">Health</TabsTrigger>
          <TabsTrigger value="dlq">DLQ</TabsTrigger>
        </TabsList>

        <TabsContent value="overview" className="mt-4">
          <OverviewTab data={dashboard.data} isLoading={dashboard.isLoading} />
        </TabsContent>

        <TabsContent value="escalation" className="mt-4">
          <div className="space-y-2">
            {escalations.isLoading && (
              <p className="text-sm text-muted-foreground">Loading escalations...</p>
            )}
            {escItems.length === 0 && !escalations.isLoading && (
              <p className="text-sm text-muted-foreground rounded-md border p-8 text-center">
                No escalations pending.
              </p>
            )}
            {escItems.map((item) => (
              <div
                key={item.id}
                className="rounded-md border p-3 flex items-center justify-between gap-3"
              >
                <div className="min-w-0 flex-1">
                  <p className="text-sm font-medium truncate">{item.subject}</p>
                  <p className="text-xs text-muted-foreground">
                    {item.sender} &middot; {item.priority} &middot;{" "}
                    {item.trigger_type}: {item.trigger_detail}
                  </p>
                </div>
                <div className="flex gap-1.5 shrink-0">
                  <button
                    className="text-xs px-2 py-1 rounded bg-primary/10 text-primary hover:bg-primary/20"
                    onClick={() =>
                      escalationAction.mutate({
                        id: item.id,
                        payload: { status: "seen" },
                      })
                    }
                  >
                    Mark Seen
                  </button>
                  <button
                    className="text-xs px-2 py-1 rounded bg-emerald-500/10 text-emerald-500 hover:bg-emerald-500/20"
                    onClick={() => setActionItem(item)}
                  >
                    Action
                  </button>
                  <button
                    className="text-xs px-2 py-1 rounded bg-amber-500/10 text-amber-500 hover:bg-amber-500/20"
                    onClick={() => setSnoozeItem(item)}
                  >
                    Snooze
                  </button>
                  <button
                    className="text-xs px-2 py-1 rounded bg-red-500/10 text-red-500 hover:bg-red-500/20"
                    onClick={() => setDismissItem(item)}
                  >
                    Dismiss
                  </button>
                </div>
              </div>
            ))}
          </div>
        </TabsContent>

        <TabsContent value="quarantine" className="mt-4">
          <QuarantineTab
            items={quarantine.data?.items ?? []}
            isLoading={quarantine.isLoading}
            onRelease={(item) => releaseQuarantine.mutate(item.id)}
            onDelete={(item) => deleteQuarantine.mutate(item.id)}
          />
        </TabsContent>

        <TabsContent value="rules" className="mt-4">
          <RulesTab
            data={rules.data}
            isLoading={rules.isLoading}
            onCreateRoutingRule={(p) => createRoutingRule.mutate(p)}
            onCreateClassificationRule={(p) => createClassificationRule.mutate(p)}
            onCreateEscalationRule={(p) => createEscalationRule.mutate(p)}
            onToggleRule={(type, id) => toggleRule.mutate({ type, id })}
          />
        </TabsContent>

        <TabsContent value="learning" className="mt-4">
          <LearningTab data={learning.data} isLoading={learning.isLoading} />
        </TabsContent>

        <TabsContent value="health" className="mt-4">
          <HealthTab
            health={health.data}
            sla={sla.data}
            isLoading={health.isLoading}
            onWakeSnoozed={() => wakeSnoozed.mutate()}
            onReprocess={() => reprocessDlq.mutate()}
          />
        </TabsContent>

        <TabsContent value="dlq" className="mt-4">
          <DlqTab
            items={dlq.data?.items ?? []}
            counts={dlq.data?.counts ?? {}}
            isLoading={dlq.isLoading}
            onRetry={(item: EmailIntakeDlqItem) => retryDlq.mutate(item.id)}
            onDiscard={(item: EmailIntakeDlqItem) => discardDlq.mutate(item.id)}
          />
        </TabsContent>
      </Tabs>

      {/* Dialogs */}
      <EscalationActionDialog
        open={!!actionItem}
        item={actionItem}
        metadata={metadata.data}
        onOpenChange={(open) => !open && setActionItem(null)}
        onSubmit={(payload) => {
          if (actionItem) {
            escalationAction.mutate({ id: actionItem.id, payload });
            setActionItem(null);
          }
        }}
      />

      <EscalationDismissDialog
        open={!!dismissItem}
        item={dismissItem}
        metadata={metadata.data}
        onOpenChange={(open) => !open && setDismissItem(null)}
        onSubmit={(payload) => {
          if (dismissItem) {
            escalationAction.mutate({ id: dismissItem.id, payload });
            setDismissItem(null);
          }
        }}
      />

      <EscalationSnoozeDialog
        open={!!snoozeItem}
        item={snoozeItem}
        onOpenChange={(open) => !open && setSnoozeItem(null)}
        onSubmit={(payload) => {
          if (snoozeItem) {
            escalationAction.mutate({ id: snoozeItem.id, payload });
            setSnoozeItem(null);
          }
        }}
      />
    </div>
  );
}
