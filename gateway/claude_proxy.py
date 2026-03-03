#!/usr/bin/env python3
"""
Anthropic ↔ OpenAI Translation Proxy for Open WebUI.

Translates:
  - Auth: Bearer token → x-api-key header
  - Request: OpenAI chat/completions format → Anthropic Messages API
  - Response: Anthropic Messages → OpenAI chat/completions format
  - Tools: OpenAI function definitions ↔ Anthropic tool definitions
  - Tool results: OpenAI tool messages ↔ Anthropic tool_result blocks

Runs on port 5100 (localhost), serves Open WebUI as an "OpenAI-compatible" endpoint.
"""

import os
import json
import asyncio
import logging
import uuid
from aiohttp import web, ClientSession

logging.basicConfig(level=logging.INFO, format="%(asctime)s [CLAUDE-PROXY] %(message)s")
log = logging.getLogger("claude_proxy")

ANTHROPIC_BASE = "https://api.anthropic.com"
ANTHROPIC_VERSION = "2023-06-01"
LISTEN_PORT = int(os.getenv("CLAUDE_PROXY_PORT", "5100"))

# Claude models to advertise
CLAUDE_MODELS = [
    {"id": "claude-opus-4-6", "name": "Claude Opus 4.6"},
    {"id": "claude-opus-4-5-20251101", "name": "Claude Opus 4.5"},
    {"id": "claude-sonnet-4-5-20250929", "name": "Claude Sonnet 4.5"},
    {"id": "claude-haiku-4-5-20251001", "name": "Claude Haiku 4.5"},
    {"id": "claude-opus-4-1-20250805", "name": "Claude Opus 4.1"},
    {"id": "claude-opus-4-20250514", "name": "Claude Opus 4"},
    {"id": "claude-sonnet-4-20250514", "name": "Claude Sonnet 4"},
    {"id": "claude-3-5-haiku-20241022", "name": "Claude Haiku 3.5"},
    {"id": "claude-3-haiku-20240307", "name": "Claude Haiku 3"},
]


def _extract_api_key(request: web.Request) -> str:
    """Extract API key from Bearer token or x-api-key header."""
    auth = request.headers.get("Authorization", "")
    if auth.startswith("Bearer "):
        return auth[7:]
    return request.headers.get("x-api-key", "")


# ─── OpenAI → Anthropic Format Translation ───────────────────────────────────


def _convert_tools_to_anthropic(openai_tools: list) -> list:
    """Convert OpenAI function definitions to Anthropic tool format."""
    anthropic_tools = []
    for tool in openai_tools:
        if tool.get("type") == "function":
            func = tool["function"]
            anthropic_tools.append({
                "name": func["name"],
                "description": func.get("description", ""),
                "input_schema": func.get("parameters", {"type": "object", "properties": {}}),
            })
        elif "name" in tool:
            # Already in a simpler format
            anthropic_tools.append({
                "name": tool["name"],
                "description": tool.get("description", ""),
                "input_schema": tool.get("parameters", {"type": "object", "properties": {}}),
            })
    return anthropic_tools


def _convert_messages_to_anthropic(messages: list) -> tuple[str | None, list]:
    """
    Convert OpenAI messages to Anthropic format.
    Returns (system_text, anthropic_messages).
    Handles: system, user, assistant, tool messages.
    """
    system_text = None
    anthropic_msgs = []

    for msg in messages:
        role = msg.get("role", "user")
        content = msg.get("content", "")

        if role == "system":
            # Accumulate system messages
            if system_text is None:
                system_text = content
            else:
                system_text += "\n\n" + content

        elif role == "user":
            anthropic_msgs.append({"role": "user", "content": content})

        elif role == "assistant":
            # Check if this assistant message had tool_calls
            tool_calls = msg.get("tool_calls", [])
            if tool_calls:
                # Build content blocks: text + tool_use blocks
                blocks = []
                if content:
                    blocks.append({"type": "text", "text": content})
                for tc in tool_calls:
                    func = tc.get("function", {})
                    try:
                        args = json.loads(func.get("arguments", "{}"))
                    except json.JSONDecodeError:
                        args = {}
                    blocks.append({
                        "type": "tool_use",
                        "id": tc.get("id", str(uuid.uuid4())),
                        "name": func.get("name", ""),
                        "input": args,
                    })
                anthropic_msgs.append({"role": "assistant", "content": blocks})
            else:
                anthropic_msgs.append({"role": "assistant", "content": content})

        elif role == "tool":
            # Tool result message → Anthropic tool_result block
            tool_call_id = msg.get("tool_call_id", "")
            anthropic_msgs.append({
                "role": "user",
                "content": [
                    {
                        "type": "tool_result",
                        "tool_use_id": tool_call_id,
                        "content": content if isinstance(content, str) else json.dumps(content),
                    }
                ],
            })

    # Anthropic requires alternating user/assistant. Merge consecutive same-role messages.
    merged = _merge_consecutive_roles(anthropic_msgs)
    return system_text, merged


