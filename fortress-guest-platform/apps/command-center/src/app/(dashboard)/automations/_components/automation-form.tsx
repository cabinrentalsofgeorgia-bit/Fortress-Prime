"use client";

import { useEffect } from "react";
import { Controller, FormProvider, useForm, useWatch, type Resolver } from "react-hook-form";
import { zodResolver } from "@hookform/resolvers/zod";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Switch } from "@/components/ui/switch";
import {
  Sheet,
  SheetContent,
  SheetHeader,
  SheetTitle,
  SheetDescription,
  SheetFooter,
} from "@/components/ui/sheet";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import { Separator } from "@/components/ui/separator";
import { Save, FlaskConical, Loader2 } from "lucide-react";
import { useCreateRule, useUpdateRule, useTestRule } from "@/lib/hooks";
import { AutomationFormSchema } from "@/lib/schemas/automations";
import type {
  AutomationFormSubmitValues,
  AutomationFormValues,
} from "@/lib/schemas/automations";
import type { AutomationRule } from "@/lib/types";
import { ConditionBuilder } from "./condition-builder";
import { ActionPayloadFields } from "./action-payload-fields";

const TARGET_ENTITIES = [
  { value: "reservation", label: "Reservation" },
  { value: "work_order", label: "Work Order" },
  { value: "guest", label: "Guest" },
  { value: "message", label: "Message" },
  { value: "legal_case", label: "Legal Case (Division 3)" },
  { value: "legal_document", label: "Legal Document (Division 3)" },
  { value: "discovery_pack", label: "Discovery Pack (Division 3)" },
];

const TRIGGER_EVENTS = [
  { value: "created", label: "Created" },
  { value: "updated", label: "Updated" },
  { value: "status_changed", label: "Status Changed" },
  { value: "deadline_approaching", label: "Deadline Approaching (72h)" },
  { value: "docket_updated", label: "Docket Updated" },
  { value: "opposing_counsel_correspondence", label: "Opposing Counsel Correspondence" },
];

const ACTION_TYPES = [
  { value: "send_email_template", label: "Send Email Template" },
  { value: "create_task", label: "Create Task" },
  { value: "notify_staff", label: "Notify Staff" },
  { value: "legal_search", label: "Paperclip: Legal Search" },
  { value: "legal_council", label: "Paperclip: 9-Seat Council" },
  { value: "legal_ingest", label: "Paperclip: Legal Ingest" },
  { value: "legal_deposition", label: "Paperclip: Deposition Outline" },
  { value: "draft_motion_extension", label: "Paperclip: Draft Motion Extension" },
  { value: "analyze_opposing_filing", label: "Paperclip: Analyze Opposing Filing" },
  { value: "concierge_conflict", label: "Paperclip: Concierge Conflict Mediator" },
];

const EMPTY_FORM: AutomationFormValues = {
  name: "",
  target_entity: "reservation",
  trigger_event: "created",
  conditions: { operator: "AND", rules: [] },
  action_type: "send_email_template",
  action_payload: {},
  is_active: false,
};

interface AutomationFormProps {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  editingRule: AutomationRule | null;
}

