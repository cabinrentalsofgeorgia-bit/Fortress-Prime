"use client";

import { useParams, useRouter } from "next/navigation";
import { useState } from "react";
import {
  useProperty, useUpdateProperty, useReservations, useWorkOrders,
  usePropertyUtilities, useServiceTypes, useCreateUtility, useUpdateUtility,
  useDeleteUtility, useAddReading, useUtilityCostAnalytics,
} from "@/lib/hooks";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/tabs";
import { Separator } from "@/components/ui/separator";
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@/components/ui/table";
import {
  Sheet,
  SheetContent,
  SheetHeader,
  SheetTitle,
  SheetTrigger,
} from "@/components/ui/sheet";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import { Textarea } from "@/components/ui/textarea";
import { Progress } from "@/components/ui/progress";
import { Dialog, DialogContent, DialogHeader, DialogTitle, DialogTrigger } from "@/components/ui/dialog";
import {
  ArrowLeft,
  Home,
  Bed,
  Bath,
  Users,
  Wifi,
  KeyRound,
  Car,
  CalendarDays,
  Wrench,
  Pencil,
  DollarSign,
  TrendingUp,
  BookOpen,
  Plug,
  Droplets,
  Flame,
  Globe,
  Eye,
  EyeOff,
  Plus,
  Trash2,
  Zap,
} from "lucide-react";
import { DetailSkeleton } from "@/components/skeletons";
import { toast } from "sonner";

