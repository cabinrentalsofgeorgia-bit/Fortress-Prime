"use client";

import Link from "next/link";
import { useEffect, useMemo, useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useRouter } from "next/navigation";
import {
  AlertCircle,
  ArrowLeft,
  CheckCircle2,
  LoaderCircle,
  OctagonX,
  ShieldAlert,
} from "lucide-react";
import { toast } from "sonner";

import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import {
  Card,
  CardContent,
  CardDescription,
  CardHeader,
  CardTitle,
} from "@/components/ui/card";
import { Label } from "@/components/ui/label";
import { Separator } from "@/components/ui/separator";
import { Textarea } from "@/components/ui/textarea";
import {
  getPendingSwarmEscalation,
  getSwarmRun,
  overrideSwarmEscalation,
  type JsonObject,
  type OverrideAction,
  type TrustPayload,
} from "@/lib/api/swarm-trust";

interface PolicyFailure {
  key: string;
  value: string;
}

function isJsonObject(value: unknown): value is JsonObject {
  return Boolean(value) && typeof value === "object" && !Array.isArray(value);
}

function prettyJson(value: unknown): string {
  try {
    return JSON.stringify(value ?? {}, null, 2);
  } catch {
    return "{}";
  }
}

function formatLabel(value: string): string {
  return value
    .split("_")
    .map((chunk) => chunk.slice(0, 1).toUpperCase() + chunk.slice(1))
    .join(" ");
}

function formatTimestamp(value: string | null): string {
  if (!value) return "--";
  return new Date(value).toLocaleString();
}

function collectPolicyFailures(policy: JsonObject): PolicyFailure[] {
  return Object.entries(policy).flatMap(([key, value]) => {
    if (value === false) {
      return [{ key, value: "false" }];
    }

    if (key === "reason_code" && typeof value === "string" && value !== "compliant") {
      return [{ key, value }];
    }

    return [];
  });
}

function JsonPanel({ value }: { value: unknown }) {
  return (
    <pre className="max-h-[420px] overflow-auto rounded-xl border border-slate-800 bg-slate-950 p-4 font-mono text-xs leading-6 text-slate-200">
      {prettyJson(value)}
    </pre>
  );
}

