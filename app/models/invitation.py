from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum
from typing import Any


class InvitationType(StrEnum):
    HOUSEHOLD = "household"
    STAFF = "staff"


class InvitationStatus(StrEnum):
    PENDING = "pending"
    ACCEPTED = "accepted"
    DECLINED = "declined"
    EXPIRED = "expired"
    CANCELLED = "cancelled"


@dataclass(frozen=True, slots=True)
class Invitation:
    id: str
    invitation_type: InvitationType
    invited_by_user_id: str
    invitee_email: str
    invitee_user_id: str | None
    display_name: str
    status: InvitationStatus
    token_hash: str
    expires_at: datetime
    accepted_at: datetime | None
    accepted_by_user_id: str | None
    context: dict[str, Any]
    created_at: datetime
    updated_at: datetime
