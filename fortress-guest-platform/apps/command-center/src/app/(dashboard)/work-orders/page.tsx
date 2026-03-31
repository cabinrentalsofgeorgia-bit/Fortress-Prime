"use client";

import { useEffect, useMemo, useState } from "react";
import { useWorkOrders, useCreateWorkOrder, useUpdateWorkOrder, useProperties } from "@/lib/hooks";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardContent } from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Textarea } from "@/components/ui/textarea";
import { ScrollArea } from "@/components/ui/scroll-area";
import {
  Sheet,
  SheetContent,
  SheetHeader,
  SheetTitle,
} from "@/components/ui/sheet";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import {
  Dialog,
  DialogContent,
  DialogHeader,
  DialogTitle,
  DialogTrigger,
} from "@/components/ui/dialog";
import {
  Plus,
  Clock,
  CheckCircle,
  AlertTriangle,
  Home,
  Search,
} from "lucide-react";
import { KanbanSkeleton } from "@/components/skeletons";
import type { WorkOrder } from "@/lib/types";
import { cn } from "@/lib/utils";
import { useAppStore } from "@/lib/store";

const COLUMNS = [
  { id: "open", label: "Open", icon: AlertTriangle, color: "text-orange-500" },
  { id: "in_progress", label: "In Progress", icon: Clock, color: "text-blue-500" },
  { id: "completed", label: "Completed", icon: CheckCircle, color: "text-green-500" },
];

const PRIORITY_COLORS: Record<string, string> = {
  urgent: "bg-red-500/10 text-red-500 border-red-500/30",
  high: "bg-orange-500/10 text-orange-500 border-orange-500/30",
  medium: "bg-yellow-500/10 text-yellow-600 border-yellow-500/30",
  low: "bg-slate-500/10 text-slate-500 border-slate-500/30",
};

