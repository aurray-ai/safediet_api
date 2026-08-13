from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from enum import StrEnum

from app.core.config import Settings
from app.models.billing import PLAN_PRICE_MINOR, SubscriptionPlanCode
from app.models.student_verification import (
    StudentClaimSource,
    StudentVerification,
    StudentVerificationStatus,
)
from app.models.user import User
from app.repositories.student_verification_repository import StudentVerificationRepository
from app.repositories.user_repository import UserRepository
from app.services.email_service import EmailService
from app.services.unidays_gateway import UnidaysGateway

logger = logging.getLogger(__name__)


class StudentVerificationNotClaimedError(Exception):
    """Raised when verification is started but the user hasn't claimed student status."""


class StudentVerificationUnknownReferenceError(Exception):
    """Raised when a UNiDAYS webhook references a verification we don't recognize."""


class PlanEligibility(StrEnum):
    STUDENT = "student"
    STANDARD = "standard"
    AWAITING_VERIFICATION = "awaiting_verification"


@dataclass(frozen=True, slots=True)
class EligiblePlanResult:
    eligibility: PlanEligibility
    plan_code: SubscriptionPlanCode | None
    price_minor: int | None


@dataclass(frozen=True, slots=True)
class StartVerificationResult:
    record: StudentVerification
    verification_url: str


