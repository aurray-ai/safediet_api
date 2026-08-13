from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, ConfigDict

from app.models.billing import SubscriptionPlanCode
from app.models.student_verification import StudentClaimSource, StudentVerificationStatus
from app.services.student_verification_service import PlanEligibility


class StudentClaimRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    claims_student: bool
    source: StudentClaimSource = StudentClaimSource.SETTINGS


class StudentVerificationStatusResponse(BaseModel):
    claims_student: bool
    status: StudentVerificationStatus
    verification_method: str | None = None
    started_at: datetime | None = None
    verified_at: datetime | None = None
    expires_at: datetime | None = None
    needs_reconciliation: bool = False


class StudentVerificationStartResponse(StudentVerificationStatusResponse):
    # Populated whenever this call actually (re)started a UNiDAYS session — a one-time
    # hosted-flow link, not something worth persisting or returning from /status. None
    # when a /claim call didn't trigger a fresh verification (e.g. claims_student=false).
    verification_url: str | None = None


class EligiblePlanResponse(BaseModel):
    eligibility: PlanEligibility
    plan_code: SubscriptionPlanCode | None = None
    price_minor: int | None = None
