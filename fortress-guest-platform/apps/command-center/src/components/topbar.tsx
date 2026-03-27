"use client";

import { LogOut } from "lucide-react";
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

export function Topbar() {
  const user = useAppStore((s) => s.user);
  const { data: health } = useSystemHealth();
  const initials = user
    ? `${user.first_name?.[0] ?? ""}${user.last_name?.[0] ?? ""}`.toUpperCase()
    : "LK";
  const displayName = user ? `${user.first_name} ${user.last_name}` : "Lissa Knight";
  const displayRole = user?.role ?? "Admin";
  const databaseOnline = health?.postgres_ok === true;
  const qdrantHealthy = health?.qdrant_reachable === true;
  const dbTone = databaseOnline ? "border-emerald-500/30 bg-emerald-500/10 text-emerald-700 dark:text-emerald-200" : "border-amber-500/30 bg-amber-500/10 text-amber-700 dark:text-amber-200";
  const securityTone = "border-cyan-500/30 bg-cyan-500/10 text-cyan-700 dark:text-cyan-200";
  const uptime = formatUptime(health?.uptime_seconds);

  return (
    <header className="flex min-h-16 flex-wrap items-center justify-between gap-3 border-b bg-card px-6 py-3">
      <div className="flex min-w-0 flex-1 items-center gap-3">
        <CommandSearch />
        <div className="hidden items-center gap-2 xl:flex">
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
                health.status === "NOMINAL"
                  ? "border-emerald-500/30 bg-emerald-500/10 text-emerald-700 dark:text-emerald-200"
                  : health.status === "WARNING"
                    ? "border-amber-500/30 bg-amber-500/10 text-amber-700 dark:text-amber-200"
                    : "border-rose-500/30 bg-rose-500/10 text-rose-700 dark:text-rose-200"
              }
            >
              OPS {health.status}
            </Badge>
          ) : null}
          {health ? (
            <Badge
              variant="outline"
              className={
                qdrantHealthy
                  ? "border-emerald-500/30 bg-emerald-500/10 text-emerald-700 dark:text-emerald-200"
                  : "border-amber-500/30 bg-amber-500/10 text-amber-700 dark:text-amber-200"
              }
            >
              Vector {qdrantHealthy ? "reachable" : "watch"}
            </Badge>
          ) : null}
        </div>
      </div>

      <div className="flex items-center gap-3">
        <NotificationDropdown />

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
