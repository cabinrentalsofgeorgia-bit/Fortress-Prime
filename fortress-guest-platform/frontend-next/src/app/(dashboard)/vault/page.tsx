"use client";

import { useState, useCallback } from "react";
import { api } from "@/lib/api";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Badge } from "@/components/ui/badge";
import {
  Search,
  Download,
  Shield,
  Filter,
  ChevronDown,
  ChevronUp,
  FileText,
  Clock,
  User,
  AlertTriangle,
} from "lucide-react";

// ── Types ───────────────────────────────────────────────────────────────────

interface VaultHit {
  score: number;
  subject: string;
  sender: string;
  date: string;
  preview: string;
  source_file: string;
  chunk_index: number;
}

interface VaultSearchResponse {
  query: string;
  filters: Record<string, string | boolean>;
  total_results: number;
  results: VaultHit[];
  audit_id: string | null;
}

// ── Helpers ─────────────────────────────────────────────────────────────────

function relevanceBadge(score: number) {
  if (score >= 0.75) return <Badge className="bg-green-600 text-white">{score.toFixed(3)}</Badge>;
  if (score >= 0.5) return <Badge className="bg-yellow-600 text-white">{score.toFixed(3)}</Badge>;
  if (score >= 0.3) return <Badge className="bg-orange-600 text-white">{score.toFixed(3)}</Badge>;
  return <Badge variant="secondary">{score.toFixed(3)}</Badge>;
}

function downloadCSV(results: VaultHit[]) {
  const header = "Relevance,Date,Sender,Subject,Preview,Source File,Chunk\n";
  const rows = results.map((r) => {
    const esc = (s: string) => `"${(s ?? "").replace(/"/g, '""')}"`;
    return [r.score, esc(r.date), esc(r.sender), esc(r.subject), esc(r.preview?.slice(0, 300) ?? ""), esc(r.source_file), r.chunk_index].join(",");
  });
  const blob = new Blob([header + rows.join("\n")], { type: "text/csv" });
  const url = URL.createObjectURL(blob);
  const a = document.createElement("a");
  a.href = url;
  a.download = `vault_export_${new Date().toISOString().slice(0, 10)}.csv`;
  a.click();
  URL.revokeObjectURL(url);
}

// ── Component ───────────────────────────────────────────────────────────────

