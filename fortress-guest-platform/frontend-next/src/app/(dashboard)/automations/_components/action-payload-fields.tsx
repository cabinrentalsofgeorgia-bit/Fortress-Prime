"use client";

import { Controller, useFormContext, type Control, type UseFormRegister } from "react-hook-form";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
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