export default function WorkOrdersPage() {
  const { data: workOrders, isLoading } = useWorkOrders();
  const { data: properties } = useProperties();
  const updateWorkOrder = useUpdateWorkOrder();
  const createWorkOrder = useCreateWorkOrder();
  const activeWorkOrderContext = useAppStore((s) => s.activeWorkOrderContext);
  const setActiveWorkOrderContext = useAppStore((s) => s.setActiveWorkOrderContext);
  const clearActiveWorkOrderContext = useAppStore((s) => s.clearActiveWorkOrderContext);
  const [search, setSearch] = useState("");
  const [createOpen, setCreateOpen] = useState(false);
  const [selectedWoId, setSelectedWoId] = useState<string | null>(
    activeWorkOrderContext?.id ?? null,
  );
  const [filterPriority, setFilterPriority] = useState("all");
  const [filterProperty] = useState("all");

  const propMap = useMemo(
    () => new Map((properties ?? []).map((p) => [p.id, p.name])),
    [properties],
  );
  const selectedWo =
    (workOrders ?? []).find((wo) => wo.id === selectedWoId) ?? null;

  const filtered = (workOrders ?? []).filter((wo) => {
    if (filterPriority !== "all" && wo.priority !== filterPriority) return false;
    if (filterProperty !== "all" && wo.property_id !== filterProperty) return false;
    if (search) {
      const q = search.toLowerCase();
      return wo.title.toLowerCase().includes(q) || wo.ticket_number.toLowerCase().includes(q);
    }
    return true;
  });

  function moveToColumn(wo: WorkOrder, newStatus: string) {
    updateWorkOrder.mutate({ id: wo.id, status: newStatus });
  }

  function handleCreate(e: React.FormEvent<HTMLFormElement>) {
    e.preventDefault();
    const form = new FormData(e.currentTarget);
    createWorkOrder.mutate({
      property_id: form.get("property_id") as string,
      title: form.get("title") as string,
      description: form.get("description") as string,
      category: (form.get("category") as string) || "other",
      priority: (form.get("priority") as string) || "medium",
    }, { onSuccess: () => setCreateOpen(false) });
  }

  useEffect(() => {
    if (!selectedWo) {
      if (activeWorkOrderContext?.id) {
        return;
      }
      clearActiveWorkOrderContext();
      return;
    }

    setActiveWorkOrderContext({
      id: selectedWo.id,
      title: selectedWo.title,
      ticketNumber: selectedWo.ticket_number,
      status: selectedWo.status,
      priority: selectedWo.priority,
      propertyName: propMap.get(selectedWo.property_id ?? ""),
      assignedTo: selectedWo.assigned_to,
    });
  }, [
    activeWorkOrderContext?.id,
    clearActiveWorkOrderContext,
    propMap,
    selectedWo,
    setActiveWorkOrderContext,
  ]);

  if (isLoading) return <KanbanSkeleton />;

  return (
    <div className="space-y-6">
      <div className="flex items-center justify-between">
        <div>
          <h1 className="text-2xl font-bold tracking-tight">Work Orders</h1>
          <p className="text-muted-foreground">
            {workOrders?.length ?? 0} work orders · {filtered.filter((w) => w.status === "open").length} open
          </p>
        </div>
        <div className="flex items-center gap-2">
          <div className="relative">
            <Search className="absolute left-2.5 top-1/2 -translate-y-1/2 h-3.5 w-3.5 text-muted-foreground" />
            <Input
              placeholder="Search..."
              className="w-48 pl-8 h-9"
              value={search}
              onChange={(e) => setSearch(e.target.value)}
            />
          </div>
          <Select value={filterPriority} onValueChange={setFilterPriority}>
            <SelectTrigger className="w-32 h-9"><SelectValue placeholder="Priority" /></SelectTrigger>
            <SelectContent>
              <SelectItem value="all">All Priority</SelectItem>
              <SelectItem value="urgent">Urgent</SelectItem>
              <SelectItem value="high">High</SelectItem>
              <SelectItem value="medium">Medium</SelectItem>
              <SelectItem value="low">Low</SelectItem>
            </SelectContent>
          </Select>
          <Dialog open={createOpen} onOpenChange={setCreateOpen}>
            <DialogTrigger asChild>
              <Button><Plus className="mr-2 h-4 w-4" />New Work Order</Button>
            </DialogTrigger>
            <DialogContent>
              <DialogHeader>
                <DialogTitle>Create Work Order</DialogTitle>
              </DialogHeader>
              <form onSubmit={handleCreate} className="space-y-4 mt-2">
                <div className="space-y-2">
                  <Label>Property</Label>
                  <Select name="property_id" required>
                    <SelectTrigger><SelectValue placeholder="Select property..." /></SelectTrigger>
                    <SelectContent>
                      {(properties ?? []).filter((p) => p.is_active).map((p) => (
                        <SelectItem key={p.id} value={p.id}>{p.name}</SelectItem>
                      ))}
                    </SelectContent>
                  </Select>
                </div>
                <div className="space-y-2">
                  <Label>Title</Label>
                  <Input name="title" placeholder="Brief description of the issue" required />
                </div>
                <div className="space-y-2">
                  <Label>Description</Label>
                  <Textarea name="description" placeholder="Full details..." rows={3} required />
                </div>
                <div className="grid grid-cols-2 gap-4">
                  <div className="space-y-2">
                    <Label>Category</Label>
                    <Select name="category" defaultValue="other">
                      <SelectTrigger><SelectValue /></SelectTrigger>
                      <SelectContent>
                        <SelectItem value="plumbing">Plumbing</SelectItem>
                        <SelectItem value="electrical">Electrical</SelectItem>
                        <SelectItem value="hvac">HVAC</SelectItem>
                        <SelectItem value="appliance">Appliance</SelectItem>
                        <SelectItem value="structural">Structural</SelectItem>
                        <SelectItem value="cleaning">Cleaning</SelectItem>
                        <SelectItem value="other">Other</SelectItem>
                      </SelectContent>
                    </Select>
                  </div>
                  <div className="space-y-2">
                    <Label>Priority</Label>
                    <Select name="priority" defaultValue="medium">
                      <SelectTrigger><SelectValue /></SelectTrigger>
                      <SelectContent>
                        <SelectItem value="urgent">Urgent</SelectItem>
                        <SelectItem value="high">High</SelectItem>
                        <SelectItem value="medium">Medium</SelectItem>
                        <SelectItem value="low">Low</SelectItem>
                      </SelectContent>
                    </Select>
                  </div>
                </div>
                <Button type="submit" className="w-full" disabled={createWorkOrder.isPending}>
                  {createWorkOrder.isPending ? "Creating..." : "Create Work Order"}
                </Button>
              </form>
            </DialogContent>
          </Dialog>
        </div>
      </div>

      {/* Kanban Board */}
      <div className="grid gap-6 lg:grid-cols-3">
        {COLUMNS.map((col) => {
          const items = filtered.filter((wo) => wo.status === col.id);
          return (
            <div key={col.id} className="space-y-3">
              <div className="flex items-center justify-between">
                <h3 className={`text-sm font-semibold flex items-center gap-1.5 ${col.color}`}>
                  <col.icon className="h-4 w-4" />
                  {col.label}
                </h3>
                <Badge variant="secondary" className="text-xs">{items.length}</Badge>
              </div>
              <ScrollArea className="h-[calc(100vh-16rem)]">
                <div className="space-y-2 pr-2">
                  {items.map((wo) => (
                    <Card
                      key={wo.id}
                      className="cursor-pointer hover:shadow-md transition-shadow"
                      onClick={() => setSelectedWoId(wo.id)}
                    >
                      <CardContent className="p-3 space-y-2">
                        <div className="flex items-start justify-between">
                          <p className="text-sm font-medium line-clamp-2">{wo.title}</p>
                          <Badge variant="outline" className={cn("text-[10px] shrink-0 ml-1", PRIORITY_COLORS[wo.priority])}>
                            {wo.priority}
                          </Badge>
                        </div>
                        <div className="flex items-center gap-2 text-xs text-muted-foreground">
                          <span className="flex items-center gap-1">
                            <Home className="h-3 w-3" />
                            {propMap.get(wo.property_id ?? "") ?? "–"}
                          </span>
                        </div>
                        <div className="flex items-center justify-between">
                          <span className="text-[10px] font-mono text-muted-foreground">{wo.ticket_number}</span>
                          <span className="text-[10px] text-muted-foreground">
                            {new Date(wo.created_at).toLocaleDateString()}
                          </span>
                        </div>
                      </CardContent>
                    </Card>
                  ))}
                  {items.length === 0 && (
                    <p className="text-center text-xs text-muted-foreground py-8">No items</p>
                  )}
                </div>
              </ScrollArea>
            </div>
          );
        })}
      </div>

      {/* Detail Sheet */}
      <Sheet open={!!selectedWo} onOpenChange={() => setSelectedWoId(null)}>
        <SheetContent className="w-[480px] overflow-y-auto">
          {selectedWo && (
            <>
              <SheetHeader>
                <SheetTitle>{selectedWo.title}</SheetTitle>
              </SheetHeader>
              <div className="mt-6 space-y-6">
                <div className="flex gap-2 flex-wrap">
                  <Badge variant="outline" className={PRIORITY_COLORS[selectedWo.priority]}>
                    {selectedWo.priority}
                  </Badge>
                  <Badge variant="outline">{selectedWo.category}</Badge>
                  <Badge variant="outline">{selectedWo.status.replace("_", " ")}</Badge>
                </div>

                <div className="space-y-2">
                  <p className="text-xs font-medium text-muted-foreground">Description</p>
                  <p className="text-sm">{selectedWo.description}</p>
                </div>

                <div className="grid grid-cols-2 gap-3">
                  <div className="rounded-lg border p-3">
                    <p className="text-xs text-muted-foreground">Property</p>
                    <p className="text-sm font-medium">{propMap.get(selectedWo.property_id ?? "") ?? "–"}</p>
                  </div>
                  <div className="rounded-lg border p-3">
                    <p className="text-xs text-muted-foreground">Ticket</p>
                    <p className="text-sm font-mono">{selectedWo.ticket_number}</p>
                  </div>
                  <div className="rounded-lg border p-3">
                    <p className="text-xs text-muted-foreground">Assigned To</p>
                    <p className="text-sm font-medium">{selectedWo.assigned_to ?? "Unassigned"}</p>
                  </div>
                  <div className="rounded-lg border p-3">
                    <p className="text-xs text-muted-foreground">Created</p>
                    <p className="text-sm">{new Date(selectedWo.created_at).toLocaleDateString()}</p>
                  </div>
                </div>

                <div className="space-y-2">
                  <p className="text-xs font-medium text-muted-foreground">Move to</p>
                  <div className="flex gap-2">
                    {COLUMNS.filter((c) => c.id !== selectedWo.status).map((col) => (
                      <Button
                        key={col.id}
                        variant="outline"
                        size="sm"
                        onClick={() => {
                          moveToColumn(selectedWo, col.id);
                          setSelectedWoId(null);
                        }}
                      >
                        <col.icon className={`mr-1.5 h-3.5 w-3.5 ${col.color}`} />
                        {col.label}
                      </Button>
                    ))}
                  </div>
                </div>
              </div>
            </>
          )}
        </SheetContent>
      </Sheet>
    </div>
  );
}
