import type { ReactNode } from "react";

import { StorefrontSurface } from "@/components/storefront/storefront-surface";

// The root layout forces html.dark and dark CSS custom properties so the
// command center renders correctly. Storefront pages are always light-themed,
// so we re-define every dark-mode CSS variable on this wrapper. All descendants
// inherit light values regardless of the html.dark class set at the root.
const LIGHT_VARS = {
  colorScheme: "light",
  "--background": "#ffffff",
  "--foreground": "#0f172a",
  "--card": "#ffffff",
  "--card-foreground": "#0f172a",
  "--popover": "#ffffff",
  "--popover-foreground": "#0f172a",
  "--primary": "#0f172a",
  "--primary-foreground": "#f8fafc",
  "--secondary": "#f1f5f9",
  "--secondary-foreground": "#0f172a",
  "--muted": "#f8fafc",
  "--muted-foreground": "#64748b",
  "--accent": "#f1f5f9",
  "--accent-foreground": "#0f172a",
  "--border": "rgb(226 232 240)",
  "--input": "rgb(226 232 240)",
  "--ring": "#0f172a",
} as React.CSSProperties;

export default async function StorefrontLayout({ children }: { children: ReactNode }) {
  return (
    <div style={LIGHT_VARS}>
      <StorefrontSurface>{children}</StorefrontSurface>
    </div>
  );
}
