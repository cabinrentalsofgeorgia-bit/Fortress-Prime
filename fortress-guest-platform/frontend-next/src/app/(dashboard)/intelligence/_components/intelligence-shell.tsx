"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import ReactMarkdown from "react-markdown";
import remarkGfm from "remark-gfm";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Badge } from "@/components/ui/badge";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import {
  useStreamingChat,
  type ChatMessage,
  type StatusStep,
  type ComponentEvent,
} from "@/lib/use-streaming-chat";
import {
  Brain,
  CircleStop,
  Cpu,
  Loader2,
  Send,
  Sparkles,
  Timer,
  Trash2,
  User,
  Zap,
  CheckCircle2,
  AlertCircle,
  ChevronDown,
} from "lucide-react";

/* ── Generative UI Component Registry ───────────────────────────────── */

function GenericComponentCard({ name, props }: { name: string; props: Record<string, unknown> }) {
  return (
    <Card className="my-3 border-primary/30 bg-primary/5">
      <CardHeader className="pb-2">
        <CardTitle className="text-sm flex items-center gap-2">
          <Sparkles className="h-4 w-4 text-primary" />
          {name}
        </CardTitle>
      </CardHeader>
      <CardContent className="text-sm">
        <pre className="overflow-x-auto rounded bg-muted p-3 text-xs">
          {JSON.stringify(props, null, 2)}
        </pre>
      </CardContent>
    </Card>
  );
}

function CaseCard({ props }: { props: Record<string, unknown> }) {
  const caseNum = props.case_number != null ? String(props.case_number) : null;
  const court = props.court != null ? String(props.court) : null;
  const risk = props.risk_score != null ? Number(props.risk_score) : null;
  const critDate = props.critical_date != null ? String(props.critical_date) : null;
  const ourRole = props.our_role != null ? String(props.our_role) : null;
  const status = props.status != null ? String(props.status) : null;
  const slug = props.case_slug != null ? String(props.case_slug) : null;

  return (
    <Card className="my-3 border-yellow-500/30 bg-yellow-500/5">
      <CardHeader className="pb-2">
        <CardTitle className="text-sm flex items-center gap-2">
          <AlertCircle className="h-4 w-4 text-yellow-500" />
          Legal Case: {String(props.case_name ?? props.name ?? "Unknown")}
        </CardTitle>
      </CardHeader>
      <CardContent className="space-y-1 text-sm">
        {caseNum && <p><span className="text-muted-foreground">Case #:</span> {caseNum}</p>}
        {court && <p><span className="text-muted-foreground">Court:</span> {court}</p>}
        <div className="flex flex-wrap gap-2 pt-1">
          {ourRole && (
            <Badge variant="outline" className="capitalize">
              {ourRole}
            </Badge>
          )}
          {status && (
            <Badge variant={status === "active" ? "default" : "secondary"} className="capitalize">
              {status}
            </Badge>
          )}
          {risk !== null && (
            <Badge variant={risk >= 4 ? "destructive" : "secondary"}>
              Risk {risk}/5
            </Badge>
          )}
        </div>
        {critDate && <p className="pt-1"><span className="text-muted-foreground">Critical Date:</span> {critDate}</p>}
        {slug && (
          <a href={`/legal/cases/${slug}`} className="text-xs text-primary hover:underline">
            View Full Case →
          </a>
        )}
      </CardContent>
    </Card>
  );
}

const COMPONENT_REGISTRY: Record<string, React.ComponentType<{ props: Record<string, unknown> }>> = {
  CaseCard,
  CaseDetailCard: CaseCard,
  PropertyCard: ({ props }) => <GenericComponentCard name="Property" props={props} />,
  ReservationCard: ({ props }) => <GenericComponentCard name="Reservation" props={props} />,
};

function RenderComponent({ event }: { event: ComponentEvent }) {
  const Component = COMPONENT_REGISTRY[event.name];
  if (Component) return <Component props={event.props} />;
  return <GenericComponentCard name={event.name} props={event.props} />;
}

/* ── Chain-of-Thought Steps ─────────────────────────────────────────── */

function ThoughtProcess({ steps }: { steps: StatusStep[] }) {
  if (steps.length === 0) return null;
  return (
    <div className="mb-3 space-y-1.5">
      {steps.map((step, i) => (
        <div
          key={i}
          className="flex items-center gap-2 text-xs text-muted-foreground animate-in fade-in slide-in-from-left-2 duration-300"
        >
          {step.complete ? (
            <CheckCircle2 className="h-3.5 w-3.5 text-emerald-500 shrink-0" />
          ) : (
            <Loader2 className="h-3.5 w-3.5 animate-spin text-primary shrink-0" />
          )}
          <span className="font-medium text-foreground/70">{step.agent}</span>
          <span className="text-muted-foreground">{step.message}</span>
        </div>
      ))}
    </div>
  );
}

/* ── Reasoning Accordion (live-streamed R1 thoughts) ───────────────── */

function ReasoningAccordion({
  reasoning,
  isStreaming,
}: {
  reasoning: string;
  isStreaming: boolean;
}) {
  const endRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    endRef.current?.scrollIntoView({ block: "nearest" });
  }, [reasoning]);

  if (!reasoning) return null;

  return (
    <details open className="mb-3 group">
      <summary className="flex cursor-pointer items-center gap-2 text-xs text-muted-foreground select-none list-none">
        {isStreaming ? (
          <Loader2 className="h-3.5 w-3.5 animate-spin text-violet-400 shrink-0" />
        ) : (
          <Brain className="h-3.5 w-3.5 text-violet-400 shrink-0" />
        )}
        <span className="font-medium text-violet-400">
          {isStreaming ? "Thinking…" : "Reasoning"}
        </span>
        <ChevronDown className="h-3 w-3 transition-transform group-open:rotate-180" />
      </summary>
      <div className="mt-2 max-h-60 overflow-y-auto rounded-lg border border-violet-500/20 bg-violet-500/5 px-3 py-2 text-xs leading-relaxed text-muted-foreground font-mono whitespace-pre-wrap">
        {reasoning}
        {isStreaming && (
          <span className="inline-block h-3 w-1 animate-pulse rounded-sm bg-violet-400 ml-0.5 align-middle" />
        )}
        <div ref={endRef} />
      </div>
    </details>
  );
}

