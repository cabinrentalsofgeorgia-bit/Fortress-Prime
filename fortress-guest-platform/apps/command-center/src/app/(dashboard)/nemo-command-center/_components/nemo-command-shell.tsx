"use client";

import { useNemoCommandCenter } from "@/lib/hooks";
import { Badge } from "@/components/ui/badge";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { Skeleton } from "@/components/ui/skeleton";
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@/components/ui/table";

function signaturePreview(sig: string | null): string {
  if (!sig) return "—";
  return sig.length > 8 ? `${sig.slice(0, 8)}…` : sig;
}

function formatUsd(cents: number): string {
  return new Intl.NumberFormat("en-US", {
    style: "currency",
    currency: "USD",
  }).format(cents / 100);
}

export function NemoCommandShell() {
  const { data, isLoading, isError, error } = useNemoCommandCenter();

  if (isLoading) {
    return (
      <div className="space-y-6">
        <Skeleton className="h-36 w-full rounded-xl" />
        <Skeleton className="h-[420px] w-full rounded-xl" />
      </div>
    );
  }

  if (isError || !data) {
    return (
      <Card className="border-destructive/50">
        <CardHeader>
          <CardTitle className="text-destructive">Failed to load NeMo Command Center</CardTitle>
          <CardDescription>
            {error instanceof Error ? error.message : "Unknown error"}
          </CardDescription>
        </CardHeader>
      </Card>
    );
  }

  const { hash_chain: hc, transactions, total_transaction_count: total } = data;
  const chainOk = hc.status === "ok";

  return (
    <div className="space-y-6">
      <Card>
        <CardHeader>
          <CardTitle className="flex flex-wrap items-center gap-3">
            Hermes hash-chain
            <Badge
              className={
                chainOk
                  ? "bg-emerald-600 text-white hover:bg-emerald-600"
                  : "bg-destructive text-white hover:bg-destructive"
              }
            >
              {chainOk ? "SYSTEM VERIFIED" : "CRITICAL BREACH"}
            </Badge>
          </CardTitle>
          <CardDescription>
            Cryptographic integrity of signed trust transactions (Hermes daily auditor verifier).
          </CardDescription>
        </CardHeader>
        <CardContent className="flex flex-wrap gap-6 text-sm">
          <div>
            <p className="text-muted-foreground">Chain status</p>
            <p className="font-mono font-medium">{hc.status}</p>
          </div>
          <div>
            <p className="text-muted-foreground">Verified in chain</p>
            <p className="font-mono font-medium">{hc.verified_count}</p>
          </div>
          <div>
            <p className="text-muted-foreground">Total transactions (DB)</p>
            <p className="font-mono font-medium">{total}</p>
          </div>
          {!chainOk && hc.broken_at ? (
            <div>
              <p className="text-muted-foreground">Broken at transaction id</p>
              <p className="font-mono text-destructive">{hc.broken_at}</p>
            </div>
          ) : null}
        </CardContent>
      </Card>

      <Card>
        <CardHeader>
          <CardTitle>Ledger feed</CardTitle>
          <CardDescription>
            50 most recent trust transactions — signature preview (SHA-256 prefix).
          </CardDescription>
        </CardHeader>
        <CardContent>
          <Table>
            <TableHeader>
              <TableRow>
                <TableHead>Time (UTC)</TableHead>
                <TableHead>Event id</TableHead>
                <TableHead>Signature</TableHead>
                <TableHead>Entries</TableHead>
              </TableRow>
            </TableHeader>
            <TableBody>
              {transactions.length === 0 ? (
                <TableRow>
                  <TableCell colSpan={4} className="text-muted-foreground">
                    No trust transactions yet.
                  </TableCell>
                </TableRow>
              ) : (
                transactions.map((tx) => (
                  <TableRow key={tx.id}>
                    <TableCell className="font-mono text-xs whitespace-nowrap">
                      {tx.timestamp}
                    </TableCell>
                    <TableCell className="max-w-[220px] truncate font-mono text-xs" title={tx.streamline_event_id}>
                      {tx.streamline_event_id}
                    </TableCell>
                    <TableCell className="font-mono text-xs">{signaturePreview(tx.signature)}</TableCell>
                    <TableCell className="text-xs">
                      <ul className="space-y-0.5">
                        {tx.entries.map((e, i) => (
                          <li key={`${tx.id}-${i}`}>
                            <span className={e.entry_type === "debit" ? "text-amber-600 dark:text-amber-400" : "text-sky-600 dark:text-sky-400"}>
                              {e.entry_type.toUpperCase()}
                            </span>{" "}
                            {formatUsd(e.amount_cents)} → {e.account_name}
                          </li>
                        ))}
                      </ul>
                    </TableCell>
                  </TableRow>
                ))
              )}
            </TableBody>
          </Table>
        </CardContent>
      </Card>
    </div>
  );
}
