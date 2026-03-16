"use client";

import { useState } from "react";
import { useReviewQueue, useReviewAction, useDashboardStats, useMessageTemplates } from "@/lib/hooks";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import {
  Card,
  CardContent,
  CardHeader,
  CardTitle,
} from "@/components/ui/card";
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/tabs";
import { Textarea } from "@/components/ui/textarea";
import { Bot, Check, X, Edit, Zap, Shield, Brain, Save } from "lucide-react";

export default function AIEnginePage() {
  const { data: queue } = useReviewQueue();
  const { data: stats } = useDashboardStats();
  const { data: templates } = useMessageTemplates();
  const reviewAction = useReviewAction();

  const safeQueue = Array.isArray(queue) ? queue : [];
  const safeTemplates = Array.isArray(templates) ? templates : [];

  const pending = safeQueue.filter((i) => i.status === "pending");
  const processed = safeQueue.filter((i) => i.status !== "pending");

  const [editId, setEditId] = useState<string | null>(null);
  const [editText, setEditText] = useState("");

  return (
    <div className="space-y-6">
      <div>
        <h1 className="text-2xl font-bold tracking-tight">AI Engine</h1>
        <p className="text-muted-foreground">
          Autonomous guest communication intelligence
        </p>
      </div>

      <div className="grid gap-4 md:grid-cols-4">
        <Card>
          <CardHeader className="flex flex-row items-center justify-between pb-2">
            <CardTitle className="text-sm font-medium text-muted-foreground">
              Automation Rate
            </CardTitle>
            <Zap className="h-4 w-4 text-amber-500" />
          </CardHeader>
          <CardContent>
            <div className="text-2xl font-bold">
              {stats ? `${Math.round(stats.ai_automation_rate)}%` : "–"}
            </div>
            <p className="text-xs text-muted-foreground">AI-handled messages</p>
          </CardContent>
        </Card>
        <Card>
          <CardHeader className="flex flex-row items-center justify-between pb-2">
            <CardTitle className="text-sm font-medium text-muted-foreground">
              Pending Review
            </CardTitle>
            <Shield className="h-4 w-4 text-orange-500" />
          </CardHeader>
          <CardContent>
            <div className="text-2xl font-bold">{pending.length}</div>
            <p className="text-xs text-muted-foreground">Needs human approval</p>
          </CardContent>
        </Card>
        <Card>
          <CardHeader className="flex flex-row items-center justify-between pb-2">
            <CardTitle className="text-sm font-medium text-muted-foreground">
              Processed Today
            </CardTitle>
            <Brain className="h-4 w-4 text-violet-500" />
          </CardHeader>
          <CardContent>
            <div className="text-2xl font-bold">{processed.length}</div>
            <p className="text-xs text-muted-foreground">Approved / rejected</p>
          </CardContent>
        </Card>
        <Card>
          <CardHeader className="flex flex-row items-center justify-between pb-2">
            <CardTitle className="text-sm font-medium text-muted-foreground">
              Templates Active
            </CardTitle>
            <Bot className="h-4 w-4 text-blue-500" />
          </CardHeader>
          <CardContent>
            <div className="text-2xl font-bold">
              {safeTemplates.filter((t) => t.is_active).length || "–"}
            </div>
            <p className="text-xs text-muted-foreground">Message templates</p>
          </CardContent>
        </Card>
      </div>

      <Tabs defaultValue="queue">
        <TabsList>
          <TabsTrigger value="queue">
            Review Queue
            {pending.length > 0 && (
              <Badge variant="destructive" className="ml-2 text-[10px]">
                {pending.length}
              </Badge>
            )}
          </TabsTrigger>
          <TabsTrigger value="templates">Templates</TabsTrigger>
          <TabsTrigger value="history">History</TabsTrigger>
        </TabsList>

        <TabsContent value="queue" className="mt-4 space-y-4">
          {pending.length === 0 ? (
            <Card>
              <CardContent className="py-12 text-center">
                <Bot className="h-12 w-12 mx-auto mb-4 text-muted-foreground/50" />
                <p className="text-muted-foreground">All caught up. No pending reviews.</p>
              </CardContent>
            </Card>
          ) : (
            pending.map((item) => (
              <Card key={item.id}>
                <CardContent className="p-4 space-y-3">
                  <div className="flex items-start justify-between">
                    <div className="flex items-center gap-2">
                      <Badge variant="outline">{item.intent}</Badge>
                      <Badge variant="outline">{item.sentiment}</Badge>
                      <Badge variant="secondary">
                        {Math.round((item.ai_confidence ?? 0) * 100)}% confidence
                      </Badge>
                    </div>
                    <span className="text-xs text-muted-foreground">
                      {new Date(item.created_at).toLocaleString()}
                    </span>
                  </div>

                  <div className="rounded-lg bg-muted p-3">
                    <p className="text-xs font-medium text-muted-foreground mb-1">Guest message:</p>
                    <p className="text-sm">{item.original_message}</p>
                  </div>

                  {editId === item.id ? (
                    <div className="space-y-2">
                      <p className="text-xs font-medium text-primary flex items-center gap-1">
                        <Edit className="h-3 w-3" />
                        Editing AI Draft:
                      </p>
                      <Textarea
                        value={editText}
                        onChange={(e) => setEditText(e.target.value)}
                        rows={4}
                      />
                      <div className="flex gap-2">
                        <Button
                          size="sm"
                          onClick={() => {
                            reviewAction.mutate({ id: item.id, action: "edit", edited_response: editText });
                            setEditId(null);
                            setEditText("");
                          }}
                        >
                          <Save className="h-4 w-4 mr-1" />
                          Save & Send
                        </Button>
                        <Button
                          size="sm"
                          variant="ghost"
                          onClick={() => { setEditId(null); setEditText(""); }}
                        >
                          Cancel
                        </Button>
                      </div>
                    </div>
                  ) : (
                    <div className="rounded-lg border border-primary/20 bg-primary/5 p-3">
                      <p className="text-xs font-medium text-primary mb-1 flex items-center gap-1">
                        <Bot className="h-3 w-3" />
                        AI Draft:
                      </p>
                      <p className="text-sm">{item.ai_draft_response}</p>
                    </div>
                  )}

                  <div className="flex gap-2 pt-1">
                    <Button
                      size="sm"
                      onClick={() => reviewAction.mutate({ id: item.id, action: "approve" })}
                    >
                      <Check className="h-4 w-4 mr-1" />
                      Approve & Send
                    </Button>
                    <Button
                      size="sm"
                      variant="outline"
                      onClick={() => {
                        setEditId(item.id);
                        setEditText(item.ai_draft_response);
                      }}
                    >
                      <Edit className="h-4 w-4 mr-1" />
                      Edit
                    </Button>
                    <Button
                      size="sm"
                      variant="destructive"
                      onClick={() => reviewAction.mutate({ id: item.id, action: "reject" })}
                    >
                      <X className="h-4 w-4 mr-1" />
                      Reject
                    </Button>
                  </div>
                </CardContent>
              </Card>
            ))
          )}
        </TabsContent>

        <TabsContent value="templates" className="mt-4">
          <div className="grid gap-4 md:grid-cols-2">
            {safeTemplates.map((t) => (
              <Card key={t.id}>
                <CardHeader className="pb-2">
                  <div className="flex items-center justify-between">
                    <CardTitle className="text-sm">{t.name}</CardTitle>
                    <Badge variant={t.is_active ? "default" : "secondary"}>
                      {t.is_active ? "Active" : "Inactive"}
                    </Badge>
                  </div>
                </CardHeader>
                <CardContent className="space-y-2">
                  <Badge variant="outline" className="text-[10px]">
                    {t.category} &middot; {t.trigger_type}
                  </Badge>
                  <p className="text-xs text-muted-foreground">{(t.body ?? "").slice(0, 120)}...</p>
                  <div className="flex gap-1 flex-wrap">
                    {(t.variables ?? []).map((v) => (
                      <Badge key={v} variant="outline" className="text-[10px] font-mono">
                        {`{{${v}}}`}
                      </Badge>
                    ))}
                  </div>
                </CardContent>
              </Card>
            ))}
          </div>
        </TabsContent>

        <TabsContent value="history" className="mt-4 space-y-4">
          {processed.length === 0 ? (
            <Card>
              <CardContent className="py-12 text-center">
                <Brain className="h-12 w-12 mx-auto mb-4 text-muted-foreground/50" />
                <p className="text-muted-foreground">No review history yet</p>
              </CardContent>
            </Card>
          ) : (
            processed.map((item) => (
              <Card key={item.id}>
                <CardContent className="p-4 space-y-3">
                  <div className="flex items-start justify-between">
                    <div className="flex items-center gap-2">
                      <Badge variant="outline">{item.intent}</Badge>
                      <Badge variant="outline">{item.sentiment}</Badge>
                      <Badge
                        variant={
                          item.status === "approved"
                            ? "default"
                            : item.status === "rejected"
                              ? "destructive"
                              : "secondary"
                        }
                      >
                        {item.status}
                      </Badge>
                    </div>
                    <span className="text-xs text-muted-foreground">
                      {new Date(item.created_at).toLocaleString()}
                    </span>
                  </div>

                  <div className="rounded-lg bg-muted p-3">
                    <p className="text-xs font-medium text-muted-foreground mb-1">Guest message:</p>
                    <p className="text-sm">{item.original_message}</p>
                  </div>

                  <div className="rounded-lg border p-3">
                    <p className="text-xs font-medium text-muted-foreground mb-1 flex items-center gap-1">
                      <Bot className="h-3 w-3" />
                      AI Response:
                    </p>
                    <p className="text-sm">{item.ai_draft_response}</p>
                  </div>
                </CardContent>
              </Card>
            ))
          )}
        </TabsContent>
      </Tabs>
    </div>
  );
}
