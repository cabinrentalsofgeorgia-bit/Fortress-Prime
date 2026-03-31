"use client";

import { Controller, useFormContext, type Control, type UseFormRegister } from "react-hook-form";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Switch } from "@/components/ui/switch";
import { Textarea } from "@/components/ui/textarea";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import { useEmailTemplates } from "@/lib/hooks";
import type { AutomationFormValues } from "@/lib/schemas/automations";

export function ActionPayloadFields() {
  const { watch, register, control } = useFormContext<AutomationFormValues>();
  const actionType = watch("action_type");

  if (actionType === "send_email_template") {
    return <EmailFields />;
  }

  if (actionType === "create_task") {
    return <TaskFields control={control} register={register} />;
  }

  if (actionType === "notify_staff") {
    return <NotifyFields register={register} />;
  }

  if (actionType === "legal_search") {
    return <LegalSearchFields register={register} />;
  }

  if (actionType === "legal_council") {
    return <LegalCouncilFields register={register} control={control} />;
  }

  if (actionType === "legal_ingest") {
    return <LegalIngestFields register={register} />;
  }

  if (actionType === "legal_deposition") {
    return <LegalDepositionFields register={register} control={control} />;
  }

  if (actionType === "draft_motion_extension") {
    return <LegalMotionExtensionFields register={register} control={control} />;
  }

  if (actionType === "analyze_opposing_filing") {
    return <LegalOpposingFilingFields register={register} control={control} />;
  }

  if (actionType === "concierge_conflict") {
    return <ConciergeConflictFields register={register} control={control} />;
  }

  return (
    <p className="text-xs text-muted-foreground italic">
      Select an action type to configure its payload.
    </p>
  );
}

function EmailFields() {
  const { control } = useFormContext<AutomationFormValues>();
  const { data: templates, isLoading } = useEmailTemplates();

  return (
    <div className="pt-3 border-t space-y-3">
      <p className="text-xs text-muted-foreground">
        Select the template and recipient role for outbound email.
      </p>
      <div>
        <Label className="text-xs text-muted-foreground">Email Template</Label>
        <Controller
          control={control}
          name="action_payload.template_id"
          render={({ field }) => (
            <Select
              value={(field.value as string) ?? ""}
              onValueChange={field.onChange}
            >
              <SelectTrigger className="w-full">
                <SelectValue
                  placeholder={
                    isLoading ? "Loading templates..." : "Choose a template..."
                  }
                />
              </SelectTrigger>
              <SelectContent>
                {(templates ?? []).map((tpl) => (
                  <SelectItem key={tpl.id} value={tpl.id}>
                    {tpl.name}
                  </SelectItem>
                ))}
              </SelectContent>
            </Select>
          )}
        />
      </div>
      <div>
        <Label className="text-xs text-muted-foreground">Recipient Role</Label>
        <Controller
          control={control}
          name="action_payload.recipient_role"
          render={({ field }) => (
            <Select
              value={(field.value as string) ?? ""}
              onValueChange={field.onChange}
            >
              <SelectTrigger className="w-full">
                <SelectValue placeholder="Who gets this email?" />
              </SelectTrigger>
              <SelectContent>
                <SelectItem value="guest">The Guest</SelectItem>
                <SelectItem value="owner">The Property Owner</SelectItem>
                <SelectItem value="cleaner">Assigned Housekeeper</SelectItem>
                <SelectItem value="staff">Internal Staff (Admin)</SelectItem>
              </SelectContent>
            </Select>
          )}
        />
      </div>
    </div>
  );
}

type AutomationControl = Control<AutomationFormValues>;
type AutomationRegister = UseFormRegister<AutomationFormValues>;

