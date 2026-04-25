"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import { api } from "@/lib/api";
import { Badge } from "@/components/ui/badge";
import { ScrollArea } from "@/components/ui/scroll-area";
import { Archive, CheckCircle, Clock, Loader2, Lock, Upload, XCircle } from "lucide-react";
import { toast } from "sonner";

type ProcessingStatus =
  | "pending"
  | "vectorizing"
  | "completed"
  | "failed"
  | "ocr_failed"
  | "locked_privileged"
  | "duplicate";

type VaultDocument = {
  id: string;
  file_name: string;
  mime_type: string;
  file_size_bytes: number;
  chunk_count: number;
  processing_status: ProcessingStatus;
  error_detail?: string | null;
  created_at: string;
};

// PR G — vault-document filter: which buckets to render in the ledger.
type VaultFilter = "all" | "evidence" | "privileged";

type VaultListResponse = {
  case_slug: string;
  documents: VaultDocument[];
  total: number;
};

type EdiscoveryDropzoneProps = {
  slug: string;
};

const STATUS_ICON: Record<string, React.ReactNode> = {
  pending: <Clock className="h-3 w-3 text-zinc-400" />,
  vectorizing: <Loader2 className="h-3 w-3 text-blue-400 animate-spin" />,
  completed: <CheckCircle className="h-3 w-3 text-emerald-400" />,
  failed: <XCircle className="h-3 w-3 text-red-400" />,
  ocr_failed: <XCircle className="h-3 w-3 text-amber-400" />,
  locked_privileged: <Lock className="h-3 w-3 text-purple-400" />,
  duplicate: <CheckCircle className="h-3 w-3 text-zinc-500" />,
};

// PR G — distinguish privileged docs from work product. Privileged docs land
// in legal_privileged_communications (Council retrieves them on the
// privileged track only). Everything else is evidence / work product.
const PRIVILEGED_STATUSES = new Set<ProcessingStatus>(["locked_privileged"]);

function isPrivileged(doc: VaultDocument): boolean {
  return PRIVILEGED_STATUSES.has(doc.processing_status);
}