/* ── Message Bubble ─────────────────────────────────────────────────── */

function MessageBubble({ msg }: { msg: ChatMessage }) {
  const isUser = msg.role === "user";

  return (
    <div className={`flex gap-3 ${isUser ? "justify-end" : "justify-start"}`}>
      {!isUser && (
        <div className="flex h-8 w-8 shrink-0 items-center justify-center rounded-full bg-primary/10 mt-0.5">
          <Brain className="h-4 w-4 text-primary" />
        </div>
      )}

      <div className={`max-w-[80%] space-y-1 ${isUser ? "items-end" : "items-start"}`}>
        {isUser ? (
          <div className="rounded-2xl rounded-tr-sm bg-primary px-4 py-2.5 text-sm text-primary-foreground">
            {msg.content}
          </div>
        ) : (
          <div className="space-y-0">
            <ThoughtProcess steps={msg.steps} />

            <ReasoningAccordion
              reasoning={msg.reasoning}
              isStreaming={msg.isStreaming && !msg.content}
            />

            {msg.content && (
              <div className="prose prose-sm prose-invert max-w-none rounded-2xl rounded-tl-sm bg-muted/50 px-4 py-3 text-sm">
                <ReactMarkdown
                  remarkPlugins={[remarkGfm]}
                  components={{
                    pre: ({ children }) => (
                      <pre className="overflow-x-auto rounded-lg bg-black/50 p-3 text-xs">{children}</pre>
                    ),
                    code: ({ children, className }) => {
                      const isBlock = className?.startsWith("language-");
                      if (isBlock) return <code className={className}>{children}</code>;
                      return (
                        <code className="rounded bg-black/30 px-1.5 py-0.5 text-xs font-mono text-emerald-400">
                          {children}
                        </code>
                      );
                    },
                    table: ({ children }) => (
                      <div className="overflow-x-auto my-2">
                        <table className="min-w-full text-xs border border-border/50">{children}</table>
                      </div>
                    ),
                    th: ({ children }) => (
                      <th className="border border-border/50 bg-muted/50 px-3 py-1.5 text-left font-medium">{children}</th>
                    ),
                    td: ({ children }) => (
                      <td className="border border-border/50 px-3 py-1.5">{children}</td>
                    ),
                  }}
                >
                  {msg.content}
                </ReactMarkdown>
                {msg.isStreaming && (
                  <span className="inline-block h-4 w-1.5 animate-pulse rounded-sm bg-primary ml-0.5" />
                )}
              </div>
            )}

            {!msg.content && msg.isStreaming && !msg.reasoning && msg.steps.length > 0 && (
              <div className="rounded-2xl rounded-tl-sm bg-muted/50 px-4 py-3">
                <span className="inline-block h-4 w-1.5 animate-pulse rounded-sm bg-primary" />
              </div>
            )}

            {msg.components.map((comp, i) => (
              <RenderComponent key={i} event={comp} />
            ))}

            {msg.metadata && (
              <div className="flex flex-wrap items-center gap-2 pt-1 text-[10px] text-muted-foreground">
                <span className="flex items-center gap-1">
                  <Cpu className="h-3 w-3" />
                  {msg.metadata.model}
                </span>
                <span className="flex items-center gap-1">
                  <Zap className="h-3 w-3" />
                  {msg.metadata.tokens} tokens
                </span>
                <span className="flex items-center gap-1">
                  <Timer className="h-3 w-3" />
                  {(msg.metadata.latency_ms / 1000).toFixed(1)}s
                </span>
                <span>({msg.metadata.tok_per_sec} tok/s)</span>
                {msg.metadata.grounded && (
                  <Badge variant="outline" className="text-[10px] h-4 px-1.5 border-emerald-500/30 text-emerald-500">
                    Grounded
                  </Badge>
                )}
                {msg.metadata.tools_used && msg.metadata.tools_used.length > 0 && (
                  <span className="text-emerald-500/70">
                    Tools: {[...new Set(msg.metadata.tools_used)].join(", ")}
                  </span>
                )}
              </div>
            )}
          </div>
        )}
      </div>

      {isUser && (
        <div className="flex h-8 w-8 shrink-0 items-center justify-center rounded-full bg-accent mt-0.5">
          <User className="h-4 w-4" />
        </div>
      )}
    </div>
  );
}

