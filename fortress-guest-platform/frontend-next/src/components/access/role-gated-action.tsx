"use client";

import type { ReactNode } from "react";
import { Tooltip, TooltipContent, TooltipTrigger } from "@/components/ui/tooltip";

export function RoleGatedAction({
  allowed,
  reason = "Manager or admin role required.",
  children,
}: {
  allowed: boolean;
  reason?: string;
  children: ReactNode;
}) {
  if (allowed) return <>{children}</>;
  return (
    <Tooltip>
      <TooltipTrigger asChild>
        <span className="inline-flex cursor-not-allowed">{children}</span>
      </TooltipTrigger>
      <TooltipContent sideOffset={6}>{reason}</TooltipContent>
    </Tooltip>
  );
}
