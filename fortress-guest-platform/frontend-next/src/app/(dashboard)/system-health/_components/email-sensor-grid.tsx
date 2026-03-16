"use client";

import { useCallback, useEffect, useState } from "react";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Switch } from "@/components/ui/switch";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import {
  Dialog,
  DialogContent,
  DialogHeader,
  DialogTitle,
  DialogTrigger,
} from "@/components/ui/dialog";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@/components/ui/table";
import { Mail, Plus, Radio, ShieldCheck } from "lucide-react";

interface Sensor {
  id: string;
  email_address: string;
  display_name: string | null;
  protocol: string;
  server_address: string;
  server_port: number;
  use_ssl: boolean;
  is_active: boolean;
  last_sweep_at: string | null;
  last_sweep_status: string;
  last_sweep_error: string | null;
  emails_ingested_total: number;
}

function relativeTime(iso: string | null): string {
  if (!iso) return "Never";
  const diff = Date.now() - new Date(iso).getTime();
  const mins = Math.floor(diff / 60_000);
  if (mins < 1) return "Just now";
  if (mins < 60) return `${mins}m ago`;
  const hrs = Math.floor(mins / 60);
  if (hrs < 24) return `${hrs}h ago`;
  return `${Math.floor(hrs / 24)}d ago`;
}

function StatusDot({ status }: { status: string }) {
  const color =
    status === "green"
      ? "bg-emerald-500"
      : status === "red"
        ? "bg-red-500"
        : "bg-amber-400";
  const pulse = status === "green" ? "animate-pulse" : "";
  return (
    <span className="relative flex h-2.5 w-2.5">
      {status === "green" && (
        <span className={`absolute inline-flex h-full w-full rounded-full ${color} opacity-50 ${pulse}`} />
      )}
      <span className={`relative inline-flex rounded-full h-2.5 w-2.5 ${color}`} />
    </span>
  );
}

