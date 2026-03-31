"use client";

import { useState } from "react";
import { api } from "@/lib/api";
import { RoleGatedAction } from "@/components/access/role-gated-action";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Badge } from "@/components/ui/badge";
import { FileText, Loader2, ShieldAlert } from "lucide-react";
import { toast } from "sonner";

type IngestResponse = {
  case_slug: string;
  source_ref: string;
  chunks_processed?: number;
  nodes_created: number;
  edges_created: number;
  statements_created: number;
  inference_source: string;
  breaker_state: string;
  latency_ms: number;
};

type EvidenceUploadProps = {
  slug: string;
  onIngested?: () => void;
  canOperate?: boolean;
};

export function EvidenceUpload({ slug, onIngested, canOperate = true }: EvidenceUploadProps) {
  const [text, setText] = useState("");
  const [sourceRef, setSourceRef] = useState("");
  const [ingesting, setIngesting] = useState(false);
  const [result, setResult] = useState<IngestResponse | null>(null);

  const canSubmit = text.trim().length >= 20 && sourceRef.trim().length >= 3 && !ingesting;

  async function handleIngest() {
    setIngesting(true);
    setResult(null);
    try {
      const res = await api.post<IngestResponse>(
        `/api/internal/legal/cases/${slug}/evidence/ingest-text`,
        { document_text: text.trim(), source_ref: sourceRef.trim() },
      );
      setResult(res);
      toast.success(
        `Ingested: ${res.nodes_created} nodes, ${res.edges_created} edges, ${res.statements_created} statements`,
      );
      onIngested?.();
    } catch (err) {
      toast.error(err instanceof Error ? err.message : "Ingestion failed");
    } finally {
      setIngesting(false);
    }
  }

  return (
    <div className="rounded-lg border border-zinc-800 bg-zinc-950/80 p-4 space-y-3">
      <div className="flex items-center gap-2">
        <FileText className="h-4 w-4 text-blue-400" />
        <p className="text-sm font-semibold text-zinc-100">Evidence Ingestion</p>
      </div>

      <Input
        value={sourceRef}
        onChange={(e) => setSourceRef(e.target.value)}
        placeholder="Source name (e.g., Generali Affidavit 03-13-2026)"
        className="bg-zinc-900 border-zinc-700 text-sm"
      />

      <textarea
        value={text}
        onChange={(e) => setText(e.target.value)}
        placeholder="Paste the raw text of an affidavit, complaint, or filing here..."
        rows={8}
        className="w-full rounded-md border border-zinc-700 bg-zinc-900 px-3 py-2 text-sm text-zinc-100 placeholder:text-zinc-500 focus:outline-none focus:ring-2 focus:ring-blue-500 resize-y"
      />

      <div className="flex items-center gap-3">
        <RoleGatedAction allowed={canOperate} reason="Manager or admin role required.">
          <Button
            type="button"
            onClick={handleIngest}
            disabled={!canOperate || !canSubmit}
            className="gap-2"
          >
            {ingesting ? (
              <>
                <Loader2 className="h-4 w-4 animate-spin" />
                {text.length > 15000
                  ? "Swarm is processing massive document... This may take a minute."
                  : "Ingesting to Swarm..."}
              </>
            ) : (
              <>
                <FileText className="h-4 w-4" />
                Ingest to Swarm
              </>
            )}
          </Button>
        </RoleGatedAction>
        <span className="text-[10px] text-zinc-500">
          {text.length.toLocaleString()} chars
          {text.length > 10000 && ` · ~${Math.ceil(text.length / 10000)} chunks`}
        </span>
      </div>

      {result && (
        <div className="space-y-2">
          <div className="rounded-md border-2 border-red-600 bg-red-950/60 p-2 flex items-start gap-2">
            <ShieldAlert className="h-4 w-4 text-red-500 shrink-0 mt-0.5" />
            <p className="text-[11px] font-bold text-red-400 uppercase tracking-wider">
              AI Extraction — Counsel Must Verify Accuracy Before Reliance
            </p>
          </div>

          <div className="flex items-center gap-2 flex-wrap">
            {(result.chunks_processed ?? 0) > 1 && (
              <Badge variant="outline" className="text-[10px] bg-purple-500/10 text-purple-400 border-purple-500/30">
                {result.chunks_processed} chunks
              </Badge>
            )}
            <Badge variant="outline" className="text-[10px] bg-emerald-500/10 text-emerald-400 border-emerald-500/30">
              {result.nodes_created} nodes
            </Badge>
            <Badge variant="outline" className="text-[10px] bg-blue-500/10 text-blue-400 border-blue-500/30">
              {result.edges_created} edges
            </Badge>
            <Badge variant="outline" className="text-[10px] bg-amber-500/10 text-amber-400 border-amber-500/30">
              {result.statements_created} statements
            </Badge>
            <Badge variant="outline" className="text-[10px]">
              {result.inference_source}
            </Badge>
            <Badge variant="outline" className="text-[10px]">
              {(result.latency_ms / 1000).toFixed(1)}s
            </Badge>
          </div>
        </div>
      )}
    </div>
  );
}
