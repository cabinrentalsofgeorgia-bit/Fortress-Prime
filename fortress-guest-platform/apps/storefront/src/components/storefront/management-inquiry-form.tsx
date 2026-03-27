"use client";

import { useState } from "react";
import { zodResolver } from "@hookform/resolvers/zod";
import { CheckCircle2, LoaderCircle, ShieldAlert } from "lucide-react";
import { useForm } from "react-hook-form";
import { toast } from "sonner";
import { z } from "zod";

import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Textarea } from "@/components/ui/textarea";
import { getStorefrontSessionId } from "@/lib/storefront-session";

const LEGACY_CONFIRMATION_MESSAGE = "Thank you! Your message has been sent!";
const SHADOW_SESSION_KEY = "fgp_session_id";

const managementInquirySchema = z.object({
  first_name: z.string().trim().min(1, "First name is required.").max(120, "First name is too long."),
  last_name: z.string().trim().min(1, "Last name is required.").max(120, "Last name is too long."),
  email_address: z.email("Enter a valid email address."),
  phone: z.string().trim().min(7, "Phone is required.").max(40, "Phone number is too long."),
  property_street_address: z
    .string()
    .trim()
    .max(1000, "Property address is too long.")
    .optional()
    .or(z.literal("")),
  message: z.string().trim().max(5000, "Message is too long.").optional().or(z.literal("")),
});

type ManagementInquiryValues = z.infer<typeof managementInquirySchema>;

function resolveShadowSessionId(): string | null {
  if (typeof window === "undefined") {
    return null;
  }

  const localShadowId = window.localStorage.getItem(SHADOW_SESSION_KEY);
  if (z.uuid().safeParse(localShadowId).success) {
    return localShadowId;
  }

  const storefrontSessionId = getStorefrontSessionId();
  if (typeof storefrontSessionId === "string" && z.uuid().safeParse(storefrontSessionId).success) {
    window.localStorage.setItem(SHADOW_SESSION_KEY, storefrontSessionId);
    return storefrontSessionId;
  }

  return null;
}

function buildRetryMessage(retryAfterSeconds: number | null): string {
  if (!retryAfterSeconds || retryAfterSeconds <= 0) {
    return "Too many requests. Please try again later.";
  }
  const retryAfterMinutes = Math.max(1, Math.ceil(retryAfterSeconds / 60));
  return `Too many requests. Please wait about ${retryAfterMinutes} minute${retryAfterMinutes === 1 ? "" : "s"} before trying again.`;
}

