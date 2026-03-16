"use client";

import { useEffect, useState, useCallback } from "react";
import { useRouter } from "next/navigation";
import {
  CommandDialog,
  CommandEmpty,
  CommandGroup,
  CommandInput,
  CommandItem,
  CommandList,
  CommandSeparator,
} from "@/components/ui/command";
import {
  CalendarDays,
  Home,
  MessageSquare,
  Users,
  Wrench,
  BarChart3,
  Bot,
  Settings,
  Search,
  KeyRound,
  ClipboardList,
  Shield,
  BookOpen,
} from "lucide-react";
import { useProperties, useGuests } from "@/lib/hooks";
import type { Guest } from "@/lib/types";

const navItems = [
  { label: "Command Center", href: "/", icon: Home },
  { label: "Reservations", href: "/reservations", icon: CalendarDays },
  { label: "Properties", href: "/properties", icon: Home },
  { label: "Messages", href: "/messages", icon: MessageSquare },
  { label: "Guests", href: "/guests", icon: Users },
  { label: "Work Orders", href: "/work-orders", icon: Wrench },
  { label: "Analytics", href: "/analytics", icon: BarChart3 },
  { label: "AI Engine", href: "/ai-engine", icon: Bot },
  { label: "Housekeeping", href: "/housekeeping", icon: ClipboardList },
  { label: "Damage Claims", href: "/damage-claims", icon: Shield },
  { label: "Guestbooks", href: "/guestbooks", icon: BookOpen },
  { label: "Owner Portal", href: "/owner", icon: KeyRound },
  { label: "Settings", href: "/settings", icon: Settings },
];

function getGuestDisplayName(guest: Guest): string {
  const fullName = guest.full_name?.trim();
  if (fullName) return fullName;
  const combined = `${guest.first_name ?? ""} ${guest.last_name ?? ""}`.trim();
  return combined || "Guest";
}

export function CommandSearch() {
  const [open, setOpen] = useState(false);
  const router = useRouter();
  const { data: properties } = useProperties();
  const { data: guests } = useGuests();

  useEffect(() => {
    const down = (e: KeyboardEvent) => {
      if (e.key === "k" && (e.metaKey || e.ctrlKey)) {
        e.preventDefault();
        setOpen((o) => !o);
      }
    };
    document.addEventListener("keydown", down);
    return () => document.removeEventListener("keydown", down);
  }, []);

  const go = useCallback(
    (href: string) => {
      setOpen(false);
      router.push(href);
    },
    [router],
  );

  return (
    <>
      <button
        onClick={() => setOpen(true)}
        className="flex items-center gap-2 rounded-md border bg-background px-3 py-2 text-sm text-muted-foreground hover:bg-accent transition-colors w-80"
      >
        <Search className="h-4 w-4" />
        <span className="flex-1 text-left">Search...</span>
        <kbd className="pointer-events-none hidden h-5 select-none items-center gap-1 rounded border bg-muted px-1.5 font-mono text-[10px] font-medium text-muted-foreground sm:flex">
          <span className="text-xs">⌘</span>K
        </kbd>
      </button>

      <CommandDialog open={open} onOpenChange={setOpen}>
        <CommandInput placeholder="Search properties, guests, pages..." />
        <CommandList>
          <CommandEmpty>No results found.</CommandEmpty>

          <CommandGroup heading="Pages">
            {navItems.map((item) => (
              <CommandItem key={item.href} onSelect={() => go(item.href)}>
                <item.icon className="mr-2 h-4 w-4" />
                {item.label}
              </CommandItem>
            ))}
          </CommandGroup>

          {Array.isArray(properties) && properties.length > 0 && (
            <>
              <CommandSeparator />
              <CommandGroup heading="Properties">
                {(properties ?? []).slice(0, 8).map((p) => (
                  <CommandItem key={p.id} onSelect={() => go(`/properties/${p.id}`)}>
                    <Home className="mr-2 h-4 w-4" />
                    {p.name}
                    <span className="ml-auto text-xs text-muted-foreground">
                      {p.bedrooms}BR · Sleeps {p.max_guests}
                    </span>
                  </CommandItem>
                ))}
              </CommandGroup>
            </>
          )}

          {Array.isArray(guests) && guests.length > 0 && (
            <>
              <CommandSeparator />
              <CommandGroup heading="Guests">
                {(guests ?? []).slice(0, 6).map((g) => (
                  <CommandItem key={g.id} onSelect={() => go(`/guests/${g.id}`)}>
                    <Users className="mr-2 h-4 w-4" />
                    {getGuestDisplayName(g)}
                    {g.email && (
                      <span className="ml-auto text-xs text-muted-foreground">
                        {g.email}
                      </span>
                    )}
                  </CommandItem>
                ))}
              </CommandGroup>
            </>
          )}
        </CommandList>
      </CommandDialog>
    </>
  );
}
