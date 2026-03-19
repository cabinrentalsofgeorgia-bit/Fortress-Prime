"use client";

import { useState } from "react";
import { useQuery, useMutation } from "@tanstack/react-query";
import { api } from "@/lib/api";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Textarea } from "@/components/ui/textarea";
import {
  Card,
  CardContent,
  CardDescription,
  CardHeader,
  CardTitle,
} from "@/components/ui/card";
import { Badge } from "@/components/ui/badge";
import { Separator } from "@/components/ui/separator";
import { Mountain, Bed, Bath, Users, Calendar, Check, CreditCard, ArrowRight, Shield, Star, Percent } from "lucide-react";

type AvailabilityResult = {
  check_in: string;
  check_out: string;
  guests: number;
  results: Array<{
    id: string;
    name: string;
    slug: string;
    property_type: string;
    bedrooms: number;
    bathrooms: number;
    max_guests: number;
    pricing: {
      nightly_rate: number;
      nights: number;
      subtotal: number;
      cleaning_fee: number;
      service_fee: number;
      tax: number;
      total: number;
    };
  }>;
};

type BookingResult = {
  reservation_id: string;
  confirmation_code: string;
  total_amount: number;
  payment: { client_secret: string; payment_intent_id: string };
};

export default function BookPage() {
  const [step, setStep] = useState<"search" | "results" | "details" | "confirmed">("search");
  const [checkIn, setCheckIn] = useState("");
  const [checkOut, setCheckOut] = useState("");
  const [guests, setGuests] = useState(2);
  const [selectedProperty, setSelectedProperty] = useState<string>("");
  const [guestInfo, setGuestInfo] = useState({
    first_name: "", last_name: "", email: "", phone: "", requests: "",
  });
  const [confirmation, setConfirmation] = useState<BookingResult | null>(null);

  const availability = useQuery<AvailabilityResult>({
    queryKey: ["availability", checkIn, checkOut, guests],
    queryFn: () => api.get("/api/direct-booking/availability", { check_in: checkIn, check_out: checkOut, guests }),
    enabled: step === "results" && !!checkIn && !!checkOut,
  });

  const bookMutation = useMutation({
    mutationFn: (data: Record<string, unknown>) => api.post<BookingResult>("/api/direct-booking/book", data),
    onSuccess: (data) => {
      setConfirmation(data);
      setStep("confirmed");
    },
  });

  const selected = availability.data?.results.find((p) => p.id === selectedProperty);

  function handleSearch(e: React.FormEvent) {
    e.preventDefault();
    setStep("results");
  }

  function handleBook(e: React.FormEvent) {
    e.preventDefault();
    bookMutation.mutate({
      property_id: selectedProperty,
      check_in: checkIn,
      check_out: checkOut,
      num_guests: guests,
      guest_first_name: guestInfo.first_name,
      guest_last_name: guestInfo.last_name,
      guest_email: guestInfo.email,
      guest_phone: guestInfo.phone,
      special_requests: guestInfo.requests || undefined,
    });
  }

  return (
    <div className="min-h-screen bg-background">
      <header className="border-b bg-card">
        <div className="mx-auto max-w-5xl px-6 py-4 flex items-center gap-3">
          <Mountain className="h-7 w-7 text-primary" />
          <div>
            <h1 className="font-bold">Cabin Rentals of Georgia</h1>
            <p className="text-xs text-muted-foreground">Direct Booking — Best Rate Guaranteed</p>
          </div>
        </div>
      </header>

      <main className="mx-auto max-w-5xl px-6 py-8">
        {step === "search" && (
          <Card className="max-w-xl mx-auto">
            <CardHeader>
              <CardTitle>Find Your Perfect Cabin</CardTitle>
              <CardDescription>Search availability and book direct — save up to 15% vs OTAs</CardDescription>
            </CardHeader>
            <CardContent>
              <form onSubmit={handleSearch} className="space-y-4">
                <div className="grid grid-cols-2 gap-4">
                  <div className="space-y-2">
                    <Label className="flex items-center gap-1.5"><Calendar className="h-3.5 w-3.5" />Check-in</Label>
                    <Input type="date" value={checkIn} onChange={(e) => setCheckIn(e.target.value)} required min={new Date().toISOString().split("T")[0]} />
                  </div>
                  <div className="space-y-2">
                    <Label className="flex items-center gap-1.5"><Calendar className="h-3.5 w-3.5" />Check-out</Label>
                    <Input type="date" value={checkOut} onChange={(e) => setCheckOut(e.target.value)} required min={checkIn || new Date().toISOString().split("T")[0]} />
                  </div>
                </div>
                <div className="space-y-2">
                  <Label className="flex items-center gap-1.5"><Users className="h-3.5 w-3.5" />Guests</Label>
                  <Input type="number" min={1} max={20} value={guests} onChange={(e) => setGuests(Number(e.target.value))} />
                </div>
                <Button type="submit" className="w-full" size="lg">
                  Search Availability
                  <ArrowRight className="ml-2 h-4 w-4" />
                </Button>
                <div className="flex items-center justify-center gap-4 text-xs text-muted-foreground pt-2">
                  <span className="flex items-center gap-1"><Shield className="h-3 w-3" />Secure booking</span>
                  <span className="flex items-center gap-1"><Percent className="h-3 w-3" />Best rate guarantee</span>
                  <span className="flex items-center gap-1"><Star className="h-3 w-3" />No hidden fees</span>
                </div>
              </form>
            </CardContent>
          </Card>
        )}

        {step === "results" && (
          <div className="space-y-6">
            <div className="flex items-center justify-between">
              <div>
                <h2 className="text-xl font-bold">Available Cabins</h2>
                <p className="text-muted-foreground text-sm">
                  {checkIn} to {checkOut} &middot; {guests} guests
                </p>
              </div>
              <Button variant="outline" onClick={() => setStep("search")}>Change Dates</Button>
            </div>
            {availability.isLoading ? (
              <p className="text-muted-foreground">Searching...</p>
            ) : (availability.data?.results ?? []).length === 0 ? (
              <Card>
                <CardContent className="py-12 text-center text-muted-foreground">
                  No cabins available for these dates. Try different dates.
                </CardContent>
              </Card>
            ) : (
              <div className="grid gap-4 md:grid-cols-2">
                {(availability.data?.results ?? []).map((p) => (
                  <Card key={p.id} className="cursor-pointer hover:shadow-lg transition-shadow" onClick={() => { setSelectedProperty(p.id); setStep("details"); }}>
                    <CardHeader className="pb-3">
                      <CardTitle className="text-lg">{p.name}</CardTitle>
                      <div className="flex items-center gap-3 text-sm text-muted-foreground">
                        <span className="flex items-center gap-1"><Bed className="h-3 w-3" />{p.bedrooms}BR</span>
                        <span className="flex items-center gap-1"><Bath className="h-3 w-3" />{p.bathrooms}BA</span>
                        <span className="flex items-center gap-1"><Users className="h-3 w-3" />Sleeps {p.max_guests}</span>
                      </div>
                    </CardHeader>
                    <CardContent>
                      <div className="flex items-center justify-between">
                        <div>
                          <p className="text-2xl font-bold">${p.pricing.nightly_rate}<span className="text-sm text-muted-foreground font-normal">/night</span></p>
                          <p className="text-sm text-muted-foreground">${p.pricing.total} total · {p.pricing.nights} nights</p>
                        </div>
                        <Button>Book Now</Button>
                      </div>
                    </CardContent>
                  </Card>
                ))}
              </div>
            )}
          </div>
        )}

        {step === "details" && selected && (
          <div className="grid gap-6 lg:grid-cols-3">
            <div className="lg:col-span-2">
              <Card>
                <CardHeader>
                  <CardTitle>Complete Your Booking</CardTitle>
                  <CardDescription>{selected.name} &middot; {checkIn} to {checkOut}</CardDescription>
                </CardHeader>
                <CardContent>
                  <form onSubmit={handleBook} className="space-y-4">
                    <div className="grid grid-cols-2 gap-4">
                      <div className="space-y-2">
                        <Label>First Name</Label>
                        <Input value={guestInfo.first_name} onChange={(e) => setGuestInfo({ ...guestInfo, first_name: e.target.value })} required />
                      </div>
                      <div className="space-y-2">
                        <Label>Last Name</Label>
                        <Input value={guestInfo.last_name} onChange={(e) => setGuestInfo({ ...guestInfo, last_name: e.target.value })} required />
                      </div>
                    </div>
                    <div className="space-y-2">
                      <Label>Email</Label>
                      <Input type="email" value={guestInfo.email} onChange={(e) => setGuestInfo({ ...guestInfo, email: e.target.value })} required />
                    </div>
                    <div className="space-y-2">
                      <Label>Phone</Label>
                      <Input type="tel" value={guestInfo.phone} onChange={(e) => setGuestInfo({ ...guestInfo, phone: e.target.value })} required />
                    </div>
                    <div className="space-y-2">
                      <Label>Special Requests (optional)</Label>
                      <Textarea value={guestInfo.requests} onChange={(e) => setGuestInfo({ ...guestInfo, requests: e.target.value })} />
                    </div>
                    <Button type="submit" className="w-full" disabled={bookMutation.isPending}>
                      <CreditCard className="h-4 w-4 mr-2" />
                      {bookMutation.isPending ? "Processing..." : `Pay $${selected.pricing.total}`}
                    </Button>
                  </form>
                </CardContent>
              </Card>
            </div>
            <Card>
              <CardHeader>
                <CardTitle className="text-base">Price Breakdown</CardTitle>
              </CardHeader>
              <CardContent className="space-y-3">
                <div className="flex justify-between text-sm">
                  <span>${selected.pricing.nightly_rate} × {selected.pricing.nights} nights</span>
                  <span>${selected.pricing.subtotal}</span>
                </div>
                <div className="flex justify-between text-sm">
                  <span>Cleaning fee</span>
                  <span>${selected.pricing.cleaning_fee}</span>
                </div>
                <div className="flex justify-between text-sm">
                  <span>Service fee</span>
                  <span>${selected.pricing.service_fee}</span>
                </div>
                <div className="flex justify-between text-sm">
                  <span>Taxes</span>
                  <span>${selected.pricing.tax}</span>
                </div>
                <Separator />
                <div className="flex justify-between font-bold">
                  <span>Total</span>
                  <span>${selected.pricing.total}</span>
                </div>
              </CardContent>
            </Card>
          </div>
        )}

        {step === "confirmed" && confirmation && (
          <Card className="max-w-lg mx-auto text-center">
            <CardContent className="py-12 space-y-4">
              <div className="mx-auto flex h-16 w-16 items-center justify-center rounded-full bg-green-500/10">
                <Check className="h-8 w-8 text-green-500" />
              </div>
              <h2 className="text-2xl font-bold">Booking Confirmed!</h2>
              <p className="text-muted-foreground">
                Your confirmation code is:
              </p>
              <Badge className="text-lg px-4 py-2">{confirmation.confirmation_code}</Badge>
              <p className="text-sm text-muted-foreground">
                A confirmation email has been sent. You&apos;ll receive access details before your arrival.
              </p>
              <Button variant="outline" onClick={() => setStep("search")}>Book Another Cabin</Button>
            </CardContent>
          </Card>
        )}
      </main>
    </div>
  );
}
