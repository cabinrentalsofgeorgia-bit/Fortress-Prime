"use client";

import { useState } from "react";
import {
  Card,
  CardContent,
  CardDescription,
  CardHeader,
  CardTitle,
} from "@/components/ui/card";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Switch } from "@/components/ui/switch";
import { Label } from "@/components/ui/label";
import { Separator } from "@/components/ui/separator";
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/tabs";
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
  DialogFooter,
} from "@/components/ui/dialog";
import {
  Users,
  Plug,
  Shield,
  Bell,
  Palette,
  CheckCircle,
  XCircle,
  RefreshCw,
  Trash2,
  Loader2,
  KeyRound,
  Mail,
  MailCheck,
  Clock,
  Ban,
  Send,
  RotateCw,
} from "lucide-react";
import {
  useStreamlineStatus,
  useChannelStatus,
  useStaffUsers,
  useDeactivateUser,
  useResetUserPassword,
  useInvites,
  useSendInvite,
  useResendInvite,
  useRevokeInvite,
} from "@/lib/hooks";
import { RoleGatedAction } from "@/components/access/role-gated-action";
import { useAppStore } from "@/lib/store";
import { canManageStaff } from "@/lib/roles";
import { toast } from "sonner";

const FEATURE_FLAGS = [
  { id: "ai_responses", label: "AI Responses", desc: "Enable AI-generated responses to guest messages", default: true },
  { id: "auto_replies", label: "Auto Replies", desc: "Automatically send AI responses above confidence threshold", default: false },
  { id: "sentiment", label: "Sentiment Analysis", desc: "Analyze guest message sentiment in real-time", default: true },
  { id: "predictive", label: "Predictive Analytics", desc: "Revenue forecasting and demand prediction", default: false },
  { id: "multi_lang", label: "Multi-Language", desc: "Auto-translate guest messages", default: false },
  { id: "damage_claims", label: "AI Damage Claims", desc: "Auto-generate damage claim letters with legal drafting", default: false },
  { id: "iot_monitoring", label: "IoT Monitoring", desc: "Smart lock, thermostat, and noise monitor integration", default: false },
];

const NOTIFICATION_PREFS = [
  { id: "urgent", label: "Urgent Issues", desc: "Emergency, broken, not working — immediate alert", default: true },
  { id: "work_orders", label: "Work Orders", desc: "New work orders created from guest messages", default: true },
  { id: "checkin", label: "Check-in Alerts", desc: "When guests check in to a property", default: false },
  { id: "checkout", label: "Check-out Alerts", desc: "When guests check out", default: false },
  { id: "reviews", label: "New Reviews", desc: "When guests leave reviews", default: true },
  { id: "ai_escalation", label: "AI Escalation", desc: "When AI confidence is too low and needs human review", default: true },
];

