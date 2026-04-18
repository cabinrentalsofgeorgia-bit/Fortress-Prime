import Link from "next/link";

import type {
  FooterColumn,
  NavItem,
  StorefrontContactPayload,
} from "@/lib/storefront-homepage-content";

interface StorefrontFooterProps {
  columns: FooterColumn[];
  socialLinks: NavItem[];
  contact: StorefrontContactPayload;
}

function FooterAnchor({ item }: { item: NavItem }) {
  if (item.external) {
    return (
      <a href={item.href} target="_blank" rel="noreferrer" className="transition hover:text-white">
        {item.label}
      </a>
    );
  }

  return (
    <Link href={item.href} className="transition hover:text-white">
      {item.label}
    </Link>
  );
}

export function StorefrontFooter({
  columns,
  socialLinks,
  contact,
}: StorefrontFooterProps) {
  return (
    <footer className="bg-stone-950 text-stone-200">
      <div className="mx-auto grid max-w-7xl gap-10 px-4 py-14 sm:px-6 lg:grid-cols-[1.2fr_repeat(3,1fr)] lg:px-8">
        <div className="space-y-4">
          <p className="text-xs font-semibold uppercase tracking-[0.3em] text-amber-200">
            Cabin Rentals of Georgia
          </p>
          <h2 className="text-2xl font-semibold tracking-tight text-white">
            {contact.businessName}
          </h2>
          <div className="space-y-1 text-sm leading-7">
            <a href={contact.phoneHref} className="block transition hover:text-white">
              {contact.phoneLabel}
            </a>
            {contact.addressLines.map((line) => (
              <p key={line}>{line}</p>
            ))}
          </div>
          <div className="flex flex-wrap gap-4 pt-2 text-sm">
            {socialLinks.map((item) => (
              <FooterAnchor key={item.label} item={item} />
            ))}
          </div>
        </div>

        {columns.map((column) => (
          <div key={column.title} className="space-y-4">
            <h3 className="text-sm font-semibold uppercase tracking-[0.2em] text-white">
              {column.title}
            </h3>
            <div className="space-y-2 text-sm text-stone-300">
              {column.items.map((item) => (
                <div key={item.label}>
                  <FooterAnchor item={item} />
                </div>
              ))}
            </div>
          </div>
        ))}
      </div>
    </footer>
  );
}