/* ── Main Shell ─────────────────────────────────────────────────────── */

export function IntelligenceShell() {
  const [model, setModel] = useState("auto");
  const [input, setInput] = useState("");
  const { messages, isStreaming, error, send, stop, clear } = useStreamingChat({
    model,
  });

  /* ── Auto-scroll ── */
  const scrollRef = useRef<HTMLDivElement>(null);
  const bottomRef = useRef<HTMLDivElement>(null);
  const userScrolledUp = useRef(false);
  const [showScrollDown, setShowScrollDown] = useState(false);

  const scrollToBottom = useCallback(() => {
    bottomRef.current?.scrollIntoView({ behavior: "smooth" });
    userScrolledUp.current = false;
    setShowScrollDown(false);
  }, []);

  useEffect(() => {
    if (!userScrolledUp.current) {
      bottomRef.current?.scrollIntoView({ behavior: "smooth" });
    }
  }, [messages]);

  const handleScroll = useCallback(() => {
    const el = scrollRef.current;
    if (!el) return;
    const distanceFromBottom = el.scrollHeight - el.scrollTop - el.clientHeight;
    if (distanceFromBottom > 100) {
      userScrolledUp.current = true;
      setShowScrollDown(true);
    } else {
      userScrolledUp.current = false;
      setShowScrollDown(false);
    }
  }, []);

  /* ── Submit ── */
  const handleSubmit = useCallback(() => {
    const trimmed = input.trim();
    if (!trimmed || isStreaming) return;
    setInput("");
    send(trimmed);
  }, [input, isStreaming, send]);

  const handleKeyDown = useCallback(
    (e: React.KeyboardEvent) => {
      if (e.key === "Enter" && !e.shiftKey) {
        e.preventDefault();
        handleSubmit();
      }
    },
    [handleSubmit]
  );

  return (
    <div className="flex h-[calc(100vh-4rem)] flex-col">
      {/* ── Header ── */}
      <div className="flex items-center justify-between border-b px-6 py-3">
        <div className="flex items-center gap-3">
          <Brain className="h-6 w-6 text-primary" />
          <div>
            <h1 className="text-lg font-semibold">Intelligence Console</h1>
            <p className="text-xs text-muted-foreground">
              Agentic AI — tool calling, grounded responses, GPU abort protection
            </p>
          </div>
        </div>

        <div className="flex items-center gap-2">
          <Select value={model} onValueChange={setModel}>
            <SelectTrigger className="w-40 h-8 text-xs">
              <SelectValue />
            </SelectTrigger>
            <SelectContent>
              <SelectItem value="auto">Auto-Route</SelectItem>
              <SelectItem value="swarm">SWARM (Fast)</SelectItem>
              <SelectItem value="hydra">HYDRA (Deep)</SelectItem>
            </SelectContent>
          </Select>

          <Button variant="ghost" size="icon" className="h-8 w-8" onClick={clear} title="Clear chat">
            <Trash2 className="h-4 w-4" />
          </Button>
        </div>
      </div>

      {/* ── Messages ── */}
      <div
        ref={scrollRef}
        onScroll={handleScroll}
        className="flex-1 overflow-y-auto px-6 py-4 space-y-6 relative"
      >
        {messages.length === 0 && (
          <div className="flex flex-col items-center justify-center h-full text-center space-y-4 text-muted-foreground">
            <Brain className="h-16 w-16 opacity-20" />
            <div className="space-y-1">
              <p className="text-lg font-medium text-foreground/60">Fortress Intelligence</p>
              <p className="text-sm max-w-md">
                Ask about legal cases, property data, reservations, financials, or any
                operational question. The model is auto-routed based on complexity.
              </p>
            </div>
            <div className="flex flex-wrap justify-center gap-2 pt-2">
              {[
                "Summarize the Generali v. CROG case",
                "What properties have the highest occupancy?",
                "Draft a demand letter for a damage claim",
                "Analyze our Q1 revenue trends",
              ].map((q) => (
                <button
                  key={q}
                  onClick={() => {
                    setInput(q);
                    send(q);
                  }}
                  className="rounded-full border border-border/50 bg-muted/30 px-3 py-1.5 text-xs
                             transition-colors hover:bg-muted hover:text-foreground"
                >
                  {q}
                </button>
              ))}
            </div>
          </div>
        )}

        {messages.map((msg) => (
          <MessageBubble key={msg.id} msg={msg} />
        ))}

        <div ref={bottomRef} />

        {/* Scroll-to-bottom indicator */}
        {showScrollDown && (
          <button
            onClick={scrollToBottom}
            className="fixed bottom-24 right-10 z-10 flex h-8 w-8 items-center justify-center
                       rounded-full bg-primary text-primary-foreground shadow-lg
                       transition-transform hover:scale-110"
          >
            <ChevronDown className="h-4 w-4" />
          </button>
        )}
      </div>

      {/* ── Error ── */}
      {error && (
        <div className="mx-6 mb-2 rounded-lg border border-destructive/30 bg-destructive/10 px-4 py-2 text-xs text-destructive">
          {error}
        </div>
      )}

      {/* ── Input ── */}
      <div className="border-t px-6 py-3">
        <div className="flex items-end gap-2">
          <div className="relative flex-1">
            <textarea
              value={input}
              onChange={(e) => setInput(e.target.value)}
              onKeyDown={handleKeyDown}
              placeholder="Ask the Intelligence Console…"
              rows={1}
              disabled={isStreaming}
              className="w-full resize-none rounded-xl border bg-muted/30 px-4 py-3 pr-12 text-sm
                         placeholder:text-muted-foreground/50 focus:outline-none focus:ring-2
                         focus:ring-primary/30 disabled:opacity-50"
              style={{ minHeight: "44px", maxHeight: "120px" }}
              onInput={(e) => {
                const target = e.target as HTMLTextAreaElement;
                target.style.height = "auto";
                target.style.height = `${Math.min(target.scrollHeight, 120)}px`;
              }}
            />
          </div>

          {isStreaming ? (
            <Button
              onClick={stop}
              variant="destructive"
              size="icon"
              className="h-11 w-11 rounded-xl shrink-0"
              title="Stop generating (frees GPU)"
            >
              <CircleStop className="h-5 w-5" />
            </Button>
          ) : (
            <Button
              onClick={handleSubmit}
              disabled={!input.trim()}
              size="icon"
              className="h-11 w-11 rounded-xl shrink-0"
              title="Send"
            >
              <Send className="h-5 w-5" />
            </Button>
          )}
        </div>

        <p className="mt-1.5 text-center text-[10px] text-muted-foreground/50">
          {isStreaming
            ? "Streaming — click the red button to stop and free GPU VRAM"
            : "Enter to send · Shift+Enter for newline · GPU abort protection active"}
        </p>
      </div>
    </div>
  );
}
