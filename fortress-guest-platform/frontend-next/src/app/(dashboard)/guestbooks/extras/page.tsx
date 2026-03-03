"use client";

import { useState } from "react";
import { useExtras, useProperties } from "@/lib/hooks";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Textarea } from "@/components/ui/textarea";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import {
  Sheet,
  SheetContent,
  SheetHeader,
  SheetTitle,
} from "@/components/ui/sheet";
import {
  ShoppingBag,
  Plus,
  DollarSign,
  Clock,
  Package,
  Flame,
  BedDouble,
  ShoppingCart,
  Pencil,
} from "lucide-react";
import { toast } from "sonner";
import { CardGridSkeleton } from "@/components/skeletons";

interface Extra {
  id: string;
  name: string;
  description: string;
  price: number;
  category: string;
  is_active: boolean;
}

const CATEGORY_ICONS: Record<string, React.ReactNode> = {
  "early_check_in": <Clock className="h-5 w-5" />,
  "late_checkout": <Clock className="h-5 w-5" />,
  "firewood": <Flame className="h-5 w-5" />,
  "linens": <BedDouble className="h-5 w-5" />,
  "grocery": <ShoppingCart className="h-5 w-5" />,
  "other": <Package className="h-5 w-5" />,
};

export default function ExtrasPage() {
  const { data: extras, isLoading } = useExtras();
  const { data: properties } = useProperties();
  const [createOpen, setCreateOpen] = useState(false);

  const extrasList = Array.isArray(extras) ? extras as Extra[] : [];

  if (isLoading) return <CardGridSkeleton />;

  return (
    <div className="space-y-6">
      <div className="flex items-center justify-between">
        <div>
          <h1 className="text-2xl font-bold tracking-tight">Extras Marketplace</h1>
          <p className="text-muted-foreground">
            Upsell add-ons inside your digital guestbooks
          </p>
        </div>
        <Button onClick={() => setCreateOpen(true)}>
          <Plus className="mr-2 h-4 w-4" />
          Add Extra
        </Button>
      </div>

      {extrasList.length === 0 ? (
        <Card>
          <CardContent className="py-16 text-center">
            <ShoppingBag className="h-16 w-16 mx-auto mb-4 text-muted-foreground/30" />
            <p className="text-lg font-medium">No extras configured yet</p>
            <p className="text-sm text-muted-foreground mt-1">
              Create add-ons like early check-in, late checkout, firewood bundles, or grocery delivery
            </p>
            <Button className="mt-4" onClick={() => setCreateOpen(true)}>
              <Plus className="mr-2 h-4 w-4" />
              Create Your First Extra
            </Button>
          </CardContent>
        </Card>
      ) : (
        <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-3">
          {extrasList.map((extra) => (
            <Card key={extra.id} className="hover:shadow-md transition-shadow">
              <CardHeader className="pb-3">
                <div className="flex items-start justify-between">
                  <div className="flex items-center gap-2">
                    <div className="h-10 w-10 rounded-lg bg-primary/10 flex items-center justify-center text-primary">
                      {CATEGORY_ICONS[extra.category] ?? <Package className="h-5 w-5" />}
                    </div>
                    <div>
                      <CardTitle className="text-base">{extra.name}</CardTitle>
                      <Badge variant="outline" className="text-[10px] mt-0.5">
                        {extra.category.replace("_", " ")}
                      </Badge>
                    </div>
                  </div>
                  <Badge variant={extra.is_active ? "default" : "secondary"}>
                    {extra.is_active ? "Active" : "Inactive"}
                  </Badge>
                </div>
              </CardHeader>
              <CardContent>
                <p className="text-sm text-muted-foreground line-clamp-2 mb-3">
                  {extra.description}
                </p>
                <div className="flex items-center justify-between">
                  <span className="text-lg font-bold text-green-600">
                    ${extra.price.toFixed(2)}
                  </span>
                  <Button variant="ghost" size="sm">
                    <Pencil className="h-4 w-4 mr-1" />
                    Edit
                  </Button>
                </div>
              </CardContent>
            </Card>
          ))}
        </div>
      )}

      {/* Create Extra Sheet */}
      <Sheet open={createOpen} onOpenChange={setCreateOpen}>
        <SheetContent className="w-[400px] overflow-y-auto">
          <SheetHeader>
            <SheetTitle>New Extra</SheetTitle>
          </SheetHeader>
          <form
            className="mt-6 space-y-4"
            onSubmit={(e) => {
              e.preventDefault();
              toast.success("Extra created");
              setCreateOpen(false);
            }}
          >
            <div className="space-y-2">
              <Label>Name</Label>
              <Input placeholder="e.g. Early Check-in (2 PM)" required />
            </div>
            <div className="space-y-2">
              <Label>Description</Label>
              <Textarea placeholder="What does the guest get?" rows={3} />
            </div>
            <div className="space-y-2">
              <Label>Price ($)</Label>
              <Input type="number" step="0.01" min="0" placeholder="50.00" required />
            </div>
            <div className="space-y-2">
              <Label>Category</Label>
              <Select defaultValue="other">
                <SelectTrigger><SelectValue /></SelectTrigger>
                <SelectContent>
                  <SelectItem value="early_check_in">Early Check-in</SelectItem>
                  <SelectItem value="late_checkout">Late Checkout</SelectItem>
                  <SelectItem value="firewood">Firewood</SelectItem>
                  <SelectItem value="linens">Linens</SelectItem>
                  <SelectItem value="grocery">Grocery Delivery</SelectItem>
                  <SelectItem value="other">Other</SelectItem>
                </SelectContent>
              </Select>
            </div>
            <div className="space-y-2">
              <Label>Available for Properties</Label>
              <Select>
                <SelectTrigger><SelectValue placeholder="All properties" /></SelectTrigger>
                <SelectContent>
                  <SelectItem value="all">All Properties</SelectItem>
                  {(properties ?? []).map((p) => (
                    <SelectItem key={p.id} value={p.id}>{p.name}</SelectItem>
                  ))}
                </SelectContent>
              </Select>
            </div>
            <Button type="submit" className="w-full">Create Extra</Button>
          </form>
        </SheetContent>
      </Sheet>
    </div>
  );
}
