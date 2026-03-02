"use client";

import { useState, useMemo } from "react";
import {
  useManagementContracts,
  useGenerateContract,
  useGenerateProspectus,
  useSendContract,
  useProperties,
  type ManagementContract,
  type FleetProperty,
} from "@/lib/hooks";
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
import { Label } from "@/components/ui/label";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
  DialogTrigger,
} from "@/components/ui/dialog";
import {
  Sheet,
  SheetContent,
  SheetDescription,
  SheetHeader,
  SheetTitle,
} from "@/components/ui/sheet";
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@/components/ui/table";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import {
  ArrowLeft,
  CheckCircle2,
  Clock,
  Download,
  FileText,
  Loader2,
  Presentation,
  PenTool,
  Plus,
  Send,
  ShieldCheck,
} from "lucide-react";

// ---------------------------------------------------------------------------
// Helpers
// ---------------------------------------------------------------------------

const STATUS_CONFIG: Record<string, { label: string; variant: "default" | "secondary" | "destructive" | "outline" }> = {
  draft: { label: "Draft", variant: "secondary" },
  awaiting_signature: { label: "Awaiting Signature", variant: "default" },
  signed: { label: "Executed", variant: "outline" },
  expired: { label: "Expired", variant: "destructive" },
};

function StatusBadge({ status }: { status: string }) {
  const cfg = STATUS_CONFIG[status] ?? { label: status, variant: "secondary" as const };
  return <Badge variant={cfg.variant}>{cfg.label}</Badge>;
}

function fmtDate(d: string | null | undefined): string {
  if (!d) return "—";
  return new Date(d).toLocaleDateString("en-US", {
    month: "short",
    day: "numeric",
    year: "numeric",
  });
}

// ---------------------------------------------------------------------------
// Props
// ---------------------------------------------------------------------------

interface ContractManagementPanelProps {
  fleet: FleetProperty[];
  /** Pre-fill the generate form with a specific owner after onboarding */
  prefillOwnerId?: string;
  onBack: () => void;
}

// ---------------------------------------------------------------------------
// Component
// ---------------------------------------------------------------------------

