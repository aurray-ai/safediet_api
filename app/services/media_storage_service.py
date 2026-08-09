from __future__ import annotations

import hashlib
import logging
import mimetypes
import re
import time
from dataclasses import dataclass
from pathlib import Path
from uuid import uuid4

import httpx
from fastapi import UploadFile

from app.core.config import Settings

logger = logging.getLogger(__name__)

_SAFE_SEGMENT_RE = re.compile(r"[^a-zA-Z0-9/_-]+")
_IMAGE_MIME_PREFIX = "image/"


@dataclass(frozen=True, slots=True)
class StoredMediaAsset:
    url: str
    storage_backend: str
    content_type: str
    original_filename: str


def resolve_local_media_directory(settings: Settings) -> Path:
    configured = Path(settings.local_media_directory)
    if configured.is_absolute():
        return configured
    return Path(__file__).resolve().parents[2] / configured


class MediaStorageService:
    def __init__(self, settings: Settings) -> None:
        self._settings = settings
        self._local_directory = resolve_local_media_directory(settings)
        self._local_directory.mkdir(parents=True, exist_ok=True)

    async def upload_image(
        self,
        *,
        file: UploadFile,
        folder: str,
        public_base_url: str | None = None,
    ) -> StoredMediaAsset:
        content_type = (file.content_type or "").strip().lower()
        if not content_type.startswith(_IMAGE_MIME_PREFIX):
            raise ValueError("Only image uploads are supported.")

        payload = await file.read()
        if not payload:
            raise ValueError("Uploaded image was empty.")

        extension = self._resolve_extension(filename=file.filename, content_type=content_type)
        key = self._build_key(folder=folder, extension=extension)

        uploaded = self._upload_to_cloudinary(
            key=key,
            payload=payload,
            content_type=content_type,
            original_filename=file.filename or "upload",
        )
        if uploaded is not None:
            return uploaded

        if self._should_use_s3():
            uploaded = self._upload_to_s3(
                key=key,
                payload=payload,
                content_type=content_type,
                original_filename=file.filename or "upload",
            )
            if uploaded is not None:
                return uploaded

        return self._upload_to_local(
            key=key,
            payload=payload,
            content_type=content_type,
            original_filename=file.filename or "upload",
            public_base_url=self.resolve_public_base_url(request_base_url=public_base_url),
        )

    def resolve_public_base_url(self, *, request_base_url: str | None = None) -> str:
        if self._settings.api_public_base_url:
            return self._settings.api_public_base_url
        if request_base_url:
            normalized_request_base_url = request_base_url.strip().rstrip("/")
            if normalized_request_base_url:
                return normalized_request_base_url
        return f"http://127.0.0.1:{self._settings.app_port}"

    def _should_use_s3(self) -> bool:
        return bool(self._settings.aws_s3_bucket_name and self._settings.aws_s3_region)

    def _upload_to_cloudinary(
        self,
        *,
        key: str,
        payload: bytes,
        content_type: str,
        original_filename: str,
    ) -> StoredMediaAsset | None:
        cloud_name = (self._settings.cloudinary_cloud_name or "").strip()
        if not cloud_name:
            return None

        has_signed_credentials = bool(
            (self._settings.cloudinary_api_key or "").strip()
            and self._settings.cloudinary_api_secret is not None
            and self._settings.cloudinary_api_secret.get_secret_value().strip()
        )
        upload_preset = (self._settings.cloudinary_upload_preset or "").strip()
        if not has_signed_credentials and not upload_preset:
            logger.warning(
                "Cloudinary is partially configured but missing either signed credentials "
                "or an unsigned upload preset. Falling back to local media storage."
            )
            return None

        key_path = Path(key)
        folder = self._cloudinary_folder(key_path.parent.as_posix())
        form_data: dict[str, str] = {"folder": folder}
        if has_signed_credentials:
            timestamp = str(int(time.time()))
            api_key = str(self._settings.cloudinary_api_key).strip()
            api_secret = self._settings.cloudinary_api_secret.get_secret_value().strip()
            public_id = key_path.stem
            signature_fields = {
                "folder": folder,
                "public_id": public_id,
                "timestamp": timestamp,
            }
            form_data.update(
                {
                    "api_key": api_key,
                    "public_id": public_id,
                    "timestamp": timestamp,
                    "signature": self._sign_cloudinary_payload(signature_fields, api_secret),
                }
            )
        else:
            form_data["upload_preset"] = upload_preset

        upload_url = f"{self._settings.cloudinary_api_base_url}/{cloud_name}/image/upload"
        try:
            response = httpx.post(
                upload_url,
                data=form_data,
                files={"file": (original_filename, payload, content_type)},
                timeout=self._settings.cloudinary_timeout_seconds,
            )
            response.raise_for_status()
            response_payload = response.json()
        except Exception:
            logger.exception("Cloudinary image upload failed. Falling back to local media storage.")
            return None

        asset_url = str(response_payload.get("secure_url") or response_payload.get("url") or "").strip()
        if not asset_url:
            logger.warning(
                "Cloudinary upload succeeded without returning a public URL. Falling back to local media storage."
            )
            return None

        return StoredMediaAsset(
            url=asset_url,
            storage_backend="cloudinary",
            content_type=content_type,
            original_filename=original_filename,
        )

    def _upload_to_s3(
        self,
        *,
        key: str,
        payload: bytes,
        content_type: str,
        original_filename: str,
    ) -> StoredMediaAsset | None:
        try:
            import boto3
        except Exception:
            logger.warning("boto3 is unavailable. Falling back to local media storage.")
            return None

        try:
            client = boto3.client(
                "s3",
                region_name=self._settings.aws_s3_region,
                aws_access_key_id=self._settings.aws_s3_access_key_id,
                aws_secret_access_key=(
                    self._settings.aws_s3_secret_access_key.get_secret_value()
                    if self._settings.aws_s3_secret_access_key
                    else None
                ),
                endpoint_url=self._settings.aws_s3_endpoint_url,
            )
            client.put_object(
                Bucket=str(self._settings.aws_s3_bucket_name),
                Key=key,
                Body=payload,
                ContentType=content_type,
            )
        except Exception:
            logger.exception("S3 image upload failed. Falling back to local media storage.")
            return None

        return StoredMediaAsset(
            url=self._build_s3_url(key),
            storage_backend="s3",
            content_type=content_type,
            original_filename=original_filename,
        )

    def _upload_to_local(
        self,
        *,
        key: str,
        payload: bytes,
        content_type: str,
        original_filename: str,
        public_base_url: str,
    ) -> StoredMediaAsset:
        destination = self._local_directory / key
        destination.parent.mkdir(parents=True, exist_ok=True)
        destination.write_bytes(payload)
        url = f"{public_base_url.rstrip('/')}{self._settings.local_media_url_prefix}/{key}"
        return StoredMediaAsset(
            url=url,
            storage_backend="local",
            content_type=content_type,
            original_filename=original_filename,
        )

    def _build_s3_url(self, key: str) -> str:
        if self._settings.aws_s3_public_base_url:
            return f"{self._settings.aws_s3_public_base_url.rstrip('/')}/{key}"
        if self._settings.aws_s3_endpoint_url:
            return (
                f"{self._settings.aws_s3_endpoint_url.rstrip('/')}/"
                f"{self._settings.aws_s3_bucket_name}/{key}"
            )
        return (
            f"https://{self._settings.aws_s3_bucket_name}.s3."
            f"{self._settings.aws_s3_region}.amazonaws.com/{key}"
        )

    @staticmethod
    def _resolve_extension(*, filename: str | None, content_type: str) -> str:
        if filename:
            suffix = Path(filename).suffix.strip().lower()
            if suffix:
                return suffix
        guessed = mimetypes.guess_extension(content_type) or ".jpg"
        return guessed if guessed.startswith(".") else f".{guessed}"

    @staticmethod
    def _build_key(*, folder: str, extension: str) -> str:
        normalized_folder = MediaStorageService._normalize_folder(folder)
        normalized_folder = normalized_folder or "meals"
        return f"{normalized_folder}/{uuid4().hex}{extension}"

    @staticmethod
    def _normalize_folder(folder: str) -> str:
        return _SAFE_SEGMENT_RE.sub("", folder.strip().replace("\\", "/")).strip("/")

    def _cloudinary_folder(self, folder: str) -> str:
        normalized_folder = self._normalize_folder(folder)
        root = self._normalize_folder(self._settings.cloudinary_upload_folder_root or "")
        if root and normalized_folder:
            return f"{root}/{normalized_folder}"
        return root or normalized_folder or "safedaet"

    @staticmethod
    def _sign_cloudinary_payload(fields: dict[str, str], api_secret: str) -> str:
        serialized = "&".join(
            f"{key}={value}"
            for key, value in sorted(fields.items())
            if value not in ("", None)
        )
        digest = hashlib.sha1(f"{serialized}{api_secret}".encode("utf-8"))
        return digest.hexdigest()
