"use client";

import { useState, useCallback } from "react";
import {
  useFleetStatus,
  useUpdateSplit,
  useUpdateMarkup,
  useAdminPendingCapex,
  useAdminApproveCapex,
  useAdminRejectCapex,
  useDispatchCapitalCall,
  useOnboardOwner,
  useAdminMarketingBudgets,
  type FleetProperty,
  type CapitalCallResult,
  type OnboardOwnerPayload,
  type OnboardOwnerResponse,
} from "@/lib/hooks";
import ContractManagementPanel from "./components/ContractManagementPanel";
import DisputeExceptionDesk from "./components/DisputeExceptionDesk";
import {
  Card,
  CardContent,
  CardDescription,
  CardHeader,
  CardTitle,
} from "@/components/ui/card";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import {
  AlertCircle,
  ArrowLeft,
  BarChart3,
  Building2,
  CheckCircle2,
  ClipboardCopy,
  DollarSign,
  ExternalLink,
  FileText,
  Link2,
  Loader2,
  Mail,
  PiggyBank,
  Shield,
  ShieldAlert,
  Target,
  TrendingUp,
  UserPlus,
  Wrench,
  XCircle,
} from "lucide-react";

function fmt(n: number | null | undefined): string {
  if (n == null) return "0.00";
  return n.toLocaleString(undefined, {
    minimumFractionDigits: 2,
    maximumFractionDigits: 2,
  });
}

function HealthIcon({ health }: { health: string | undefined }) {
  if (health === "overdraft")
    return <AlertCircle className="h-5 w-5 text-red-500" />;
  if (health === "warning")
    return <AlertCircle className="h-5 w-5 text-amber-500" />;
  return <CheckCircle2 className="h-5 w-5 text-emerald-500" />;
}

function CapexReviewSection({ propertyId }: { propertyId: string }) {
  const { data, isLoading } = useAdminPendingCapex(propertyId);
  const approveMutation = useAdminApproveCapex();
  const rejectMutation = useAdminRejectCapex();
  const dispatchMutation = useDispatchCapitalCall();

  const [rejectingId, setRejectingId] = useState<number | null>(null);
  const [rejectReason, setRejectReason] = useState("");
  const [dispatchedLinks, setDispatchedLinks] = useState<
    Record<number, CapitalCallResult>
  >({});

  if (isLoading) {
    return (
      <Card className="md:col-span-2">
        <CardContent className="flex items-center justify-center py-8 gap-2 text-muted-foreground">
          <Loader2 className="h-4 w-4 animate-spin" />
          Loading pending CapEx items...
        </CardContent>
      </Card>
    );
  }

  const items = data?.items ?? [];
  if (items.length === 0) return null;

  return (
    <Card className="md:col-span-2 border-amber-500/30">
      <CardHeader className="pb-3">
        <CardTitle className="text-base flex items-center gap-2">
          <Wrench className="h-4 w-4 text-amber-500" />
          CapEx Review — {items.length} Pending Item
          {items.length !== 1 ? "s" : ""}
        </CardTitle>
        <CardDescription>
          Approve to commit journal lines, reject to discard, or dispatch a
          Capital Call to collect funds from the owner via Stripe
        </CardDescription>
      </CardHeader>
      <CardContent className="space-y-3">
        {items.map((item) => {
          const markup = item.total_owner_charge - item.amount;
          const dispatched = dispatchedLinks[item.id];
          const isRejecting = rejectingId === item.id;

          return (
            <div
              key={item.id}
              className="rounded-lg border border-border/50 p-4 space-y-3"
            >
              <div className="flex items-start justify-between">
                <div>
                  <p className="font-medium">{item.vendor}</p>
                  <p className="text-sm text-muted-foreground">
                    {item.description || "Maintenance expense"}
                  </p>
                  {item.created_at && (
                    <p className="text-xs text-muted-foreground mt-1">
                      Staged {new Date(item.created_at).toLocaleDateString()}
                    </p>
                  )}
                </div>
                <Badge variant="secondary" className="text-amber-500 shrink-0">
                  PENDING
                </Badge>
              </div>

              <div className="grid grid-cols-3 gap-3 text-sm">
                <div className="rounded-md bg-muted/50 p-2.5">
                  <p className="text-xs text-muted-foreground">Invoice</p>
                  <p className="font-mono font-medium">${fmt(item.amount)}</p>
                </div>
                <div className="rounded-md bg-muted/50 p-2.5">
                  <p className="text-xs text-muted-foreground">PM Markup</p>
                  <p className="font-mono font-medium">${fmt(markup)}</p>
                </div>
                <div className="rounded-md bg-emerald-500/10 p-2.5">
                  <p className="text-xs text-muted-foreground">Total Due</p>
                  <p className="font-mono font-bold text-emerald-500">
                    ${fmt(item.total_owner_charge)}
                  </p>
                </div>
              </div>

              {dispatched && (
                <div className="rounded-md bg-emerald-500/10 border border-emerald-500/20 p-3 space-y-1">
                  <div className="flex items-center gap-2 text-sm text-emerald-500">
                    <Mail className="h-4 w-4" />
                    Capital call sent to {dispatched.email_sent_to}
                  </div>
                  <a
                    href={dispatched.payment_link_url}
                    target="_blank"
                    rel="noopener noreferrer"
                    className="flex items-center gap-1 text-xs text-blue-400 hover:underline"
                  >
                    <ExternalLink className="h-3 w-3" />
                    Stripe Payment Link
                  </a>
                </div>
              )}

              {isRejecting && (
                <div className="flex items-center gap-2">
                  <Input
                    placeholder="Rejection reason..."
                    value={rejectReason}
                    onChange={(e) => setRejectReason(e.target.value)}
                    className="flex-1 text-sm"
                  />
                  <Button
                    size="sm"
                    variant="destructive"
                    disabled={!rejectReason.trim() || rejectMutation.isPending}
                    onClick={() => {
                      rejectMutation.mutate(
                        { stagingId: item.id, reason: rejectReason },
                        {
                          onSuccess: () => {
                            setRejectingId(null);
                            setRejectReason("");
                          },
                        },
                      );
                    }}
                  >
                    {rejectMutation.isPending ? (
                      <Loader2 className="h-3 w-3 animate-spin" />
                    ) : (
                      "Confirm Reject"
                    )}
                  </Button>
                  <Button
                    size="sm"
                    variant="ghost"
                    onClick={() => {
                      setRejectingId(null);
                      setRejectReason("");
                    }}
                  >
                    Cancel
                  </Button>
                </div>
              )}

              {!dispatched && !isRejecting && (
                <div className="flex items-center gap-2 pt-1">
                  <Button
                    size="sm"
                    className="bg-emerald-600 hover:bg-emerald-700"
                    disabled={approveMutation.isPending}
                    onClick={() =>
                      approveMutation.mutate({ stagingId: item.id })
                    }
                  >
                    {approveMutation.isPending ? (
                      <Loader2 className="h-3 w-3 animate-spin mr-1" />
                    ) : (
                      <CheckCircle2 className="h-3 w-3 mr-1" />
                    )}
                    Approve
                  </Button>
                  <Button
                    size="sm"
                    variant="destructive"
                    onClick={() => setRejectingId(item.id)}
                  >
                    <XCircle className="h-3 w-3 mr-1" />
                    Reject
                  </Button>
                  <Button
                    size="sm"
                    variant="outline"
                    className="border-amber-500/50 text-amber-500 hover:bg-amber-500/10"
                    disabled={dispatchMutation.isPending}
                    onClick={() =>
                      dispatchMutation.mutate(
                        { stagingId: item.id },
                        {
                          onSuccess: (result) => {
                            setDispatchedLinks((prev) => ({
                              ...prev,
                              [item.id]: result,
                            }));
                          },
                        },
                      )
                    }
                  >
                    {dispatchMutation.isPending ? (
                      <Loader2 className="h-3 w-3 animate-spin mr-1" />
                    ) : (
                      <DollarSign className="h-3 w-3 mr-1" />
                    )}
                    Dispatch Capital Call
                  </Button>
                </div>
              )}
            </div>
          );
        })}
      </CardContent>
    </Card>
  );
}