function DetailContent({ escalationId }: { escalationId: string }) {
  const router = useRouter();
  const queryClient = useQueryClient();
  const escalation = useQuery({
    queryKey: ["trust-review", "escalation", escalationId],
    queryFn: () => getPendingSwarmEscalation(escalationId),
    staleTime: 5_000,
  });

  const run = useQuery({
    queryKey: ["trust-review", "run", escalation.data?.run_id],
    queryFn: async () => {
      if (!escalation.data) {
        throw new Error("Escalation context is missing.");
      }
      return getSwarmRun(escalation.data.run_id);
    },
    enabled: Boolean(escalation.data?.run_id),
    staleTime: 5_000,
  });

  const [payloadDraft, setPayloadDraft] = useState("{}");

  useEffect(() => {
    if (escalation.data) {
      setPayloadDraft(prettyJson(escalation.data.proposed_payload));
    }
  }, [escalation.data]);

  const parsedPayload = useMemo(() => {
    try {
      const parsed = JSON.parse(payloadDraft);
      if (!isJsonObject(parsed)) {
        return {
          value: null,
          error: "Final payload must be a JSON object.",
        };
      }
      return { value: parsed as TrustPayload, error: null };
    } catch (error) {
      return {
        value: null,
        error: error instanceof Error ? error.message : "Invalid JSON payload.",
      };
    }
  }, [payloadDraft]);

  const policyFailures = useMemo(
    () => collectPolicyFailures(escalation.data?.policy_evaluation ?? {}),
    [escalation.data?.policy_evaluation],
  );

  const overrideMutation = useMutation({
    mutationFn: ({
      overrideAction,
      finalPayload,
    }: {
      overrideAction: OverrideAction;
      finalPayload: TrustPayload;
    }) =>
      overrideSwarmEscalation(escalationId, {
        override_action: overrideAction,
        final_payload: finalPayload,
      }),
    onSuccess: (_result, variables) => {
      const successMessage =
        variables.overrideAction === "approve"
          ? "Override approved. Agent run forced through."
          : variables.overrideAction === "modify"
            ? "Modified payload approved. Escalation resolved."
            : "Run blocked. Escalation rejected.";

      toast.success(successMessage);
      void queryClient.invalidateQueries({ queryKey: ["trust-review"] });
      router.push("/trust-review");
      router.refresh();
    },
    onError: (error) => {
      toast.error(error instanceof Error ? error.message : "Override execution failed.");
    },
  });

  if (escalation.isLoading || run.isLoading) {
    return (
      <div className="space-y-6">
        <Button asChild variant="ghost" size="sm">
          <Link href="/trust-review">
            <ArrowLeft className="mr-2 h-4 w-4" />
            Back to Escalation Queue
          </Link>
        </Button>
        <Card className="border-slate-800 bg-slate-950/70">
          <CardContent className="flex min-h-[420px] items-center justify-center">
            <div className="flex items-center gap-3 text-sm text-slate-400">
              <LoaderCircle className="h-4 w-4 animate-spin" />
              Loading Trust Swarm escalation detail...
            </div>
          </CardContent>
        </Card>
      </div>
    );
  }

  if (escalation.error || run.error) {
    const message =
      escalation.error instanceof Error
        ? escalation.error.message
        : run.error instanceof Error
          ? run.error.message
          : "Failed to load the Trust Swarm escalation detail.";

    return (
      <div className="space-y-6">
        <Button asChild variant="ghost" size="sm">
          <Link href="/trust-review">
            <ArrowLeft className="mr-2 h-4 w-4" />
            Back to Escalation Queue
          </Link>
        </Button>
        <Card className="border-rose-900/60 bg-slate-950/70">
          <CardContent className="flex min-h-[420px] flex-col items-center justify-center gap-4 px-6 text-center">
            <AlertCircle className="h-8 w-8 text-rose-400" />
            <p className="max-w-xl text-sm text-rose-300">{message}</p>
            <Button type="button" onClick={() => void Promise.all([escalation.refetch(), run.refetch()])}>
              Retry
            </Button>
          </CardContent>
        </Card>
      </div>
    );
  }

  if (!escalation.data || !run.data) {
    return (
      <div className="space-y-6">
        <Button asChild variant="ghost" size="sm">
          <Link href="/trust-review">
            <ArrowLeft className="mr-2 h-4 w-4" />
            Back to Escalation Queue
          </Link>
        </Button>
        <Card className="border-slate-800 bg-slate-950/70">
          <CardContent className="flex min-h-[420px] flex-col items-center justify-center gap-4 px-6 text-center">
            <OctagonX className="h-8 w-8 text-amber-300" />
            <p className="max-w-xl text-sm text-slate-300">
              This escalation is no longer pending or could not be located in the live queue.
            </p>
          </CardContent>
        </Card>
      </div>
    );
  }

  const isBusy = overrideMutation.isPending;
  const escalationData = escalation.data;
  const runData = run.data;

  return (
    <div className="space-y-6">
      <Button asChild variant="ghost" size="sm">
        <Link href="/trust-review">
          <ArrowLeft className="mr-2 h-4 w-4" />
          Back to Escalation Queue
        </Link>
      </Button>

      <Card className="border-slate-800 bg-slate-950/70">
        <CardHeader className="border-b border-slate-800/80">
          <div className="flex flex-wrap items-start justify-between gap-4">
            <div className="space-y-2">
              <div className="flex flex-wrap items-center gap-2">
                <CardTitle className="text-2xl text-slate-100">{runData.agent_name}</CardTitle>
                <Badge
                  variant="outline"
                  className="border-amber-500/30 bg-amber-500/10 text-amber-200"
                >
                  {formatLabel(escalationData.reason_code)}
                </Badge>
              </div>
              <CardDescription className="text-slate-400">
                Trust Swarm escalation {escalationData.id}
              </CardDescription>
            </div>

            <div className="grid gap-3 sm:grid-cols-3">
              <div className="rounded-xl border border-slate-800 bg-slate-900/80 p-3">
                <p className="text-[11px] uppercase tracking-[0.22em] text-slate-500">
                  Trigger Source
                </p>
                <p className="mt-2 text-sm text-slate-100">{runData.trigger_source}</p>
              </div>
              <div className="rounded-xl border border-slate-800 bg-slate-900/80 p-3">
                <p className="text-[11px] uppercase tracking-[0.22em] text-slate-500">
                  Deterministic Score
                </p>
                <p className="mt-2 font-mono text-xl text-slate-100">
                  {escalationData.deterministic_score.toFixed(3)}
                </p>
              </div>
              <div className="rounded-xl border border-slate-800 bg-slate-900/80 p-3">
                <p className="text-[11px] uppercase tracking-[0.22em] text-slate-500">
                  Decision Status
                </p>
                <p className="mt-2 text-sm text-slate-100">
                  {formatLabel(escalationData.decision_status)}
                </p>
              </div>
            </div>
          </div>
        </CardHeader>
      </Card>

      <div className="grid gap-6 xl:grid-cols-[minmax(0,0.95fr)_minmax(0,1.05fr)]">
        <Card className="border-slate-800 bg-slate-950/70">
          <CardHeader>
            <CardTitle className="flex items-center gap-2 text-base text-slate-100">
              <ShieldAlert className="h-4 w-4 text-amber-300" />
              Audit Panel
            </CardTitle>
            <CardDescription className="text-slate-400">
              Deterministic policy evidence, run state, and failed control signals.
            </CardDescription>
          </CardHeader>
          <CardContent className="space-y-5">
            <div className="grid gap-3 sm:grid-cols-2">
              <div className="rounded-xl border border-slate-800 bg-slate-900/80 p-3">
                <p className="text-[11px] uppercase tracking-[0.22em] text-slate-500">Run ID</p>
                <p className="mt-2 font-mono text-xs text-slate-100">{runData.id}</p>
              </div>
              <div className="rounded-xl border border-slate-800 bg-slate-900/80 p-3">
                <p className="text-[11px] uppercase tracking-[0.22em] text-slate-500">Run Status</p>
                <p className="mt-2 text-sm text-slate-100">{formatLabel(runData.status)}</p>
              </div>
              <div className="rounded-xl border border-slate-800 bg-slate-900/80 p-3">
                <p className="text-[11px] uppercase tracking-[0.22em] text-slate-500">Started</p>
                <p className="mt-2 text-sm text-slate-100">{formatTimestamp(runData.started_at)}</p>
              </div>
              <div className="rounded-xl border border-slate-800 bg-slate-900/80 p-3">
                <p className="text-[11px] uppercase tracking-[0.22em] text-slate-500">Completed</p>
                <p className="mt-2 text-sm text-slate-100">{formatTimestamp(runData.completed_at)}</p>
              </div>
            </div>

            <Separator className="bg-slate-800" />

            <div className="space-y-3">
              <p className="text-xs font-semibold uppercase tracking-[0.22em] text-slate-500">
                Failed Deterministic Checks
              </p>
              {policyFailures.length > 0 ? (
                <div className="space-y-3">
                  {policyFailures.map((failure) => (
                    <div
                      key={`${failure.key}-${failure.value}`}
                      className="rounded-xl border border-rose-500/20 bg-rose-500/10 p-3 text-sm text-rose-100"
                    >
                      <span className="font-medium">{failure.key}</span>: {failure.value}
                    </div>
                  ))}
                </div>
              ) : (
                <div className="rounded-xl border border-slate-800 bg-slate-900/80 p-4 text-sm text-slate-400">
                  No explicit failing boolean checks were returned in `policy_evaluation`.
                </div>
              )}
            </div>

            <div className="space-y-3">
              <p className="text-xs font-semibold uppercase tracking-[0.22em] text-slate-500">
                Policy Evaluation Payload
              </p>
              <JsonPanel value={escalationData.policy_evaluation} />
            </div>
          </CardContent>
        </Card>

        <Card className="border-slate-800 bg-slate-950/70">
          <CardHeader>
            <CardTitle className="text-base text-slate-100">Payload Editor</CardTitle>
            <CardDescription className="text-slate-400">
              Edit the proposed debits and credits before sealing a manual override.
            </CardDescription>
          </CardHeader>
          <CardContent className="space-y-4">
            <div className="space-y-2">
              <Label htmlFor="trust-payload-editor">Final Payload JSON</Label>
              <Textarea
                id="trust-payload-editor"
                value={payloadDraft}
                onChange={(event) => setPayloadDraft(event.target.value)}
                className="min-h-[540px] border-slate-800 bg-slate-950 font-mono text-xs text-slate-100"
                spellCheck={false}
              />
            </div>
            {parsedPayload.error ? (
              <p className="text-sm text-rose-300">{parsedPayload.error}</p>
            ) : (
              <p className="text-sm text-slate-400">
                JSON validated. `Modify & Approve` will persist this final payload.
              </p>
            )}
          </CardContent>
        </Card>
      </div>

      <Card className="border-slate-800 bg-slate-950/70">
        <CardHeader>
          <CardTitle className="text-base text-slate-100">Action Bar</CardTitle>
          <CardDescription className="text-slate-400">
            Operator identity is derived server-side from the authenticated staff session.
          </CardDescription>
        </CardHeader>
        <CardContent className="flex flex-wrap items-center gap-3">
          <Button
            type="button"
            disabled={isBusy}
            onClick={() =>
              overrideMutation.mutate({
                overrideAction: "approve",
                finalPayload: escalationData.proposed_payload,
              })
            }
          >
            <CheckCircle2 className="mr-2 h-4 w-4" />
            Approve Override
          </Button>
          <Button
            type="button"
            variant="secondary"
            disabled={isBusy || Boolean(parsedPayload.error) || !parsedPayload.value}
            onClick={() => {
              if (!parsedPayload.value) return;
              overrideMutation.mutate({
                overrideAction: "modify",
                finalPayload: parsedPayload.value,
              });
            }}
          >
            <CheckCircle2 className="mr-2 h-4 w-4" />
            Modify & Approve
          </Button>
          <Button
            type="button"
            variant="destructive"
            disabled={isBusy}
            onClick={() =>
              overrideMutation.mutate({
                overrideAction: "reject",
                finalPayload: escalationData.proposed_payload,
              })
            }
          >
            <OctagonX className="mr-2 h-4 w-4" />
            Reject & Block
          </Button>
        </CardContent>
      </Card>
    </div>
  );
}

export function TrustReviewDetail({ escalationId }: { escalationId: string }) {
  return <DetailContent escalationId={escalationId} />;
}
