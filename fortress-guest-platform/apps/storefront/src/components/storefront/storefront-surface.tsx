import type { ReactNode } from "react";

import { SovereignNudge } from "@/components/storefront/sovereign-nudge";

interface StorefrontSurfaceProps {
  children: ReactNode;
}

export function StorefrontSurface({ children }: StorefrontSurfaceProps) {
  return (
    <div
      className="min-h-screen bg-white text-[#533e27]"
      style={{ colorScheme: "light", backgroundColor: "#ffffff", color: "#533e27" }}
    >
      <main>{children}</main>
      <SovereignNudge />
    </div>
  );
}
