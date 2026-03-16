"use client";

import { useState } from "react";
import { useProperties, useGuestbooks } from "@/lib/hooks";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Textarea } from "@/components/ui/textarea";
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/tabs";
import { Separator } from "@/components/ui/separator";
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
  BookOpen,
  Plus,
  QrCode,
  ExternalLink,
  Wifi,
  KeyRound,
  Car,
  MapPin,
  Utensils,
  Mountain,
  Phone,
  FileText,
  Link2,
  Copy,
  Eye,
} from "lucide-react";
import { QRCodeSVG } from "qrcode.react";
import { toast } from "sonner";
import { CardGridSkeleton } from "@/components/skeletons";

interface GuestbookSection {
  id: string;
  title: string;
  icon: React.ReactNode;
  content: string;
}

export default function GuestbooksPage() {
  const { data: properties, isLoading: propsLoading } = useProperties();
  const { data: guestbooks } = useGuestbooks();
  const [selectedProperty, setSelectedProperty] = useState<string>("");
  const [editorOpen, setEditorOpen] = useState(false);
  const [qrOpen, setQrOpen] = useState(false);
  const [sections, setSections] = useState<GuestbookSection[]>([
    { id: "welcome", title: "Welcome Message", icon: <BookOpen className="h-4 w-4" />, content: "Welcome to {property_name}! We're thrilled to have you as our guest." },
    { id: "house_rules", title: "House Rules", icon: <FileText className="h-4 w-4" />, content: "• Quiet hours: 10 PM - 8 AM\n• No smoking inside\n• Max occupancy as booked\n• Pets must be approved in advance" },
    { id: "wifi", title: "WiFi & Access", icon: <Wifi className="h-4 w-4" />, content: "WiFi: {wifi_ssid}\nPassword: {wifi_password}" },
    { id: "access", title: "Check-in Instructions", icon: <KeyRound className="h-4 w-4" />, content: "Your door code will be sent 24 hours before check-in.\n{access_code_location}" },
    { id: "parking", title: "Parking", icon: <Car className="h-4 w-4" />, content: "{parking_instructions}" },
    { id: "area_guide", title: "Area Guide", icon: <MapPin className="h-4 w-4" />, content: "Explore the beautiful North Georgia mountains! Popular nearby attractions include..." },
    { id: "dining", title: "Dining & Restaurants", icon: <Utensils className="h-4 w-4" />, content: "• Local Favorite Restaurant - 10 min drive\n• Mountain View Cafe - 5 min drive\n• Pizza Delivery - (706) 555-0123" },
    { id: "activities", title: "Activities & Adventures", icon: <Mountain className="h-4 w-4" />, content: "• Hiking trails (Blue Ridge area)\n• Tubing on the river\n• Zip-lining nearby\n• Horseback riding" },
    { id: "emergency", title: "Emergency Info", icon: <Phone className="h-4 w-4" />, content: "Emergency: 911\nProperty Manager: (706) 471-1479\nNearest Hospital: Blue Ridge Medical Center" },
  ]);
  const [activeSection, setActiveSection] = useState("welcome");

  const selectedProp = properties?.find((p) => p.id === selectedProperty);
  const guestbookUrl = selectedProp
    ? `${typeof window !== "undefined" ? window.location.origin : ""}/guest/${selectedProp.slug}`
    : "";

  function updateSection(id: string, content: string) {
    setSections((prev) => prev.map((s) => (s.id === id ? { ...s, content } : s)));
  }

  function copyLink() {
    navigator.clipboard.writeText(guestbookUrl);
    toast.success("Guestbook link copied to clipboard");
  }

  if (propsLoading) return <CardGridSkeleton />;

  return (
    <div className="space-y-6">
      <div className="flex items-center justify-between">
        <div>
          <h1 className="text-2xl font-bold tracking-tight">Digital Guestbooks</h1>
          <p className="text-muted-foreground">
            Create beautiful guides for your properties — like Ruebarue, but built in
          </p>
        </div>
      </div>

      {/* Property selector */}
      <div className="flex items-center gap-4">
        <Select value={selectedProperty} onValueChange={setSelectedProperty}>
          <SelectTrigger className="w-72">
            <SelectValue placeholder="Select a property..." />
          </SelectTrigger>
          <SelectContent>
            {(properties ?? []).filter((p) => p.is_active).map((p) => (
              <SelectItem key={p.id} value={p.id}>{p.name}</SelectItem>
            ))}
          </SelectContent>
        </Select>
        {selectedProperty && (
          <div className="flex items-center gap-2">
            <Button variant="outline" size="sm" onClick={copyLink}>
              <Copy className="mr-2 h-4 w-4" />
              Copy Link
            </Button>
            <Button variant="outline" size="sm" onClick={() => setQrOpen(true)}>
              <QrCode className="mr-2 h-4 w-4" />
              QR Code
            </Button>
            {guestbookUrl && (
              <Button variant="outline" size="sm" asChild>
                <a href={guestbookUrl} target="_blank" rel="noopener noreferrer">
                  <Eye className="mr-2 h-4 w-4" />
                  Preview
                </a>
              </Button>
            )}
          </div>
        )}
      </div>

      {!selectedProperty ? (
        <Card>
          <CardContent className="py-16 text-center">
            <BookOpen className="h-16 w-16 mx-auto mb-4 text-muted-foreground/30" />
            <p className="text-lg font-medium">Select a property to edit its guestbook</p>
            <p className="text-sm text-muted-foreground mt-1">
              Each property gets a unique digital guide with a shareable link and QR code
            </p>
          </CardContent>
        </Card>
      ) : (
        <div className="grid gap-6 lg:grid-cols-[280px_1fr]">
          {/* Section list */}
          <Card className="h-fit">
            <CardHeader className="pb-3">
              <CardTitle className="text-sm">Sections</CardTitle>
            </CardHeader>
            <CardContent className="p-0">
              {sections.map((s) => (
                <button
                  key={s.id}
                  onClick={() => setActiveSection(s.id)}
                  className={`w-full flex items-center gap-2.5 px-4 py-2.5 text-sm transition-colors border-l-2 ${
                    activeSection === s.id
                      ? "bg-accent border-l-primary font-medium"
                      : "border-l-transparent text-muted-foreground hover:bg-accent/50"
                  }`}
                >
                  {s.icon}
                  {s.title}
                </button>
              ))}
            </CardContent>
          </Card>

          {/* Editor */}
          <Card>
            <CardHeader>
              <CardTitle className="text-base flex items-center gap-2">
                {sections.find((s) => s.id === activeSection)?.icon}
                {sections.find((s) => s.id === activeSection)?.title}
              </CardTitle>
            </CardHeader>
            <CardContent className="space-y-4">
              <Textarea
                value={sections.find((s) => s.id === activeSection)?.content ?? ""}
                onChange={(e) => updateSection(activeSection, e.target.value)}
                rows={10}
                className="font-mono text-sm"
              />
              <div className="flex items-center gap-2 text-xs text-muted-foreground">
                <span>Variables:</span>
                {["{property_name}", "{wifi_ssid}", "{wifi_password}", "{access_code_location}", "{parking_instructions}", "{guest_name}", "{check_in_date}"].map((v) => (
                  <Badge key={v} variant="outline" className="font-mono text-[10px] cursor-pointer hover:bg-accent"
                    onClick={() => {
                      const section = sections.find((s) => s.id === activeSection);
                      if (section) updateSection(activeSection, section.content + " " + v);
                    }}
                  >
                    {v}
                  </Badge>
                ))}
              </div>
              <Separator />
              {/* Live preview */}
              <div>
                <p className="text-sm font-medium mb-2">Preview</p>
                <div className="rounded-lg border p-4 bg-background min-h-[100px]">
                  <p className="text-sm whitespace-pre-wrap">
                    {(sections.find((s) => s.id === activeSection)?.content ?? "")
                      .replace(/\{property_name\}/g, selectedProp?.name ?? "Property")
                      .replace(/\{wifi_ssid\}/g, selectedProp?.wifi_ssid ?? "—")
                      .replace(/\{wifi_password\}/g, selectedProp?.wifi_password ?? "—")
                      .replace(/\{access_code_location\}/g, selectedProp?.access_code_location ?? "—")
                      .replace(/\{parking_instructions\}/g, selectedProp?.parking_instructions ?? "—")
                      .replace(/\{guest_name\}/g, "Guest")
                      .replace(/\{check_in_date\}/g, "2026-02-20")}
                  </p>
                </div>
              </div>
              <Button onClick={() => toast.success("Guestbook saved")} className="w-full">
                Save Guestbook
              </Button>
            </CardContent>
          </Card>
        </div>
      )}

      {/* QR Code Modal */}
      <Sheet open={qrOpen} onOpenChange={setQrOpen}>
        <SheetContent className="w-[400px]">
          <SheetHeader>
            <SheetTitle>QR Code — {selectedProp?.name}</SheetTitle>
          </SheetHeader>
          <div className="mt-6 flex flex-col items-center gap-4">
            {guestbookUrl && (
              <div className="bg-white p-6 rounded-xl">
                <QRCodeSVG value={guestbookUrl} size={200} />
              </div>
            )}
            <p className="text-sm text-muted-foreground text-center">
              Print this QR code and place it at the property.
              Guests scan to access the digital guestbook instantly.
            </p>
            <div className="flex items-center gap-2 w-full">
              <Input value={guestbookUrl} readOnly className="text-xs" />
              <Button size="sm" variant="outline" onClick={copyLink}>
                <Copy className="h-4 w-4" />
              </Button>
            </div>
          </div>
        </SheetContent>
      </Sheet>
    </div>
  );
}
