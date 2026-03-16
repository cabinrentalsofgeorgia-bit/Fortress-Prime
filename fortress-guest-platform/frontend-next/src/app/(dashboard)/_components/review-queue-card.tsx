"use client";

import {
  Card,
  CardContent,
  CardHeader,
  CardTitle,
} from "@/components/ui/card";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Bot, Check, X } from "lucide-react";
import { useReviewAction } from "@/lib/hooks";
import type { ReviewQueueItem } from "@/lib/types";

interface Props {
  items?: ReviewQueueItem[];
}

export function ReviewQueueCard({ items }: Props) {
  const pending = (items ?? []).filter((i) => i.status === "pending");
  const reviewAction = useReviewAction();

  return (
    <Card>
      <CardHeader className="flex flex-row items-center justify-between">
        <CardTitle className="flex items-center gap-2 text-base">
          <Bot className="h-5 w-5 text-violet-500" />
          AI Review Queue
        </CardTitle>
        <Badge variant={pending.length > 0 ? "destructive" : "secondary"}>
          {pending.length} pending
        </Badge>
      </CardHeader>
      <CardContent>
        {pending.length === 0 ? (
          <p className="text-sm text-muted-foreground py-6 text-center">
            All caught up
          </p>
        ) : (
          <div className="space-y-3">
            {pending.slice(0, 5).map((item) => (
              <div key={item.id} className="rounded-lg border p-3 space-y-2">
                <div className="flex items-start justify-between">
                  <div>
                    <p className="text-xs font-medium text-muted-foreground">
                      Guest message:
                    </p>
                    <p className="text-sm">{item.original_message}</p>
                  </div>
                  <Badge variant="outline" className="text-[10px] shrink-0">
                    {Math.round((item.ai_confidence ?? 0) * 100)}% conf
                  </Badge>
                </div>
                <div>
                  <p className="text-xs font-medium text-muted-foreground">
                    AI draft:
                  </p>
                  <p className="text-sm text-muted-foreground">
                    {(item.ai_draft_response ?? "").slice(0, 120)}
                    {(item.ai_draft_response ?? "").length > 120 ? "..." : ""}
                  </p>
                </div>
                <div className="flex gap-2 pt-1">
                  <Button
                    size="sm"
                    variant="default"
                    className="h-7 text-xs"
                    onClick={() =>
                      reviewAction.mutate({ id: item.id, action: "approve" })
                    }
                  >
                    <Check className="h-3 w-3 mr-1" />
                    Approve
                  </Button>
                  <Button
                    size="sm"
                    variant="outline"
                    className="h-7 text-xs"
                    onClick={() =>
                      reviewAction.mutate({ id: item.id, action: "reject" })
                    }
                  >
                    <X className="h-3 w-3 mr-1" />
                    Reject
                  </Button>
                </div>
              </div>
            ))}
          </div>
        )}
      </CardContent>
    </Card>
  );
}
