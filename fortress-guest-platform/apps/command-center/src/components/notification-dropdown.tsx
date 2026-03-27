"use client";

import { Bell, MessageSquare, Bot, AlertTriangle } from "lucide-react";
import { Button } from "@/components/ui/button";
import { Badge } from "@/components/ui/badge";
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuLabel,
  DropdownMenuSeparator,
  DropdownMenuTrigger,
} from "@/components/ui/dropdown-menu";
import { ScrollArea } from "@/components/ui/scroll-area";
import { useDashboardStats, useReviewQueue } from "@/lib/hooks";
import { useRouter } from "next/navigation";

export function NotificationDropdown() {
  const { data: stats } = useDashboardStats();
  const { data: queue } = useReviewQueue();
  const router = useRouter();

  const totalBadge =
    (stats?.unread_messages ?? 0) +
    (stats?.open_work_orders ?? 0) +
    (queue?.length ?? 0);

  return (
    <DropdownMenu>
      <DropdownMenuTrigger asChild>
        <Button variant="ghost" size="icon" className="relative">
          <Bell className="h-5 w-5" />
          {totalBadge > 0 && (
            <Badge
              variant="destructive"
              className="absolute -right-1 -top-1 h-5 min-w-5 rounded-full p-0 text-[10px] flex items-center justify-center"
            >
              {totalBadge > 99 ? "99+" : totalBadge}
            </Badge>
          )}
        </Button>
      </DropdownMenuTrigger>
      <DropdownMenuContent align="end" className="w-80">
        <DropdownMenuLabel>Notifications</DropdownMenuLabel>
        <DropdownMenuSeparator />
        <ScrollArea className="h-72">
          {(stats?.unread_messages ?? 0) > 0 && (
            <DropdownMenuItem onClick={() => router.push("/messages")} className="cursor-pointer">
              <div className="flex items-start gap-3 py-1">
                <MessageSquare className="h-5 w-5 text-violet-500 mt-0.5 shrink-0" />
                <div>
                  <p className="text-sm font-medium">
                    {stats!.unread_messages} unread message{stats!.unread_messages !== 1 ? "s" : ""}
                  </p>
                  <p className="text-xs text-muted-foreground">Tap to view inbox</p>
                </div>
              </div>
            </DropdownMenuItem>
          )}

          {(queue?.length ?? 0) > 0 && (
            <DropdownMenuItem onClick={() => router.push("/ai-engine")} className="cursor-pointer">
              <div className="flex items-start gap-3 py-1">
                <Bot className="h-5 w-5 text-amber-500 mt-0.5 shrink-0" />
                <div>
                  <p className="text-sm font-medium">
                    {queue!.length} AI response{queue!.length !== 1 ? "s" : ""} pending review
                  </p>
                  <p className="text-xs text-muted-foreground">Approve or edit AI drafts</p>
                </div>
              </div>
            </DropdownMenuItem>
          )}

          {(stats?.open_work_orders ?? 0) > 0 && (
            <DropdownMenuItem onClick={() => router.push("/work-orders")} className="cursor-pointer">
              <div className="flex items-start gap-3 py-1">
                <AlertTriangle className="h-5 w-5 text-orange-500 mt-0.5 shrink-0" />
                <div>
                  <p className="text-sm font-medium">
                    {stats!.open_work_orders} open work order{stats!.open_work_orders !== 1 ? "s" : ""}
                  </p>
                  <p className="text-xs text-muted-foreground">Maintenance needs attention</p>
                </div>
              </div>
            </DropdownMenuItem>
          )}

          {totalBadge === 0 && (
            <div className="p-6 text-center text-sm text-muted-foreground">
              All caught up — no pending items.
            </div>
          )}
        </ScrollArea>
      </DropdownMenuContent>
    </DropdownMenu>
  );
}
