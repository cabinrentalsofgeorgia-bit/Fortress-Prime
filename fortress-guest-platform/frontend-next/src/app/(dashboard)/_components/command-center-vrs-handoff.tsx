"use client";

import Link from "next/link";
import { ArrowRight, Building2 } from "lucide-react";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";

export function CommandCenterVrsHandoff() {
  return (
    <Card className="border-primary/30">
      <CardHeader>
        <CardTitle className="flex items-center gap-2">
          <Building2 className="h-4 w-4 text-primary" />
          CROG-VRS Operations
        </CardTitle>
        <CardDescription>
          Rental business operations are isolated in the dedicated CROG-VRS dashboard.
        </CardDescription>
      </CardHeader>
      <CardContent>
        <Button asChild>
          <Link href="/vrs" className="inline-flex items-center gap-2">
            Open VRS Hub
            <ArrowRight className="h-4 w-4" />
          </Link>
        </Button>
      </CardContent>
    </Card>
  );
}
