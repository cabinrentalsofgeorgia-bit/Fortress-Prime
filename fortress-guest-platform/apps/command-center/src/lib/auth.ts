import { api, setToken, clearToken, getToken } from "./api";

export interface StaffUser {
  id: string;
  email: string;
  first_name: string;
  last_name: string;
  role: "super_admin" | "manager" | "reviewer";
  is_active?: boolean;
  notification_phone?: string | null;
  notification_email?: string | null;
}

export interface LoginResponse {
  access_token: string;
  token_type: string;
  user: StaffUser;
  /** Seconds; matches JWT lifetime and fortress_session cookie (from BFF). */
  expires_in?: number;
}

export async function login(email: string, password: string): Promise<LoginResponse> {
  const res = await api.post<LoginResponse>("/api/auth/login", { email, password });
  setToken(res.access_token);
  return res;
}

export async function logout(): Promise<void> {
  try {
    await fetch("/api/auth/logout", {
      method: "POST",
      credentials: "include",
    });
  } finally {
    clearToken();
    localStorage.removeItem("fgp_user");
    window.location.href = "/login";
  }
}

export function isAuthenticated(): boolean {
  return !!getToken() || !!getStoredUser();
}

export async function fetchMe(): Promise<StaffUser> {
  type MePayload = StaffUser & { access_token?: string };
  const raw = await api.get<MePayload>("/api/auth/me");
  const { access_token, ...user } = raw;
  if (access_token) {
    setToken(access_token);
  }
  return user as StaffUser;
}

export function getStoredUser(): StaffUser | null {
  if (typeof window === "undefined") return null;
  const raw = localStorage.getItem("fgp_user");
  if (!raw) return null;
  try {
    return JSON.parse(raw);
  } catch {
    return null;
  }
}

export function storeUser(user: StaffUser) {
  localStorage.setItem("fgp_user", JSON.stringify(user));
}

export async function bootstrapSession(): Promise<StaffUser> {
  const user = await fetchMe();
  storeUser(user);
  return user;
}
