"use client";

import { useState } from "react";
import {
  useDamageClaims,
  useDamageClaimStats,
  useCreateDamageClaim,
  useGenerateLegalDraft,
  useApproveDamageClaim,
  useChargeDamageClaim,
  useSendDamageClaim,
  useUpdateDamageClaim,
  useReservationOptions,
  useProperties,
  useInspectionHistory,
  useInspectionSummary,
  useFailedInspections,
} from "@/lib/hooks";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Textarea } from "@/components/ui/textarea";
import { ScrollArea } from "@/components/ui/scroll-area";
import { Separator } from "@/components/ui/separator";
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/tabs";
import {
  Sheet,
  SheetContent,
  SheetHeader,
  SheetTitle,
} from "@/components/ui/sheet";
import {
  Dialog,
  DialogContent,
  DialogHeader,
  DialogTitle,
  DialogTrigger,
} from "@/components/ui/dialog";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import { Checkbox } from "@/components/ui/checkbox";
import {
  AlertTriangle,
  Camera,
  CreditCard,
  FileText,
  Plus,
  Shield,
  Scale,
  Send,
  CheckCircle,
  Clock,
  DollarSign,
  Home,
  Eye,
  Bot,
  Search,
  Loader2,
  ArrowRight,
  Pencil,
  Save,
  X,
  MessageSquareText,
} from "lucide-react";
import { cn } from "@/lib/utils";
import { toast } from "sonner";

interface DamageClaim {
  id: string;
  claim_number: string;
  property_id: string;
  guest_id: string;
  reservation_id: string;
  damage_description: string;
  damage_areas: string[];
  estimated_cost: number;
  status: string;
  photo_urls: string[];
  inspection_notes: string;
  legal_draft: string | null;
  legal_draft_at: string | null;
  legal_draft_model?: string | null;
  agreement_clauses?: { clauses?: string[]; draft_source?: DraftSource } | null;
  reported_by: string | null;
  inspection_date: string | null;
  resolution: string | null;
  resolution_amount: number | null;
  stripe_charge_id?: string | null;
  amount_charged?: number | null;
  charge_executed_at?: string | null;
  created_at: string;
  confirmation_code?: string | null;
  check_in_date?: string | null;
  check_out_date?: string | null;
  streamline_notes?: StreamlineNote[];
  property?: { name: string };
  guest?: { first_name: string; last_name: string };
}

interface StreamlineNote {
  processor_name?: string;
  creation_date?: string;
  message?: string;
  schedule_follow_up?: boolean;
}

interface DraftSource {
  confirmation_code?: string;
  reservation_id?: string;
  property_name?: string;
  check_in?: string;
  check_out?: string;
  rental_agreement_id?: string | null;
  agreement_used?: boolean;
  agreement_signed_at?: string | null;
}

interface ClaimStats {
  total: number;
  by_status: Record<string, number>;
  total_estimated_cost: number;
  total_resolved_amount: number;
}

function DraftSourceSummary({ source }: { source: DraftSource }) {
  return (
    <div className="space-y-0.5 text-muted-foreground">
      <p>Reservation: <span className="font-medium text-foreground">{source.confirmation_code ?? "—"}</span> · {source.property_name ?? "—"} · {source.check_in ?? "—"} to {source.check_out ?? "—"}</p>
      <p>Agreement used: {source.agreement_used ? `Yes${source.agreement_signed_at ? ` (signed ${new Date(source.agreement_signed_at).toLocaleDateString()})` : ""}` : "No — draft is AI-generated only (no signed agreement on file)"}</p>
    </div>
  );
}

const STATUS_FLOW = ["reported", "draft_ready", "approved", "sent", "resolved", "closed"];
const STATUS_COLORS: Record<string, string> = {
  reported: "bg-orange-500/10 text-orange-600 border-orange-500/30",
  draft_ready: "bg-blue-500/10 text-blue-600 border-blue-500/30",
  approved: "bg-emerald-500/10 text-emerald-600 border-emerald-500/30",
  sent: "bg-violet-500/10 text-violet-600 border-violet-500/30",
  resolved: "bg-green-500/10 text-green-600 border-green-500/30",
  closed: "bg-slate-500/10 text-slate-500 border-slate-500/30",
};

const DAMAGE_AREAS = [
  "Living Room", "Kitchen", "Master Bedroom", "Bedroom 2", "Bedroom 3",
  "Bathroom", "Deck/Patio", "Hot Tub", "Game Room", "Exterior",
  "Garage", "Furniture", "Appliances", "Flooring", "Walls/Paint",
];