def _merge_consecutive_roles(messages: list) -> list:
    """Merge consecutive messages with the same role (Anthropic requirement)."""
    if not messages:
        return messages

    merged = [messages[0]]
    for msg in messages[1:]:
        if msg["role"] == merged[-1]["role"]:
            # Merge content
            prev_content = merged[-1]["content"]
            curr_content = msg["content"]

            # Normalize to lists
            if isinstance(prev_content, str):
                prev_content = [{"type": "text", "text": prev_content}]
            if isinstance(curr_content, str):
                curr_content = [{"type": "text", "text": curr_content}]
            if isinstance(prev_content, list) and isinstance(curr_content, list):
                merged[-1]["content"] = prev_content + curr_content
            else:
                merged.append(msg)
        else:
            merged.append(msg)
    return merged


# ─── Anthropic → OpenAI Format Translation ───────────────────────────────────


def _convert_response_to_openai(anthropic_data: dict, model: str) -> dict:
    """Convert Anthropic Messages response to OpenAI chat/completions format."""
    content_blocks = anthropic_data.get("content", [])

    # Separate text and tool_use blocks
    text_parts = []
    tool_calls = []

    for block in content_blocks:
        if block.get("type") == "text":
            text_parts.append(block["text"])
        elif block.get("type") == "thinking":
            text_parts.append(f"<thinking>{block['thinking']}</thinking>")
        elif block.get("type") == "tool_use":
            tool_calls.append({
                "id": block["id"],
                "type": "function",
                "function": {
                    "name": block["name"],
                    "arguments": json.dumps(block.get("input", {})),
                },
            })

    combined_text = "\n\n".join(text_parts) if text_parts else ""
    stop_reason = anthropic_data.get("stop_reason", "end_turn")

    message = {"role": "assistant", "content": combined_text if combined_text else None}
    if tool_calls:
        message["tool_calls"] = tool_calls

    finish_reason = _map_stop_reason(stop_reason)

    return {
        "id": anthropic_data.get("id", f"chatcmpl-{uuid.uuid4().hex[:8]}"),
        "object": "chat.completion",
        "created": 1700000000,
        "model": model,
        "choices": [
            {
                "index": 0,
                "message": message,
                "finish_reason": finish_reason,
            }
        ],
        "usage": {
            "prompt_tokens": anthropic_data.get("usage", {}).get("input_tokens", 0),
            "completion_tokens": anthropic_data.get("usage", {}).get("output_tokens", 0),
            "total_tokens": (
                anthropic_data.get("usage", {}).get("input_tokens", 0)
                + anthropic_data.get("usage", {}).get("output_tokens", 0)
            ),
        },
    }


def _map_stop_reason(reason: str) -> str:
    """Map Anthropic stop reason to OpenAI finish reason."""
    return {
        "end_turn": "stop",
        "max_tokens": "length",
        "stop_sequence": "stop",
        "tool_use": "tool_calls",
    }.get(reason, "stop")


# ─── HTTP Handlers ────────────────────────────────────────────────────────────


async def handle_models(request: web.Request) -> web.Response:
    """Return available Claude models in OpenAI format."""
    return web.json_response({
        "object": "list",
        "data": [
            {
                "id": m["id"],
                "object": "model",
                "created": 1700000000,
                "owned_by": "anthropic",
            }
            for m in CLAUDE_MODELS
        ],
    })


async def handle_chat_completions(request: web.Request) -> web.Response:
    """Proxy /v1/chat/completions: full OpenAI ↔ Anthropic translation."""
    api_key = _extract_api_key(request)
    if not api_key:
        return web.json_response({"error": "No API key provided"}, status=401)

    body = await request.json()
    model = body.get("model", "claude-sonnet-4-5-20250929")
    messages = body.get("messages", [])
    stream = body.get("stream", False)
    max_tokens = body.get("max_tokens", 8192)
    temperature = body.get("temperature")
    openai_tools = body.get("tools", [])

    # Debug: log request summary
    log.info(f"REQUEST model={model} stream={stream} tools={len(openai_tools)} msgs={len(messages)}")

    # Dump full request to file for debugging (overwrite each time)
    try:
        with open("/tmp/claude_proxy_last_request.json", "w") as f:
            json.dump(body, f, indent=2, default=str)
    except Exception:
        pass

    # ── Translate messages ──
    system_text, anthropic_messages = _convert_messages_to_anthropic(messages)

    # ── Build Anthropic request ──
    anthropic_body = {
        "model": model,
        "messages": anthropic_messages,
        "max_tokens": max_tokens,
    }
    if system_text:
        anthropic_body["system"] = system_text
    if temperature is not None:
        anthropic_body["temperature"] = temperature

    # ── Translate tools ──
    if openai_tools:
        anthropic_tools = _convert_tools_to_anthropic(openai_tools)
        if anthropic_tools:
            anthropic_body["tools"] = anthropic_tools
            log.info(f"Forwarding {len(anthropic_tools)} tools to Anthropic")

    anthropic_headers = {
        "x-api-key": api_key,
        "anthropic-version": ANTHROPIC_VERSION,
        "content-type": "application/json",
    }

    if stream:
        return await _stream_response(request, anthropic_headers, anthropic_body, model)
    else:
        return await _sync_response(anthropic_headers, anthropic_body, model)


