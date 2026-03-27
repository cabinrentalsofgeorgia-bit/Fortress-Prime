"use client";

import { useRef, useEffect } from "react";
import { MessageSquare, Bot, User, Loader2, Send, Brain, Trash2 } from "lucide-react";
import { useStreamingChat, type ChatMessage, type StatusStep } from "@/lib/use-streaming-chat";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";

interface Props {
  propertyId: string;
}

function StatusBadge({ step }: { step: StatusStep }) {
  return (
    <div className="flex items-center gap-2 text-xs text-slate-400 py-1">
      {step.complete ? (
        <span className="h-1.5 w-1.5 rounded-full bg-green-500" />
      ) : (
        <Loader2 className="h-3 w-3 animate-spin text-teal-400" />
      )}
      <span>
        <span className="font-medium text-slate-300">{step.agent}:</span> {step.message}
      </span>
    </div>
  );
}

function MessageBubble({ msg }: { msg: ChatMessage }) {
  const isUser = msg.role === "user";

  return (
    <div className={`flex gap-3 ${isUser ? "flex-row-reverse" : ""}`}>
      <div
        className={`w-7 h-7 rounded-full flex items-center justify-center shrink-0 ${
          isUser ? "bg-blue-900/50" : "bg-teal-900/50"
        }`}
      >
        {isUser ? (
          <User className="h-4 w-4 text-blue-400" />
        ) : (
          <Bot className="h-4 w-4 text-teal-400" />
        )}
      </div>
      <div className={`max-w-[80%] space-y-1 ${isUser ? "text-right" : ""}`}>
        {msg.steps.length > 0 && (
          <div className="space-y-0.5 mb-1">
            {msg.steps.map((s, i) => (
              <StatusBadge key={i} step={s} />
            ))}
          </div>
        )}
        {msg.reasoning && (
          <details className="text-xs text-slate-500 mb-1">
            <summary className="cursor-pointer flex items-center gap-1">
              <Brain className="h-3 w-3" /> Reasoning
            </summary>
            <p className="mt-1 whitespace-pre-wrap pl-4 border-l border-slate-700">
              {msg.reasoning}
            </p>
          </details>
        )}
        {msg.content && (
          <div
            className={`rounded-lg px-3 py-2 text-sm whitespace-pre-wrap ${
              isUser
                ? "bg-blue-900/30 text-blue-100"
                : "bg-slate-800 text-slate-200"
            }`}
          >
            {msg.content}
            {msg.isStreaming && (
              <span className="inline-block w-1.5 h-4 bg-teal-400 animate-pulse ml-0.5 align-text-bottom" />
            )}
          </div>
        )}
        {msg.metadata && (
          <p className="text-[10px] text-slate-600 mt-0.5">
            {msg.metadata.model} · {msg.metadata.tokens} tok · {msg.metadata.tok_per_sec} tok/s ·{" "}
            {(msg.metadata.latency_ms / 1000).toFixed(1)}s
          </p>
        )}
      </div>
    </div>
  );
}

export function OwnerConcierge({ propertyId }: Props) {
  const { messages, isStreaming, error, send, stop, clear } = useStreamingChat({
    endpoint: `/api/owner/${propertyId}/concierge`,
    temperature: 0.3,
    maxTokens: 1024,
  });

  const inputRef = useRef<HTMLInputElement>(null);
  const scrollRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    if (scrollRef.current) {
      scrollRef.current.scrollTop = scrollRef.current.scrollHeight;
    }
  }, [messages]);

  const handleSubmit = (e: React.FormEvent) => {
    e.preventDefault();
    const value = inputRef.current?.value?.trim();
    if (!value || isStreaming) return;
    send(value);
    if (inputRef.current) inputRef.current.value = "";
  };

  return (
    <div className="flex flex-col h-[600px] border border-slate-800 rounded-lg bg-slate-950">
      {/* Header */}
      <div className="flex items-center justify-between px-4 py-3 border-b border-slate-800">
        <div className="flex items-center gap-2">
          <MessageSquare className="h-4 w-4 text-teal-400" />
          <span className="text-sm font-medium text-white">Fiduciary Concierge</span>
          <span className="text-[10px] bg-teal-900/50 text-teal-300 px-1.5 py-0.5 rounded">AI</span>
        </div>
        {messages.length > 0 && (
          <Button variant="ghost" size="sm" onClick={clear} className="text-slate-500 hover:text-slate-300">
            <Trash2 className="h-3.5 w-3.5 mr-1" />
            Clear
          </Button>
        )}
      </div>

      {/* Messages */}
      <div ref={scrollRef} className="flex-1 overflow-y-auto p-4 space-y-4">
        {messages.length === 0 && (
          <div className="flex flex-col items-center justify-center h-full text-slate-500 space-y-3">
            <Bot className="h-10 w-10 text-teal-700" />
            <p className="text-sm text-center max-w-xs">
              Ask me anything about your property finances, reservations, maintenance charges, trust account, or management contract terms.
            </p>
            <div className="flex flex-wrap gap-2 justify-center">
              {[
                "Explain my recent charges",
                "What is my current trust balance?",
                "Show my upcoming reservations",
                "Any pending maintenance?",
                "What is my maintenance minimum?",
                "How are pet fees handled?",
                "What is my management fee percentage?",
                "What are my early termination rights?",
              ].map((q) => (
                <button
                  key={q}
                  className="text-xs bg-slate-800 hover:bg-slate-700 text-slate-300 px-3 py-1.5 rounded-full transition-colors"
                  onClick={() => send(q)}
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
      </div>

      {/* Error */}
      {error && (
        <div className="mx-4 mb-2 px-3 py-2 bg-red-950/30 border border-red-900/50 rounded text-xs text-red-400">
          {error}
        </div>
      )}

      {/* Input */}
      <form onSubmit={handleSubmit} className="p-3 border-t border-slate-800 flex gap-2">
        <Input
          ref={inputRef}
          placeholder="Ask about your property finances..."
          className="bg-slate-800 border-slate-700 text-sm"
          disabled={isStreaming}
        />
        {isStreaming ? (
          <Button type="button" variant="outline" size="sm" onClick={stop} className="shrink-0">
            <Loader2 className="h-4 w-4 animate-spin mr-1" />
            Stop
          </Button>
        ) : (
          <Button type="submit" size="sm" className="bg-teal-700 hover:bg-teal-600 shrink-0">
            <Send className="h-4 w-4" />
          </Button>
        )}
      </form>
    </div>
  );
}
