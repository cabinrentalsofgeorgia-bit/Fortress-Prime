"use client";

import Link from "next/link";
import { Menu, Phone, X } from "lucide-react";
import { useState } from "react";

import type {
  NavGroup,
  NavItem,
} from "@/lib/storefront-homepage-content";

interface StorefrontNavigationProps {
  groups: NavGroup[];
  utilityLinks: NavItem[];
  phoneLabel: string;
  phoneHref: string;
}

function NavAnchor({ item, className }: { item: NavItem; className?: string }) {
  if (item.external) {
    return (
      <a
        href={item.href}
        target="_blank"
        rel="noreferrer"
        className={className}
      >
        {item.label}
      </a>
    );
  }

  return (
    <Link href={item.href} className={className}>
      {item.label}
    </Link>
  );
}

export function StorefrontNavigation({
  groups,
  utilityLinks,
  phoneLabel,
  phoneHref,
}: StorefrontNavigationProps) {
  const [mobileOpen, setMobileOpen] = useState(false);

  return (
    <header className="sticky top-0 z-50 border-b border-stone-200/80 bg-white/95 text-stone-900 backdrop-blur">
      <div className="border-b border-stone-200 bg-stone-900 text-stone-100">
        <div className="mx-auto flex max-w-7xl flex-wrap items-center justify-between gap-3 px-4 py-2 text-xs uppercase tracking-[0.18em] sm:px-6 lg:px-8">
          <div className="flex flex-wrap items-center gap-4">
            {utilityLinks.map((item) => (
              <NavAnchor
                key={item.label}
                item={item}
                className="transition hover:text-amber-200"
              />
            ))}
          </div>
          <a
            href={phoneHref}
            className="inline-flex items-center gap-2 font-semibold tracking-[0.22em] transition hover:text-amber-200"
          >
            <Phone className="h-3.5 w-3.5" />
            {phoneLabel}
          </a>
        </div>
      </div>

      <div className="mx-auto max-w-7xl px-4 sm:px-6 lg:px-8">
        <div className="flex min-h-20 items-center justify-between gap-6 py-4">
          <div className="min-w-0">
            <Link href="/" className="block">
              <span className="block text-xs font-semibold uppercase tracking-[0.3em] text-stone-500">
                Cabin Rentals of Georgia
              </span>
              <span className="block truncate pt-1 text-lg font-semibold tracking-tight text-stone-900 sm:text-xl">
                Blue Ridge Luxury Cabin Collection
              </span>
            </Link>
          </div>

          <nav className="hidden items-center gap-2 lg:flex">
            {groups.map((group) => (
              <div key={group.label} className="group relative">
                <Link
                  href={group.href}
                  className="inline-flex items-center rounded-full px-4 py-2 text-sm font-semibold text-stone-700 transition hover:bg-amber-50 hover:text-stone-950"
                >
                  {group.label}
                </Link>
                {group.items.length > 0 ? (
                  <div className="invisible absolute left-0 top-full mt-3 w-80 translate-y-2 rounded-3xl border border-stone-200 bg-white p-5 opacity-0 shadow-2xl shadow-stone-900/10 transition duration-200 group-hover:visible group-hover:translate-y-0 group-hover:opacity-100">
                    <div className="space-y-2">
                      {group.items.map((item) => (
                        <NavAnchor
                          key={item.label}
                          item={item}
                          className="block rounded-2xl px-3 py-3 text-sm text-stone-700 transition hover:bg-stone-50 hover:text-stone-950"
                        />
                      ))}
                    </div>
                  </div>
                ) : null}
              </div>
            ))}
          </nav>

          <button
            type="button"
            className="inline-flex h-11 w-11 items-center justify-center rounded-full border border-stone-300 text-stone-700 transition hover:bg-stone-50 lg:hidden"
            onClick={() => setMobileOpen((current) => !current)}
            aria-expanded={mobileOpen}
            aria-label={mobileOpen ? "Close navigation" : "Open navigation"}
          >
            {mobileOpen ? <X className="h-5 w-5" /> : <Menu className="h-5 w-5" />}
          </button>
        </div>

        {mobileOpen ? (
          <div className="border-t border-stone-200 py-4 lg:hidden">
            <div className="space-y-5">
              {groups.map((group) => (
                <div key={group.label} className="space-y-2">
                  <Link
                    href={group.href}
                    className="block text-sm font-semibold uppercase tracking-[0.18em] text-stone-900"
                    onClick={() => setMobileOpen(false)}
                  >
                    {group.label}
                  </Link>
                  <div className="grid gap-2">
                    {group.items.map((item) => (
                      <NavAnchor
                        key={item.label}
                        item={item}
                        className="rounded-2xl bg-stone-50 px-3 py-3 text-sm text-stone-700"
                      />
                    ))}
                  </div>
                </div>
              ))}
            </div>
          </div>
        ) : null}
      </div>
    </header>
  );
}