function MasterOwnerCard({
  property,
  onBack,
}: {
  property: FleetProperty;
  onBack: () => void;
}) {
  const splitMutation = useUpdateSplit();
  const markupMutation = useUpdateMarkup();

  const [ownerPct, setOwnerPct] = useState(property.owner_pct ?? 65);
  const [pmPct, setPmPct] = useState(property.pm_pct ?? 35);
  const [markupPct, setMarkupPct] = useState(property.markup_pct ?? 23);

  function handleOwnerPctChange(val: string) {
    const o = parseFloat(val) || 0;
    setOwnerPct(o);
    setPmPct(Math.round((100 - o) * 100) / 100);
  }

  function handlePmPctChange(val: string) {
    const p = parseFloat(val) || 0;
    setPmPct(p);
    setOwnerPct(Math.round((100 - p) * 100) / 100);
  }

  return (
    <div className="space-y-6">
      <Button variant="ghost" onClick={onBack} className="gap-2">
        <ArrowLeft className="h-4 w-4" /> Back to Fleet Matrix
      </Button>

      <div className="flex items-center gap-3">
        <Building2 className="h-6 w-6 text-primary" />
        <div>
          <h1 className="text-2xl font-bold tracking-tight">
            {property.name}
          </h1>
          <p className="text-sm text-muted-foreground">
            {property.owner_name}
            {property.owner_email ? ` — ${property.owner_email}` : ""}
          </p>
        </div>
        <Badge
          variant={
            property.health === "overdraft"
              ? "destructive"
              : property.health === "warning"
                ? "secondary"
                : "default"
          }
          className="ml-auto"
        >
          {property.health?.toUpperCase() ?? "UNKNOWN"}
        </Badge>
      </div>

      <div className="grid gap-6 md:grid-cols-2">
        {/* Financial Controls */}
        <Card>
          <CardHeader className="pb-3">
            <CardTitle className="text-base">Revenue Split Controls</CardTitle>
            <CardDescription>
              Owner / PM commission split (must total 100%)
            </CardDescription>
          </CardHeader>
          <CardContent className="space-y-4">
            <div className="flex items-center gap-3">
              <div className="space-y-1">
                <label className="text-xs text-muted-foreground">
                  Owner %
                </label>
                <Input
                  type="number"
                  step="0.5"
                  min="0"
                  max="100"
                  value={ownerPct}
                  onChange={(e) => handleOwnerPctChange(e.target.value)}
                  className="w-24 font-mono"
                />
              </div>
              <span className="text-muted-foreground pt-5">/</span>
              <div className="space-y-1">
                <label className="text-xs text-muted-foreground">PM %</label>
                <Input
                  type="number"
                  step="0.5"
                  min="0"
                  max="100"
                  value={pmPct}
                  onChange={(e) => handlePmPctChange(e.target.value)}
                  className="w-24 font-mono"
                />
              </div>
              <Button
                className="mt-5"
                onClick={() =>
                  splitMutation.mutate({
                    propertyId: property.property_id,
                    ownerPct,
                    pmPct,
                  })
                }
                disabled={
                  splitMutation.isPending ||
                  Math.round((ownerPct + pmPct) * 100) !== 10000
                }
              >
                {splitMutation.isPending ? (
                  <Loader2 className="h-4 w-4 animate-spin" />
                ) : (
                  "Save Split"
                )}
              </Button>
            </div>
            {Math.round((ownerPct + pmPct) * 100) !== 10000 && (
              <p className="text-xs text-red-400">
                Split totals {(ownerPct + pmPct).toFixed(2)}% — must be 100.00%
              </p>
            )}
            {property.split_effective_date && (
              <p className="text-xs text-muted-foreground">
                Current split effective since {property.split_effective_date}
              </p>
            )}
          </CardContent>
        </Card>

        {/* CapEx Markup */}
        <Card>
          <CardHeader className="pb-3">
            <CardTitle className="text-base">CapEx PM Markup</CardTitle>
            <CardDescription>
              Markup percentage applied to owner-chargeable contractor invoices
            </CardDescription>
          </CardHeader>
          <CardContent className="space-y-4">
            <div className="flex items-center gap-3">
              <div className="space-y-1">
                <label className="text-xs text-muted-foreground">
                  Markup %
                </label>
                <Input
                  type="number"
                  step="0.5"
                  min="0"
                  max="100"
                  value={markupPct}
                  onChange={(e) =>
                    setMarkupPct(parseFloat(e.target.value) || 0)
                  }
                  className="w-24 font-mono"
                />
              </div>
              <Button
                variant="secondary"
                className="mt-5"
                onClick={() =>
                  markupMutation.mutate({
                    propertyId: property.property_id,
                    markupPct,
                  })
                }
                disabled={markupMutation.isPending}
              >
                {markupMutation.isPending ? (
                  <Loader2 className="h-4 w-4 animate-spin" />
                ) : (
                  "Update Markup"
                )}
              </Button>
            </div>
          </CardContent>
        </Card>

        {/* Trust Balance Detail */}
        <Card>
          <CardHeader className="pb-3">
            <CardTitle className="text-base">Trust Account</CardTitle>
          </CardHeader>
          <CardContent className="space-y-2">
            {[
              {
                label: "Owner Funds",
                value: property.trust_owner_funds,
                negative: property.trust_owner_funds < 0,
              },
              {
                label: "Operating Funds",
                value: property.trust_operating_funds,
                negative: property.trust_operating_funds < 0,
              },
              { label: "Escrow", value: property.trust_escrow },
              { label: "Security Deposits", value: property.trust_security_deps },
            ].map((row) => (
              <div
                key={row.label}
                className="flex justify-between items-center p-2.5 rounded-md bg-muted/50"
              >
                <span className="text-sm text-muted-foreground">
                  {row.label}
                </span>
                <span
                  className={`font-mono text-sm font-medium ${row.negative ? "text-red-400" : ""}`}
                >
                  ${fmt(row.value)}
                </span>
              </div>
            ))}
          </CardContent>
        </Card>

        {/* MTD Performance */}
        <Card>
          <CardHeader className="pb-3">
            <CardTitle className="text-base">Month-to-Date</CardTitle>
          </CardHeader>
          <CardContent className="space-y-2">
            <div className="flex justify-between items-center p-2.5 rounded-md bg-muted/50">
              <span className="text-sm text-muted-foreground">
                PM Revenue (4100)
              </span>
              <span className="font-mono text-sm font-medium text-emerald-500">
                ${fmt(property.mtd_pm_revenue)}
              </span>
            </div>
            <div className="flex justify-between items-center p-2.5 rounded-md bg-muted/50">
              <span className="text-sm text-muted-foreground">
                Reservations
              </span>
              <span className="font-mono text-sm font-medium">
                {property.mtd_reservations ?? 0}
              </span>
            </div>
            <div className="flex justify-between items-center p-2.5 rounded-md bg-muted/50">
              <span className="text-sm text-muted-foreground">
                Pending CapEx
              </span>
              <span className="font-mono text-sm font-medium text-amber-400">
                {property.pending_capex_count ?? 0} items — $
                {fmt(property.pending_capex_total)}
              </span>
            </div>
          </CardContent>
        </Card>

        {/* CapEx Review Section — shows when there are pending items */}
        {(property.pending_capex_count ?? 0) > 0 && (
          <CapexReviewSection propertyId={property.property_id} />
        )}
      </div>
    </div>
  );
}

