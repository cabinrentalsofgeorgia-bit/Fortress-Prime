"use client";

import { Button } from "@/components/ui/button";
import { Card, CardContent } from "@/components/ui/card";
import type { EmailIntakeQuarantineItem } from "@/lib/types";

type Props = {
  items: EmailIntakeQuarantineItem[];
  isLoading: boolean;
  onRelease: (item: EmailIntakeQuarantineItem) => void;
  onDelete: (item: EmailIntakeQuarantineItem) => void;
};

export function QuarantineTab({ items, isLoading, onRelease, onDelete }: Props) {
  if (isLoading) return <div className="text-sm text-muted-foreground">Loading quarantine...</div>;
  if (items.length === 0) {
    return (
      <div className="rounded-md border p-8 text-center text-sm text-muted-foreground">
        Quarantine is clear.
      </div>
    );
  }

  return (
    <div className="space-y-3">
      {items.map((item) => (
        <Card key={item.id}>
          <CardContent className="p-4 space-y-2">
            <div className="flex items-center justify-between text-xs text-muted-foreground">
              <span>{item.sender}</span>
              <span>{new Date(item.created_at).toLocaleString()}</span>
            </div>
            <p className="font-medium">{item.subject}</p>
            <p className="text-xs text-muted-foreground">
              Blocked by: {item.rule_reason || item.rule_type || "unknown"}
            </p>
            <p className="text-sm whitespace-pre-wrap">{item.content_preview}</p>
            <div className="flex items-center justify-end gap-2">
              <Button variant="outline" size="sm" onClick={() => onRelease(item)}>
                Release & Ingest
              </Button>
              <Button variant="destructive" size="sm" onClick={() => onDelete(item)}>
                Permanently Delete
              </Button>
            </div>
          </CardContent>
        </Card>
      ))}
    </div>
  );
}

