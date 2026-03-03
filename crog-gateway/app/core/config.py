"""
Configuration Management using Pydantic Settings

All secrets and feature flags are managed via environment variables.
NEVER hardcode API keys or credentials.
"""

from typing import Literal
from pydantic import Field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Application configuration with strict validation"""

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",
    )

    # Application
    app_name: str = "CROG Gateway"
    app_version: str = "1.0.0"
    environment: Literal["development", "staging", "production"] = "development"
    log_level: Literal["DEBUG", "INFO", "WARNING", "ERROR"] = "INFO"

    # Feature Flags - The Strangler Pattern Controllers
    enable_ai_replies: bool = Field(
        default=False,
        description="If True, AI can respond directly to guests (Cutover mode)",
    )
    shadow_mode: bool = Field(
        default=False,
        description="If True, send to both legacy AND AI, compare results",
    )
    ai_intent_filter: str = Field(
        default="",
        description="Comma-separated intents AI should handle (e.g., 'WIFI_QUESTION,CHECKIN_QUESTION')",
    )

    # RueBaRue SMS Provider (Legacy)
    ruebarue_api_url: str = Field(
        default="https://app.ruebarue.com",
        description="RueBaRue API base URL",
    )
    ruebarue_username: str = Field(
        default="",
        description="RueBaRue username (email)",
    )
    ruebarue_password: str = Field(
        default="",
        description="RueBaRue password",
    )
    ruebarue_api_key: str = Field(
        default="",
        description="RueBaRue API authentication key (alternative to username/password)",
    )
    ruebarue_phone_number: str = Field(
        default="",
        description="RueBaRue SMS sending number",
    )

    # Streamline VRS (Legacy PMS)
    streamline_api_url: str = Field(
        default="https://api.streamlinevrs.com/v2",
        description="Streamline VRS API base URL",
    )
    streamline_api_key: str = Field(
        default="",
        description="Streamline VRS API key",
    )
    streamline_property_id: str = Field(
        default="",
        description="Streamline property identifier",
    )

    # CROG AI System (New)
    crog_ai_url: str = Field(
        default="http://localhost:8000",
        description="Internal CROG AI service endpoint",
    )
    crog_ai_api_key: str = Field(
        default="",
        description="CROG AI authentication token",
    )
    
    # Twilio SMS Provider (Production)
    twilio_account_sid: str = Field(
        default="",
        description="Twilio Account SID",
    )
    twilio_auth_token: str = Field(
        default="",
        description="Twilio Auth Token",
    )
    twilio_phone_number: str = Field(
        default="",
        description="Twilio phone number in E.164 format (e.g., +15551234567)",
    )

    # Resiliency
    http_timeout_seconds: int = Field(
        default=30,
        ge=1,
        le=300,
        description="HTTP client timeout",
    )
    retry_max_attempts: int = Field(
        default=3,
        ge=1,
        le=10,
        description="Max retry attempts for external API calls",
    )
    retry_wait_seconds: int = Field(
        default=2,
        ge=1,
        le=60,
        description="Initial wait time between retries (exponential backoff)",
    )

    @field_validator("ai_intent_filter")
    @classmethod
    def parse_intent_filter(cls, v: str) -> list[str]:
        """Convert comma-separated string to list"""
        if not v:
            return []
        return [intent.strip().upper() for intent in v.split(",")]

    def should_use_ai_for_intent(self, intent: str) -> bool:
        """
        Determine if AI should handle this specific intent.
        
        Logic:
        - If enable_ai_replies=False: Never use AI
        - If ai_intent_filter is empty: Use AI for all intents
        - If ai_intent_filter has values: Only use AI for listed intents
        """
        if not self.enable_ai_replies:
            return False

        if not self.ai_intent_filter:
            # AI handles everything when filter is empty and AI is enabled
            return True

        return intent.upper() in self.ai_intent_filter


# Singleton instance
settings = Settings()
