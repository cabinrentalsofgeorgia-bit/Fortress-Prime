"use client";

import { useState, type ComponentProps } from "react";
import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query";
import { api } from "@/lib/api";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardContent } from "@/components/ui/card";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import {
  Sheet,
  SheetContent,
  SheetHeader,
  SheetTitle,
} from "@/components/ui/sheet";
import {
  FileSignature,
  Send,
  Bell,
  Download,
  Eye,
  Clock,
  CheckCircle2,
  XCircle,
  FileText,
  Loader2,
  type LucideIcon,
} from "lucide-react";

type BadgeVariant = ComponentProps<typeof Badge>["variant"];
type AgreementStatus = "draft" | "sent" | "viewed" | "signed" | "expired" | "cancelled";
type AgreementSummary = {
  id: string;
  guest_name?: string | null;
  property_name?: string | null;
  agreement_type?: string | null;
  status: AgreementStatus;
  sent_at?: string | null;
  signed_at?: string | null;
  pdf_url?: string | null;
  signer_name?: string | null;
  signer_email?: string | null;
  signature_type?: string | null;
  signer_ip_address?: string | null;
  consent_recorded?: boolean | null;
  agreement_url?: string | null;
  view_count?: number | null;
  reminder_count?: number | null;
  created_at?: string | null;
  expires_at?: string | null;
};

const statusColor: Record<AgreementStatus, BadgeVariant> = {
  draft: "outline",
  sent: "secondary",
  viewed: "default",
  signed: "default",
  expired: "destructive",
  cancelled: "outline",
};

const statusIcon: Record<AgreementStatus, LucideIcon> = {
  draft: FileText,
  sent: Send,
  viewed: Eye,
  signed: CheckCircle2,
  expired: Clock,
  cancelled: XCircle,
};

