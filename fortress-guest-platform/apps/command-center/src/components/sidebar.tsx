"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";
import { cn } from "@/lib/utils";
import { useAppStore } from "@/lib/store";
import { Button } from "@/components/ui/button";
import { PanelLeftClose, PanelLeftOpen } from "lucide-react";
import {
  filterCommandHierarchy,
  getNavHref,
  getRoleBadgeLabel,
  getRoleFromUser,
  getTerminalLabel,
  isRouteItem,
} from "@/config/navigation";

function isActivePath(pathname: string, href?: string): boolean {
  if (!href) {
    return false;
  }

  return href === "/command" ? pathname === href : pathname.startsWith(href);
}

export function Sidebar() {
  const pathname = usePathname();
  const collapsed = useAppStore((s) => s.sidebarCollapsed);
  const toggle = useAppStore((s) => s.toggleSidebar);
  const user = useAppStore((s) => s.user);
  const currentRole = getRoleFromUser(user);
  const navSections = filterCommandHierarchy(currentRole)
    .map((section) => ({
      ...section,
      items: section.items.filter(isRouteItem),
    }))
    .filter((section) => section.items.length > 0);
  const displayName = user
    ? `${user.first_name} ${user.last_name}`.trim() || user.email
    : "System Operator";
  const displayRole = getRoleBadgeLabel(currentRole);

  return (
    <aside
      className={cn(
        "flex h-screen flex-col border-r border-neutral-800 bg-black text-neutral-300 transition-[width] duration-200",
        collapsed ? "w-20" : "w-72",
      )}
    >
      <div className="flex h-16 items-center justify-between border-b border-neutral-800 px-4">
        {collapsed ? (
          <Link
            href="/command"
            className="font-mono text-xs uppercase tracking-[0.35em] text-neutral-500"
          >
            FP
          </Link>
        ) : (
          <Link href="/command" className="space-y-1">
            <p className="font-mono text-[10px] uppercase tracking-[0.35em] text-neutral-600">
              Command Center
            </p>
            <p className="font-mono text-sm font-semibold uppercase tracking-[0.22em] text-white">
              Fortress Prime
            </p>
          </Link>
        )}
        <Button
          variant="ghost"
          size="icon"
          className="h-8 w-8 shrink-0 rounded-none border border-transparent text-neutral-500 hover:border-neutral-800 hover:bg-neutral-950 hover:text-neutral-200"
          onClick={toggle}
          aria-label={collapsed ? "Expand sidebar" : "Collapse sidebar"}
        >
          {collapsed ? (
            <PanelLeftOpen className="h-4 w-4" />
          ) : (
            <PanelLeftClose className="h-4 w-4" />
          )}
        </Button>
      </div>

      <nav className="flex-1 space-y-5 overflow-y-auto px-3 py-4">
        {navSections.map((section, sectionIndex) => (
          <div key={section.sector}>
            {collapsed ? (
              <div
                className={cn(
                  "mb-2 border-t border-neutral-900 pt-2 text-center font-mono text-[9px] tracking-[0.25em] text-neutral-700",
                  sectionIndex === 0 && "border-t-0 pt-0",
                )}
              >
                {String(sectionIndex + 1).padStart(2, "0")}
              </div>
            ) : (
              <p className="mb-2 px-2 font-mono text-[10px] font-semibold uppercase tracking-[0.32em] text-neutral-600">
                {section.sector}
              </p>
            )}
            <ul className="space-y-1">
              {section.items.map((item) => {
                const href = getNavHref(item);
                const active = isActivePath(pathname, href);
                const itemClasses = cn(
                  "group flex min-h-10 w-full items-center border-l px-3 py-2 text-left text-sm transition-colors",
                  item.isMono ? "font-mono text-[13px]" : "font-medium",
                  active
                    ? "border-white bg-neutral-950 text-white"
                    : "border-transparent text-neutral-400 hover:border-neutral-700 hover:bg-neutral-950 hover:text-neutral-200",
                  collapsed && "justify-center px-2",
                );
                const content = collapsed ? (
                  <span className="font-mono text-[10px] uppercase tracking-[0.24em]">
                    {getTerminalLabel(item.label)}
                  </span>
                ) : (
                  <>
                    <span
                      aria-hidden="true"
                      className={cn(
                        "mr-3 font-mono text-xs",
                        active ? "text-white" : "text-neutral-700 group-hover:text-neutral-500",
                      )}
                    >
                      {active ? ">" : "/"}
                    </span>
                    <span className="truncate">{item.label}</span>
                  </>
                );

                return (
                  <li key={`${section.sector}-${item.label}`}>
                    {isRouteItem(item) && href ? (
                      <Link href={href} className={itemClasses} title={collapsed ? item.label : undefined}>
                        {content}
                      </Link>
                    ) : (
                      <button
                        type="button"
                        className={cn(itemClasses, "cursor-not-allowed opacity-60")}
                        title={collapsed ? item.label : undefined}
                        disabled
                      >
                        {content}
                      </button>
                    )}
                  </li>
                );
              })}
            </ul>
          </div>
        ))}
      </nav>

      <div className="border-t border-neutral-800 px-4 py-4">
        {collapsed ? (
          <div className="space-y-1 text-center">
            <div className="font-mono text-[10px] uppercase tracking-[0.22em] text-neutral-400">
              {getTerminalLabel(displayRole)}
            </div>
            <div className="mx-auto h-2 w-2 rounded-full bg-emerald-500" />
          </div>
        ) : (
          <div className="space-y-1">
            <p className="font-mono text-[10px] uppercase tracking-[0.3em] text-neutral-600">
              Operator Status
            </p>
            <div className="flex items-center justify-between gap-3">
              <div className="min-w-0">
                <p className="truncate text-sm text-neutral-200">{displayName}</p>
                <p className="font-mono text-[11px] uppercase tracking-[0.22em] text-neutral-500">
                  {displayRole}
                </p>
              </div>
              <div className="h-2 w-2 shrink-0 rounded-full bg-emerald-500" />
            </div>
          </div>
        )}
      </div>
    </aside>
  );
}
