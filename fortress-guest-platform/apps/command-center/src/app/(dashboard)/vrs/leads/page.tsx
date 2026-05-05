import Link from "next/link";
import { ArrowRight, Radar } from "lucide-react";

import { Badge } from "@/components/ui/badge";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";

export default function VrsLeadsPage() {
  return (
    <div className="space-y-6 p-6">
      <div>
        <div className="mb-2 flex items-center gap-2">
          <Radar className="h-5 w-5 text-cyan-400" />
          <Badge variant="outline" className="border-cyan-500/30 bg-cyan-500/10 text-cyan-200">
            Read-only
          </Badge>
        </div>
        <h1 className="text-2xl font-semibold tracking-tight">VRS Leads</h1>
        <p className="mt-1 max-w-2xl text-sm text-muted-foreground">
          Protected shell route for lead review. Operational queues stay behind their dedicated VRS surfaces.
        </p>
      </div>

      <Card>
        <CardHeader>
          <CardTitle>Lead Review Surface</CardTitle>
          <CardDescription>
            This route exists so the authenticated command shell resolves every advertised navigation target.
          </CardDescription>
        </CardHeader>
        <CardContent>
          <Link href="/vrs/hunter" className="inline-flex items-center gap-2 text-sm font-medium text-primary hover:underline">
            Open VRS Hunter
            <ArrowRight className="h-4 w-4" />
          </Link>
        </CardContent>
      </Card>
    </div>
  );
}