export default function SettingsPage() {
  const user = useAppStore((state) => state.user);
  const canAdminSettings = canManageStaff(user);
  const { data: streamline, isLoading: streamlineLoading } = useStreamlineStatus();
  useChannelStatus();
  const [features, setFeatures] = useState<Record<string, boolean>>(
    Object.fromEntries(FEATURE_FLAGS.map((f) => [f.id, f.default])),
  );
  const [notifications, setNotifications] = useState<Record<string, boolean>>(
    Object.fromEntries(NOTIFICATION_PREFS.map((n) => [n.id, n.default])),
  );
  const [companyName, setCompanyName] = useState("Cabin Rentals of Georgia");
  const [primaryColor, setPrimaryColor] = useState("#2563eb");

  // Staff management
  const { data: staffUsers, isLoading: staffLoading } = useStaffUsers();
  const { data: invites, isLoading: invitesLoading } = useInvites();
  const deactivateUser = useDeactivateUser();
  const resetPassword = useResetUserPassword();
  const sendInvite = useSendInvite();
  const resendInvite = useResendInvite();
  const revokeInvite = useRevokeInvite();
  const [inviteOpen, setInviteOpen] = useState(false);
  const [resetPwUser, setResetPwUser] = useState<{ id: string; name: string } | null>(null);
  const [resetPw, setResetPw] = useState("");
  const [resetPwConfirm, setResetPwConfirm] = useState("");
  const [inviteForm, setInviteForm] = useState({
    first_name: "",
    last_name: "",
    email: "",
    role: "reviewer",
  });

  function toggleFeature(id: string, checked: boolean) {
    setFeatures((prev) => ({ ...prev, [id]: checked }));
    toast.success("Feature flag updated");
  }

  function toggleNotification(id: string, checked: boolean) {
    setNotifications((prev) => ({ ...prev, [id]: checked }));
    toast.success("Notification preference updated");
  }

  const streamlineConnected = !!streamline && !streamlineLoading;

  return (
    <div className="space-y-6">
      <div>
        <h1 className="text-2xl font-bold tracking-tight">Settings</h1>
        <p className="text-muted-foreground">
          Platform configuration and management
        </p>
        {!canAdminSettings ? (
          <Badge variant="outline" className="mt-2 text-xs">
            View-only role
          </Badge>
        ) : null}
      </div>

      <Tabs defaultValue="integrations">
        <TabsList>
          <TabsTrigger value="integrations">Integrations</TabsTrigger>
          <TabsTrigger value="staff">Staff</TabsTrigger>
          <TabsTrigger value="features">Features</TabsTrigger>
          <TabsTrigger value="notifications">Notifications</TabsTrigger>
          <TabsTrigger value="branding">Branding</TabsTrigger>
        </TabsList>

        {/* Integrations */}
        <TabsContent value="integrations" className="mt-4 space-y-4">
          {[
            {
              name: "Streamline VRS",
              desc: "Property management system — syncs properties, reservations, and guests",
              connected: streamlineConnected,
              loading: streamlineLoading,
              detail: streamlineConnected
                ? `${String((streamline as Record<string, unknown>)?.total_properties ?? "")} properties synced`
                : "Not connected",
            },
            {
              name: "Twilio SMS",
              desc: "Guest messaging via SMS — send, receive, and automate",
              connected: true,
              loading: false,
              detail: "+1 (706) 471-1479 · Delivery tracking active",
            },
            {
              name: "AI Engine (Ollama)",
              desc: "Local LLM inference — data sovereignty, no cloud dependency",
              connected: true,
              loading: false,
              detail: "qwen2.5:7b (fast) · deepseek-r1:70b (deep think)",
            },
            {
              name: "QuickBooks Online",
              desc: "Financial reconciliation — P&L, Balance Sheet, Trial Balance",
              connected: true,
              loading: false,
              detail: "Read-only financial sync",
              badge: "Read-Only",
            },
            {
              name: "Stripe Payments",
              desc: "Direct booking payments and extras purchasing",
              connected: false,
              loading: false,
              detail: "Configure API keys to enable direct payments",
            },
          ].map((int) => (
            <Card key={int.name}>
              <CardHeader>
                <CardTitle className="flex items-center gap-2">
                  <Plug className="h-5 w-5" />
                  {int.name}
                </CardTitle>
                <CardDescription>{int.desc}</CardDescription>
              </CardHeader>
              <CardContent>
                <div className="flex items-center justify-between">
                  <div className="flex items-center gap-3">
                    {int.loading ? (
                      <Badge variant="secondary" className="flex items-center gap-1">
                        <RefreshCw className="h-3 w-3 animate-spin" />
                        Checking...
                      </Badge>
                    ) : int.connected ? (
                      <Badge variant="default" className="bg-green-600 flex items-center gap-1">
                        <CheckCircle className="h-3 w-3" />
                        {int.badge ?? "Connected"}
                      </Badge>
                    ) : (
                      <Badge variant="secondary" className="flex items-center gap-1">
                        <XCircle className="h-3 w-3" />
                        Disconnected
                      </Badge>
                    )}
                    <span className="text-sm text-muted-foreground">{int.detail}</span>
                  </div>
                  <Button variant="outline" size="sm">
                    {int.connected ? "Configure" : "Connect"}
                  </Button>
                </div>
              </CardContent>
            </Card>
          ))}
        </TabsContent>

        {/* Staff */}
        <TabsContent value="staff" className="mt-4 space-y-4">
          {/* Active Users */}
          <Card>
            <CardHeader>
              <div className="flex items-center justify-between">
                <div>
                  <CardTitle className="flex items-center gap-2">
                    <Users className="h-5 w-5" />
                    Active Users
                  </CardTitle>
                  <CardDescription>Manage team members with platform access</CardDescription>
                </div>
                <RoleGatedAction allowed={canAdminSettings} reason="Admin role required.">
                  <Button size="sm" onClick={() => setInviteOpen(true)} disabled={!canAdminSettings}>
                    <Send className="mr-2 h-4 w-4" />
                    Invite User
                  </Button>
                </RoleGatedAction>
              </div>
            </CardHeader>
            <CardContent>
              {staffLoading ? (
                <div className="flex justify-center py-6">
                  <Loader2 className="h-6 w-6 animate-spin text-muted-foreground" />
                </div>
              ) : (
                <div className="space-y-3">
                  {staffUsers?.map((s) => (
                    <div key={s.id} className="flex items-center justify-between rounded-lg border p-3">
                      <div className="flex items-center gap-3">
                        <div className="h-8 w-8 rounded-full bg-primary/10 flex items-center justify-center text-xs font-medium">
                          {s.first_name?.[0]}{s.last_name?.[0]}
                        </div>
                        <div>
                          <p className="text-sm font-medium">{s.first_name} {s.last_name}</p>
                          <p className="text-xs text-muted-foreground">{s.email}</p>
                        </div>
                      </div>
                      <div className="flex items-center gap-2">
                        <Badge variant="outline" className="text-xs capitalize">{s.role}</Badge>
                        <Badge variant={s.is_active ? "default" : "secondary"} className="text-xs">
                          {s.is_active ? "Active" : "Inactive"}
                        </Badge>
                        {s.last_login_at && (
                          <span className="text-[10px] text-muted-foreground hidden lg:inline">
                            Last: {new Date(s.last_login_at).toLocaleDateString()}
                          </span>
                        )}
                        {s.is_active && (
                          <>
                            <RoleGatedAction allowed={canAdminSettings} reason="Admin role required.">
                              <Button variant="ghost" size="icon" className="h-7 w-7 text-muted-foreground hover:text-primary" title="Reset password" disabled={!canAdminSettings} onClick={() => { setResetPwUser({ id: s.id, name: `${s.first_name} ${s.last_name}` }); setResetPw(""); setResetPwConfirm(""); }}>
                                <KeyRound className="h-3.5 w-3.5" />
                              </Button>
                            </RoleGatedAction>
                            <RoleGatedAction allowed={canAdminSettings} reason="Admin role required.">
                              <Button variant="ghost" size="icon" className="h-7 w-7 text-muted-foreground hover:text-destructive" title="Deactivate" disabled={!canAdminSettings} onClick={() => { if (confirm(`Deactivate ${s.first_name} ${s.last_name}?`)) deactivateUser.mutate(s.id); }}>
                                <Trash2 className="h-3.5 w-3.5" />
                              </Button>
                            </RoleGatedAction>
                          </>
                        )}
                      </div>
                    </div>
                  ))}
                  {(!staffUsers || staffUsers.length === 0) && (
                    <p className="text-sm text-muted-foreground text-center py-4">No active users</p>
                  )}
                </div>
              )}
            </CardContent>
          </Card>

          {/* Pending Invitations */}
          <Card>
            <CardHeader>
              <CardTitle className="flex items-center gap-2">
                <Mail className="h-5 w-5" />
                Invitations
              </CardTitle>
              <CardDescription>Track pending, accepted, and expired invitations</CardDescription>
            </CardHeader>
            <CardContent>
              {invitesLoading ? (
                <div className="flex justify-center py-6">
                  <Loader2 className="h-6 w-6 animate-spin text-muted-foreground" />
                </div>
              ) : !invites || invites.length === 0 ? (
                <p className="text-sm text-muted-foreground text-center py-4">
                  No invitations sent yet. Click &ldquo;Invite User&rdquo; to get started.
                </p>
              ) : (
                <div className="space-y-3">
                  {invites.map((inv) => (
                    <div key={inv.id} className="flex items-center justify-between rounded-lg border p-3">
                      <div className="flex items-center gap-3">
                        <div className="h-8 w-8 rounded-full flex items-center justify-center text-xs font-medium" style={{ background: inv.status === "pending" ? "hsl(var(--primary) / 0.1)" : inv.status === "accepted" ? "hsl(142 76% 36% / 0.1)" : "hsl(var(--muted))" }}>
                          {inv.status === "pending" && <Clock className="h-4 w-4 text-primary" />}
                          {inv.status === "accepted" && <MailCheck className="h-4 w-4 text-green-600" />}
                          {inv.status === "expired" && <XCircle className="h-4 w-4 text-muted-foreground" />}
                          {inv.status === "revoked" && <Ban className="h-4 w-4 text-muted-foreground" />}
                        </div>
                        <div>
                          <p className="text-sm font-medium">{inv.first_name} {inv.last_name}</p>
                          <p className="text-xs text-muted-foreground">{inv.email}</p>
                        </div>
                      </div>
                      <div className="flex items-center gap-2">
                        <Badge variant="outline" className="text-xs capitalize">{inv.role}</Badge>
                        <Badge
                          variant={inv.status === "accepted" ? "default" : inv.status === "pending" ? "secondary" : "outline"}
                          className={`text-xs capitalize ${inv.status === "accepted" ? "bg-green-600" : ""}`}
                        >
                          {inv.status}
                        </Badge>
                        {inv.status === "pending" && (
                          <>
                            <RoleGatedAction allowed={canAdminSettings} reason="Admin role required.">
                              <Button variant="ghost" size="icon" className="h-7 w-7 text-muted-foreground hover:text-primary" title="Resend invite" disabled={!canAdminSettings} onClick={() => resendInvite.mutate(inv.id)}>
                                <RotateCw className="h-3.5 w-3.5" />
                              </Button>
                            </RoleGatedAction>
                            <RoleGatedAction allowed={canAdminSettings} reason="Admin role required.">
                              <Button variant="ghost" size="icon" className="h-7 w-7 text-muted-foreground hover:text-destructive" title="Revoke invite" disabled={!canAdminSettings} onClick={() => { if (confirm(`Revoke invitation for ${inv.first_name}?`)) revokeInvite.mutate(inv.id); }}>
                                <Ban className="h-3.5 w-3.5" />
                              </Button>
                            </RoleGatedAction>
                          </>
                        )}
                        {inv.expires_at && inv.status === "pending" && (
                          <span className="text-[10px] text-muted-foreground hidden lg:inline">
                            Exp: {new Date(inv.expires_at).toLocaleDateString()}
                          </span>
                        )}
                      </div>
                    </div>
                  ))}
                </div>
              )}
            </CardContent>
          </Card>

          {/* Reset Password Dialog */}
          <Dialog open={!!resetPwUser} onOpenChange={(open) => { if (!open) setResetPwUser(null); }}>
            <DialogContent>
              <DialogHeader>
                <DialogTitle>Reset Password — {resetPwUser?.name}</DialogTitle>
              </DialogHeader>
              <form className="space-y-4" onSubmit={(e) => { e.preventDefault(); if (resetPw.length < 8) { toast.error("Password must be at least 8 characters"); return; } if (resetPw !== resetPwConfirm) { toast.error("Passwords do not match"); return; } if (!resetPwUser) return; resetPassword.mutate({ userId: resetPwUser.id, new_password: resetPw }, { onSuccess: () => setResetPwUser(null) }); }}>
                <div className="space-y-2">
                  <Label htmlFor="rp-new">New Password</Label>
                  <Input id="rp-new" type="password" placeholder="Minimum 8 characters" value={resetPw} onChange={(e) => setResetPw(e.target.value)} required minLength={8} />
                </div>
                <div className="space-y-2">
                  <Label htmlFor="rp-confirm">Confirm Password</Label>
                  <Input id="rp-confirm" type="password" placeholder="Re-enter password" value={resetPwConfirm} onChange={(e) => setResetPwConfirm(e.target.value)} required minLength={8} />
                </div>
                <DialogFooter className="gap-2">
                  <Button type="button" variant="outline" onClick={() => setResetPwUser(null)}>Cancel</Button>
                  <Button type="submit" disabled={resetPassword.isPending}>
                    {resetPassword.isPending ? <><Loader2 className="mr-2 h-4 w-4 animate-spin" />Resetting...</> : "Reset Password"}
                  </Button>
                </DialogFooter>
              </form>
            </DialogContent>
          </Dialog>

          {/* Send Invite Dialog */}
          <Dialog open={inviteOpen} onOpenChange={setInviteOpen}>
            <DialogContent>
              <DialogHeader>
                <DialogTitle>Invite a Team Member</DialogTitle>
              </DialogHeader>
              <p className="text-sm text-muted-foreground">
                They&apos;ll receive an email with a secure link to create their account and set their own password.
              </p>
              <form className="space-y-4" onSubmit={(e) => { e.preventDefault(); if (!inviteForm.first_name || !inviteForm.last_name || !inviteForm.email) { toast.error("All fields are required"); return; } sendInvite.mutate(inviteForm, { onSuccess: () => { setInviteOpen(false); setInviteForm({ first_name: "", last_name: "", email: "", role: "reviewer" }); } }); }}>
                <div className="grid grid-cols-2 gap-3">
                  <div className="space-y-2">
                    <Label htmlFor="inv-first">First Name</Label>
                    <Input id="inv-first" placeholder="Jane" value={inviteForm.first_name} onChange={(e) => setInviteForm((p) => ({ ...p, first_name: e.target.value }))} required />
                  </div>
                  <div className="space-y-2">
                    <Label htmlFor="inv-last">Last Name</Label>
                    <Input id="inv-last" placeholder="Doe" value={inviteForm.last_name} onChange={(e) => setInviteForm((p) => ({ ...p, last_name: e.target.value }))} required />
                  </div>
                </div>
                <div className="space-y-2">
                  <Label htmlFor="inv-email">Email Address</Label>
                  <Input id="inv-email" type="email" placeholder="jane@example.com" value={inviteForm.email} onChange={(e) => setInviteForm((p) => ({ ...p, email: e.target.value }))} required />
                </div>
                <div className="space-y-2">
                  <Label htmlFor="inv-role">Role</Label>
                  <Select value={inviteForm.role} onValueChange={(val) => setInviteForm((p) => ({ ...p, role: val }))}>
                    <SelectTrigger id="inv-role"><SelectValue /></SelectTrigger>
                    <SelectContent>
                      <SelectItem value="manager">Manager</SelectItem>
                      <SelectItem value="reviewer">Reviewer</SelectItem>
                    </SelectContent>
                  </Select>
                </div>
                <DialogFooter className="gap-2">
                  <Button type="button" variant="outline" onClick={() => setInviteOpen(false)}>Cancel</Button>
                  <Button type="submit" disabled={!canAdminSettings || sendInvite.isPending}>
                    {sendInvite.isPending ? <><Loader2 className="mr-2 h-4 w-4 animate-spin" />Sending...</> : <><Send className="mr-2 h-4 w-4" />Send Invitation</>}
                  </Button>
                </DialogFooter>
              </form>
            </DialogContent>
          </Dialog>
        </TabsContent>

        {/* Feature Flags */}
        <TabsContent value="features" className="mt-4">
          <Card>
            <CardHeader>
              <CardTitle className="flex items-center gap-2">
                <Shield className="h-5 w-5" />
                Feature Flags
              </CardTitle>
              <CardDescription>
                Toggle platform capabilities. Changes take effect immediately.
              </CardDescription>
            </CardHeader>
            <CardContent className="space-y-4">
              {FEATURE_FLAGS.map((f) => (
                <div key={f.id} className="flex items-center justify-between">
                  <div className="flex-1">
                    <Label htmlFor={f.id} className="text-sm font-medium">{f.label}</Label>
                    <p className="text-xs text-muted-foreground">{f.desc}</p>
                  </div>
                  <Switch
                    id={f.id}
                    checked={features[f.id] ?? false}
                    onCheckedChange={(checked) => toggleFeature(f.id, checked)}
                  />
                </div>
              ))}
            </CardContent>
          </Card>
        </TabsContent>

        {/* Notifications */}
        <TabsContent value="notifications" className="mt-4">
          <Card>
            <CardHeader>
              <CardTitle className="flex items-center gap-2">
                <Bell className="h-5 w-5" />
                Notification Preferences
              </CardTitle>
              <CardDescription>
                Control which events trigger notifications
              </CardDescription>
            </CardHeader>
            <CardContent className="space-y-4">
              {NOTIFICATION_PREFS.map((n) => (
                <div key={n.id} className="flex items-center justify-between">
                  <div className="flex-1">
                    <Label htmlFor={n.id} className="text-sm font-medium">{n.label}</Label>
                    <p className="text-xs text-muted-foreground">{n.desc}</p>
                  </div>
                  <Switch
                    id={n.id}
                    checked={notifications[n.id] ?? false}
                    onCheckedChange={(checked) => toggleNotification(n.id, checked)}
                  />
                </div>
              ))}
            </CardContent>
          </Card>
        </TabsContent>

        {/* Branding */}
        <TabsContent value="branding" className="mt-4 space-y-4">
          <Card>
            <CardHeader>
              <CardTitle className="flex items-center gap-2">
                <Palette className="h-5 w-5" />
                Branding
              </CardTitle>
              <CardDescription>
                Customize how your platform appears to guests
              </CardDescription>
            </CardHeader>
            <CardContent className="space-y-4">
              <div className="space-y-2">
                <Label>Company Name</Label>
                <Input
                  value={companyName}
                  onChange={(e) => setCompanyName(e.target.value)}
                />
              </div>
              <div className="space-y-2">
                <Label>Primary Color</Label>
                <div className="flex items-center gap-3">
                  <input
                    type="color"
                    value={primaryColor}
                    onChange={(e) => setPrimaryColor(e.target.value)}
                    className="h-10 w-14 rounded border cursor-pointer"
                  />
                  <Input
                    value={primaryColor}
                    onChange={(e) => setPrimaryColor(e.target.value)}
                    className="w-32 font-mono"
                  />
                  <div
                    className="h-10 flex-1 rounded-lg flex items-center justify-center text-white text-sm font-medium"
                    style={{ backgroundColor: primaryColor }}
                  >
                    Preview
                  </div>
                </div>
              </div>
              <Separator />
              <Button onClick={() => toast.success("Branding settings saved")}>
                Save Branding
              </Button>
            </CardContent>
          </Card>
        </TabsContent>
      </Tabs>
    </div>
  );
}