function OnboardOwnerPanel({
  fleet,
  onComplete,
  onGenerateContract,
}: {
  fleet: FleetProperty[];
  onComplete: () => void;
  onGenerateContract?: (ownerId: string) => void;
}) {
  const onboardMutation = useOnboardOwner();

  const [ownerName, setOwnerName] = useState("");
  const [email, setEmail] = useState("");
  const [phone, setPhone] = useState("");
  const [slOwnerId, setSlOwnerId] = useState("");
  const [selectedPids, setSelectedPids] = useState<string[]>([]);
  const [ownerPct, setOwnerPct] = useState(65);
  const [pmPct, setPmPct] = useState(35);
  const [markupPct, setMarkupPct] = useState(23);
  const [contractPath, setContractPath] = useState("");
  const [result, setResult] = useState<OnboardOwnerResponse | null>(null);
  const [copied, setCopied] = useState(false);

  const handleOwnerPctChange = useCallback((val: string) => {
    const o = parseFloat(val) || 0;
    setOwnerPct(o);
    setPmPct(Math.round((100 - o) * 100) / 100);
  }, []);

  const handlePmPctChange = useCallback((val: string) => {
    const p = parseFloat(val) || 0;
    setPmPct(p);
    setOwnerPct(Math.round((100 - p) * 100) / 100);
  }, []);

  function toggleProperty(pid: string) {
    setSelectedPids((prev) =>
      prev.includes(pid) ? prev.filter((p) => p !== pid) : [...prev, pid],
    );
  }

  function handleSubmit() {
    const payload: OnboardOwnerPayload = {
      owner_name: ownerName.trim(),
      email: email.trim(),
      sl_owner_id: slOwnerId.trim(),
      property_ids: selectedPids,
      owner_pct: ownerPct,
      pm_pct: pmPct,
      markup_pct: markupPct,
    };
    if (phone.trim()) payload.phone = phone.trim();
    if (contractPath.trim()) payload.contract_nas_path = contractPath.trim();

    onboardMutation.mutate(payload, {
      onSuccess: (data) => setResult(data),
    });
  }

  async function copyLink() {
    if (!result?.magic_link_url) return;
    try {
      await navigator.clipboard.writeText(result.magic_link_url);
      setCopied(true);
      setTimeout(() => setCopied(false), 2000);
    } catch {
      /* clipboard not available */
    }
  }

  const splitValid = Math.round((ownerPct + pmPct) * 100) === 10000;
  const formValid =
    ownerName.trim() &&
    email.trim() &&
    slOwnerId.trim() &&
    selectedPids.length > 0 &&
    splitValid;

  if (result) {
    return (
      <div className="space-y-6">
        <div className="flex items-center gap-3">
          <div className="h-10 w-10 rounded-full bg-emerald-500/20 flex items-center justify-center">
            <CheckCircle2 className="h-5 w-5 text-emerald-500" />
          </div>
          <div>
            <h2 className="text-xl font-bold">Ledger Initialized</h2>
            <p className="text-sm text-muted-foreground">
              {result.owner_name} onboarded across{" "}
              {result.properties_seeded.length} propert
              {result.properties_seeded.length === 1 ? "y" : "ies"}
            </p>
          </div>
          <Badge className="ml-auto bg-emerald-500/20 text-emerald-500 border-emerald-500/30">
            ONBOARDED
          </Badge>
        </div>

        <div className="grid gap-4 md:grid-cols-3">
          <Card>
            <CardContent className="pt-4 pb-3">
              <p className="text-xs text-muted-foreground">Revenue Split</p>
              <p className="text-lg font-bold font-mono">
                {result.splits.owner_pct}/{result.splits.pm_pct}
              </p>
            </CardContent>
          </Card>
          <Card>
            <CardContent className="pt-4 pb-3">
              <p className="text-xs text-muted-foreground">CapEx Markup</p>
              <p className="text-lg font-bold font-mono">
                {result.markup_pct}%
              </p>
            </CardContent>
          </Card>
          <Card>
            <CardContent className="pt-4 pb-3">
              <p className="text-xs text-muted-foreground">Sub-Ledgers</p>
              <p className="text-lg font-bold font-mono">
                {result.sub_ledger_accounts.length}
              </p>
            </CardContent>
          </Card>
        </div>

        <Card>
          <CardHeader className="pb-3">
            <CardTitle className="text-base flex items-center gap-2">
              <Link2 className="h-4 w-4 text-emerald-500" />
              Owner Magic Link
            </CardTitle>
            <CardDescription>
              Share this link with the owner for immediate portal access (24h
              expiry)
            </CardDescription>
          </CardHeader>
          <CardContent>
            <div className="flex items-center gap-2">
              <Input
                readOnly
                value={result.magic_link_url}
                className="font-mono text-xs"
              />
              <Button variant="outline" size="sm" onClick={copyLink}>
                {copied ? (
                  <CheckCircle2 className="h-4 w-4 text-emerald-500" />
                ) : (
                  <ClipboardCopy className="h-4 w-4" />
                )}
              </Button>
            </div>
          </CardContent>
        </Card>

        {result.contract_ingested && (
          <Badge variant="secondary" className="text-emerald-500">
            Contract ingestion queued
          </Badge>
        )}

        <div className="flex gap-3 pt-2">
          <Button variant="outline" onClick={onComplete}>
            <ArrowLeft className="h-4 w-4 mr-1" />
            Back to Fleet Matrix
          </Button>
          {onGenerateContract && result.owner_id && (
            <Button
              className="bg-blue-600 hover:bg-blue-700"
              onClick={() => onGenerateContract(result.owner_id)}
            >
              <FileText className="h-4 w-4 mr-1" />
              Generate Contract
            </Button>
          )}
          <Button
            onClick={() => {
              setResult(null);
              setOwnerName("");
              setEmail("");
              setPhone("");
              setSlOwnerId("");
              setSelectedPids([]);
              setOwnerPct(65);
              setPmPct(35);
              setMarkupPct(23);
              setContractPath("");
            }}
          >
            <UserPlus className="h-4 w-4 mr-1" />
            Onboard Another
          </Button>
        </div>
      </div>
    );
  }

  return (
    <div className="space-y-6">
      <div className="flex items-center gap-3">
        <UserPlus className="h-6 w-6 text-primary" />
        <div>
          <h2 className="text-xl font-bold tracking-tight">Onboard New Owner</h2>
          <p className="text-sm text-muted-foreground">
            Seed ledger tables, set commission splits, and generate a magic-link
            login
          </p>
        </div>
      </div>

      <div className="grid gap-6 md:grid-cols-2">
        {/* Owner Info */}
        <Card>
          <CardHeader className="pb-3">
            <CardTitle className="text-base">Owner Information</CardTitle>
          </CardHeader>
          <CardContent className="space-y-3">
            <div className="space-y-1">
              <label className="text-xs text-muted-foreground">Owner Name</label>
              <Input
                placeholder="Jane Doe"
                value={ownerName}
                onChange={(e) => setOwnerName(e.target.value)}
              />
            </div>
            <div className="space-y-1">
              <label className="text-xs text-muted-foreground">Email</label>
              <Input
                type="email"
                placeholder="owner@example.com"
                value={email}
                onChange={(e) => setEmail(e.target.value)}
              />
            </div>
            <div className="space-y-1">
              <label className="text-xs text-muted-foreground">
                Phone (optional)
              </label>
              <Input
                type="tel"
                placeholder="+1 555-123-4567"
                value={phone}
                onChange={(e) => setPhone(e.target.value)}
              />
            </div>
            <div className="space-y-1">
              <label className="text-xs text-muted-foreground">
                Streamline Owner ID
              </label>
              <Input
                placeholder="e.g. 12345"
                value={slOwnerId}
                onChange={(e) => setSlOwnerId(e.target.value)}
              />
            </div>
          </CardContent>
        </Card>

        {/* Property Multi-Select */}
        <Card>
          <CardHeader className="pb-3">
            <CardTitle className="text-base">
              Assign Properties
              {selectedPids.length > 0 && (
                <Badge variant="secondary" className="ml-2">
                  {selectedPids.length} selected
                </Badge>
              )}
            </CardTitle>
            <CardDescription>
              Select the properties this owner will manage
            </CardDescription>
          </CardHeader>
          <CardContent>
            <div className="max-h-64 overflow-y-auto space-y-1 rounded-md border border-border/50 p-2">
              {fleet.map((p) => {
                const isSelected = selectedPids.includes(p.property_id);
                return (
                  <button
                    key={p.property_id}
                    type="button"
                    onClick={() => toggleProperty(p.property_id)}
                    className={`w-full flex items-center justify-between rounded-md px-3 py-2 text-sm transition-colors ${
                      isSelected
                        ? "bg-emerald-500/15 text-emerald-400 border border-emerald-500/30"
                        : "hover:bg-muted/50"
                    }`}
                  >
                    <span>{p.name}</span>
                    <span className="font-mono text-xs text-muted-foreground">
                      {p.property_id}
                    </span>
                  </button>
                );
              })}
              {fleet.length === 0 && (
                <p className="text-center py-4 text-muted-foreground text-sm">
                  No properties in fleet
                </p>
              )}
            </div>
          </CardContent>
        </Card>

        {/* Revenue Split + Markup */}
        <Card>
          <CardHeader className="pb-3">
            <CardTitle className="text-base">Financial Terms</CardTitle>
          </CardHeader>
          <CardContent className="space-y-4">
            <div>
              <label className="text-xs text-muted-foreground block mb-2">
                Revenue Split — Owner / PM
              </label>
              <div className="flex items-center gap-3">
                <div className="space-y-1">
                  <label className="text-xs text-muted-foreground">
                    Owner %
                  </label>
                  <Input
                    type="number"
                    step="0.5"
                    min="0"
                    max="100"
                    value={ownerPct}
                    onChange={(e) => handleOwnerPctChange(e.target.value)}
                    className="w-24 font-mono"
                  />
                </div>
                <span className="text-muted-foreground pt-5">/</span>
                <div className="space-y-1">
                  <label className="text-xs text-muted-foreground">PM %</label>
                  <Input
                    type="number"
                    step="0.5"
                    min="0"
                    max="100"
                    value={pmPct}
                    onChange={(e) => handlePmPctChange(e.target.value)}
                    className="w-24 font-mono"
                  />
                </div>
              </div>
              {!splitValid && (
                <p className="text-xs text-red-400 mt-1">
                  Split totals {(ownerPct + pmPct).toFixed(2)}% — must be
                  100.00%
                </p>
              )}
            </div>
            <div>
              <label className="text-xs text-muted-foreground block mb-2">
                CapEx PM Markup
              </label>
              <div className="flex items-center gap-3">
                <Input
                  type="number"
                  step="0.5"
                  min="0"
                  max="100"
                  value={markupPct}
                  onChange={(e) =>
                    setMarkupPct(parseFloat(e.target.value) || 0)
                  }
                  className="w-24 font-mono"
                />
                <span className="text-sm text-muted-foreground">%</span>
              </div>
            </div>
          </CardContent>
        </Card>

        {/* Contract NAS Path */}
        <Card>
          <CardHeader className="pb-3">
            <CardTitle className="text-base">Management Contract</CardTitle>
            <CardDescription>
              Optional: NAS path to the signed management contract for Qdrant
              ingestion
            </CardDescription>
          </CardHeader>
          <CardContent>
            <Input
              placeholder="/mnt/fortress_nas/sectors/legal/..."
              value={contractPath}
              onChange={(e) => setContractPath(e.target.value)}
              className="font-mono text-xs"
            />
          </CardContent>
        </Card>
      </div>

      <div className="flex items-center gap-3 pt-2">
        <Button
          onClick={handleSubmit}
          disabled={!formValid || onboardMutation.isPending}
          className="bg-emerald-600 hover:bg-emerald-700"
        >
          {onboardMutation.isPending ? (
            <Loader2 className="h-4 w-4 animate-spin mr-2" />
          ) : (
            <UserPlus className="h-4 w-4 mr-2" />
          )}
          Onboard Owner
        </Button>
        <Button variant="outline" onClick={onComplete}>
          Cancel
        </Button>
      </div>
    </div>
  );
}

