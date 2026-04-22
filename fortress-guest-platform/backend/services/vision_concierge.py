"""
vision_concierge.py — Image attachment enrichment via Nemotron-Nano-12B-v2-VL NIM.

Called by email_message_service.receive_email when the inbound email contains
image attachments. Sends each image to the VL NIM on spark-3 (:8101) and
prepends [IMAGE: description] to the email body before storing, so the 9-seat
concierge council can reason about image content.

Limits: first 3 images only, each < 5MB, total < 15MB.
Fails silently if NIM is unavailable — email is processed without enrichment.
Never logs image content.
"""
from __future__ import annotations

import base64
import logging
from typing import Optional

import httpx

logger = logging.getLogger("vision_concierge")

VISION_NIM_URL = "http://192.168.0.105:8101/v1"
VISION_NIM_MODEL = "nvidia/nemotron-nano-12b-v2-vl"
MAX_IMAGES = 3
MAX_IMAGE_BYTES = 5 * 1024 * 1024  # 5MB
VL_TIMEOUT = 30.0


async def enrich_body_with_image_descriptions(
    body_text: str,
    attachments: list[dict],
) -> tuple[str, list[dict]]:
    """
    For each image attachment (up to MAX_IMAGES, up to MAX_IMAGE_BYTES each),
    call the VL NIM and prepend [IMAGE: description] to the body.

    attachments: list of {"filename": str, "content": bytes, "mime_type": str}

    Returns (enriched_body, image_descriptions) where image_descriptions is a
    list of {"filename": str, "description": str} for storage in image_descriptions JSONB.
    """
    images = [
        a for a in attachments
        if a.get("mime_type", "").startswith("image/")
        and len(a.get("content", b"")) <= MAX_IMAGE_BYTES
    ][:MAX_IMAGES]

    if not images:
        return body_text, []

    descriptions = []
    for img in images:
        desc = await _describe_image(img)
        if desc:
            descriptions.append({"filename": img.get("filename", "image"), "description": desc})

    if not descriptions:
        return body_text, []

    prefix_lines = [f"[IMAGE: {d['description'][:300]}]" for d in descriptions]
    enriched = "\n".join(prefix_lines) + "\n\n" + body_text
    logger.info(
        "vision_concierge.enriched attachments=%d descriptions_added=%d",
        len(images), len(descriptions),
    )
    return enriched, descriptions


async def _describe_image(attachment: dict) -> Optional[str]:
    """Call the VL NIM to describe one image. Returns None on any failure."""
    try:
        content: bytes = attachment.get("content", b"")
        mime_type: str = attachment.get("mime_type", "image/jpeg")
        b64 = base64.b64encode(content).decode("ascii")
        data_url = f"data:{mime_type};base64,{b64}"

        payload = {
            "model": VISION_NIM_MODEL,
            "messages": [
                {
                    "role": "user",
                    "content": [
                        {"type": "image_url", "image_url": {"url": data_url}},
                        {
                            "type": "text",
                            "text": (
                                "Describe what you see in this image in 1-2 sentences. "
                                "Focus on content relevant to a vacation rental inquiry "
                                "(property damage, amenity questions, location, etc.). "
                                "Be specific and factual."
                            ),
                        },
                    ],
                }
            ],
            "max_tokens": 150,
            "temperature": 0.2,
        }

        async with httpx.AsyncClient(timeout=VL_TIMEOUT) as client:
            resp = await client.post(f"{VISION_NIM_URL}/chat/completions", json=payload)
            resp.raise_for_status()
            choices = resp.json().get("choices", [])
            if choices:
                return (choices[0].get("message", {}).get("content") or "").strip()
    except Exception as exc:
        logger.warning(
            "vision_concierge.describe_failed filename=%s err=%s",
            attachment.get("filename", "?"), str(exc)[:120],
        )
    return None
