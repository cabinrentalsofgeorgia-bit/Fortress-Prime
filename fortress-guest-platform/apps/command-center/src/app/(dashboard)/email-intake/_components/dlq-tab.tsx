"use client";

import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardContent } from "@/components/ui/card";
import type { EmailIntakeDlqItem } from "@/lib/types";

type Props = {
  items: EmailIntakeDlqItem[];
  counts: Record<string, number>;
  isLoading: boolean;
  onRetry: (item: EmailIntakeDlqItem) => void;
  onDiscard: (item: EmailIntakeDlqItem) => void;
};

export function DlqTab({ items, counts, isLoading, onRetry, onDiscard }: Props) {
  if (isLoading) return <div className="text-sm text-muted-foreground">Loading dead letter queue...</div>;

  return (
    <div className="space-y-4">
      <div className="flex flex-wrap gap-2">
        {Object.entries(counts).map(([status, cnt]) => (
          <Badge key={status} variant="outline">
            {status}: {cnt}
          </Badge>
        ))}
      </div>

      {items.length === 0 ? (
        <div className="rounded-md border p-8 text-center text-sm text-muted-foreground">
          Dead letter queue is clear.
        </div>
      ) : (
        <div className="space-y-3">
          {items.map((item) => (
            <Card key={item.id}>
              <CardContent className="p-4 space-y-2">
                <div className="flex items-center gap-2 text-xs">
                  <Badge variant="outline">{item.status}</Badge>
                  <span className="text-muted-foreground">
                    retry {item.retry_count}/{item.max_retries}
                  </span>
                  <span className="ml-auto text-muted-foreground">
                    {new Date(item.created_at).toLocaleString()}
                  </span>
                </div>
                <p className="font-medium">{item.subject || "No subject"}</p>
                <p className="text-xs text-muted-foreground">{item.sender || "Unknown sender"}</p>
                <p className="rounded-md border bg-muted/40 p-2 text-xs">{item.error_message}</p>
                <div className="flex items-center justify-end gap-2">
                  <Button
                    size="sm"
                    variant="outline"
                    disabled={!["dead", "manual_review"].includes(item.status)}
                    onClick={() => onRetry(item)}
                  >
                    Retry
                  </Button>
                  <Button
                    size="sm"
                    variant="destructive"
                    disabled={item.status === "discarded"}
                    onClick={() => onDiscard(item)}
                  >
                    Discard
                  </Button>
                </div>
              </CardContent>
            </Card>
          ))}
        </div>
      )}
    </div>
  );
}

