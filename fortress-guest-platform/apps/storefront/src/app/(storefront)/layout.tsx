import type { ReactNode } from "react";

import { SovereignNudge } from "@/components/storefront/sovereign-nudge";

export default async function StorefrontLayout({ children }: { children: ReactNode }) {
  return (
    <main>
      {children}
      <SovereignNudge />
    </main>
  );
}
