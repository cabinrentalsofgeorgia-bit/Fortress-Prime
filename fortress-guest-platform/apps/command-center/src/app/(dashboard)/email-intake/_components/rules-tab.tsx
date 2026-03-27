"use client";

import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@/components/ui/table";
import { RulesCreateForms } from "./rules-create-forms";
import type { EmailIntakeRulesResponse } from "@/lib/types";

type Props = {
  data?: EmailIntakeRulesResponse;
  isLoading: boolean;
  onCreateRoutingRule: (payload: {
    rule_type: string;
    pattern: string;
    action: string;
    division?: string;
    reason?: string;
  }) => void;
  onCreateClassificationRule: (payload: {
    division: string;
    match_field: string;
    pattern: string;
    weight: number;
    notes?: string;
  }) => void;
  onCreateEscalationRule: (payload: {
    rule_name: string;
    trigger_type: string;
    match_field: string;
    pattern: string;
    priority: string;
    notes?: string;
  }) => void;
  onToggleRule: (type: "routing" | "classification" | "escalation", ruleId: number, isActive: boolean) => void;
};

export function RulesTab({
  data,
  isLoading,
  onCreateRoutingRule,
  onCreateClassificationRule,
  onCreateEscalationRule,
  onToggleRule,
}: Props) {
  if (isLoading) return <div className="text-sm text-muted-foreground">Loading rules...</div>;
  if (!data) return <div className="text-sm text-muted-foreground">No rule data.</div>;

  return (
    <div className="space-y-4">
      <RulesCreateForms
        onCreateRoutingRule={onCreateRoutingRule}
        onCreateClassificationRule={onCreateClassificationRule}
        onCreateEscalationRule={onCreateEscalationRule}
      />

      <section className="space-y-2">
        <h3 className="text-sm font-semibold">Routing Rules ({data.routing_rules.length})</h3>
        <Table>
          <TableHeader>
            <TableRow>
              <TableHead>ID</TableHead>
              <TableHead>Type</TableHead>
              <TableHead>Pattern</TableHead>
              <TableHead>Action</TableHead>
              <TableHead>Hits</TableHead>
              <TableHead>Active</TableHead>
              <TableHead />
            </TableRow>
          </TableHeader>
          <TableBody>
            {data.routing_rules.map((rule) => (
              <TableRow key={rule.id}>
                <TableCell>#{rule.id}</TableCell>
                <TableCell>{rule.rule_type}</TableCell>
                <TableCell className="max-w-[300px] truncate">{rule.pattern}</TableCell>
                <TableCell>{rule.action}</TableCell>
                <TableCell>{rule.hit_count}</TableCell>
                <TableCell>
                  <Badge variant={rule.is_active ? "default" : "outline"}>
                    {rule.is_active ? "Yes" : "No"}
                  </Badge>
                </TableCell>
                <TableCell>
                  <Button
                    size="sm"
                    variant="outline"
                    onClick={() => onToggleRule("routing", rule.id, !rule.is_active)}
                  >
                    Toggle
                  </Button>
                </TableCell>
              </TableRow>
            ))}
          </TableBody>
        </Table>
      </section>

      <section className="space-y-2">
        <h3 className="text-sm font-semibold">
          Classification Rules ({data.classification_rules.length})
        </h3>
        <Table>
          <TableHeader>
            <TableRow>
              <TableHead>ID</TableHead>
              <TableHead>Division</TableHead>
              <TableHead>Field</TableHead>
              <TableHead>Pattern</TableHead>
              <TableHead>Weight</TableHead>
              <TableHead>Hits</TableHead>
              <TableHead>Active</TableHead>
              <TableHead />
            </TableRow>
          </TableHeader>
          <TableBody>
            {data.classification_rules.map((rule) => (
              <TableRow key={rule.id}>
                <TableCell>#{rule.id}</TableCell>
                <TableCell>{rule.division}</TableCell>
                <TableCell>{rule.match_field}</TableCell>
                <TableCell className="max-w-[300px] truncate">{rule.pattern}</TableCell>
                <TableCell>{rule.weight}</TableCell>
                <TableCell>{rule.hit_count}</TableCell>
                <TableCell>
                  <Badge variant={rule.is_active ? "default" : "outline"}>
                    {rule.is_active ? "Yes" : "No"}
                  </Badge>
                </TableCell>
                <TableCell>
                  <Button
                    size="sm"
                    variant="outline"
                    onClick={() => onToggleRule("classification", rule.id, !rule.is_active)}
                  >
                    Toggle
                  </Button>
                </TableCell>
              </TableRow>
            ))}
          </TableBody>
        </Table>
      </section>

      <section className="space-y-2">
        <h3 className="text-sm font-semibold">Escalation Rules ({data.escalation_rules.length})</h3>
        <Table>
          <TableHeader>
            <TableRow>
              <TableHead>ID</TableHead>
              <TableHead>Name</TableHead>
              <TableHead>Trigger</TableHead>
              <TableHead>Field</TableHead>
              <TableHead>Pattern</TableHead>
              <TableHead>Priority</TableHead>
              <TableHead>Active</TableHead>
              <TableHead />
            </TableRow>
          </TableHeader>
          <TableBody>
            {data.escalation_rules.map((rule) => (
              <TableRow key={rule.id}>
                <TableCell>#{rule.id}</TableCell>
                <TableCell>{rule.rule_name}</TableCell>
                <TableCell>{rule.trigger_type}</TableCell>
                <TableCell>{rule.match_field}</TableCell>
                <TableCell className="max-w-[300px] truncate">{rule.pattern}</TableCell>
                <TableCell>{rule.priority}</TableCell>
                <TableCell>
                  <Badge variant={rule.is_active ? "default" : "outline"}>
                    {rule.is_active ? "Yes" : "No"}
                  </Badge>
                </TableCell>
                <TableCell>
                  <Button
                    size="sm"
                    variant="outline"
                    onClick={() => onToggleRule("escalation", rule.id, !rule.is_active)}
                  >
                    Toggle
                  </Button>
                </TableCell>
              </TableRow>
            ))}
          </TableBody>
        </Table>
      </section>
    </div>
  );
}

