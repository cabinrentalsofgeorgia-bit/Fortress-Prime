/**
 * First-party storefront session id (intent lane / funnel bridge).
 * Must stay aligned with SovereignNudge session storage.
 */
export const STOREFRONT_SESSION_STORAGE_KEY = "fgp_storefront_session_id";

/** Returns a stable per-tab session UUID; creates one if missing. */
export function getStorefrontSessionId(): string | null {
  if (typeof window === "undefined") return null;
  try {
    let id = window.sessionStorage.getItem(STOREFRONT_SESSION_STORAGE_KEY);
    if (!id) {
      id = crypto.randomUUID();
      window.sessionStorage.setItem(STOREFRONT_SESSION_STORAGE_KEY, id);
    }
    return id;
  } catch {
    return null;
  }
}