function formatBytes(bytes: number): string {
  if (bytes < 1024) return `${bytes} B`;
  if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(1)} KB`;
  return `${(bytes / (1024 * 1024)).toFixed(1)} MB`;
}

export function EdiscoveryDropzone({ slug }: EdiscoveryDropzoneProps) {
  const [docs, setDocs] = useState<VaultDocument[]>([]);
  const [uploading, setUploading] = useState(false);
  const [dragOver, setDragOver] = useState(false);
  const [filter, setFilter] = useState<VaultFilter>("all");
  const inputRef = useRef<HTMLInputElement>(null);

  const visibleDocs = docs.filter((d) => {
    if (filter === "all") return true;
    if (filter === "privileged") return isPrivileged(d);
    return !isPrivileged(d);   // "evidence" — everything except privileged
  });
  const privilegedCount = docs.filter(isPrivileged).length;
  const evidenceCount = docs.length - privilegedCount;

  const loadDocs = useCallback(async () => {
    try {
      const res = await api.get<VaultListResponse>(`/api/internal/legal/cases/${slug}/vault/documents`);
      setDocs(res?.documents ?? []);
    } catch {
      /* silent */
    }
  }, [slug]);

  useEffect(() => {
    const initialLoad = setTimeout(() => {
      void loadDocs();
    }, 0);
    const interval = setInterval(loadDocs, 5000);
    return () => {
      clearTimeout(initialLoad);
      clearInterval(interval);
    };
  }, [loadDocs]);

  async function uploadFiles(files: FileList | File[]) {
    setUploading(true);
    let uploaded = 0;
    for (const file of Array.from(files)) {
      try {
        const formData = new FormData();
        formData.append("file", file);
        const token = typeof window !== "undefined" ? localStorage.getItem("fgp_token") : null;
        const headers: Record<string, string> = {};
        if (token) headers["Authorization"] = `Bearer ${token}`;

        const res = await fetch(`/api/internal/legal/cases/${slug}/vault/upload`, {
          method: "POST",
          headers,
          body: formData,
        });
        if (!res.ok) {
          const detail = await res.text().catch(() => res.statusText);
          toast.error(`Failed: ${file.name} — ${detail}`);
        } else {
          uploaded++;
        }
      } catch {
        toast.error(`Upload error: ${file.name}`);
      }
    }
    if (uploaded > 0) {
      toast.success(`${uploaded} file(s) queued for vectorization`);
      setTimeout(loadDocs, 1000);
    }
    setUploading(false);
  }

  function handleDrop(e: React.DragEvent) {
    e.preventDefault();
    setDragOver(false);
    if (e.dataTransfer.files.length > 0) uploadFiles(e.dataTransfer.files);
  }

  const hasProcessing = docs.some((d) => d.processing_status === "pending" || d.processing_status === "vectorizing");

  return (
    <div className="rounded-lg border border-zinc-800 bg-zinc-950/80 p-4 space-y-3">
      <div className="flex items-center gap-2">
        <Archive className="h-4 w-4 text-purple-400" />
        <p className="text-sm font-semibold text-zinc-100">E-Discovery Vault</p>
        <Badge variant="outline" className="text-[10px] ml-auto">{docs.length} files</Badge>
      </div>

      <div
        onDragOver={(e) => { e.preventDefault(); setDragOver(true); }}
        onDragLeave={() => setDragOver(false)}
        onDrop={handleDrop}
        onClick={() => inputRef.current?.click()}
        className={`rounded-lg border-2 border-dashed p-6 text-center cursor-pointer transition ${
          dragOver
            ? "border-purple-500 bg-purple-500/10"
            : "border-zinc-700 hover:border-zinc-500"
        }`}
      >
        <input
          ref={inputRef}
          type="file"
          multiple
          accept=".pdf,.txt,.csv,.doc,.docx"
          className="hidden"
          onChange={(e) => e.target.files && uploadFiles(e.target.files)}
        />
        {uploading ? (
          <div className="flex items-center justify-center gap-2 text-zinc-400">
            <Loader2 className="h-5 w-5 animate-spin" />
            <span className="text-sm">Uploading...</span>
          </div>
        ) : (
          <div className="space-y-1">
            <Upload className="h-6 w-6 mx-auto text-zinc-500" />
            <p className="text-xs text-zinc-400">Drop PDFs, TXT, or CSV here — or click to browse</p>
            <p className="text-[10px] text-zinc-500">Multi-file supported · 50MB max per file</p>
          </div>
        )}
      </div>

      {docs.length > 0 && (
        <div>
          <div className="flex items-center justify-between mb-2 gap-2 flex-wrap">
            <p className="text-[10px] uppercase tracking-wider text-zinc-500 font-semibold">Vault Ledger</p>
            <div className="flex items-center gap-2">
              {/* PR G — show only evidence / only privileged / both */}
              <div className="flex items-center gap-1 rounded-md bg-zinc-900/60 p-0.5 text-[10px]">
                {(["all", "evidence", "privileged"] as VaultFilter[]).map((f) => (
                  <button
                    key={f}
                    onClick={() => setFilter(f)}
                    className={`px-2 py-0.5 rounded transition ${
                      filter === f
                        ? "bg-zinc-700 text-zinc-100"
                        : "text-zinc-400 hover:text-zinc-200"
                    }`}
                    aria-pressed={filter === f}
                  >
                    {f === "all" && `All (${docs.length})`}
                    {f === "evidence" && `Evidence (${evidenceCount})`}
                    {f === "privileged" && (
                      <span className="inline-flex items-center gap-1">
                        <Lock className="h-2.5 w-2.5" />
                        Privileged ({privilegedCount})
                      </span>
                    )}
                  </button>
                ))}
              </div>
              {hasProcessing && (
                <Badge variant="outline" className="text-[9px] bg-blue-500/10 text-blue-400 border-blue-500/30 animate-pulse">
                  Processing...
                </Badge>
              )}
            </div>
          </div>
          <ScrollArea className="max-h-48">
            <div className="space-y-1">
              {visibleDocs.map((doc) => {
                const priv = isPrivileged(doc);
                return (
                  <div
                    key={doc.id}
                    className={`rounded border px-3 py-2 flex items-center gap-3 ${
                      priv
                        ? "border-purple-500/40 bg-purple-500/5"
                        : "border-zinc-800 bg-zinc-900/50"
                    }`}
                  >
                    {STATUS_ICON[doc.processing_status] ?? STATUS_ICON.pending}
                    <div className="flex-1 min-w-0">
                      <p className="text-xs text-zinc-200 truncate flex items-center gap-1.5">
                        {doc.file_name}
                        {priv && (
                          <Badge
                            variant="outline"
                            className="text-[9px] text-purple-300 border-purple-500/40 bg-purple-500/10 gap-0.5"
                          >
                            <Lock className="h-2 w-2" />
                            Privileged
                          </Badge>
                        )}
                      </p>
                      <p className="text-[10px] text-zinc-500">
                        {formatBytes(doc.file_size_bytes)}
                        {doc.chunk_count > 0 && ` · ${doc.chunk_count} chunks`}
                        {doc.error_detail && ` · ${doc.error_detail.slice(0, 60)}`}
                      </p>
                    </div>
                    <Badge
                      variant="outline"
                      className={`text-[9px] ${
                        doc.processing_status === "completed"
                          ? "text-emerald-400 border-emerald-500/30"
                          : doc.processing_status === "failed"
                            ? "text-red-400 border-red-500/30"
                            : doc.processing_status === "locked_privileged"
                              ? "text-purple-300 border-purple-500/40"
                              : doc.processing_status === "ocr_failed"
                                ? "text-amber-400 border-amber-500/30"
                                : "text-zinc-400 border-zinc-600"
                      }`}
                    >
                      {doc.processing_status}
                    </Badge>
                  </div>
                );
              })}
              {visibleDocs.length === 0 && (
                <p className="text-[10px] text-zinc-500 italic px-3 py-2">
                  No documents match the {filter} filter.
                </p>
              )}
            </div>
          </ScrollArea>
        </div>
      )}
    </div>
  );
}
