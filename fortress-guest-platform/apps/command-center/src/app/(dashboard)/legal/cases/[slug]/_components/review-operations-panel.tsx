"use client";

import { Badge } from "@/components/ui/badge";
import { Skeleton } from "@/components/ui/skeleton";
import { useReviewOperations } from "@/lib/legal-hooks";
import {
  Activity,
  BarChart3,
  ClipboardCheck,
  ClipboardList,
  GitBranch,
  RotateCcw,
  ShieldCheck,
  TimerReset,
  UserRoundCheck,
  Users,
} from "lucide-react";

function Metric({ label, value }: { label: string; value: number | string }) {
  return (
    <div className="rounded-md border border-zinc-800 bg-zinc-950/70 p-3">
      <p className="text-[10px] uppercase tracking-wide text-zinc-500">{label}</p>
      <p className="text-lg font-semibold text-zinc-100">{value}</p>
    </div>
  );
}

function tone(value: string) {
  if (value.includes("restricted") || value.includes("locked")) return "bg-purple-500/10 text-purple-300 border-purple-500/30";
  if (value.includes("contradiction")) return "bg-amber-500/10 text-amber-300 border-amber-500/30";
  if (value.includes("source_missing") || value.includes("evidence")) return "bg-red-500/10 text-red-300 border-red-500/30";
  if (value.includes("tier_1") || value.includes("critical")) return "bg-orange-500/10 text-orange-300 border-orange-500/30";
  return "bg-blue-500/10 text-blue-300 border-blue-500/30";
}

function label(value: string) {
  return value.replaceAll("_", " ");
}

