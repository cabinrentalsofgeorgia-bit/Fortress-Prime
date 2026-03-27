import { unstable_noStore as noStore } from "next/cache";
import { cookies } from "next/headers";
import { notFound, redirect } from "next/navigation";
import {
  Eye,
  Shield,
  ShieldCheck,
  ShieldEllipsis,
  UserCog,
} from "lucide-react";

import { Badge } from "@/components/ui/badge";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { buildBackendUrl } from "@/lib/server/backend-url";

import { ProvisionAccountForm } from "./provision-account-form";

const SESSION_COOKIE = "fortress_session";

type SessionUser = {
  email: string;
  role: string;
};

type StaffMember = {
  id: string;
  email: string;
  first_name: string;
  last_name: string;
  role: "super_admin" | "manager" | "reviewer";
  is_active: boolean;
  last_login_at: string | null;
  created_at: string;
  updated_at: string;
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

async function fetchWithSession<T>(path: string, token: string): Promise<T> {
  const response = await fetch(buildBackendUrl(path), {
    method: "GET",
    headers: {
      Authorization: `Bearer ${token}`,
    },
    cache: "no-store",
  });

  if (response.status === 401) {
    redirect("/login?expired=1");
  }
  if (!response.ok) {
    throw new Error(await parseErrorMessage(response, `Failed to load ${path}`));
  }

  return (await response.json()) as T;
}

function formatLastSeen(value: string | null): string {
  if (!value) return "No login recorded";
  return new Date(value).toLocaleString();
}

function roleBadgeClasses(role: StaffMember["role"]): string {
  if (role === "super_admin") return "border-red-500/30 bg-red-500/10 text-red-200";
  if (role === "manager") return "border-amber-500/30 bg-amber-500/10 text-amber-200";
  return "border-cyan-500/30 bg-cyan-500/10 text-cyan-200";
}

function roleIcon(role: StaffMember["role"]) {
  if (role === "super_admin") return <ShieldEllipsis className="h-4 w-4 text-red-300" />;
  if (role === "manager") return <ShieldCheck className="h-4 w-4 text-amber-300" />;
  return <Eye className="h-4 w-4 text-cyan-300" />;
}

export default async function StaffSettingsPage() {
  noStore();

  const cookieStore = await cookies();
  const token = cookieStore.get(SESSION_COOKIE)?.value;
  if (!token) {
    redirect("/login?expired=1");
  }

  const [currentUser, staffUsers] = await Promise.all([
    fetchWithSession<SessionUser>("/api/auth/me", token),
    fetchWithSession<StaffMember[]>("/api/staff/users", token),
  ]);

  if (currentUser.role !== "super_admin") {
    notFound();
  }

  const activeUsers = staffUsers.filter((user) => user.is_active);
  const managerCount = activeUsers.filter((user) => user.role === "manager").length;
  const reviewerCount = activeUsers.filter((user) => user.role === "reviewer").length;
  const superAdminCount = activeUsers.filter((user) => user.role === "super_admin").length;

  return (
    <div className="space-y-6">
      <div className="flex flex-col gap-4 lg:flex-row lg:items-end lg:justify-between">
        <div className="space-y-2">
          <div className="inline-flex items-center gap-2 rounded-full border border-emerald-500/30 bg-emerald-500/10 px-3 py-1 text-xs font-medium uppercase tracking-[0.24em] text-emerald-200">
            <Shield className="h-3.5 w-3.5" />
            Sovereign RBAC Ledger
          </div>
          <div>
            <h1 className="text-3xl font-semibold tracking-tight text-zinc-50">Staff Settings</h1>
            <p className="mt-1 max-w-2xl text-sm text-zinc-400">
              Root-only control plane for scoped staff access across Fortress Prime.
            </p>
          </div>
        </div>
        <ProvisionAccountForm />
      </div>

      <div className="grid gap-4 md:grid-cols-3">
        <Card className="border-red-500/20 bg-zinc-950/80">
          <CardHeader className="pb-3">
            <CardDescription>Full iron access</CardDescription>
            <CardTitle className="text-2xl text-zinc-50">{superAdminCount}</CardTitle>
          </CardHeader>
        </Card>
        <Card className="border-amber-500/20 bg-zinc-950/80">
          <CardHeader className="pb-3">
            <CardDescription>Managers can approve pricing and SEO</CardDescription>
            <CardTitle className="text-2xl text-zinc-50">{managerCount}</CardTitle>
          </CardHeader>
        </Card>
        <Card className="border-cyan-500/20 bg-zinc-950/80">
          <CardHeader className="pb-3">
            <CardDescription>Reviewers hold read-only queue access</CardDescription>
            <CardTitle className="text-2xl text-zinc-50">{reviewerCount}</CardTitle>
          </CardHeader>
        </Card>
      </div>

      <Card className="border-zinc-800 bg-zinc-950/80">
        <CardHeader className="flex flex-col gap-2 lg:flex-row lg:items-center lg:justify-between">
          <div>
            <CardTitle className="flex items-center gap-2 text-zinc-50">
              <UserCog className="h-5 w-5 text-emerald-300" />
              Active Staff Ledger
            </CardTitle>
            <CardDescription>
              Session owner: {currentUser.email}. Active operators are shown below with live role posture.
            </CardDescription>
          </div>
          <Badge variant="outline" className="w-fit border-zinc-700 bg-zinc-900 text-zinc-200">
            {activeUsers.length} active accounts
          </Badge>
        </CardHeader>
        <CardContent className="space-y-3">
          {staffUsers.length === 0 ? (
            <div className="rounded-xl border border-dashed border-zinc-800 bg-zinc-900/60 px-4 py-6 text-sm text-zinc-400">
              No staff accounts detected.
            </div>
          ) : (
            staffUsers.map((user) => (
              <div
                key={user.id}
                className="flex flex-col gap-4 rounded-xl border border-zinc-800 bg-zinc-900/70 px-4 py-4 lg:flex-row lg:items-center lg:justify-between"
              >
                <div className="space-y-2">
                  <div className="flex items-center gap-3">
                    <div className="flex h-10 w-10 items-center justify-center rounded-full border border-zinc-800 bg-zinc-950 text-sm font-semibold text-zinc-100">
                      {user.first_name[0]}
                      {user.last_name[0]}
                    </div>
                    <div>
                      <p className="text-sm font-medium text-zinc-100">
                        {user.first_name} {user.last_name}
                      </p>
                      <p className="text-xs text-zinc-400">{user.email}</p>
                    </div>
                  </div>
                  <div className="flex flex-wrap items-center gap-2">
                    <Badge variant="outline" className={roleBadgeClasses(user.role)}>
                      <span className="mr-1 inline-flex">{roleIcon(user.role)}</span>
                      {user.role.replace("_", " ")}
                    </Badge>
                    <Badge
                      variant="outline"
                      className={
                        user.is_active
                          ? "border-emerald-500/30 bg-emerald-500/10 text-emerald-200"
                          : "border-zinc-700 bg-zinc-900 text-zinc-400"
                      }
                    >
                      {user.is_active ? "Active" : "Inactive"}
                    </Badge>
                  </div>
                </div>
                <div className="grid gap-1 text-xs text-zinc-400 lg:text-right">
                  <span>Last seen: {formatLastSeen(user.last_login_at)}</span>
                  <span>Provisioned: {new Date(user.created_at).toLocaleString()}</span>
                </div>
              </div>
            ))
          )}
        </CardContent>
      </Card>
    </div>
  );
}
