"use client";

import { useState } from "react";
import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query";
import { api } from "@/lib/api";
import { Button } from "@/components/ui/button";
import { Card, CardContent } from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Textarea } from "@/components/ui/textarea";
import { Badge } from "@/components/ui/badge";
import { Checkbox } from "@/components/ui/checkbox";
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
import { Plus, FileText, Pencil, Trash2, Loader2 } from "lucide-react";

const VARIABLES = [
  "guest_name", "guest_email", "guest_phone", "guest_address",
  "property_name", "property_address", "owner_name",
  "check_in_date", "check_out_date", "num_nights", "num_guests",
  "total_amount", "paid_amount", "balance_due", "nightly_rate",
  "access_code", "wifi_password", "today_date", "confirmation_code",
  "max_guests", "bedrooms", "bathrooms",
];

const TYPES = [
  { value: "rental_agreement", label: "Rental Agreement" },
  { value: "pet_addendum", label: "Pet Addendum" },
  { value: "damage_waiver", label: "Damage Waiver" },
  { value: "liability_waiver", label: "Liability Waiver" },
  { value: "house_rules", label: "House Rules" },
  { value: "cancellation_policy", label: "Cancellation Policy" },
  { value: "pool_waiver", label: "Pool Waiver" },
];

interface TemplateForm {
  name: string;
  description: string;
  agreement_type: string;
  content_markdown: string;
  requires_signature: boolean;
  requires_initials: boolean;
  auto_send: boolean;
  send_days_before_checkin: number;
}

interface AgreementTemplateRecord extends TemplateForm {
  id: string;
}

const emptyForm: TemplateForm = {
  name: "",
  description: "",
  agreement_type: "rental_agreement",
  content_markdown: "",
  requires_signature: true,
  requires_initials: false,
  auto_send: true,
  send_days_before_checkin: 7,
};

