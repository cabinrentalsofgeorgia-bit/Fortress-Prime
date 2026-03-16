"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";
import { cn } from "@/lib/utils";
import { useAppStore } from "@/lib/store";
import { Button } from "@/components/ui/button";
import {
  Activity,
  BarChart3,
  BedDouble,
  BookOpen,
  Bot,
  Brain,
  Calendar,
  Crosshair,
  CreditCard,
  FileText,
  Gavel,
  Home,
  Inbox,
  Mail,
  MessageSquare,
  LineChart,
  PanelLeftClose,
  PanelLeftOpen,
  Radio,
  Search,
  Server,
  Settings,
  Shield,
  Sparkles,
  Users,
  Wrench,
} from "lucide-react";

interface NavItem {
  label: string;
  href: string;
  icon: React.ComponentType<{ className?: string }>;
}

const NAV_SECTIONS: { heading: string; items: NavItem[] }[] = [
  {
    heading: "Overview",
    items: [
      { label: "Dashboard", href: "/", icon: Home },
      { label: "Analytics", href: "/analytics", icon: BarChart3 },
    ],
  },
  {
    heading: "Operations",
    items: [
      { label: "Reservations", href: "/reservations", icon: Calendar },
      { label: "Properties", href: "/properties", icon: BedDouble },
      { label: "Guests", href: "/guests", icon: Users },
      { label: "Messages", href: "/messages", icon: MessageSquare },
      { label: "Work Orders", href: "/work-orders", icon: Wrench },
      { label: "Housekeeping", href: "/housekeeping", icon: Activity },
      { label: "IoT Devices", href: "/iot", icon: Radio },
      { label: "Virtual Terminal", href: "/payments", icon: CreditCard },
    ],
  },
  {
    heading: "Intelligence",
    items: [
      { label: "AI Engine", href: "/ai-engine", icon: Brain },
      { label: "Intelligence", href: "/intelligence", icon: Sparkles },
      { label: "Market Canary", href: "/intelligence/market-shadow", icon: LineChart },
      { label: "Dispatch Radar", href: "/vrs/dispatch", icon: Radio },
      { label: "Reactivation Hunter", href: "/vrs/hunter", icon: Crosshair },
      { label: "Automations", href: "/automations", icon: Bot },
      { label: "Email Intake", href: "/email-intake", icon: Mail },
      { label: "E-Discovery Vault", href: "/vault", icon: Search },
    ],
  },
  {
    heading: "Management",
    items: [
      { label: "Damage Claims", href: "/damage-claims", icon: FileText },
      { label: "Agreements", href: "/agreements", icon: BookOpen },
      { label: "Guestbooks", href: "/guestbooks", icon: Inbox },
      { label: "Legal", href: "/legal", icon: Gavel },
      { label: "Owner Portal", href: "/owner", icon: Users },
    ],
  },
  {
    heading: "System",
    items: [
      { label: "System Health", href: "/system-health", icon: Server },
      { label: "VRS Dashboard", href: "/vrs", icon: Activity },
      { label: "Admin Ops", href: "/admin", icon: Shield },
      { label: "Settings", href: "/settings", icon: Settings },
    ],
  },
];

export function Sidebar() {
  const pathname = usePathname();
  const collapsed = useAppStore((s) => s.sidebarCollapsed);
  const toggle = useAppStore((s) => s.toggleSidebar);

  return (
    <aside
      className={cn(
        "flex flex-col border-r bg-card transition-all duration-200",
        collapsed ? "w-16" : "w-60",
      )}
    >
      {/* Brand */}
      <div className="flex h-16 items-center justify-between border-b px-4">
        {!collapsed && (
          <Link href="/" className="flex items-center gap-2">
            <div className="flex h-8 w-8 items-center justify-center rounded-lg bg-primary text-primary-foreground font-bold text-sm">
              F
            </div>
            <span className="font-semibold text-sm">Fortress</span>
          </Link>
        )}
        <Button
          variant="ghost"
          size="icon"
          className="h-8 w-8 shrink-0"
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

      {/* Navigation */}
      <nav className="flex-1 overflow-y-auto py-3 px-2 space-y-4">
        {NAV_SECTIONS.map((section) => (
          <div key={section.heading}>
            {!collapsed && (
              <p className="mb-1 px-3 text-[10px] font-semibold uppercase tracking-wider text-muted-foreground">
                {section.heading}
              </p>
            )}
            <ul className="space-y-0.5">
              {section.items.map((item) => {
                const active =
                  item.href === "/"
                    ? pathname === "/"
                    : pathname.startsWith(item.href);
                const linkClasses = cn(
                  "flex items-center gap-3 rounded-md px-3 py-2 text-sm transition-colors",
                  active
                    ? "bg-accent text-accent-foreground font-medium"
                    : "text-muted-foreground hover:bg-accent/50 hover:text-foreground",
                  collapsed && "justify-center px-0",
                );
                const linkContent = (
                  <>
                    <item.icon className="h-4 w-4 shrink-0" />
                    {!collapsed && <span className="truncate">{item.label}</span>}
                  </>
                );
                return (
                  <li key={item.href}>
                    <Link
                      href={item.href}
                      className={linkClasses}
                      title={collapsed ? item.label : undefined}
                    >
                      {linkContent}
                    </Link>
                  </li>
                );
              })}
            </ul>
          </div>
        ))}
      </nav>
    </aside>
  );
}