export default function VaultPage() {
  const [query, setQuery] = useState("");
  const [startDate, setStartDate] = useState("");
  const [endDate, setEndDate] = useState("");
  const [senderDomain, setSenderDomain] = useState("");
  const [results, setResults] = useState<VaultSearchResponse | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [expandedIdx, setExpandedIdx] = useState<number | null>(null);
  const [showFilters, setShowFilters] = useState(true);

  const executeSearch = useCallback(async () => {
    if (!query.trim()) return;
    setLoading(true);
    setError(null);
    setExpandedIdx(null);

    try {
      const payload: Record<string, unknown> = { query: query.trim(), limit: 50 };
      if (startDate) payload.start_date = startDate;
      if (endDate) payload.end_date = endDate;
      if (senderDomain.trim()) payload.sender_domain = senderDomain.trim();

      const data = await api.post<VaultSearchResponse>("/api/vault/search", payload);
      setResults(data);
    } catch (err: unknown) {
      const msg = err instanceof Error ? err.message : "Search failed";
      setError(msg);
    } finally {
      setLoading(false);
    }
  }, [query, startDate, endDate, senderDomain]);

  const handleKeyDown = (e: React.KeyboardEvent) => {
    if (e.key === "Enter") executeSearch();
  };

  const activeFilterCount = [startDate, endDate, senderDomain].filter(Boolean).length;

  return (
    <div className="flex flex-col h-full">
      {/* Header */}
      <div className="flex items-center justify-between border-b px-6 py-4">
        <div className="flex items-center gap-3">
          <div className="flex h-10 w-10 items-center justify-center rounded-lg bg-red-600/20">
            <Shield className="h-5 w-5 text-red-400" />
          </div>
          <div>
            <h1 className="text-lg font-semibold">E-Discovery Vault</h1>
            <p className="text-xs text-muted-foreground">
              Hybrid semantic + metadata search across 320K+ emails &middot; Chain of custody audit logging
            </p>
          </div>
        </div>
        {results && results.total_results > 0 && (
          <Button
            variant="outline"
            size="sm"
            onClick={() => downloadCSV(results.results)}
          >
            <Download className="h-4 w-4 mr-2" />
            Export CSV ({results.total_results})
          </Button>
        )}
      </div>

      <div className="flex flex-1 overflow-hidden">
        {/* Filter Sidebar */}
        <div
          className={`border-r transition-all duration-200 overflow-y-auto ${
            showFilters ? "w-72 p-4" : "w-0 p-0 overflow-hidden"
          }`}
        >
          {showFilters && (
            <div className="space-y-5">
              <div className="flex items-center justify-between">
                <h2 className="text-sm font-semibold flex items-center gap-2">
                  <Filter className="h-4 w-4" /> Metadata Filters
                </h2>
                {activeFilterCount > 0 && (
                  <Badge variant="secondary" className="text-xs">
                    {activeFilterCount} active
                  </Badge>
                )}
              </div>

              {/* Date Range */}
              <div className="space-y-2">
                <label className="text-xs font-medium text-muted-foreground uppercase tracking-wider">
                  Date Range
                </label>
                <div className="space-y-1.5">
                  <Input
                    type="date"
                    value={startDate}
                    onChange={(e) => setStartDate(e.target.value)}
                    className="h-8 text-xs"
                    placeholder="From"
                  />
                  <Input
                    type="date"
                    value={endDate}
                    onChange={(e) => setEndDate(e.target.value)}
                    className="h-8 text-xs"
                    placeholder="To"
                  />
                </div>
              </div>

              {/* Sender */}
              <div className="space-y-2">
                <label className="text-xs font-medium text-muted-foreground uppercase tracking-wider">
                  Sender / Domain
                </label>
                <Input
                  value={senderDomain}
                  onChange={(e) => setSenderDomain(e.target.value)}
                  className="h-8 text-xs"
                  placeholder="e.g. generali, coinbits"
                  onKeyDown={handleKeyDown}
                />
              </div>

              {/* Clear */}
              {activeFilterCount > 0 && (
                <Button
                  variant="ghost"
                  size="sm"
                  className="w-full text-xs"
                  onClick={() => {
                    setStartDate("");
                    setEndDate("");
                    setSenderDomain("");
                  }}
                >
                  Clear All Filters
                </Button>
              )}

              {/* Audit Badge */}
              {results?.audit_id && (
                <div className="rounded-md border p-3 bg-muted/30 space-y-1">
                  <p className="text-[10px] font-medium text-muted-foreground uppercase tracking-wider">
                    Chain of Custody
                  </p>
                  <p className="text-xs font-mono break-all">{results.audit_id}</p>
                  <p className="text-[10px] text-muted-foreground">
                    Logged to vault_audit_logs
                  </p>
                </div>
              )}
            </div>
          )}
        </div>

        {/* Main Content */}
        <div className="flex-1 flex flex-col overflow-hidden">
          {/* Search Bar */}
          <div className="flex items-center gap-2 p-4 border-b">
            <Button
              variant="ghost"
              size="icon"
              className="h-8 w-8 shrink-0"
              onClick={() => setShowFilters(!showFilters)}
              title="Toggle filters"
            >
              <Filter className="h-4 w-4" />
            </Button>
            <div className="flex-1 relative">
              <Search className="absolute left-3 top-1/2 -translate-y-1/2 h-4 w-4 text-muted-foreground" />
              <Input
                value={query}
                onChange={(e) => setQuery(e.target.value)}
                onKeyDown={handleKeyDown}
                className="pl-9 h-10"
                placeholder="Semantic search: e.g. &quot;Generali insurance commission dispute&quot; or &quot;KYC distribution notice&quot;"
              />
            </div>
            <Button onClick={executeSearch} disabled={loading || !query.trim()} className="h-10">
              {loading ? (
                <span className="flex items-center gap-2">
                  <span className="h-4 w-4 border-2 border-white/30 border-t-white rounded-full animate-spin" />
                  Searching...
                </span>
              ) : (
                "Search Vault"
              )}
            </Button>
          </div>

          {/* Results Area */}
          <div className="flex-1 overflow-y-auto p-4">
            {error && (
              <div className="flex items-center gap-3 rounded-lg border border-red-500/30 bg-red-500/5 p-4 mb-4">
                <AlertTriangle className="h-5 w-5 text-red-400 shrink-0" />
                <p className="text-sm text-red-400">{error}</p>
              </div>
            )}

            {!results && !loading && !error && (
              <div className="flex flex-col items-center justify-center h-full text-center space-y-3 text-muted-foreground">
                <Shield className="h-12 w-12 opacity-30" />
                <div>
                  <p className="text-sm font-medium">Enterprise E-Discovery Vault</p>
                  <p className="text-xs mt-1 max-w-md">
                    Hybrid search combines AI semantic understanding with exact metadata filtering.
                    Every search is logged for legal chain of custody compliance.
                  </p>
                </div>
              </div>
            )}

            {results && results.total_results === 0 && (
              <div className="flex flex-col items-center justify-center py-16 text-muted-foreground">
                <FileText className="h-10 w-10 opacity-30 mb-3" />
                <p className="text-sm font-medium">No results found</p>
                <p className="text-xs mt-1">Try broadening your date range or removing sender filters.</p>
              </div>
            )}

            {results && results.total_results > 0 && (
              <div className="space-y-1">
                <div className="flex items-center justify-between mb-3">
                  <p className="text-xs text-muted-foreground">
                    <span className="font-semibold text-foreground">{results.total_results}</span> results
                    for &ldquo;{results.query}&rdquo;
                    {Object.keys(results.filters).length > 0 && (
                      <span>
                        {" "}with {Object.entries(results.filters).map(([k, v]) => `${k}=${v}`).join(", ")}
                      </span>
                    )}
                  </p>
                </div>

                {/* Results Table */}
                <div className="rounded-lg border overflow-hidden">
                  <table className="w-full text-sm">
                    <thead>
                      <tr className="bg-muted/40 text-xs text-muted-foreground">
                        <th className="text-left px-3 py-2 w-20">Score</th>
                        <th className="text-left px-3 py-2 w-40">Date</th>
                        <th className="text-left px-3 py-2 w-52">Sender</th>
                        <th className="text-left px-3 py-2">Subject</th>
                        <th className="text-left px-3 py-2 w-10"></th>
                      </tr>
                    </thead>
                    <tbody className="divide-y">
                      {results.results.map((hit, idx) => (
                        <ResultRow
                          key={`${hit.source_file}-${hit.chunk_index}`}
                          hit={hit}
                          expanded={expandedIdx === idx}
                          onToggle={() => setExpandedIdx(expandedIdx === idx ? null : idx)}
                        />
                      ))}
                    </tbody>
                  </table>
                </div>
              </div>
            )}
          </div>
        </div>
      </div>
    </div>
  );
}

