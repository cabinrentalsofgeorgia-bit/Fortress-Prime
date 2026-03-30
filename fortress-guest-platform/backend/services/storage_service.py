"""Sovereign S3-compatible object storage helpers."""

from __future__ import annotations

import asyncio
import shutil
import subprocess
import tempfile
from pathlib import Path
from urllib.parse import quote

import boto3
from botocore.client import Config as BotoConfig
import structlog

from backend.core.config import settings

logger = structlog.get_logger(service="storage_service")
APP_ROOT = Path(__file__).resolve().parents[2]


class StorageConfigurationError(RuntimeError):
    """Raised when sovereign storage settings are incomplete."""


def _normalized_key(destination_key: str) -> str:
    key = destination_key.strip().lstrip("/")
    if not key:
        raise ValueError("destination_key must not be empty")
    return key


class SovereignStorageService:
    """Uploads property media into the configured sovereign bucket."""

    @staticmethod
    def _has_s3_credentials() -> bool:
        return bool(
            settings.s3_endpoint_url
            and settings.s3_bucket_name
            and settings.s3_access_key
            and settings.s3_secret_key
        )

    def _require_config(self) -> tuple[str, str, str, str]:
        endpoint_url = settings.s3_endpoint_url
        bucket_name = settings.s3_bucket_name
        access_key = settings.s3_access_key
        secret_key = settings.s3_secret_key
        if not endpoint_url or not bucket_name or not access_key or not secret_key:
            raise StorageConfigurationError(
                "S3_ENDPOINT_URL, S3_BUCKET_NAME, S3_ACCESS_KEY, and S3_SECRET_KEY must be configured."
            )
        return endpoint_url, bucket_name, access_key, secret_key

    def _build_client(self):
        endpoint_url, _, access_key, secret_key = self._require_config()
        session = boto3.session.Session()
        return session.client(
            "s3",
            endpoint_url=endpoint_url,
            aws_access_key_id=access_key,
            aws_secret_access_key=secret_key,
            config=BotoConfig(signature_version="s3v4"),
        )

    def _build_public_url(self, destination_key: str) -> str:
        encoded_key = "/".join(quote(part, safe="") for part in _normalized_key(destination_key).split("/"))
        if settings.s3_public_base_url:
            return f"{settings.s3_public_base_url.rstrip('/')}/{encoded_key}"
        endpoint_url, bucket_name, _, _ = self._require_config()
        return f"{endpoint_url.rstrip('/')}/{bucket_name}/{encoded_key}"

    def _upload_with_wrangler(
        self,
        *,
        file_bytes: bytes,
        bucket_name: str,
        normalized_key: str,
        content_type: str,
    ) -> None:
        wrangler_path = shutil.which("wrangler")
        if not wrangler_path:
            raise StorageConfigurationError(
                "wrangler is not installed; cannot bootstrap uploads without S3 credentials."
            )

        with tempfile.NamedTemporaryFile(delete=False) as temp_file:
            temp_file.write(file_bytes)
            temp_path = Path(temp_file.name)

        try:
            command = [
                wrangler_path,
                "r2",
                "object",
                "put",
                f"{bucket_name}/{normalized_key}",
                "--remote",
                "--file",
                str(temp_path),
                "--content-type",
                content_type,
                "--cache-control",
                "public, max-age=31536000, immutable",
            ]
            result = subprocess.run(
                command,
                cwd=APP_ROOT,
                capture_output=True,
                text=True,
                check=False,
            )
            if result.returncode != 0:
                raise RuntimeError(result.stderr.strip() or result.stdout.strip() or "wrangler upload failed")
            logger.info("wrangler_r2_upload_succeeded", bucket_name=bucket_name, key=normalized_key)
        finally:
            temp_path.unlink(missing_ok=True)

    async def upload_image_bytes(
        self,
        file_bytes: bytes,
        destination_key: str,
        content_type: str,
    ) -> str:
        if not file_bytes:
            raise ValueError("file_bytes must not be empty")

        bucket_name = settings.s3_bucket_name.strip()
        if not bucket_name:
            raise StorageConfigurationError("S3_BUCKET_NAME must be configured.")
        normalized_key = _normalized_key(destination_key)

        if self._has_s3_credentials():
            def _upload() -> None:
                client = self._build_client()
                client.put_object(
                    Bucket=bucket_name,
                    Key=normalized_key,
                    Body=file_bytes,
                    ContentType=content_type,
                    CacheControl="public, max-age=31536000, immutable",
                )

            await asyncio.to_thread(_upload)
        else:
            await asyncio.to_thread(
                self._upload_with_wrangler,
                file_bytes=file_bytes,
                bucket_name=bucket_name,
                normalized_key=normalized_key,
                content_type=content_type,
            )
        return self._build_public_url(normalized_key)


storage_service = SovereignStorageService()


async def upload_image_bytes(file_bytes: bytes, destination_key: str, content_type: str) -> str:
    """Upload an image to sovereign storage and return its public URL."""

    return await storage_service.upload_image_bytes(file_bytes, destination_key, content_type)