export function ReviewOperationsPanel({ slug }: { slug: string }) {
  const { data, isLoading, error } = useReviewOperations(slug);

  if (isLoading) {
    return (
      <div className="rounded-lg border border-zinc-800 bg-zinc-950/80 p-4 space-y-3">
        <Skeleton className="h-6 w-80" />
        <Skeleton className="h-28 w-full" />
      </div>
    );
  }

  if (error || !data) {
    return (
      <div className="rounded-lg border border-zinc-800 bg-zinc-950/70 p-4 text-sm text-zinc-400">
        Controlled review operations read model is not available yet.
      </div>
    );
  }

  const remediationItems = data.queues.remediation_review.items.slice(0, 6);
  const contradictionItems = data.queues.contradiction_review.items.slice(0, 4);
  const evidenceItems = data.queues.evidence_navigation.items.slice(0, 4);

  return (
    <div className="rounded-lg border border-cyan-500/30 bg-cyan-500/5 p-4 space-y-4">
      <div className="flex items-center justify-between gap-3 flex-wrap">
        <div>
          <p className="text-sm font-semibold text-cyan-200 flex items-center gap-2">
            <ClipboardList className="h-4 w-4" />
            Controlled Review Operations
          </p>
          <p className="text-xs text-zinc-400">
            {data.status.replaceAll("_", " ")} / {data.governance.review_operations_mode.replaceAll("_", " ")}
          </p>
        </div>
        <div className="flex gap-2 flex-wrap">
          <Badge variant="outline" className="bg-red-500/10 text-red-300 border-red-500/30 text-[10px]">
            DRAFT / COUNSEL REVIEW REQUIRED
          </Badge>
          <Badge variant="outline" className="bg-amber-500/10 text-amber-300 border-amber-500/30 text-[10px]">
            {data.governance.counsel_signoff}
          </Badge>
          <Badge variant="outline" className="bg-zinc-900 text-zinc-300 border-zinc-700 text-[10px]">
            {data.governance.external_submission_authority}
          </Badge>
          <Badge variant="outline" className="bg-zinc-900 text-zinc-300 border-zinc-700 text-[10px]">
            {data.governance.legal_advice_status}
          </Badge>
        </div>
      </div>

      <div className="rounded-md border border-cyan-500/20 bg-cyan-500/5 p-3 text-xs text-cyan-100">
        Review operations are read-only queue and analytics views. Unresolved source issues remain excluded from
        relied-upon sections; locked/restricted materials stay metadata only restricted; no review action creates
        signoff, final legal advice, or external submission authority.
      </div>

      <section className="rounded-md border border-emerald-500/30 bg-emerald-500/5 p-3 space-y-3">
        <div className="flex items-center justify-between gap-3 flex-wrap">
          <p className="text-xs font-semibold text-emerald-100 flex items-center gap-2">
            <ClipboardCheck className="h-3.5 w-3.5 text-emerald-300" />
            Operational Readiness Certification
          </p>
          <Badge variant="outline" className="bg-emerald-500/10 text-emerald-300 border-emerald-500/30 text-[10px]">
            {label(data.operational_certification.status)}
          </Badge>
        </div>
        <p className="text-[10px] text-zinc-500">
          Scope: {label(data.operational_certification.certification_scope)}.
        </p>
        <div className="grid gap-2 sm:grid-cols-2 xl:grid-cols-5">
          <Metric label="Route Verified" value={data.operational_certification.readiness_audit.production_route_verified ? "Yes" : "No"} />
          <Metric label="Excluded Issues" value={data.operational_certification.readiness_audit.unresolved_source_issues_excluded} />
          <Metric label="Signoff" value={label(data.operational_certification.readiness_audit.counsel_signoff_status)} />
          <Metric label="External Use" value={label(data.operational_certification.readiness_audit.external_submission_authority)} />
          <Metric label="Schema/RLS" value={label(data.operational_certification.readiness_audit.schema_rls_policy_mutation)} />
        </div>
        <div className="grid gap-3 xl:grid-cols-3">
          <div className="rounded border border-zinc-800 bg-zinc-950/70 p-2">
            <p className="text-[11px] font-semibold text-zinc-100">Pilot Governance</p>
            <p className="text-[10px] text-zinc-500">
              {label(data.operational_certification.pilot_governance.pilot_mode)} / public launch {data.operational_certification.pilot_governance.public_launch_enabled ? "enabled" : "disabled"}.
            </p>
            <div className="mt-1 flex flex-wrap gap-1">
              {data.operational_certification.pilot_governance.allowed_operations.map((operation) => (
                <Badge key={operation} variant="outline" className="bg-blue-500/10 text-blue-300 border-blue-500/30 text-[10px]">
                  {label(operation)}
                </Badge>
              ))}
              {data.operational_certification.pilot_governance.forbidden_operations.map((operation) => (
                <Badge key={operation} variant="outline" className="bg-red-500/10 text-red-300 border-red-500/30 text-[10px]">
                  forbidden {label(operation)}
                </Badge>
              ))}
            </div>
          </div>
          <div className="rounded border border-zinc-800 bg-zinc-950/70 p-2">
            <p className="text-[11px] font-semibold text-zinc-100">Reviewer Onboarding Governance</p>
            <p className="text-[10px] text-zinc-500">
              {label(data.operational_certification.reviewer_onboarding.status)}
            </p>
            <div className="mt-1 flex flex-wrap gap-1">
              {data.operational_certification.reviewer_onboarding.required_acknowledgments.map((ack) => (
                <Badge key={ack} variant="outline" className="bg-amber-500/10 text-amber-300 border-amber-500/30 text-[10px]">
                  acknowledge {label(ack)}
                </Badge>
              ))}
            </div>
          </div>
          <div className="rounded border border-zinc-800 bg-zinc-950/70 p-2">
            <p className="text-[11px] font-semibold text-zinc-100 flex items-center gap-1">
              <RotateCcw className="h-3 w-3 text-cyan-300" />
              Rollback Certification
            </p>
            <p className="text-[10px] text-zinc-500">
              {label(data.operational_certification.rollback_certification.status)} / git revertable {data.operational_certification.rollback_certification.git_revertable ? "yes" : "no"}.
            </p>
            <div className="mt-1 flex flex-wrap gap-1">
              {data.operational_certification.rollback_certification.verification_after_rollback.map((check) => (
                <Badge key={check} variant="outline" className="text-[10px]">
                  {label(check)}
                </Badge>
              ))}
            </div>
          </div>
        </div>
        <div className="grid gap-3 xl:grid-cols-2">
          <div className="rounded border border-zinc-800 bg-zinc-950/70 p-2">
            <p className="text-[11px] font-semibold text-zinc-100">Governance Enforcement Verification</p>
            <div className="mt-1 flex flex-wrap gap-1">
              {data.operational_certification.governance_enforcement.required_checks.map((check) => (
                <Badge key={check} variant="outline" className="bg-emerald-500/10 text-emerald-300 border-emerald-500/30 text-[10px]">
                  {label(check)}
                </Badge>
              ))}
            </div>
          </div>
          <div className="rounded border border-zinc-800 bg-zinc-950/70 p-2">
            <p className="text-[11px] font-semibold text-zinc-100">Operational Safety Certification</p>
            <p className="text-[10px] text-zinc-500">
              {label(data.operational_certification.operational_safety.status)}
            </p>
            <div className="mt-1 flex flex-wrap gap-1">
              {data.operational_certification.operational_safety.certification_limitations.map((limitation) => (
                <Badge key={limitation} variant="outline" className="bg-red-500/10 text-red-300 border-red-500/30 text-[10px]">
                  limit {label(limitation)}
                </Badge>
              ))}
            </div>
          </div>
        </div>
      </section>

      <div className="grid gap-2 sm:grid-cols-2 xl:grid-cols-6">
        <Metric label="Review Queue" value={data.review_operations_summary.remediation_queue_depth} />
        <Metric label="Contradictions" value={data.review_operations_summary.contradiction_queue_depth} />
        <Metric label="Evidence Pivots" value={data.review_operations_summary.evidence_navigation_items} />
        <Metric label="High Priority" value={data.review_operations_summary.high_priority_items} />
        <Metric label="Unassigned" value={data.review_operations_summary.reviewer_owner_unassigned} />
        <Metric label="Verified Subset" value={data.review_operations_summary.verified_subset_count} />
      </div>

      <div className="grid gap-4 xl:grid-cols-[1fr_1fr_1fr]">
        <section className="rounded-md border border-zinc-800 bg-zinc-950/70 p-3 space-y-2">
          <p className="text-xs font-semibold text-zinc-100 flex items-center gap-2">
            <UserRoundCheck className="h-3.5 w-3.5 text-cyan-300" />
            Reviewer Assignment
          </p>
          <p className="text-[10px] text-zinc-500">
            {label(data.reviewer_operations.assignment_model.mode)} / {label(data.reviewer_operations.assignment_model.authority_boundary)}
          </p>
          <div className="flex flex-wrap gap-1">
            {data.reviewer_operations.assignment_model.reviewer_groups.map((group) => (
              <Badge key={group} variant="outline" className={`text-[10px] ${tone(group)}`}>
                {label(group)}
              </Badge>
            ))}
          </div>
          <div className="flex flex-wrap gap-1 pt-1 border-t border-zinc-800">
            {data.reviewer_operations.assignment_model.forbidden_assignment_effects.map((effect) => (
              <Badge key={effect} variant="outline" className="bg-red-500/10 text-red-300 border-red-500/30 text-[10px]">
                forbidden {label(effect)}
              </Badge>
            ))}
          </div>
        </section>

        <section className="rounded-md border border-zinc-800 bg-zinc-950/70 p-3 space-y-2">
          <p className="text-xs font-semibold text-zinc-100 flex items-center gap-2">
            <Users className="h-3.5 w-3.5 text-blue-300" />
            Workload Balancing
          </p>
          <div className="grid grid-cols-2 gap-2">
            <Metric label="Weight" value={data.reviewer_operations.workload_balancing.summary.total_workload_weight} />
            <Metric label="Unassigned" value={data.reviewer_operations.workload_balancing.summary.unassigned_items} />
            <Metric label="Source Review" value={data.reviewer_operations.workload_balancing.summary.source_reviewer_items} />
            <Metric label="Counsel Lane" value={data.reviewer_operations.workload_balancing.summary.counsel_or_senior_reviewer_items} />
          </div>
          <div className="flex flex-wrap gap-1">
            {data.reviewer_operations.workload_balancing.distribution.map((row) => (
              <Badge key={row.owner_role_hint} variant="outline" className={`text-[10px] ${tone(row.owner_role_hint)}`}>
                {label(row.owner_role_hint)} {row.count}
              </Badge>
            ))}
          </div>
        </section>

        <section className="rounded-md border border-zinc-800 bg-zinc-950/70 p-3 space-y-2">
          <p className="text-xs font-semibold text-zinc-100 flex items-center gap-2">
            <TimerReset className="h-3.5 w-3.5 text-amber-300" />
            Queue Aging / SLA
          </p>
          <p className="text-[10px] text-zinc-500">
            {label(data.reviewer_operations.queue_aging_sla.model)} / {label(data.reviewer_operations.queue_aging_sla.baseline_age_source)}
          </p>
          {data.reviewer_operations.queue_aging_sla.targets.map((target) => (
            <div key={target.sla_band} className="flex items-center justify-between rounded border border-zinc-800 bg-zinc-900/70 px-2 py-1.5">
              <span className="text-xs text-zinc-200">{label(target.sla_band)}</span>
              <Badge variant="outline" className={`text-[10px] ${tone(target.sla_band)}`}>
                {label(target.target)}
              </Badge>
            </div>
          ))}
        </section>
      </div>

      <div className="grid gap-4 xl:grid-cols-[1.2fr_0.9fr_0.9fr]">
        <section className="rounded-md border border-zinc-800 bg-zinc-950/70 p-3 space-y-2">
          <p className="text-xs font-semibold text-zinc-100 flex items-center gap-2">
            <TimerReset className="h-3.5 w-3.5 text-cyan-300" />
            Review Queue Operations
          </p>
          <div className="space-y-2">
            {remediationItems.map((item) => (
              <div key={`${item.item_type}-${item.item_id}`} className="rounded border border-zinc-800 bg-zinc-900/70 p-2">
                <div className="flex items-start justify-between gap-2">
                  <p className="text-xs text-zinc-100">{label(item.item_type)} / {item.item_id}</p>
                  <Badge variant="outline" className="text-[10px]">
                    {label(item.owner_placeholder)}
                  </Badge>
                </div>
                <div className="mt-1 flex flex-wrap gap-1">
                  <Badge variant="outline" className={`text-[10px] ${tone(item.materiality_tier)}`}>
                    {label(item.materiality_tier)}
                  </Badge>
                  <Badge variant="outline" className={`text-[10px] ${tone(item.review_lane)}`}>
                    {label(item.review_lane)}
                  </Badge>
                  <Badge variant="outline" className="bg-zinc-900 text-zinc-300 border-zinc-700 text-[10px]">
                    {label(item.audit_state)}
                  </Badge>
                  <Badge variant="outline" className={`text-[10px] ${tone(item.sla_band)}`}>
                    {label(item.sla_band)}
                  </Badge>
                  <Badge variant="outline" className={`text-[10px] ${tone(item.escalation_state)}`}>
                    {label(item.escalation_state)}
                  </Badge>
                  <Badge variant="outline" className="bg-zinc-900 text-zinc-300 border-zinc-700 text-[10px]">
                    excluded from relied-upon sections
                  </Badge>
                </div>
              </div>
            ))}
          </div>
        </section>

        <section className="rounded-md border border-zinc-800 bg-zinc-950/70 p-3 space-y-2">
          <p className="text-xs font-semibold text-zinc-100 flex items-center gap-2">
            <GitBranch className="h-3.5 w-3.5 text-amber-300" />
            Contradiction Review
          </p>
          {data.queues.contradiction_review.severity_levels.map((level) => (
            <div key={level.level} className="rounded border border-zinc-800 bg-zinc-900/70 px-2 py-1.5">
              <div className="flex items-center justify-between gap-2">
                <span className="text-xs text-zinc-200">{label(level.level)}</span>
                <Badge variant="outline" className={`text-[10px] ${tone(level.level)}`}>human review</Badge>
              </div>
              <p className="mt-1 text-[10px] text-zinc-500">{level.rule}</p>
            </div>
          ))}
          {contradictionItems.map((item) => (
            <div key={`${item.item_id}-contradiction`} className="rounded border border-amber-500/20 bg-amber-500/5 px-2 py-1.5 text-[11px] text-amber-100">
              {item.item_id} / {label(item.review_state)} / score {item.priority_score}
            </div>
          ))}
        </section>

        <section className="rounded-md border border-zinc-800 bg-zinc-950/70 p-3 space-y-2">
          <p className="text-xs font-semibold text-zinc-100 flex items-center gap-2">
            <ShieldCheck className="h-3.5 w-3.5 text-emerald-300" />
            Evidence Navigator
          </p>
          {data.queues.evidence_navigation.groups.map((group) => (
            <div key={group.item_type} className="flex items-center justify-between rounded border border-zinc-800 bg-zinc-900/70 px-2 py-1.5">
              <span className="text-xs text-zinc-200">{label(group.item_type)}</span>
              <Badge variant="outline" className="text-[10px]">{group.count}</Badge>
            </div>
          ))}
          {evidenceItems.map((item) => (
            <div key={`${item.item_id}-evidence`} className="rounded border border-zinc-800 bg-zinc-900/70 px-2 py-1.5 text-[11px] text-zinc-300">
              {item.item_id} / {label(item.staleness_indicator)} / {item.locked_restricted_involved ? "metadata only restricted" : "metadata safe"}
            </div>
          ))}
        </section>
      </div>

      <div className="grid gap-4 xl:grid-cols-2">
        <section className="rounded-md border border-zinc-800 bg-zinc-950/70 p-3 space-y-2">
          <p className="text-xs font-semibold text-zinc-100 flex items-center gap-2">
            <BarChart3 className="h-3.5 w-3.5 text-blue-300" />
            Review Analytics
          </p>
          <div className="grid gap-2 sm:grid-cols-2">
            <Metric label="Baseline Queue" value={data.review_analytics.throughput_model.baseline_queue_depth} />
            <Metric label="Human Review Required" value={data.review_analytics.throughput_model.human_review_required} />
            <Metric label="Safe Auto Resolutions" value={data.review_analytics.throughput_model.safe_auto_resolutions} />
            <Metric label="Completed This Phase" value={data.review_analytics.throughput_model.completed_this_phase} />
          </div>
          <div className="flex flex-wrap gap-1">
            {data.review_analytics.confidence_distribution.map((row) => (
              <Badge key={row.state} variant="outline" className={`text-[10px] ${tone(row.state)}`}>
                {label(row.state)} {row.count}
              </Badge>
            ))}
            {data.review_analytics.sla_distribution.map((row) => (
              <Badge key={row.sla_band} variant="outline" className={`text-[10px] ${tone(row.sla_band)}`}>
                {label(row.sla_band)} {row.count}
              </Badge>
            ))}
          </div>
        </section>

        <section className="rounded-md border border-zinc-800 bg-zinc-950/70 p-3 space-y-2">
          <p className="text-xs font-semibold text-zinc-100 flex items-center gap-2">
            <Activity className="h-3.5 w-3.5 text-cyan-300" />
            Controlled Pilot Readiness
          </p>
          <div className="grid gap-2 sm:grid-cols-2">
            <Metric label="Internal Review Ready" value={data.pilot_readiness.controlled_internal_review_ready ? "Yes" : "No"} />
            <Metric label="External Use Enabled" value={data.pilot_readiness.public_or_external_use_enabled ? "Yes" : "No"} />
          </div>
          <div className="flex flex-wrap gap-1">
            {data.pilot_readiness.required_controls.map((control) => (
              <Badge key={control} variant="outline" className="bg-emerald-500/10 text-emerald-300 border-emerald-500/30 text-[10px]">
                {label(control)}
              </Badge>
            ))}
            {data.pilot_readiness.forbidden_operations.map((operation) => (
              <Badge key={operation} variant="outline" className="bg-red-500/10 text-red-300 border-red-500/30 text-[10px]">
                forbidden {label(operation)}
              </Badge>
            ))}
          </div>
        </section>
      </div>

      <section className="rounded-md border border-zinc-800 bg-zinc-950/70 p-3 space-y-2">
        <p className="text-xs font-semibold text-zinc-100 flex items-center gap-2">
          <Activity className="h-3.5 w-3.5 text-red-300" />
          Escalation & Incident Readiness
        </p>
        <div className="grid gap-2 sm:grid-cols-3">
          <Metric label="Incident Status" value={label(data.reviewer_operations.incident_readiness.status)} />
          <Metric label="Rollback Required" value={data.reviewer_operations.incident_readiness.rollback_required ? "Yes" : "No"} />
          <Metric label="Escalation Model" value={label(data.reviewer_operations.escalation_governance.model)} />
        </div>
        <div className="flex flex-wrap gap-1">
          {data.reviewer_operations.escalation_governance.distribution.map((row) => (
            <Badge key={row.escalation_state} variant="outline" className={`text-[10px] ${tone(row.escalation_state)}`}>
              {label(row.escalation_state)} {row.count}
            </Badge>
          ))}
          {data.reviewer_operations.incident_readiness.stop_conditions.map((condition) => (
            <Badge key={condition} variant="outline" className="bg-red-500/10 text-red-300 border-red-500/30 text-[10px]">
              stop {label(condition)}
            </Badge>
          ))}
        </div>
      </section>
    </div>
  );
}
