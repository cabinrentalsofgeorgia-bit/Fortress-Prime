"use server";

import { revalidatePath } from "next/cache";
import { cookies } from "next/headers";
import { buildBackendUrl } from "@/lib/server/backend-url";

const SESSION_COOKIE = "fortress_session";

export type ProvisionStaffActionState =
  | { status: "idle" }
  | { status: "success"; message: string; email: string; role: "manager" | "reviewer" }
  | { status: "error"; message: string };

type SessionUser = {
  email: string;
  role: string;
};

async function parseErrorMessage(response: Response, fallback: string): Promise<string> {
  const payload = (await response.json().catch(() => null)) as
    | { detail?: string | { message?: string } }
    | null;
  if (!payload?.detail) return fallback;
  if (typeof payload.detail === "string") return payload.detail;
  if (typeof payload.detail.message === "string") return payload.detail.message;
  return fallback;
}

async function requireSuperAdminSession(): Promise<string> {
  const cookieStore = await cookies();
  const token = cookieStore.get(SESSION_COOKIE)?.value;
  if (!token) {
    throw new Error("Super-admin session missing. Log in again and retry.");
  }

  const response = await fetch(buildBackendUrl("/api/auth/me"), {
    method: "GET",
    headers: {
      Authorization: `Bearer ${token}`,
    },
    cache: "no-store",
  });
  if (!response.ok) {
    throw new Error(await parseErrorMessage(response, "Unable to verify the current session."));
  }

  const user = (await response.json()) as SessionUser;
  if (user.role !== "super_admin") {
    throw new Error("Only super admins can provision staff accounts.");
  }
  return token;
}

export async function provisionStaffAccount(
  _previousState: ProvisionStaffActionState,
  formData: FormData,
): Promise<ProvisionStaffActionState> {
  try {
    const token = await requireSuperAdminSession();
    const email = String(formData.get("email") ?? "").trim().toLowerCase();
    const password = String(formData.get("password") ?? "");
    const role = String(formData.get("role") ?? "").trim().toLowerCase();

    if (!email || !password || !role) {
      return { status: "error", message: "Email, password, and role are required." };
    }
    if (password.length < 8) {
      return { status: "error", message: "Initial password must be at least 8 characters." };
    }
    if (role !== "manager" && role !== "reviewer") {
      return { status: "error", message: "Role must be manager or reviewer." };
    }

    const response = await fetch(buildBackendUrl("/api/staff/users"), {
      method: "POST",
      headers: {
        "Content-Type": "application/json",
        Authorization: `Bearer ${token}`,
      },
      cache: "no-store",
      body: JSON.stringify({ email, password, role }),
    });

    if (!response.ok) {
      return {
        status: "error",
        message: await parseErrorMessage(response, "Failed to provision staff account."),
      };
    }

    revalidatePath("/command/settings/staff");
    return {
      status: "success",
      message: `Provisioned ${role} access for ${email}.`,
      email,
      role,
    };
  } catch (error) {
    return {
      status: "error",
      message: error instanceof Error ? error.message : "Failed to provision staff account.",
    };
  }
}