export function EmailSensorGrid() {
  const [sensors, setSensors] = useState<Sensor[]>([]);
  const [loading, setLoading] = useState(true);
  const [addOpen, setAddOpen] = useState(false);
  const [submitting, setSubmitting] = useState(false);

  const [newEmail, setNewEmail] = useState("");
  const [newDisplay, setNewDisplay] = useState("");
  const [newProtocol, setNewProtocol] = useState("pop3");
  const [newServer, setNewServer] = useState("mail.cabin-rentals-of-georgia.com");
  const [newPort, setNewPort] = useState("995");
  const [newPassword, setNewPassword] = useState("");

  const fetchSensors = useCallback(async () => {
    try {
      const res = await fetch("/api/system/sensors");
      if (res.ok) {
        const data = await res.json();
        if (Array.isArray(data)) setSensors(data);
      }
    } catch {
      /* silent retry */
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    fetchSensors();
    const interval = setInterval(fetchSensors, 30_000);
    return () => clearInterval(interval);
  }, [fetchSensors]);

  const handleToggle = async (sensor: Sensor) => {
    try {
      await fetch("/api/system/sensors", {
        method: "PATCH",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          sensor_id: sensor.id,
          is_active: !sensor.is_active,
        }),
      });
      await fetchSensors();
    } catch {
      /* toast would go here */
    }
  };

  const handleAdd = async () => {
    if (!newEmail || !newPassword) return;
    setSubmitting(true);
    try {
      const res = await fetch("/api/system/sensors", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          email_address: newEmail,
          display_name: newDisplay || undefined,
          protocol: newProtocol,
          server_address: newServer,
          server_port: parseInt(newPort, 10) || 995,
          password: newPassword,
        }),
      });
      if (res.ok) {
        setAddOpen(false);
        setNewEmail("");
        setNewDisplay("");
        setNewPassword("");
        setNewProtocol("pop3");
        setNewServer("mail.cabin-rentals-of-georgia.com");
        setNewPort("995");
        await fetchSensors();
      }
    } catch {
      /* toast would go here */
    } finally {
      setSubmitting(false);
    }
  };

  const activeCount = sensors.filter((s) => s.is_active).length;
  const greenCount = sensors.filter(
    (s) => s.is_active && s.last_sweep_status === "green",
  ).length;
  const totalIngested = sensors.reduce(
    (sum, s) => sum + (s.emails_ingested_total ?? 0),
    0,
  );

  return (
    <Card>
      <CardHeader className="flex flex-row items-center justify-between pb-3">
        <div className="flex items-center gap-2">
          <ShieldCheck className="h-5 w-5 text-emerald-500" />
          <CardTitle className="text-sm font-semibold">Iron Dome &mdash; Email Sensor Grid</CardTitle>
          <Badge variant="outline" className="text-[10px] ml-2">
            {greenCount}/{activeCount} online
          </Badge>
          <span className="text-[10px] text-muted-foreground ml-2">
            {totalIngested.toLocaleString()} total ingested
          </span>
        </div>
        <Dialog open={addOpen} onOpenChange={setAddOpen}>
          <DialogTrigger asChild>
            <Button size="sm" variant="outline" className="gap-1">
              <Plus className="h-3.5 w-3.5" />
              Add Sensor
            </Button>
          </DialogTrigger>
          <DialogContent className="sm:max-w-md">
            <DialogHeader>
              <DialogTitle>Add Email Sensor</DialogTitle>
            </DialogHeader>
            <div className="grid gap-4 py-2">
              <div className="grid gap-2">
                <Label htmlFor="sensor-email">Email Address</Label>
                <Input
                  id="sensor-email"
                  placeholder="user@company.com"
                  value={newEmail}
                  onChange={(e) => setNewEmail(e.target.value)}
                />
              </div>
              <div className="grid gap-2">
                <Label htmlFor="sensor-display">Display Name (optional)</Label>
                <Input
                  id="sensor-display"
                  placeholder="e.g. Info Inbox"
                  value={newDisplay}
                  onChange={(e) => setNewDisplay(e.target.value)}
                />
              </div>
              <div className="grid grid-cols-2 gap-4">
                <div className="grid gap-2">
                  <Label>Protocol</Label>
                  <Select value={newProtocol} onValueChange={(v) => {
                    setNewProtocol(v);
                    if (v === "imap") { setNewPort("993"); setNewServer("imap.gmail.com"); }
                    else { setNewPort("995"); setNewServer("mail.cabin-rentals-of-georgia.com"); }
                  }}>
                    <SelectTrigger><SelectValue /></SelectTrigger>
                    <SelectContent>
                      <SelectItem value="pop3">POP3</SelectItem>
                      <SelectItem value="imap">IMAP</SelectItem>
                    </SelectContent>
                  </Select>
                </div>
                <div className="grid gap-2">
                  <Label htmlFor="sensor-port">Port</Label>
                  <Input id="sensor-port" value={newPort} onChange={(e) => setNewPort(e.target.value)} />
                </div>
              </div>
              <div className="grid gap-2">
                <Label htmlFor="sensor-server">Server</Label>
                <Input
                  id="sensor-server"
                  value={newServer}
                  onChange={(e) => setNewServer(e.target.value)}
                />
              </div>
              <div className="grid gap-2">
                <Label htmlFor="sensor-pw">Password</Label>
                <Input
                  id="sensor-pw"
                  type="password"
                  placeholder="App password or account password"
                  value={newPassword}
                  onChange={(e) => setNewPassword(e.target.value)}
                />
              </div>
              <Button onClick={handleAdd} disabled={submitting || !newEmail || !newPassword}>
                {submitting ? "Encrypting & Saving..." : "Add Sensor"}
              </Button>
            </div>
          </DialogContent>
        </Dialog>
      </CardHeader>
      <CardContent className="px-0 pb-0">
        {loading ? (
          <div className="py-8 text-center text-sm text-muted-foreground">Loading sensors...</div>
        ) : sensors.length === 0 ? (
          <div className="py-8 text-center text-sm text-muted-foreground">No sensors configured</div>
        ) : (
          <Table>
            <TableHeader>
              <TableRow>
                <TableHead className="w-8" />
                <TableHead>Mailbox</TableHead>
                <TableHead>Protocol</TableHead>
                <TableHead>Server</TableHead>
                <TableHead>Last Synced</TableHead>
                <TableHead className="text-right">Ingested</TableHead>
                <TableHead className="text-center">Active</TableHead>
              </TableRow>
            </TableHeader>
            <TableBody>
              {sensors.map((s) => (
                <TableRow key={s.id} className={!s.is_active ? "opacity-40" : undefined}>
                  <TableCell>
                    <StatusDot status={s.is_active ? s.last_sweep_status : "pending"} />
                  </TableCell>
                  <TableCell>
                    <div className="flex items-center gap-2">
                      <Mail className="h-3.5 w-3.5 text-muted-foreground" />
                      <div>
                        <p className="text-sm font-medium leading-none">{s.email_address}</p>
                        {s.display_name && (
                          <p className="text-[10px] text-muted-foreground">{s.display_name}</p>
                        )}
                      </div>
                    </div>
                  </TableCell>
                  <TableCell>
                    <Badge variant="secondary" className="text-[10px] uppercase">
                      {s.protocol}
                    </Badge>
                  </TableCell>
                  <TableCell className="text-xs text-muted-foreground">
                    {s.server_address}:{s.server_port}
                  </TableCell>
                  <TableCell>
                    <span className="text-xs">{relativeTime(s.last_sweep_at)}</span>
                    {s.last_sweep_error && s.last_sweep_status === "red" && (
                      <p className="text-[10px] text-red-400 truncate max-w-[180px]">{s.last_sweep_error}</p>
                    )}
                  </TableCell>
                  <TableCell className="text-right tabular-nums text-sm">
                    {(s.emails_ingested_total ?? 0).toLocaleString()}
                  </TableCell>
                  <TableCell className="text-center">
                    <Switch
                      checked={s.is_active}
                      onCheckedChange={() => handleToggle(s)}
                      aria-label={`Toggle ${s.email_address}`}
                    />
                  </TableCell>
                </TableRow>
              ))}
            </TableBody>
          </Table>
        )}
      </CardContent>
    </Card>
  );
}
