"use client";

import { useMemo } from "react";
import { Bell, LogOut } from "lucide-react";
import { usePathname } from "next/navigation";
import { Button } from "@/components/ui/button";
import { Avatar, AvatarFallback } from "@/components/ui/avatar";
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuLabel,
  DropdownMenuSeparator,
  DropdownMenuTrigger,
} from "@/components/ui/dropdown-menu";
import { Badge } from "@/components/ui/badge";
import { CommandSearch } from "@/components/command-search";
import { NotificationDropdown } from "@/components/notification-dropdown";
import { useSystemHealth } from "@/lib/hooks";
import { useAppStore } from "@/lib/store";
import { logout } from "@/lib/auth";

function formatUptime(seconds: number | undefined): string {
  if (!seconds || seconds <= 0) return "--";
  const days = Math.floor(seconds / 86_400);
  const hours = Math.floor((seconds % 86_400) / 3_600);
  const minutes = Math.floor((seconds % 3_600) / 60);
  if (days > 0) return `${days}d ${hours}h`;
  if (hours > 0) return `${hours}h ${minutes}m`;
  return `${minutes}m`;
}

function ReadOnlyRouteLabel({ isLegalPath }: { isLegalPath: boolean }) {
  return (
    <div className="flex min-h-10 min-w-0 items-center rounded-md border border-border bg-muted/30 px-3">
      <div className="min-w-0">
        <p className="truncate text-sm font-medium">
          {isLegalPath ? "Fortress Legal" : "Command Dashboard"}
        </p>
        <p className="truncate text-xs text-muted-foreground">
          Read-only staging certification surface
        </p>
      </div>
    </div>
  );
}

function OpsHealthBadges() {
  const { data: health } = useSystemHealth();
  const databaseOnline = useMemo(() => {
    const postgresTables = Object.keys(health?.databases?.postgres ?? {});
    return postgresTables.length > 0;
  }, [health?.databases?.postgres]);
  const qdrantHealthy = useMemo(() => {
    const entries = Object.values(health?.databases?.qdrant ?? {});
    return entries.length > 0 && entries.every((entry) => entry.status === "green");
  }, [health?.databases?.qdrant]);
  const dbTone = databaseOnline ? "border-emerald-500/30 bg-emerald-500/10 text-emerald-700 dark:text-emerald-200" : "border-amber-500/30 bg-amber-500/10 text-amber-700 dark:text-amber-200";
  const securityTone = "border-cyan-500/30 bg-cyan-500/10 text-cyan-700 dark:text-cyan-200";
  const uptime = formatUptime(health?.uptime_seconds);

  return (
    <>
      <Badge variant="outline" className={dbTone}>
        DB {databaseOnline ? "online" : "degraded"}
      </Badge>
      <Badge variant="outline" className={securityTone}>
        Security RS256 + bcrypt
      </Badge>
      <Badge variant="outline" className="border-zinc-500/30 bg-zinc-500/10 text-zinc-700 dark:text-zinc-200">
        Uptime {uptime}
      </Badge>
      {health?.status ? (
        <Badge
          variant="outline"
          className={
            health.status === "healthy"
              ? "border-emerald-500/30 bg-emerald-500/10 text-emerald-700 dark:text-emerald-200"
              : "border-amber-500/30 bg-amber-500/10 text-amber-700 dark:text-amber-200"
          }
        >
          OPS {health.status}
        </Badge>
      ) : null}
      {health?.databases?.qdrant ? (
        <Badge
          variant="outline"
          className={
            qdrantHealthy
              ? "border-emerald-500/30 bg-emerald-500/10 text-emerald-700 dark:text-emerald-200"
              : "border-amber-500/30 bg-amber-500/10 text-amber-700 dark:text-amber-200"
          }
        >
          Vector {qdrantHealthy ? "green" : "watch"}
        </Badge>
      ) : null}
    </>
  );
}

export function Topbar() {
  const pathname = usePathname();
  const user = useAppStore((s) => s.user);
  const isLegalPath = pathname.startsWith("/legal");
  const isReadOnlyCertificationPath = isLegalPath || pathname === "/dashboard";
  const initials = user
    ? `${user.first_name?.[0] ?? ""}${user.last_name?.[0] ?? ""}`.toUpperCase()
    : "LK";
  const displayName = user ? `${user.first_name} ${user.last_name}` : "Lissa Knight";
  const displayRole = user?.role ?? "Admin";

  return (
    <header className="flex min-h-16 flex-wrap items-center justify-between gap-3 border-b bg-card px-6 py-3">
      <div className="flex min-w-0 flex-1 items-center gap-3">
        {isReadOnlyCertificationPath ? (
          <ReadOnlyRouteLabel isLegalPath={isLegalPath} />
        ) : (
          <CommandSearch />
        )}
        <div className="hidden items-center gap-2 xl:flex">
          {isReadOnlyCertificationPath ? (
            <Badge variant="outline" className="border-cyan-500/30 bg-cyan-500/10 text-cyan-700 dark:text-cyan-200">
              Read-only legal audit
            </Badge>
          ) : (
            <OpsHealthBadges />
          )}
        </div>
      </div>

      <div className="flex items-center gap-3">
        {isReadOnlyCertificationPath ? (
          <Button
            variant="ghost"
            size="icon"
            disabled
            aria-label="Notifications paused on read-only legal routes"
          >
            <Bell className="h-5 w-5" />
          </Button>
        ) : (
          <NotificationDropdown />
        )}

        <DropdownMenu>
          <DropdownMenuTrigger asChild>
            <Button variant="ghost" className="flex items-center gap-3 px-2">
              <Avatar className="h-8 w-8">
                <AvatarFallback className="text-xs">{initials}</AvatarFallback>
              </Avatar>
              <div className="hidden md:block text-left">
                <p className="text-sm font-medium leading-none">{displayName}</p>
                <p className="text-xs text-muted-foreground">{displayRole}</p>
              </div>
            </Button>
          </DropdownMenuTrigger>
          <DropdownMenuContent align="end" className="w-48">
            <DropdownMenuLabel>{displayName}</DropdownMenuLabel>
            <DropdownMenuSeparator />
            <DropdownMenuItem
              onClick={() => logout()}
              className="cursor-pointer text-destructive focus:text-destructive"
            >
              <LogOut className="mr-2 h-4 w-4" />
              Sign out
            </DropdownMenuItem>
          </DropdownMenuContent>
        </DropdownMenu>
      </div>
    </header>
  );
}