export function ManagementInquiryForm() {
  const [successMessage, setSuccessMessage] = useState<string | null>(null);
  const [submitError, setSubmitError] = useState<string | null>(null);

  const form = useForm<ManagementInquiryValues>({
    resolver: zodResolver(managementInquirySchema),
    defaultValues: {
      first_name: "",
      last_name: "",
      email_address: "",
      phone: "",
      property_street_address: "",
      message: "",
    },
  });

  const {
    register,
    handleSubmit,
    formState: { errors, isSubmitting },
    reset,
  } = form;

  const onSubmit = handleSubmit(async (values) => {
    setSubmitError(null);
    setSuccessMessage(null);

    const sessionId = resolveShadowSessionId();
    const payload = {
      ...values,
      property_street_address: values.property_street_address?.trim() || null,
      message: values.message?.trim() || null,
      session_id: sessionId,
    };

    const response = await fetch("/api/dispatch/contact-form", {
      method: "POST",
      headers: {
        "Content-Type": "application/json",
      },
      credentials: "same-origin",
      body: JSON.stringify(payload),
    });

    if (response.status === 429) {
      const retryAfter = Number(response.headers.get("retry-after") || "0");
      const message = buildRetryMessage(Number.isFinite(retryAfter) ? retryAfter : 0);
      setSubmitError(message);
      toast.error(message);
      return;
    }

    if (!response.ok) {
      const detail = await response
        .json()
        .then((body) => (typeof body?.detail === "string" ? body.detail : "Unable to submit your request right now."))
        .catch(() => "Unable to submit your request right now.");
      setSubmitError(detail);
      toast.error(detail);
      return;
    }

    reset();
    setSuccessMessage(LEGACY_CONFIRMATION_MESSAGE);
    toast.success(LEGACY_CONFIRMATION_MESSAGE);
  });

  return (
    <div className="rounded-[2rem] border border-slate-700/70 bg-slate-950/90 p-6 shadow-2xl shadow-slate-950/40 backdrop-blur sm:p-8">
      <div className="mb-6 space-y-3">
        <div className="inline-flex items-center gap-2 rounded-full border border-sky-500/30 bg-sky-500/10 px-3 py-1 text-[11px] font-semibold uppercase tracking-[0.24em] text-sky-100">
          Public Bridge for Node 2719
        </div>
        <div className="space-y-2">
          <h2 className="text-2xl font-semibold tracking-tight text-white">Property Management Inquiry</h2>
          <p className="text-sm leading-7 text-slate-300">
            Secure your place in the Sovereign lead ledger. This bridge mirrors the legacy workflow while routing
            directly into the new dispatch API.
          </p>
        </div>
      </div>

      <form className="space-y-5" onSubmit={onSubmit} noValidate>
        <div className="grid gap-5 sm:grid-cols-2">
          <div className="space-y-2">
            <Label htmlFor="first_name" className="text-slate-100">
              First Name
            </Label>
            <Input
              id="first_name"
              autoComplete="given-name"
              className="border-slate-700 bg-slate-900 text-slate-50 placeholder:text-slate-500"
              aria-invalid={errors.first_name ? "true" : "false"}
              {...register("first_name")}
            />
            {errors.first_name ? <p className="text-sm text-rose-300">{errors.first_name.message}</p> : null}
          </div>

          <div className="space-y-2">
            <Label htmlFor="last_name" className="text-slate-100">
              Last Name
            </Label>
            <Input
              id="last_name"
              autoComplete="family-name"
              className="border-slate-700 bg-slate-900 text-slate-50 placeholder:text-slate-500"
              aria-invalid={errors.last_name ? "true" : "false"}
              {...register("last_name")}
            />
            {errors.last_name ? <p className="text-sm text-rose-300">{errors.last_name.message}</p> : null}
          </div>
        </div>

        <div className="grid gap-5 sm:grid-cols-2">
          <div className="space-y-2">
            <Label htmlFor="email_address" className="text-slate-100">
              Email Address
            </Label>
            <Input
              id="email_address"
              type="email"
              autoComplete="email"
              className="border-slate-700 bg-slate-900 text-slate-50 placeholder:text-slate-500"
              aria-invalid={errors.email_address ? "true" : "false"}
              {...register("email_address")}
            />
            {errors.email_address ? <p className="text-sm text-rose-300">{errors.email_address.message}</p> : null}
          </div>

          <div className="space-y-2">
            <Label htmlFor="phone" className="text-slate-100">
              Phone
            </Label>
            <Input
              id="phone"
              autoComplete="tel"
              className="border-slate-700 bg-slate-900 text-slate-50 placeholder:text-slate-500"
              aria-invalid={errors.phone ? "true" : "false"}
              {...register("phone")}
            />
            {errors.phone ? <p className="text-sm text-rose-300">{errors.phone.message}</p> : null}
          </div>
        </div>

        <div className="space-y-2">
          <Label htmlFor="property_street_address" className="text-slate-100">
            Property Street Address
          </Label>
          <Textarea
            id="property_street_address"
            rows={3}
            className="border-slate-700 bg-slate-900 text-slate-50 placeholder:text-slate-500"
            aria-invalid={errors.property_street_address ? "true" : "false"}
            {...register("property_street_address")}
          />
          {errors.property_street_address ? (
            <p className="text-sm text-rose-300">{errors.property_street_address.message}</p>
          ) : null}
        </div>

        <div className="space-y-2">
          <Label htmlFor="message" className="text-slate-100">
            Message
          </Label>
          <Textarea
            id="message"
            rows={6}
            className="border-slate-700 bg-slate-900 text-slate-50 placeholder:text-slate-500"
            aria-invalid={errors.message ? "true" : "false"}
            {...register("message")}
          />
          {errors.message ? <p className="text-sm text-rose-300">{errors.message.message}</p> : null}
        </div>

        <div className="rounded-2xl border border-slate-800 bg-slate-900/80 px-4 py-3 text-sm text-slate-300">
          <div className="flex items-start gap-3">
            <ShieldAlert className="mt-0.5 h-4 w-4 flex-none text-sky-300" />
            <div className="space-y-1">
              <p className="font-medium text-slate-100">Sovereign safeguards</p>
              <p>The storefront enforces the legacy throttle: no more than 4 inquiries per hour.</p>
              <p>Shadow session linkage is attached automatically for this browser before dispatch.</p>
            </div>
          </div>
        </div>

        {submitError ? (
          <div className="rounded-2xl border border-rose-500/30 bg-rose-500/10 px-4 py-3 text-sm text-rose-100">
            {submitError}
          </div>
        ) : null}

        {successMessage ? (
          <div className="rounded-2xl border border-emerald-500/30 bg-emerald-500/10 px-4 py-3 text-sm text-emerald-100">
            <div className="flex items-center gap-2">
              <CheckCircle2 className="h-4 w-4" />
              <span>{successMessage}</span>
            </div>
          </div>
        ) : null}

        <Button
          type="submit"
          size="lg"
          className="w-full rounded-xl bg-sky-500 text-slate-950 hover:bg-sky-400"
          disabled={isSubmitting}
        >
          {isSubmitting ? (
            <>
              <LoaderCircle className="h-4 w-4 animate-spin" />
              Sending inquiry...
            </>
          ) : (
            "Request More Info"
          )}
        </Button>
      </form>
    </div>
  );
}
