"use client";

import { useState } from "react";
import { api } from "@/lib/api";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Loader2, Shield, Swords, Eye } from "lucide-react";
import { toast } from "sonner";

interface PersonaOpinion {
  persona_name: string;
  seat: string;
  signal: string;
  conviction: number;
  reasoning: string;
  vulnerabilities?: string[];
  recommended_actions?: string[];
  model_used?: string;
  elapsed_seconds?: number;
}

interface ConsensusResult {
  overall_signal: string;
  weighted_score: number;
  defense_count: number;
  attack_count: number;
  total_opinions: number;
}

interface DeliberationResult {
  opinions?: PersonaOpinion[];
  consensus?: ConsensusResult;
  session_id?: string;
  status?: string;
}

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
  const [result, setResult] = useState<DeliberationResult | null>(null);
  const [loading, setLoading] = useState(false);

  const handleDeliberate = async () => {
    setLoading(true);
    toast.info("Convening the Counsel of 9 — this may take several minutes...");
    try {
      const data = await api.post<DeliberationResult>(
        `/api/legal/cases/${slug}/deliberate`,
      );
      setResult(data);
      toast.success("Counsel deliberation complete");
    } catch (e) {
      toast.error(e instanceof Error ? e.message : "Deliberation failed");
    } finally {
      setLoading(false);
    }
  };

  const opinions = result?.opinions ?? [];
  const consensus = result?.consensus;

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
            disabled={loading}
            className="text-xs h-7"
          >
            {loading ? (
              <>
                <Loader2 className="h-3 w-3 mr-1 animate-spin" />
                Deliberating...
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
        {!result && !loading && (
          <div className="text-center py-8 text-muted-foreground text-xs">
            <Eye className="h-8 w-8 mx-auto mb-2 opacity-30" />
            Click &ldquo;Convene the Counsel&rdquo; to run 9 parallel legal personas against the case evidence.
          </div>
        )}

        {consensus && (
          <div className="mb-4 rounded-lg border p-3 bg-muted/30">
            <div className="flex items-center gap-3 mb-2">
              <span className="text-xs font-semibold">CONSENSUS</span>
              <Badge
                variant="outline"
                className={SIGNAL_STYLES[consensus.overall_signal] ?? SIGNAL_STYLES.NEUTRAL}
              >
                {SIGNAL_LABEL[consensus.overall_signal] ?? consensus.overall_signal}
              </Badge>
              <span className="text-xs text-muted-foreground ml-auto tabular-nums">
                Score: {consensus.weighted_score?.toFixed(2)} | {consensus.defense_count} defense / {consensus.attack_count} attack
              </span>
            </div>
          </div>
        )}

        {opinions.length > 0 && (
          <div className="grid gap-2 md:grid-cols-3">
            {opinions.map((op, i) => {
              const sig = (op.signal || "NEUTRAL").toUpperCase().replace(" ", "_");
              return (
                <div
                  key={op.persona_name || i}
                  className={`rounded-lg border p-2.5 text-xs ${SIGNAL_STYLES[sig] ?? SIGNAL_STYLES.NEUTRAL}`}
                >
                  <div className="flex items-center justify-between mb-1.5">
                    <span className="font-semibold text-foreground truncate">
                      {op.persona_name}
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
                  {op.vulnerabilities && op.vulnerabilities.length > 0 && (
                    <div className="mt-1">
                      <span className="text-[10px] text-red-400 font-semibold">Vulnerabilities:</span>
                      <ul className="text-[10px] text-red-400/80 list-disc pl-3 mt-0.5">
                        {op.vulnerabilities.slice(0, 3).map((v, j) => (
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
      </CardContent>
    </Card>
  );
}
