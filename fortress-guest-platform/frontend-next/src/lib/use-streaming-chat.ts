"use client";

import { useCallback, useReducer, useRef } from "react";
import { getToken } from "@/lib/api";

/* ── SSE Event Protocol ─────────────────────────────────────────────── */

export interface StatusStep {
  agent: string;
  message: string;
  complete: boolean;
}

export interface ComponentEvent {
  name: string;
  props: Record<string, unknown>;
}

export interface DoneMetadata {
  model: string;
  model_id: string;
  tokens: number;
  latency_ms: number;
  tok_per_sec: number;
  tools_used?: string[];
  grounded?: boolean;
}

export interface ChatMessage {
  id: string;
  role: "user" | "assistant";
  content: string;
  reasoning: string;
  steps: StatusStep[];
  components: ComponentEvent[];
  metadata: DoneMetadata | null;
  isStreaming: boolean;
}

/* ── State & Reducer ────────────────────────────────────────────────── */

interface State {
  messages: ChatMessage[];
  isStreaming: boolean;
  error: string | null;
}

type Action =
  | { type: "ADD_USER"; content: string }
  | { type: "START_ASSISTANT" }
  | { type: "STATUS"; agent: string; message: string }
  | { type: "THOUGHT"; content: string }
  | { type: "TOKEN"; content: string }
  | { type: "COMPONENT"; name: string; props: Record<string, unknown> }
  | { type: "DONE"; meta: DoneMetadata }
  | { type: "ERROR"; error: string }
  | { type: "ABORT" }
  | { type: "CLEAR" };

function makeMsg(
  role: "user" | "assistant",
  content: string,
  streaming = false
): ChatMessage {
  return {
    id: crypto.randomUUID(),
    role,
    content,
    reasoning: "",
    steps: [],
    components: [],
    metadata: null,
    isStreaming: streaming,
  };
}

function updateLast(msgs: ChatMessage[], updater: (m: ChatMessage) => ChatMessage): ChatMessage[] {
  if (msgs.length === 0) return msgs;
  const out = [...msgs];
  out[out.length - 1] = updater(out[out.length - 1]);
  return out;
}

function reducer(state: State, action: Action): State {
  switch (action.type) {
    case "ADD_USER":
      return {
        ...state,
        messages: [...state.messages, makeMsg("user", action.content)],
      };

    case "START_ASSISTANT":
      return {
        ...state,
        isStreaming: true,
        error: null,
        messages: [...state.messages, makeMsg("assistant", "", true)],
      };

    case "STATUS":
      return {
        ...state,
        messages: updateLast(state.messages, (m) => ({
          ...m,
          steps: [
            ...m.steps.map((s) => ({ ...s, complete: true })),
            { agent: action.agent, message: action.message, complete: false },
          ],
        })),
      };

    case "THOUGHT":
      return {
        ...state,
        messages: updateLast(state.messages, (m) => ({
          ...m,
          reasoning: m.reasoning + action.content,
        })),
      };

    case "TOKEN":
      return {
        ...state,
        messages: updateLast(state.messages, (m) => ({
          ...m,
          content: m.content + action.content,
        })),
      };

    case "COMPONENT":
      return {
        ...state,
        messages: updateLast(state.messages, (m) => ({
          ...m,
          components: [...m.components, { name: action.name, props: action.props }],
        })),
      };

    case "DONE":
      return {
        ...state,
        isStreaming: false,
        messages: updateLast(state.messages, (m) => ({
          ...m,
          isStreaming: false,
          metadata: action.meta,
          steps: m.steps.map((s) => ({ ...s, complete: true })),
        })),
      };

    case "ERROR":
      return {
        ...state,
        isStreaming: false,
        error: action.error,
        messages: updateLast(state.messages, (m) => ({
          ...m,
          isStreaming: false,
        })),
      };

    case "ABORT":
      return {
        ...state,
        isStreaming: false,
        messages: updateLast(state.messages, (m) => ({
          ...m,
          isStreaming: false,
        })),
      };

    case "CLEAR":
      return { messages: [], isStreaming: false, error: null };

    default:
      return state;
  }
}

/* ── Hook ───────────────────────────────────────────────────────────── */

interface UseStreamingChatOptions {
  endpoint?: string;
  model?: string;
  maxTokens?: number;
  temperature?: number;
  systemPrompt?: string;
}