export default function ContractManagementPanel({
  fleet,
  prefillOwnerId,
  onBack,
}: ContractManagementPanelProps) {
  const { data: contractsData, isLoading } = useManagementContracts();
  const { data: propertiesData } = useProperties();
  const generateMutation = useGenerateContract();
  const prospectusMutation = useGenerateProspectus();
  const sendMutation = useSendContract();

  // Generate Dialog state
  const [genOpen, setGenOpen] = useState(!!prefillOwnerId);
  const [genPropertyId, setGenPropertyId] = useState("");
  const [genOwnerId, setGenOwnerId] = useState(prefillOwnerId ?? "");
  const [genTermYears, setGenTermYears] = useState("1");
  const [genEffective, setGenEffective] = useState(
    new Date().toISOString().slice(0, 10),
  );

  // Prospectus Dialog state
  const [prosOpen, setProsOpen] = useState(false);
  const [prosPropertyId, setProsPropertyId] = useState("");
  const [prosOwnerId, setProsOwnerId] = useState(prefillOwnerId ?? "");
  const [prosTermYears, setProsTermYears] = useState("1");

  // Detail Sheet state
  const [detailContract, setDetailContract] = useState<ManagementContract | null>(null);
  const [sendEmail, setSendEmail] = useState("");
  const [sendDays, setSendDays] = useState("7");

  const contracts = contractsData?.contracts ?? [];

  const stats = useMemo(() => {
    const total = contracts.length;
    const draft = contracts.filter((c) => c.status === "draft").length;
    const awaiting = contracts.filter((c) => c.status === "awaiting_signature").length;
    const executed = contracts.filter((c) => c.status === "signed").length;
    return { total, draft, awaiting, executed };
  }, [contracts]);

  // Build a map of property_id -> property name for display
  const propertyNames = useMemo(() => {
    const map: Record<string, string> = {};
    for (const p of propertiesData ?? []) {
      map[p.id] = p.name || p.id;
    }
    for (const fp of fleet) {
      if (fp.property_id) map[fp.property_id] = fp.property_name || fp.property_id;
    }
    return map;
  }, [propertiesData, fleet]);

  function handleGenerate() {
    if (!genPropertyId || !genOwnerId) return;
    generateMutation.mutate(
      {
        owner_id: genOwnerId.trim(),
        property_id: genPropertyId,
        term_years: parseInt(genTermYears, 10) || 1,
        effective_date: genEffective || undefined,
      },
      {
        onSuccess: () => {
          setGenOpen(false);
          setGenPropertyId("");
          setGenOwnerId(prefillOwnerId ?? "");
          setGenTermYears("1");
        },
      },
    );
  }

  function handleProspectus() {
    if (!prosPropertyId || !prosOwnerId) return;
    prospectusMutation.mutate(
      {
        owner_id: prosOwnerId.trim(),
        property_id: prosPropertyId,
        term_years: parseInt(prosTermYears, 10) || 1,
      },
      {
        onSuccess: () => {
          setProsOpen(false);
          setProsPropertyId("");
          setProsOwnerId(prefillOwnerId ?? "");
          setProsTermYears("1");
        },
      },
    );
  }

  function handleSend() {
    if (!detailContract) return;
    sendMutation.mutate(
      {
        agreementId: detailContract.id,
        recipient_email: sendEmail.trim() || undefined,
        expires_days: parseInt(sendDays, 10) || 7,
      },
      {
        onSuccess: () => {
          setDetailContract(null);
          setSendEmail("");
          setSendDays("7");
        },
      },
    );
  }

  if (isLoading) {
    return (
      <div className="flex items-center justify-center h-64 gap-2 text-muted-foreground">
        <Loader2 className="h-5 w-5 animate-spin" />
        Loading contract pipeline...
      </div>
    );
  }

  return (
    <div className="space-y-6">
      {/* Header */}
      <div className="flex items-center justify-between">
        <div className="flex items-center gap-3">
          <Button variant="ghost" size="sm" onClick={onBack}>
            <ArrowLeft className="h-4 w-4" />
          </Button>
          <div>
            <h2 className="text-xl font-bold tracking-tight flex items-center gap-2">
              <FileText className="h-5 w-5 text-primary" />
              Contract Management
            </h2>
            <p className="text-sm text-muted-foreground">
              Generate, dispatch, and track management agreements
            </p>
          </div>
        </div>
        <div className="flex gap-2">
        <Dialog open={prosOpen} onOpenChange={setProsOpen}>
          <DialogTrigger asChild>
            <Button variant="outline" className="border-blue-500/40 text-blue-400 hover:bg-blue-500/10">
              <Presentation className="h-4 w-4 mr-2" />
              Generate Prospectus
            </Button>
          </DialogTrigger>
          <DialogContent className="sm:max-w-md">
            <DialogHeader>
              <DialogTitle>Generate SOTA Prospectus</DialogTitle>
              <DialogDescription>
                Creates a multi-page pitch PDF with Pro Forma projections and embedded management agreement
              </DialogDescription>
            </DialogHeader>
            <div className="grid gap-4 py-4">
              <div className="grid gap-2">
                <Label>Owner ID</Label>
                <Input
                  placeholder="UUID from onboarding"
                  value={prosOwnerId}
                  onChange={(e) => setProsOwnerId(e.target.value)}
                />
              </div>
              <div className="grid gap-2">
                <Label>Property</Label>
                <Select value={prosPropertyId} onValueChange={setProsPropertyId}>
                  <SelectTrigger>
                    <SelectValue placeholder="Select property" />
                  </SelectTrigger>
                  <SelectContent>
                    {fleet.map((fp) => (
                      <SelectItem key={fp.property_id} value={fp.property_id}>
                        {fp.property_name || fp.property_id}
                      </SelectItem>
                    ))}
                  </SelectContent>
                </Select>
              </div>
              <div className="grid gap-2">
                <Label>Term (years)</Label>
                <Input
                  type="number"
                  min={1}
                  max={10}
                  value={prosTermYears}
                  onChange={(e) => setProsTermYears(e.target.value)}
                />
              </div>
            </div>
            <DialogFooter>
              <Button
                onClick={handleProspectus}
                disabled={!prosPropertyId || !prosOwnerId.trim() || prospectusMutation.isPending}
                className="bg-blue-600 hover:bg-blue-700"
              >
                {prospectusMutation.isPending ? (
                  <Loader2 className="h-4 w-4 mr-2 animate-spin" />
                ) : (
                  <Presentation className="h-4 w-4 mr-2" />
                )}
                Generate Prospectus
              </Button>
            </DialogFooter>
          </DialogContent>
        </Dialog>
        <Dialog open={genOpen} onOpenChange={setGenOpen}>
          <DialogTrigger asChild>
            <Button className="bg-emerald-600 hover:bg-emerald-700">
              <Plus className="h-4 w-4 mr-2" />
              Generate Agreement
            </Button>
          </DialogTrigger>
          <DialogContent className="sm:max-w-md">
            <DialogHeader>
              <DialogTitle>Generate Management Agreement</DialogTitle>
              <DialogDescription>
                Creates a branded PDF using the Iron Dome templating engine
              </DialogDescription>
            </DialogHeader>
            <div className="grid gap-4 py-4">
              <div className="grid gap-2">
                <Label>Owner ID</Label>
                <Input
                  placeholder="UUID from onboarding"
                  value={genOwnerId}
                  onChange={(e) => setGenOwnerId(e.target.value)}
                />
              </div>
              <div className="grid gap-2">
                <Label>Property</Label>
                <Select value={genPropertyId} onValueChange={setGenPropertyId}>
                  <SelectTrigger>
                    <SelectValue placeholder="Select property" />
                  </SelectTrigger>
                  <SelectContent>
                    {fleet.map((fp) => (
                      <SelectItem key={fp.property_id} value={fp.property_id}>
                        {fp.property_name || fp.property_id}
                      </SelectItem>
                    ))}
                  </SelectContent>
                </Select>
              </div>
              <div className="grid grid-cols-2 gap-4">
                <div className="grid gap-2">
                  <Label>Term (years)</Label>
                  <Input
                    type="number"
                    min={1}
                    max={10}
                    value={genTermYears}
                    onChange={(e) => setGenTermYears(e.target.value)}
                  />
                </div>
                <div className="grid gap-2">
                  <Label>Effective Date</Label>
                  <Input
                    type="date"
                    value={genEffective}
                    onChange={(e) => setGenEffective(e.target.value)}
                  />
                </div>
              </div>
            </div>
            <DialogFooter>
              <Button
                onClick={handleGenerate}
                disabled={!genPropertyId || !genOwnerId.trim() || generateMutation.isPending}
              >
                {generateMutation.isPending ? (
                  <Loader2 className="h-4 w-4 mr-2 animate-spin" />
                ) : (
                  <PenTool className="h-4 w-4 mr-2" />
                )}
                Generate PDF
              </Button>
            </DialogFooter>
          </DialogContent>
        </Dialog>
        </div>
      </div>

      {/* Telemetry Cards */}
      <div className="grid gap-3 md:grid-cols-4">
        <Card>
          <CardContent className="pt-4 pb-3">
            <div className="flex items-center justify-between">
              <p className="text-xs text-muted-foreground">Total Contracts</p>
              <FileText className="h-3.5 w-3.5 text-blue-400" />
            </div>
            <p className="text-2xl font-bold font-mono">{stats.total}</p>
          </CardContent>
        </Card>
        <Card>
          <CardContent className="pt-4 pb-3">
            <div className="flex items-center justify-between">
              <p className="text-xs text-muted-foreground">Draft</p>
              <PenTool className="h-3.5 w-3.5 text-amber-400" />
            </div>
            <p className="text-2xl font-bold font-mono text-amber-400">
              {stats.draft}
            </p>
          </CardContent>
        </Card>
        <Card>
          <CardContent className="pt-4 pb-3">
            <div className="flex items-center justify-between">
              <p className="text-xs text-muted-foreground">Awaiting Signature</p>
              <Clock className="h-3.5 w-3.5 text-orange-400" />
            </div>
            <p className="text-2xl font-bold font-mono text-orange-400">
              {stats.awaiting}
            </p>
          </CardContent>
        </Card>
        <Card>
          <CardContent className="pt-4 pb-3">
            <div className="flex items-center justify-between">
              <p className="text-xs text-muted-foreground">Executed</p>
              <ShieldCheck className="h-3.5 w-3.5 text-emerald-400" />
            </div>
            <p className="text-2xl font-bold font-mono text-emerald-400">
              {stats.executed}
            </p>
          </CardContent>
        </Card>
      </div>

      {/* Contracts Table */}
      <Card>
        <CardHeader className="pb-3">
          <CardTitle className="text-base">Agreement Pipeline</CardTitle>
          <CardDescription>
            Click any row to open the detail sheet
          </CardDescription>
        </CardHeader>
        <CardContent>
          {contracts.length === 0 ? (
            <div className="flex flex-col items-center justify-center py-12 text-muted-foreground gap-2">
              <FileText className="h-8 w-8 opacity-40" />
              <p className="text-sm">No agreements generated yet</p>
            </div>
          ) : (
            <Table>
              <TableHeader>
                <TableRow>
                  <TableHead>Property</TableHead>
                  <TableHead>Type</TableHead>
                  <TableHead>Status</TableHead>
                  <TableHead>Created</TableHead>
                  <TableHead>Sent</TableHead>
                  <TableHead>Signed</TableHead>
                  <TableHead>Signer</TableHead>
                </TableRow>
              </TableHeader>
              <TableBody>
                {contracts.map((c) => (
                  <TableRow
                    key={c.id}
                    className="cursor-pointer hover:bg-muted/50"
                    onClick={() => setDetailContract(c)}
                  >
                    <TableCell className="font-medium">
                      {c.property_id
                        ? propertyNames[c.property_id] ?? c.property_id.slice(0, 8)
                        : "—"}
                    </TableCell>
                    <TableCell>
                      {c.agreement_type === "prospectus" ? (
                        <Badge variant="secondary" className="bg-blue-500/10 text-blue-400 border-blue-500/20">
                          Prospectus
                        </Badge>
                      ) : (
                        <Badge variant="secondary">Agreement</Badge>
                      )}
                    </TableCell>
                    <TableCell>
                      <StatusBadge status={c.status} />
                    </TableCell>
                    <TableCell className="text-muted-foreground text-sm">
                      {fmtDate(c.created_at)}
                    </TableCell>
                    <TableCell className="text-muted-foreground text-sm">
                      {fmtDate(c.sent_at)}
                    </TableCell>
                    <TableCell className="text-muted-foreground text-sm">
                      {fmtDate(c.signed_at)}
                    </TableCell>
                    <TableCell className="text-sm">
                      {c.signer_name ?? "—"}
                    </TableCell>
                  </TableRow>
                ))}
              </TableBody>
            </Table>
          )}
        </CardContent>
      </Card>

      {/* Detail Sheet */}
      <Sheet
        open={!!detailContract}
        onOpenChange={(open) => {
          if (!open) setDetailContract(null);
        }}
      >
        <SheetContent className="sm:max-w-lg overflow-y-auto">
          {detailContract && (
            <>
              <SheetHeader>
                <SheetTitle className="flex items-center gap-2">
                  <FileText className="h-5 w-5" />
                  Agreement Detail
                </SheetTitle>
                <SheetDescription>
                  {detailContract.property_id
                    ? propertyNames[detailContract.property_id] ??
                      detailContract.property_id
                    : "Unknown Property"}
                </SheetDescription>
              </SheetHeader>

              <div className="mt-6 space-y-6">
                {/* Status + Dates */}
                <div className="grid grid-cols-2 gap-4">
                  <div>
                    <p className="text-xs text-muted-foreground mb-1">Status</p>
                    <StatusBadge status={detailContract.status} />
                  </div>
                  <div>
                    <p className="text-xs text-muted-foreground mb-1">Created</p>
                    <p className="text-sm font-mono">
                      {fmtDate(detailContract.created_at)}
                    </p>
                  </div>
                  {detailContract.sent_at && (
                    <div>
                      <p className="text-xs text-muted-foreground mb-1">Sent</p>
                      <p className="text-sm font-mono">
                        {fmtDate(detailContract.sent_at)}
                      </p>
                    </div>
                  )}
                  {detailContract.signed_at && (
                    <div>
                      <p className="text-xs text-muted-foreground mb-1">
                        Signed
                      </p>
                      <p className="text-sm font-mono">
                        {fmtDate(detailContract.signed_at)}
                      </p>
                    </div>
                  )}
                  {detailContract.signer_name && (
                    <div className="col-span-2">
                      <p className="text-xs text-muted-foreground mb-1">
                        Signer
                      </p>
                      <p className="text-sm">{detailContract.signer_name}</p>
                    </div>
                  )}
                </div>

                {/* Actions */}
                <div className="space-y-3 border-t pt-4">
                  {/* Download PDF */}
                  {detailContract.pdf_url && (
                    <Button variant="outline" className="w-full justify-start" asChild>
                      <a
                        href={`/api/admin/contracts/${detailContract.id}/pdf`}
                        target="_blank"
                        rel="noopener noreferrer"
                      >
                        <Download className="h-4 w-4 mr-2" />
                        Download PDF
                      </a>
                    </Button>
                  )}

                  {/* Send for Signature (only for draft status) */}
                  {detailContract.status === "draft" && (
                    <Card className="border-emerald-500/30">
                      <CardHeader className="pb-3">
                        <CardTitle className="text-sm flex items-center gap-2">
                          <Send className="h-4 w-4 text-emerald-500" />
                          Dispatch Signing Link
                        </CardTitle>
                      </CardHeader>
                      <CardContent className="space-y-3">
                        <div className="grid gap-2">
                          <Label className="text-xs">
                            Recipient Email (optional override)
                          </Label>
                          <Input
                            type="email"
                            placeholder="owner@example.com"
                            value={sendEmail}
                            onChange={(e) => setSendEmail(e.target.value)}
                          />
                        </div>
                        <div className="grid gap-2">
                          <Label className="text-xs">Link Expires (days)</Label>
                          <Input
                            type="number"
                            min={1}
                            max={30}
                            value={sendDays}
                            onChange={(e) => setSendDays(e.target.value)}
                          />
                        </div>
                        <Button
                          className="w-full bg-emerald-600 hover:bg-emerald-700"
                          onClick={handleSend}
                          disabled={sendMutation.isPending}
                        >
                          {sendMutation.isPending ? (
                            <Loader2 className="h-4 w-4 mr-2 animate-spin" />
                          ) : (
                            <Send className="h-4 w-4 mr-2" />
                          )}
                          Send for Signature
                        </Button>
                      </CardContent>
                    </Card>
                  )}

                  {/* Signed confirmation */}
                  {detailContract.status === "signed" && (
                    <div className="flex items-center gap-2 p-3 rounded-md bg-emerald-500/10 text-emerald-500 text-sm">
                      <CheckCircle2 className="h-4 w-4 shrink-0" />
                      Agreement fully executed
                      {detailContract.signed_at && (
                        <span className="text-muted-foreground ml-auto">
                          {fmtDate(detailContract.signed_at)}
                        </span>
                      )}
                    </div>
                  )}
                </div>
              </div>
            </>
          )}
        </SheetContent>
      </Sheet>
    </div>
  );
}
