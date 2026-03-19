"use client";

import { use } from "react";
import { useQuery } from "@tanstack/react-query";
import { api } from "@/lib/api";
import {
  Card,
  CardContent,
  CardHeader,
  CardTitle,
} from "@/components/ui/card";
import { Badge } from "@/components/ui/badge";
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/tabs";
import {
  Mountain,
  Wifi,
  Key,
  Car,
  Bed,
  Users,
  Calendar,
  BookOpen,
  ShoppingBag,
  AlertTriangle,
} from "lucide-react";

interface PortalData {
  reservation: {
    confirmation_code: string;
    check_in: string;
    check_out: string;
    num_guests: number;
    status: string;
  };
  guest: { first_name: string; last_name: string };
  property: {
    name: string;
    bedrooms: number;
    bathrooms: number;
    max_guests: number;
    address?: string;
    wifi?: { ssid: string; password: string };
    access?: { type: string; location: string; code: string };
    parking?: string;
  };
  phase: string;
  guides: Array<{ title: string; content: string; category: string }>;
  extras: Array<{ id: string; name: string; description: string; price: number; category: string }>;
}

export default function GuestPortalPage({ params }: { params: Promise<{ code: string }> }) {
  const { code } = use(params);

  const { data: portal, isLoading, error } = useQuery<PortalData>({
    queryKey: ["guest-portal", code],
    queryFn: () => api.get(`/api/guest-portal/${code}`),
  });

  if (isLoading) {
    return (
      <div className="min-h-screen flex items-center justify-center">
        <p className="text-muted-foreground">Loading your portal...</p>
      </div>
    );
  }

  if (error || !portal) {
    return (
      <div className="min-h-screen flex items-center justify-center">
        <Card className="max-w-sm text-center">
          <CardContent className="py-12">
            <AlertTriangle className="h-12 w-12 mx-auto mb-4 text-muted-foreground" />
            <p className="font-semibold">Reservation not found</p>
            <p className="text-sm text-muted-foreground mt-2">
              Please check your confirmation code and try again.
            </p>
          </CardContent>
        </Card>
      </div>
    );
  }

  const { reservation, guest, property, phase, guides, extras } = portal;

  const phaseLabels: Record<string, string> = {
    pre_arrival: "Before Your Arrival",
    during_stay: "During Your Stay",
    post_checkout: "After Checkout",
  };

  return (
    <div className="min-h-screen bg-background">
      <header className="border-b bg-card">
        <div className="mx-auto max-w-3xl px-6 py-4 flex items-center justify-between">
          <div className="flex items-center gap-3">
            <Mountain className="h-6 w-6 text-primary" />
            <span className="font-bold text-sm">Cabin Rentals of Georgia</span>
          </div>
          <Badge variant="outline">{reservation.confirmation_code}</Badge>
        </div>
      </header>

      <main className="mx-auto max-w-3xl px-6 py-8 space-y-6">
        <div>
          <h1 className="text-2xl font-bold">
            Welcome, {guest.first_name}!
          </h1>
          <p className="text-muted-foreground">
            {property.name} &middot; {phaseLabels[phase]}
          </p>
        </div>

        {/* Reservation Overview */}
        <Card>
          <CardContent className="p-4">
            <div className="grid grid-cols-2 gap-4 md:grid-cols-4">
              <div className="flex items-center gap-2">
                <Calendar className="h-4 w-4 text-primary" />
                <div>
                  <p className="text-xs text-muted-foreground">Check-in</p>
                  <p className="text-sm font-medium">{reservation.check_in}</p>
                </div>
              </div>
              <div className="flex items-center gap-2">
                <Calendar className="h-4 w-4 text-primary" />
                <div>
                  <p className="text-xs text-muted-foreground">Check-out</p>
                  <p className="text-sm font-medium">{reservation.check_out}</p>
                </div>
              </div>
              <div className="flex items-center gap-2">
                <Users className="h-4 w-4 text-primary" />
                <div>
                  <p className="text-xs text-muted-foreground">Guests</p>
                  <p className="text-sm font-medium">{reservation.num_guests}</p>
                </div>
              </div>
              <div className="flex items-center gap-2">
                <Bed className="h-4 w-4 text-primary" />
                <div>
                  <p className="text-xs text-muted-foreground">Property</p>
                  <p className="text-sm font-medium">{property.bedrooms}BR / {property.bathrooms}BA</p>
                </div>
              </div>
            </div>
          </CardContent>
        </Card>

        {/* Access Info (only during stay) */}
        {property.wifi && (
          <div className="grid gap-4 md:grid-cols-3">
            <Card>
              <CardHeader className="pb-2">
                <CardTitle className="text-sm flex items-center gap-2">
                  <Wifi className="h-4 w-4 text-blue-500" /> WiFi
                </CardTitle>
              </CardHeader>
              <CardContent>
                <p className="text-sm"><strong>Network:</strong> {property.wifi.ssid}</p>
                <p className="text-sm"><strong>Password:</strong> {property.wifi.password}</p>
              </CardContent>
            </Card>
            {property.access && (
              <Card>
                <CardHeader className="pb-2">
                  <CardTitle className="text-sm flex items-center gap-2">
                    <Key className="h-4 w-4 text-green-500" /> Access
                  </CardTitle>
                </CardHeader>
                <CardContent>
                  <p className="text-sm"><strong>Type:</strong> {property.access.type}</p>
                  {property.access.code && <p className="text-sm"><strong>Code:</strong> {property.access.code}</p>}
                  <p className="text-sm text-muted-foreground">{property.access.location}</p>
                </CardContent>
              </Card>
            )}
            {property.parking && (
              <Card>
                <CardHeader className="pb-2">
                  <CardTitle className="text-sm flex items-center gap-2">
                    <Car className="h-4 w-4 text-orange-500" /> Parking
                  </CardTitle>
                </CardHeader>
                <CardContent>
                  <p className="text-sm">{property.parking}</p>
                </CardContent>
              </Card>
            )}
          </div>
        )}

        <Tabs defaultValue="guides">
          <TabsList>
            <TabsTrigger value="guides">
              <BookOpen className="h-4 w-4 mr-1" /> Guide
            </TabsTrigger>
            <TabsTrigger value="extras">
              <ShoppingBag className="h-4 w-4 mr-1" /> Extras
            </TabsTrigger>
          </TabsList>

          <TabsContent value="guides" className="mt-4 space-y-4">
            {guides.length === 0 ? (
              <Card><CardContent className="py-8 text-center text-muted-foreground">No guides available</CardContent></Card>
            ) : (
              guides.map((g, i) => (
                <Card key={i}>
                  <CardHeader className="pb-2">
                    <div className="flex items-center justify-between">
                      <CardTitle className="text-sm">{g.title}</CardTitle>
                      <Badge variant="outline" className="text-[10px]">{g.category}</Badge>
                    </div>
                  </CardHeader>
                  <CardContent>
                    <p className="text-sm text-muted-foreground whitespace-pre-wrap">{g.content}</p>
                  </CardContent>
                </Card>
              ))
            )}
          </TabsContent>

          <TabsContent value="extras" className="mt-4">
            {extras.length === 0 ? (
              <Card><CardContent className="py-8 text-center text-muted-foreground">No extras available</CardContent></Card>
            ) : (
              <div className="grid gap-4 md:grid-cols-2">
                {extras.map((e) => (
                  <Card key={e.id}>
                    <CardHeader className="pb-2">
                      <div className="flex items-center justify-between">
                        <CardTitle className="text-sm">{e.name}</CardTitle>
                        <Badge>${e.price}</Badge>
                      </div>
                    </CardHeader>
                    <CardContent>
                      <p className="text-sm text-muted-foreground">{e.description}</p>
                    </CardContent>
                  </Card>
                ))}
              </div>
            )}
          </TabsContent>
        </Tabs>
      </main>
    </div>
  );
}
