"""
Scans for verified student accounts whose verification is expiring soon, sends a
reverify-now nudge email, and once actually expired, flips the record to `expired`
(which drops eligibility back to standard pricing) and flags it for reconciliation
so the paywall/settings gate picks it up on both web and iOS.

Intended to run on a daily schedule via an external cron trigger — there is no
in-process scheduler in this codebase, so this script is the unit of work a cron
job (or equivalent) should invoke, matching the other one-off scripts in this
directory.
"""

from datetime import datetime, timedelta, timezone

from app.core.config import get_settings
from app.db.mongodb import mongo_manager
from app.models.student_verification import StudentVerificationStatus
from app.repositories.student_verification_repository import StudentVerificationRepository
from app.repositories.user_repository import UserRepository
from app.services.email_service import EmailService, build_email_sender


def main() -> None:
    settings = get_settings()
    mongo_manager.connect()
    try:
        verification_repository = StudentVerificationRepository(
            mongo_manager.student_verifications_collection()
        )
        user_repository = UserRepository(mongo_manager.users_collection())
        email_service = EmailService(
            sender=build_email_sender(settings),
            web_app_base_url=settings.web_app_base_url,
            mobile_app_link_base_url=settings.mobile_app_link_base_url,
        )

        now = datetime.now(timezone.utc)
        nudge_cutoff = now + timedelta(days=settings.student_verification_expiry_nudge_days)

        nudged = 0
        expired = 0
        for record in verification_repository.list_expiring_before(cutoff=nudge_cutoff):
            user = user_repository.find_by_id(record.user_id)
            if user is None:
                continue

            if record.expires_at is not None and record.expires_at <= now:
                verification_repository.upsert(
                    user_id=record.user_id,
                    claims_student=record.claims_student,
                    status=StudentVerificationStatus.EXPIRED,
                    unidays_reference_id=record.unidays_reference_id,
                    verification_method=record.verification_method,
                    started_at=record.started_at,
                    verified_at=record.verified_at,
                    expires_at=record.expires_at,
                    needs_reconciliation=True,
                    source=record.source,
                )
                expired += 1
                continue

            email_service.send_student_verification_expiring_soon_email(
                user=user,
                expires_at=record.expires_at,
            )
            nudged += 1

        print(f"Sent {nudged} expiry nudge emails; expired {expired} verifications.")
    finally:
        mongo_manager.close()


if __name__ == "__main__":
    main()
