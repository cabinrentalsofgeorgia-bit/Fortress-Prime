import Link from "next/link";
import { Activity, ArrowRight, Building2, Server } from "lucide-react";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { Button } from "@/components/ui/button";

export default function CommandCenterPage() {
  return (
    <div className="space-y-6">
      <div className="space-y-1">
        <h1 className="text-2xl font-bold tracking-tight">Command Center</h1>
        <p className="text-muted-foreground">
          System operations entrypoint. Open CROG-VRS for rental operations.
        </p>
      </div>

      <div className="grid gap-4 md:grid-cols-2 lg:grid-cols-3">
        <Card className="border-emerald-500/30 bg-emerald-500/5">
          <CardHeader>
            <CardTitle className="flex items-center gap-2">
              <Activity className="h-4 w-4 text-emerald-500" />
              Fortress Prime
            </CardTitle>
            <CardDescription>
              God Mode - live Swarm telemetry, treasury dashboard, and Iron Dome
              ledger. Real-time Redpanda event stream.
            </CardDescription>
          </CardHeader>
          <CardContent>
            <Button asChild className="bg-emerald-600 hover:bg-emerald-700">
              <Link href="/prime">
                Open Prime
                <ArrowRight className="ml-2 h-4 w-4" />
              </Link>
            </Button>
          </CardContent>
        </Card>

        <Card className="border-primary/30">
          <CardHeader>
            <CardTitle className="flex items-center gap-2">
              <Building2 className="h-4 w-4 text-primary" />
              CROG-VRS Operations
            </CardTitle>
            <CardDescription>Reservations, guests, messaging, and rental operations hub.</CardDescription>
          </CardHeader>
          <CardContent>
            <Button asChild>
              <Link href="/vrs">
                Open VRS Hub
                <ArrowRight className="ml-2 h-4 w-4" />
              </Link>
            </Button>
          </CardContent>
        </Card>

        <Card>
          <CardHeader>
            <CardTitle className="flex items-center gap-2">
              <Server className="h-4 w-4 text-primary" />
              System Operations
            </CardTitle>
            <CardDescription>Cluster health, infrastructure monitoring, and service controls.</CardDescription>
          </CardHeader>
          <CardContent>
            <Button asChild variant="outline">
              <Link href="/system-health">
                View System Health
                <ArrowRight className="ml-2 h-4 w-4" />
              </Link>
            </Button>
          </CardContent>
        </Card>
      </div>
    </div>
  );
}
