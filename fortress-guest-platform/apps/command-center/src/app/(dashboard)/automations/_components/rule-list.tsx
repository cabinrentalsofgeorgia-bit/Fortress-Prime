"use client";

import { useState } from "react";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Badge } from "@/components/ui/badge";
import { Switch } from "@/components/ui/switch";
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@/components/ui/table";
import { Pencil, Trash2, Search } from "lucide-react";
import { useAutomationRules, useDeleteRule, useUpdateRule } from "@/lib/hooks";
import type { AutomationRule } from "@/lib/types";

interface RuleListProps {
  onEdit: (rule: AutomationRule) => void;
}

const entityColor: Record<string, string> = {
  reservation: "bg-blue-500/15 text-blue-400",
  work_order: "bg-amber-500/15 text-amber-400",
  guest: "bg-emerald-500/15 text-emerald-400",
  message: "bg-violet-500/15 text-violet-400",
};

export function RuleList({ onEdit }: RuleListProps) {
  const [search, setSearch] = useState("");
  const { data: rules = [], isLoading } = useAutomationRules();
  const deleteRule = useDeleteRule();
  const updateRule = useUpdateRule();

  const filtered = rules.filter((r) =>
    r.name.toLowerCase().includes(search.toLowerCase()),
  );

  function handleToggle(rule: AutomationRule) {
    updateRule.mutate({
      id: rule.id,
      data: { is_active: !rule.is_active },
    });
  }

  return (
    <div className="space-y-3">
      <div className="relative">
        <Search className="absolute left-2.5 top-2.5 h-4 w-4 text-muted-foreground" />
        <Input
          placeholder="Search rules..."
          value={search}
          onChange={(e) => setSearch(e.target.value)}
          className="pl-8"
        />
      </div>

      <div className="rounded-md border">
        <Table>
          <TableHeader>
            <TableRow>
              <TableHead>Name</TableHead>
              <TableHead>Entity</TableHead>
              <TableHead>Trigger</TableHead>
              <TableHead>Action</TableHead>
              <TableHead className="w-16 text-center">Active</TableHead>
              <TableHead className="w-20" />
            </TableRow>
          </TableHeader>
          <TableBody>
            {isLoading && (
              <TableRow>
                <TableCell colSpan={6} className="text-center text-muted-foreground py-8">
                  Loading rules...
                </TableCell>
              </TableRow>
            )}
            {!isLoading && filtered.length === 0 && (
              <TableRow>
                <TableCell colSpan={6} className="text-center text-muted-foreground py-8">
                  {search ? "No rules match your search" : "No automation rules yet"}
                </TableCell>
              </TableRow>
            )}
            {filtered.map((rule) => (
              <TableRow key={rule.id}>
                <TableCell className="font-medium">{rule.name}</TableCell>
                <TableCell>
                  <Badge
                    variant="secondary"
                    className={entityColor[rule.target_entity] ?? ""}
                  >
                    {rule.target_entity}
                  </Badge>
                </TableCell>
                <TableCell className="text-sm text-muted-foreground">
                  {rule.trigger_event}
                </TableCell>
                <TableCell className="text-sm text-muted-foreground">
                  {rule.action_type.replaceAll("_", " ")}
                </TableCell>
                <TableCell className="text-center">
                  <Switch
                    checked={rule.is_active}
                    onCheckedChange={() => handleToggle(rule)}
                    size="sm"
                  />
                </TableCell>
                <TableCell>
                  <div className="flex items-center gap-1">
                    <Button
                      variant="ghost"
                      size="icon"
                      className="h-7 w-7"
                      onClick={() => onEdit(rule)}
                    >
                      <Pencil className="h-3.5 w-3.5" />
                    </Button>
                    <Button
                      variant="ghost"
                      size="icon"
                      className="h-7 w-7 text-muted-foreground hover:text-destructive"
                      onClick={() => deleteRule.mutate(rule.id)}
                      disabled={deleteRule.isPending}
                    >
                      <Trash2 className="h-3.5 w-3.5" />
                    </Button>
                  </div>
                </TableCell>
              </TableRow>
            ))}
          </TableBody>
        </Table>
      </div>
    </div>
  );
}
