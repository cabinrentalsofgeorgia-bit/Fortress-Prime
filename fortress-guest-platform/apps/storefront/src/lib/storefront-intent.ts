import { getStorefrontSessionId } from "@/lib/storefront-session";

const STOREFRONT_MARKETING_CONSENT_KEY = "fgp_marketing_consent";
const STOREFRONT_INTENT_SENT_PREFIX = "fgp_intent_sent";

export type StorefrontIntentEventType =
  | "page_view"
  | "property_view"
  | "quote_open"
  | "checkout_step"
  | "insight_impression"
  | "consent_granted"
  | "consent_revoked"
  | "nudge_dismissed";

type PostStorefrontIntentEventInput = {
  eventType: StorefrontIntentEventType;
  propertySlug?: string | null;
  meta?: Record<string, unknown>;
  consentMarketing?: boolean;
  dedupeKey?: string;
};

function readStorefrontMarketingConsent(): boolean {
  if (typeof window === "undefined") {
    return false;
  }
  try {
    return window.localStorage.getItem(STOREFRONT_MARKETING_CONSENT_KEY) === "true";
  } catch {
    return false;
  }
}

function normalizePropertySlug(value: string | null | undefined): string | null {
  if (!value) {
    return null;
  }
  const normalized = value.trim().toLowerCase();
  return normalized || null;
}

function dedupeStorageKey(dedupeKey: string): string {
  return `${STOREFRONT_INTENT_SENT_PREFIX}:${dedupeKey}`;
}

export async function postStorefrontIntentEvent({
  eventType,
  propertySlug,
  meta = {},
  consentMarketing,
  dedupeKey,
}: PostStorefrontIntentEventInput): Promise<boolean> {
  if (typeof window === "undefined") {
    return false;
  }

  try {
    if (dedupeKey && window.sessionStorage.getItem(dedupeStorageKey(dedupeKey))) {
      return true;
    }
  } catch {
    return false;
  }

  const sessionId = getStorefrontSessionId();
  if (!sessionId) {
    return false;
  }

  try {
    const response = await fetch("/api/storefront/intent/event", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      credentials: "same-origin",
      body: JSON.stringify({
        session_id: sessionId,
        event_type: eventType,
        consent_marketing: consentMarketing ?? readStorefrontMarketingConsent(),
        property_slug: normalizePropertySlug(propertySlug),
        meta,
      }),
    });
    if (!response.ok) {
      return false;
    }
    if (dedupeKey) {
      window.sessionStorage.setItem(dedupeStorageKey(dedupeKey), "1");
    }
    return true;
  } catch {
    return false;
  }
}
