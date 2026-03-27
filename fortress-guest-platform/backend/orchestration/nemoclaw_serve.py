from __future__ import annotations

import asyncio
import base64
import json
import logging
import os
from pathlib import Path
import re
import shutil
import tempfile
from itertools import cycle
from typing import Any

import httpx
import ray
from fastapi import FastAPI, HTTPException
from openai import AsyncOpenAI
from ray import serve
from pydantic import BaseModel, ConfigDict, Field

from backend.core.config import settings

logger = logging.getLogger(__name__)

app = FastAPI(title="Fortress Prime: NemoClaw Orchestrator")

HEAD_NODE_IP = "192.168.0.100"
WORKER_NODE_IPS = ("192.168.0.104", "192.168.0.105", "192.168.0.106")
OPEN_SHELL_GATEWAY_NAME = "nemoclaw"
NEMOCLAW_RELEASE_ID = os.getenv("NEMOCLAW_RELEASE_ID", "2026-03-26-bridge-rollout-1")


class AgentDirective(BaseModel):
    task_id: str
    intent: str
    context_payload: dict[str, Any] | None = None


class AgentResponse(BaseModel):
    task_id: str
    status: str
    action_log: list[str]
    result_payload: dict[str, Any] | None = None


class ChatCompletionRequest(BaseModel):
    model: str | None = None
    messages: list[dict[str, Any]]
    temperature: float | None = None
    max_tokens: int | None = None
    stream: bool = False

    model_config = ConfigDict(extra="allow")


def _normalize_openai_base_url(base_url: str) -> str:
    value = (base_url or "").strip().rstrip("/")
    if not value:
        return ""
    if value.endswith("/chat/completions"):
        value = value[: -len("/chat/completions")]
    if value.endswith("/v1"):
        return value
    return f"{value}/v1"


def _extract_message_text(response_data: dict[str, Any]) -> str:
    choices = response_data.get("choices") or []
    if not choices:
        return ""
    message = (choices[0] or {}).get("message") or {}
    content = message.get("content")
    if isinstance(content, str):
        return content.strip()
    if isinstance(content, list):
        text_parts = []
        for part in content:
            if isinstance(part, dict) and part.get("type") == "text":
                text = (part.get("text") or "").strip()
                if text:
                    text_parts.append(text)
        return "\n".join(text_parts).strip()
    return ""


def _recovery_prompt(context_payload: dict[str, Any] | None) -> tuple[str, str]:
    payload = context_payload or {}
    guest_name = str(payload.get("guest_name") or "there").strip() or "there"
    cabin_name = str(payload.get("cabin_name") or "your cabin").strip() or "your cabin"
    check_in = str(payload.get("check_in") or "").strip()
    check_out = str(payload.get("check_out") or "").strip()
    friction_label = str(payload.get("friction_label") or "left before finishing checkout").strip()
    cart_value = str(payload.get("cart_value") or "").strip()
    stay_window = f"{check_in} to {check_out}" if check_in and check_out else "their requested dates"
    value_line = f"Quoted total: {cart_value}." if cart_value else ""
    system_prompt = (
        "You draft recovery emails for Cabin Rentals of Georgia. "
        "Return only the email body text. No markdown, no subject line, no JSON, no signatures beyond a concise brand sign-off. "
        "Keep it warm, high-conversion, and factual. Do not invent discounts, policies, amenities, or urgency."
    )
    user_prompt = (
        f"Write a concise abandoned-cart recovery email to {guest_name}. "
        f"They were considering {cabin_name} for {stay_window} and {friction_label}. "
        f"{value_line} Mention the cabin and the dates, invite them back to complete the reservation, "
        "and keep the tone premium but human."
    )
    return system_prompt, user_prompt


def _default_chat_base_url(node_ip: str) -> str:
    base_url = (os.getenv("NEMOCLAW_SHARED_CHAT_BASE_URL") or f"http://{HEAD_NODE_IP}:4000/v1").strip()
    return _normalize_openai_base_url(base_url)


def _default_chat_model(node_ip: str) -> str:
    return (
        os.getenv("NEMOCLAW_SHARED_CHAT_MODEL")
        or settings.dgx_inference_model
        or "nemotron-3-super-120b"
    )


def _gateway_task_urls() -> list[str]:
    env_urls = (os.getenv("NEMOCLAW_LOCAL_TASK_URLS") or "").strip()
    if env_urls:
        return [item.strip() for item in env_urls.split(",") if item.strip()]
    return [
        "http://127.0.0.1:8080/v1/agent/task",
        "https://127.0.0.1:8080/v1/agent/task",
    ]


