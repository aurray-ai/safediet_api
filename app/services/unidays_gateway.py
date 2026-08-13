from __future__ import annotations

import hashlib
import hmac
import json
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any

import httpx

from app.core.config import Settings


@dataclass(frozen=True, slots=True)
class UnidaysVerificationSession:
    reference_id: str
    verification_url: str
    method: str


@dataclass(frozen=True, slots=True)
class UnidaysVerificationOutcome:
    reference_id: str
    outcome: str  # "approved" | "declined" | "pending"
    method: str | None
    expires_at: datetime | None


class UnidaysGateway:
    """
    Thin adapter around UNiDAYS's partner verification API.

    NOTE: the exact endpoint paths, request/response field names, and webhook payload
    shape below follow the common pattern used by verification-as-a-service providers
    (UNiDAYS, SheerID) but have not been checked against SafeDiet's actual UNiDAYS
    partner docs. Everything that touches the wire format lives in this one file —
    once the real docs are available, only `start_verification`, `_extract_reference_id`,
    and `parse_webhook_event` should need adjusting. `StudentVerificationService`
    (the caller) only depends on the typed dataclasses above, not on any UNiDAYS-specific
    field names, so callers are shielded from that change.
    """

    def __init__(self, *, settings: Settings) -> None:
        self._settings = settings

    def start_verification(
        self,
        *,
        user_id: str,
        email: str,
        first_name: str,
        last_name: str,
        return_url: str,
    ) -> UnidaysVerificationSession:
        api_key = self._require_api_key()
        response = httpx.post(
            f"{self._settings.unidays_api_base_url.rstrip('/')}/v1/verifications",
            json={
                "external_reference": user_id,
                "email": email,
                "first_name": first_name,
                "last_name": last_name,
                "return_url": return_url,
            },
            headers={
                "Authorization": f"Bearer {api_key}",
                "Content-Type": "application/json",
            },
            timeout=self._settings.unidays_request_timeout_seconds,
        )
        response.raise_for_status()
        data = response.json()

        reference_id = str(data.get("id") or data.get("reference_id") or "")
        verification_url = str(data.get("verification_url") or data.get("url") or "")
        if not reference_id or not verification_url:
            raise RuntimeError("UNiDAYS did not return a verification session.")

        return UnidaysVerificationSession(
            reference_id=reference_id,
            verification_url=verification_url,
            method=str(data.get("method") or "unknown"),
        )

    def verify_webhook_signature(self, *, raw_body: bytes, signature_header: str | None) -> None:
        secret = self._require_webhook_secret()
        if signature_header is None or not signature_header.strip():
            raise ValueError("Missing UNiDAYS webhook signature header.")

        expected_signature = hmac.new(
            secret.encode("utf-8"),
            raw_body,
            hashlib.sha256,
        ).hexdigest()
        if not hmac.compare_digest(expected_signature, signature_header.strip()):
            raise ValueError("Invalid UNiDAYS webhook signature.")

    def parse_webhook_event(self, *, raw_body: bytes) -> UnidaysVerificationOutcome:
        payload = json.loads(raw_body.decode("utf-8"))
        reference_id = str(payload.get("id") or payload.get("reference_id") or "")
        if not reference_id:
            raise ValueError("UNiDAYS webhook payload is missing a reference id.")

        raw_outcome = str(payload.get("status") or payload.get("outcome") or "pending").lower()
        if raw_outcome in {"approved", "verified", "success"}:
            outcome = "approved"
        elif raw_outcome in {"declined", "rejected", "failed"}:
            outcome = "declined"
        else:
            outcome = "pending"

        expires_at: datetime | None = None
        raw_expiry = payload.get("expires_at") or payload.get("expiry")
        if raw_expiry:
            expires_at = self._parse_timestamp(raw_expiry)

        return UnidaysVerificationOutcome(
            reference_id=reference_id,
            outcome=outcome,
            method=str(payload.get("method") or "") or None,
            expires_at=expires_at,
        )

    def _require_api_key(self) -> str:
        if self._settings.unidays_api_key is None:
            raise RuntimeError("UNiDAYS API key is not configured.")
        return self._settings.unidays_api_key.get_secret_value()

    def _require_webhook_secret(self) -> str:
        if self._settings.unidays_webhook_secret is None:
            raise RuntimeError("UNiDAYS webhook secret is not configured.")
        return self._settings.unidays_webhook_secret.get_secret_value()

    @staticmethod
    def _parse_timestamp(value: Any) -> datetime | None:
        if isinstance(value, (int, float)):
            try:
                return datetime.fromtimestamp(float(value), tz=timezone.utc)
            except (TypeError, ValueError, OSError):
                return None
        if isinstance(value, str):
            try:
                return datetime.fromisoformat(value.replace("Z", "+00:00"))
            except ValueError:
                return None
        return None