// ── Result Row ──────────────────────────────────────────────────────────────

function ResultRow({
  hit,
  expanded,
  onToggle,
}: {
  hit: VaultHit;
  expanded: boolean;
  onToggle: () => void;
}) {
  return (
    <>
      <tr
        className="hover:bg-muted/20 cursor-pointer transition-colors"
        onClick={onToggle}
      >
        <td className="px-3 py-2.5">{relevanceBadge(hit.score)}</td>
        <td className="px-3 py-2.5">
          <span className="flex items-center gap-1.5 text-xs text-muted-foreground">
            <Clock className="h-3 w-3" />
            {hit.date ? hit.date.slice(0, 25) : "—"}
          </span>
        </td>
        <td className="px-3 py-2.5">
          <span className="flex items-center gap-1.5 text-xs truncate max-w-[200px]">
            <User className="h-3 w-3 text-muted-foreground shrink-0" />
            {hit.sender || "—"}
          </span>
        </td>
        <td className="px-3 py-2.5 text-xs font-medium truncate max-w-[300px]">
          {hit.subject || "(no subject)"}
        </td>
        <td className="px-3 py-2.5">
          {expanded ? (
            <ChevronUp className="h-4 w-4 text-muted-foreground" />
          ) : (
            <ChevronDown className="h-4 w-4 text-muted-foreground" />
          )}
        </td>
      </tr>
      {expanded && (
        <tr className="bg-muted/10">
          <td colSpan={5} className="px-4 py-3">
            <div className="space-y-2">
              <p className="text-xs whitespace-pre-wrap leading-relaxed text-muted-foreground">
                {hit.preview || "No content preview available."}
              </p>
              <div className="flex items-center gap-4 text-[10px] text-muted-foreground pt-1 border-t">
                <span>Source: <span className="font-mono">{hit.source_file}</span></span>
                <span>Chunk: {hit.chunk_index}</span>
              </div>
            </div>
          </td>
        </tr>
      )}
    </>
  );
}