export default function AgreementsPage() {
  const qc = useQueryClient();
  const [filter, setFilter] = useState<string>("all");
  const [selected, setSelected] = useState<AgreementSummary | null>(null);

  const { data: dashboard } = useQuery({
    queryKey: ["agreements-dashboard"],
    queryFn: () => api.get<{ total: number; by_status: Record<string, number>; expiring_soon: number }>("/api/agreements/dashboard"),
  });

  const { data: agreements = [], isLoading } = useQuery<AgreementSummary[]>({
    queryKey: ["agreements", filter],
    queryFn: () =>
      api.get<AgreementSummary[]>(
        `/api/agreements${filter !== "all" ? `?status=${filter}` : ""}`
      ),
  });

  const sendMut = useMutation({
    mutationFn: (id: string) =>
      api.post(`/api/agreements/${id}/send`),
    onSuccess: () => qc.invalidateQueries({ queryKey: ["agreements"] }),
  });

  const remindMut = useMutation({
    mutationFn: (id: string) =>
      api.post(`/api/agreements/${id}/remind`),
    onSuccess: () => qc.invalidateQueries({ queryKey: ["agreements"] }),
  });

  const stats = dashboard?.by_status ?? {};

  return (
    <div className="space-y-6">
      <div className="flex items-center justify-between">
        <div>
          <h1 className="text-2xl font-bold tracking-tight">Agreements</h1>
          <p className="text-sm text-muted-foreground">
            Rental agreements, e-signatures, and document management
          </p>
        </div>
      </div>

      {/* Stats */}
      <div className="grid grid-cols-2 md:grid-cols-5 gap-4">
        {[
          { label: "Draft", value: stats.draft ?? 0, color: "text-slate-500" },
          { label: "Sent", value: stats.sent ?? 0, color: "text-blue-500" },
          { label: "Viewed", value: stats.viewed ?? 0, color: "text-amber-500" },
          { label: "Signed", value: stats.signed ?? 0, color: "text-green-600" },
          { label: "Expired", value: stats.expired ?? 0, color: "text-red-500" },
        ].map((s) => (
          <Card key={s.label}>
            <CardContent className="pt-4 pb-3 px-4">
              <p className="text-xs text-muted-foreground">{s.label}</p>
              <p className={`text-2xl font-bold ${s.color}`}>{s.value}</p>
            </CardContent>
          </Card>
        ))}
      </div>

      {/* Filter */}
      <div className="flex items-center gap-3">
        <Select value={filter} onValueChange={setFilter}>
          <SelectTrigger className="w-40">
            <SelectValue placeholder="Filter status" />
          </SelectTrigger>
          <SelectContent>
            <SelectItem value="all">All</SelectItem>
            <SelectItem value="draft">Draft</SelectItem>
            <SelectItem value="sent">Sent</SelectItem>
            <SelectItem value="viewed">Viewed</SelectItem>
            <SelectItem value="signed">Signed</SelectItem>
            <SelectItem value="expired">Expired</SelectItem>
          </SelectContent>
        </Select>
      </div>

      {/* Table */}
      <Card>
        <CardContent className="p-0">
          <div className="overflow-x-auto">
            <table className="w-full text-sm">
              <thead>
                <tr className="border-b bg-muted/50">
                  <th className="text-left p-3 font-medium">Guest</th>
                  <th className="text-left p-3 font-medium">Property</th>
                  <th className="text-left p-3 font-medium">Type</th>
                  <th className="text-left p-3 font-medium">Status</th>
                  <th className="text-left p-3 font-medium">Sent</th>
                  <th className="text-left p-3 font-medium">Signed</th>
                  <th className="text-right p-3 font-medium">Actions</th>
                </tr>
              </thead>
              <tbody>
                {isLoading ? (
                  <tr>
                    <td colSpan={7} className="text-center py-12 text-muted-foreground">
                      <Loader2 className="h-5 w-5 animate-spin mx-auto mb-2" />
                      Loading agreements...
                    </td>
                  </tr>
                ) : agreements.length === 0 ? (
                  <tr>
                    <td colSpan={7} className="text-center py-12 text-muted-foreground">
                      <FileSignature className="h-8 w-8 mx-auto mb-2 opacity-40" />
                      No agreements yet. Create one from a reservation.
                    </td>
                  </tr>
                ) : (
                  agreements.map((a) => {
                    const Icon = statusIcon[a.status] ?? FileText;
                    return (
                      <tr
                        key={a.id}
                        className="border-b hover:bg-muted/30 cursor-pointer"
                        onClick={() => setSelected(a)}
                      >
                        <td className="p-3 font-medium">{a.guest_name ?? "—"}</td>
                        <td className="p-3">{a.property_name ?? "—"}</td>
                        <td className="p-3 capitalize">
                          {a.agreement_type?.replace(/_/g, " ") ?? "—"}
                        </td>
                        <td className="p-3">
                          <Badge variant={statusColor[a.status] ?? "outline"} className="gap-1">
                            <Icon className="h-3 w-3" />
                            {a.status}
                          </Badge>
                        </td>
                        <td className="p-3 text-muted-foreground">
                          {a.sent_at ? new Date(a.sent_at).toLocaleDateString() : "—"}
                        </td>
                        <td className="p-3 text-muted-foreground">
                          {a.signed_at ? new Date(a.signed_at).toLocaleDateString() : "—"}
                        </td>
                        <td className="p-3 text-right">
                          <div className="flex gap-1 justify-end" onClick={(e) => e.stopPropagation()}>
                            {a.status === "draft" && (
                              <Button
                                size="sm"
                                variant="outline"
                                onClick={() => sendMut.mutate(a.id)}
                                disabled={sendMut.isPending}
                              >
                                <Send className="h-3 w-3 mr-1" />
                                Send
                              </Button>
                            )}
                            {(a.status === "sent" || a.status === "viewed") && (
                              <Button
                                size="sm"
                                variant="outline"
                                onClick={() => remindMut.mutate(a.id)}
                                disabled={remindMut.isPending}
                              >
                                <Bell className="h-3 w-3 mr-1" />
                                Remind
                              </Button>
                            )}
                            {a.pdf_url && (
                              <Button size="sm" variant="outline" asChild>
                                <a href={`/api/agreements/${a.id}/pdf`} target="_blank">
                                  <Download className="h-3 w-3 mr-1" />
                                  PDF
                                </a>
                              </Button>
                            )}
                          </div>
                        </td>
                      </tr>
                    );
                  })
                )}
              </tbody>
            </table>
          </div>
        </CardContent>
      </Card>

      {/* Detail Sheet */}
      <Sheet open={!!selected} onOpenChange={() => setSelected(null)}>
        <SheetContent className="overflow-y-auto">
          <SheetHeader>
            <SheetTitle>Agreement Detail</SheetTitle>
          </SheetHeader>
          {selected && (
            <div className="mt-4 space-y-4">
              <div className="grid grid-cols-2 gap-3">
                <div className="rounded-lg border p-3">
                  <p className="text-xs text-muted-foreground">Status</p>
                  <Badge variant={statusColor[selected.status] ?? "outline"}>
                    {selected.status}
                  </Badge>
                </div>
                <div className="rounded-lg border p-3">
                  <p className="text-xs text-muted-foreground">Type</p>
                  <p className="text-sm font-medium capitalize">
                    {selected.agreement_type?.replace(/_/g, " ")}
                  </p>
                </div>
                <div className="rounded-lg border p-3">
                  <p className="text-xs text-muted-foreground">Guest</p>
                  <p className="text-sm font-medium">{selected.guest_name ?? "—"}</p>
                </div>
                <div className="rounded-lg border p-3">
                  <p className="text-xs text-muted-foreground">Property</p>
                  <p className="text-sm font-medium">{selected.property_name ?? "—"}</p>
                </div>
              </div>

              {selected.signed_at && (
                <div className="rounded-lg border p-4 bg-green-50 space-y-2">
                  <h4 className="text-sm font-semibold text-green-800">
                    Signature Verification
                  </h4>
                  <div className="text-xs space-y-1 text-green-700">
                    <p>Signed by: {selected.signer_name}</p>
                    <p>Email: {selected.signer_email}</p>
                    <p>Date: {new Date(selected.signed_at).toLocaleString()}</p>
                    <p>Method: {selected.signature_type}</p>
                    <p>IP: {selected.signer_ip_address}</p>
                    <p>Consent: {selected.consent_recorded ? "Yes" : "No"}</p>
                  </div>
                </div>
              )}

              {selected.agreement_url && selected.status !== "signed" && (
                <div className="rounded-lg border p-3">
                  <p className="text-xs text-muted-foreground mb-1">Signing URL</p>
                  <a
                    href={selected.agreement_url}
                    target="_blank"
                    className="text-xs text-blue-600 break-all hover:underline"
                  >
                    {selected.agreement_url}
                  </a>
                </div>
              )}

              <div className="text-xs text-muted-foreground space-y-1">
                <p>Views: {selected.view_count}</p>
                <p>Reminders sent: {selected.reminder_count}</p>
                <p>Created: {selected.created_at ? new Date(selected.created_at).toLocaleString() : "—"}</p>
                {selected.expires_at && (
                  <p>Expires: {new Date(selected.expires_at).toLocaleString()}</p>
                )}
              </div>
            </div>
          )}
        </SheetContent>
      </Sheet>
    </div>
  );
}