export default function DamageClaimsPage() {
  const { data: claims, isLoading } = useDamageClaims();
  const { data: stats } = useDamageClaimStats();
  const { data: properties } = useProperties();
  const { data: reservationOptions } = useReservationOptions();
  const createClaim = useCreateDamageClaim();
  const generateDraft = useGenerateLegalDraft();
  const approveClaim = useApproveDamageClaim();
  const sendClaim = useSendDamageClaim();
  const chargeClaim = useChargeDamageClaim();
  const updateClaim = useUpdateDamageClaim();
  const { data: inspections } = useInspectionHistory({ limit: 25 });
  const { data: inspSummary } = useInspectionSummary();
  const { data: failedInspections } = useFailedInspections();

  const [createOpen, setCreateOpen] = useState(false);
  const [selectedClaim, setSelectedClaim] = useState<DamageClaim | null>(null);
  const [statusFilter, setStatusFilter] = useState("all");
  const [search, setSearch] = useState("");
  const [selectedAreas, setSelectedAreas] = useState<string[]>([]);
  const [activeTab, setActiveTab] = useState("claims");
  const [editingDescription, setEditingDescription] = useState(false);
  const [editedDescription, setEditedDescription] = useState("");
  const [showChargeModal, setShowChargeModal] = useState(false);
  const [chargeAmount, setChargeAmount] = useState("");

  const claimsList = Array.isArray(claims) ? (claims as DamageClaim[]) : [];
  const claimStats = stats as ClaimStats | undefined;
  const propMap = new Map((properties ?? []).map((p) => [p.id, p.name]));

  const filtered = claimsList.filter((c) => {
    if (statusFilter !== "all" && c.status !== statusFilter) return false;
    if (search) {
      const q = search.toLowerCase();
      return (
        c.claim_number?.toLowerCase().includes(q) ||
        c.damage_description?.toLowerCase().includes(q) ||
        (propMap.get(c.property_id) ?? "").toLowerCase().includes(q)
      );
    }
    return true;
  });

  function handleCreate(e: React.FormEvent<HTMLFormElement>) {
    e.preventDefault();
    const form = new FormData(e.currentTarget);
    const resId = form.get("reservation_id") as string;
    const resOpt = Array.isArray(reservationOptions)
      ? (reservationOptions as Array<{ id: string; property_id: string; guest_id: string }>).find((r) => r.id === resId)
      : null;

    createClaim.mutate({
      reservation_id: resId,
      property_id: resOpt?.property_id ?? (form.get("property_id") as string),
      guest_id: resOpt?.guest_id ?? "",
      damage_description: form.get("damage_description") as string,
      damage_areas: selectedAreas,
      estimated_cost: parseFloat(form.get("estimated_cost") as string) || 0,
      inspection_notes: form.get("inspection_notes") as string,
    }, {
      onSuccess: () => {
        setCreateOpen(false);
        setSelectedAreas([]);
      },
    });
  }

  function getStepIndex(status: string) {
    return STATUS_FLOW.indexOf(status);
  }

  return (
    <div className="space-y-6">
      <div className="flex items-center justify-between">
        <div>
          <h1 className="text-2xl font-bold tracking-tight flex items-center gap-2">
            <Shield className="h-6 w-6 text-orange-500" />
            Damage Claims
          </h1>
          <p className="text-muted-foreground">
            Post-checkout inspections, evidence collection, and AI legal response drafting
          </p>
        </div>
        <Dialog open={createOpen} onOpenChange={setCreateOpen}>
          <DialogTrigger asChild>
            <Button><Plus className="mr-2 h-4 w-4" />New Claim</Button>
          </DialogTrigger>
          <DialogContent className="max-w-lg max-h-[90vh] overflow-y-auto">
            <DialogHeader>
              <DialogTitle>File Damage Claim</DialogTitle>
            </DialogHeader>
            <form onSubmit={handleCreate} className="space-y-4 mt-2">
              <div className="space-y-2">
                <Label>Reservation</Label>
                <Select name="reservation_id" required>
                  <SelectTrigger><SelectValue placeholder="Select recent checkout..." /></SelectTrigger>
                  <SelectContent>
                    {Array.isArray(reservationOptions) && (reservationOptions as Array<{ id: string; confirmation_code: string; guest_name: string; property_name: string }>).map((r) => (
                      <SelectItem key={r.id} value={r.id}>
                        {r.confirmation_code} — {r.guest_name} at {r.property_name}
                      </SelectItem>
                    ))}
                  </SelectContent>
                </Select>
              </div>

              <div className="space-y-2">
                <Label>Damage Description</Label>
                <Textarea name="damage_description" placeholder="Describe the damage found during inspection..." rows={4} required />
              </div>

              <div className="space-y-2">
                <Label>Affected Areas</Label>
                <div className="grid grid-cols-3 gap-2">
                  {DAMAGE_AREAS.map((area) => (
                    <div key={area} className="flex items-center gap-1.5">
                      <Checkbox
                        checked={selectedAreas.includes(area)}
                        onCheckedChange={(checked) => {
                          setSelectedAreas((prev) =>
                            checked ? [...prev, area] : prev.filter((a) => a !== area),
                          );
                        }}
                      />
                      <span className="text-xs">{area}</span>
                    </div>
                  ))}
                </div>
              </div>

              <div className="grid grid-cols-2 gap-4">
                <div className="space-y-2">
                  <Label>Estimated Cost ($)</Label>
                  <Input name="estimated_cost" type="number" step="0.01" min="0" placeholder="0.00" />
                </div>
                <div className="space-y-2">
                  <Label>Property (auto-filled)</Label>
                  <Select name="property_id">
                    <SelectTrigger><SelectValue placeholder="From reservation" /></SelectTrigger>
                    <SelectContent>
                      {(properties ?? []).map((p) => (
                        <SelectItem key={p.id} value={p.id}>{p.name}</SelectItem>
                      ))}
                    </SelectContent>
                  </Select>
                </div>
              </div>

              <div className="space-y-2">
                <Label>Inspection Notes</Label>
                <Textarea name="inspection_notes" placeholder="Additional notes from the walk-through..." rows={2} />
              </div>

              <Button type="submit" className="w-full" disabled={createClaim.isPending}>
                {createClaim.isPending ? "Filing Claim..." : "File Damage Claim"}
              </Button>
            </form>
          </DialogContent>
        </Dialog>
      </div>

      {/* Stats */}
      <div className="grid gap-4 md:grid-cols-4">
        <Card>
          <CardContent className="pt-4 flex items-center gap-3">
            <AlertTriangle className="h-8 w-8 text-orange-500" />
            <div>
              <p className="text-2xl font-bold">{claimStats?.total ?? claimsList.length}</p>
              <p className="text-xs text-muted-foreground">Total Claims</p>
            </div>
          </CardContent>
        </Card>
        <Card>
          <CardContent className="pt-4 flex items-center gap-3">
            <Clock className="h-8 w-8 text-blue-500" />
            <div>
              <p className="text-2xl font-bold">
                {claimStats?.by_status?.reported ?? claimsList.filter((c) => c.status === "reported").length}
              </p>
              <p className="text-xs text-muted-foreground">Pending Review</p>
            </div>
          </CardContent>
        </Card>
        <Card>
          <CardContent className="pt-4 flex items-center gap-3">
            <DollarSign className="h-8 w-8 text-red-500" />
            <div>
              <p className="text-2xl font-bold">
                ${(claimStats?.total_estimated_cost ?? claimsList.reduce((s, c) => s + (c.estimated_cost ?? 0), 0)).toLocaleString()}
              </p>
              <p className="text-xs text-muted-foreground">Total Estimated</p>
            </div>
          </CardContent>
        </Card>
        <Card>
          <CardContent className="pt-4 flex items-center gap-3">
            <CheckCircle className="h-8 w-8 text-green-500" />
            <div>
              <p className="text-2xl font-bold">
                ${(claimStats?.total_resolved_amount ?? 0).toLocaleString()}
              </p>
              <p className="text-xs text-muted-foreground">Recovered</p>
            </div>
          </CardContent>
        </Card>
      </div>

      <Tabs value={activeTab} onValueChange={setActiveTab}>
        <TabsList>
          <TabsTrigger value="claims">
            Damage Claims
            {claimsList.length > 0 && (
              <Badge variant="outline" className="ml-1.5 text-[10px]">{claimsList.length}</Badge>
            )}
          </TabsTrigger>
          <TabsTrigger value="inspections">
            Vision Inspections
            {(inspSummary as { failed?: number } | undefined)?.failed ? (
              <Badge variant="destructive" className="ml-1.5 text-[10px]">
                {(inspSummary as { failed: number }).failed} failed
              </Badge>
            ) : null}
          </TabsTrigger>
        </TabsList>

        <TabsContent value="claims" className="mt-4 space-y-4">
          {/* Filters */}
          <div className="flex items-center gap-3">
            <div className="relative flex-1 max-w-xs">
              <Search className="absolute left-2.5 top-1/2 -translate-y-1/2 h-3.5 w-3.5 text-muted-foreground" />
              <Input placeholder="Search claims..." className="pl-8" value={search} onChange={(e) => setSearch(e.target.value)} />
            </div>
            <Select value={statusFilter} onValueChange={setStatusFilter}>
              <SelectTrigger className="w-40"><SelectValue /></SelectTrigger>
              <SelectContent>
                <SelectItem value="all">All Status</SelectItem>
                <SelectItem value="reported">Reported</SelectItem>
                <SelectItem value="draft_ready">Draft Ready</SelectItem>
                <SelectItem value="approved">Approved</SelectItem>
                <SelectItem value="sent">Sent</SelectItem>
                <SelectItem value="resolved">Resolved</SelectItem>
                <SelectItem value="closed">Closed</SelectItem>
              </SelectContent>
            </Select>
          </div>

          {/* Claims list */}
          {claimsList.length === 0 && !isLoading ? (
            <Card>
              <CardContent className="py-16 text-center">
                <Shield className="h-16 w-16 mx-auto mb-4 text-muted-foreground/30" />
                <p className="text-lg font-medium">No damage claims filed</p>
                <p className="text-sm text-muted-foreground mt-1">
                  When post-checkout inspections reveal damage, file a claim to start the recovery process
                </p>
                <Button className="mt-4" onClick={() => setCreateOpen(true)}>
                  <Plus className="mr-2 h-4 w-4" />File First Claim
                </Button>
              </CardContent>
            </Card>
          ) : (
            <div className="space-y-3">
              {filtered.map((claim) => (
                <Card
                  key={claim.id}
                  className="cursor-pointer hover:shadow-md transition-shadow"
                  onClick={() => setSelectedClaim(claim)}
                >
                  <CardContent className="p-4">
                    <div className="flex items-center justify-between">
                      <div className="flex items-center gap-4">
                        <div className="h-10 w-10 rounded-lg bg-orange-500/10 flex items-center justify-center">
                          <AlertTriangle className="h-5 w-5 text-orange-500" />
                        </div>
                        <div>
                          <div className="flex items-center gap-2">
                            <p className="font-medium">{claim.claim_number ?? `CLM-${(claim.id ?? "").slice(0, 6)}`}</p>
                            <Badge variant="outline" className={cn("text-[10px]", STATUS_COLORS[claim.status])}>
                              {claim.status.replace("_", " ")}
                            </Badge>
                          </div>
                          <p className="text-sm text-muted-foreground line-clamp-1">
                            {claim.damage_description}
                          </p>
                          <div className="flex items-center gap-3 text-xs text-muted-foreground mt-1">
                            <span className="flex items-center gap-1">
                              <Home className="h-3 w-3" />
                              {propMap.get(claim.property_id) ?? claim.property?.name ?? "—"}
                            </span>
                            {claim.damage_areas?.length > 0 && (
                              <span>{claim.damage_areas.length} area{claim.damage_areas.length !== 1 ? "s" : ""}</span>
                            )}
                            <span>{new Date(claim.created_at).toLocaleDateString()}</span>
                          </div>
                        </div>
                      </div>
                      <div className="text-right">
                        {claim.estimated_cost > 0 && (
                          <p className="text-lg font-bold text-red-600">${claim.estimated_cost.toLocaleString()}</p>
                        )}
                        {claim.legal_draft && (
                          <Badge variant="outline" className="text-[10px] mt-1">
                            <Bot className="h-3 w-3 mr-1" />Legal draft ready
                          </Badge>
                        )}
                      </div>
                    </div>
                  </CardContent>
                </Card>
              ))}
            </div>
          )}
        </TabsContent>

        <TabsContent value="inspections" className="mt-4 space-y-4">
          {inspSummary ? (
            <div className="grid gap-4 md:grid-cols-5">
              <Card>
                <CardContent className="pt-4 flex items-center gap-3">
                  <Eye className="h-8 w-8 text-blue-500" />
                  <div>
                    <p className="text-2xl font-bold">{(inspSummary as Record<string, number>).total ?? 0}</p>
                    <p className="text-xs text-muted-foreground">Total Inspections</p>
                  </div>
                </CardContent>
              </Card>
              <Card>
                <CardContent className="pt-4 flex items-center gap-3">
                  <CheckCircle className="h-8 w-8 text-green-500" />
                  <div>
                    <p className="text-2xl font-bold">{(inspSummary as Record<string, number>).passed ?? 0}</p>
                    <p className="text-xs text-muted-foreground">Passed</p>
                  </div>
                </CardContent>
              </Card>
              <Card>
                <CardContent className="pt-4 flex items-center gap-3">
                  <AlertTriangle className="h-8 w-8 text-red-500" />
                  <div>
                    <p className="text-2xl font-bold">{(inspSummary as Record<string, number>).failed ?? 0}</p>
                    <p className="text-xs text-muted-foreground">Failed</p>
                  </div>
                </CardContent>
              </Card>
              <Card>
                <CardContent className="pt-4 flex items-center gap-3">
                  <Camera className="h-8 w-8 text-violet-500" />
                  <div>
                    <p className="text-2xl font-bold">{(inspSummary as Record<string, number>).avg_score ?? 0}</p>
                    <p className="text-xs text-muted-foreground">Avg Score</p>
                  </div>
                </CardContent>
              </Card>
              <Card>
                <CardContent className="pt-4 flex items-center gap-3">
                  <Home className="h-8 w-8 text-amber-500" />
                  <div>
                    <p className="text-2xl font-bold">{(inspSummary as Record<string, number>).cabins_inspected ?? 0}</p>
                    <p className="text-xs text-muted-foreground">Properties</p>
                  </div>
                </CardContent>
              </Card>
            </div>
          ) : null}

          {/* Failed inspections that need attention */}
          {Array.isArray(failedInspections) && failedInspections.length > 0 && (
            <Card className="border-red-500/30">
              <CardHeader className="pb-3">
                <CardTitle className="text-base flex items-center gap-2 text-red-600">
                  <AlertTriangle className="h-4 w-4" />
                  Failed Inspections — May Require Damage Claim
                </CardTitle>
              </CardHeader>
              <CardContent>
                <div className="space-y-2">
                  {(failedInspections as Array<{
                    id: number;
                    cabin_name: string;
                    room_type: string;
                    overall_score: number;
                    issues_found: string;
                    generated_at: string;
                    items_failed: number;
                  }>).map((insp) => (
                    <div
                      key={insp.id}
                      className="flex items-center justify-between rounded-lg border border-red-500/20 bg-red-500/5 p-3"
                    >
                      <div className="flex items-center gap-3">
                        <div className="h-8 w-8 rounded bg-red-500/10 flex items-center justify-center">
                          <AlertTriangle className="h-4 w-4 text-red-500" />
                        </div>
                        <div>
                          <p className="text-sm font-medium">
                            {insp.cabin_name} — {insp.room_type}
                          </p>
                          <p className="text-xs text-muted-foreground">
                            Score: {insp.overall_score}/100 — {insp.items_failed} item(s) failed — {insp.generated_at ? new Date(insp.generated_at).toLocaleDateString() : ""}
                          </p>
                        </div>
                      </div>
                      <Button
                        size="sm"
                        variant="outline"
                        className="text-red-600 border-red-500/30 hover:bg-red-500/10"
                        onClick={() => {
                          setActiveTab("claims");
                          setCreateOpen(true);
                        }}
                      >
                        <FileText className="mr-1.5 h-3.5 w-3.5" />
                        File Claim
                      </Button>
                    </div>
                  ))}
                </div>
              </CardContent>
            </Card>
          )}

          {/* Inspection history */}
          <Card>
            <CardHeader>
              <CardTitle className="text-base flex items-center gap-2">
                <Eye className="h-4 w-4" />
                Inspection History (CF-01 GuardianOps)
              </CardTitle>
            </CardHeader>
            <CardContent>
              {Array.isArray(inspections) && inspections.length > 0 ? (
                <ScrollArea className="h-[400px]">
                  <div className="space-y-2">
                    {(inspections as Array<{
                      id: number;
                      run_id: string;
                      cabin_name: string;
                      room_type: string;
                      room_display?: string;
                      overall_score: number;
                      verdict: string;
                      ai_confidence_score?: number;
                      inspector_id?: string;
                      generated_at?: string;
                      items_passed?: number;
                      items_failed?: number;
                      items_total?: number;
                    }>).map((insp) => (
                      <div
                        key={insp.id}
                        className="flex items-center justify-between border-b py-2.5 last:border-0"
                      >
                        <div className="flex items-center gap-3">
                          <div className={cn(
                            "h-8 w-8 rounded flex items-center justify-center",
                            insp.verdict === "PASS" ? "bg-green-500/10" : "bg-red-500/10",
                          )}>
                            {insp.verdict === "PASS" ? (
                              <CheckCircle className="h-4 w-4 text-green-500" />
                            ) : (
                              <AlertTriangle className="h-4 w-4 text-red-500" />
                            )}
                          </div>
                          <div>
                            <p className="text-sm font-medium">
                              {insp.cabin_name} — {insp.room_display ?? insp.room_type}
                            </p>
                            <div className="flex items-center gap-2 text-xs text-muted-foreground">
                              <span>Score: {insp.overall_score}/100</span>
                              {insp.items_total && (
                                <span>{insp.items_passed}/{insp.items_total} items passed</span>
                              )}
                              {insp.inspector_id && <span>by {insp.inspector_id}</span>}
                              {insp.generated_at && <span>{new Date(insp.generated_at).toLocaleDateString()}</span>}
                            </div>
                          </div>
                        </div>
                        <Badge
                          variant="outline"
                          className={cn(
                            "text-[10px]",
                            insp.verdict === "PASS"
                              ? "bg-green-500/10 text-green-600 border-green-500/30"
                              : "bg-red-500/10 text-red-600 border-red-500/30",
                          )}
                        >
                          {insp.verdict}
                        </Badge>
                      </div>
                    ))}
                  </div>
                </ScrollArea>
              ) : (
                <div className="py-12 text-center text-muted-foreground">
                  <Camera className="h-12 w-12 mx-auto mb-3 opacity-30" />
                  <p className="text-sm">No vision inspections recorded yet</p>
                  <p className="text-xs mt-1">
                    CF-01 GuardianOps inspections will appear here when cleaners upload photos
                  </p>
                </div>
              )}
            </CardContent>
          </Card>
        </TabsContent>
      </Tabs>

      {/* Claim Detail Sheet */}
      <Sheet open={!!selectedClaim} onOpenChange={() => {
        setSelectedClaim(null);
        setEditingDescription(false);
        setEditedDescription("");
      }}>
        <SheetContent className="w-[560px] sm:max-w-[560px] overflow-y-auto">
          {selectedClaim && (
            <>
              <SheetHeader>
                <SheetTitle className="flex items-center gap-2">
                  <Shield className="h-5 w-5 text-orange-500" />
                  {selectedClaim.claim_number ?? `Claim`}
                </SheetTitle>
              </SheetHeader>

              <div className="mt-6 space-y-6">
                {/* Workflow progress */}
                <div>
                  <p className="text-xs font-medium text-muted-foreground mb-2">Workflow Progress</p>
                  <div className="flex items-center gap-1">
                    {STATUS_FLOW.map((step, i) => {
                      const current = getStepIndex(selectedClaim.status);
                      const done = i <= current;
                      return (
                        <div key={step} className="flex items-center gap-1 flex-1">
                          <div className={cn(
                            "h-2 flex-1 rounded-full",
                            done ? "bg-primary" : "bg-muted",
                          )} />
                          {i < STATUS_FLOW.length - 1 && <ArrowRight className="h-3 w-3 text-muted-foreground shrink-0" />}
                        </div>
                      );
                    })}
                  </div>
                  <div className="flex justify-between text-[10px] text-muted-foreground mt-1">
                    {STATUS_FLOW.map((s) => <span key={s}>{s.replace("_", " ")}</span>)}
                  </div>
                </div>

                <Separator />

                {/* Details */}
                <div className="space-y-3">
                  <div>
                    <div className="flex items-center justify-between">
                      <p className="text-xs text-muted-foreground">Description</p>
                      {!editingDescription ? (
                        <Button
                          size="sm"
                          variant="ghost"
                          className="h-6 px-2 text-xs"
                          onClick={() => {
                            setEditingDescription(true);
                            setEditedDescription(selectedClaim.damage_description);
                          }}
                        >
                          <Pencil className="h-3 w-3 mr-1" />
                          Edit
                        </Button>
                      ) : (
                        <div className="flex items-center gap-1">
                          <Button
                            size="sm"
                            variant="ghost"
                            className="h-6 px-2 text-xs text-green-600 hover:text-green-700 hover:bg-green-50"
                            onClick={() => {
                              if (editedDescription.trim() && editedDescription !== selectedClaim.damage_description) {
                                updateClaim.mutate(
                                  { id: selectedClaim.id, damage_description: editedDescription.trim() },
                                  {
                                    onSuccess: () => {
                                      toast.success("Description updated");
                                      setEditingDescription(false);
                                      setSelectedClaim((prev) =>
                                        prev ? { ...prev, damage_description: editedDescription.trim() } : null
                                      );
                                    },
                                  }
                                );
                              } else {
                                setEditingDescription(false);
                              }
                            }}
                            disabled={updateClaim.isPending}
                          >
                            {updateClaim.isPending ? (
                              <Loader2 className="h-3 w-3 animate-spin" />
                            ) : (
                              <>
                                <Save className="h-3 w-3 mr-1" />
                                Save
                              </>
                            )}
                          </Button>
                          <Button
                            size="sm"
                            variant="ghost"
                            className="h-6 px-2 text-xs text-muted-foreground hover:text-red-600"
                            onClick={() => {
                              setEditingDescription(false);
                              setEditedDescription("");
                            }}
                          >
                            <X className="h-3 w-3" />
                          </Button>
                        </div>
                      )}
                    </div>
                    {editingDescription ? (
                      <Textarea
                        value={editedDescription}
                        onChange={(e) => setEditedDescription(e.target.value)}
                        className="mt-2 text-sm"
                        rows={6}
                        placeholder="Edit the damage description to improve accuracy..."
                      />
                    ) : (
                      <p className="text-sm mt-1">{selectedClaim.damage_description}</p>
                    )}
                    {editingDescription && (
                      <p className="text-[10px] text-muted-foreground mt-1">
                        Tip: Correcting descriptions helps improve future AI-generated legal drafts
                      </p>
                    )}
                  </div>

                  {selectedClaim.damage_areas?.length > 0 && (
                    <div>
                      <p className="text-xs text-muted-foreground mb-1">Affected Areas</p>
                      <div className="flex flex-wrap gap-1">
                        {selectedClaim.damage_areas.map((a) => (
                          <Badge key={a} variant="outline" className="text-xs">{a}</Badge>
                        ))}
                      </div>
                    </div>
                  )}

                  <div className="grid grid-cols-2 gap-3">
                    <div className="rounded-lg border p-3">
                      <p className="text-xs text-muted-foreground">Estimated Cost</p>
                      <p className="text-lg font-bold text-red-600">
                        ${selectedClaim.estimated_cost?.toLocaleString() ?? "0"}
                      </p>
                    </div>
                    <div className="rounded-lg border p-3">
                      <p className="text-xs text-muted-foreground">Property</p>
                      <p className="text-sm font-medium">
                        {propMap.get(selectedClaim.property_id) ?? "—"}
                      </p>
                    </div>
                  </div>

                  {selectedClaim.inspection_notes && (
                    <div>
                      <p className="text-xs text-muted-foreground">Inspection Notes</p>
                      <p className="text-sm mt-1 rounded-lg border p-3 bg-muted/50">
                        {selectedClaim.inspection_notes}
                      </p>
                    </div>
                  )}
                </div>

                {/* Streamline Notes */}
                {selectedClaim.streamline_notes && selectedClaim.streamline_notes.length > 0 && (
                  <>
                    <Separator />
                    <div className="space-y-2">
                      <p className="text-sm font-semibold flex items-center gap-2">
                        <MessageSquareText className="h-4 w-4 text-blue-500" />
                        Streamline Notes ({selectedClaim.streamline_notes.length})
                      </p>
                      <ScrollArea className={selectedClaim.streamline_notes.length > 3 ? "h-[250px]" : ""}>
                        <div className="space-y-2">
                          {selectedClaim.streamline_notes.map((note, i) => (
                            <div key={i} className="rounded-lg border border-blue-500/20 bg-blue-500/5 p-3">
                              <p className="text-sm whitespace-pre-wrap">{note.message}</p>
                              <div className="flex items-center gap-2 mt-2 text-[10px] text-muted-foreground">
                                {note.processor_name && <span className="font-medium">{note.processor_name}</span>}
                                {note.creation_date && <span>{new Date(note.creation_date).toLocaleString()}</span>}
                              </div>
                            </div>
                          ))}
                        </div>
                      </ScrollArea>
                    </div>
                  </>
                )}

                <Separator />

                {/* Legal Draft */}
                <div className="space-y-3">
                  <div className="flex items-center justify-between">
                    <p className="text-sm font-semibold flex items-center gap-2">
                      <Scale className="h-4 w-4 text-violet-500" />
                      AI Legal Response
                    </p>
                    {selectedClaim.status === "reported" && (
                      <Button
                        size="sm"
                        variant="outline"
                        onClick={() => generateDraft.mutate(selectedClaim.id)}
                        disabled={generateDraft.isPending}
                      >
                        {generateDraft.isPending ? (
                          <><Loader2 className="mr-1.5 h-3.5 w-3.5 animate-spin" />Generating...</>
                        ) : (
                          <><Bot className="mr-1.5 h-3.5 w-3.5" />Generate Draft</>
                        )}
                      </Button>
                    )}
                  </div>

                  {selectedClaim.legal_draft ? (
                    <div className="space-y-3">
                      <div className="rounded-lg border border-violet-500/20 bg-violet-500/5 p-4">
                        <p className="text-sm whitespace-pre-wrap">{selectedClaim.legal_draft}</p>
                        <p className="text-[10px] text-muted-foreground mt-2">
                          Generated {selectedClaim.legal_draft_at ? new Date(selectedClaim.legal_draft_at).toLocaleString() : ""}
                          {selectedClaim.legal_draft_model && ` · Model: ${selectedClaim.legal_draft_model}`}
                        </p>
                      </div>
                      {(() => {
                        const draftSource = (selectedClaim.agreement_clauses as { draft_source?: DraftSource } | undefined)?.draft_source;
                        return (
                          <div className="rounded-lg border border-amber-500/20 bg-amber-500/5 p-3 text-xs">
                            <p className="font-medium text-amber-800 dark:text-amber-200 mb-1">Draft source (for troubleshooting)</p>
                            {draftSource ? (
                              <>
                                <DraftSourceSummary source={draftSource} />
                                <p className="text-muted-foreground mt-2 pt-2 border-t border-amber-500/20">
                                  If the draft references another reservation or wrong property: (1) Confirm this claim is filed against the correct reservation above. (2) Ensure a signed rental agreement exists for that reservation; without it, the AI generates from policy only and may sound generic or wrong.
                                </p>
                              </>
                            ) : (
                              <p className="text-muted-foreground">
                                Source not recorded (draft generated before audit). This claim is for reservation <strong>{selectedClaim.confirmation_code ?? "—"}</strong>, {selectedClaim.check_in_date ? new Date(selectedClaim.check_in_date).toLocaleDateString() : "—"}–{selectedClaim.check_out_date ? new Date(selectedClaim.check_out_date).toLocaleDateString() : "—"}. If the draft references another stay, re-generate the draft to record the source, or verify the claim is filed against the correct reservation.
                              </p>
                            )}
                          </div>
                        );
                      })()}
                    </div>
                  ) : (
                    <p className="text-sm text-muted-foreground text-center py-4">
                      Generate an AI legal response based on the rental agreement and damage evidence
                    </p>
                  )}
                </div>

                <Separator />

                {/* Actions */}
                <div className="space-y-2">
                  <p className="text-xs font-medium text-muted-foreground">Actions</p>
                  <div className="flex flex-wrap gap-2">
                    {selectedClaim.status === "reported" && !selectedClaim.legal_draft && (
                      <Button
                        size="sm"
                        onClick={() => generateDraft.mutate(selectedClaim.id)}
                        disabled={generateDraft.isPending}
                      >
                        <Bot className="mr-1.5 h-4 w-4" />
                        Generate AI Legal Draft
                      </Button>
                    )}
                    {(selectedClaim.status === "draft_ready" || (selectedClaim.status === "reported" && selectedClaim.legal_draft)) && (
                      <Button
                        size="sm"
                        onClick={() => approveClaim.mutate(selectedClaim.id)}
                        disabled={approveClaim.isPending}
                      >
                        <CheckCircle className="mr-1.5 h-4 w-4" />
                        Approve Draft
                      </Button>
                    )}
                    {selectedClaim.status === "approved" && (
                      <>
                        <Button
                          size="sm"
                          onClick={() => sendClaim.mutate({ id: selectedClaim.id, via: "email" })}
                          disabled={sendClaim.isPending}
                        >
                          <Send className="mr-1.5 h-4 w-4" />
                          Send via Email
                        </Button>
                        <Button
                          size="sm"
                          variant="outline"
                          onClick={() => sendClaim.mutate({ id: selectedClaim.id, via: "sms" })}
                          disabled={sendClaim.isPending}
                        >
                          <Send className="mr-1.5 h-4 w-4" />
                          Send via SMS
                        </Button>
                      </>
                    )}
                    {selectedClaim.status === "sent" && (
                      <Button
                        size="sm"
                        variant="outline"
                        onClick={() => {
                          updateClaim.mutate({ id: selectedClaim.id, status: "resolved" });
                          setSelectedClaim(null);
                        }}
                      >
                        <CheckCircle className="mr-1.5 h-4 w-4" />
                        Mark Resolved
                      </Button>
                    )}
                    {["approved", "sent", "resolved"].includes(selectedClaim.status) && !selectedClaim.stripe_charge_id && (
                      <Button
                        size="sm"
                        variant="destructive"
                        onClick={() => {
                          setChargeAmount(String(selectedClaim.resolution_amount ?? selectedClaim.estimated_cost ?? ""));
                          setShowChargeModal(true);
                        }}
                      >
                        <CreditCard className="mr-1.5 h-4 w-4" />
                        Charge Guest
                      </Button>
                    )}
                    {selectedClaim.stripe_charge_id && (
                      <Badge className="bg-emerald-500/10 text-emerald-600 border border-emerald-500/30 px-2 py-1 text-xs font-mono">
                        <CreditCard className="mr-1 h-3 w-3" />
                        Charged ${selectedClaim.amount_charged?.toFixed(2)} · {selectedClaim.stripe_charge_id}
                      </Badge>
                    )}
                  </div>
                </div>
              </div>
            </>
          )}
        </SheetContent>
      </Sheet>

      {/* Charge Guest Modal */}
      <Dialog open={showChargeModal} onOpenChange={setShowChargeModal}>
        <DialogContent className="sm:max-w-md">
          <DialogHeader>
            <DialogTitle className="flex items-center gap-2">
              <CreditCard className="h-5 w-5 text-destructive" />
              Charge Guest
            </DialogTitle>
          </DialogHeader>
          {selectedClaim && (
            <div className="space-y-4 pt-2">
              <div className="rounded-md bg-destructive/10 border border-destructive/30 p-3 text-sm text-destructive">
                This will immediately charge the guest&apos;s saved payment method off-session via Stripe. This action cannot be undone.
              </div>
              <div className="space-y-1.5">
                <Label htmlFor="charge-amount">Charge Amount ($)</Label>
                <Input
                  id="charge-amount"
                  type="number"
                  step="0.01"
                  min="0.01"
                  value={chargeAmount}
                  onChange={(e) => setChargeAmount(e.target.value)}
                  placeholder="0.00"
                />
                <p className="text-xs text-muted-foreground">
                  Estimated cost: ${selectedClaim.estimated_cost?.toFixed(2) ?? "—"}
                  {selectedClaim.resolution_amount ? ` · Resolution amount: $${selectedClaim.resolution_amount.toFixed(2)}` : ""}
                </p>
              </div>
              <div className="flex justify-end gap-2 pt-2">
                <Button variant="outline" size="sm" onClick={() => setShowChargeModal(false)}>
                  Cancel
                </Button>
                <Button
                  variant="destructive"
                  size="sm"
                  disabled={!chargeAmount || Number(chargeAmount) <= 0 || chargeClaim.isPending}
                  onClick={() => {
                    chargeClaim.mutate(
                      { id: selectedClaim.id, amount: Number(chargeAmount), note: undefined },
                      {
                        onSuccess: (data) => {
                          setShowChargeModal(false);
                          if (data?.charged) {
                            setSelectedClaim((prev) =>
                              prev
                                ? {
                                    ...prev,
                                    stripe_charge_id: data.stripe_charge_id,
                                    amount_charged: data.amount_charged,
                                    charge_executed_at: new Date().toISOString(),
                                  }
                                : null
                            );
                          }
                        },
                      }
                    );
                  }}
                >
                  {chargeClaim.isPending ? (
                    <><Loader2 className="mr-1.5 h-4 w-4 animate-spin" /> Charging…</>
                  ) : (
                    <><CreditCard className="mr-1.5 h-4 w-4" /> Confirm Charge</>
                  )}
                </Button>
              </div>
            </div>
          )}
        </DialogContent>
      </Dialog>
    </div>
  );
}
