"use client";

import { useState, useMemo, useCallback, useEffect } from "react";
import {
  useHousekeepingToday,
  useHousekeepingWeek,
  useProperties,
  useDepartingToday,
  useAssignCleaner,
  useCompleteTurnover,
  useAutoScheduleHousekeeping,
  useLinenRequirements,
} from "@/lib/hooks";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/tabs";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import { Checkbox } from "@/components/ui/checkbox";
import { Label } from "@/components/ui/label";
import { ScrollArea } from "@/components/ui/scroll-area";
import { Textarea } from "@/components/ui/textarea";
import { Progress } from "@/components/ui/progress";
import { Separator } from "@/components/ui/separator";
import {
  Sheet,
  SheetContent,
  SheetHeader,
  SheetTitle,
} from "@/components/ui/sheet";
import {
  ClipboardList,
  Home,
  CalendarDays,
  User,
  Clock,
  CheckCircle,
  AlertCircle,
  Camera,
  Sparkles,
  ArrowRight,
  ArrowLeft,
  PlayCircle,
  Timer,
  Shield,
  Bed,
  Bath,
  ChefHat,
  Sofa,
  TreePine,
  Gamepad2,
  DoorOpen,
  Thermometer,
  Lock,
  Trash2,
  Package,
  Eye,
  AlertTriangle,
  Zap,
  Loader2,
} from "lucide-react";
import { toast } from "sonner";
import { KanbanSkeleton } from "@/components/skeletons";
import { cn } from "@/lib/utils";

// ---------------------------------------------------------------------------
// Room-by-room Walk the Wall definitions
// ---------------------------------------------------------------------------
interface RoomZone {
  id: string;
  name: string;
  icon: React.ReactNode;
  items: ChecklistItem[];
}

interface ChecklistItem {
  id: string;
  label: string;
  category: "clean" | "inspect" | "restock" | "secure";
  critical?: boolean;
}