def _gateway_tls_cert() -> tuple[str, str] | None:
    cert_path = (os.getenv("NEMOCLAW_CLIENT_CERT_PATH") or "").strip()
    key_path = (os.getenv("NEMOCLAW_CLIENT_KEY_PATH") or "").strip()
    if cert_path and key_path:
        return (cert_path, key_path)
    return None


def _default_openshell_chat_base_url() -> str:
    base_url = (
        os.getenv("NEMOCLAW_OPENSHELL_CHAT_BASE_URL")
        or "https://inference.local/v1"
    ).strip()
    return _normalize_openai_base_url(base_url)


def _default_openshell_bin() -> str:
    override = (os.getenv("NEMOCLAW_OPENSHELL_BIN") or "").strip()
    if override:
        return override
    for candidate in (
        shutil.which("openshell"),
        "/home/admin/.local/bin/openshell",
        "/usr/local/bin/openshell",
    ):
        if candidate and Path(candidate).exists():
            return candidate
    return "/home/admin/.local/bin/openshell"


def _default_openshell_profile_dir() -> str:
    """TLS + profile layout produced by tools/cluster/propagate_openshell.sh."""
    override = (os.getenv("NEMOCLAW_OPENSHELL_PROFILE_DIR") or "").strip()
    if override:
        return override
    home = Path(os.getenv("HOME", "/home/admin"))
    return str(home / ".openshell" / "profiles" / OPEN_SHELL_GATEWAY_NAME)


def _openshell_env() -> dict[str, str]:
    env = os.environ.copy()
    env.setdefault("HOME", "/home/admin")
    env.setdefault("OPENSHELL_GATEWAY", OPEN_SHELL_GATEWAY_NAME)
    env.setdefault("PATH", "/home/admin/.local/bin:/usr/local/bin:/usr/bin:/bin")
    return env


def _trunc_text(value: str, max_len: int) -> str:
    text = (value or "").strip()
    if len(text) <= max_len:
        return text
    return f"{text[:max_len]}...[truncated]"


def _inline_ready_sandbox_failure_message(
    *,
    event: str,
    returncode: int | None,
    worker_label: str,
    sandbox_name: str,
    stdout: str,
    stderr: str,
    stdout_max: int = 500,
    stderr_max: int = 500,
) -> str:
    return (
        f"{event} rc={returncode} worker={worker_label} sandbox={sandbox_name} "
        f"stdout={_trunc_text(stdout, stdout_max)!r} stderr={_trunc_text(stderr, stderr_max)!r}"
    )


def _sandbox_script_payload(directive: AgentDirective, *, chat_base_url: str, chat_model: str, chat_api_key: str) -> str:
    context_payload_b64 = base64.standard_b64encode(
        json.dumps(
            directive.context_payload or {},
            default=str,
            sort_keys=True,
        ).encode("utf-8"),
    ).decode("ascii")
    return json.dumps(
        {
            "task_id": directive.task_id,
            "intent": directive.intent,
            "context_payload_b64": context_payload_b64,
            "chat_base_url": chat_base_url,
            "chat_model": chat_model,
            "chat_api_key": chat_api_key,
        },
        sort_keys=True,
    )


