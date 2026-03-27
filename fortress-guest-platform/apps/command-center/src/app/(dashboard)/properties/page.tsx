"use client";

import { useRouter } from "next/navigation";
import { useProperties } from "@/lib/hooks";
import { Badge } from "@/components/ui/badge";
import {
  Card,
  CardContent,
  CardHeader,
  CardTitle,
} from "@/components/ui/card";
import { Bed, Bath, Users } from "lucide-react";
import { CardGridSkeleton } from "@/components/skeletons";

export default function PropertiesPage() {
  const router = useRouter();
  const { data: properties, isLoading } = useProperties();

  return (
    <div className="space-y-6">
      <div>
        <h1 className="text-2xl font-bold tracking-tight">Properties</h1>
        <p className="text-muted-foreground">
          {properties?.length ?? 0} managed properties
        </p>
      </div>

      {isLoading ? (
        <CardGridSkeleton count={6} />
      ) : (
        <div className="grid gap-4 md:grid-cols-2 lg:grid-cols-3">
          {(properties ?? []).map((p) => (
            <Card key={p.id} className="hover:shadow-md transition-shadow cursor-pointer" onClick={() => router.push(`/properties/${p.id}`)}>
              <CardHeader className="pb-3">
                <div className="flex items-start justify-between">
                  <div>
                    <CardTitle className="text-base">{p.name}</CardTitle>
                    <p className="text-xs text-muted-foreground mt-1">
                      {p.property_type} &middot; {p.slug}
                    </p>
                  </div>
                  <Badge variant={p.is_active ? "default" : "secondary"}>
                    {p.is_active ? "Active" : "Inactive"}
                  </Badge>
                </div>
              </CardHeader>
              <CardContent>
                <div className="flex items-center gap-4 text-sm text-muted-foreground">
                  <span className="flex items-center gap-1">
                    <Bed className="h-4 w-4" />
                    {p.bedrooms} BR
                  </span>
                  <span className="flex items-center gap-1">
                    <Bath className="h-4 w-4" />
                    {p.bathrooms} BA
                  </span>
                  <span className="flex items-center gap-1">
                    <Users className="h-4 w-4" />
                    Sleeps {p.max_guests}
                  </span>
                </div>
                {p.streamline_property_id && (
                  <p className="mt-3 text-xs text-muted-foreground">
                    Streamline ID: {p.streamline_property_id}
                  </p>
                )}
                {p.access_code_type && (
                  <div className="mt-3 flex gap-2">
                    <Badge variant="outline" className="text-[10px]">
                      {p.access_code_type}
                    </Badge>
                    {p.wifi_ssid && (
                      <Badge variant="outline" className="text-[10px]">
                        WiFi: {p.wifi_ssid}
                      </Badge>
                    )}
                  </div>
                )}
              </CardContent>
            </Card>
          ))}
        </div>
      )}
    </div>
  );
}