function TaskFields({ control, register }: { control: AutomationControl; register: AutomationRegister }) {
  return (
    <div className="pt-3 border-t space-y-3">
      <p className="text-xs text-muted-foreground">
        Configure a housekeeping or maintenance task to be created automatically.
      </p>
      <div>
        <Label className="text-xs text-muted-foreground">Task Title</Label>
        <Input
          placeholder="e.g. Follow up on check-in"
          {...register("action_payload.title")}
        />
      </div>
      <div>
        <Label className="text-xs text-muted-foreground">Category</Label>
        <Input
          placeholder="e.g. maintenance, housekeeping"
          {...register("action_payload.category")}
        />
      </div>
      <div>
        <Label className="text-xs text-muted-foreground">Priority</Label>
        <Controller
          control={control}
          name="action_payload.priority"
          render={({ field }) => (
            <Select
              value={(field.value as string) ?? ""}
              onValueChange={field.onChange}
            >
              <SelectTrigger className="w-full">
                <SelectValue placeholder="Select priority" />
              </SelectTrigger>
              <SelectContent>
                <SelectItem value="low">Low</SelectItem>
                <SelectItem value="medium">Medium</SelectItem>
                <SelectItem value="high">High</SelectItem>
                <SelectItem value="urgent">Urgent</SelectItem>
              </SelectContent>
            </Select>
          )}
        />
      </div>
    </div>
  );
}

function NotifyFields({ register }: { register: AutomationRegister }) {
  return (
    <div className="pt-3 border-t space-y-3">
      <p className="text-xs text-muted-foreground">
        Send a structured notification to staff when this rule fires.
      </p>
      <div>
        <Label className="text-xs text-muted-foreground">
          Notification Message
        </Label>
        <Textarea
          placeholder="Message sent to staff when this rule fires..."
          rows={3}
          {...register("action_payload.message")}
        />
      </div>
    </div>
  );
}

function LegalSearchFields({ register }: { register: AutomationRegister }) {
  return (
    <div className="pt-3 border-t space-y-3">
      <p className="text-xs text-muted-foreground">
        Division 3 search tool. Use this for case reconstruction, contradictions, and evidence questions.
      </p>
      <div>
        <Label className="text-xs text-muted-foreground">Case Slug</Label>
        <Input placeholder="fish-trap-suv2026000013" {...register("action_payload.case_slug")} />
      </div>
      <div>
        <Label className="text-xs text-muted-foreground">Search Query</Label>
        <Textarea
          placeholder="Summarize contradictions and chronology pressure points..."
          rows={4}
          {...register("action_payload.query")}
        />
      </div>
    </div>
  );
}

function LegalCouncilFields({
  register,
  control,
}: {
  register: AutomationRegister;
  control: AutomationControl;
}) {
  return (
    <div className="pt-3 border-t space-y-3">
      <p className="text-xs text-muted-foreground">
        9-seat council workflow. Runs the legal council bridge and can persist answer artifacts into the vault.
      </p>
      <div>
        <Label className="text-xs text-muted-foreground">Case Slug</Label>
        <Input placeholder="fish-trap-suv2026000013" {...register("action_payload.case_slug")} />
      </div>
      <div>
        <Label className="text-xs text-muted-foreground">Case Number</Label>
        <Input placeholder="SUV2026000013" {...register("action_payload.case_number")} />
      </div>
      <div>
        <Label className="text-xs text-muted-foreground">Council Objective</Label>
        <Textarea
          placeholder="Draft the answer and defenses while weighting chronology contradictions..."
          rows={4}
          {...register("action_payload.query")}
        />
      </div>
      <div>
        <Label className="text-xs text-muted-foreground">Operator Context</Label>
        <Textarea
          placeholder="Optional strategic notes for the council..."
          rows={3}
          {...register("action_payload.context")}
        />
      </div>
      <div className="flex items-center justify-between rounded-md border p-3">
        <div>
          <Label>Persist to Vault</Label>
          <p className="text-xs text-muted-foreground">
            Save generated answer artifacts into the sovereign NAS vault.
          </p>
        </div>
        <Controller
          control={control}
          name="action_payload.persist_to_vault"
          render={({ field }) => (
            <Switch checked={Boolean(field.value ?? true)} onCheckedChange={field.onChange} />
          )}
        />
      </div>
    </div>
  );
}

