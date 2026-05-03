"""
Application configuration using Pydantic Settings.
"""

import os
from pathlib import Path
from urllib.parse import SplitResult, urlsplit, urlunsplit

from pydantic import AliasChoices, Field, field_validator
from pydantic_settings import BaseSettings


DEFAULT_HISTORIAN_BLUEPRINT_PATH = str(
    Path(__file__).resolve().parents[1] / "scripts" / "drupal_granular_blueprint.json"
)
DEFAULT_HERMES_SYSTEM_PROMPT_PATH = str(
    Path(__file__).resolve().parents[3] / "docs" / "paperclip" / "AGENTS.md"
)
# fortress_shadow_test is the dedicated test database (Phase G.1.5).
# It mirrors fortress_shadow's schema but is safe to write test fixtures to.
ALLOWED_POSTGRES_DATABASES = frozenset(
    {"fortress_prod", "fortress_shadow", "fortress_db", "fortress_shadow_test"}
)
# Loopback plus dual-lane 200G RoCE /30 backplane (node-1 .1, node-2 .2 per lane).
ALLOWED_POSTGRES_HOSTS = frozenset(
    {
        "127.0.0.1",
        "localhost",
        "::1",
        "10.101.1.1",
        "10.101.1.2",
        "10.101.2.1",
        "10.101.2.2",
    }
)
ALLOWED_POSTGRES_PORT = 5432
ALLOWED_POSTGRES_SCHEMES = frozenset({"postgres", "postgresql", "postgresql+asyncpg"})


_VALID_LOG_LEVELS = frozenset({"DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"})


