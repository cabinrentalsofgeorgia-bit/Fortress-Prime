"use client";

import { useMemo } from "react";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Loader2, Shield, Swords, Eye, Radio, Scale } from "lucide-react";
import { toast } from "sonner";
import { useCouncilStream } from "@/lib/use-council-stream";

const SIGNAL_STYLES: Record<string, string> = {
  STRONG_DEFENSE: "bg-emerald-500/10 text-emerald-400 border-emerald-500/30",
  DEFENSE: "bg-green-500/10 text-green-400 border-green-500/30",
  NEUTRAL: "bg-muted text-muted-foreground border-border",
  WEAK: "bg-amber-500/10 text-amber-400 border-amber-500/30",
  VULNERABLE: "bg-red-500/10 text-red-400 border-red-500/30",
  ERROR: "bg-zinc-500/10 text-zinc-400 border-zinc-500/30",
};

const SIGNAL_LABEL: Record<string, string> = {
  STRONG_DEFENSE: "Strong Defense",
  DEFENSE: "Defense",
  NEUTRAL: "Neutral",
  WEAK: "Weak Point",
  VULNERABLE: "Vulnerable",
  ERROR: "Error",
};

export function CounselThreatMatrix({ slug }: { slug: string }) {
  const council = useCouncilStream(slug);
  const opinions = council.finalResult?.opinions.length
    ? council.finalResult.opinions
    : council.opinions;
  const consensus = council.finalResult ?? council.consensus;
  const liveSummary = useMemo(
    () => council.streamLines.slice(-8).reverse(),
    [council.streamLines],
  );

  const handleDeliberate = async () => {
    toast.info("Convening the Counsel of 9 — this may take several minutes...");
    try {
      await council.start();
      toast.success("Council stream established");
    } catch (e) {
      toast.error(e instanceof Error ? e.message : "Deliberation failed");
    }
  };

  const isRunning = council.connectionState !== "idle" &&
    council.connectionState !== "done" &&
    council.connectionState !== "stopped" &&
    council.connectionState !== "error";

  return (
    <Card>
      <CardHeader className="pb-2">
        <div className="flex items-center justify-between">
          <CardTitle className="text-sm flex items-center gap-1.5">
            <Shield className="h-4 w-4 text-primary" />
            Counsel of 9 — Threat Matrix
          </CardTitle>
          <Button
            size="sm"
            onClick={handleDeliberate}
            disabled={isRunning}
            className="text-xs h-7"
          >
            {isRunning ? (
              <>
                <Loader2 className="h-3 w-3 mr-1 animate-spin" />
                {council.connectionState === "reconnecting" ? "Reconnecting..." : "Streaming..."}
              </>
            ) : (
              <>
                <Swords className="h-3 w-3 mr-1" />
                Convene the Counsel
              </>
            )}
          </Button>
        </div>
      </CardHeader>
      <CardContent>
        {!council.hasActiveJob && !isRunning && (
          <div className="text-center py-8 text-muted-foreground text-xs">
            <Eye className="h-8 w-8 mx-auto mb-2 opacity-30" />
            Click &ldquo;Convene the Counsel&rdquo; to open the Redis-backed live stream and watch the 9 legal personas reason in real time.
          </div>
        )}

        {consensus && (
          <div className="mb-4 rounded-lg border p-3 bg-muted/30">
            <div className="flex items-center gap-3 mb-2">
              <span className="text-xs font-semibold">CONSENSUS</span>
              <Badge
                variant="outline"
                className={SIGNAL_STYLES[consensus.consensus_signal] ?? SIGNAL_STYLES.NEUTRAL}
              >
                {SIGNAL_LABEL[consensus.consensus_signal] ?? consensus.consensus_signal}
              </Badge>
              <span className="text-xs text-muted-foreground ml-auto tabular-nums">
                Score: {consensus.net_score_adjusted?.toFixed(2)} | {consensus.defense_count} defense / {consensus.weak_count} weak
              </span>
            </div>
          </div>
        )}

        {(council.hasActiveJob || isRunning || council.error) && (
          <div className="mb-4 rounded-lg border p-3 space-y-2 bg-muted/20">
            <div className="flex flex-wrap items-center gap-2 text-xs">
              <Badge variant="outline" className="gap-1">
                <Radio className="h-3 w-3" />
                {council.connectionState}
              </Badge>
              {council.jobId && (
                <Badge variant="outline" className="font-mono">
                  job {council.jobId.slice(0, 8)}
                </Badge>
              )}
              {council.contextFrozen && (
                <Badge variant="outline">
                  {council.contextFrozen.vector_count} vectors frozen
                </Badge>
              )}
              {council.vaulted?.event_id && (
                <Badge variant="outline" className="font-mono">
                  vault {council.vaulted.event_id.slice(0, 8)}
                </Badge>
              )}
            </div>
            {council.error && (
              <p className="text-xs text-red-400">{council.error}</p>
            )}
            {liveSummary.length > 0 && (
              <div className="space-y-1 rounded-md border bg-background/50 p-2">
                {liveSummary.map((line) => (
                  <div key={line.id} className="text-[11px] text-muted-foreground">
                    <span className="font-medium text-foreground/80">
                      {line.type}
                    </span>
                    {" "}
                    {line.label}
                  </div>
                ))}
              </div>
            )}
          </div>
        )}

        {opinions.length > 0 && (
          <div className="grid gap-2 md:grid-cols-3">
            {opinions.map((op, i) => {
              const sig = (op.signal || "NEUTRAL").toUpperCase().replace(" ", "_");
              return (
                <div
                  key={op.persona || i}
                  className={`rounded-lg border p-2.5 text-xs ${SIGNAL_STYLES[sig] ?? SIGNAL_STYLES.NEUTRAL}`}
                >
                  <div className="flex items-center justify-between mb-1.5">
                    <span className="font-semibold text-foreground truncate">
                      {op.persona}
                    </span>
                    <Badge
                      variant="outline"
                      className={`text-[9px] px-1.5 py-0 ${SIGNAL_STYLES[sig] ?? ""}`}
                    >
                      {SIGNAL_LABEL[sig] ?? sig}
                    </Badge>
                  </div>
                  <div className="text-[10px] text-muted-foreground mb-1">
                    Seat: {op.seat} | Conviction: {(op.conviction * 100).toFixed(0)}%
                  </div>
                  <p className="text-foreground/80 leading-snug line-clamp-4 mb-1.5">
                    {op.reasoning}
                  </p>
                  {op.risk_factors.length > 0 && (
                    <div className="mt-1">
                      <span className="text-[10px] text-red-400 font-semibold">Risk Factors:</span>
                      <ul className="text-[10px] text-red-400/80 list-disc pl-3 mt-0.5">
                        {op.risk_factors.slice(0, 3).map((v, j) => (
                          <li key={j} className="line-clamp-2">{v}</li>
                        ))}
                      </ul>
                    </div>
                  )}
                  {op.recommended_actions && op.recommended_actions.length > 0 && (
                    <div className="mt-1">
                      <span className="text-[10px] text-emerald-400 font-semibold">Actions:</span>
                      <ul className="text-[10px] text-emerald-400/80 list-disc pl-3 mt-0.5">
                        {op.recommended_actions.slice(0, 3).map((a, j) => (
                          <li key={j} className="line-clamp-2">{a}</li>
                        ))}
                      </ul>
                    </div>
                  )}
                  {op.model_used && (
                    <div className="text-[9px] text-muted-foreground mt-1 tabular-nums">
                      {op.model_used} | {op.elapsed_seconds?.toFixed(1)}s
                    </div>
                  )}
                </div>
              );
            })}
          </div>
        )}

        {council.finalResult?.sha256_signature && (
          <div className="mt-4 rounded-lg border p-3 bg-muted/20">
            <div className="flex items-center gap-2 text-xs text-muted-foreground">
              <Scale className="h-3.5 w-3.5" />
              Sealed deliberation signature
            </div>
            <p className="mt-2 break-all font-mono text-[11px] text-foreground/80">
              {council.finalResult.sha256_signature}
            </p>
          </div>
        )}
      </CardContent>
    </Card>
  );
}