function LegalIngestFields({ register }: { register: AutomationRegister }) {
  return (
    <div className="pt-3 border-t space-y-3">
      <p className="text-xs text-muted-foreground">
        Discovery ingest tool. Use this when a rule should push raw evidence into the legal graph and pack pipeline.
      </p>
      <div>
        <Label className="text-xs text-muted-foreground">Case Slug</Label>
        <Input placeholder="fish-trap-suv2026000013" {...register("action_payload.case_slug")} />
      </div>
      <div>
        <Label className="text-xs text-muted-foreground">Legacy Pack ID</Label>
        <Input placeholder="aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee" {...register("action_payload.pack_id")} />
      </div>
      <div>
        <Label className="text-xs text-muted-foreground">Source Document</Label>
        <Input placeholder="Affidavit_2026-03-29.pdf" {...register("action_payload.source_document")} />
      </div>
      <div>
        <Label className="text-xs text-muted-foreground">Source Reference</Label>
        <Input placeholder="Bates 001-004" {...register("action_payload.source_ref")} />
      </div>
      <div>
        <Label className="text-xs text-muted-foreground">Payload Text</Label>
        <Textarea
          placeholder="Paste or template the raw evidence text to ingest..."
          rows={5}
          {...register("action_payload.payload_text")}
        />
      </div>
    </div>
  );
}

function LegalDepositionFields({
  register,
  control,
}: {
  register: AutomationRegister;
  control: AutomationControl;
}) {
  return (
    <div className="pt-3 border-t space-y-3">
      <p className="text-xs text-muted-foreground">
        Deposition outline tool. Collects the deponent and operator focus required by the General Counsel workflow.
      </p>
      <div>
        <Label className="text-xs text-muted-foreground">Case Slug</Label>
        <Input placeholder="fish-trap-suv2026000013" {...register("action_payload.case_slug")} />
      </div>
      <div>
        <Label className="text-xs text-muted-foreground">Case Number</Label>
        <Input placeholder="SUV2026000013" {...register("action_payload.case_number")} />
      </div>
      <div>
        <Label className="text-xs text-muted-foreground">Deponent Name</Label>
        <Input placeholder="Colleen Blackman" {...register("action_payload.deponent_entity")} />
      </div>
      <div>
        <Label className="text-xs text-muted-foreground">Operator Focus</Label>
        <Textarea
          placeholder="Focus on contradictions between the affidavit narrative and the 2023 schedule metadata..."
          rows={4}
          {...register("action_payload.operator_focus")}
        />
      </div>
      <div className="flex items-center justify-between rounded-md border p-3">
        <div>
          <Label>Persist to Vault</Label>
          <p className="text-xs text-muted-foreground">
            Save the outline JSON artifact into the case vault.
          </p>
        </div>
        <Controller
          control={control}
          name="action_payload.persist_to_vault"
          render={({ field }) => (
            <Switch checked={Boolean(field.value ?? true)} onCheckedChange={field.onChange} />
          )}
        />
      </div>
    </div>
  );
}

function LegalMotionExtensionFields({
  register,
  control,
}: {
  register: AutomationRegister;
  control: AutomationControl;
}) {
  return (
    <div className="pt-3 border-t space-y-3">
      <p className="text-xs text-muted-foreground">
        Deadline-driven motion drafter. Intended for `deadline_approaching` legal case events.
      </p>
      <div className="grid grid-cols-2 gap-3">
        <div>
          <Label className="text-xs text-muted-foreground">Case Slug</Label>
          <Input placeholder="fish-trap-suv2026000013" {...register("action_payload.case_slug")} />
        </div>
        <div>
          <Label className="text-xs text-muted-foreground">Case Number</Label>
          <Input placeholder="SUV2026000013" {...register("action_payload.case_number")} />
        </div>
      </div>
      <div>
        <Label className="text-xs text-muted-foreground">Target Vault Path</Label>
        <Input
          placeholder="/mnt/fortress_nas/sectors/legal/fish-trap-suv2026000013/filings/outgoing"
          {...register("action_payload.target_vault_path")}
        />
      </div>
      <div>
        <Label className="text-xs text-muted-foreground">Deadline Type</Label>
        <Input placeholder="Responsive Pleading" {...register("action_payload.deadline_type")} />
      </div>
      <div>
        <Label className="text-xs text-muted-foreground">Motion Context</Label>
        <Textarea
          placeholder="Optional supporting context tailored to Judge Priest and the approaching deadline..."
          rows={4}
          {...register("action_payload.description")}
        />
      </div>
      <div className="flex items-center justify-between rounded-md border p-3">
        <div>
          <Label>Persist to Vault</Label>
          <p className="text-xs text-muted-foreground">
            Save the generated motion DOCX into the sovereign NAS vault.
          </p>
        </div>
        <Controller
          control={control}
          name="action_payload.persist_to_vault"
          render={({ field }) => (
            <Switch checked={Boolean(field.value ?? true)} onCheckedChange={field.onChange} />
          )}
        />
      </div>
    </div>
  );
}