def _build_openshell_python_script(script_payload: str) -> str:
    return """
import base64
import json
import os
import traceback
import urllib.request


def _extract_message_text(response_data):
    choices = response_data.get("choices") or []
    if not choices:
        return ""
    message = (choices[0] or {}).get("message") or {}
    content = message.get("content")
    if isinstance(content, str):
        return content.strip()
    if isinstance(content, list):
        out = []
        for part in content:
            if isinstance(part, dict) and part.get("type") == "text":
                text = str(part.get("text") or "").strip()
                if text:
                    out.append(text)
        return "\\n".join(out).strip()
    return ""


def _recovery_prompt(context_payload):
    guest_name = str(context_payload.get("guest_name") or "there").strip() or "there"
    cabin_name = str(context_payload.get("cabin_name") or "your cabin").strip() or "your cabin"
    check_in = str(context_payload.get("check_in") or "").strip()
    check_out = str(context_payload.get("check_out") or "").strip()
    friction_label = str(context_payload.get("friction_label") or "left before finishing checkout").strip()
    cart_value = str(context_payload.get("cart_value") or "").strip()
    stay_window = f"{check_in} to {check_out}" if check_in and check_out else "their requested dates"
    value_line = f"Quoted total: {cart_value}." if cart_value else ""
    system_prompt = (
        "You draft recovery emails for Cabin Rentals of Georgia. "
        "Return only the email body text. No markdown, no subject line, no JSON, no signatures beyond a concise brand sign-off. "
        "Keep it warm, high-conversion, and factual. Do not invent discounts, policies, amenities, or urgency."
    )
    user_prompt = (
        f"Write a concise abandoned-cart recovery email to {guest_name}. "
        f"They were considering {cabin_name} for {stay_window} and {friction_label}. "
        f"{value_line} Mention the cabin and the dates, invite them back to complete the reservation, "
        "and keep the tone premium but human."
    )
    return system_prompt, user_prompt


def _call_local_llm(base_url, api_key, model, system_prompt, user_prompt):
    request_body = json.dumps(
        {
            "model": model,
            "messages": [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt},
            ],
            "temperature": 0.35,
            "max_tokens": 400,
            "stream": False,
        }
    ).encode("utf-8")
    request = urllib.request.Request(
        base_url.rstrip("/") + "/chat/completions",
        data=request_body,
        headers={
            "Content-Type": "application/json",
            "Authorization": "Bearer " + api_key,
        },
        method="POST",
    )
    with urllib.request.urlopen(request, timeout=45) as response:
        response_data = json.loads(response.read().decode("utf-8"))
    text = _extract_message_text(response_data)
    if not text:
        raise RuntimeError("local llm returned empty recovery draft")
    return text


def _guest_concierge_prompts(res_data, snippets):
    system_prompt = (
        "You are the elite AI Guest Concierge for Cabin Rentals of Georgia, a luxury property management company. "
        "Your objective is to draft pre-arrival communications based strictly on the provided property rules and reservation details.\n\n"
        "CRITICAL BOUNDARIES:\n"
        "1. NEVER invent access codes, Wi-Fi passwords, or policies. If a detail is missing from the snippets, omit it or note it for staff.\n"
        "2. Maintain a warm, high-end, and professional tone.\n"
        "3. You must output ONLY valid JSON matching this exact schema: "
        '{"draft_email": "string", "draft_sms": "string", "internal_staff_notes": "string"}\n'
        "Use the exact key names draft_email, draft_sms, internal_staff_notes."
    )
    user_prompt = (
        "Reservation Details:\n"
        + json.dumps(res_data, indent=2, default=str)
        + "\n\nProperty Context (Qdrant snippets; authoritative for on-property facts):\n"
        + json.dumps(snippets, indent=2, default=str)
    )
    return system_prompt, user_prompt


def _call_local_llm_json(base_url, api_key, model, system_prompt, user_prompt):
    request_body = json.dumps(
        {
            "model": model,
            "messages": [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt},
            ],
            "temperature": 0.2,
            "max_tokens": 2048,
            "stream": False,
            "response_format": {"type": "json_object"},
        }
    ).encode("utf-8")
    request = urllib.request.Request(
        base_url.rstrip("/") + "/chat/completions",
        data=request_body,
        headers={
            "Content-Type": "application/json",
            "Authorization": "Bearer " + api_key,
        },
        method="POST",
    )
    with urllib.request.urlopen(request, timeout=120) as response:
        response_data = json.loads(response.read().decode("utf-8"))
    text = _extract_message_text(response_data)
    if not text:
        raise RuntimeError("local llm returned empty concierge JSON")
    return text


try:
    payload = json.loads(%r)
    task_id = payload["task_id"]
    intent = payload["intent"]
    context_payload = json.loads(base64.standard_b64decode(payload["context_payload_b64"]).decode("utf-8"))
    chat_base_url = (
        os.getenv("OPENAI_BASE_URL")
        or os.getenv("LITELLM_BASE_URL")
        or payload["chat_base_url"]
    )
    chat_api_key = (
        os.getenv("LITELLM_API_KEY")
        or os.getenv("OPENAI_API_KEY")
        or payload["chat_api_key"]
    )
    chat_model = os.getenv("OPENAI_MODEL") or payload["chat_model"]
    chat_base_url_source = (
        "OPENAI_BASE_URL" if os.getenv("OPENAI_BASE_URL")
        else "LITELLM_BASE_URL" if os.getenv("LITELLM_BASE_URL")
        else "payload"
    )
    chat_api_key_source = (
        "LITELLM_API_KEY" if os.getenv("LITELLM_API_KEY")
        else "OPENAI_API_KEY" if os.getenv("OPENAI_API_KEY")
        else "payload"
    )
    verification_path = "/tmp/nemoclaw_verification.txt"
    with open(verification_path, "w", encoding="utf-8") as handle:
        handle.write("FORTRESS_LOCAL_LANE_ACTIVE")
    with open(verification_path, "r", encoding="utf-8") as handle:
        read_result = handle.read()

    action_log = [
        "directive executed inside OpenShell sandbox",
        "intent=" + intent,
        "sandbox_verification=" + read_result,
        "context_keys=" + json.dumps(sorted(context_payload.keys())),
        "llm_base_url=" + chat_base_url,
        "llm_base_url_source=" + chat_base_url_source,
        "llm_api_key_source=" + chat_api_key_source,
    ]
    result_payload = {}
    if intent == "draft_recovery_email":
        system_prompt, user_prompt = _recovery_prompt(context_payload)
        draft_body = _call_local_llm(
            chat_base_url,
            chat_api_key,
            chat_model,
            system_prompt,
            user_prompt,
        )
        result_payload["draft_body"] = draft_body
        action_log.append("draft_chars=" + str(len(draft_body)))

    elif intent == "guest_concierge":
        res_data = context_payload.get("reservation")
        if not isinstance(res_data, dict):
            res_data = {}
        snippets = context_payload.get("snippets")
        if not isinstance(snippets, list):
            snippets = []
        system_prompt, user_prompt = _guest_concierge_prompts(res_data, snippets)
        try:
            raw_content = _call_local_llm_json(
                chat_base_url,
                chat_api_key,
                chat_model,
                system_prompt,
                user_prompt,
            )
        except Exception as json_mode_exc:
            fallback_body = json.dumps(
                {
                    "model": chat_model,
                    "messages": [
                        {"role": "system", "content": system_prompt},
                        {"role": "user", "content": user_prompt},
                    ],
                    "temperature": 0.2,
                    "max_tokens": 2048,
                    "stream": False,
                }
            ).encode("utf-8")
            request = urllib.request.Request(
                chat_base_url.rstrip("/") + "/chat/completions",
                data=fallback_body,
                headers={
                    "Content-Type": "application/json",
                    "Authorization": "Bearer " + chat_api_key,
                },
                method="POST",
            )
            with urllib.request.urlopen(request, timeout=120) as response:
                response_data = json.loads(response.read().decode("utf-8"))
            raw_content = _extract_message_text(response_data)
            if not raw_content:
                raise json_mode_exc
            action_log.append("concierge_json_mode_fallback=1")
        try:
            parsed_json = json.loads(raw_content)
        except json.JSONDecodeError:
            result_payload = {
                "error": "Failed to parse JSON",
                "raw": raw_content[:4000],
            }
        else:
            if not isinstance(parsed_json, dict):
                result_payload = {
                    "error": "LLM JSON was not an object",
                    "raw": raw_content[:4000],
                }
            else:
                result_payload = {
                    "draft_email": str(parsed_json.get("draft_email") or ""),
                    "draft_sms": str(parsed_json.get("draft_sms") or ""),
                    "internal_staff_notes": str(parsed_json.get("internal_staff_notes") or ""),
                }
                action_log.append("concierge_fields_ok=1")

    print(json.dumps({
        "task_id": task_id,
        "status": "success",
        "action_log": action_log,
        "result_payload": result_payload,
    }))
except Exception as exc:
    print(json.dumps({"error": str(exc), "trace": traceback.format_exc()}))
    raise SystemExit(1)
""".strip() % script_payload