class StudentVerificationService:
    def __init__(
        self,
        *,
        repository: StudentVerificationRepository,
        unidays_gateway: UnidaysGateway,
        email_service: EmailService,
        user_repository: UserRepository,
        settings: Settings,
    ) -> None:
        self._repository = repository
        self._unidays_gateway = unidays_gateway
        self._email_service = email_service
        self._user_repository = user_repository
        self._settings = settings

    def get_status(self, *, user: User) -> StudentVerification:
        return self._existing_or_default(user_id=user.id)

    def resolve_eligible_plan(self, *, user: User) -> EligiblePlanResult:
        record = self._repository.get_by_user_id(user_id=user.id)

        if record is None or not record.claims_student:
            return self._standard_result()

        if record.status == StudentVerificationStatus.VERIFIED:
            if record.expires_at is not None and record.expires_at <= datetime.now(timezone.utc):
                return self._standard_result()
            return EligiblePlanResult(
                eligibility=PlanEligibility.STUDENT,
                plan_code=SubscriptionPlanCode.PREMIUM_MONTHLY_STUDENT,
                price_minor=PLAN_PRICE_MINOR[SubscriptionPlanCode.PREMIUM_MONTHLY_STUDENT],
            )

        if record.status in (StudentVerificationStatus.NONE, StudentVerificationStatus.PENDING):
            return EligiblePlanResult(
                eligibility=PlanEligibility.AWAITING_VERIFICATION,
                plan_code=None,
                price_minor=None,
            )

        # REJECTED or EXPIRED both fall back to standard pricing rather than blocking checkout.
        return self._standard_result()

    def submit_claim(
        self,
        *,
        user: User,
        claims_student: bool,
        source: StudentClaimSource,
    ) -> StartVerificationResult:
        existing = self._repository.get_by_user_id(user_id=user.id)

        if existing is not None and existing.claims_student == claims_student:
            # No real change — nothing to reconcile, leave status/verification untouched.
            return StartVerificationResult(record=existing, verification_url=None)

        # A change on a brand-new record (registration) has nothing to reconcile against.
        # A change on an existing record (Settings, mid-subscription) does.
        needs_reconciliation = existing is not None

        record = self._repository.upsert(
            user_id=user.id,
            claims_student=claims_student,
            status=StudentVerificationStatus.NONE,
            unidays_reference_id=None,
            verification_method=None,
            started_at=None,
            verified_at=None,
            expires_at=None,
            needs_reconciliation=needs_reconciliation,
            source=source,
        )

        if claims_student:
            return self.start_verification(user=user)

        return StartVerificationResult(record=record, verification_url=None)

    def start_verification(self, *, user: User) -> StartVerificationResult:
        record = self._repository.get_by_user_id(user_id=user.id)
        if record is None or not record.claims_student:
            raise StudentVerificationNotClaimedError(
                "User has not claimed student status; nothing to verify."
            )

        name_parts = user.name.strip().split(" ", 1)
        first_name = name_parts[0] if name_parts else user.name
        last_name = name_parts[1] if len(name_parts) > 1 else ""

        session = self._unidays_gateway.start_verification(
            user_id=user.id,
            email=user.email,
            first_name=first_name,
            last_name=last_name,
            return_url=f"{self._settings.web_app_base_url.rstrip('/')}/account/student-verification/return",
        )

        updated = self._repository.upsert(
            user_id=user.id,
            claims_student=True,
            status=StudentVerificationStatus.PENDING,
            unidays_reference_id=session.reference_id,
            verification_method=session.method,
            started_at=datetime.now(timezone.utc),
            verified_at=None,
            expires_at=None,
            needs_reconciliation=record.needs_reconciliation,
            source=record.source,
        )

        return StartVerificationResult(record=updated, verification_url=session.verification_url)

    def handle_unidays_webhook(self, *, raw_body: bytes, signature_header: str | None) -> StudentVerification:
        self._unidays_gateway.verify_webhook_signature(
            raw_body=raw_body,
            signature_header=signature_header,
        )
        outcome = self._unidays_gateway.parse_webhook_event(raw_body=raw_body)

        record = self._repository.find_by_unidays_reference_id(
            unidays_reference_id=outcome.reference_id,
        )
        if record is None:
            raise StudentVerificationUnknownReferenceError(
                f"No verification found for UNiDAYS reference {outcome.reference_id!r}."
            )

        if outcome.outcome == "approved":
            new_status = StudentVerificationStatus.VERIFIED
            verified_at = datetime.now(timezone.utc)
            expires_at = outcome.expires_at or (
                verified_at + timedelta(days=self._settings.student_verification_default_validity_days)
            )
        elif outcome.outcome == "declined":
            new_status = StudentVerificationStatus.REJECTED
            verified_at = None
            expires_at = None
        else:
            # Still pending (e.g. an async document-review step continuing) — nothing to update yet.
            return record

        updated = self._repository.upsert(
            user_id=record.user_id,
            claims_student=record.claims_student,
            status=new_status,
            unidays_reference_id=record.unidays_reference_id,
            verification_method=outcome.method or record.verification_method,
            started_at=record.started_at,
            verified_at=verified_at,
            expires_at=expires_at,
            needs_reconciliation=record.needs_reconciliation,
            source=record.source,
        )

        notify_user = self._user_repository.find_by_id(record.user_id)
        if notify_user is not None:
            self._email_service.send_student_verification_result_email(
                user=notify_user,
                approved=(new_status == StudentVerificationStatus.VERIFIED),
            )
        else:
            logger.warning(
                "Skipping student verification result email — user %s not found.",
                record.user_id,
            )
        return updated

    def acknowledge_reconciliation(self, *, user: User) -> StudentVerification:
        record = self._repository.get_by_user_id(user_id=user.id)
        if record is None:
            raise StudentVerificationNotClaimedError("No student verification record for this user.")

        return self._repository.upsert(
            user_id=record.user_id,
            claims_student=record.claims_student,
            status=record.status,
            unidays_reference_id=record.unidays_reference_id,
            verification_method=record.verification_method,
            started_at=record.started_at,
            verified_at=record.verified_at,
            expires_at=record.expires_at,
            needs_reconciliation=False,
            source=record.source,
        )

    def _existing_or_default(self, *, user_id: str) -> StudentVerification:
        existing = self._repository.get_by_user_id(user_id=user_id)
        if existing is not None:
            return existing

        now = datetime.now(timezone.utc)
        return StudentVerification(
            id="",
            user_id=user_id,
            claims_student=False,
            status=StudentVerificationStatus.NONE,
            unidays_reference_id=None,
            verification_method=None,
            started_at=None,
            verified_at=None,
            expires_at=None,
            needs_reconciliation=False,
            source=StudentClaimSource.REGISTRATION,
            created_at=now,
            updated_at=now,
        )

    @staticmethod
    def _standard_result() -> EligiblePlanResult:
        return EligiblePlanResult(
            eligibility=PlanEligibility.STANDARD,
            plan_code=SubscriptionPlanCode.PREMIUM_MONTHLY_STANDARD,
            price_minor=PLAN_PRICE_MINOR[SubscriptionPlanCode.PREMIUM_MONTHLY_STANDARD],
        )