async def _sync_response(headers: dict, body: dict, model: str) -> web.Response:
    """Non-streaming: call Anthropic and convert response to OpenAI format."""
    async with ClientSession() as session:
        async with session.post(
            f"{ANTHROPIC_BASE}/v1/messages", headers=headers, json=body
        ) as resp:
            if resp.status != 200:
                error_text = await resp.text()
                log.error(f"Anthropic error {resp.status}: {error_text[:500]}")
                return web.Response(
                    text=error_text, status=resp.status,
                    content_type="application/json"
                )
            data = await resp.json()

    openai_response = _convert_response_to_openai(data, model)

    # Log tool usage
    tc = openai_response["choices"][0]["message"].get("tool_calls", [])
    if tc:
        log.info(f"Claude requested {len(tc)} tool calls: {[t['function']['name'] for t in tc]}")

    return web.json_response(openai_response)


async def _stream_response(
    request: web.Request, headers: dict, body: dict, model: str
) -> web.StreamResponse:
    """Streaming: convert Anthropic SSE stream to OpenAI SSE format.

    Handles parallel tool calls by assigning each a unique, incrementing index
    (matching OpenAI's streaming format for multiple function calls).
    """
    body["stream"] = True

    resp_out = web.StreamResponse(
        status=200,
        headers={
            "Content-Type": "text/event-stream",
            "Cache-Control": "no-cache",
            "X-Accel-Buffering": "no",
        },
    )
    await resp_out.prepare(request)

    # Track tool use blocks during streaming — supports parallel tool calls
    current_tool_use = None   # {"id": ..., "name": ..., "index": N}
    tool_call_index = 0       # Increments for each parallel tool call in one response

    async with ClientSession() as session:
        async with session.post(
            f"{ANTHROPIC_BASE}/v1/messages", headers=headers, json=body
        ) as resp:
            if resp.status != 200:
                error_text = await resp.text()
                log.error(f"Stream error {resp.status}: {error_text[:300]}")
                err = {
                    "id": "error",
                    "object": "chat.completion.chunk",
                    "model": model,
                    "choices": [{"index": 0, "delta": {"content": f"[API Error: {error_text[:200]}]"}, "finish_reason": "stop"}],
                }
                await resp_out.write(f"data: {json.dumps(err)}\n\n".encode())
                await resp_out.write(b"data: [DONE]\n\n")
                return resp_out

            buffer = ""
            async for chunk in resp.content:
                buffer += chunk.decode("utf-8", errors="replace")
                while "\n" in buffer:
                    line, buffer = buffer.split("\n", 1)
                    line = line.strip()
                    if not line or line.startswith(":"):
                        continue
                    if line.startswith("event: "):
                        continue
                    if line.startswith("data: "):
                        data_str = line[6:]
                        try:
                            event = json.loads(data_str)
                            signals = _convert_stream_event(event, model, current_tool_use)
                            for sig in signals:
                                if sig == "__TOOL_START__":
                                    # New tool call — assign unique index, emit initial chunk
                                    cb = event.get("content_block", {})
                                    current_tool_use = {
                                        "id": cb.get("id", str(uuid.uuid4())),
                                        "name": cb.get("name", ""),
                                        "index": tool_call_index,
                                    }
                                    # Emit the initial chunk (name + empty arguments)
                                    init_chunk = {
                                        "id": f"chatcmpl-{uuid.uuid4().hex[:8]}",
                                        "object": "chat.completion.chunk",
                                        "created": 1700000000,
                                        "model": model,
                                        "choices": [{
                                            "index": 0,
                                            "delta": {
                                                "tool_calls": [{
                                                    "index": tool_call_index,
                                                    "id": current_tool_use["id"],
                                                    "type": "function",
                                                    "function": {
                                                        "name": current_tool_use["name"],
                                                        "arguments": "",
                                                    },
                                                }],
                                            },
                                            "finish_reason": None,
                                        }],
                                    }
                                    await resp_out.write(f"data: {json.dumps(init_chunk)}\n\n".encode())
                                    tool_call_index += 1
                                    log.info(f"Tool call #{current_tool_use['index']}: {current_tool_use['name']}")

                                elif sig == "__TOOL_DELTA__":
                                    # Stream argument JSON deltas with correct index
                                    delta = event.get("delta", {})
                                    if current_tool_use and delta.get("type") == "input_json_delta":
                                        partial = delta.get("partial_json", "")
                                        if partial:
                                            arg_chunk = {
                                                "id": f"chatcmpl-{uuid.uuid4().hex[:8]}",
                                                "object": "chat.completion.chunk",
                                                "created": 1700000000,
                                                "model": model,
                                                "choices": [{
                                                    "index": 0,
                                                    "delta": {
                                                        "tool_calls": [{
                                                            "index": current_tool_use["index"],
                                                            "function": {
                                                                "arguments": partial,
                                                            },
                                                        }],
                                                    },
                                                    "finish_reason": None,
                                                }],
                                            }
                                            await resp_out.write(f"data: {json.dumps(arg_chunk)}\n\n".encode())

                                elif sig == "__TOOL_END__":
                                    # Tool block complete — reset tracker
                                    current_tool_use = None

                                elif sig is not None:
                                    await resp_out.write(f"data: {json.dumps(sig)}\n\n".encode())
                        except json.JSONDecodeError:
                            pass

    await resp_out.write(b"data: [DONE]\n\n")
    return resp_out