export default function AgreementTemplatesPage() {
  const qc = useQueryClient();
  const [editing, setEditing] = useState<AgreementTemplateRecord | "new" | null>(null);
  const [form, setForm] = useState<TemplateForm>(emptyForm);
  const [preview, setPreview] = useState(false);

  const { data: templates = [], isLoading } = useQuery<AgreementTemplateRecord[]>({
    queryKey: ["agreement-templates"],
    queryFn: () => api.get<AgreementTemplateRecord[]>("/api/agreements/templates"),
  });

  const createMut = useMutation({
    mutationFn: (data: TemplateForm) =>
      api.post("/api/agreements/templates", data),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["agreement-templates"] });
      setEditing(null);
      setForm(emptyForm);
    },
  });

  const updateMut = useMutation({
    mutationFn: ({ id, data }: { id: string; data: Partial<TemplateForm> }) =>
      api.patch(`/api/agreements/templates/${id}`, data),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["agreement-templates"] });
      setEditing(null);
      setForm(emptyForm);
    },
  });

  const deleteMut = useMutation({
    mutationFn: (id: string) =>
      api.delete(`/api/agreements/templates/${id}`),
    onSuccess: () => qc.invalidateQueries({ queryKey: ["agreement-templates"] }),
  });

  function openNew() {
    setForm(emptyForm);
    setEditing("new");
  }

  function openEdit(t: AgreementTemplateRecord) {
    setForm({
      name: t.name,
      description: t.description || "",
      agreement_type: t.agreement_type,
      content_markdown: t.content_markdown,
      requires_signature: t.requires_signature,
      requires_initials: t.requires_initials,
      auto_send: t.auto_send,
      send_days_before_checkin: t.send_days_before_checkin,
    });
    setEditing(t);
  }

  function insertVariable(v: string) {
    setForm((f) => ({
      ...f,
      content_markdown: f.content_markdown + `{{${v}}}`,
    }));
  }

  function handleSave() {
    if (editing === "new") {
      createMut.mutate(form);
      return;
    }

    if (!editing) return;

    updateMut.mutate({ id: editing.id, data: form });
  }

  return (
    <div className="space-y-6">
      <div className="flex items-center justify-between">
        <div>
          <h1 className="text-2xl font-bold tracking-tight">Agreement Templates</h1>
          <p className="text-sm text-muted-foreground">
            Create and manage rental agreement templates with variable placeholders
          </p>
        </div>
        <Button onClick={openNew}>
          <Plus className="h-4 w-4 mr-2" />
          New Template
        </Button>
      </div>

      {/* Template List */}
      <div className="grid gap-4">
        {isLoading ? (
          <div className="text-center py-12 text-muted-foreground">
            <Loader2 className="h-5 w-5 animate-spin mx-auto mb-2" />
            Loading templates...
          </div>
        ) : templates.length === 0 ? (
          <Card>
            <CardContent className="text-center py-12">
              <FileText className="h-10 w-10 mx-auto mb-3 text-muted-foreground/40" />
              <p className="text-muted-foreground">No templates yet</p>
              <Button variant="outline" className="mt-3" onClick={openNew}>
                Create your first template
              </Button>
            </CardContent>
          </Card>
        ) : (
          templates.map((t) => (
            <Card key={t.id}>
              <CardContent className="flex items-center justify-between py-4 px-5">
                <div className="flex items-center gap-4">
                  <div className="h-10 w-10 bg-blue-100 rounded-lg flex items-center justify-center">
                    <FileText className="h-5 w-5 text-blue-600" />
                  </div>
                  <div>
                    <h3 className="font-semibold text-sm">{t.name}</h3>
                    <div className="flex gap-2 mt-1">
                      <Badge variant="outline" className="text-xs capitalize">
                        {t.agreement_type?.replace(/_/g, " ")}
                      </Badge>
                      {t.requires_signature && (
                        <Badge variant="secondary" className="text-xs">Signature</Badge>
                      )}
                      {t.requires_initials && (
                        <Badge variant="secondary" className="text-xs">Initials</Badge>
                      )}
                      {t.auto_send && (
                        <Badge variant="secondary" className="text-xs">
                          Auto-send {t.send_days_before_checkin}d before
                        </Badge>
                      )}
                    </div>
                  </div>
                </div>
                <div className="flex gap-2">
                  <Button size="sm" variant="outline" onClick={() => openEdit(t)}>
                    <Pencil className="h-3 w-3 mr-1" />
                    Edit
                  </Button>
                  <Button
                    size="sm"
                    variant="outline"
                    className="text-red-600"
                    onClick={() => deleteMut.mutate(t.id)}
                  >
                    <Trash2 className="h-3 w-3" />
                  </Button>
                </div>
              </CardContent>
            </Card>
          ))
        )}
      </div>

      {/* Editor Sheet */}
      <Sheet open={!!editing} onOpenChange={() => setEditing(null)}>
        <SheetContent className="sm:max-w-2xl overflow-y-auto">
          <SheetHeader>
            <SheetTitle>
              {editing === "new" ? "New Template" : `Edit: ${form.name}`}
            </SheetTitle>
          </SheetHeader>

          <div className="mt-4 space-y-5">
            <div className="grid grid-cols-2 gap-4">
              <div>
                <Label>Name</Label>
                <Input
                  value={form.name}
                  onChange={(e) => setForm((f) => ({ ...f, name: e.target.value }))}
                  placeholder="Standard Rental Agreement"
                />
              </div>
              <div>
                <Label>Type</Label>
                <Select
                  value={form.agreement_type}
                  onValueChange={(v) => setForm((f) => ({ ...f, agreement_type: v }))}
                >
                  <SelectTrigger><SelectValue /></SelectTrigger>
                  <SelectContent>
                    {TYPES.map((t) => (
                      <SelectItem key={t.value} value={t.value}>{t.label}</SelectItem>
                    ))}
                  </SelectContent>
                </Select>
              </div>
            </div>

            <div>
              <Label>Description</Label>
              <Input
                value={form.description}
                onChange={(e) => setForm((f) => ({ ...f, description: e.target.value }))}
                placeholder="Full rental agreement with house rules..."
              />
            </div>

            {/* Variable insertion */}
            <div>
              <Label className="mb-2 block">Insert Variable</Label>
              <div className="flex flex-wrap gap-1.5">
                {VARIABLES.map((v) => (
                  <button
                    key={v}
                    onClick={() => insertVariable(v)}
                    className="text-[10px] bg-blue-50 text-blue-700 px-2 py-0.5 rounded hover:bg-blue-100 transition-colors"
                  >
                    {`{{${v}}}`}
                  </button>
                ))}
              </div>
            </div>

            {/* Content editor */}
            <div>
              <div className="flex justify-between mb-1">
                <Label>Template Content (Markdown)</Label>
                <button
                  onClick={() => setPreview(!preview)}
                  className="text-xs text-blue-600 hover:underline"
                >
                  {preview ? "Edit" : "Preview"}
                </button>
              </div>
              {preview ? (
                <div className="border rounded-lg p-4 min-h-[300px] prose prose-sm max-w-none">
                  <div
                    dangerouslySetInnerHTML={{
                      __html: form.content_markdown
                        .replace(/\n/g, "<br>")
                        .replace(/^## (.+)/gm, "<h2>$1</h2>")
                        .replace(/^### (.+)/gm, "<h3>$1</h3>")
                        .replace(/\*\*(.+?)\*\*/g, "<strong>$1</strong>"),
                    }}
                  />
                </div>
              ) : (
                <Textarea
                  value={form.content_markdown}
                  onChange={(e) =>
                    setForm((f) => ({ ...f, content_markdown: e.target.value }))
                  }
                  placeholder="# Rental Agreement\n\nThis agreement is between {{owner_name}} and {{guest_name}}..."
                  className="min-h-[300px] font-mono text-xs"
                />
              )}
            </div>

            {/* Settings */}
            <div className="grid grid-cols-2 gap-4">
              <div className="flex items-center gap-2">
                <Checkbox
                  checked={form.requires_signature}
                  onCheckedChange={(c) =>
                    setForm((f) => ({ ...f, requires_signature: !!c }))
                  }
                />
                <Label className="text-sm">Requires Signature</Label>
              </div>
              <div className="flex items-center gap-2">
                <Checkbox
                  checked={form.requires_initials}
                  onCheckedChange={(c) =>
                    setForm((f) => ({ ...f, requires_initials: !!c }))
                  }
                />
                <Label className="text-sm">Requires Initials</Label>
              </div>
              <div className="flex items-center gap-2">
                <Checkbox
                  checked={form.auto_send}
                  onCheckedChange={(c) =>
                    setForm((f) => ({ ...f, auto_send: !!c }))
                  }
                />
                <Label className="text-sm">Auto-send before check-in</Label>
              </div>
              <div>
                <Label className="text-xs">Days before check-in</Label>
                <Input
                  type="number"
                  value={form.send_days_before_checkin}
                  onChange={(e) =>
                    setForm((f) => ({
                      ...f,
                      send_days_before_checkin: parseInt(e.target.value) || 7,
                    }))
                  }
                  min={1}
                  max={30}
                />
              </div>
            </div>

            <div className="flex gap-3 pt-2">
              <Button
                onClick={handleSave}
                disabled={createMut.isPending || updateMut.isPending || !form.name || !form.content_markdown}
              >
                {(createMut.isPending || updateMut.isPending) && (
                  <Loader2 className="h-4 w-4 mr-2 animate-spin" />
                )}
                {editing === "new" ? "Create Template" : "Save Changes"}
              </Button>
              <Button variant="outline" onClick={() => setEditing(null)}>
                Cancel
              </Button>
            </div>
          </div>
        </SheetContent>
      </Sheet>
    </div>
  );
}