const ROOM_ZONES: RoomZone[] = [
  {
    id: "entry",
    name: "Entry & First Impression",
    icon: <DoorOpen className="h-4 w-4" />,
    items: [
      { id: "entry-1", label: "Front door clean, no scuffs", category: "inspect" },
      { id: "entry-2", label: "Door lock & keypad functioning", category: "secure", critical: true },
      { id: "entry-3", label: "Welcome mat clean & straight", category: "clean" },
      { id: "entry-4", label: "Entry light working", category: "inspect" },
      { id: "entry-5", label: "Shoes/boots tray empty", category: "clean" },
      { id: "entry-6", label: "Check for guest left-behind items", category: "inspect", critical: true },
    ],
  },
  {
    id: "living",
    name: "Living Room",
    icon: <Sofa className="h-4 w-4" />,
    items: [
      { id: "living-1", label: "Vacuum/sweep all floors", category: "clean" },
      { id: "living-2", label: "Dust all surfaces & shelves", category: "clean" },
      { id: "living-3", label: "Wipe TV & remote (batteries check)", category: "clean" },
      { id: "living-4", label: "Fluff & arrange cushions/throws", category: "clean" },
      { id: "living-5", label: "Windows clean, no streaks", category: "clean" },
      { id: "living-6", label: "Check for stains on furniture", category: "inspect", critical: true },
      { id: "living-7", label: "Fireplace clean & damper closed", category: "inspect" },
      { id: "living-8", label: "Check walls for scuffs/damage", category: "inspect", critical: true },
    ],
  },
  {
    id: "kitchen",
    name: "Kitchen",
    icon: <ChefHat className="h-4 w-4" />,
    items: [
      { id: "kit-1", label: "Clean all countertops", category: "clean" },
      { id: "kit-2", label: "Clean inside microwave", category: "clean" },
      { id: "kit-3", label: "Clean oven (check for spills)", category: "clean" },
      { id: "kit-4", label: "Clean refrigerator inside & out", category: "clean" },
      { id: "kit-5", label: "Run & empty dishwasher", category: "clean" },
      { id: "kit-6", label: "Clean sink, no residue", category: "clean" },
      { id: "kit-7", label: "Restock dish soap & sponge", category: "restock" },
      { id: "kit-8", label: "Restock coffee/tea supplies", category: "restock" },
      { id: "kit-9", label: "Restock paper towels & trash bags", category: "restock" },
      { id: "kit-10", label: "Check all burners work", category: "inspect" },
      { id: "kit-11", label: "Verify all dishes/utensils present", category: "inspect" },
    ],
  },
  {
    id: "master",
    name: "Master Bedroom",
    icon: <Bed className="h-4 w-4" />,
    items: [
      { id: "master-1", label: "Strip bed completely", category: "clean" },
      { id: "master-2", label: "Check mattress pad for stains", category: "inspect", critical: true },
      { id: "master-3", label: "Make bed with fresh linens", category: "clean" },
      { id: "master-4", label: "Vacuum/sweep floor & under bed", category: "clean" },
      { id: "master-5", label: "Dust nightstands & lamps", category: "clean" },
      { id: "master-6", label: "Empty drawers & closet (check for items)", category: "inspect", critical: true },
      { id: "master-7", label: "Check for wall/furniture damage", category: "inspect", critical: true },
      { id: "master-8", label: "Set alarm clock to off", category: "secure" },
    ],
  },
  {
    id: "bedroom2",
    name: "Additional Bedrooms",
    icon: <Bed className="h-4 w-4" />,
    items: [
      { id: "bed2-1", label: "Strip & remake all beds with fresh linens", category: "clean" },
      { id: "bed2-2", label: "Check all mattress pads", category: "inspect", critical: true },
      { id: "bed2-3", label: "Vacuum/sweep all floors", category: "clean" },
      { id: "bed2-4", label: "Dust all surfaces", category: "clean" },
      { id: "bed2-5", label: "Check closets & drawers empty", category: "inspect", critical: true },
      { id: "bed2-6", label: "Check walls/furniture for damage", category: "inspect", critical: true },
    ],
  },
  {
    id: "bathroom",
    name: "Bathrooms",
    icon: <Bath className="h-4 w-4" />,
    items: [
      { id: "bath-1", label: "Scrub toilets inside & out", category: "clean" },
      { id: "bath-2", label: "Clean shower/tub (no mildew)", category: "clean" },
      { id: "bath-3", label: "Clean mirrors (streak-free)", category: "clean" },
      { id: "bath-4", label: "Clean vanity & sink", category: "clean" },
      { id: "bath-5", label: "Mop/clean floors", category: "clean" },
      { id: "bath-6", label: "Replace all towels (fresh set)", category: "restock" },
      { id: "bath-7", label: "Restock toilet paper (2+ rolls)", category: "restock" },
      { id: "bath-8", label: "Restock shampoo/conditioner/soap", category: "restock" },
      { id: "bath-9", label: "Check drain speed (hair clogs)", category: "inspect" },
      { id: "bath-10", label: "Check for tile/grout damage", category: "inspect", critical: true },
    ],
  },
  {
    id: "outdoor",
    name: "Deck, Patio & Exterior",
    icon: <TreePine className="h-4 w-4" />,
    items: [
      { id: "out-1", label: "Sweep deck/patio", category: "clean" },
      { id: "out-2", label: "Wipe outdoor furniture", category: "clean" },
      { id: "out-3", label: "Check grill (clean if used)", category: "clean" },
      { id: "out-4", label: "Hot tub: check water & cover", category: "inspect", critical: true },
      { id: "out-5", label: "Check exterior lights working", category: "inspect" },
      { id: "out-6", label: "Remove any guest trash/items", category: "clean" },
      { id: "out-7", label: "Check railing & stairs safety", category: "inspect", critical: true },
    ],
  },
  {
    id: "final",
    name: "Final Walkthrough & Lockup",
    icon: <Lock className="h-4 w-4" />,
    items: [
      { id: "final-1", label: "Set thermostat to away mode", category: "secure" },
      { id: "final-2", label: "All lights off except porch", category: "secure" },
      { id: "final-3", label: "All windows closed & locked", category: "secure", critical: true },
      { id: "final-4", label: "All doors locked", category: "secure", critical: true },
      { id: "final-5", label: "Take out all trash to bin", category: "clean" },
      { id: "final-6", label: "Garage door closed", category: "secure" },
      { id: "final-7", label: "Check smoke/CO detectors (light on)", category: "inspect", critical: true },
      { id: "final-8", label: "Overall smell check — fresh", category: "inspect" },
      { id: "final-9", label: "Photo documentation complete", category: "inspect" },
    ],
  },
];

interface HKTask {
  id: string;
  property: string;
  propertyId: string;
  status: string;
  assignedTo: string;
  checkoutTime: string;
  nextCheckIn: string;
  estimatedMinutes: number;
  scheduledDate: string;
  checkedItems: Record<string, boolean>;
  notes: string;
  damageFlags: string[];
  startedAt: number | null;
}

