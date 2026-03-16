"use client";

import { useState } from "react";
import { api } from "@/lib/api";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import { BookOpen, Loader2, Scale, Search, User } from "lucide-react";
import { toast } from "sonner";

interface CasePrecedent {
  case_name: string;
  citation: string;
  date_filed: string;
  summary: string;
  url: string;
  relevance: string;
}

interface PrecedentResult {
  query: string;
  total_api_results: number;
  precedents: CasePrecedent[];
  inference_source: string;
  latency_ms: number;
}

interface LitigatorProfile {
  name: string;
  cases_found: number;
  frequent_jurisdictions: string[];
  top_cited_precedents: string[];
  practice_areas: string[];
  win_indicators: string[];
  courtlistener_url: string;
  analysis: string;
}

interface ReconResult {
  query: string;
  profiles: LitigatorProfile[];
  total_api_results: number;
  inference_source: string;
  latency_ms: number;
}

export function JurisprudenceRadar({ slug }: { slug: string }) {
  const [precKeywords, setPrecKeywords] = useState("apparent authority single-member LLC contract");
  const [precResult, setPrecResult] = useState<PrecedentResult | null>(null);
  const [precLoading, setPrecLoading] = useState(false);

  const [reconQuery, setReconQuery] = useState("");
  const [reconResult, setReconResult] = useState<ReconResult | null>(null);
  const [reconLoading, setReconLoading] = useState(false);

  const handlePrecedentSearch = async () => {
    if (!precKeywords.trim()) return;
    setPrecLoading(true);
    try {
      const data = await api.post<PrecedentResult>(
        `/api/legal/cases/${slug}/jurisprudence/precedent`,
        { keywords: precKeywords.split(/\s+/).filter(Boolean) },
      );
      setPrecResult(data);
      toast.success(`Found ${data.precedents?.length ?? 0} relevant precedents`);
    } catch (e) {
      toast.error(e instanceof Error ? e.message : "Precedent search failed");
    } finally {
      setPrecLoading(false);
    }
  };

  const handleAttorneyRecon = async () => {
    if (!reconQuery.trim()) return;
    setReconLoading(true);
    try {
      const data = await api.post<ReconResult>(
        `/api/legal/cases/${slug}/jurisprudence/attorney-recon`,
        { query: reconQuery.trim() },
      );
      setReconResult(data);
      toast.success(`Found ${data.profiles?.length ?? 0} attorney profiles`);
    } catch (e) {
      toast.error(e instanceof Error ? e.message : "Attorney recon failed");
    } finally {
      setReconLoading(false);
    }
  };

  return (
    <div className="grid gap-4 lg:grid-cols-2">
      {/* ── Precedent Radar ── */}
      <Card>
        <CardHeader className="pb-2">
          <CardTitle className="text-sm flex items-center gap-1.5">
            <BookOpen className="h-4 w-4 text-primary" />
            Georgia Precedent Radar
          </CardTitle>
        </CardHeader>
        <CardContent className="space-y-3">
          <div className="flex gap-2">
            <Input
              value={precKeywords}
              onChange={(e) => setPrecKeywords(e.target.value)}
              placeholder="apparent authority contract breach LLC"
              className="text-xs h-8"
              onKeyDown={(e) => e.key === "Enter" && handlePrecedentSearch()}
            />
            <Button
              size="sm"
              onClick={handlePrecedentSearch}
              disabled={precLoading}
              className="text-xs h-8 px-3"
            >
              {precLoading ? <Loader2 className="h-3 w-3 animate-spin" /> : <Search className="h-3 w-3" />}
            </Button>
          </div>

          {precResult && (
            <div className="text-[10px] text-muted-foreground">
              {precResult.total_api_results} CourtListener results | {precResult.precedents.length} filtered by Sovereign | {precResult.inference_source} | {precResult.latency_ms}ms
            </div>
          )}

          <div className="space-y-2 max-h-80 overflow-y-auto">
            {precResult?.precedents?.map((p, i) => (
              <div key={i} className="rounded-lg border p-2.5 text-xs bg-background/50 space-y-1">
                <div className="flex items-start justify-between gap-2">
                  <span className="font-semibold text-foreground leading-snug">{p.case_name}</span>
                  <Badge variant="outline" className="text-[9px] px-1.5 py-0 flex-shrink-0">
                    {p.date_filed || "?"}
                  </Badge>
                </div>
                {p.citation && (
                  <div className="text-[10px] text-sky-400 font-mono">{p.citation}</div>
                )}
                {p.relevance && (
                  <p className="text-emerald-400/80 leading-snug text-[10px]">{p.relevance}</p>
                )}
                {p.summary && (
                  <p className="text-muted-foreground leading-snug line-clamp-3">{p.summary}</p>
                )}
                {p.url && (
                  <a
                    href={`https://www.courtlistener.com${p.url}`}
                    target="_blank"
                    rel="noopener noreferrer"
                    className="text-[10px] text-sky-400 hover:underline"
                  >
                    View on CourtListener
                  </a>
                )}
              </div>
            ))}
            {precResult && precResult.precedents.length === 0 && (
              <p className="text-muted-foreground text-xs text-center py-4">
                No matching Georgia precedent found. Try broader keywords.
              </p>
            )}
          </div>
        </CardContent>
      </Card>

      {/* ── Litigator Profiler ── */}
      <Card>
        <CardHeader className="pb-2">
          <CardTitle className="text-sm flex items-center gap-1.5">
            <User className="h-4 w-4 text-primary" />
            Litigator Reconnaissance
          </CardTitle>
        </CardHeader>
        <CardContent className="space-y-3">
          <div className="flex gap-2">
            <Input
              value={reconQuery}
              onChange={(e) => setReconQuery(e.target.value)}
              placeholder="J. David Stuart or &quot;Georgia contract defense attorney&quot;"
              className="text-xs h-8"
              onKeyDown={(e) => e.key === "Enter" && handleAttorneyRecon()}
            />
            <Button
              size="sm"
              onClick={handleAttorneyRecon}
              disabled={reconLoading}
              className="text-xs h-8 px-3"
            >
              {reconLoading ? <Loader2 className="h-3 w-3 animate-spin" /> : <Search className="h-3 w-3" />}
            </Button>
          </div>

          {reconResult && (
            <div className="text-[10px] text-muted-foreground">
              {reconResult.total_api_results} CourtListener results | {reconResult.profiles.length} profiles built | {reconResult.inference_source} | {reconResult.latency_ms}ms
            </div>
          )}

          <div className="space-y-2 max-h-80 overflow-y-auto">
            {reconResult?.profiles?.map((p, i) => (
              <div key={i} className="rounded-lg border p-2.5 text-xs bg-background/50 space-y-1.5">
                <div className="flex items-center justify-between">
                  <span className="font-semibold text-foreground">{p.name}</span>
                  <Badge variant="outline" className="text-[9px] px-1.5 py-0">
                    {p.cases_found} cases
                  </Badge>
                </div>
                {p.practice_areas.length > 0 && (
                  <div className="flex flex-wrap gap-1">
                    {p.practice_areas.map((area, j) => (
                      <Badge key={j} variant="secondary" className="text-[9px] px-1.5 py-0">{area}</Badge>
                    ))}
                  </div>
                )}
                {p.frequent_jurisdictions.length > 0 && (
                  <div className="text-[10px] text-muted-foreground">
                    Courts: {p.frequent_jurisdictions.join(", ")}
                  </div>
                )}
                {p.win_indicators.length > 0 && (
                  <div className="mt-1">
                    <span className="text-[10px] text-emerald-400 font-semibold">Win Indicators:</span>
                    <ul className="text-[10px] text-emerald-400/80 list-disc pl-3 mt-0.5">
                      {p.win_indicators.slice(0, 3).map((w, j) => (
                        <li key={j}>{w}</li>
                      ))}
                    </ul>
                  </div>
                )}
                {p.top_cited_precedents.length > 0 && (
                  <div className="mt-1">
                    <span className="text-[10px] text-sky-400 font-semibold">Top Cited:</span>
                    <ul className="text-[10px] text-sky-400/80 list-disc pl-3 mt-0.5">
                      {p.top_cited_precedents.slice(0, 3).map((c, j) => (
                        <li key={j} className="font-mono">{c}</li>
                      ))}
                    </ul>
                  </div>
                )}
                {p.analysis && (
                  <p className="text-muted-foreground leading-snug mt-1">{p.analysis}</p>
                )}
              </div>
            ))}
            {reconResult && reconResult.profiles.length === 0 && (
              <p className="text-muted-foreground text-xs text-center py-4">
                No attorney profiles found. Try a different name or specialty.
              </p>
            )}
          </div>
        </CardContent>
      </Card>
    </div>
  );
}
