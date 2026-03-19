"use client";

import { useState } from "react";
import { useRouter } from "next/navigation";
import { LogOut, Building, ShieldCheck } from "lucide-react";
import { Button } from "@/components/ui/button";
import { ErrorBoundary } from "@/components/error-boundary";

interface OwnerProfile {
  owner_id: string;
  email: string;
  properties: Array<{ unit_id: string; name: string }>;
}

export default function OwnerLayout({
  children,
}: {
  children: React.ReactNode;
}) {
  const router = useRouter();
  const [ownerProfile] = useState<OwnerProfile | null>(() => {
    if (typeof window === "undefined") {
      return null;
    }
    const raw = localStorage.getItem("fgp_owner_profile");
    if (!raw) {
      return null;
    }
    try {
      return JSON.parse(raw) as OwnerProfile;
    } catch {
      return null;
    }
  });

  const handleSignOut = async () => {
    try {
      await fetch("/api/auth/owner/logout", { method: "POST" });
    } catch {
      /* best-effort -- redirect regardless */
    }
    localStorage.removeItem("fgp_owner_profile");
    router.push("/owner-login");
  };

  return (
    <div className="min-h-screen bg-background text-foreground flex flex-col">
      <header className="sticky top-0 z-50 border-b border-border bg-background/95 backdrop-blur supports-[backdrop-filter]:bg-background/60">
        <div className="flex h-14 items-center justify-between px-4 md:px-6 max-w-7xl mx-auto w-full">
          <div className="flex items-center gap-3">
            <div className="flex h-8 w-8 items-center justify-center rounded-lg bg-primary">
              <ShieldCheck className="h-4 w-4 text-primary-foreground" />
            </div>
            <span className="font-semibold tracking-tight">Owner Portal</span>
            {ownerProfile && (
              <span className="hidden md:inline-flex items-center gap-1.5 text-sm text-muted-foreground">
                <Building className="h-3.5 w-3.5" />
                {ownerProfile.properties?.length ?? 0} properties
              </span>
            )}
          </div>
          <div className="flex items-center gap-3">
            {ownerProfile && (
              <span className="hidden sm:inline text-sm text-muted-foreground">
                {ownerProfile.email}
              </span>
            )}
            <Button
              variant="ghost"
              size="sm"
              onClick={handleSignOut}
              className="gap-1.5 text-muted-foreground hover:text-foreground"
            >
              <LogOut className="h-4 w-4" />
              <span className="hidden sm:inline">Sign Out</span>
            </Button>
          </div>
        </div>
      </header>

      <main className="flex-1 p-4 md:p-8 max-w-7xl mx-auto w-full">
        <ErrorBoundary>{children}</ErrorBoundary>
      </main>
    </div>
  );
}