class Settings(BaseSettings):
    environment: str = Field(default="development")
    debug: bool = Field(default=False)
    log_level: str = Field(
        default="INFO",
        alias="LOG_LEVEL",
        description="Python root logger level. One of DEBUG/INFO/WARNING/ERROR/CRITICAL.",
    )

    @field_validator("log_level", mode="before")
    @classmethod
    def _normalise_log_level(cls, v: str) -> str:
        upper = (v or "INFO").strip().upper()
        return upper if upper in _VALID_LOG_LEVELS else "INFO"

    db_auto_create_tables: bool = Field(
        default=False,
        alias="DB_AUTO_CREATE_TABLES",
        description="Opt-in dev convenience flag for SQLAlchemy create_all() at startup.",
    )

    # Database
    postgres_admin_uri: str = Field(
        default="",
        alias="POSTGRES_ADMIN_URI",
        description="Local fortress_admin connection string used exclusively by Alembic migrations.",
    )
    postgres_api_uri: str = Field(
        default="",
        alias="POSTGRES_API_URI",
        description="Local fortress_api connection string used by the FastAPI runtime.",
    )
    swarm_api_key: str = Field(default="")

    # ----------------------------------------
    # Vanguard MySQL Source (Phase 1 CDC Probe)
    # ----------------------------------------
    mysql_source_host: str = Field(default="")
    mysql_source_port: int = Field(default=3306)
    mysql_source_user: str = Field(default="")
    mysql_source_password: str = Field(default="")
    mysql_source_database: str = Field(default="")
    mysql_source_ssl_mode: str = Field(default="PREFERRED")
    mysql_source_ssl_ca_path: str = Field(default="")
    mysql_source_ssl_cert_path: str = Field(default="")
    mysql_source_ssl_key_path: str = Field(default="")

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
    audit_log_signing_key: str = Field(default="")
    agentic_system_active: bool = Field(
        default=False,
        alias="AGENTIC_SYSTEM_ACTIVE",
        description="Enables Shadow Parallel observation and parity aggregation without switching live authority.",
    )
    sovereign_quote_signing_key: str = Field(
        default="",
        alias="SOVEREIGN_QUOTE_SIGNING_KEY",
        description="HMAC secret for sealed checkout quotes. When set, POST /api/direct-booking/book requires signed_quote.",
    )
    historian_blueprint_path: str = Field(default=DEFAULT_HISTORIAN_BLUEPRINT_PATH)
    historian_blueprint_db_path: str = Field(default="")
    historian_archive_output_dir: str = Field(default="")
    semrush_shadow_snapshot_path: str = Field(
        default="/mnt/fortress_nas/fortress_data/ai_brain/analytics/semrush_shadow_snapshot.json",
        alias="SEMRUSH_SHADOW_SNAPSHOT_PATH",
        description="Local SEMRush observation snapshot on sovereign storage for Shadow Parallel SEO parity.",
    )
    legacy_host_active: bool = Field(
        default=False,
        alias="LEGACY_HOST_ACTIVE",
        description="Whether workers are allowed to reach the retired legacy Drupal estate.",
    )

    @field_validator("postgres_admin_uri", "postgres_api_uri", mode="before")
    @classmethod
    def _normalize_database_uri(cls, value: str) -> str:
        return (value or "").strip()

    @field_validator("postgres_admin_uri", "postgres_api_uri")
    @classmethod
    def _validate_sovereign_postgres_contract(cls, value: str) -> str:
        if not value:
            return value

        parsed = urlsplit(value)
        if parsed.scheme not in ALLOWED_POSTGRES_SCHEMES:
            raise ValueError("PostgreSQL URIs must use postgres/postgresql schemes only.")
        host = (parsed.hostname or "").strip().lower()
        if host == "localhost":
            host = "127.0.0.1"
        if host not in ALLOWED_POSTGRES_HOSTS:
            allowed = ", ".join(sorted(ALLOWED_POSTGRES_HOSTS))
            raise ValueError(f"PostgreSQL host must be one of: {allowed}.")
        if parsed.port != ALLOWED_POSTGRES_PORT:
            raise ValueError(f"PostgreSQL port must be {ALLOWED_POSTGRES_PORT}.")
        if not parsed.username:
            raise ValueError("PostgreSQL URIs must include an explicit role name.")

        database_name = parsed.path.removeprefix("/")
        if database_name not in ALLOWED_POSTGRES_DATABASES:
            raise ValueError(
                f"PostgreSQL database must be one of: {', '.join(sorted(ALLOWED_POSTGRES_DATABASES))}."
            )

        return value

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

    @staticmethod
    def _rewrite_database_driver(uri: str, *, async_driver: bool) -> str:
        parsed = urlsplit(uri)
        if parsed.scheme not in ALLOWED_POSTGRES_SCHEMES:
            raise RuntimeError("PostgreSQL URI uses an unsupported driver.")

        target_scheme = "postgresql+asyncpg" if async_driver else "postgresql"
        rewritten = SplitResult(
            scheme=target_scheme,
            netloc=parsed.netloc,
            path=parsed.path,
            query=parsed.query,
            fragment=parsed.fragment,
        )
        return urlunsplit(rewritten)

    def _require_database_uri(self, value: str, *, expected_role: str, env_var: str) -> str:
        if not value:
            raise RuntimeError(
                f"{env_var} must be set to a local PostgreSQL 16 URI for Fortress Prime."
            )

        parsed = urlsplit(value)
        role_name = parsed.username or ""
        if role_name != expected_role:
            raise RuntimeError(f"{env_var} must authenticate as {expected_role}.")

        return value

    @property
    def database_url(self) -> str:
        runtime_uri = self._require_database_uri(
            self.postgres_api_uri,
            expected_role="fortress_api",
            env_var="POSTGRES_API_URI",
        )
        return self._rewrite_database_driver(runtime_uri, async_driver=True)

    @property
    def database_admin_url(self) -> str:
        admin_uri = self._require_database_uri(
            self.postgres_admin_uri,
            expected_role="fortress_admin",
            env_var="POSTGRES_ADMIN_URI",
        )
        return self._rewrite_database_driver(admin_uri, async_driver=True)

    @property
    def alembic_database_url(self) -> str:
        admin_uri = self._require_database_uri(
            self.postgres_admin_uri,
            expected_role="fortress_admin",
            env_var="POSTGRES_ADMIN_URI",
        )
        return self._rewrite_database_driver(admin_uri, async_driver=False)

    @property
    def database_name(self) -> str:
        runtime_uri = self._require_database_uri(
            self.postgres_api_uri,
            expected_role="fortress_api",
            env_var="POSTGRES_API_URI",
        )
        return urlsplit(runtime_uri).path.removeprefix("/")

    @property
    def test_database_url(self) -> str | None:
        """Async DSN for the isolated test database (fortress_shadow_test).

        Set TEST_DATABASE_URL to redirect conftest fixtures away from the
        production fortress_shadow DB. When unset, tests fall back to the
        runtime DB (fortress_shadow) with a warning emitted by conftest.

        The URL must use fortress_api as the role (runtime user), not
        fortress_admin — so tests exercise the same permission surface as
        the application.

        Example:
            TEST_DATABASE_URL=postgresql://fortress_api:PASSWORD@127.0.0.1:5432/fortress_shadow_test
        """
        raw = os.getenv("TEST_DATABASE_URL", "").strip()
        if not raw:
            return None
        return self._rewrite_database_driver(raw, async_driver=True)

    @property
    def sovereign_quote_signing_enabled(self) -> bool:
        return bool(self.sovereign_quote_signing_key.strip())

    secret_key: str = Field(default="change-me-fortress-secret")

    @field_validator("swarm_api_key", mode="before")
    @classmethod
    def _normalize_swarm_api_key(cls, value: str) -> str:
        return (value or "").strip()

    # Command Center
    command_center_url: str = Field(default="http://localhost:9800")
    frontend_url: str = Field(default="https://crog-ai.com")
    command_center_ingress_hosts: str = Field(
        default="",
        alias="COMMAND_CENTER_INGRESS_HOSTS",
        description=(
            "Comma-separated extra hostnames allowed for Command Center /api ingress "
            "(e.g. LAN staging: 192.168.0.100,192.168.0.114)."
        ),
    )

    # AI Models — Local (DGX)
    ollama_base_url: str = Field(default="http://192.168.0.100:11434")
    ollama_fast_model: str = Field(default="qwen2.5:7b")
    ollama_deep_model: str = Field(default="deepseek-r1:70b")
    use_local_llm: bool = Field(default=True)

    # AI Models — DGX Nodes
    dgx_reasoner_url: str = Field(default="http://192.168.0.100/hydra/v1")
    dgx_reasoner_model: str = Field(default="deepseek-r1:70b")
    dgx_inference_url: str = Field(
        default="",
        alias="DGX_INFERENCE_URL",
        description="Direct sovereign OpenAI-compatible /v1 endpoint for local DGX inference.",
    )
    dgx_inference_model: str = Field(
        default="",
        alias="DGX_INFERENCE_MODEL",
        description="Model alias served by the direct DGX inference endpoint.",
    )
    dgx_inference_api_key: str = Field(
        default="",
        alias="DGX_INFERENCE_API_KEY",
        description="Optional bearer token for the DGX inference endpoint.",
    )
    dgx_ocular_url: str = Field(default="http://192.168.0.105:8000/v1")
    dgx_ocular_model: str = Field(default="qwen2.5:7b")
    dgx_memory_url: str = Field(default="http://192.168.0.106:8000/v1")
    dgx_memory_model: str = Field(default="qwen2.5:7b")
    nemoclaw_orchestrator_url: str = Field(
        default="http://192.168.0.100:8000",
        description="Authoritative Ray-governed NemoClaw control-plane base URL on the sovereign head node.",
    )
    nemoclaw_orchestrator_api_key: str = Field(default="")
    paperclip_control_plane_url: str = Field(
        default="",
        alias="PAPERCLIP_CONTROL_PLANE_URL",
        description="Paperclip control-plane base URL used for Fortress BYOA callback delivery.",
    )
    paperclip_control_plane_api_key: str = Field(
        default="",
        alias="PAPERCLIP_CONTROL_PLANE_API_KEY",
        description="Paperclip API key used by the Fortress bridge to POST heartbeat-run callbacks.",
    )
    hermes_system_prompt_path: str = Field(
        default=DEFAULT_HERMES_SYSTEM_PROMPT_PATH,
        alias="HERMES_SYSTEM_PROMPT_PATH",
        description="Absolute path to the AGENTS.md contract injected into Hermes/Paperclip execute payloads.",
    )
    hermes_memory_path: str = Field(
        default="/app/memory",
        alias="HERMES_MEMORY_PATH",
        description="Persistent SQLite/FTS5 working directory mounted into the Hermes container.",
    )
    firecrawl_api_key: str = Field(
        default="",
        alias="FIRECRAWL_API_KEY",
        description="Firecrawl API key used by the acquisition ingestion worker.",
    )
    firecrawl_base_url: str = Field(
        default="https://api.firecrawl.dev",
        alias="FIRECRAWL_BASE_URL",
        description="Base URL for Firecrawl extract/scrape requests.",
    )
    firecrawl_timeout_seconds: float = Field(
        default=120.0,
        alias="FIRECRAWL_TIMEOUT_SECONDS",
        description="HTTP timeout for Firecrawl ingestion requests.",
    )
    apollo_api_key: str = Field(
        default="",
        alias="APOLLO_API_KEY",
        description="Apollo master API key used for owner contact enrichment.",
    )
    apollo_base_url: str = Field(
        default="https://api.apollo.io/api/v1",
        alias="APOLLO_BASE_URL",
        description="Apollo API base URL for people search and enrichment.",
    )
    airdna_api_key: str = Field(
        default="",
        alias="AIRDNA_API_KEY",
        description="AirDNA API key used for vendor-grade STR signal ingestion.",
    )
    airdna_base_url: str = Field(
        default="",
        alias="AIRDNA_BASE_URL",
        description="AirDNA base URL for STR market sync calls.",
    )
    airdna_market_path: str = Field(
        default="",
        alias="AIRDNA_MARKET_PATH",
        description="Relative AirDNA path used by the STR sync worker to fetch market or listing data.",
    )
    airdna_timeout_seconds: float = Field(
        default=45.0,
        alias="AIRDNA_TIMEOUT_SECONDS",
        description="HTTP timeout for AirDNA market sync requests.",
    )
    airdna_market: str = Field(
        default="Fannin County, Georgia",
        alias="AIRDNA_MARKET",
        description="Default AirDNA market label for the STR sync worker.",
    )
    airdna_sync_enabled: bool = Field(
        default=False,
        alias="AIRDNA_SYNC_ENABLED",
        description="Enables recurring AirDNA STR signal sync jobs on the ARQ worker.",
    )
    airdna_sync_interval_seconds: int = Field(
        default=21600,
        alias="AIRDNA_SYNC_INTERVAL_SECONDS",
        description="Seconds between recurring AirDNA STR sync enqueue attempts.",
    )
    orchestrator_source: str = Field(default="spark_node_2_leader")
    inbound_agentic_loop_enabled: bool = Field(default=True)
    swarm_model: str = Field(default="qwen2.5:14b")
    seo_swarm_api_key: str = Field(
        default="",
        validation_alias=AliasChoices("SWARM_SEO_API_KEY", "SEO_SWARM_API_KEY"),
    )
    seo_grading_consumer_enabled: bool = Field(default=True)
    seo_rewrite_consumer_enabled: bool = Field(default=True)
    seo_deploy_consumer_enabled: bool = Field(default=True)
    semrush_shadow_observer_enabled: bool = Field(
        default=False,
        alias="SEMRUSH_SHADOW_OBSERVER_ENABLED",
        description="Enables recurring SEMRush Shadow Parallel observation jobs.",
    )
    semrush_shadow_observer_interval_seconds: int = Field(
        default=900,
        alias="SEMRUSH_SHADOW_OBSERVER_INTERVAL_SECONDS",
        description="Seconds between recurring SEMRush Shadow Parallel observation jobs.",
    )
    research_scout_enabled: bool = Field(
        default=False,
        alias="RESEARCH_SCOUT_ENABLED",
        description="Enables recurring Gemini-grounded market intelligence Scout jobs.",
    )
    research_scout_interval_seconds: int = Field(
        default=86400,
        alias="RESEARCH_SCOUT_INTERVAL_SECONDS",
        description="Seconds between recurring Research Scout cycles.",
    )
    research_scout_market: str = Field(
        default="Blue Ridge, Georgia",
        alias="RESEARCH_SCOUT_MARKET",
        description="Primary market locality used by the Research Scout prompt.",
    )
    acquisition_worker_enabled: bool = Field(
        default=False,
        alias="ACQUISITION_WORKER_ENABLED",
        description="Enables recurring CROG acquisition ingestion cycles on the ARQ worker.",
    )
    acquisition_worker_interval_seconds: int = Field(
        default=21600,
        alias="ACQUISITION_WORKER_INTERVAL_SECONDS",
        description="Seconds between recurring acquisition ingestion enqueue attempts.",
    )
    acquisition_default_county: str = Field(
        default="Fannin",
        alias="ACQUISITION_DEFAULT_COUNTY",
        description="Default county used when acquisition parcel records omit county_name.",
    )
    acquisition_qpublic_url: str = Field(
        default="",
        alias="ACQUISITION_QPUBLIC_URL",
        description="qPublic or equivalent parcel-source URL for acquisition ingestion.",
    )
    acquisition_str_permits_url: str = Field(
        default="",
        alias="ACQUISITION_STR_PERMITS_URL",
        description="County/municipal STR registry URL for acquisition ingestion.",
    )
    acquisition_ota_search_urls: str = Field(
        default="",
        alias="ACQUISITION_OTA_SEARCH_URLS",
        description="Comma-separated OTA search URLs used for heuristic Airbnb/Vrbo sweeps.",
    )
    acquisition_ota_radius_meters: int = Field(
        default=75,
        alias="ACQUISITION_OTA_RADIUS_METERS",
        description="Fallback PostGIS match radius for OTA listing coordinate resolution.",
    )
    acquisition_b2c_contact_provider: str = Field(
        default="mock",
        alias="ACQUISITION_B2C_CONTACT_PROVIDER",
        description="B2C owner contact provider stage inserted after Apollo: mock|propertyradar|trellis.",
    )
    recursive_agent_loop_enabled: bool = Field(
        default=True,
        alias="RECURSIVE_AGENT_LOOP_ENABLED",
        description="Enables the cross-vertical recursive intelligence flywheel (V1/V2/V3 signal bus).",
    )
    concierge_shadow_draft_enabled: bool = Field(
        default=False,
        alias="CONCIERGE_SHADOW_DRAFT_ENABLED",
        description="Enables recurring Concierge Alpha recovery draft parity (legacy vs sovereign) jobs.",
    )
    concierge_shadow_draft_interval_seconds: int = Field(
        default=1800,
        alias="CONCIERGE_SHADOW_DRAFT_INTERVAL_SECONDS",
        description="Seconds between Concierge Alpha shadow-draft enqueue attempts (~30m default).",
    )
    concierge_recovery_parity_candidate_limit: int = Field(
        default=25,
        alias="CONCIERGE_RECOVERY_PARITY_CANDIDATE_LIMIT",
        description="Max funnel recovery candidates scanned per shadow-draft cycle.",
    )
    hunter_queue_sweep_enabled: bool = Field(
        default=True,
        alias="HUNTER_QUEUE_SWEEP_ENABLED",
        description="Enables recurring Reactivation Hunter queue sweeps on the ARQ worker heartbeat.",
    )
    hunter_queue_sweep_interval_seconds: int = Field(
        default=300,
        alias="HUNTER_QUEUE_SWEEP_INTERVAL_SECONDS",
        description="Seconds between Hunter queue sweep enqueue attempts (~5m default).",
    )
    hunter_queue_candidate_limit: int = Field(
        default=50,
        alias="HUNTER_QUEUE_CANDIDATE_LIMIT",
        description="Max candidates gathered per prey class during a Hunter queue sweep.",
    )
    node_ip: str = Field(default="127.0.0.1")
    seo_redirect_swarm_model: str = Field(default="nemotron-3-super-120b")
    seo_grade_requests_channel: str = Field(default="fortress:seo:grade_requests")
    seo_redirect_grade_threshold: float = Field(default=0.95)
    seo_godhead_min_score: float = Field(default=0.95)
    seo_max_rewrite_attempts: int = Field(default=3)
    seo_redis_cache_ttl: int = Field(default=3600)
    seo_godhead_model: str = Field(default="nemotron-3-super-120b")
    edge_revalidation_secret: str = Field(default="")
    storefront_base_url: str = Field(default="https://cabin-rentals-of-georgia.com")
    storefront_revalidate_origin: str = Field(default="")

    # Strike 8 — Redirect Vanguard (Cloudflare KV registry of sovereign-ready cabin slugs)
    cloudflare_account_id: str = Field(default="", alias="CLOUDFLARE_ACCOUNT_ID")
    cloudflare_api_token: str = Field(default="", alias="CLOUDFLARE_API_TOKEN")
    cloudflare_kv_namespace_deployed_slugs: str = Field(
        default="",
        alias="CLOUDFLARE_KV_NAMESPACE_DEPLOYED_SLUGS",
        description="Workers KV namespace ID for cabin slugs that should proxy to the sovereign storefront.",
    )

    @property
    def swarm_seo_api_key(self) -> str:
        return self.seo_swarm_api_key

    @property
    def internal_api_bearer_token(self) -> str:
        return (self.internal_api_token or self.swarm_api_key).strip()

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
    litellm_master_key: str = Field(
        default="fortress-dev-key",
        description="Bearer token used by internal services to authenticate to the LiteLLM proxy.",
    )

    # Internal service HTTP
    internal_api_base_url: str = Field(
        default="http://127.0.0.1:8100",
        alias="INTERNAL_API_BASE_URL",
        description="Trusted local Fortress API base URL used by sovereign workers (consumer, sweepers, rule engine).",
    )
    internal_api_token: str = Field(
        default="",
        alias="INTERNAL_API_TOKEN",
        description="Bearer token for worker-to-API calls. Falls back to SWARM_API_KEY when unset.",
    )

    # Gateway
    gateway_api_url: str = Field(default="http://localhost:8000")

    # Qdrant — primary (spark-2)
    qdrant_url: str = Field(default="http://localhost:6333")
    qdrant_api_key: str = Field(default="")
    qdrant_collection_name: str = Field(default="fgp_knowledge")
    # Qdrant — VRS secondary (spark-4, Phase 5a Part 3 dual-write)
    qdrant_vrs_url: str = Field(default="http://192.168.0.106:6333")
    enable_qdrant_vrs_dual_write: bool = Field(default=True)
    # Phase 5a Part 4 — read cutover (Option A: restart to flip)
    # False  → reads target spark-2 fgp_knowledge (default, safe)
    # True   → reads target spark-4 fgp_vrs_knowledge
    # Run src/rag/verify_dual_write_parity.py --compare-search before flipping.
    read_from_vrs_store: bool = Field(default=False)
    # Phase 5b — NIM sovereign inference endpoint (Docker/systemd on spark-1)
    # Replaces k8s ClusterIP 10.43.38.88:8000 after cutover.
    # Model: meta/llama-3.1-8b-instruct (DGX Spark variant)
    nim_sovereign_url: str = Field(default="http://192.168.0.104:8000")
    # Phase A5 — BRAIN (Tier 2 sovereign reasoning) inference endpoint.
    # Currently NIM 2.0.1 / vLLM serving nvidia/Llama-3.3-Nemotron-Super-49B-v1.5-FP8
    # on spark-5:8100, reached over Tailscale by hostname.
    brain_base_url: str = Field(
        default="http://spark-5:8100",
        alias="BRAIN_BASE_URL",
        description="OpenAI-compatible /v1 base URL for the BRAIN inference service (spark-5).",
    )
    # Phase B drafting orchestrator (case_briefing_compose.py) — output root.
    # Default points at the canonical NAS filings/outgoing/ layout. Operator
    # may override with `--output-dir` on the CLI for ad-hoc / dry-run output.
    case_briefing_output_root: str = Field(
        default="/mnt/fortress_nas/Corporate_Legal/Business_Legal",
        alias="CASE_BRIEFING_OUTPUT_ROOT",
        description="NAS root under which `case_briefing_cli compose` writes briefing packages (`<root>/<case_slug>/filings/outgoing/`).",
    )

    # Redis
    redis_url: str = Field(default="redis://localhost:6379/0")
    arq_redis_url: str = Field(default="redis://localhost:6379/1")
    arq_queue_name: str = Field(default="fortress:arq")
    arq_concurrency: int = Field(default=8)
    arq_job_timeout_seconds: int = Field(default=3600)
    arq_keep_result_seconds: int = Field(default=86400)
    arq_max_tries: int = Field(default=3)
    async_job_watchdog_enabled: bool = Field(
        default=True,
        alias="ASYNC_JOB_WATCHDOG_ENABLED",
        description="Enables the ARQ worker watchdog that detects and repairs stale async job ledger rows.",
    )
    async_job_watchdog_interval_seconds: int = Field(
        default=60,
        alias="ASYNC_JOB_WATCHDOG_INTERVAL_SECONDS",
        description="Seconds between async job watchdog sweeps.",
    )
    async_job_stale_queued_seconds: int = Field(
        default=180,
        alias="ASYNC_JOB_STALE_QUEUED_SECONDS",
        description="Queued job age threshold before the watchdog raises an alert.",
    )
    async_job_stale_running_seconds: int = Field(
        default=900,
        alias="ASYNC_JOB_STALE_RUNNING_SECONDS",
        description="Running job age threshold before the watchdog raises an alert.",
    )
    council_stream_ttl_seconds: int = Field(default=86400)
    council_stream_maxlen: int = Field(default=500)
    council_stream_heartbeat_seconds: int = Field(default=15)

    # Sovereign object storage
    s3_endpoint_url: str = Field(
        default="",
        alias="S3_ENDPOINT_URL",
        description="S3-compatible API endpoint for sovereign media storage.",
    )
    s3_bucket_name: str = Field(
        default="",
        alias="S3_BUCKET_NAME",
        description="Bucket name for sovereign media storage.",
    )
    s3_access_key: str = Field(
        default="",
        alias="S3_ACCESS_KEY",
        description="Access key for sovereign media storage.",
    )
    s3_secret_key: str = Field(
        default="",
        alias="S3_SECRET_KEY",
        description="Secret key for sovereign media storage.",
    )
    s3_public_base_url: str = Field(
        default="",
        alias="S3_PUBLIC_BASE_URL",
        description="Public CDN base URL for sovereign media reads. Falls back to endpoint/bucket path style when omitted.",
    )

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
    streamline_sovereign_bridge_hold_enabled: bool = Field(
        default=False,
        alias="STREAMLINE_SOVEREIGN_BRIDGE_HOLD_ENABLED",
        description=(
            "When true, notify Streamline after a sovereign checkout hold commits "
            "(RPC method from STREAMLINE_SOVEREIGN_BRIDGE_HOLD_METHOD)."
        ),
    )
    streamline_sovereign_bridge_hold_method: str = Field(
        default="",
        alias="STREAMLINE_SOVEREIGN_BRIDGE_HOLD_METHOD",
        description=(
            "Streamline JSON-RPC methodName for a temporary admin block/hold (account-specific; "
            "empty skips outbound calls while the bridge flag is on)."
        ),
    )
    streamline_sovereign_bridge_settlement_enabled: bool = Field(
        default=False,
        alias="STREAMLINE_SOVEREIGN_BRIDGE_SETTLEMENT_ENABLED",
        description=(
            "When true, after a direct-booking hold converts to a reservation via Stripe webhook, "
            "emit an optional Streamline RPC (STREAMLINE_SOVEREIGN_BRIDGE_RESERVATION_METHOD)."
        ),
    )
    streamline_sovereign_bridge_reservation_method: str = Field(
        default="",
        alias="STREAMLINE_SOVEREIGN_BRIDGE_RESERVATION_METHOD",
        description=(
            "Streamline JSON-RPC methodName for post-settlement reservation sync (account-specific)."
        ),
    )

    deferred_api_reconciliation_enabled: bool = Field(
        default=False,
        alias="DEFERRED_API_RECONCILIATION_ENABLED",
        description=(
            "When true, ARQ worker runs a background loop that replays pending "
            "deferred_api_writes rows for Streamline (Strike 20 / circuit-deferred RPC)."
        ),
    )
    deferred_api_reconciliation_interval_seconds: int = Field(
        default=120,
        alias="DEFERRED_API_RECONCILIATION_INTERVAL_SECONDS",
        ge=30,
        description="Sleep between reconciliation sweeps in the worker background loop.",
    )
    deferred_api_reconciliation_batch_size: int = Field(
        default=50,
        alias="DEFERRED_API_RECONCILIATION_BATCH_SIZE",
        ge=1,
        le=500,
        description="Max deferred Streamline rows to process per sweep.",
    )
    deferred_api_reconciliation_max_retries: int = Field(
        default=10,
        alias="DEFERRED_API_RECONCILIATION_MAX_RETRIES",
        ge=1,
        le=1000,
        description="After this many failed replay attempts, row status becomes failed_final.",
    )

    # Stripe Payments
    stripe_secret_key: str = Field(default="", alias="STRIPE_SECRET_KEY")
    stripe_publishable_key: str = Field(default="")
    stripe_webhook_secret: str = Field(default="", alias="STRIPE_WEBHOOK_SECRET")
    stripe_connect_webhook_secret: str = Field(default="")
    stripe_dispute_webhook_secret: str = Field(default="")
    stripe_connect_client_id: str = Field(
        default="",
        alias="STRIPE_CONNECT_CLIENT_ID",
        description=(
            "Stripe Connect application client_id (ca_...). "
            "Required for Standard OAuth Connect. Not needed for Express accounts."
        ),
    )
    reservation_hold_ttl_minutes: int = Field(
        default=15,
        description="Checkout hold duration before reservation_holds expire.",
    )

    # Continuous Liquidity
    minimum_payout_amount: float = Field(default=25.00)

    # Reservation Webhooks (HMAC shared secret for POST /api/webhooks/reservations)
    reservation_webhook_secret: str = Field(default="")

    # Streamline inbound webhook (POST /api/webhooks/streamline) — optional dedicated secret.
    # When empty, HMAC verification uses reservation_webhook_secret (same as /reservations).
    streamline_webhook_secret: str = Field(
        default="",
        alias="STREAMLINE_WEBHOOK_SECRET",
        description="HMAC secret for Streamline payload vault webhooks; falls back to reservation_webhook_secret.",
    )

    # Channex (or compatible headless channel manager) — POST /api/webhooks/channex
    channex_webhook_secret: str = Field(default="", alias="CHANNEX_WEBHOOK_SECRET")
    # Channex egress (availability push) — used by backend.workers.channex_egress
    channex_api_base_url: str = Field(default="", alias="CHANNEX_API_BASE_URL")
    channex_api_key: str = Field(default="", alias="CHANNEX_API_KEY")

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
    LEGAL_VAULT_ROOT: str = "/mnt/fortress_nas/sectors/legal"
    nas_work_orders_root: str = Field(
        default="/mnt/fortress_nas/work_orders",
        alias="NAS_WORK_ORDERS_ROOT",
        description="NAS mount path for work order photo storage.",
    )
    nas_acquisitions_root: str = Field(
        default="/mnt/fortress_nas/acquisitions",
        alias="NAS_ACQUISITIONS_ROOT",
        description="NAS mount path for acquisition document storage.",
    )

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
    sandbox_work_dir: str = Field(
        default="/var/lib/fortress/fireclaw",
        description="Per-run Fireclaw workspace root on the host (payload ext4 + FC config).",
    )
    sandbox_payload_mb: int = Field(
        default=32,
        ge=8,
        le=256,
        description="Size of the ephemeral ext4 payload volume (secondary drive) in MiB.",
    )
    sandbox_kernel_boot_args: str = Field(
        default="",
        description=(
            "Kernel cmdline for Firecracker; empty uses a minimal virtio-root + serial console default."
        ),
    )
    sandbox_interrogate_max_mb: int = Field(
        default=48,
        ge=1,
        le=200,
        description="Max upload size (MB) for Fireclaw interrogation mode (PDF/binary payload).",
    )

    # Messaging
    max_message_length: int = Field(default=1600)
    message_rate_limit: int = Field(default=100)
    ai_confidence_threshold: float = Field(default=0.75, ge=0.0, le=1.0)

    # Scheduler
    message_send_start_hour: int = Field(default=8)
    message_send_end_hour: int = Field(default=21)

    # Email / SMTP (kept for IMAP inbound paths that still reference smtp_user)
    smtp_host: str = Field(default="smtp.gmail.com")
    smtp_port: int = Field(default=587)
    smtp_user: str = Field(default="")
    smtp_password: str = Field(default="")
    email_from_name: str = Field(default="Cabin Rentals of Georgia")
    email_from_address: str = Field(default="")
    email_user: str = Field(default="")

    # Gmail API (OAuth2) — outbound sending via Gmail API instead of SMTP
    gmail_client_id: str = Field(default="", alias="GMAIL_CLIENT_ID")
    gmail_client_secret: str = Field(default="", alias="GMAIL_CLIENT_SECRET")
    gmail_refresh_token: str = Field(default="", alias="GMAIL_REFRESH_TOKEN")

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

    # Legal Email Intake (dedicated MailPlus inbox for legal correspondence)
    legal_mailplus_host: str = Field(default="", alias="LEGAL_MAILPLUS_HOST")
    legal_mailplus_port: int = Field(default=993, alias="LEGAL_MAILPLUS_PORT")
    legal_mailplus_user: str = Field(default="", alias="LEGAL_MAILPLUS_USER")
    legal_mailplus_password: str = Field(default="", alias="LEGAL_MAILPLUS_PASSWORD")
    legal_mailplus_folder: str = Field(default="INBOX", alias="LEGAL_MAILPLUS_FOLDER")
    legal_email_poll_interval: int = Field(default=120, alias="LEGAL_EMAIL_POLL_INTERVAL")
    legal_email_intake_enabled: bool = Field(default=False, alias="LEGAL_EMAIL_INTAKE_ENABLED")

    # Deprecated — legacy single-mailbox legal_email_intake loop. Captain's
    # multi-mailbox intake (LEGAL_EMAIL_INTAKE_ENABLED) supersedes this for
    # legal@cabin-rentals-of-georgia.com. Kept as an emergency-rollback gate
    # only. Set true only if you need to revert to the pre-captain path.
    legacy_legal_intake_enabled: bool = Field(
        default=False, alias="LEGACY_LEGAL_INTAKE_ENABLED"
    )

    # FLOS Phase 0a-2 — legal_mail_ingester (separate pipeline from Captain).
    # Polls mailboxes tagged with `ingester=legal_mail` in MAILBOXES_CONFIG,
    # writes bilateral to email_archive (fortress_db + fortress_prod), emits
    # to legal.event_log. Coexists with Captain (BODY.PEEK[] preserves
    # \\Seen so Captain's parallel polling sees the same UNSEEN set).
    # Default OFF during Phase 0a-2 rollout — flip ON after Phase 0a-3
    # validation (CLI + health endpoint) per design v1.1 §11.
    legal_mail_ingester_enabled: bool = Field(
        default=False, alias="LEGAL_MAIL_INGESTER_ENABLED"
    )

    # FLOS Phase 1-2 — legal_dispatcher (consumer side of the FLOS event
    # architecture). Polls legal.event_log for unprocessed rows, dispatches
    # to handlers in the in-file _HANDLERS registry, records attempt
    # outcomes to legal.dispatcher_event_attempts, emits dead-letter events
    # when retries are exhausted. Single writer to legal.case_posture
    # (Principle 1; case_posture writes ship in Phase 1-3 handlers).
    # Default OFF during Phase 1-2/1-3/1-4 rollout — flip ON after Phase
    # 1-4 (CLI + health endpoint) validation per design v1.1 §11 +
    # implementation spec §1 cutover gating.
    legal_dispatcher_enabled: bool = Field(
        default=False, alias="LEGAL_DISPATCHER_ENABLED"
    )

    # M3 — Spark-1 mirror (catchup phase of legal migration)
    LEGAL_M3_SPARK1_MIRROR_ENABLED: bool = False
    SPARK1_DATABASE_URL: str = ""

    # Captain junk/bulk-mail filter. When true (default), every inbound
    # email runs through captain_junk_filter.classify_junk() BEFORE the
    # privilege filter — junked mail is dropped with a log line, zero DB
    # writes. Set false to revert to pre-junk-filter behaviour without
    # editing code.
    captain_junk_filter_enabled: bool = Field(
        default=True, alias="CAPTAIN_JUNK_FILTER_ENABLED"
    )

    # Twilio
    twilio_account_sid: str = Field(default="")
    twilio_auth_token: str = Field(default="")
    twilio_phone_number: str = Field(default="")
    twilio_status_callback_url: str = Field(default="")
    # Strike 11 — Enticer Swarm (off by default; requires Twilio env).
    concierge_recovery_sms_enabled: bool = Field(default=False, alias="CONCIERGE_RECOVERY_SMS_ENABLED")
    concierge_recovery_sms_cooldown_hours: int = Field(
        default=168,
        ge=1,
        le=8760,
        alias="CONCIERGE_RECOVERY_SMS_COOLDOWN_HOURS",
    )
    concierge_recovery_sms_body_template: str = Field(default="", alias="CONCIERGE_RECOVERY_SMS_BODY_TEMPLATE")
    concierge_storefront_book_url: str = Field(
        default="https://cabin-rentals-of-georgia.com/book",
        alias="CONCIERGE_STOREFRONT_BOOK_URL",
    )
    # Strike 17 — Active Pilot: granular authority for live recovery SMS (Enticer Swarm).
    concierge_strike_enabled: bool = Field(
        default=False,
        alias="CONCIERGE_STRIKE_ENABLED",
        description="When true with recovery SMS enabled, live sends require cohort allowlists and optional agentic gate.",
    )
    concierge_strike_allowed_guest_ids: str = Field(
        default="",
        alias="CONCIERGE_STRIKE_ALLOWED_GUEST_IDS",
        description="Comma-separated guest UUIDs permitted for live recovery under Strike 17.",
    )
    concierge_strike_allowed_property_slugs: str = Field(
        default="",
        alias="CONCIERGE_STRIKE_ALLOWED_PROPERTY_SLUGS",
        description="Comma-separated storefront property slugs permitted for live recovery under Strike 17.",
    )
    concierge_strike_allowed_loyalty_tiers: str = Field(
        default="",
        alias="CONCIERGE_STRIKE_ALLOWED_LOYALTY_TIERS",
        description="Comma-separated loyalty tiers (e.g. gold,silver) permitted when non-empty.",
    )
    concierge_strike_require_agentic_system_active: bool = Field(
        default=True,
        alias="CONCIERGE_STRIKE_REQUIRE_AGENTIC_SYSTEM_ACTIVE",
        description="When true, Strike 17 live sends are blocked unless AGENTIC_SYSTEM_ACTIVE is on (kill-switch).",
    )
    sendgrid_inbound_public_key: str = Field(default="", alias="SENDGRID_INBOUND_PUBLIC_KEY")
    sendgrid_inbound_max_age_seconds: int = Field(default=300, alias="SENDGRID_INBOUND_MAX_AGE_SECONDS")

    # Invites
    invite_expiry_hours: int = Field(default=72)

    # System Health (sovereign telemetry: NVML, SNMP MikroTik, Synology mounts)
    system_health_mikrotik_snmp_host: str = Field(
        default="",
        alias="SYSTEM_HEALTH_MIKROTIK_SNMP_HOST",
        description="MikroTik (or switch) SNMP agent host. Empty disables SNMP interface polling.",
    )
    system_health_mikrotik_snmp_version: str = Field(
        default="v2c",
        alias="SYSTEM_HEALTH_MIKROTIK_SNMP_VERSION",
        description="SNMP security model for telemetry polling: v2c or v3.",
    )
    system_health_mikrotik_snmp_community: str | None = Field(
        default=None,
        alias="SYSTEM_HEALTH_MIKROTIK_SNMP_COMMUNITY",
        description="SNMPv2c community for MikroTik CRS / CRS812 telemetry.",
    )
    system_health_mikrotik_snmp_port: int = Field(
        default=161,
        alias="SYSTEM_HEALTH_MIKROTIK_SNMP_PORT",
        description="SNMP UDP port (usually 161).",
    )
    system_health_mikrotik_snmp_if_indices: str = Field(
        default="",
        alias="SYSTEM_HEALTH_MIKROTIK_SNMP_IF_INDICES",
        description="Comma-separated IF-MIB ifIndex values to poll (e.g. 1,2,3).",
    )
    system_health_mikrotik_snmp_v3_username: str | None = Field(
        default=None,
        alias="SYSTEM_HEALTH_MIKROTIK_SNMP_V3_USERNAME",
        description="SNMPv3 username for MikroTik telemetry polling.",
    )
    system_health_mikrotik_snmp_v3_auth_protocol: str | None = Field(
        default="SHA",
        alias="SYSTEM_HEALTH_MIKROTIK_SNMP_V3_AUTH_PROTOCOL",
        description="SNMPv3 auth protocol: SHA or MD5.",
    )
    system_health_mikrotik_snmp_v3_auth_key: str | None = Field(
        default=None,
        alias="SYSTEM_HEALTH_MIKROTIK_SNMP_V3_AUTH_KEY",
        description="SNMPv3 auth key for MikroTik telemetry polling.",
    )
    system_health_mikrotik_snmp_v3_priv_protocol: str | None = Field(
        default="AES128",
        alias="SYSTEM_HEALTH_MIKROTIK_SNMP_V3_PRIV_PROTOCOL",
        description="SNMPv3 privacy protocol: AES128 or DES.",
    )
    system_health_mikrotik_snmp_v3_priv_key: str | None = Field(
        default=None,
        alias="SYSTEM_HEALTH_MIKROTIK_SNMP_V3_PRIV_KEY",
        description="SNMPv3 privacy key for MikroTik telemetry polling.",
    )
    system_health_synology_mount_paths: str = Field(
        default="/mnt/synology",
        alias="SYSTEM_HEALTH_SYNOLOGY_MOUNT_PATHS",
        description="Comma-separated mount paths for sovereign NAS capacity telemetry.",
    )

    # Staff notifications
    staff_notification_email: str = Field(default="")
    staff_notification_phone: str = Field(default="")

    # ── Owner Statement System (Phase F) ─────────────────────────────────────
    #
    # CROG_STATEMENTS_PARALLEL_MODE (default: True)
    #   When True, the send_approved_statements_job cron fires but does NOT
    #   send any emails to real owners. Statements are generated normally on
    #   the 12th but the 15th send is suppressed. Set to False ONLY after
    #   Phase G validation has completed and the product owner has approved
    #   the production cutover.
    crog_statements_parallel_mode: bool = Field(
        default=True,
        alias="CROG_STATEMENTS_PARALLEL_MODE",
    )
    #
    # OWNER_STATEMENT_ALERT_EMAIL (required for monitoring)
    #   Email address that receives a run-summary after every cron fire
    #   (both the generation job and the send job). Leave empty to disable
    #   alert emails (useful in dev environments).
    owner_statement_alert_email: str = Field(
        default="",
        alias="OWNER_STATEMENT_ALERT_EMAIL",
    )

    # Keywords
    urgent_keywords_list: str = Field(default="emergency,urgent,broken,flood,fire,leak,police")

    @field_validator(
        "stripe_secret_key",
        "stripe_webhook_secret",
        "stripe_connect_client_id",
        mode="before",
    )
    @classmethod
    def _normalize_stripe_secrets(cls, value: str) -> str:
        return (value or "").strip()

    @field_validator(
        "s3_endpoint_url",
        "s3_bucket_name",
        "s3_access_key",
        "s3_secret_key",
        "s3_public_base_url",
        mode="before",
    )
    @classmethod
    def _normalize_s3_config(cls, value: str) -> str:
        return (value or "").strip()

    model_config = {"env_file": ".env", "env_file_encoding": "utf-8", "extra": "ignore"}


settings = Settings()
