from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum


class StudentVerificationStatus(StrEnum):
    NONE = "none"
    PENDING = "pending"
    VERIFIED = "verified"
    REJECTED = "rejected"
    EXPIRED = "expired"


class StudentClaimSource(StrEnum):
    REGISTRATION = "registration"
    SETTINGS = "settings"


@dataclass(frozen=True, slots=True)
class StudentVerification:
    id: str
    user_id: str
    claims_student: bool
    status: StudentVerificationStatus
    unidays_reference_id: str | None
    verification_method: str | None
    started_at: datetime | None
    verified_at: datetime | None
    expires_at: datetime | None
    needs_reconciliation: bool
    source: StudentClaimSource
    created_at: datetime
    updated_at: datetime
