import { isStorefrontHost } from "@/lib/domain-boundaries";

const API_BASE = process.env.NEXT_PUBLIC_API_URL ?? "";

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

const STAFF_AUTH_PUBLIC_PREFIXES = ["/login", "/sso", "/owner-login"] as const;

function shouldRedirectToStaffLogin(pathname: string, host: string): boolean {
  if (isStorefrontHost(host)) return false;
  return !STAFF_AUTH_PUBLIC_PREFIXES.some(
    (p) => pathname === p || pathname.startsWith(`${p}/`),
  );
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

  const res = await fetch(url, {
    ...fetchOpts,
    headers,
    credentials: "include",
    redirect: "follow",
  });

  if (res.status === 401) {
    const detail = await res
      .json()
      .then((d) => d?.detail || "Unauthorized")
      .catch(() => "Unauthorized");
    clearToken();
    if (
      typeof window !== "undefined" &&
      shouldRedirectToStaffLogin(window.location.pathname, window.location.hostname)
    ) {
      window.dispatchEvent(
        new CustomEvent("fortress:auth-expired", {
          detail: { path, message: detail },
        }),
      );
      window.location.href = "/login?expired=1";
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

  post: <T>(path: string, body?: unknown) =>
    request<T>(path, { method: "POST", body: body ? JSON.stringify(body) : undefined }),

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
      request<T>("/api/openshell/audit/log", {
        method: "GET",
        params: { limit },
      }),
    dispatch: <T>(body: unknown) =>
      request<T>("/api/vrs/hunter/dispatch", {
        method: "POST",
        body: JSON.stringify(body),
      }),
    approveVia: <T>(entryId: string, channel: "email" | "sms") =>
      request<T>(`/api/vrs/hunter/queue/${entryId}/approve`, {
        method: "POST",
        body: JSON.stringify({ channel }),
      }),
    editVia: <T>(entryId: string, finalMessage: string, channel: "email" | "sms") =>
      request<T>(`/api/vrs/hunter/queue/${entryId}/edit`, {
        method: "POST",
        body: JSON.stringify({ final_human_message: finalMessage, channel }),
      }),
    reject: <T>(entryId: string, reason?: string) =>
      request<T>(`/api/vrs/hunter/queue/${entryId}/reject`, {
        method: "POST",
        body: JSON.stringify(reason ? { reason } : {}),
      }),
    retryVia: <T>(entryId: string, channel: "email" | "sms") =>
      request<T>(`/api/vrs/hunter/queue/${entryId}/retry`, {
        method: "POST",
        body: JSON.stringify({ channel }),
      }),
  },
};

export { getToken, setToken, clearToken, ApiError, API_BASE };