@serve.deployment
class NemoClawWorker:
    def __init__(self, pinned_node_ip: str, worker_label: str) -> None:
        self.pinned_node_ip = pinned_node_ip
        self.worker_label = worker_label
        self.runtime_node_ip = ray.util.get_node_ip_address()
        self.local_gateway_health_url = (
            os.getenv("NEMOCLAW_LOCAL_HEALTH_URL") or "http://127.0.0.1:8080/health"
        ).strip()
        self.local_gateway_task_urls = _gateway_task_urls()
        self.gateway_tls_cert = _gateway_tls_cert()
        self.gateway_verify_ssl = (
            os.getenv("NEMOCLAW_GATEWAY_VERIFY_SSL", "false").strip().lower() in {"1", "true", "yes", "on"}
        )
        self.gateway_timeout_s = float(os.getenv("NEMOCLAW_GATEWAY_TIMEOUT_S", "20"))
        self.openshell_bin = _default_openshell_bin()
        self.openshell_profile_dir = _default_openshell_profile_dir()
        openshell_bin_path = Path(self.openshell_bin)
        openshell_key_path = Path(self.openshell_profile_dir) / "client.key"
        if openshell_bin_path.is_file() and openshell_key_path.is_file():
            self.openshell_enabled = True
            logger.info(
                "[Nemoclaw] OpenShell local lane ARMED on worker %s.",
                self.pinned_node_ip,
            )
        else:
            self.openshell_enabled = False
            logger.warning(
                "[Nemoclaw] OpenShell missing or unconfigured on %s. "
                "Falling back to LiteLLM over the network.",
                self.pinned_node_ip,
            )
        if not self.openshell_enabled:
            logger.warning(
                "nemoclaw_worker_openshell_missing",
                extra={
                    "pinned_node_ip": self.pinned_node_ip,
                    "worker_label": self.worker_label,
                    "openshell_bin": self.openshell_bin,
                    "openshell_bin_exists": openshell_bin_path.is_file(),
                    "openshell_profile_dir": self.openshell_profile_dir,
                    "openshell_profile_dir_exists": Path(self.openshell_profile_dir).exists(),
                    "openshell_client_key_exists": openshell_key_path.is_file(),
                },
            )
        self.openshell_timeout_s = float(os.getenv("NEMOCLAW_OPENSHELL_TIMEOUT_S", "300"))
        self.openshell_from = (os.getenv("NEMOCLAW_OPENSHELL_FROM") or "base").strip()
        self.openshell_sandbox_name = (os.getenv("NEMOCLAW_OPENSHELL_SANDBOX") or "my-assistant").strip()
        self.openshell_ssh_bin = (os.getenv("NEMOCLAW_SSH_BIN") or "/usr/bin/ssh").strip()
        self.openshell_chat_base_url = _default_openshell_chat_base_url()
        self.chat_base_url = _default_chat_base_url(self.pinned_node_ip)
        self.chat_model = _default_chat_model(self.pinned_node_ip)
        self.chat_api_key = (
            str(settings.dgx_inference_api_key or "").strip()
            or str(settings.litellm_master_key or "").strip()
            or "fortress-local-gateway"
        )
        logger.info(
            "nemoclaw_worker_initialized",
            extra={
                "pinned_node_ip": self.pinned_node_ip,
                "runtime_node_ip": self.runtime_node_ip,
                "worker_label": self.worker_label,
                "chat_base_url": self.chat_base_url,
                "chat_model": self.chat_model,
                "openshell_chat_base_url": self.openshell_chat_base_url,
                "openshell_enabled": self.openshell_enabled,
            },
        )
        self._last_openshell_ready_diag: str | None = None

    def _openshell_remote_env_args(self) -> list[str]:
        sandbox_api_key = (
            "unused"
            if "inference.local" in (self.openshell_chat_base_url or "")
            else self.chat_api_key
        )
        remote_env = [
            "env",
            f"OPENAI_BASE_URL={self.openshell_chat_base_url}",
            f"LITELLM_API_KEY={sandbox_api_key}",
            f"OPENAI_API_KEY={sandbox_api_key}",
        ]
        if self.chat_model:
            remote_env.append(f"OPENAI_MODEL={self.chat_model}")
        return remote_env

    async def execute(self, payload: dict[str, Any]) -> dict[str, Any]:
        directive = AgentDirective.model_validate(payload)
        self._last_openshell_ready_diag = None

        try:
            openshell_result = await self._submit_openshell_cli_task(directive)
            if openshell_result is not None:
                return openshell_result

            gateway_result = await self._submit_gateway_task(directive)
            if gateway_result is not None:
                return gateway_result

            return await self._submit_fallback_directive(directive)
        except Exception as exc:  # noqa: BLE001
            raise RuntimeError(str(exc)[:400]) from None

    async def chat_completion(self, payload: dict[str, Any]) -> dict[str, Any]:
        request = ChatCompletionRequest.model_validate(payload)
        if request.stream:
            raise RuntimeError("Streaming is not enabled for NemoClaw Serve.")
        if not self.chat_base_url:
            raise RuntimeError(
                f"No sovereign chat base URL configured for worker {self.pinned_node_ip}."
            )

        client = AsyncOpenAI(
            base_url=self.chat_base_url,
            api_key=self.chat_api_key,
            timeout=float(os.getenv("NEMOCLAW_CHAT_TIMEOUT_S", "45")),
        )
        try:
            response = await client.chat.completions.create(
                model=request.model or self.chat_model,
                messages=request.messages,
                stream=False,
                temperature=request.temperature if request.temperature is not None else 0.2,
                max_tokens=request.max_tokens,
            )
            return response.model_dump(mode="json")
        finally:
            await client.close()

    async def health(self) -> dict[str, Any]:
        return {
            "worker_label": self.worker_label,
            "pinned_node_ip": self.pinned_node_ip,
            "runtime_node_ip": self.runtime_node_ip,
            "local_gateway_health_url": self.local_gateway_health_url,
            "chat_base_url": self.chat_base_url,
            "chat_model": self.chat_model,
            "openshell_enabled": self.openshell_enabled,
        }

    async def _submit_openshell_cli_task(self, directive: AgentDirective) -> dict[str, Any] | None:
        if not self.openshell_enabled:
            return None

        ready_result = await self._submit_openshell_ready_sandbox_task(directive)
        if ready_result is not None:
            return ready_result

        if self.openshell_sandbox_name:
            return None

        status_proc = await asyncio.create_subprocess_exec(
            self.openshell_bin,
            "status",
            "-g",
            OPEN_SHELL_GATEWAY_NAME,
            env=_openshell_env(),
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        try:
            status_stdout, status_stderr = await asyncio.wait_for(
                status_proc.communicate(),
                timeout=min(self.openshell_timeout_s, 30),
            )
        except TimeoutError:
            status_proc.kill()
            await status_proc.communicate()
            return None

        if status_proc.returncode != 0:
            logger.warning(
                "nemoclaw_openshell_status_failed",
                extra={
                    "worker_label": self.worker_label,
                    "stderr": status_stderr.decode("utf-8", errors="ignore")[:300],
                },
            )
            return None

        return await self._submit_openshell_create_task(directive)

    async def _submit_openshell_ready_sandbox_task(
        self,
        directive: AgentDirective,
    ) -> dict[str, Any] | None:
        if not self.openshell_sandbox_name:
            return None

        ssh_config_proc = await asyncio.create_subprocess_exec(
            self.openshell_bin,
            "sandbox",
            "ssh-config",
            "-g",
            OPEN_SHELL_GATEWAY_NAME,
            self.openshell_sandbox_name,
            env=_openshell_env(),
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        try:
            ssh_config_stdout, ssh_config_stderr = await asyncio.wait_for(
                ssh_config_proc.communicate(),
                timeout=min(self.openshell_timeout_s, 30),
            )
        except TimeoutError:
            ssh_config_proc.kill()
            await ssh_config_proc.communicate()
            self._last_openshell_ready_diag = (
                "nemoclaw_openshell_ssh_config_timeout "
                f"worker={self.worker_label} sandbox={self.openshell_sandbox_name}"
            )
            logger.warning(self._last_openshell_ready_diag)
            return None

        if ssh_config_proc.returncode != 0:
            err_txt = ssh_config_stderr.decode("utf-8", errors="ignore")
            msg = (
                f"nemoclaw_openshell_ssh_config_failed rc={ssh_config_proc.returncode} "
                f"worker={self.worker_label} sandbox={self.openshell_sandbox_name} "
                f"stderr={_trunc_text(err_txt, 500)!r}"
            )
            logger.warning(msg)
            self._last_openshell_ready_diag = _trunc_text(msg, 600)
            return None

        ssh_config_text = ssh_config_stdout.decode("utf-8", errors="ignore").strip()
        if not ssh_config_text:
            self._last_openshell_ready_diag = (
                "nemoclaw_openshell_ssh_config_empty "
                f"worker={self.worker_label} sandbox={self.openshell_sandbox_name}"
            )
            logger.warning(self._last_openshell_ready_diag)
            return None
        ssh_config_text = re.sub(r"(?m)^(\s*HostName\s+).+$", r"\g<1>127.0.0.1", ssh_config_text)

        script_payload = _sandbox_script_payload(
            directive,
            chat_base_url=self.chat_base_url,
            chat_model=self.chat_model,
            chat_api_key=self.chat_api_key,
        )
        sandbox_script = _build_openshell_python_script(script_payload)

        with tempfile.NamedTemporaryFile("w", delete=False, prefix="openshell-", suffix=".ssh") as handle:
            handle.write(ssh_config_text)
            handle.write("\n")
            ssh_config_path = handle.name

        try:
            ssh_proc = await asyncio.create_subprocess_exec(
                self.openshell_ssh_bin,
                "-o",
                "BatchMode=yes",
                "-o",
                "ConnectTimeout=20",
                "-F",
                ssh_config_path,
                f"openshell-{self.openshell_sandbox_name}",
                *self._openshell_remote_env_args(),
                "python3",
                "-",
                env=_openshell_env(),
                stdin=asyncio.subprocess.PIPE,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
            try:
                ssh_stdout, ssh_stderr = await asyncio.wait_for(
                    ssh_proc.communicate(sandbox_script.encode("utf-8")),
                    timeout=min(self.openshell_timeout_s, 60),
                )
            except TimeoutError:
                ssh_proc.kill()
                await ssh_proc.communicate()
                self._last_openshell_ready_diag = (
                    "nemoclaw_openshell_ready_sandbox_ssh_timeout "
                    f"worker={self.worker_label} sandbox={self.openshell_sandbox_name}"
                )
                logger.warning(self._last_openshell_ready_diag)
                return None
        finally:
            try:
                os.unlink(ssh_config_path)
            except OSError:
                pass

        if ssh_proc.returncode != 0:
            out_txt = ssh_stdout.decode("utf-8", errors="ignore")
            err_txt = ssh_stderr.decode("utf-8", errors="ignore")
            msg = _inline_ready_sandbox_failure_message(
                event="nemoclaw_openshell_ready_sandbox_failed",
                returncode=ssh_proc.returncode,
                worker_label=self.worker_label,
                sandbox_name=self.openshell_sandbox_name,
                stdout=out_txt,
                stderr=err_txt,
            )
            logger.warning(msg)
            self._last_openshell_ready_diag = _trunc_text(msg, 600)
            return None

        stdout_text = ssh_stdout.decode("utf-8", errors="ignore").strip()
        try:
            response_json = json.loads(stdout_text)
        except json.JSONDecodeError:
            msg = (
                "nemoclaw_openshell_ready_sandbox_unstructured_output "
                f"worker={self.worker_label} sandbox={self.openshell_sandbox_name} "
                f"stdout={_trunc_text(stdout_text, 700)!r}"
            )
            logger.warning(msg)
            self._last_openshell_ready_diag = _trunc_text(msg, 600)
            return None
        action_log = [
            f"worker_label={self.worker_label}",
            f"worker_node_ip={self.runtime_node_ip}",
            "execution_path=openshell_cli",
            f"sandbox_name={self.openshell_sandbox_name}",
        ]
        action_log.extend(response_json.get("action_log", [])[:6])
        return {
            "task_id": directive.task_id,
            "status": str(response_json.get("status") or "success"),
            "action_log": action_log,
            "result_payload": response_json.get("result_payload")
            if isinstance(response_json.get("result_payload"), dict)
            else None,
        }

    async def _submit_openshell_create_task(self, directive: AgentDirective) -> dict[str, Any] | None:
        sanitized_task = re.sub(r"[^a-z0-9-]+", "-", directive.task_id.lower()).strip("-") or "directive"
        sandbox_name = f"nemoclaw-{sanitized_task[:40]}"
        script_payload = _sandbox_script_payload(
            directive,
            chat_base_url=self.chat_base_url,
            chat_model=self.chat_model,
            chat_api_key=self.chat_api_key,
        )
        sandbox_script = _build_openshell_python_script(script_payload)

        create_args = [
            self.openshell_bin,
            "sandbox",
            "create",
            "-g",
            OPEN_SHELL_GATEWAY_NAME,
            "--name",
            sandbox_name,
            "--from",
            self.openshell_from,
            "--no-keep",
            "--no-bootstrap",
            "--",
            *self._openshell_remote_env_args(),
            "python3",
            "-c",
            sandbox_script,
        ]

        create_proc = await asyncio.create_subprocess_exec(
            *create_args,
            env=_openshell_env(),
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        try:
            create_stdout, create_stderr = await asyncio.wait_for(
                create_proc.communicate(),
                timeout=self.openshell_timeout_s,
            )
        except TimeoutError:
            create_proc.kill()
            await create_proc.communicate()
            logger.warning(
                "nemoclaw_openshell_timeout",
                extra={"worker_label": self.worker_label, "sandbox_name": sandbox_name},
            )
            return None

        if create_proc.returncode != 0:
            logger.warning(
                "nemoclaw_openshell_create_failed",
                extra={
                    "worker_label": self.worker_label,
                    "sandbox_name": sandbox_name,
                    "stderr": create_stderr.decode("utf-8", errors="ignore")[:400],
                },
            )
            return None

        stdout_text = create_stdout.decode("utf-8", errors="ignore")
        response_json: dict[str, Any] | None = None
        for line in reversed(stdout_text.splitlines()):
            candidate = line.strip()
            if candidate.startswith("{") and candidate.endswith("}"):
                response_json = json.loads(candidate)
                break

        if response_json is None:
            logger.warning(
                "nemoclaw_openshell_unstructured_output",
                extra={
                    "worker_label": self.worker_label,
                    "sandbox_name": sandbox_name,
                    "stdout": stdout_text[-400:],
                },
            )
            return None

        action_log = [
            f"worker_label={self.worker_label}",
            f"worker_node_ip={self.runtime_node_ip}",
            "execution_path=openshell_cli",
            f"sandbox_name={sandbox_name}",
        ]
        action_log.extend(response_json.get("action_log", [])[:6])
        return {
            "task_id": directive.task_id,
            "status": str(response_json.get("status") or "success"),
            "action_log": action_log,
            "result_payload": response_json.get("result_payload")
            if isinstance(response_json.get("result_payload"), dict)
            else None,
        }

    async def _submit_gateway_task(self, directive: AgentDirective) -> dict[str, Any] | None:
        gateway_errors: list[str] = []
        task_payload = {
            "task_id": directive.task_id,
            "directive": directive.intent,
            "context": directive.context_payload or {},
        }

        for task_url in self.local_gateway_task_urls:
            try:
                async with httpx.AsyncClient(
                    timeout=self.gateway_timeout_s,
                    verify=self.gateway_verify_ssl,
                    cert=self.gateway_tls_cert,
                ) as client:
                    health_response = await client.get(self.local_gateway_health_url)
                    health_response.raise_for_status()
                    response = await client.post(task_url, json=task_payload)
                    response.raise_for_status()
                    response_json: dict[str, Any] = response.json() if response.content else {}
            except Exception as exc:  # noqa: BLE001
                gateway_errors.append(f"{task_url}:{str(exc)[:200]}")
                continue

            action_log = [
                f"worker_label={self.worker_label}",
                f"worker_node_ip={self.runtime_node_ip}",
                "execution_path=openshell_gateway",
                f"task_url={task_url}",
            ]
            if response_json.get("status"):
                action_log.append(f"gateway_status={response_json['status']}")
            if response_json.get("message"):
                action_log.append(f"gateway_message={str(response_json['message'])[:240]}")
            return {
                "task_id": directive.task_id,
                "status": str(response_json.get("status") or "success"),
                "action_log": action_log,
                "result_payload": response_json.get("result_payload")
                if isinstance(response_json.get("result_payload"), dict)
                else None,
            }

        if gateway_errors:
            logger.warning(
                "nemoclaw_gateway_unavailable",
                extra={
                    "worker_label": self.worker_label,
                    "worker_node_ip": self.runtime_node_ip,
                    "errors": gateway_errors,
                },
            )
        return None

    async def _submit_fallback_directive(self, directive: AgentDirective) -> dict[str, Any]:
        logger.error(
            "FATAL: OpenShell execution failed on %s for task %s.",
            self.pinned_node_ip,
            directive.task_id,
        )
        if directive.intent in {"draft_recovery_email", "guest_concierge"}:
            logger.error(
                "Worker-local fallback for intent=%s has been removed; inference.local is required.",
                directive.intent,
            )
        else:
            logger.error("LiteLLM fallback is explicitly disabled to protect Head Node memory.")
        raise RuntimeError(
            f"OpenShell sandbox execution failed on worker {self.pinned_node_ip}. Matrix must retry."
        )


@serve.deployment(
    name="nemoclaw-alpha-router",
    ray_actor_options={
        "num_cpus": 1,
        "resources": {f"node:{HEAD_NODE_IP}": 0.001},
        "runtime_env": {"env_vars": {"NEMOCLAW_RELEASE_ID": NEMOCLAW_RELEASE_ID}},
    },
)
@serve.ingress(app)
class NemoClawOrchestrator:
    def __init__(self, *workers: Any) -> None:
        self.workers = list(workers)
        self._worker_cycle = cycle(self.workers)

    @app.get("/health")
    async def health(self) -> dict[str, Any]:
        worker_states = []
        for worker in self.workers:
            worker_states.append(await worker.health.remote())
        return {
            "status": "ok",
            "head_node_ip": HEAD_NODE_IP,
            "worker_targets": worker_states,
        }

    @app.post("/api/agent/execute", response_model=AgentResponse)
    async def execute_directive(self, payload: AgentDirective) -> AgentResponse:
        worker = next(self._worker_cycle)
        try:
            result = await worker.execute.remote(payload.model_dump())
        except Exception as exc:  # noqa: BLE001
            raise HTTPException(status_code=502, detail=f"NemoClaw worker execution failed: {exc}") from exc

        return AgentResponse.model_validate(result)

    @app.post("/v1/chat/completions")
    async def chat_completions(self, payload: ChatCompletionRequest) -> dict[str, Any]:
        worker = next(self._worker_cycle)
        try:
            return await worker.chat_completion.remote(payload.model_dump())
        except Exception as exc:  # noqa: BLE001
            raise HTTPException(status_code=502, detail=f"NemoClaw chat worker failed: {exc}") from exc


def _worker_actor_options(node_ip: str) -> dict[str, Any]:
    return {
        "num_cpus": 16,
        "num_gpus": 1,
        "resources": {f"node:{node_ip}": 0.001},
        "runtime_env": {"env_vars": {"NEMOCLAW_RELEASE_ID": NEMOCLAW_RELEASE_ID}},
    }


worker_104 = NemoClawWorker.options(
    name="nemoclaw-alpha-worker-104",
    ray_actor_options=_worker_actor_options("192.168.0.104"),
).bind("192.168.0.104", "spark-node-1")

worker_105 = NemoClawWorker.options(
    name="nemoclaw-alpha-worker-105",
    ray_actor_options=_worker_actor_options("192.168.0.105"),
).bind("192.168.0.105", "spark-3")

worker_106 = NemoClawWorker.options(
    name="nemoclaw-alpha-worker-106",
    ray_actor_options=_worker_actor_options("192.168.0.106"),
).bind("192.168.0.106", "spark-4")

deployment = NemoClawOrchestrator.bind(worker_104, worker_105, worker_106)
