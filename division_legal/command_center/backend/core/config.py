"""
Legal Command Center configuration — loaded from environment.
"""
from typing import List
from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",
    )

    environment: str = Field(default="development")
    debug: bool = Field(default=True)
    api_port: int = Field(default=8200)

    database_url: str = Field(
        default="postgresql://miner_bot:password@localhost:5432/fortress_db"
    )
    database_pool_size: int = Field(default=10)
    database_max_overflow: int = Field(default=5)

    cors_origins: str = Field(
        default="http://localhost:8200,http://192.168.0.100:8200,https://crog-ai.com"
    )

    log_level: str = Field(default="INFO")

    @property
    def cors_origins_list(self) -> List[str]:
        return [o.strip() for o in self.cors_origins.split(",")]


settings = Settings()