const CATEGORY_COLORS: Record<string, string> = {
  clean: "bg-blue-500",
  inspect: "bg-amber-500",
  restock: "bg-emerald-500",
  secure: "bg-violet-500",
};

const STATUS_COLORS: Record<string, string> = {
  pending: "bg-slate-500/10 text-slate-500",
  scheduled: "bg-blue-500/10 text-blue-500",
  in_progress: "bg-amber-500/10 text-amber-500",
  completed: "bg-green-500/10 text-green-500",
  inspected: "bg-emerald-500/10 text-emerald-600",
};

export default function HousekeepingPage() {
  const { data: todayData, isLoading: todayLoading } = useHousekeepingToday();
  const { data: weekData } = useHousekeepingWeek();
  const { data: departing } = useDepartingToday();
  const { data: properties } = useProperties();
  const assignCleaner = useAssignCleaner();
  const completeTurnover = useCompleteTurnover();
  const autoSchedule = useAutoScheduleHousekeeping();

  const [tasks, setTasks] = useState<HKTask[]>([]);
  const [selectedTaskId, setSelectedTaskId] = useState<string | null>(null);
  const [walkMode, setWalkMode] = useState(false);
  const [currentZone, setCurrentZone] = useState(0);
  const [completionNotes, setCompletionNotes] = useState("");
  const [tab, setTab] = useState("today");

  useEffect(() => {
    const rawTasks = Array.isArray(todayData)
      ? (todayData as Array<{
          id: string;
          property_name?: string;
          property_id: string;
          status: string;
          assigned_to?: string;
          scheduled_time?: string;
          estimated_minutes?: number;
          scheduled_date?: string;
        }>)
      : (departing ?? []).map((r, i) => ({
          id: r.id ?? `dep-${i}`,
          property_name: r.property_name ?? "Property",
          property_id: r.property_id,
          status: "pending",
          assigned_to: "",
          scheduled_time: "11:00",
          estimated_minutes: 150,
          scheduled_date: new Date().toISOString().split("T")[0],
        }));

    setTasks(
      rawTasks.map((t) => ({
        id: t.id,
        property: t.property_name ?? "Property",
        propertyId: t.property_id,
        status: t.status,
        assignedTo: t.assigned_to ?? "Unassigned",
        checkoutTime: t.scheduled_time ?? "11:00 AM",
        nextCheckIn: "4:00 PM",
        estimatedMinutes: t.estimated_minutes ?? 150,
        scheduledDate: t.scheduled_date ?? new Date().toISOString().split("T")[0],
        checkedItems: {},
        notes: "",
        damageFlags: [],
        startedAt: null,
      })),
    );
  }, [todayData, departing]);

  const selectedTask = tasks.find((t) => t.id === selectedTaskId) ?? null;
  const selectedIdx = tasks.findIndex((t) => t.id === selectedTaskId);

  const totalChecklistItems = ROOM_ZONES.reduce((s, z) => s + z.items.length, 0);
  const checkedCount = selectedTask
    ? Object.values(selectedTask.checkedItems).filter(Boolean).length
    : 0;
  const progressPct = totalChecklistItems > 0 ? Math.round((checkedCount / totalChecklistItems) * 100) : 0;

  function toggleItem(itemId: string) {
    if (!selectedTaskId) return;
    setTasks((prev) =>
      prev.map((t) =>
        t.id === selectedTaskId
          ? { ...t, checkedItems: { ...t.checkedItems, [itemId]: !t.checkedItems[itemId] } }
          : t,
      ),
    );
  }

  function flagDamage(itemId: string, label: string) {
    if (!selectedTaskId) return;
    setTasks((prev) =>
      prev.map((t) => {
        if (t.id !== selectedTaskId) return t;
        const has = t.damageFlags.includes(itemId);
        return {
          ...t,
          damageFlags: has
            ? t.damageFlags.filter((f) => f !== itemId)
            : [...t.damageFlags, itemId],
        };
      }),
    );
    toast.info(selectedTask?.damageFlags.includes(itemId) ? "Damage flag removed" : `Damage flagged: ${label}`);
  }

  function startCleaning() {
    if (!selectedTaskId) return;
    setTasks((prev) =>
      prev.map((t) =>
        t.id === selectedTaskId ? { ...t, status: "in_progress", startedAt: Date.now() } : t,
      ),
    );
    assignCleaner.mutate({ taskId: selectedTaskId, cleanerName: selectedTask?.assignedTo ?? "Unassigned" });
    setWalkMode(true);
    setCurrentZone(0);
    toast.success("Walk the Wall started — follow each room step by step");
  }

  function finishCleaning() {
    if (!selectedTaskId) return;
    const dmgCount = selectedTask?.damageFlags.length ?? 0;
    completeTurnover.mutate({
      taskId: selectedTaskId,
      notes: completionNotes + (dmgCount > 0 ? `\n[${dmgCount} damage item(s) flagged]` : ""),
    });
    setTasks((prev) =>
      prev.map((t) =>
        t.id === selectedTaskId ? { ...t, status: "completed" } : t,
      ),
    );
    setWalkMode(false);
    setCompletionNotes("");
    if (dmgCount > 0) {
      toast.warning(`Completed with ${dmgCount} damage flag(s) — review in Damage Claims`);
    }
  }

  function handleAssign(cleanerName: string) {
    if (!selectedTaskId) return;
    setTasks((prev) =>
      prev.map((t) =>
        t.id === selectedTaskId ? { ...t, assignedTo: cleanerName } : t,
      ),
    );
    assignCleaner.mutate({ taskId: selectedTaskId, cleanerName });
  }

  const todayStats = useMemo(() => ({
    total: tasks.length,
    pending: tasks.filter((t) => t.status === "pending" || t.status === "scheduled").length,
    inProgress: tasks.filter((t) => t.status === "in_progress").length,
    completed: tasks.filter((t) => t.status === "completed" || t.status === "inspected").length,
    damageFlags: tasks.reduce((s, t) => s + t.damageFlags.length, 0),
  }), [tasks]);

  if (todayLoading) return <KanbanSkeleton />;

  // ---------------------------------------------------------------------------
  // Walk the Wall guided mode
  // ---------------------------------------------------------------------------
  if (walkMode && selectedTask) {
    const zone = ROOM_ZONES[currentZone];
    const zoneChecked = zone.items.filter((it) => selectedTask.checkedItems[it.id]).length;
    const zoneTotal = zone.items.length;
    const allZonesComplete = ROOM_ZONES.every((z) =>
      z.items.every((it) => selectedTask.checkedItems[it.id]),
    );

    return (
      <div className="space-y-4">
        {/* Walk the Wall header */}
        <div className="flex items-center justify-between">
          <div>
            <h1 className="text-xl font-bold flex items-center gap-2">
              <Shield className="h-5 w-5 text-primary" />
              Walk the Wall — {selectedTask.property}
            </h1>
            <p className="text-sm text-muted-foreground">
              Room {currentZone + 1} of {ROOM_ZONES.length} — {zone.name}
            </p>
          </div>
          <div className="flex items-center gap-3">
            {selectedTask.startedAt && (
              <TimerDisplay startedAt={selectedTask.startedAt} estimated={selectedTask.estimatedMinutes} />
            )}
            <Button variant="outline" size="sm" onClick={() => setWalkMode(false)}>
              Exit Walk Mode
            </Button>
          </div>
        </div>

        {/* Progress overview */}
        <div className="flex items-center gap-3">
          <Progress value={progressPct} className="flex-1 h-3" />
          <span className="text-sm font-medium tabular-nums">{progressPct}%</span>
        </div>

        {/* Zone nav pills */}
        <div className="flex items-center gap-1.5 overflow-x-auto pb-1">
          {ROOM_ZONES.map((z, i) => {
            const done = z.items.every((it) => selectedTask.checkedItems[it.id]);
            const partial = z.items.some((it) => selectedTask.checkedItems[it.id]) && !done;
            const hasDamage = z.items.some((it) => selectedTask.damageFlags.includes(it.id));
            return (
              <button
                key={z.id}
                onClick={() => setCurrentZone(i)}
                className={cn(
                  "flex items-center gap-1.5 rounded-full px-3 py-1.5 text-xs font-medium transition-all shrink-0 border",
                  i === currentZone
                    ? "bg-primary text-primary-foreground border-primary"
                    : done
                      ? "bg-green-500/10 text-green-600 border-green-500/30"
                      : partial
                        ? "bg-amber-500/10 text-amber-600 border-amber-500/30"
                        : "bg-muted text-muted-foreground border-transparent",
                  hasDamage && "ring-2 ring-red-500/50",
                )}
              >
                {z.icon}
                {z.name}
                {done && <CheckCircle className="h-3 w-3 ml-0.5" />}
                {hasDamage && <AlertTriangle className="h-3 w-3 ml-0.5 text-red-500" />}
              </button>
            );
          })}
        </div>

        {/* Current zone checklist */}
        <Card>
          <CardHeader className="pb-3">
            <div className="flex items-center justify-between">
              <CardTitle className="text-base flex items-center gap-2">
                {zone.icon}
                {zone.name}
                <Badge variant="outline" className="ml-2 text-xs">{zoneChecked}/{zoneTotal}</Badge>
              </CardTitle>
              <div className="flex gap-1.5">
                <span className="flex items-center gap-1 text-[10px] text-blue-500"><span className="h-2 w-2 rounded-full bg-blue-500" />Clean</span>
                <span className="flex items-center gap-1 text-[10px] text-amber-500"><span className="h-2 w-2 rounded-full bg-amber-500" />Inspect</span>
                <span className="flex items-center gap-1 text-[10px] text-emerald-500"><span className="h-2 w-2 rounded-full bg-emerald-500" />Restock</span>
                <span className="flex items-center gap-1 text-[10px] text-violet-500"><span className="h-2 w-2 rounded-full bg-violet-500" />Secure</span>
              </div>
            </div>
          </CardHeader>
          <CardContent>
            <div className="space-y-1.5">
              {zone.items.map((item) => {
                const checked = !!selectedTask.checkedItems[item.id];
                const damaged = selectedTask.damageFlags.includes(item.id);
                return (
                  <div
                    key={item.id}
                    className={cn(
                      "flex items-center gap-3 rounded-lg border p-3 transition-colors",
                      checked && !damaged && "bg-green-500/5 border-green-500/20",
                      damaged && "bg-red-500/5 border-red-500/30",
                      !checked && !damaged && "hover:bg-muted/50",
                    )}
                  >
                    <span className={cn("h-2.5 w-2.5 rounded-full shrink-0", CATEGORY_COLORS[item.category])} />
                    <Checkbox
                      checked={checked}
                      onCheckedChange={() => toggleItem(item.id)}
                    />
                    <span className={cn(
                      "text-sm flex-1",
                      checked && !damaged && "line-through text-muted-foreground",
                    )}>
                      {item.label}
                      {item.critical && (
                        <Badge variant="outline" className="ml-1.5 text-[9px] text-red-500 border-red-500/30">CRITICAL</Badge>
                      )}
                    </span>
                    <Button
                      variant={damaged ? "destructive" : "ghost"}
                      size="icon"
                      className="h-7 w-7 shrink-0"
                      onClick={() => flagDamage(item.id, item.label)}
                      title={damaged ? "Remove damage flag" : "Flag damage"}
                    >
                      <AlertTriangle className="h-3.5 w-3.5" />
                    </Button>
                  </div>
                );
              })}
            </div>

            {/* Zone navigation */}
            <div className="flex items-center justify-between mt-6">
              <Button
                variant="outline"
                size="sm"
                disabled={currentZone === 0}
                onClick={() => setCurrentZone((c) => c - 1)}
              >
                <ArrowLeft className="mr-1.5 h-4 w-4" />Previous Room
              </Button>

              {currentZone < ROOM_ZONES.length - 1 ? (
                <Button
                  size="sm"
                  onClick={() => setCurrentZone((c) => c + 1)}
                >
                  Next Room<ArrowRight className="ml-1.5 h-4 w-4" />
                </Button>
              ) : (
                <Button
                  size="sm"
                  className={cn(allZonesComplete ? "bg-green-600 hover:bg-green-700" : "")}
                  onClick={finishCleaning}
                  disabled={completeTurnover.isPending}
                >
                  {completeTurnover.isPending ? (
                    <><Loader2 className="mr-1.5 h-4 w-4 animate-spin" />Submitting...</>
                  ) : (
                    <><CheckCircle className="mr-1.5 h-4 w-4" />Complete Turnover</>
                  )}
                </Button>
              )}
            </div>

            {/* Damage summary & notes at end */}
            {currentZone === ROOM_ZONES.length - 1 && (
              <div className="mt-4 space-y-3">
                <Separator />
                {selectedTask.damageFlags.length > 0 && (
                  <div className="rounded-lg border border-red-500/30 bg-red-500/5 p-3">
                    <p className="text-sm font-medium text-red-600 flex items-center gap-1.5">
                      <AlertTriangle className="h-4 w-4" />
                      {selectedTask.damageFlags.length} Damage Item(s) Flagged
                    </p>
                    <ul className="mt-1.5 space-y-0.5">
                      {selectedTask.damageFlags.map((fId) => {
                        const item = ROOM_ZONES.flatMap((z) => z.items).find((it) => it.id === fId);
                        return (
                          <li key={fId} className="text-xs text-red-600/80">
                            - {item?.label ?? fId}
                          </li>
                        );
                      })}
                    </ul>
                    <p className="text-[10px] text-muted-foreground mt-2">
                      These will be available to reference when filing a damage claim
                    </p>
                  </div>
                )}
                <div className="space-y-1.5">
                  <Label className="text-xs">Completion Notes (optional)</Label>
                  <Textarea
                    rows={3}
                    placeholder="Any notes for the manager..."
                    value={completionNotes}
                    onChange={(e) => setCompletionNotes(e.target.value)}
                  />
                </div>
              </div>
            )}
          </CardContent>
        </Card>
      </div>
    );
  }

  // ---------------------------------------------------------------------------
  // Normal housekeeping dashboard
  // ---------------------------------------------------------------------------
  return (
    <div className="space-y-6">
      <div className="flex items-center justify-between">
        <div>
          <h1 className="text-2xl font-bold tracking-tight flex items-center gap-2">
            <ClipboardList className="h-6 w-6 text-blue-500" />
            Housekeeping
          </h1>
          <p className="text-muted-foreground">
            {new Date().toLocaleDateString("en-US", { weekday: "long", month: "long", day: "numeric" })}
          </p>
        </div>
        <Button
          variant="outline"
          onClick={() => autoSchedule.mutate()}
          disabled={autoSchedule.isPending}
        >
          {autoSchedule.isPending ? <Loader2 className="mr-2 h-4 w-4 animate-spin" /> : <Zap className="mr-2 h-4 w-4" />}
          Auto-Schedule Turnovers
        </Button>
      </div>

      {/* Stats */}
      <div className="grid gap-4 md:grid-cols-5">
        <Card>
          <CardContent className="pt-4 flex items-center gap-3">
            <ClipboardList className="h-8 w-8 text-blue-500" />
            <div>
              <p className="text-2xl font-bold">{todayStats.total}</p>
              <p className="text-xs text-muted-foreground">Total Today</p>
            </div>
          </CardContent>
        </Card>
        <Card>
          <CardContent className="pt-4 flex items-center gap-3">
            <Clock className="h-8 w-8 text-slate-500" />
            <div>
              <p className="text-2xl font-bold">{todayStats.pending}</p>
              <p className="text-xs text-muted-foreground">Pending</p>
            </div>
          </CardContent>
        </Card>
        <Card>
          <CardContent className="pt-4 flex items-center gap-3">
            <Sparkles className="h-8 w-8 text-amber-500" />
            <div>
              <p className="text-2xl font-bold">{todayStats.inProgress}</p>
              <p className="text-xs text-muted-foreground">In Progress</p>
            </div>
          </CardContent>
        </Card>
        <Card>
          <CardContent className="pt-4 flex items-center gap-3">
            <CheckCircle className="h-8 w-8 text-green-500" />
            <div>
              <p className="text-2xl font-bold">{todayStats.completed}</p>
              <p className="text-xs text-muted-foreground">Completed</p>
            </div>
          </CardContent>
        </Card>
        <Card>
          <CardContent className="pt-4 flex items-center gap-3">
            <AlertTriangle className="h-8 w-8 text-red-500" />
            <div>
              <p className="text-2xl font-bold">{todayStats.damageFlags}</p>
              <p className="text-xs text-muted-foreground">Damage Flags</p>
            </div>
          </CardContent>
        </Card>
      </div>

      <Tabs value={tab} onValueChange={setTab}>
        <TabsList>
          <TabsTrigger value="today">Today&apos;s Turnovers</TabsTrigger>
          <TabsTrigger value="week">Week Ahead</TabsTrigger>
        </TabsList>

        <TabsContent value="today" className="mt-4">
          <div className="grid gap-6 lg:grid-cols-[1fr_420px]">
            {/* Task list */}
            <div className="space-y-3">
              {tasks.length === 0 ? (
                <Card>
                  <CardContent className="py-12 text-center text-muted-foreground">
                    <CheckCircle className="h-12 w-12 mx-auto mb-4 opacity-30" />
                    <p className="font-medium">No turnovers scheduled for today</p>
                    <p className="text-sm mt-1">Use Auto-Schedule to generate tasks from upcoming checkouts</p>
                  </CardContent>
                </Card>
              ) : (
                tasks.map((task) => {
                  const taskChecked = Object.values(task.checkedItems).filter(Boolean).length;
                  const hasDamage = task.damageFlags.length > 0;
                  return (
                    <Card
                      key={task.id}
                      className={cn(
                        "cursor-pointer transition-all",
                        selectedTaskId === task.id ? "ring-2 ring-primary" : "hover:shadow-md",
                        hasDamage && "border-red-500/30",
                      )}
                      onClick={() => setSelectedTaskId(task.id)}
                    >
                      <CardContent className="p-4">
                        <div className="flex items-center justify-between">
                          <div className="flex items-center gap-3">
                            <div className={cn(
                              "h-10 w-10 rounded-lg flex items-center justify-center",
                              task.status === "completed"
                                ? "bg-green-500/10"
                                : task.status === "in_progress"
                                  ? "bg-amber-500/10"
                                  : "bg-muted",
                            )}>
                              <Home className={cn(
                                "h-5 w-5",
                                task.status === "completed"
                                  ? "text-green-500"
                                  : task.status === "in_progress"
                                    ? "text-amber-500"
                                    : "text-muted-foreground",
                              )} />
                            </div>
                            <div>
                              <p className="font-medium">{task.property}</p>
                              <div className="flex items-center gap-3 text-xs text-muted-foreground mt-0.5">
                                <span className="flex items-center gap-1">
                                  <User className="h-3 w-3" />{task.assignedTo || "Unassigned"}
                                </span>
                                <span>CO: {task.checkoutTime}</span>
                                <span>~{task.estimatedMinutes}min</span>
                              </div>
                            </div>
                          </div>
                          <div className="flex items-center gap-2">
                            {hasDamage && (
                              <Badge variant="outline" className="text-[10px] text-red-500 border-red-500/30">
                                <AlertTriangle className="h-3 w-3 mr-0.5" />
                                {task.damageFlags.length}
                              </Badge>
                            )}
                            <Badge className={STATUS_COLORS[task.status] ?? STATUS_COLORS["pending"]}>
                              {task.status.replace("_", " ")}
                            </Badge>
                            {taskChecked > 0 && (
                              <span className="text-xs text-muted-foreground tabular-nums">
                                {taskChecked}/{totalChecklistItems}
                              </span>
                            )}
                          </div>
                        </div>
                        {taskChecked > 0 && (
                          <Progress
                            value={Math.round((taskChecked / totalChecklistItems) * 100)}
                            className="mt-3 h-1.5"
                          />
                        )}
                      </CardContent>
                    </Card>
                  );
                })
              )}
            </div>

            {/* Task detail panel */}
            {selectedTask && (
              <Card className="h-fit sticky top-6">
                <CardHeader className="pb-3">
                  <CardTitle className="text-base flex items-center gap-2">
                    <Home className="h-4 w-4" />
                    {selectedTask.property}
                  </CardTitle>
                </CardHeader>
                <CardContent className="space-y-4">
                  {/* Quick stats */}
                  <div className="grid grid-cols-3 gap-2 text-center">
                    <div className="rounded-lg border p-2">
                      <p className="text-lg font-bold">{checkedCount}</p>
                      <p className="text-[10px] text-muted-foreground">Checked</p>
                    </div>
                    <div className="rounded-lg border p-2">
                      <p className="text-lg font-bold">{totalChecklistItems - checkedCount}</p>
                      <p className="text-[10px] text-muted-foreground">Remaining</p>
                    </div>
                    <div className="rounded-lg border p-2">
                      <p className="text-lg font-bold text-red-500">{selectedTask.damageFlags.length}</p>
                      <p className="text-[10px] text-muted-foreground">Damage</p>
                    </div>
                  </div>

                  <Progress value={progressPct} className="h-2" />

                  {/* Assign cleaner */}
                  <div className="flex items-center gap-2">
                    <Label className="text-xs whitespace-nowrap">Cleaner:</Label>
                    <Select
                      value={selectedTask.assignedTo || "Unassigned"}
                      onValueChange={handleAssign}
                    >
                      <SelectTrigger className="h-8 text-xs flex-1">
                        <SelectValue />
                      </SelectTrigger>
                      <SelectContent>
                        <SelectItem value="Unassigned">Unassigned</SelectItem>
                        <SelectItem value="Cleaning Team A">Cleaning Team A</SelectItem>
                        <SelectItem value="Cleaning Team B">Cleaning Team B</SelectItem>
                        <SelectItem value="Maria">Maria</SelectItem>
                        <SelectItem value="Juan">Juan</SelectItem>
                      </SelectContent>
                    </Select>
                  </div>

                  <Separator />

                  {/* Room zone summary */}
                  <div className="space-y-1.5">
                    <p className="text-xs font-medium text-muted-foreground">Room Zones</p>
                    {ROOM_ZONES.map((z) => {
                      const zDone = z.items.filter((it) => selectedTask.checkedItems[it.id]).length;
                      const zTotal = z.items.length;
                      const complete = zDone === zTotal;
                      const hasDmg = z.items.some((it) => selectedTask.damageFlags.includes(it.id));
                      return (
                        <div
                          key={z.id}
                          className={cn(
                            "flex items-center justify-between text-xs p-1.5 rounded",
                            complete ? "text-green-600 bg-green-500/5" : "text-muted-foreground",
                            hasDmg && "ring-1 ring-red-500/30",
                          )}
                        >
                          <span className="flex items-center gap-1.5">
                            {z.icon}
                            {z.name}
                          </span>
                          <span className="tabular-nums">{zDone}/{zTotal}</span>
                        </div>
                      );
                    })}
                  </div>

                  <Separator />

                  {/* Actions */}
                  {(selectedTask.status === "pending" || selectedTask.status === "scheduled") && (
                    <Button className="w-full" onClick={startCleaning}>
                      <PlayCircle className="mr-2 h-4 w-4" />
                      Start Walk the Wall
                    </Button>
                  )}
                  {selectedTask.status === "in_progress" && (
                    <Button className="w-full" onClick={() => { setWalkMode(true); setCurrentZone(0); }}>
                      <Shield className="mr-2 h-4 w-4" />
                      Resume Walk the Wall
                    </Button>
                  )}
                  {selectedTask.status === "completed" && (
                    <div className="text-center py-2">
                      <CheckCircle className="h-8 w-8 text-green-500 mx-auto mb-1" />
                      <p className="text-sm font-medium text-green-600">Turnover Complete</p>
                      {selectedTask.damageFlags.length > 0 && (
                        <p className="text-xs text-red-500 mt-1">
                          {selectedTask.damageFlags.length} damage flag(s) — file claim in Damage Claims
                        </p>
                      )}
                    </div>
                  )}
                </CardContent>
              </Card>
            )}
          </div>
        </TabsContent>

        <TabsContent value="week" className="mt-4">
          <Card>
            <CardHeader>
              <CardTitle>Upcoming Turnovers</CardTitle>
            </CardHeader>
            <CardContent>
              {Array.isArray(weekData) && weekData.length > 0 ? (
                <div className="space-y-2">
                  {(weekData as Array<{ date: string; property: string; status: string; assigned_to?: string }>).map((t, i) => (
                    <div key={i} className="flex items-center justify-between border-b py-2.5 last:border-0">
                      <div className="flex items-center gap-3">
                        <CalendarDays className="h-4 w-4 text-muted-foreground" />
                        <div>
                          <p className="text-sm font-medium">{t.property}</p>
                          <p className="text-xs text-muted-foreground">{t.date} {t.assigned_to ? `— ${t.assigned_to}` : ""}</p>
                        </div>
                      </div>
                      <Badge variant="outline">{t.status}</Badge>
                    </div>
                  ))}
                </div>
              ) : (
                <div className="text-center py-8 text-muted-foreground">
                  <CalendarDays className="h-10 w-10 mx-auto mb-3 opacity-30" />
                  <p className="text-sm">Week-ahead schedule will populate from departing reservations</p>
                  <Button
                    variant="outline"
                    className="mt-3"
                    onClick={() => autoSchedule.mutate()}
                    disabled={autoSchedule.isPending}
                  >
                    <Zap className="mr-2 h-4 w-4" />Auto-Schedule
                  </Button>
                </div>
              )}
            </CardContent>
          </Card>
        </TabsContent>
      </Tabs>
    </div>
  );
}

function TimerDisplay({ startedAt, estimated }: { startedAt: number; estimated: number }) {
  const [elapsed, setElapsed] = useState(0);

  useEffect(() => {
    const iv = setInterval(() => {
      setElapsed(Math.floor((Date.now() - startedAt) / 60000));
    }, 30000);
    setElapsed(Math.floor((Date.now() - startedAt) / 60000));
    return () => clearInterval(iv);
  }, [startedAt]);

  const overTime = elapsed > estimated;

  return (
    <div className={cn(
      "flex items-center gap-1.5 rounded-full px-3 py-1 text-xs font-medium",
      overTime ? "bg-red-500/10 text-red-600" : "bg-primary/10 text-primary",
    )}>
      <Timer className="h-3.5 w-3.5" />
      {elapsed}min / {estimated}min
    </div>
  );
}
