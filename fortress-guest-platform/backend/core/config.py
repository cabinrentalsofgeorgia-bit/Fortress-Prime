"""
Application configuration using Pydantic Settings
"""

from pydantic_settings import BaseSettings
from pydantic import Field, field_validator


class Settings(BaseSettings):
    environment: str = Field(default="development")
    debug: bool = Field(default=False)

    # Database
    database_url: str = Field(default="postgresql+asyncpg://fgp_app:fortress2024@localhost:5432/fortress_guest")
    swarm_api_key: str = Field(default="")

    # JWT (Tier-0 hardening): RS256 asymmetric keys.
    # Keys are expected as base64-encoded PEM strings for env portability.
    jwt_secret_key: str = Field(default="")
    jwt_rsa_private_key: str = Field(default="")
    jwt_rsa_public_key: str = Field(default="")
    jwt_key_id: str = Field(default="fgp-rs256-v1")
    jwt_accept_legacy_hs256: bool = Field(default=True)
    jwt_legacy_hs256_secrets: str = Field(default="")
    jwt_algorithm: str = Field(default="RS256")
    jwt_expiration_hours: int = Field(default=24)

    @field_validator("jwt_rsa_private_key", "jwt_rsa_public_key", mode="before")
    @classmethod
    def _decode_pem_key(cls, v: str) -> str:
        value = (v or "").strip()
        if not value:
            return value
        if value.startswith("-----BEGIN"):
            return value
        try:
            import base64
            return base64.b64decode(value).decode("utf-8")
        except Exception:
            return value

    @field_validator("jwt_secret_key", mode="before")
    @classmethod
    def _compat_jwt_secret(cls, v: str) -> str:
        # Backward-compat for components that still derive non-auth tokens
        # from this field (e.g., signing_token.py). Auth now uses RSA keys.
        return (v or "").strip() or "compat-jwt-secret-not-used-for-auth"

    @field_validator("jwt_algorithm", mode="before")
    @classmethod
    def _force_rs256(cls, _v: str) -> str:
        return "RS256"

    @field_validator("jwt_key_id", mode="before")
    @classmethod
    def _normalize_kid(cls, v: str) -> str:
        value = (v or "").strip()
        return value or "fgp-rs256-v1"
    secret_key: str = Field(default="change-me-fortress-secret")

    # Command Center
    command_center_url: str = Field(default="http://localhost:9800")
    frontend_url: str = Field(default="https://crog-ai.com")

    # AI Models — Local (DGX)
    ollama_base_url: str = Field(default="http://192.168.0.100:11434")
    ollama_fast_model: str = Field(default="qwen2.5:7b")
    ollama_deep_model: str = Field(default="deepseek-r1:70b")
    use_local_llm: bool = Field(default=True)

    # AI Models — DGX Nodes
    dgx_reasoner_url: str = Field(default="http://192.168.0.100/hydra/v1")
    dgx_reasoner_model: str = Field(default="deepseek-r1:70b")
    dgx_ocular_url: str = Field(default="http://192.168.0.105:8000/v1")
    dgx_ocular_model: str = Field(default="qwen2.5:7b")
    dgx_memory_url: str = Field(default="http://192.168.0.106:8000/v1")
    dgx_memory_model: str = Field(default="qwen2.5:7b")

    # AI Models — Cloud (fallback)
    openai_api_key: str = Field(default="")
    openai_model: str = Field(default="gpt-4o")
    anthropic_api_key: str = Field(default="")
    anthropic_model: str = Field(default="claude-sonnet-4-20250514")
    gemini_api_key: str = Field(default="")
    gemini_model: str = Field(default="gemini-2.5-pro")
    xai_api_key: str = Field(default="")
    xai_model: str = Field(default="grok-3")

    # LiteLLM Gateway — canonical base for chat completions (RAG, vision lane, failover, telemetry)
    litellm_base_url: str = Field(
        default="http://127.0.0.1:4000/v1",
        description="Base URL for LiteLLM gateway; backend appends /chat/completions. FGP_BACKEND_URL is unrelated (Next.js BFF upstream).",
    )

    # Gateway
    gateway_api_url: str = Field(default="http://localhost:8000")

    # Qdrant
    qdrant_url: str = Field(default="http://localhost:6333")
    qdrant_api_key: str = Field(default="")
    qdrant_collection_name: str = Field(default="fgp_knowledge")

    # Redis
    redis_url: str = Field(default="redis://localhost:6379/0")

    # Embedding (nomic-embed-text via Ollama, E5 NIM as future upgrade)
    embed_base_url: str = Field(default="http://192.168.0.100:11434")
    embed_model: str = Field(default="nomic-embed-text")
    embed_dim: int = Field(default=768)
    recursive_embed_url: str = Field(
        default="http://127.0.0.1:8003/v1/embeddings",
        description="Council DAG embedding endpoint (OpenAI-compatible /v1/embeddings).",
    )

    # Streamline VRS
    streamline_api_url: str = Field(default="")
    streamline_api_key: str = Field(default="")
    streamline_api_secret: str = Field(default="")
    streamline_property_id: str = Field(default="")
    streamline_sync_interval: int = Field(default=300)

    # Stripe Payments
    stripe_secret_key: str = Field(default="")
    stripe_publishable_key: str = Field(default="")
    stripe_webhook_secret: str = Field(default="")
    stripe_connect_webhook_secret: str = Field(default="")
    stripe_dispute_webhook_secret: str = Field(default="")

    # Continuous Liquidity
    minimum_payout_amount: float = Field(default=25.00)

    # Reservation Webhooks (HMAC shared secret for POST /api/webhooks/reservations)
    reservation_webhook_secret: str = Field(default="")

    # Feature Flags
    enable_ai_responses: bool = Field(default=True)
    enable_auto_replies: bool = Field(default=False)
    enable_sentiment_analysis: bool = Field(default=True)
    enable_predictive_analytics: bool = Field(default=False)
    enable_multi_language: bool = Field(default=False)

    # ==========================================
    # LEGAL HYBRID MVP - COMPLIANCE GUARDRAILS
    # ==========================================
    # Strict limits to prevent automated spoliation or Rule 26 violations
    LEGAL_DISCOVERY_MAX_ITEMS: int = 25
    LEGAL_DISCOVERY_FOIA_ENABLED: bool = False  # Requires explicit override per case
    LEGAL_PROPORTIONALITY_MODE: str = "strict"  # 'strict' or 'advisory'
    LEGAL_GRAPH_MAX_NODES: int = 1500  # VRAM memory protection for the Swarm

    # ==========================================
    # COURTLISTENER / JURISPRUDENCE ENGINE
    # ==========================================
    courtlistener_api_token: str = Field(default="")
    courtlistener_base_url: str = Field(default="https://www.courtlistener.com/api/rest/v4/")

    # Execution sandbox runtime
    sandbox_runtime: str = Field(
        default="docker",
        description="Execution backend for execute_python: docker|firecracker.",
    )
    sandbox_memory_mb: int = Field(default=512)
    sandbox_vcpu_count: int = Field(default=1)
    sandbox_firecracker_helper: str = Field(
        default="",
        description="Path to helper binary/script that launches Firecracker + jailer per request.",
    )
    sandbox_firecracker_bin: str = Field(default="/usr/bin/firecracker")
    sandbox_jailer_bin: str = Field(default="/usr/bin/jailer")
    sandbox_kernel_image: str = Field(default="")
    sandbox_rootfs_image: str = Field(default="")

    # Messaging
    max_message_length: int = Field(default=1600)
    message_rate_limit: int = Field(default=100)
    ai_confidence_threshold: float = Field(default=0.75, ge=0.0, le=1.0)

    # Scheduler
    message_send_start_hour: int = Field(default=8)
    message_send_end_hour: int = Field(default=21)

    # Email / SMTP
    smtp_host: str = Field(default="smtp.gmail.com")
    smtp_port: int = Field(default=587)
    smtp_user: str = Field(default="")
    smtp_password: str = Field(default="")
    email_from_name: str = Field(default="Cabin Rentals of Georgia")
    email_from_address: str = Field(default="")
    email_user: str = Field(default="")

    # IMAP (Email Bridge)
    imap_host: str = Field(default="imap.gmail.com")
    imap_user: str = Field(default="")
    imap_app_password: str = Field(default="")
    email_poll_interval: int = Field(default=60)

    # Gmail / MailPlus
    gmail_app_password: str = Field(default="")
    mailplus_imap_host: str = Field(default="")
    mailplus_imap_port: int = Field(default=993)
    mailplus_imap_password: str = Field(default="")

    # Twilio
    twilio_account_sid: str = Field(default="")
    twilio_auth_token: str = Field(default="")
    twilio_phone_number: str = Field(default="")
    twilio_status_callback_url: str = Field(default="")

    # Invites
    invite_expiry_hours: int = Field(default=72)

    # Staff notifications
    staff_notification_email: str = Field(default="")
    staff_notification_phone: str = Field(default="")

    # Keywords
    urgent_keywords_list: str = Field(default="emergency,urgent,broken,flood,fire,leak,police")

    model_config = {"env_file": ".env", "env_file_encoding": "utf-8", "extra": "ignore"}


settings = Settings()