export default function AdminOperationsGlass() {
  const { data, isLoading, error } = useFleetStatus();
  const { data: mktgBudgets } = useAdminMarketingBudgets();
  const [selectedProperty, setSelectedProperty] =
    useState<FleetProperty | null>(null);
  const [showOnboard, setShowOnboard] = useState(false);
  const [showContracts, setShowContracts] = useState(false);
  const [showDisputes, setShowDisputes] = useState(false);
  const [contractPrefillOwnerId, setContractPrefillOwnerId] = useState<
    string | undefined
  >();

  if (isLoading) {
    return (
      <div className="flex items-center justify-center h-64 gap-2 text-muted-foreground">
        <Loader2 className="h-5 w-5 animate-spin" />
        Initializing Admin Operations Glass...
      </div>
    );
  }

  if (error) {
    return (
      <div className="flex items-center justify-center h-64 gap-2 text-red-400">
        <AlertCircle className="h-5 w-5" />
        Fleet status unavailable: {(error as Error)?.message ?? "Unknown error"}
      </div>
    );
  }

  if (selectedProperty) {
    return (
      <MasterOwnerCard
        property={selectedProperty}
        onBack={() => setSelectedProperty(null)}
      />
    );
  }

  const fleet = data?.fleet ?? [];
  const totals = data?.global_totals;

  if (showOnboard) {
    return (
      <OnboardOwnerPanel
        fleet={fleet}
        onComplete={() => setShowOnboard(false)}
        onGenerateContract={(ownerId) => {
          setShowOnboard(false);
          setContractPrefillOwnerId(ownerId);
          setShowContracts(true);
        }}
      />
    );
  }

  if (showContracts) {
    return (
      <ContractManagementPanel
        fleet={fleet}
        prefillOwnerId={contractPrefillOwnerId}
        onBack={() => {
          setShowContracts(false);
          setContractPrefillOwnerId(undefined);
        }}
      />
    );
  }

  if (showDisputes) {
    return <DisputeExceptionDesk onBack={() => setShowDisputes(false)} />;
  }

  return (
    <div className="space-y-6">
      {/* Header */}
      <div className="flex items-center justify-between">
        <div>
          <h1 className="text-2xl font-bold tracking-tight flex items-center gap-2">
            <Shield className="h-6 w-6 text-primary" />
            Admin Operations Glass
          </h1>
          <p className="text-muted-foreground text-sm">
            Fleet-wide financial controls and property management
          </p>
        </div>
        <div className="flex gap-2">
          <Button
            variant="outline"
            onClick={() => setShowDisputes(true)}
          >
            <ShieldAlert className="h-4 w-4 mr-2" />
            Disputes
          </Button>
          <Button
            variant="outline"
            onClick={() => setShowContracts(true)}
          >
            <FileText className="h-4 w-4 mr-2" />
            Contracts
          </Button>
          <Button
            onClick={() => setShowOnboard(true)}
            className="bg-emerald-600 hover:bg-emerald-700"
          >
            <UserPlus className="h-4 w-4 mr-2" />
            Onboard Owner
          </Button>
        </div>
      </div>

      {/* Global Totals HUD */}
      <div className="grid gap-3 md:grid-cols-5">
        <Card>
          <CardContent className="pt-4 pb-3">
            <div className="flex items-center justify-between">
              <p className="text-xs text-muted-foreground">Total Trust Funds</p>
              <DollarSign className="h-3.5 w-3.5 text-blue-400" />
            </div>
            <p className="text-xl font-bold font-mono">
              ${fmt(totals?.total_owner_funds)}
            </p>
          </CardContent>
        </Card>
        <Card>
          <CardContent className="pt-4 pb-3">
            <div className="flex items-center justify-between">
              <p className="text-xs text-muted-foreground">Operating Funds</p>
              <DollarSign className="h-3.5 w-3.5 text-emerald-400" />
            </div>
            <p className="text-xl font-bold font-mono">
              ${fmt(totals?.total_operating_funds)}
            </p>
          </CardContent>
        </Card>
        <Card>
          <CardContent className="pt-4 pb-3">
            <div className="flex items-center justify-between">
              <p className="text-xs text-muted-foreground">MTD PM Revenue</p>
              <TrendingUp className="h-3.5 w-3.5 text-emerald-500" />
            </div>
            <p className="text-xl font-bold font-mono text-emerald-500">
              ${fmt(totals?.total_pm_revenue_mtd)}
            </p>
          </CardContent>
        </Card>
        <Card>
          <CardContent className="pt-4 pb-3">
            <div className="flex items-center justify-between">
              <p className="text-xs text-muted-foreground">In Overdraft</p>
              <AlertCircle className="h-3.5 w-3.5 text-red-400" />
            </div>
            <p className="text-xl font-bold font-mono text-red-400">
              {totals?.properties_in_overdraft ?? 0}
            </p>
          </CardContent>
        </Card>
        <Card>
          <CardContent className="pt-4 pb-3">
            <div className="flex items-center justify-between">
              <p className="text-xs text-muted-foreground">Pending CapEx</p>
              <Wrench className="h-3.5 w-3.5 text-amber-400" />
            </div>
            <p className="text-xl font-bold font-mono text-amber-400">
              {totals?.pending_capex_items ?? 0}
            </p>
          </CardContent>
        </Card>
      </div>

      {/* Fleet Data Grid */}
      <Card>
        <CardHeader className="pb-2">
          <CardTitle className="text-sm flex items-center gap-1.5">
            <Building2 className="h-4 w-4 text-primary" />
            Fleet Matrix — {fleet.length} Properties
          </CardTitle>
          <CardDescription>
            Click &quot;Manage&quot; to adjust commission splits and CapEx
            markups
          </CardDescription>
        </CardHeader>
        <CardContent className="p-0">
          <div className="overflow-x-auto">
            <table className="w-full text-sm">
              <thead>
                <tr className="border-b text-xs text-muted-foreground uppercase">
                  <th className="px-4 py-3 text-left font-medium">Property</th>
                  <th className="px-4 py-3 text-left font-medium">Owner</th>
                  <th className="px-4 py-3 text-center font-medium">Split</th>
                  <th className="px-4 py-3 text-right font-medium">
                    Trust Balance
                  </th>
                  <th className="px-4 py-3 text-right font-medium">
                    MTD PM Rev
                  </th>
                  <th className="px-4 py-3 text-center font-medium">Health</th>
                  <th className="px-4 py-3 text-center font-medium">Action</th>
                </tr>
              </thead>
              <tbody>
                {fleet.map((p) => (
                  <tr
                    key={p.property_id}
                    className="border-b border-border/50 hover:bg-muted/50 transition-colors"
                  >
                    <td className="px-4 py-3 font-medium">{p.name}</td>
                    <td className="px-4 py-3 text-muted-foreground">
                      {p.owner_name}
                    </td>
                    <td className="px-4 py-3 text-center font-mono text-xs">
                      {p.owner_pct ?? "—"}/{p.pm_pct ?? "—"}
                    </td>
                    <td
                      className={`px-4 py-3 text-right font-mono ${(p.trust_owner_funds ?? 0) < 0 ? "text-red-400" : ""}`}
                    >
                      ${fmt(p.trust_owner_funds)}
                    </td>
                    <td className="px-4 py-3 text-right font-mono text-emerald-500">
                      ${fmt(p.mtd_pm_revenue)}
                    </td>
                    <td className="px-4 py-3 text-center">
                      <HealthIcon health={p.health} />
                    </td>
                    <td className="px-4 py-3 text-center">
                      <Button
                        variant="outline"
                        size="sm"
                        onClick={() => setSelectedProperty(p)}
                      >
                        Manage
                      </Button>
                    </td>
                  </tr>
                ))}
                {fleet.length === 0 && (
                  <tr>
                    <td
                      colSpan={7}
                      className="px-4 py-8 text-center text-muted-foreground"
                    >
                      No properties found in fleet roster
                    </td>
                  </tr>
                )}
              </tbody>
            </table>
          </div>
        </CardContent>
      </Card>

      {/* Marketing Budgets — Direct Booking Growth Engine */}
      <Card>
        <CardHeader className="pb-3">
          <CardTitle className="text-lg flex items-center gap-2">
            <Target className="h-5 w-5 text-emerald-500" />
            Marketing Budgets — Direct Booking Engine
          </CardTitle>
          <CardDescription>
            Owner-funded ad escrow balances, allocation settings, and campaign
            attribution metrics across the fleet.
          </CardDescription>
        </CardHeader>
        <CardContent>
          {/* Fleet-wide summary */}
          <div className="grid gap-3 md:grid-cols-4 mb-4">
            <div className="rounded-lg border p-3">
              <div className="flex items-center gap-1.5 text-muted-foreground mb-1">
                <PiggyBank className="h-3.5 w-3.5" />
                <span className="text-xs">Total Escrow (Acct 2400)</span>
              </div>
              <p className="text-xl font-bold tabular-nums">
                ${fmt(mktgBudgets?.fleet_totals?.total_escrow)}
              </p>
            </div>
            <div className="rounded-lg border p-3">
              <div className="flex items-center gap-1.5 text-muted-foreground mb-1">
                <DollarSign className="h-3.5 w-3.5" />
                <span className="text-xs">Total Ad Spend</span>
              </div>
              <p className="text-xl font-bold tabular-nums">
                ${fmt(mktgBudgets?.fleet_totals?.total_ad_spend)}
              </p>
            </div>
            <div className="rounded-lg border p-3">
              <div className="flex items-center gap-1.5 text-muted-foreground mb-1">
                <Building2 className="h-3.5 w-3.5" />
                <span className="text-xs">Properties Enrolled</span>
              </div>
              <p className="text-xl font-bold tabular-nums">
                {mktgBudgets?.fleet_totals?.properties_enrolled ?? 0}
                <span className="text-sm font-normal text-muted-foreground">
                  {" "}/ {mktgBudgets?.fleet_totals?.properties_total ?? 0}
                </span>
              </p>
            </div>
            <div className="rounded-lg border p-3">
              <div className="flex items-center gap-1.5 text-muted-foreground mb-1">
                <BarChart3 className="h-3.5 w-3.5" />
                <span className="text-xs">Fleet Avg ROAS</span>
              </div>
              <p className="text-xl font-bold tabular-nums text-emerald-500">
                {(() => {
                  const props = mktgBudgets?.properties ?? [];
                  const withRoas = props.filter(
                    (p) => p.latest_attribution?.roas && p.latest_attribution.roas > 0
                  );
                  if (withRoas.length === 0) return "—";
                  const avg =
                    withRoas.reduce(
                      (s, p) => s + (p.latest_attribution?.roas ?? 0),
                      0
                    ) / withRoas.length;
                  return `${avg.toFixed(1)}x`;
                })()}
              </p>
            </div>
          </div>

          {/* Per-property table */}
          {(mktgBudgets?.properties?.length ?? 0) > 0 ? (
            <div className="rounded-lg border overflow-hidden">
              <table className="w-full text-sm">
                <thead className="bg-muted/50">
                  <tr>
                    <th className="px-4 py-3 text-left font-medium">Property</th>
                    <th className="px-4 py-3 text-center font-medium">Allocation</th>
                    <th className="px-4 py-3 text-center font-medium">Status</th>
                    <th className="px-4 py-3 text-right font-medium">Escrow</th>
                    <th className="px-4 py-3 text-right font-medium">Last Spend</th>
                    <th className="px-4 py-3 text-right font-medium">ROAS</th>
                  </tr>
                </thead>
                <tbody>
                  {mktgBudgets?.properties?.map((p) => (
                    <tr
                      key={p.property_id}
                      className="border-b border-border/50 hover:bg-muted/50 transition-colors"
                    >
                      <td className="px-4 py-3 font-medium">
                        {p.property_name ?? p.property_id}
                      </td>
                      <td className="px-4 py-3 text-center font-mono text-xs">
                        {p.marketing_pct}%
                      </td>
                      <td className="px-4 py-3 text-center">
                        <Badge
                          variant="secondary"
                          className={
                            p.enabled
                              ? "bg-emerald-500/10 text-emerald-500 border-emerald-500/20"
                              : "bg-zinc-500/10 text-zinc-400"
                          }
                        >
                          {p.enabled ? "Active" : "Paused"}
                        </Badge>
                      </td>
                      <td className="px-4 py-3 text-right font-mono">
                        ${fmt(p.escrow_balance)}
                      </td>
                      <td className="px-4 py-3 text-right font-mono">
                        {p.latest_attribution
                          ? `$${fmt(p.latest_attribution.ad_spend)}`
                          : "—"}
                      </td>
                      <td className="px-4 py-3 text-right">
                        {p.latest_attribution?.roas ? (
                          <Badge
                            variant="secondary"
                            className={
                              p.latest_attribution.roas >= 3
                                ? "bg-emerald-500/10 text-emerald-500"
                                : p.latest_attribution.roas >= 1
                                  ? "bg-blue-500/10 text-blue-500"
                                  : "bg-red-500/10 text-red-400"
                            }
                          >
                            {p.latest_attribution.roas.toFixed(1)}x
                          </Badge>
                        ) : (
                          <span className="text-muted-foreground">—</span>
                        )}
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          ) : (
            <div className="text-center py-8 text-muted-foreground">
              <Target className="h-8 w-8 mx-auto mb-2 opacity-40" />
              <p className="text-sm">
                No properties have enrolled in the Direct Booking Engine yet.
              </p>
              <p className="text-xs mt-1">
                Owners can activate marketing allocation from their portal&apos;s
                Direct Booking tab.
              </p>
            </div>
          )}
        </CardContent>
      </Card>
    </div>
  );
}
