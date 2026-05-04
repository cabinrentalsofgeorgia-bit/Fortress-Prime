import { isStorefrontHost, isStaffHost } from "@/lib/domain-boundaries";

const API_BASE = process.env.NEXT_PUBLIC_API_URL ?? "";

let warnedStaffDirectApi = false;

/** Staff Command Center must use same-origin `/api/*` BFF; direct API base breaks the sovereign glass model. */
function warnIfStaffHostBypassesBff(): void {
  if (warnedStaffDirectApi || typeof window === "undefined" || !API_BASE) return;
  if (isStorefrontHost(window.location.hostname)) return;
  if (isStaffHost(window.location.hostname)) {
    warnedStaffDirectApi = true;
    console.warn(
      "[Fortress] NEXT_PUBLIC_API_URL is set on a staff host. Unset it so all API traffic uses the Next.js BFF and fortress_session.",
    );
  }
}

function resolveBase(path: string): string {
  if (path.startsWith("/api/")) return "";
  return API_BASE;
}

interface RequestOptions extends RequestInit {
  params?: Record<string, string | number | boolean | undefined>;
}

class ApiError extends Error {
  status: number;
  data: unknown;
  constructor(status: number, message: string, data?: unknown) {
    super(message);
    this.status = status;
    this.data = data;
  }
}

function getToken(): string | null {
  if (typeof window === "undefined") return null;
  return localStorage.getItem("fgp_token");
}

function setToken(token: string) {
  localStorage.setItem("fgp_token", token);
}

function clearToken() {
  localStorage.removeItem("fgp_token");
}

function resolveUnauthorizedRedirect(pathname: string, host: string): string | null {
  if (pathname.startsWith("/owner")) return "/owner-login";
  if (isStorefrontHost(host)) return null;
  if (pathname.startsWith("/login")) return null;
  return "/login?expired=1";
}

async function request<T>(path: string, options: RequestOptions = {}): Promise<T> {
  const { params, ...fetchOpts } = options;

  let url = `${resolveBase(path)}${path}`;
  if (params) {
    const qs = new URLSearchParams();
    for (const [k, v] of Object.entries(params)) {
      if (v !== undefined) qs.set(k, String(v));
    }
    const s = qs.toString();
    if (s) url += `?${s}`;
  }

  const headers: Record<string, string> = {
    ...(fetchOpts.headers as Record<string, string>),
  };
  if (fetchOpts.body && !(fetchOpts.body instanceof FormData) && !headers["Content-Type"]) {
    headers["Content-Type"] = "application/json";
  }

  const token = getToken();
  if (token) headers["Authorization"] = `Bearer ${token}`;

  warnIfStaffHostBypassesBff();

  const res = await fetch(url, {
    ...fetchOpts,
    headers,
    credentials: "include",
    redirect: "follow",
    cache: "no-store",
  });

  if (res.status === 401) {
    const detail = await res
      .json()
      .then((d) => d?.detail || "Unauthorized")
      .catch(() => "Unauthorized");
    clearToken();
    if (typeof window !== "undefined") {
      const redirectPath = resolveUnauthorizedRedirect(
        window.location.pathname,
        window.location.hostname,
      );
      if (window.location.pathname.startsWith("/owner")) {
        localStorage.removeItem("fgp_owner_profile");
      }
      if (redirectPath) {
      window.dispatchEvent(
        new CustomEvent("fortress:auth-expired", {
          detail: { path, message: detail },
        }),
      );
        window.location.href = redirectPath;
      }
    }
    throw new ApiError(401, detail);
  }

  if (!res.ok) {
    const data = await res.json().catch(() => null);
    throw new ApiError(res.status, data?.detail || res.statusText, data);
  }

  if (res.status === 204) return null as T;
  return res.json();
}

export const api = {
  get: <T>(path: string, params?: Record<string, string | number | boolean | undefined>) =>
    request<T>(path, { method: "GET", params }),

  post: <T>(path: string, body?: unknown, options?: Pick<RequestOptions, "headers">) =>
    request<T>(path, {
      method: "POST",
      body: body ? JSON.stringify(body) : undefined,
      headers: options?.headers,
    }),

  put: <T>(path: string, body?: unknown) =>
    request<T>(path, { method: "PUT", body: body ? JSON.stringify(body) : undefined }),

  patch: <T>(path: string, body?: unknown) =>
    request<T>(path, { method: "PATCH", body: body ? JSON.stringify(body) : undefined }),

  delete: <T>(path: string) => request<T>(path, { method: "DELETE" }),

  hunter: {
    queue: <T>(status = "pending_review", limit = 50) =>
      request<T>("/api/vrs/hunter/queue", {
        method: "GET",
        params: { status_filter: status, limit },
      }),
    metrics: <T>() => request<T>("/api/vrs/hunter/queue/stats", { method: "GET" }),
    activity: <T>(limit = 20) =>
      request<T>("/api/hunter/activity", {
        method: "GET",
        params: { limit },
      }),
    dispatch: <T>(body: {
      guest_id: string;
      full_name: string;
      target_score: number;
    }) => request<T>("/api/vrs/hunter/dispatch", { method: "POST", body: JSON.stringify(body) }),
    approve: <T>(entryId: string, reviewedBy = "operator") =>
      request<T>(`/api/vrs/hunter/queue/${entryId}/approve`, {
        method: "POST",
        body: JSON.stringify({ reviewed_by: reviewedBy }),
      }),
    approveVia: <T>(entryId: string, channel: "email" | "sms", reviewedBy = "operator") =>
      request<T>(`/api/vrs/hunter/queue/${entryId}/approve`, {
        method: "POST",
        body: JSON.stringify({ reviewed_by: reviewedBy, channel }),
      }),
    edit: <T>(entryId: string, finalMessage: string, reviewedBy = "operator") =>
      request<T>(`/api/vrs/hunter/queue/${entryId}/edit`, {
        method: "POST",
        body: JSON.stringify({
          final_human_message: finalMessage,
          reviewed_by: reviewedBy,
        }),
      }),
    editVia: <T>(
      entryId: string,
      finalMessage: string,
      channel: "email" | "sms",
      reviewedBy = "operator",
    ) =>
      request<T>(`/api/vrs/hunter/queue/${entryId}/edit`, {
        method: "POST",
        body: JSON.stringify({
          final_human_message: finalMessage,
          reviewed_by: reviewedBy,
          channel,
        }),
      }),
    reject: <T>(entryId: string, reason?: string, reviewedBy = "operator") =>
      request<T>(`/api/vrs/hunter/queue/${entryId}/reject`, {
        method: "POST",
        body: JSON.stringify({
          reviewed_by: reviewedBy,
          reason,
        }),
      }),
    retry: <T>(entryId: string, reviewedBy = "operator") =>
      request<T>(`/api/vrs/hunter/queue/${entryId}/retry`, {
        method: "POST",
        body: JSON.stringify({
          reviewed_by: reviewedBy,
        }),
      }),
    retryVia: <T>(entryId: string, channel: "email" | "sms", reviewedBy = "operator") =>
      request<T>(`/api/vrs/hunter/queue/${entryId}/retry`, {
        method: "POST",
        body: JSON.stringify({
          reviewed_by: reviewedBy,
          channel,
        }),
      }),
    audit: <T>(body: {
      event_name: string;
      resource_type?: string;
      resource_id?: string;
      outcome?: string;
      metadata_json?: Record<string, unknown>;
    }) => request<T>("/api/vrs/hunter/audit", { method: "POST", body: JSON.stringify(body) }),
  },
};

export { getToken, setToken, clearToken, ApiError, API_BASE };