function LegalOpposingFilingFields({
  register,
  control,
}: {
  register: AutomationRegister;
  control: AutomationControl;
}) {
  return (
    <div className="pt-3 border-t space-y-3">
      <p className="text-xs text-muted-foreground">
        Hostile filing interrogation. Intended for `docket_updated` legal document events.
      </p>
      <div className="grid grid-cols-2 gap-3">
        <div>
          <Label className="text-xs text-muted-foreground">Case Slug</Label>
          <Input placeholder="fish-trap-suv2026000013" {...register("action_payload.case_slug")} />
        </div>
        <div>
          <Label className="text-xs text-muted-foreground">Case Number</Label>
          <Input placeholder="SUV2026000013" {...register("action_payload.case_number")} />
        </div>
      </div>
      <div>
        <Label className="text-xs text-muted-foreground">Filing Name</Label>
        <Input placeholder="Opposition_Brief_2026-03-29.pdf" {...register("action_payload.filing_name")} />
      </div>
      <div>
        <Label className="text-xs text-muted-foreground">Filing Summary</Label>
        <Textarea
          placeholder="Short summary of the hostile filing or docket change..."
          rows={4}
          {...register("action_payload.filing_summary")}
        />
      </div>
      <div>
        <Label className="text-xs text-muted-foreground">Target Vault Path</Label>
        <Input
          placeholder="/mnt/fortress_nas/sectors/legal/fish-trap-suv2026000013/filings/outgoing"
          {...register("action_payload.target_vault_path")}
        />
      </div>
      <div className="flex items-center justify-between rounded-md border p-3">
        <div>
          <Label>Persist to Vault</Label>
          <p className="text-xs text-muted-foreground">
            Save the threat assessment JSON artifact into the sovereign NAS vault.
          </p>
        </div>
        <Controller
          control={control}
          name="action_payload.persist_to_vault"
          render={({ field }) => (
            <Switch checked={Boolean(field.value ?? true)} onCheckedChange={field.onChange} />
          )}
        />
      </div>
    </div>
  );
}

function ConciergeConflictFields({
  register,
  control,
}: {
  register: AutomationRegister;
  control: AutomationControl;
}) {
  return (
    <div className="pt-3 border-t space-y-3">
      <p className="text-xs text-muted-foreground">
        Maintenance Adjudicator. Cross-checks a guest complaint against recent work orders and the
        9-seat Concierge matrix before recommending corrective scheduling or refund posture.
      </p>
      <div>
        <Label className="text-xs text-muted-foreground">Trigger Type</Label>
        <Input
          placeholder="AUTOMATION_CONCIERGE_CONFLICT"
          {...register("action_payload.trigger_type")}
        />
      </div>
      <div>
        <Label className="text-xs text-muted-foreground">Fallback Message Text</Label>
        <Textarea
          placeholder="Optional explicit message body if the event payload does not include one..."
          rows={3}
          {...register("action_payload.inbound_message")}
        />
      </div>
      <div className="grid grid-cols-2 gap-3">
        <div>
          <Label className="text-xs text-muted-foreground">Guest ID Override</Label>
          <Input
            placeholder="Optional UUID"
            {...register("action_payload.guest_id")}
          />
        </div>
        <div>
          <Label className="text-xs text-muted-foreground">Reservation ID Override</Label>
          <Input
            placeholder="Optional UUID"
            {...register("action_payload.reservation_id")}
          />
        </div>
      </div>
      <div>
        <Label className="text-xs text-muted-foreground">Guest Phone Override</Label>
        <Input
          placeholder="+17065551212"
          {...register("action_payload.guest_phone")}
        />
      </div>
      <div className="flex items-center justify-between rounded-md border p-3">
        <div>
          <Label>Include Wi-Fi in Payload</Label>
          <p className="text-xs text-muted-foreground">
            Only enable when the automation is trusted to expose sensitive property credentials.
          </p>
        </div>
        <Controller
          control={control}
          name="action_payload.include_wifi_in_property_block"
          render={({ field }) => (
            <Switch checked={Boolean(field.value ?? false)} onCheckedChange={field.onChange} />
          )}
        />
      </div>
    </div>
  );
}