export function AutomationForm({
  open,
  onOpenChange,
  editingRule,
}: AutomationFormProps) {
  const createRule = useCreateRule();
  const updateRule = useUpdateRule();
  const testRule = useTestRule();

  const methods = useForm<AutomationFormValues>({
    resolver: zodResolver(AutomationFormSchema) as Resolver<AutomationFormValues>,
    defaultValues: EMPTY_FORM,
  });

  const {
    register,
    handleSubmit,
    control,
    reset,
    formState: { errors },
  } = methods;

  const targetEntity = useWatch({ control, name: "target_entity" });

  useEffect(() => {
    if (editingRule) {
      reset({
        name: editingRule.name,
        target_entity: editingRule.target_entity as AutomationFormValues["target_entity"],
        trigger_event: editingRule.trigger_event as AutomationFormValues["trigger_event"],
        conditions: {
          operator: (editingRule.conditions?.operator as "AND" | "OR") ?? "AND",
          rules: (editingRule.conditions?.rules ?? []).map((r) => ({
            field: r.field,
            operator: (r.op ?? "eq") as "eq" | "neq" | "gt" | "lt" | "contains",
            value: r.value as string | number,
          })),
        },
        action_type: editingRule.action_type as AutomationFormValues["action_type"],
        action_payload: editingRule.action_payload ?? {},
        is_active: editingRule.is_active ?? false,
      });
    } else {
      reset(EMPTY_FORM);
    }
  }, [editingRule, reset]);

  function onSubmit(data: AutomationFormSubmitValues) {
    const payload = {
      ...data,
      conditions: {
        operator: data.conditions.operator,
        rules: data.conditions.rules.map((r) => ({
          field: r.field,
          op: r.operator,
          value: r.value,
        })),
      },
    };

    if (editingRule) {
      updateRule.mutate(
        { id: editingRule.id, data: payload },
        {
          onSuccess: () => onOpenChange(false),
          onError: (err) => methods.setError("root", { message: err.message }),
        },
      );
    } else {
      createRule.mutate(payload, {
        onSuccess: () => {
          reset(EMPTY_FORM);
          onOpenChange(false);
        },
        onError: (err) => methods.setError("root", { message: err.message }),
      });
    }
  }

  function handleTest() {
    if (!editingRule) return;
    const values = methods.getValues();
    testRule.mutate({
      ruleId: editingRule.id,
      payload: {
        entity_type: values.target_entity,
        entity_id: "test-entity-001",
        event_type: values.trigger_event,
        previous_state: {},
        current_state: { status: "confirmed", num_guests: 4 },
      },
    });
  }

  const saving = createRule.isPending || updateRule.isPending;
  const isLegalTarget =
    targetEntity === "legal_case" ||
    targetEntity === "legal_document" ||
    targetEntity === "discovery_pack";

  return (
    <Sheet open={open} onOpenChange={onOpenChange}>
      <SheetContent side="right" className="sm:max-w-lg overflow-y-auto">
        <SheetHeader>
          <SheetTitle>
            {editingRule ? "Edit Rule" : "New Automation Rule"}
          </SheetTitle>
          <SheetDescription>
            {editingRule
              ? "Modify conditions and actions for this automation."
              : "Define when and how this automation should fire."}
          </SheetDescription>
        </SheetHeader>

        <FormProvider {...methods}>
          <form
            onSubmit={handleSubmit(onSubmit)}
            className="flex flex-col gap-5 px-4 pb-4"
          >
            {/* Name */}
            <div>
              <Label htmlFor="rule-name">Rule Name</Label>
              <Input
                id="rule-name"
                placeholder="e.g. Welcome email on new booking"
                {...register("name")}
              />
              {errors.name && (
                <p className="text-xs text-destructive mt-1">
                  {errors.name.message}
                </p>
              )}
            </div>

            {/* Entity + Trigger */}
            <div className="grid grid-cols-2 gap-3">
              <div>
                <Label className="text-xs text-muted-foreground">
                  Target Entity
                </Label>
                <Controller
                  control={control}
                  name="target_entity"
                  render={({ field }) => (
                    <Select value={field.value} onValueChange={field.onChange}>
                      <SelectTrigger className="w-full">
                        <SelectValue />
                      </SelectTrigger>
                      <SelectContent>
                        {TARGET_ENTITIES.map((e) => (
                          <SelectItem key={e.value} value={e.value}>
                            {e.label}
                          </SelectItem>
                        ))}
                      </SelectContent>
                    </Select>
                  )}
                />
              </div>
              <div>
                <Label className="text-xs text-muted-foreground">
                  Trigger Event
                </Label>
                <Controller
                  control={control}
                  name="trigger_event"
                  render={({ field }) => (
                    <Select value={field.value} onValueChange={field.onChange}>
                      <SelectTrigger className="w-full">
                        <SelectValue />
                      </SelectTrigger>
                      <SelectContent>
                        {TRIGGER_EVENTS.map((t) => (
                          <SelectItem key={t.value} value={t.value}>
                            {t.label}
                          </SelectItem>
                        ))}
                      </SelectContent>
                    </Select>
                  )}
                />
              </div>
            </div>

            {isLegalTarget && (
              <div className="rounded-md border border-amber-500/30 bg-amber-500/5 p-3 text-xs text-amber-200">
                Division 3 workflow selected. This rule can target the Legal Hivemind and Paperclip bridge.
              </div>
            )}

            {/* Conditions Panel */}
            <div className="space-y-4 rounded-lg border p-4">
              <h3 className="text-sm font-semibold">Conditions</h3>
              <ConditionBuilder targetEntity={targetEntity} />
            </div>

            {/* Execution Action Panel */}
            <div className="space-y-4 rounded-lg border p-4">
              <h3 className="text-sm font-semibold">Execution Action</h3>
              <div>
                <Label className="text-xs text-muted-foreground">
                  Action Type
                </Label>
                <Controller
                  control={control}
                  name="action_type"
                  render={({ field }) => (
                    <Select value={field.value} onValueChange={field.onChange}>
                      <SelectTrigger className="w-full">
                        <SelectValue />
                      </SelectTrigger>
                      <SelectContent>
                        {ACTION_TYPES.map((a) => (
                          <SelectItem key={a.value} value={a.value}>
                            {a.label}
                          </SelectItem>
                        ))}
                      </SelectContent>
                    </Select>
                  )}
                />
              </div>
              <Separator />
              <ActionPayloadFields />
            </div>

            {/* Active toggle */}
            <div className="flex items-center justify-between">
              <div>
                <Label>Active</Label>
                <p className="text-xs text-muted-foreground">
                  Rule only fires when active
                </p>
              </div>
              <Controller
                control={control}
                name="is_active"
                render={({ field }) => (
                  <Switch
                    checked={field.value ?? false}
                    onCheckedChange={field.onChange}
                  />
                )}
              />
            </div>

            {errors.root?.message && (
              <p className="text-sm font-medium text-destructive">
                {errors.root.message}
              </p>
            )}

            <SheetFooter className="flex-row gap-2 p-0 pt-2">
              {editingRule && (
                <Button
                  type="button"
                  variant="outline"
                  size="sm"
                  onClick={handleTest}
                  disabled={testRule.isPending}
                >
                  <FlaskConical className="mr-1 h-3.5 w-3.5" />
                  {testRule.isPending ? "Testing..." : "Test Rule"}
                </Button>
              )}
              <Button type="submit" size="sm" disabled={saving} className="ml-auto">
                {saving ? (
                  <Loader2 className="mr-1 h-3.5 w-3.5 animate-spin" />
                ) : (
                  <Save className="mr-1 h-3.5 w-3.5" />
                )}
                {saving
                  ? "Deploying..."
                  : editingRule
                    ? "Update Automation"
                    : "Deploy Automation"}
              </Button>
            </SheetFooter>
          </form>
        </FormProvider>
      </SheetContent>
    </Sheet>
  );
}