def _convert_stream_event(event: dict, model: str, current_tool_use) -> list:
    """Convert Anthropic streaming event to OpenAI chunk(s). Returns list of items."""
    event_type = event.get("type", "")

    if event_type == "content_block_start":
        block = event.get("content_block", {})
        if block.get("type") == "tool_use":
            return ["__TOOL_START__"]
        return []

    if event_type == "content_block_delta":
        delta = event.get("delta", {})

        if delta.get("type") == "text_delta":
            text = delta.get("text", "")
            if text:
                return [{
                    "id": f"chatcmpl-{uuid.uuid4().hex[:8]}",
                    "object": "chat.completion.chunk",
                    "created": 1700000000,
                    "model": model,
                    "choices": [{
                        "index": 0,
                        "delta": {"content": text},
                        "finish_reason": None,
                    }],
                }]

        if delta.get("type") == "input_json_delta":
            return ["__TOOL_DELTA__"]

        return []

    if event_type == "content_block_stop":
        if current_tool_use is not None:
            return ["__TOOL_END__"]
        return []

    if event_type == "message_delta":
        stop_reason = event.get("delta", {}).get("stop_reason", "end_turn")
        return [{
            "id": f"chatcmpl-{uuid.uuid4().hex[:8]}",
            "object": "chat.completion.chunk",
            "created": 1700000000,
            "model": model,
            "choices": [{
                "index": 0,
                "delta": {},
                "finish_reason": _map_stop_reason(stop_reason),
            }],
        }]

    return []


# ─── Health Endpoint ───────────────────────────────────────────────────────────

_PROXY_START = __import__("time").time()

async def handle_health(request: web.Request) -> web.Response:
    uptime = __import__("time").time() - _PROXY_START
    return web.json_response({
        "status": "healthy",
        "service": "fortress-claude-proxy",
        "version": "2.1",
        "uptime_seconds": round(uptime, 1),
        "backend": ANTHROPIC_BASE,
        "models_available": len(CLAUDE_MODELS),
    })


# ─── App Setup ────────────────────────────────────────────────────────────────

app = web.Application()
app.router.add_get("/health", handle_health)
app.router.add_get("/api/health", handle_health)
app.router.add_get("/v1/models", handle_models)
app.router.add_post("/v1/chat/completions", handle_chat_completions)
app.router.add_get("/models", handle_models)
app.router.add_post("/chat/completions", handle_chat_completions)

if __name__ == "__main__":
    log.info(f"Claude Proxy v2.0 starting on port {LISTEN_PORT}")
    log.info(f"Backend: {ANTHROPIC_BASE}")
    log.info(f"Features: auth translation, tool calling, streaming")
    log.info(f"Models: {len(CLAUDE_MODELS)}")
    # SECURITY: Bind to localhost only. Open WebUI connects from localhost.
    # Never expose to 0.0.0.0 — this proxies a paid Anthropic API key.
    web.run_app(app, host="127.0.0.1", port=LISTEN_PORT, print=None)
