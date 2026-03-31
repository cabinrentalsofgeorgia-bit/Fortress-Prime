import { z } from "zod";

export const ConditionRuleSchema = z.object({
  field: z.string().min(1, "Field is required"),
  operator: z.enum(["eq", "neq", "gt", "lt", "contains"]),
  value: z.union([z.string(), z.number()]),
});

const SendEmailPayloadSchema = z.object({
  template_id: z.string().uuid("Must select a valid template"),
  recipient_role: z.enum(["guest", "cleaner", "owner", "staff"]),
});

const CreateTaskPayloadSchema = z.object({
  task_type: z.string(),
  priority: z.enum(["low", "medium", "high", "urgent"]),
  assigned_to: z.string().uuid().optional(),
});

export const AutomationFormSchema = z.object({
  name: z.string().min(3, "Rule name must be at least 3 characters"),
  target_entity: z.enum([
    "reservation",
    "work_order",
    "message",
    "guest",
    "legal_case",
    "legal_document",
    "discovery_pack",
  ]),
  trigger_event: z.enum([
    "created",
    "updated",
    "status_changed",
    "deadline_approaching",
    "docket_updated",
    "opposing_counsel_correspondence",
  ]),
  conditions: z.object({
    operator: z.enum(["AND", "OR"]),
    rules: z.array(ConditionRuleSchema),
  }),
  action_type: z.enum([
    "send_email_template",
    "create_task",
    "notify_staff",
    "legal_search",
    "legal_council",
    "legal_ingest",
    "legal_deposition",
    "draft_motion_extension",
    "analyze_opposing_filing",
    "concierge_conflict",
  ]),
  action_payload: z.record(z.string(), z.any()),
  is_active: z.boolean().default(false),
});

export type AutomationFormValues = z.input<typeof AutomationFormSchema>;
export type AutomationFormSubmitValues = z.output<typeof AutomationFormSchema>;
export type ConditionRule = z.infer<typeof ConditionRuleSchema>;

export { SendEmailPayloadSchema, CreateTaskPayloadSchema };
