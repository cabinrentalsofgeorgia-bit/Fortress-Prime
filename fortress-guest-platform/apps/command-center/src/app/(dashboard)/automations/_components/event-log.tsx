"use client";

import { Badge } from "@/components/ui/badge";
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@/components/ui/table";
import { useAutomationEvents, useAutomationRules } from "@/lib/hooks";
import { formatDistanceToNow } from "date-fns";

export function EventLog() {
  const { data: events = [], isLoading } = useAutomationEvents(30);
  const { data: rules = [] } = useAutomationRules();

  const ruleMap = new Map(rules.map((r) => [r.id, r.name]));

  return (
    <div className="rounded-md border">
      <Table>
        <TableHeader>
          <TableRow>
            <TableHead>Time</TableHead>
            <TableHead>Rule</TableHead>
            <TableHead>Entity</TableHead>
            <TableHead>Event</TableHead>
            <TableHead>Result</TableHead>
          </TableRow>
        </TableHeader>
        <TableBody>
          {isLoading && (
            <TableRow>
              <TableCell
                colSpan={5}
                className="text-center text-muted-foreground py-8"
              >
                Loading events...
              </TableCell>
            </TableRow>
          )}
          {!isLoading && events.length === 0 && (
            <TableRow>
              <TableCell
                colSpan={5}
                className="text-center text-muted-foreground py-8"
              >
                No automation events recorded yet
              </TableCell>
            </TableRow>
          )}
          {events.map((evt) => (
            <TableRow key={evt.id}>
              <TableCell className="text-xs text-muted-foreground whitespace-nowrap">
                {evt.created_at
                  ? formatDistanceToNow(new Date(evt.created_at), {
                      addSuffix: true,
                    })
                  : "—"}
              </TableCell>
              <TableCell className="text-sm">
                {evt.rule_id ? ruleMap.get(evt.rule_id) ?? "—" : "sync event"}
              </TableCell>
              <TableCell className="text-sm text-muted-foreground">
                {evt.entity_type}/{(evt.entity_id ?? "").slice(0, 8)}
              </TableCell>
              <TableCell className="text-sm text-muted-foreground">
                {evt.event_type}
              </TableCell>
              <TableCell>
                <ResultBadge result={evt.action_result} />
              </TableCell>
            </TableRow>
          ))}
        </TableBody>
      </Table>
    </div>
  );
}

function ResultBadge({ result }: { result?: string }) {
  if (!result) {
    return (
      <Badge variant="secondary" className="text-xs">
        logged
      </Badge>
    );
  }
  if (result === "success") {
    return (
      <Badge className="bg-emerald-500/15 text-emerald-400 text-xs">
        success
      </Badge>
    );
  }
  return (
    <Badge variant="destructive" className="text-xs">
      {result}
    </Badge>
  );
}