export function useStreamingChat(opts: UseStreamingChatOptions = {}) {
  const {
    endpoint = "/api/intelligence/stream",
    model = "auto",
    maxTokens = 2048,
    temperature = 0.7,
    systemPrompt,
  } = opts;

  const [state, dispatch] = useReducer(reducer, {
    messages: [],
    isStreaming: false,
    error: null,
  });

  const abortRef = useRef<AbortController | null>(null);

  const send = useCallback(
    async (userMessage: string) => {
      if (state.isStreaming) return;

      dispatch({ type: "ADD_USER", content: userMessage });
      dispatch({ type: "START_ASSISTANT" });

      const controller = new AbortController();
      abortRef.current = controller;

      const conversationMessages = [
        ...state.messages
          .filter((m) => m.role === "user" || (m.role === "assistant" && m.content))
          .map((m) => ({ role: m.role, content: m.content })),
        { role: "user" as const, content: userMessage },
      ];

      const token = getToken();
      const headers: Record<string, string> = {
        "Content-Type": "application/json",
      };
      if (token) headers["Authorization"] = `Bearer ${token}`;

      try {
        const res = await fetch(endpoint, {
          method: "POST",
          headers,
          body: JSON.stringify({
            messages: conversationMessages,
            model,
            max_tokens: maxTokens,
            temperature,
            system_prompt: systemPrompt,
          }),
          signal: controller.signal,
        });

        if (!res.ok) {
          const text = await res.text();
          dispatch({ type: "ERROR", error: `HTTP ${res.status}: ${text.slice(0, 200)}` });
          return;
        }

        if (!res.body) {
          dispatch({ type: "ERROR", error: "No response body" });
          return;
        }

        const reader = res.body.getReader();
        const decoder = new TextDecoder();
        let buffer = "";

        while (true) {
          const { done, value } = await reader.read();
          if (done) break;

          buffer += decoder.decode(value, { stream: true });

          const lines = buffer.split("\n");
          buffer = lines.pop() ?? "";

          for (const line of lines) {
            const trimmed = line.trim();
            if (!trimmed.startsWith("data: ")) continue;

            try {
              const event = JSON.parse(trimmed.slice(6));

              switch (event.type) {
                case "status":
                  dispatch({
                    type: "STATUS",
                    agent: event.agent ?? "",
                    message: event.message ?? "",
                  });
                  break;
                case "thought":
                  dispatch({ type: "THOUGHT", content: event.content ?? "" });
                  break;
                case "token":
                  dispatch({ type: "TOKEN", content: event.content ?? "" });
                  break;
                case "component":
                  dispatch({
                    type: "COMPONENT",
                    name: event.name ?? "Card",
                    props: event.props ?? {},
                  });
                  break;
                case "done":
                  dispatch({
                    type: "DONE",
                    meta: {
                      model: event.model ?? "",
                      model_id: event.model_id ?? "",
                      tokens: event.tokens ?? 0,
                      latency_ms: event.latency_ms ?? 0,
                      tok_per_sec: event.tok_per_sec ?? 0,
                    },
                  });
                  break;
                default:
                  break;
              }
            } catch {
              // skip malformed SSE frames
            }
          }
        }

        // If stream ended without a "done" event, finalize
        if (state.isStreaming) {
          dispatch({
            type: "DONE",
            meta: { model: "", model_id: "", tokens: 0, latency_ms: 0, tok_per_sec: 0 },
          });
        }
      } catch (err) {
        if (err instanceof DOMException && err.name === "AbortError") {
          dispatch({ type: "ABORT" });
          return;
        }
        dispatch({
          type: "ERROR",
          error: err instanceof Error ? err.message : "Unknown error",
        });
      } finally {
        abortRef.current = null;
      }
    },
    // eslint-disable-next-line react-hooks/exhaustive-deps
    [state.messages, state.isStreaming, endpoint, model, maxTokens, temperature, systemPrompt]
  );

  const stop = useCallback(() => {
    abortRef.current?.abort();
    dispatch({ type: "ABORT" });
  }, []);

  const clear = useCallback(() => {
    abortRef.current?.abort();
    dispatch({ type: "CLEAR" });
  }, []);

  return {
    messages: state.messages,
    isStreaming: state.isStreaming,
    error: state.error,
    send,
    stop,
    clear,
  };
}
