"use client";

import Link from "next/link";
import { useState } from "react";
import {
  type AgentWorkItemAction,
  useAgentAutonomyGates,
  useAgentOperators,
  useAgentQueueHealth,
  useAgentWorkItemAudit,
  useAgentWorkItems,
  useAgentWorkItemAction,
  useReviewQueue,
  useReviewAction,
  useDashboardStats,
  useMessageTemplates,
} from "@/lib/hooks";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import {
  Card,
  CardContent,
  CardHeader,
  CardTitle,
} from "@/components/ui/card";
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/tabs";
import { Textarea } from "@/components/ui/textarea";
import {
  AlertTriangle,
  Activity,
  Bot,
  Brain,
  Check,
  ClipboardCheck,
  Edit,
  ExternalLink,
  History,
  Lock,
  Save,
  Shield,
  ShieldCheck,
  UserCheck,
  X,
  Zap,
} from "lucide-react";

export default function AIEnginePage() {
  const { data: queue } = useReviewQueue();
  const { data: stats } = useDashboardStats();
  const { data: templates } = useMessageTemplates();
  const { data: autonomyGates, isLoading: autonomyGatesLoading, error: autonomyGatesError } = useAgentAutonomyGates();
  const { data: operators, isLoading: operatorsLoading, error: operatorsError } = useAgentOperators();
  const { data: queueHealth, isLoading: queueHealthLoading, error: queueHealthError } = useAgentQueueHealth();
  const { data: workItems, isLoading: workItemsLoading, error: workItemsError } = useAgentWorkItems();
  const { data: workItemAudit, isLoading: workItemAuditLoading, error: workItemAuditError } = useAgentWorkItemAudit();
  const workItemAction = useAgentWorkItemAction();
  const reviewAction = useReviewAction();

  const safeQueue = Array.isArray(queue) ? queue : [];
  const safeTemplates = Array.isArray(templates) ? templates : [];
  const safeAutonomyGates = autonomyGates?.gates ?? [];
  const safeOperators = operators?.operators ?? [];
  const safeQueueHealth = queueHealth?.sources ?? [];
  const safeWorkItems = workItems?.items ?? [];
  const safeWorkItemAudit = workItemAudit?.items ?? [];

  const pending = safeQueue.filter((i) => i.status === "pending");
  const processed = safeQueue.filter((i) => i.status !== "pending");

  const [editId, setEditId] = useState<string | null>(null);
  const [editText, setEditText] = useState("");

  const performWorkItemAction = (
    item: { source: string; id: string; source_label: string },
    action: AgentWorkItemAction,
  ) => {
    const noteByAction: Record<AgentWorkItemAction, string> = {
      assign: "Claimed from the AI Engine work-items ledger.",
      escalate: "Escalated from the AI Engine work-items ledger.",
      dismiss: "Dismissed from the AI Engine work-items ledger.",
      mark_reviewed: "Marked reviewed from the AI Engine work-items ledger.",
    };
    workItemAction.mutate({
      source: item.source,
      id: item.id,
      action,
      note: noteByAction[action],
    });
  };

  return (
    <div className="space-y-6">
      <div>
        <h1 className="text-2xl font-bold tracking-tight">AI Engine</h1>
        <p className="text-muted-foreground">
          Autonomous guest communication intelligence
        </p>
      </div>

      <div className="grid gap-4 md:grid-cols-3 xl:grid-cols-7">
        <Card>
          <CardHeader className="flex flex-row items-center justify-between pb-2">
            <CardTitle className="text-sm font-medium text-muted-foreground">
              Automation Rate
            </CardTitle>
            <Zap className="h-4 w-4 text-amber-500" />
          </CardHeader>
          <CardContent>
            <div className="text-2xl font-bold">
              {stats ? `${Math.round(stats.ai_automation_rate)}%` : "–"}
            </div>
            <p className="text-xs text-muted-foreground">AI-handled messages</p>
          </CardContent>
        </Card>
        <Card>
          <CardHeader className="flex flex-row items-center justify-between pb-2">
            <CardTitle className="text-sm font-medium text-muted-foreground">
              Pending Review
            </CardTitle>
            <Shield className="h-4 w-4 text-orange-500" />
          </CardHeader>
          <CardContent>
            <div className="text-2xl font-bold">{pending.length}</div>
            <p className="text-xs text-muted-foreground">Needs human approval</p>
          </CardContent>
        </Card>
        <Card>
          <CardHeader className="flex flex-row items-center justify-between pb-2">
            <CardTitle className="text-sm font-medium text-muted-foreground">
              Processed Today
            </CardTitle>
            <Brain className="h-4 w-4 text-violet-500" />
          </CardHeader>
          <CardContent>
            <div className="text-2xl font-bold">{processed.length}</div>
            <p className="text-xs text-muted-foreground">Approved / rejected</p>
          </CardContent>
        </Card>
        <Card>
          <CardHeader className="flex flex-row items-center justify-between pb-2">
            <CardTitle className="text-sm font-medium text-muted-foreground">
              Templates Active
            </CardTitle>
            <Bot className="h-4 w-4 text-blue-500" />
          </CardHeader>
          <CardContent>
            <div className="text-2xl font-bold">
              {safeTemplates.filter((t) => t.is_active).length || "–"}
            </div>
            <p className="text-xs text-muted-foreground">Message templates</p>
          </CardContent>
        </Card>
        <Card>
          <CardHeader className="flex flex-row items-center justify-between pb-2">
            <CardTitle className="text-sm font-medium text-muted-foreground">
              Work Items
            </CardTitle>
            <Shield className="h-4 w-4 text-emerald-500" />
          </CardHeader>
          <CardContent>
            <div className="text-2xl font-bold">{workItems?.total ?? "–"}</div>
            <p className="text-xs text-muted-foreground">Unified HITL queue</p>
          </CardContent>
        </Card>
        <Card>
          <CardHeader className="flex flex-row items-center justify-between pb-2">
            <CardTitle className="text-sm font-medium text-muted-foreground">
              Queue Risk
            </CardTitle>
            <Activity className="h-4 w-4 text-cyan-500" />
          </CardHeader>
          <CardContent>
            <div className="text-2xl font-bold">
              {queueHealth ? queueHealth.summary.attention_sources ?? 0 : "–"}
            </div>
            <p className="text-xs text-muted-foreground">Sources needing attention</p>
          </CardContent>
        </Card>
        <Card>
          <CardHeader className="flex flex-row items-center justify-between pb-2">
            <CardTitle className="text-sm font-medium text-muted-foreground">
              Gates Locked
            </CardTitle>
            <Lock className="h-4 w-4 text-rose-500" />
          </CardHeader>
          <CardContent>
            <div className="text-2xl font-bold">
              {autonomyGates ? autonomyGates.summary.locked ?? 0 : "–"}
            </div>
            <p className="text-xs text-muted-foreground">Autonomy controls</p>
          </CardContent>
        </Card>
      </div>

      <Tabs defaultValue="work-items">
        <TabsList>
          <TabsTrigger value="work-items">
            Work Items
            {(workItems?.summary.human_required ?? 0) > 0 && (
              <Badge variant="destructive" className="ml-2 text-[10px]">
                {workItems?.summary.human_required}
              </Badge>
            )}
          </TabsTrigger>
          <TabsTrigger value="operators">
            Operators
            {(operators?.summary.total ?? 0) > 0 && (
              <Badge variant="secondary" className="ml-2 text-[10px]">
                {operators?.summary.total}
              </Badge>
            )}
          </TabsTrigger>
          <TabsTrigger value="autonomy-gates">
            Autonomy Gates
            {(autonomyGates?.summary.locked ?? 0) > 0 && (
              <Badge variant="destructive" className="ml-2 text-[10px]">
                {autonomyGates?.summary.locked}
              </Badge>
            )}
          </TabsTrigger>
          <TabsTrigger value="queue-health">
            Agent Health
            {(queueHealth?.summary.attention_sources ?? 0) > 0 && (
              <Badge variant="destructive" className="ml-2 text-[10px]">
                {queueHealth?.summary.attention_sources}
              </Badge>
            )}
          </TabsTrigger>
          <TabsTrigger value="work-log">
            Action Log
            {(workItemAudit?.total ?? 0) > 0 && (
              <Badge variant="secondary" className="ml-2 text-[10px]">
                {workItemAudit?.total}
              </Badge>
            )}
          </TabsTrigger>
          <TabsTrigger value="queue">
            Review Queue
            {pending.length > 0 && (
              <Badge variant="destructive" className="ml-2 text-[10px]">
                {pending.length}
              </Badge>
            )}
          </TabsTrigger>
          <TabsTrigger value="templates">Templates</TabsTrigger>
          <TabsTrigger value="history">History</TabsTrigger>
        </TabsList>

        <TabsContent value="work-items" className="mt-4 space-y-4">
          {workItemsLoading ? (
            <Card>
              <CardContent className="py-12 text-center">
                <Bot className="h-12 w-12 mx-auto mb-4 text-muted-foreground/50" />
                <p className="text-muted-foreground">Loading agent work items...</p>
              </CardContent>
            </Card>
          ) : workItemsError ? (
            <Card>
              <CardContent className="py-12 text-center">
                <Shield className="h-12 w-12 mx-auto mb-4 text-destructive/70" />
                <p className="text-muted-foreground">Agent work-item feed is unavailable.</p>
              </CardContent>
            </Card>
          ) : safeWorkItems.length === 0 ? (
            <Card>
              <CardContent className="py-12 text-center">
                <Check className="h-12 w-12 mx-auto mb-4 text-emerald-500/70" />
                <p className="text-muted-foreground">No pending agent work items.</p>
              </CardContent>
            </Card>
          ) : (
            <div className="grid gap-3">
              {safeWorkItems.map((item) => (
                <Card key={`${item.source}-${item.id}`}>
                  <CardContent className="flex flex-col gap-4 p-4 xl:flex-row xl:items-center xl:justify-between">
                    <div className="min-w-0 space-y-2">
                      <div className="flex flex-wrap items-center gap-2">
                        <Badge variant="outline">{item.source_label}</Badge>
                        <Badge variant="secondary">{item.status.replaceAll("_", " ")}</Badge>
                        <Badge variant={item.risk_level === "financial" ? "destructive" : "outline"}>
                          {item.risk_level.replaceAll("_", " ")}
                        </Badge>
                        {item.escalated ? (
                          <Badge variant="destructive">Escalated</Badge>
                        ) : null}
                        {item.assigned_to ? (
                          <Badge variant="outline" className="gap-1">
                            <UserCheck className="h-3 w-3" />
                            {item.assigned_to}
                          </Badge>
                        ) : null}
                      </div>
                      <div>
                        <p className="text-sm font-medium">{item.title}</p>
                        {item.detail ? (
                          <p className="mt-1 max-w-3xl text-xs text-muted-foreground">{item.detail}</p>
                        ) : null}
                      </div>
                      <div className="flex flex-wrap gap-x-3 gap-y-1 text-[11px] text-muted-foreground">
                        <span>
                          {item.created_at ? new Date(item.created_at).toLocaleString() : "No timestamp"}
                        </span>
                        {item.last_action ? (
                          <span>
                            Last {item.last_action.replaceAll("_", " ")}
                            {item.last_action_by ? ` by ${item.last_action_by}` : ""}
                          </span>
                        ) : null}
                      </div>
                    </div>
                    <div className="flex flex-wrap gap-2 xl:justify-end">
                      {item.actions.includes("assign") ? (
                        <Button
                          size="sm"
                          variant="outline"
                          disabled={workItemAction.isPending}
                          onClick={() => performWorkItemAction(item, "assign")}
                        >
                          <UserCheck className="mr-1 h-4 w-4" />
                          Claim
                        </Button>
                      ) : null}
                      {item.actions.includes("escalate") ? (
                        <Button
                          size="sm"
                          variant="outline"
                          disabled={workItemAction.isPending}
                          onClick={() => performWorkItemAction(item, "escalate")}
                        >
                          <AlertTriangle className="mr-1 h-4 w-4" />
                          Escalate
                        </Button>
                      ) : null}
                      {item.actions.includes("mark_reviewed") ? (
                        <Button
                          size="sm"
                          variant="outline"
                          disabled={workItemAction.isPending}
                          onClick={() => performWorkItemAction(item, "mark_reviewed")}
                        >
                          <ClipboardCheck className="mr-1 h-4 w-4" />
                          Reviewed
                        </Button>
                      ) : null}
                      {item.actions.includes("dismiss") ? (
                        <Button
                          size="sm"
                          variant="destructive"
                          disabled={workItemAction.isPending}
                          onClick={() => performWorkItemAction(item, "dismiss")}
                        >
                          <X className="mr-1 h-4 w-4" />
                          Dismiss
                        </Button>
                      ) : null}
                      <Button asChild size="sm" variant="outline">
                        <Link href={item.href}>
                          Open
                          <ExternalLink className="ml-2 h-4 w-4" />
                        </Link>
                      </Button>
                    </div>
                  </CardContent>
                </Card>
              ))}
            </div>
          )}
        </TabsContent>

        <TabsContent value="operators" className="mt-4 space-y-4">
          {operatorsLoading ? (
            <Card>
              <CardContent className="py-12 text-center">
                <Bot className="h-12 w-12 mx-auto mb-4 text-muted-foreground/50" />
                <p className="text-muted-foreground">Loading agent operators...</p>
              </CardContent>
            </Card>
          ) : operatorsError ? (
            <Card>
              <CardContent className="py-12 text-center">
                <Shield className="h-12 w-12 mx-auto mb-4 text-destructive/70" />
                <p className="text-muted-foreground">Agent operator registry is unavailable.</p>
              </CardContent>
            </Card>
          ) : safeOperators.length === 0 ? (
            <Card>
              <CardContent className="py-12 text-center">
                <Bot className="h-12 w-12 mx-auto mb-4 text-muted-foreground/50" />
                <p className="text-muted-foreground">No agent operators registered.</p>
              </CardContent>
            </Card>
          ) : (
            <div className="grid gap-3">
              {safeOperators.map((operator) => (
                <Card key={operator.id}>
                  <CardContent className="flex flex-col gap-4 p-4 xl:flex-row xl:items-start xl:justify-between">
                    <div className="min-w-0 space-y-3">
                      <div className="flex flex-wrap items-center gap-2">
                        <Badge variant="outline">{operator.label}</Badge>
                        <Badge
                          variant={
                            operator.status === "degraded"
                              ? "destructive"
                              : operator.status === "ready"
                                ? "default"
                                : "secondary"
                          }
                        >
                          {operator.status}
                        </Badge>
                        <Badge variant={operator.risk_level === "financial" ? "destructive" : "outline"}>
                          {operator.risk_level.replaceAll("_", " ")}
                        </Badge>
                        <Badge variant="outline">{operator.autonomy_level.replaceAll("_", " ")}</Badge>
                        {operator.human_approval_required ? (
                          <Badge variant="secondary" className="gap-1">
                            <ShieldCheck className="h-3 w-3" />
                            Human approval
                          </Badge>
                        ) : null}
                      </div>

                      <p className="max-w-4xl text-sm text-muted-foreground">{operator.purpose}</p>

                      <div className="grid gap-2 text-sm sm:grid-cols-3">
                        <div>
                          <p className="text-xs text-muted-foreground">Pending</p>
                          <p className="font-medium">{operator.pending_count}</p>
                        </div>
                        <div>
                          <p className="text-xs text-muted-foreground">Failed</p>
                          <p className="font-medium">{operator.failed_count}</p>
                        </div>
                        <div>
                          <p className="text-xs text-muted-foreground">Gate</p>
                          <p className="font-medium">{operator.gate_id.replaceAll("_", " ")}</p>
                        </div>
                      </div>

                      <div className="space-y-2">
                        <div className="flex flex-wrap gap-2">
                          {operator.allowed_actions.map((action) => (
                            <Badge key={`${operator.id}-allow-${action}`} variant="outline" className="text-[10px]">
                              {action.replaceAll("_", " ")}
                            </Badge>
                          ))}
                        </div>
                        <div className="flex flex-wrap gap-2">
                          {operator.blocked_actions.map((action) => (
                            <Badge key={`${operator.id}-block-${action}`} variant="destructive" className="text-[10px]">
                              {action.replaceAll("_", " ")}
                            </Badge>
                          ))}
                        </div>
                        <div className="flex flex-wrap gap-2">
                          {operator.data_scope.map((scope) => (
                            <Badge key={`${operator.id}-scope-${scope}`} variant="secondary" className="text-[10px]">
                              {scope.replaceAll("_", " ")}
                            </Badge>
                          ))}
                        </div>
                      </div>
                    </div>
                    <Button asChild size="sm" variant="outline">
                      <Link href={operator.href}>
                        Open
                        <ExternalLink className="ml-2 h-4 w-4" />
                      </Link>
                    </Button>
                  </CardContent>
                </Card>
              ))}
            </div>
          )}
        </TabsContent>

        <TabsContent value="autonomy-gates" className="mt-4 space-y-4">
          {autonomyGatesLoading ? (
            <Card>
              <CardContent className="py-12 text-center">
                <Lock className="h-12 w-12 mx-auto mb-4 text-muted-foreground/50" />
                <p className="text-muted-foreground">Loading autonomy gates...</p>
              </CardContent>
            </Card>
          ) : autonomyGatesError ? (
            <Card>
              <CardContent className="py-12 text-center">
                <Shield className="h-12 w-12 mx-auto mb-4 text-destructive/70" />
                <p className="text-muted-foreground">Autonomy gates are unavailable.</p>
              </CardContent>
            </Card>
          ) : safeAutonomyGates.length === 0 ? (
            <Card>
              <CardContent className="py-12 text-center">
                <ShieldCheck className="h-12 w-12 mx-auto mb-4 text-emerald-500/70" />
                <p className="text-muted-foreground">No autonomy gates found.</p>
              </CardContent>
            </Card>
          ) : (
            <div className="grid gap-3">
              {safeAutonomyGates.map((gate) => (
                <Card key={gate.id}>
                  <CardContent className="flex flex-col gap-4 p-4 lg:flex-row lg:items-center lg:justify-between">
                    <div className="min-w-0 space-y-3">
                      <div className="flex flex-wrap items-center gap-2">
                        <Badge variant="outline">{gate.label}</Badge>
                        <Badge
                          variant={
                            gate.status === "locked"
                              ? "destructive"
                              : gate.status === "ready"
                                ? "default"
                                : "secondary"
                          }
                        >
                          {gate.status}
                        </Badge>
                        <Badge variant={gate.risk_level === "financial" ? "destructive" : "outline"}>
                          {gate.risk_level.replaceAll("_", " ")}
                        </Badge>
                        {gate.human_approval_required ? (
                          <Badge variant="secondary" className="gap-1">
                            <ShieldCheck className="h-3 w-3" />
                            Human approval
                          </Badge>
                        ) : null}
                      </div>

                      {gate.blockers.length > 0 ? (
                        <div className="space-y-1">
                          {gate.blockers.map((blocker) => (
                            <p key={blocker} className="flex items-center gap-2 text-xs text-muted-foreground">
                              <AlertTriangle className="h-3 w-3 text-destructive" />
                              {blocker}
                            </p>
                          ))}
                        </div>
                      ) : (
                        <p className="flex items-center gap-2 text-xs text-muted-foreground">
                          <ShieldCheck className="h-3 w-3 text-emerald-500" />
                          Gate clear under current controls
                        </p>
                      )}

                      <div className="flex flex-wrap gap-2">
                        {Object.entries(gate.signals).map(([key, value]) => (
                          <Badge key={key} variant="outline" className="text-[10px]">
                            {key.replaceAll("_", " ")} {value}
                          </Badge>
                        ))}
                      </div>
                    </div>
                    <Button asChild size="sm" variant="outline">
                      <Link href={gate.href}>
                        Open
                        <ExternalLink className="ml-2 h-4 w-4" />
                      </Link>
                    </Button>
                  </CardContent>
                </Card>
              ))}
            </div>
          )}
        </TabsContent>

        <TabsContent value="queue-health" className="mt-4 space-y-4">
          {queueHealthLoading ? (
            <Card>
              <CardContent className="py-12 text-center">
                <Activity className="h-12 w-12 mx-auto mb-4 text-muted-foreground/50" />
                <p className="text-muted-foreground">Loading agent queue health...</p>
              </CardContent>
            </Card>
          ) : queueHealthError ? (
            <Card>
              <CardContent className="py-12 text-center">
                <Shield className="h-12 w-12 mx-auto mb-4 text-destructive/70" />
                <p className="text-muted-foreground">Agent queue health is unavailable.</p>
              </CardContent>
            </Card>
          ) : safeQueueHealth.length === 0 ? (
            <Card>
              <CardContent className="py-12 text-center">
                <Check className="h-12 w-12 mx-auto mb-4 text-emerald-500/70" />
                <p className="text-muted-foreground">No agent queue health signals found.</p>
              </CardContent>
            </Card>
          ) : (
            <div className="grid gap-3">
              {safeQueueHealth.map((source) => (
                <Card key={source.source}>
                  <CardContent className="flex flex-col gap-4 p-4 lg:flex-row lg:items-center lg:justify-between">
                    <div className="min-w-0 space-y-2">
                      <div className="flex flex-wrap items-center gap-2">
                        <Badge variant="outline">{source.source_label}</Badge>
                        <Badge
                          variant={
                            source.status === "degraded"
                              ? "destructive"
                              : source.status === "healthy"
                                ? "default"
                                : "secondary"
                          }
                        >
                          {source.status}
                        </Badge>
                        {source.failed_count > 0 ? (
                          <Badge variant="destructive">{source.failed_count} failed</Badge>
                        ) : null}
                      </div>
                      <div className="grid gap-2 text-sm sm:grid-cols-4">
                        <div>
                          <p className="text-xs text-muted-foreground">Pending</p>
                          <p className="font-medium">{source.pending_count}</p>
                        </div>
                        <div>
                          <p className="text-xs text-muted-foreground">Failed</p>
                          <p className="font-medium">{source.failed_count}</p>
                        </div>
                        <div>
                          <p className="text-xs text-muted-foreground">Oldest</p>
                          <p className="font-medium">
                            {source.oldest_pending_age_hours != null
                              ? `${source.oldest_pending_age_hours}h`
                              : "–"}
                          </p>
                        </div>
                        <div>
                          <p className="text-xs text-muted-foreground">24h Actions</p>
                          <p className="font-medium">{source.action_count_24h}</p>
                        </div>
                      </div>
                    </div>
                    <Button asChild size="sm" variant="outline">
                      <Link href={source.href}>
                        Open
                        <ExternalLink className="ml-2 h-4 w-4" />
                      </Link>
                    </Button>
                  </CardContent>
                </Card>
              ))}
            </div>
          )}
        </TabsContent>

        <TabsContent value="work-log" className="mt-4 space-y-4">
          {workItemAuditLoading ? (
            <Card>
              <CardContent className="py-12 text-center">
                <History className="h-12 w-12 mx-auto mb-4 text-muted-foreground/50" />
                <p className="text-muted-foreground">Loading action history...</p>
              </CardContent>
            </Card>
          ) : workItemAuditError ? (
            <Card>
              <CardContent className="py-12 text-center">
                <Shield className="h-12 w-12 mx-auto mb-4 text-destructive/70" />
                <p className="text-muted-foreground">Action history is unavailable.</p>
              </CardContent>
            </Card>
          ) : safeWorkItemAudit.length === 0 ? (
            <Card>
              <CardContent className="py-12 text-center">
                <History className="h-12 w-12 mx-auto mb-4 text-muted-foreground/50" />
                <p className="text-muted-foreground">No work-item actions have been recorded yet.</p>
              </CardContent>
            </Card>
          ) : (
            <div className="grid gap-3">
              {safeWorkItemAudit.map((entry) => (
                <Card key={entry.id}>
                  <CardContent className="flex flex-col gap-3 p-4 lg:flex-row lg:items-center lg:justify-between">
                    <div className="min-w-0 space-y-2">
                      <div className="flex flex-wrap items-center gap-2">
                        <Badge variant="outline">{entry.source_label}</Badge>
                        <Badge variant={entry.action === "dismiss" ? "destructive" : "secondary"}>
                          {entry.action.replaceAll("_", " ")}
                        </Badge>
                        <Badge variant="outline">{entry.outcome}</Badge>
                      </div>
                      <div>
                        <p className="text-sm font-medium">
                          {entry.actor_email ?? "Unknown staff"} recorded {entry.action.replaceAll("_", " ")}
                        </p>
                        {entry.note ? (
                          <p className="mt-1 max-w-3xl text-xs text-muted-foreground">{entry.note}</p>
                        ) : null}
                        {entry.assignee ? (
                          <p className="mt-1 text-xs text-muted-foreground">Assigned to {entry.assignee}</p>
                        ) : null}
                      </div>
                      <div className="flex flex-wrap gap-x-3 gap-y-1 text-[11px] text-muted-foreground">
                        <span>{entry.created_at ? new Date(entry.created_at).toLocaleString() : "No timestamp"}</span>
                        <span className="font-mono">hash {entry.audit_hash.slice(0, 12)}</span>
                      </div>
                    </div>
                    {entry.item_id ? (
                      <Button asChild size="sm" variant="outline">
                        <Link href={`/ai-engine?workItem=${entry.source}-${entry.item_id}`}>
                          Trace
                          <History className="ml-2 h-4 w-4" />
                        </Link>
                      </Button>
                    ) : null}
                  </CardContent>
                </Card>
              ))}
            </div>
          )}
        </TabsContent>

        <TabsContent value="queue" className="mt-4 space-y-4">
          {pending.length === 0 ? (
            <Card>
              <CardContent className="py-12 text-center">
                <Bot className="h-12 w-12 mx-auto mb-4 text-muted-foreground/50" />
                <p className="text-muted-foreground">All caught up. No pending reviews.</p>
              </CardContent>
            </Card>
          ) : (
            pending.map((item) => (
              <Card key={item.id}>
                <CardContent className="p-4 space-y-3">
                  <div className="flex items-start justify-between">
                    <div className="flex items-center gap-2">
                      <Badge variant="outline">{item.intent}</Badge>
                      <Badge variant="outline">{item.sentiment}</Badge>
                      <Badge variant="secondary">
                        {Math.round((item.ai_confidence ?? 0) * 100)}% confidence
                      </Badge>
                    </div>
                    <span className="text-xs text-muted-foreground">
                      {new Date(item.created_at).toLocaleString()}
                    </span>
                  </div>

                  <div className="rounded-lg bg-muted p-3">
                    <p className="text-xs font-medium text-muted-foreground mb-1">Guest message:</p>
                    <p className="text-sm">{item.original_message}</p>
                  </div>

                  {editId === item.id ? (
                    <div className="space-y-2">
                      <p className="text-xs font-medium text-primary flex items-center gap-1">
                        <Edit className="h-3 w-3" />
                        Editing AI Draft:
                      </p>
                      <Textarea
                        value={editText}
                        onChange={(e) => setEditText(e.target.value)}
                        rows={4}
                      />
                      <div className="flex gap-2">
                        <Button
                          size="sm"
                          onClick={() => {
                            reviewAction.mutate({ id: item.id, action: "edit", edited_response: editText });
                            setEditId(null);
                            setEditText("");
                          }}
                        >
                          <Save className="h-4 w-4 mr-1" />
                          Save & Send
                        </Button>
                        <Button
                          size="sm"
                          variant="ghost"
                          onClick={() => { setEditId(null); setEditText(""); }}
                        >
                          Cancel
                        </Button>
                      </div>
                    </div>
                  ) : (
                    <div className="rounded-lg border border-primary/20 bg-primary/5 p-3">
                      <p className="text-xs font-medium text-primary mb-1 flex items-center gap-1">
                        <Bot className="h-3 w-3" />
                        AI Draft:
                      </p>
                      <p className="text-sm">{item.ai_draft_response}</p>
                    </div>
                  )}

                  <div className="flex gap-2 pt-1">
                    <Button
                      size="sm"
                      onClick={() => reviewAction.mutate({ id: item.id, action: "approve" })}
                    >
                      <Check className="h-4 w-4 mr-1" />
                      Approve & Send
                    </Button>
                    <Button
                      size="sm"
                      variant="outline"
                      onClick={() => {
                        setEditId(item.id);
                        setEditText(item.ai_draft_response);
                      }}
                    >
                      <Edit className="h-4 w-4 mr-1" />
                      Edit
                    </Button>
                    <Button
                      size="sm"
                      variant="destructive"
                      onClick={() => reviewAction.mutate({ id: item.id, action: "reject" })}
                    >
                      <X className="h-4 w-4 mr-1" />
                      Reject
                    </Button>
                  </div>
                </CardContent>
              </Card>
            ))
          )}
        </TabsContent>

        <TabsContent value="templates" className="mt-4">
          <div className="grid gap-4 md:grid-cols-2">
            {safeTemplates.map((t) => (
              <Card key={t.id}>
                <CardHeader className="pb-2">
                  <div className="flex items-center justify-between">
                    <CardTitle className="text-sm">{t.name}</CardTitle>
                    <Badge variant={t.is_active ? "default" : "secondary"}>
                      {t.is_active ? "Active" : "Inactive"}
                    </Badge>
                  </div>
                </CardHeader>
                <CardContent className="space-y-2">
                  <Badge variant="outline" className="text-[10px]">
                    {t.category} &middot; {t.trigger_type}
                  </Badge>
                  <p className="text-xs text-muted-foreground">{(t.body ?? "").slice(0, 120)}...</p>
                  <div className="flex gap-1 flex-wrap">
                    {(t.variables ?? []).map((v) => (
                      <Badge key={v} variant="outline" className="text-[10px] font-mono">
                        {`{{${v}}}`}
                      </Badge>
                    ))}
                  </div>
                </CardContent>
              </Card>
            ))}
          </div>
        </TabsContent>

        <TabsContent value="history" className="mt-4 space-y-4">
          {processed.length === 0 ? (
            <Card>
              <CardContent className="py-12 text-center">
                <Brain className="h-12 w-12 mx-auto mb-4 text-muted-foreground/50" />
                <p className="text-muted-foreground">No review history yet</p>
              </CardContent>
            </Card>
          ) : (
            processed.map((item) => (
              <Card key={item.id}>
                <CardContent className="p-4 space-y-3">
                  <div className="flex items-start justify-between">
                    <div className="flex items-center gap-2">
                      <Badge variant="outline">{item.intent}</Badge>
                      <Badge variant="outline">{item.sentiment}</Badge>
                      <Badge
                        variant={
                          item.status === "approved"
                            ? "default"
                            : item.status === "rejected"
                              ? "destructive"
                              : "secondary"
                        }
                      >
                        {item.status}
                      </Badge>
                    </div>
                    <span className="text-xs text-muted-foreground">
                      {new Date(item.created_at).toLocaleString()}
                    </span>
                  </div>

                  <div className="rounded-lg bg-muted p-3">
                    <p className="text-xs font-medium text-muted-foreground mb-1">Guest message:</p>
                    <p className="text-sm">{item.original_message}</p>
                  </div>

                  <div className="rounded-lg border p-3">
                    <p className="text-xs font-medium text-muted-foreground mb-1 flex items-center gap-1">
                      <Bot className="h-3 w-3" />
                      AI Response:
                    </p>
                    <p className="text-sm">{item.ai_draft_response}</p>
                  </div>
                </CardContent>
              </Card>
            ))
          )}
        </TabsContent>
      </Tabs>
    </div>
  );
}
