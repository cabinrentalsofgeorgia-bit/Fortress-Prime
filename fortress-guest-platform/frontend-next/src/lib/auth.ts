import { api, setToken, clearToken, getToken } from "./api";

export interface StaffUser {
  id: string;
  email: string;
  first_name: string;
  last_name: string;
  role: string;
  is_active?: boolean;
  notification_phone?: string | null;
  notification_email?: string | null;
}

export interface LoginResponse {
  access_token: string;
  token_type?: string;
  user: StaffUser;
}

export async function login(username: string, password: string): Promise<LoginResponse> {
  const res = await api.post<LoginResponse>("/api/auth/login", { username, password });
  setToken(res.access_token);
  return res;
}

export function logout() {
  clearToken();
  localStorage.removeItem("fgp_user");
  window.location.href = "/login";
}

export function isAuthenticated(): boolean {
  return !!getToken();
}

export async function fetchMe(): Promise<StaffUser> {
  return api.get<StaffUser>("/api/auth/me");
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
