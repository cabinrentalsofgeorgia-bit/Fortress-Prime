"use client";

import { FormEvent, useMemo, useRef, useState } from "react";
import { ConciergeBell, LoaderCircle, SendHorizonal, Sparkles } from "lucide-react";
import { askConcierge } from "@/app/actions/chat";
import { Button } from "@/components/ui/button";
import { Textarea } from "@/components/ui/textarea";

type ConciergeMessage = {
  role: "user" | "agent";
  content: string;
};

interface SovereignConciergeWidgetProps {
  propertyId: string;
}

const OFFLINE_MESSAGE = "The Concierge is temporarily offline. Please try again in a moment.";

export function SovereignConciergeWidget({
  propertyId,
}: SovereignConciergeWidgetProps) {
  const [draft, setDraft] = useState("");
  const [isLoading, setIsLoading] = useState(false);
  const [history, setHistory] = useState<ConciergeMessage[]>([
    {
      role: "agent",
      content:
        "Ask about amenities, arrival details, or house rules and I will answer from this cabin's verified knowledge base.",
    },
  ]);
  const formRef = useRef<HTMLFormElement | null>(null);

  const canSubmit = useMemo(
    () => draft.trim().length > 0 && !isLoading,
    [draft, isLoading],
  );

  async function handleSubmit(event: FormEvent<HTMLFormElement>): Promise<void> {
    event.preventDefault();

    const nextMessage = draft.trim();
    if (!nextMessage || isLoading) {
      return;
    }

    setHistory((current) => [...current, { role: "user", content: nextMessage }]);
    setDraft("");
    setIsLoading(true);

    try {
      const response = await askConcierge(propertyId, nextMessage);
      setHistory((current) => [...current, { role: "agent", content: response }]);
      formRef.current?.reset();
    } catch (error) {
      const message = error instanceof Error && error.message.trim()
        ? error.message
        : OFFLINE_MESSAGE;
      setHistory((current) => [...current, { role: "agent", content: message }]);
    } finally {
      setIsLoading(false);
    }
  }

  return (
    <section
      data-testid="sovereign-concierge-widget"
      className="rounded-[2rem] border border-slate-200 bg-white p-6 shadow-sm sm:p-8"
    >
      <div className="flex flex-col gap-4 sm:flex-row sm:items-start sm:justify-between">
        <div className="space-y-3">
          <div className="inline-flex items-center gap-2 rounded-full border border-slate-200 bg-slate-50 px-3 py-1 text-xs font-medium uppercase tracking-[0.22em] text-slate-600">
            <ConciergeBell className="h-3.5 w-3.5" />
            Sovereign Concierge
          </div>
          <div className="space-y-2">
            <h2 className="text-2xl font-semibold tracking-tight text-slate-900">
              Ask the cabin concierge
            </h2>
            <p className="max-w-2xl text-sm leading-7 text-slate-600">
              Questions stay grounded to this specific property through a secure server action proxy.
            </p>
          </div>
        </div>

        <div className="inline-flex items-center gap-2 self-start rounded-full bg-emerald-50 px-3 py-1 text-xs font-medium uppercase tracking-[0.18em] text-emerald-700">
          <Sparkles className="h-3.5 w-3.5" />
          Local RAG online
        </div>
      </div>

      <div className="mt-6 rounded-[1.5rem] border border-slate-200 bg-slate-50 p-4 sm:p-5">
        <div data-testid="concierge-history" className="max-h-[26rem] space-y-3 overflow-y-auto pr-1">
          {history.map((message, index) => {
            const isUser = message.role === "user";
            return (
              <div
                key={`${message.role}-${index}`}
                className={`flex ${isUser ? "justify-end" : "justify-start"}`}
              >
                <div
                  className={`max-w-[85%] rounded-2xl px-4 py-3 text-sm leading-7 shadow-sm ${
                    isUser
                      ? "bg-slate-900 text-white"
                      : "border border-slate-200 bg-white text-slate-700"
                  }`}
                  data-testid={isUser ? "concierge-user-message" : "concierge-agent-message"}
                >
                  {message.content}
                </div>
              </div>
            );
          })}

          {isLoading ? (
            <div className="flex justify-start">
              <div
                data-testid="concierge-loading"
                className="inline-flex items-center gap-2 rounded-2xl border border-slate-200 bg-white px-4 py-3 text-sm text-slate-600 shadow-sm"
              >
                <LoaderCircle className="h-4 w-4 animate-spin" />
                Concierge is checking the cabin ledger
              </div>
            </div>
          ) : null}
        </div>

        <form ref={formRef} onSubmit={handleSubmit} className="mt-4 space-y-3">
          <Textarea
            name="message"
            data-testid="concierge-input"
            value={draft}
            onChange={(event) => setDraft(event.target.value)}
            placeholder="Does this cabin have wifi, hot tub access, or house rules I should know about?"
            className="min-h-24 border-slate-300 bg-white text-slate-900"
            disabled={isLoading}
            maxLength={1200}
          />
          <div className="flex items-center justify-between gap-3">
            <p className="text-xs uppercase tracking-[0.18em] text-slate-500">
              Property-scoped answers only
            </p>
            <Button
              type="submit"
              data-testid="concierge-submit"
              disabled={!canSubmit}
              className="rounded-full bg-slate-900 px-5 text-white hover:bg-slate-800"
            >
              {isLoading ? (
                <>
                  <LoaderCircle className="h-4 w-4 animate-spin" />
                  Asking
                </>
              ) : (
                <>
                  <SendHorizonal className="h-4 w-4" />
                  Ask Concierge
                </>
              )}
            </Button>
          </div>
        </form>
      </div>
    </section>
  );
}
