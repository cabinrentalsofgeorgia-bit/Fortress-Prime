"use client";

import { useState } from "react";
import { Button } from "@/components/ui/button";
import {
  Card,
  CardContent,
  CardHeader,
  CardTitle,
} from "@/components/ui/card";
import { Tabs, TabsList, TabsTrigger, TabsContent } from "@/components/ui/tabs";
import { Separator } from "@/components/ui/separator";
import {
  Workflow,
  Zap,
  Activity,
  Layers,
  Plus,
  Mail,
} from "lucide-react";
import {
  useAutomationRules,
  useAutomationEvents,
  useQueueStatus,
  useTemplateLibrary,
} from "@/lib/hooks";
import type { AutomationRule } from "@/lib/types";
import { RuleList } from "./_components/rule-list";
import { AutomationForm } from "./_components/automation-form";
import { EventLog } from "./_components/event-log";
import { TemplateGrid } from "./_components/template-grid";

export default function AutomationsPage() {
  const { data: rules = [] } = useAutomationRules();
  const { data: events = [] } = useAutomationEvents(50);
  const { data: queueStatus } = useQueueStatus();
  const { data: templates = [] } = useTemplateLibrary();

  const [formOpen, setFormOpen] = useState(false);
  const [editingRule, setEditingRule] = useState<AutomationRule | null>(null);

  const activeCount = rules.filter((r) => r.is_active).length;

  function handleEdit(rule: AutomationRule) {
    setEditingRule(rule);
    setFormOpen(true);
  }

  function handleCreate() {
    setEditingRule(null);
    setFormOpen(true);
  }

  function handleFormClose(open: boolean) {
    setFormOpen(open);
    if (!open) setEditingRule(null);
  }

  return (
    <div className="space-y-6">
      {/* Header */}
      <div className="flex items-center justify-between">
        <div>
          <h1 className="text-2xl font-bold tracking-tight">Smart Workflows</h1>
          <p className="text-muted-foreground">
            Event-driven workflows, SOTA templates, and trigger rules
          </p>
        </div>
        <Button onClick={handleCreate}>
          <Plus className="mr-1 h-4 w-4" />
          New Rule
        </Button>
      </div>

      {/* KPI Cards */}
      <div className="grid gap-4 md:grid-cols-4">
        <Card>
          <CardHeader className="flex flex-row items-center justify-between pb-2">
            <CardTitle className="text-sm font-medium text-muted-foreground">
              Total Rules
            </CardTitle>
            <Workflow className="h-4 w-4 text-blue-500" />
          </CardHeader>
          <CardContent>
            <div className="text-2xl font-bold">{rules.length}</div>
            <p className="text-xs text-muted-foreground">
              Workflow rules defined
            </p>
          </CardContent>
        </Card>

        <Card>
          <CardHeader className="flex flex-row items-center justify-between pb-2">
            <CardTitle className="text-sm font-medium text-muted-foreground">
              Active Rules
            </CardTitle>
            <Zap className="h-4 w-4 text-amber-500" />
          </CardHeader>
          <CardContent>
            <div className="text-2xl font-bold">{activeCount}</div>
            <p className="text-xs text-muted-foreground">
              Currently enabled
            </p>
          </CardContent>
        </Card>

        <Card>
          <CardHeader className="flex flex-row items-center justify-between pb-2">
            <CardTitle className="text-sm font-medium text-muted-foreground">
              Templates
            </CardTitle>
            <Mail className="h-4 w-4 text-emerald-500" />
          </CardHeader>
          <CardContent>
            <div className="text-2xl font-bold">{templates.length}</div>
            <p className="text-xs text-muted-foreground">
              Email templates loaded
            </p>
          </CardContent>
        </Card>

        <Card>
          <CardHeader className="flex flex-row items-center justify-between pb-2">
            <CardTitle className="text-sm font-medium text-muted-foreground">
              Queue Depth
            </CardTitle>
            <Layers className="h-4 w-4 text-violet-500" />
          </CardHeader>
          <CardContent>
            <div className="text-2xl font-bold">
              {queueStatus?.depth ?? "—"}
            </div>
            <p className="text-xs text-muted-foreground">
              Pending events in Redis
            </p>
          </CardContent>
        </Card>
      </div>

      {/* Tabbed Content */}
      <Tabs defaultValue="workflows">
        <TabsList>
          <TabsTrigger value="workflows">
            <Workflow className="mr-1.5 h-4 w-4" />
            Workflows
          </TabsTrigger>
          <TabsTrigger value="templates">
            <Mail className="mr-1.5 h-4 w-4" />
            Templates
          </TabsTrigger>
        </TabsList>

        <TabsContent value="workflows" className="space-y-6 pt-2">
          <div>
            <h2 className="text-lg font-semibold mb-3">Rules</h2>
            <RuleList onEdit={handleEdit} />
          </div>
          <Separator />
          <div>
            <h2 className="text-lg font-semibold mb-3">Recent Events</h2>
            <EventLog />
          </div>
        </TabsContent>

        <TabsContent value="templates" className="pt-2">
          <TemplateGrid />
        </TabsContent>
      </Tabs>

      {/* Form Sheet */}
      <AutomationForm
        open={formOpen}
        onOpenChange={handleFormClose}
        editingRule={editingRule}
      />
    </div>
  );
}