export default function PropertyDetailPage() {
  const { id } = useParams<{ id: string }>();
  const router = useRouter();
  const { data: property, isLoading } = useProperty(id);
  const { data: allReservations } = useReservations();
  const { data: workOrders } = useWorkOrders({ property_id: id });
  const updateProperty = useUpdateProperty();
  const [editOpen, setEditOpen] = useState(false);

  // Utilities
  const { data: utilities } = usePropertyUtilities(id);
  const { data: serviceTypes } = useServiceTypes();
  const createUtility = useCreateUtility();
  const updateUtility = useUpdateUtility();
  const deleteUtility = useDeleteUtility();
  const addReading = useAddReading();
  const [addServiceOpen, setAddServiceOpen] = useState(false);
  const [addReadingFor, setAddReadingFor] = useState<string | null>(null);
  const [costPeriod, setCostPeriod] = useState("mtd");
  const { data: costAnalytics } = useUtilityCostAnalytics(id, costPeriod);
  const [revealedPasswords, setRevealedPasswords] = useState<Record<string, string>>({});

  const propReservations = (allReservations ?? [])
    .filter((r) => r.property_id === id)
    .sort((a, b) => new Date(b.check_in_date).getTime() - new Date(a.check_in_date).getTime());

  const upcoming = propReservations.filter((r) => new Date(r.check_in_date) >= new Date() && r.status !== "cancelled");
  const revenueMtd = propReservations
    .filter((r) => {
      const d = new Date(r.check_in_date);
      const now = new Date();
      return d.getMonth() === now.getMonth() && d.getFullYear() === now.getFullYear();
    })
    .reduce((s, r) => s + (r.total_amount ?? 0), 0);

  const occupiedNights = propReservations.filter(
    (r) => r.status === "checked_in" || r.status === "confirmed",
  ).length;

  if (isLoading) return <DetailSkeleton />;
  if (!property) {
    return (
      <div className="text-center py-12 text-muted-foreground">
        <p>Property not found</p>
        <Button variant="link" onClick={() => router.push("/properties")}>Back to Properties</Button>
      </div>
    );
  }

  function handleSaveEdit(e: React.FormEvent<HTMLFormElement>) {
    e.preventDefault();
    const form = new FormData(e.currentTarget);
    const data: Record<string, unknown> = {};
    for (const [k, v] of form.entries()) {
      if (k === "bedrooms" || k === "bathrooms" || k === "max_guests") {
        data[k] = Number(v);
      } else {
        data[k] = v;
      }
    }
    updateProperty.mutate(
      { id, ...data } as Parameters<typeof updateProperty.mutate>[0],
      { onSuccess: () => setEditOpen(false) },
    );
  }

  return (
    <div className="space-y-6">
      <Button variant="ghost" size="sm" onClick={() => router.push("/properties")}>
        <ArrowLeft className="mr-2 h-4 w-4" />
        Back to Properties
      </Button>

      {/* Hero header */}
      <div className="flex items-start justify-between">
        <div className="flex items-center gap-4">
          <div className="h-16 w-16 rounded-xl bg-primary/10 flex items-center justify-center">
            <Home className="h-8 w-8 text-primary" />
          </div>
          <div>
            <div className="flex items-center gap-2">
              <h1 className="text-2xl font-bold">{property.name}</h1>
              <Badge variant={property.is_active ? "default" : "secondary"}>
                {property.is_active ? "Active" : "Inactive"}
              </Badge>
            </div>
            <p className="text-muted-foreground flex items-center gap-3 mt-1">
              <span className="flex items-center gap-1"><Bed className="h-4 w-4" />{property.bedrooms} BR</span>
              <span className="flex items-center gap-1"><Bath className="h-4 w-4" />{property.bathrooms} BA</span>
              <span className="flex items-center gap-1"><Users className="h-4 w-4" />Sleeps {property.max_guests}</span>
              {property.property_type && <Badge variant="outline">{property.property_type}</Badge>}
            </p>
          </div>
        </div>

        <Sheet open={editOpen} onOpenChange={setEditOpen}>
          <SheetTrigger asChild>
            <Button variant="outline" size="sm">
              <Pencil className="mr-2 h-4 w-4" />
              Edit
            </Button>
          </SheetTrigger>
          <SheetContent className="w-[400px] overflow-y-auto">
            <SheetHeader>
              <SheetTitle>Edit Property</SheetTitle>
            </SheetHeader>
            <form onSubmit={handleSaveEdit} className="mt-6 space-y-4">
              <div className="space-y-2">
                <Label>Name</Label>
                <Input name="name" defaultValue={property.name} />
              </div>
              <div className="grid grid-cols-3 gap-3">
                <div className="space-y-2">
                  <Label>Bedrooms</Label>
                  <Input name="bedrooms" type="number" defaultValue={property.bedrooms} />
                </div>
                <div className="space-y-2">
                  <Label>Bathrooms</Label>
                  <Input name="bathrooms" type="number" defaultValue={property.bathrooms} />
                </div>
                <div className="space-y-2">
                  <Label>Max Guests</Label>
                  <Input name="max_guests" type="number" defaultValue={property.max_guests} />
                </div>
              </div>
              <Separator />
              <div className="space-y-2">
                <Label>WiFi SSID</Label>
                <Input name="wifi_ssid" defaultValue={property.wifi_ssid ?? ""} />
              </div>
              <div className="space-y-2">
                <Label>WiFi Password</Label>
                <Input name="wifi_password" defaultValue={property.wifi_password ?? ""} />
              </div>
              <div className="space-y-2">
                <Label>Access Code Location</Label>
                <Input name="access_code_location" defaultValue={property.access_code_location ?? ""} />
              </div>
              <div className="space-y-2">
                <Label>Parking Instructions</Label>
                <Input name="parking_instructions" defaultValue={property.parking_instructions ?? ""} />
              </div>
              <Button type="submit" className="w-full" disabled={updateProperty.isPending}>
                {updateProperty.isPending ? "Saving..." : "Save Changes"}
              </Button>
            </form>
          </SheetContent>
        </Sheet>
      </div>

      {/* Stats */}
      <div className="grid gap-4 md:grid-cols-4">
        <Card>
          <CardContent className="pt-4 flex items-center gap-3">
            <DollarSign className="h-8 w-8 text-green-500" />
            <div>
              <p className="text-2xl font-bold">${revenueMtd.toLocaleString()}</p>
              <p className="text-xs text-muted-foreground">Revenue MTD</p>
            </div>
          </CardContent>
        </Card>
        <Card>
          <CardContent className="pt-4 flex items-center gap-3">
            <CalendarDays className="h-8 w-8 text-blue-500" />
            <div>
              <p className="text-2xl font-bold">{upcoming.length}</p>
              <p className="text-xs text-muted-foreground">Upcoming Reservations</p>
            </div>
          </CardContent>
        </Card>
        <Card>
          <CardContent className="pt-4 flex items-center gap-3">
            <Wrench className="h-8 w-8 text-orange-500" />
            <div>
              <p className="text-2xl font-bold">{(workOrders ?? []).filter((w) => w.status === "open" || w.status === "in_progress").length}</p>
              <p className="text-xs text-muted-foreground">Open Work Orders</p>
            </div>
          </CardContent>
        </Card>
        <Card>
          <CardContent className="pt-4 flex items-center gap-3">
            <TrendingUp className="h-8 w-8 text-emerald-500" />
            <div>
              <p className="text-2xl font-bold">{propReservations.length}</p>
              <p className="text-xs text-muted-foreground">Total Reservations</p>
            </div>
          </CardContent>
        </Card>
      </div>

      {/* Property info cards */}
      <div className="grid gap-4 md:grid-cols-3">
        {property.wifi_ssid && (
          <Card>
            <CardContent className="pt-4">
              <div className="flex items-center gap-2 text-sm">
                <Wifi className="h-4 w-4 text-muted-foreground" />
                <span className="text-muted-foreground">WiFi:</span>
                <span className="font-mono font-medium">{property.wifi_ssid}</span>
              </div>
              {property.wifi_password && (
                <p className="text-xs text-muted-foreground mt-1 font-mono">
                  Password: {property.wifi_password}
                </p>
              )}
            </CardContent>
          </Card>
        )}
        {property.access_code_location && (
          <Card>
            <CardContent className="pt-4">
              <div className="flex items-center gap-2 text-sm">
                <KeyRound className="h-4 w-4 text-muted-foreground" />
                <span className="text-muted-foreground">Access:</span>
                <span className="font-medium">{property.access_code_location}</span>
              </div>
            </CardContent>
          </Card>
        )}
        {property.parking_instructions && (
          <Card>
            <CardContent className="pt-4">
              <div className="flex items-center gap-2 text-sm">
                <Car className="h-4 w-4 text-muted-foreground" />
                <span className="text-muted-foreground">Parking:</span>
                <span className="font-medium">{property.parking_instructions}</span>
              </div>
            </CardContent>
          </Card>
        )}
      </div>

      {/* Tabs */}
      <Tabs defaultValue="reservations">
        <TabsList>
          <TabsTrigger value="reservations">
            Reservations
            <Badge variant="secondary" className="ml-1.5 text-[10px]">{propReservations.length}</Badge>
          </TabsTrigger>
          <TabsTrigger value="work-orders">
            Work Orders
            <Badge variant="secondary" className="ml-1.5 text-[10px]">{(workOrders ?? []).length}</Badge>
          </TabsTrigger>
          <TabsTrigger value="utilities">
            Utilities & Services
            <Badge variant="secondary" className="ml-1.5 text-[10px]">{(utilities ?? []).length}</Badge>
          </TabsTrigger>
        </TabsList>

        <TabsContent value="reservations" className="mt-4">
          <Card>
            <CardContent className="p-0">
              <Table>
                <TableHeader>
                  <TableRow>
                    <TableHead>Code</TableHead>
                    <TableHead>Guest</TableHead>
                    <TableHead>Check-in</TableHead>
                    <TableHead>Check-out</TableHead>
                    <TableHead>Guests</TableHead>
                    <TableHead>Status</TableHead>
                    <TableHead className="text-right">Amount</TableHead>
                  </TableRow>
                </TableHeader>
                <TableBody>
                  {propReservations.length === 0 ? (
                    <TableRow>
                      <TableCell colSpan={7} className="text-center py-8 text-muted-foreground">
                        No reservations
                      </TableCell>
                    </TableRow>
                  ) : (
                    propReservations.slice(0, 30).map((r) => (
                      <TableRow key={r.id}>
                        <TableCell className="font-mono text-xs">{r.confirmation_code}</TableCell>
                        <TableCell className="text-sm">{r.guest_name ?? "—"}</TableCell>
                        <TableCell className="text-sm">{r.check_in_date}</TableCell>
                        <TableCell className="text-sm">{r.check_out_date}</TableCell>
                        <TableCell className="text-sm">{r.num_guests}</TableCell>
                        <TableCell>
                          <Badge variant={
                            r.status === "checked_in" ? "default" :
                            r.status === "cancelled" ? "destructive" : "outline"
                          } className="text-xs">
                            {r.status.replace("_", " ")}
                          </Badge>
                        </TableCell>
                        <TableCell className="text-right text-sm">
                          {r.total_amount ? `$${r.total_amount.toLocaleString()}` : "—"}
                        </TableCell>
                      </TableRow>
                    ))
                  )}
                </TableBody>
              </Table>
            </CardContent>
          </Card>
        </TabsContent>

        <TabsContent value="work-orders" className="mt-4">
          <Card>
            <CardContent className="p-0">
              <Table>
                <TableHeader>
                  <TableRow>
                    <TableHead>Ticket</TableHead>
                    <TableHead>Title</TableHead>
                    <TableHead>Priority</TableHead>
                    <TableHead>Status</TableHead>
                    <TableHead>Created</TableHead>
                  </TableRow>
                </TableHeader>
                <TableBody>
                  {(workOrders ?? []).length === 0 ? (
                    <TableRow>
                      <TableCell colSpan={5} className="text-center py-8 text-muted-foreground">
                        No work orders
                      </TableCell>
                    </TableRow>
                  ) : (
                    (workOrders ?? []).map((wo) => (
                      <TableRow key={wo.id}>
                        <TableCell className="font-mono text-xs">{wo.ticket_number}</TableCell>
                        <TableCell className="text-sm font-medium">{wo.title}</TableCell>
                        <TableCell>
                          <Badge variant={wo.priority === "urgent" ? "destructive" : wo.priority === "high" ? "default" : "outline"} className="text-xs">
                            {wo.priority}
                          </Badge>
                        </TableCell>
                        <TableCell>
                          <Badge variant="outline" className="text-xs">{wo.status.replace("_", " ")}</Badge>
                        </TableCell>
                        <TableCell className="text-xs text-muted-foreground">
                          {new Date(wo.created_at).toLocaleDateString()}
                        </TableCell>
                      </TableRow>
                    ))
                  )}
                </TableBody>
              </Table>
            </CardContent>
          </Card>
        </TabsContent>

        {/* ── Utilities & Services Tab ── */}
        <TabsContent value="utilities" className="mt-4 space-y-6">
          {/* Cost Analytics Summary */}
          <div className="flex items-center justify-between">
            <h3 className="text-lg font-semibold flex items-center gap-2">
              <Zap className="h-5 w-5 text-yellow-500" />
              Utility Cost Analytics
            </h3>
            <div className="flex gap-2">
              <Select value={costPeriod} onValueChange={setCostPeriod}>
                <SelectTrigger className="w-[140px] h-8 text-xs">
                  <SelectValue />
                </SelectTrigger>
                <SelectContent>
                  <SelectItem value="mtd">Month to Date</SelectItem>
                  <SelectItem value="ytd">Year to Date</SelectItem>
                  <SelectItem value="last30">Last 30 Days</SelectItem>
                  <SelectItem value="last90">Last 90 Days</SelectItem>
                  <SelectItem value="last365">Last Year</SelectItem>
                </SelectContent>
              </Select>
              <Dialog open={addServiceOpen} onOpenChange={setAddServiceOpen}>
                <DialogTrigger asChild>
                  <Button size="sm">
                    <Plus className="h-4 w-4 mr-1" />
                    Add Service
                  </Button>
                </DialogTrigger>
                <DialogContent className="max-w-lg max-h-[90vh] overflow-y-auto">
                  <DialogHeader>
                    <DialogTitle>Add Utility / Service Account</DialogTitle>
                  </DialogHeader>
                  <form
                    className="space-y-4 mt-2"
                    onSubmit={(e) => {
                      e.preventDefault();
                      const fd = new FormData(e.currentTarget);
                      createUtility.mutate({
                        property_id: id,
                        service_type: fd.get("service_type") as string,
                        provider_name: fd.get("provider_name") as string,
                        account_number: fd.get("account_number") as string || undefined,
                        account_holder: fd.get("account_holder") as string || undefined,
                        portal_url: fd.get("portal_url") as string || undefined,
                        portal_username: fd.get("portal_username") as string || undefined,
                        portal_password: fd.get("portal_password") as string || undefined,
                        contact_phone: fd.get("contact_phone") as string || undefined,
                        contact_email: fd.get("contact_email") as string || undefined,
                        monthly_budget: fd.get("monthly_budget") ? Number(fd.get("monthly_budget")) : undefined,
                        notes: fd.get("notes") as string || undefined,
                      }, { onSuccess: () => setAddServiceOpen(false) });
                    }}
                  >
                    <div className="grid grid-cols-2 gap-3">
                      <div className="space-y-1.5">
                        <Label>Service Type</Label>
                        <Select name="service_type" required>
                          <SelectTrigger><SelectValue placeholder="Select..." /></SelectTrigger>
                          <SelectContent>
                            {(serviceTypes ?? []).map((t) => (
                              <SelectItem key={t} value={t}>{t.replace("_", " ").replace(/\b\w/g, (c) => c.toUpperCase())}</SelectItem>
                            ))}
                          </SelectContent>
                        </Select>
                      </div>
                      <div className="space-y-1.5">
                        <Label>Provider Name</Label>
                        <Input name="provider_name" placeholder="Comcast, TDS, GA Power..." required />
                      </div>
                    </div>
                    <div className="grid grid-cols-2 gap-3">
                      <div className="space-y-1.5">
                        <Label>Account Number</Label>
                        <Input name="account_number" placeholder="Account #" />
                      </div>
                      <div className="space-y-1.5">
                        <Label>Account Holder</Label>
                        <Input name="account_holder" placeholder="Gary Knight" />
                      </div>
                    </div>
                    <Separator />
                    <p className="text-xs text-muted-foreground font-medium">Portal Credentials (encrypted at rest)</p>
                    <div className="space-y-1.5">
                      <Label>Portal URL</Label>
                      <Input name="portal_url" placeholder="https://login.comcast.net" />
                    </div>
                    <div className="grid grid-cols-2 gap-3">
                      <div className="space-y-1.5">
                        <Label>Username</Label>
                        <Input name="portal_username" />
                      </div>
                      <div className="space-y-1.5">
                        <Label>Password</Label>
                        <Input name="portal_password" type="password" />
                      </div>
                    </div>
                    <Separator />
                    <div className="grid grid-cols-2 gap-3">
                      <div className="space-y-1.5">
                        <Label>Contact Phone</Label>
                        <Input name="contact_phone" placeholder="1-800-..." />
                      </div>
                      <div className="space-y-1.5">
                        <Label>Contact Email</Label>
                        <Input name="contact_email" type="email" />
                      </div>
                    </div>
                    <div className="space-y-1.5">
                      <Label>Monthly Budget</Label>
                      <Input name="monthly_budget" type="number" step="0.01" placeholder="150.00" />
                    </div>
                    <div className="space-y-1.5">
                      <Label>Notes</Label>
                      <Textarea name="notes" rows={2} placeholder="Contract renewal date, special terms..." />
                    </div>
                    <Button type="submit" className="w-full" disabled={createUtility.isPending}>
                      {createUtility.isPending ? "Saving..." : "Add Service Account"}
                    </Button>
                  </form>
                </DialogContent>
              </Dialog>
            </div>
          </div>

          {/* Cost summary cards */}
          {costAnalytics && (
            <div className="grid gap-3 md:grid-cols-4">
              <Card>
                <CardContent className="pt-4 flex items-center gap-3">
                  <DollarSign className="h-8 w-8 text-green-500" />
                  <div>
                    <p className="text-2xl font-bold">${costAnalytics.total.toLocaleString(undefined, { minimumFractionDigits: 2, maximumFractionDigits: 2 })}</p>
                    <p className="text-xs text-muted-foreground">Total ({costPeriod.toUpperCase()})</p>
                  </div>
                </CardContent>
              </Card>
              {Object.entries(costAnalytics.by_service).map(([svc, amt]) => {
                const icons: Record<string, typeof Plug> = { internet: Globe, electric: Zap, water: Droplets, gas: Flame };
                const Icon = icons[svc] || Plug;
                return (
                  <Card key={svc}>
                    <CardContent className="pt-4 flex items-center gap-3">
                      <Icon className="h-6 w-6 text-muted-foreground" />
                      <div>
                        <p className="text-lg font-bold">${(amt as number).toLocaleString(undefined, { minimumFractionDigits: 2, maximumFractionDigits: 2 })}</p>
                        <p className="text-xs text-muted-foreground capitalize">{svc.replace("_", " ")}</p>
                      </div>
                    </CardContent>
                  </Card>
                );
              })}
            </div>
          )}

          {/* Service accounts list */}
          <Card>
            <CardContent className="p-0">
              <Table>
                <TableHeader>
                  <TableRow>
                    <TableHead>Service</TableHead>
                    <TableHead>Provider</TableHead>
                    <TableHead>Account Holder</TableHead>
                    <TableHead>Account #</TableHead>
                    <TableHead>Portal</TableHead>
                    <TableHead className="text-right">MTD Cost</TableHead>
                    <TableHead className="text-right">Budget</TableHead>
                    <TableHead></TableHead>
                  </TableRow>
                </TableHeader>
                <TableBody>
                  {(utilities ?? []).length === 0 ? (
                    <TableRow>
                      <TableCell colSpan={8} className="text-center py-12 text-muted-foreground">
                        <Plug className="h-8 w-8 mx-auto mb-2 opacity-40" />
                        No utility accounts configured. Click &quot;Add Service&quot; to get started.
                      </TableCell>
                    </TableRow>
                  ) : (
                    (utilities ?? []).map((u) => {
                      const icons: Record<string, typeof Plug> = { internet: Globe, electric: Zap, water: Droplets, gas: Flame };
                      const Icon = icons[u.service_type] || Plug;
                      const overBudget = u.monthly_budget && u.total_cost_mtd && u.total_cost_mtd > u.monthly_budget;
                      const budgetPct = u.monthly_budget ? Math.min(((u.total_cost_mtd ?? 0) / u.monthly_budget) * 100, 100) : 0;
                      return (
                        <TableRow key={u.id}>
                          <TableCell>
                            <div className="flex items-center gap-2">
                              <Icon className="h-4 w-4 text-muted-foreground" />
                              <span className="text-sm capitalize font-medium">{u.service_type.replace("_", " ")}</span>
                            </div>
                          </TableCell>
                          <TableCell className="text-sm font-medium">{u.provider_name}</TableCell>
                          <TableCell className="text-sm text-muted-foreground">{u.account_holder ?? "—"}</TableCell>
                          <TableCell className="font-mono text-xs">{u.account_number ?? "—"}</TableCell>
                          <TableCell>
                            {u.portal_url ? (
                              <div className="flex items-center gap-1.5">
                                <a href={u.portal_url} target="_blank" rel="noopener noreferrer" className="text-xs text-blue-500 hover:underline truncate max-w-[120px]">
                                  {u.portal_username ?? "Login"}
                                </a>
                                {u.has_portal_password && (
                                  <Button
                                    variant="ghost"
                                    size="icon"
                                    className="h-5 w-5"
                                    onClick={async () => {
                                      if (revealedPasswords[u.id]) {
                                        setRevealedPasswords((prev) => { const n = { ...prev }; delete n[u.id]; return n; });
                                      } else {
                                        const res = await fetch(`${process.env.NEXT_PUBLIC_API_URL ?? ""}/api/utilities/${u.id}/password`);
                                        const data = await res.json();
                                        if (data.password) setRevealedPasswords((prev) => ({ ...prev, [u.id]: data.password }));
                                      }
                                    }}
                                  >
                                    {revealedPasswords[u.id] ? <EyeOff className="h-3 w-3" /> : <Eye className="h-3 w-3" />}
                                  </Button>
                                )}
                                {revealedPasswords[u.id] && (
                                  <span className="font-mono text-[10px] bg-muted px-1 rounded">{revealedPasswords[u.id]}</span>
                                )}
                              </div>
                            ) : (
                              <span className="text-xs text-muted-foreground">—</span>
                            )}
                          </TableCell>
                          <TableCell className="text-right">
                            <span className={overBudget ? "text-destructive font-bold" : "font-medium"}>
                              ${(u.total_cost_mtd ?? 0).toFixed(2)}
                            </span>
                            {u.monthly_budget ? (
                              <Progress value={budgetPct} className="h-1 mt-1" />
                            ) : null}
                          </TableCell>
                          <TableCell className="text-right text-sm text-muted-foreground">
                            {u.monthly_budget ? `$${u.monthly_budget.toFixed(2)}` : "—"}
                          </TableCell>
                          <TableCell>
                            <div className="flex items-center gap-1">
                              <Dialog open={addReadingFor === u.id} onOpenChange={(open) => setAddReadingFor(open ? u.id : null)}>
                                <DialogTrigger asChild>
                                  <Button variant="ghost" size="icon" className="h-7 w-7" title="Add cost reading">
                                    <DollarSign className="h-3.5 w-3.5" />
                                  </Button>
                                </DialogTrigger>
                                <DialogContent className="max-w-sm">
                                  <DialogHeader>
                                    <DialogTitle>Add Cost Reading — {u.provider_name}</DialogTitle>
                                  </DialogHeader>
                                  <form
                                    className="space-y-3 mt-2"
                                    onSubmit={(e) => {
                                      e.preventDefault();
                                      const fd = new FormData(e.currentTarget);
                                      addReading.mutate({
                                        utilityId: u.id,
                                        reading_date: fd.get("reading_date") as string,
                                        cost: Number(fd.get("cost")),
                                        usage_amount: fd.get("usage_amount") ? Number(fd.get("usage_amount")) : undefined,
                                        usage_unit: fd.get("usage_unit") as string || undefined,
                                        notes: fd.get("notes") as string || undefined,
                                      }, { onSuccess: () => setAddReadingFor(null) });
                                    }}
                                  >
                                    <div className="grid grid-cols-2 gap-3">
                                      <div className="space-y-1.5">
                                        <Label>Date</Label>
                                        <Input name="reading_date" type="date" defaultValue={new Date().toISOString().split("T")[0]} required />
                                      </div>
                                      <div className="space-y-1.5">
                                        <Label>Cost ($)</Label>
                                        <Input name="cost" type="number" step="0.01" placeholder="0.00" required />
                                      </div>
                                    </div>
                                    <div className="grid grid-cols-2 gap-3">
                                      <div className="space-y-1.5">
                                        <Label>Usage Amount</Label>
                                        <Input name="usage_amount" type="number" step="0.01" placeholder="kWh, gallons..." />
                                      </div>
                                      <div className="space-y-1.5">
                                        <Label>Unit</Label>
                                        <Input name="usage_unit" placeholder="kWh, gal, therms" />
                                      </div>
                                    </div>
                                    <div className="space-y-1.5">
                                      <Label>Notes</Label>
                                      <Input name="notes" placeholder="Optional note" />
                                    </div>
                                    <Button type="submit" className="w-full" disabled={addReading.isPending}>
                                      {addReading.isPending ? "Saving..." : "Add Reading"}
                                    </Button>
                                  </form>
                                </DialogContent>
                              </Dialog>
                              <Button
                                variant="ghost"
                                size="icon"
                                className="h-7 w-7 text-destructive/60 hover:text-destructive"
                                onClick={() => { if (confirm("Remove this service account?")) deleteUtility.mutate(u.id); }}
                              >
                                <Trash2 className="h-3.5 w-3.5" />
                              </Button>
                            </div>
                          </TableCell>
                        </TableRow>
                      );
                    })
                  )}
                </TableBody>
              </Table>
            </CardContent>
          </Card>
        </TabsContent>
      </Tabs>
    </div>
  );
}
