from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime, timedelta, timezone

from app.core.config import get_settings
from app.core.security import (
    generate_invitation_token,
    hash_invitation_token,
)
from app.models.household import (
    Household,
    HouseholdBudgetPeriod,
    HouseholdMember,
    HouseholdMemberRole,
    HouseholdMemberStatus,
    HouseholdSplitRuleType,
)
from app.models.invitation import Invitation, InvitationStatus, InvitationType
from app.models.user import User
from app.repositories.invitation_repository import InvitationRepository
from app.repositories.household_member_repository import HouseholdMemberRepository
from app.repositories.household_repository import HouseholdRepository
from app.repositories.user_repository import UserRepository
from app.schemas.household import (
    HouseholdBudgetProfileResponse,
    HouseholdDetailResponse,
    HouseholdInvitationDetailResponse,
    HouseholdInvitationResponse,
    HouseholdMemberResponse,
    HouseholdMembershipSummaryResponse,
    HouseholdResponse,
    HouseholdSplitRuleResponse,
)
from app.services.household_communication_service import HouseholdCommunicationService


class HouseholdError(Exception):
    pass


class HouseholdConflictError(HouseholdError):
    pass


class HouseholdPermissionError(HouseholdError):
    pass


class HouseholdNotFoundError(HouseholdError):
    pass


class HouseholdValidationError(HouseholdError):
    pass


class HouseholdCommunicationError(HouseholdError):
    pass


@dataclass(frozen=True, slots=True)
class HouseholdPeriodWindow:
    period_start: date
    period_end: date


class HouseholdService:
    def __init__(
        self,
        *,
        household_repository: HouseholdRepository,
        household_member_repository: HouseholdMemberRepository,
        invitation_repository: InvitationRepository,
        user_repository: UserRepository,
        household_communication_service: HouseholdCommunicationService | None = None,
    ) -> None:
        self._household_repository = household_repository
        self._household_member_repository = household_member_repository
        self._invitation_repository = invitation_repository
        self._user_repository = user_repository
        self._household_communication_service = household_communication_service

    def create_household(
        self,
        *,
        current_user: User,
        name: str,
        currency: str,
        target_amount_minor: int,
        budget_period: HouseholdBudgetPeriod,
        split_rule_type: HouseholdSplitRuleType,
    ) -> HouseholdDetailResponse:
        household = self._household_repository.create(
            owner_user_id=current_user.id,
            name=name,
            currency=currency,
            budget_period=budget_period,
            target_amount_minor=target_amount_minor,
            split_rule_type=split_rule_type,
        )
        owner_member = self._household_member_repository.create(
            household_id=household.id,
            user_id=current_user.id,
            display_name=current_user.name,
            role=HouseholdMemberRole.OWNER,
            status=HouseholdMemberStatus.ACTIVE,
            share_weight=1,
        )
        self._notify(
            recipient_user_ids=[current_user.id],
            title="Shared budget created",
            message=f"{current_user.name} created {household.name} with a weekly target of {household.currency} {household.budget_profile.target_amount_minor / 100:.2f}.",
            household_id=household.id,
            focus="household_created",
            idempotency_key=f"household_created:{household.id}",
            email_subject="Your shared budget is ready",
            email_intro=(
                f"you created {household.name} and the shared budget is now ready to use."
            ),
        )
        return HouseholdDetailResponse(
            household=self._to_household_response(household, member_count=1),
            members=[self._to_member_response(owner_member)],
            invitations=[],
        )

    def get_household_for_user(
        self,
        *,
        current_user: User,
        household_id: str | None = None,
    ) -> tuple[Household, list[HouseholdMember]]:
        if household_id is not None:
            membership = self._household_member_repository.get_active_by_user_id_and_household_id(
                user_id=current_user.id,
                household_id=household_id,
            )
            if membership is None:
                raise HouseholdNotFoundError("You are not an active member of that household.")
        else:
            membership = self._household_member_repository.get_active_by_user_id(user_id=current_user.id)
            if membership is None:
                raise HouseholdNotFoundError("No active household found for the current user.")

        household = self._household_repository.get_by_id(household_id=membership.household_id)
        if household is None or household.status.value != "active":
            raise HouseholdNotFoundError("Active household not found.")
        members = self._household_member_repository.list_by_household_id(household_id=household.id)
        return household, members

    def list_households_for_user(
        self,
        *,
        current_user: User,
    ) -> list[HouseholdMembershipSummaryResponse]:
        memberships = self._household_member_repository.list_active_by_user_id(user_id=current_user.id)
        if not memberships:
            return []

        households = self._household_repository.list_by_ids(
            household_ids=[membership.household_id for membership in memberships]
        )
        households_by_id = {household.id: household for household in households}

        member_counts: dict[str, int] = {}
        for membership in memberships:
            if membership.household_id not in member_counts:
                member_counts[membership.household_id] = len(
                    self._household_member_repository.list_by_household_id(
                        household_id=membership.household_id
                    )
                )

        summaries: list[HouseholdMembershipSummaryResponse] = []
        for membership in memberships:
            household = households_by_id.get(membership.household_id)
            if household is None or household.status.value != "active":
                continue
            summaries.append(
                HouseholdMembershipSummaryResponse(
                    household_id=household.id,
                    name=household.name,
                    currency=household.currency,
                    role=membership.role,
                    member_count=member_counts.get(household.id, 1),
                )
            )
        return summaries

    def list_pending_invitations(
        self,
        *,
        current_user: User,
        household_id: str,
    ) -> list[HouseholdInvitationResponse]:
        _, membership = self._require_active_membership(
            current_user=current_user,
            household_id=household_id,
        )
        if membership.role != HouseholdMemberRole.OWNER:
            return []
        invitations = self._invitation_repository.list_by_type(
            invitation_type=InvitationType.HOUSEHOLD,
            context_filters={"household_id": household_id},
            statuses=[InvitationStatus.PENDING],
        )
        return [self._to_invitation_response(item) for item in invitations]

    def invite_member(
        self,
        *,
        current_user: User,
        household_id: str,
        contact: str,
        display_name: str | None,
        role: HouseholdMemberRole,
        share_weight: int,
    ) -> HouseholdInvitationResponse:
        household, actor_membership = self._require_active_membership(
            current_user=current_user,
            household_id=household_id,
        )
        self._require_owner(actor_membership=actor_membership)

        now = datetime.now(timezone.utc)
        invitee_email = self._normalize_invitee_email(contact)
        existing_user = self._user_repository.find_by_email(invitee_email)

        if self._invitation_repository.get_pending_by_type_and_email(
            invitation_type=InvitationType.HOUSEHOLD,
            invitee_email=invitee_email,
            context_filters={"household_id": household.id},
            now=now,
        ) is not None:
            raise HouseholdConflictError("A pending household invitation already exists for that email.")

        if existing_user is not None:
            linked_member = self._household_member_repository.get_by_household_and_user_id(
                household_id=household.id,
                user_id=existing_user.id,
            )
            if linked_member is not None:
                raise HouseholdConflictError("User is already linked to this household.")

        raw_token = generate_invitation_token()
        settings = get_settings()
        expires_at = now + timedelta(days=settings.household_invitation_token_ttl_days)
        invitation = self._invitation_repository.create(
            invitation_type=InvitationType.HOUSEHOLD,
            invited_by_user_id=current_user.id,
            invitee_email=invitee_email,
            invitee_user_id=existing_user.id if existing_user is not None else None,
            display_name=self._resolve_invitation_display_name(
                display_name=display_name,
                existing_user=existing_user,
                invitee_email=invitee_email,
            ),
            token_hash=hash_invitation_token(raw_token),
            expires_at=expires_at,
            context={
                "household_id": household.id,
                "role": role.value,
                "share_weight": int(share_weight),
            },
        )

        self._notify_invitation(
            household=household,
            inviter=current_user,
            invitation=invitation,
            raw_token=raw_token,
        )
        return self._to_invitation_response(invitation)

    def get_invitation_detail(self, *, token: str) -> HouseholdInvitationDetailResponse:
        invitation, household = self._require_pending_invitation_by_token(token)
        inviter = self._user_repository.find_by_id(invitation.invited_by_user_id)
        inviter_name = inviter.name if inviter is not None and inviter.name.strip() else "A Safediet member"
        return HouseholdInvitationDetailResponse(
            invitation=self._to_invitation_response(invitation),
            household_name=household.name,
            inviter_name=inviter_name,
            requires_registration=invitation.invitee_user_id is None,
            is_existing_user=invitation.invitee_user_id is not None,
        )

    def accept_invitation(
        self,
        *,
        current_user: User,
        token: str,
    ) -> HouseholdDetailResponse:
        invitation, household = self._require_pending_invitation_by_token(token)
        if current_user.email.strip().lower() != invitation.invitee_email.strip().lower():
            raise HouseholdPermissionError(
                "This invitation belongs to a different email address. Sign in with the invited account."
            )
        if invitation.invitee_user_id is not None and invitation.invitee_user_id != current_user.id:
            raise HouseholdPermissionError(
                "This invitation belongs to a different Safediet account."
            )

        existing_household_member = self._household_member_repository.get_by_household_and_user_id(
            household_id=household.id,
            user_id=current_user.id,
        )
        if existing_household_member is not None:
            raise HouseholdConflictError("User is already linked to this household.")

        member = self._household_member_repository.create(
            household_id=household.id,
            user_id=current_user.id,
            display_name=(invitation.display_name or current_user.name).strip() or current_user.name,
            role=HouseholdMemberRole(invitation.context["role"]),
            status=HouseholdMemberStatus.ACTIVE,
            share_weight=int(invitation.context["share_weight"]),
        )
        self._invitation_repository.mark_accepted(
            invitation_id=invitation.id,
            accepted_by_user_id=current_user.id,
        )

        recipients = [
            item.user_id
            for item in self._household_member_repository.list_by_household_id(
                household_id=household.id
            )
        ]
        self._notify(
            recipient_user_ids=recipients,
            title="Household invitation accepted",
            message=f"{member.display_name} joined {household.name}.",
            household_id=household.id,
            focus="invitation_accepted",
            idempotency_key=f"household_invitation_accepted:{household.id}:{invitation.id}",
            email_subject=f"{member.display_name} joined {household.name}",
            email_intro=f"{member.display_name} accepted the household invitation and joined the shared budget.",
            details={"invitation_id": invitation.id, "member_id": member.id, "user_id": member.user_id},
        )

        members = self._household_member_repository.list_by_household_id(household_id=household.id)
        pending = self._invitation_repository.list_by_type(
            invitation_type=InvitationType.HOUSEHOLD,
            context_filters={"household_id": household.id},
            statuses=[InvitationStatus.PENDING],
        )
        return HouseholdDetailResponse(
            household=self._to_household_response(household, member_count=len(members)),
            members=[self._to_member_response(item) for item in members],
            invitations=[self._to_invitation_response(item) for item in pending],
        )

    def add_member(
        self,
        *,
        current_user: User,
        household_id: str,
        user_id: str | None,
        contact: str | None,
        display_name: str | None,
        role: HouseholdMemberRole,
        share_weight: int,
    ) -> HouseholdMemberResponse:
        household, actor_membership = self._require_active_membership(
            current_user=current_user,
            household_id=household_id,
        )
        self._require_owner(actor_membership=actor_membership)

        resolved_user_id = self._resolve_member_user_id(user_id=user_id, contact=contact)
        existing_user = self._user_repository.find_by_id(resolved_user_id)
        if existing_user is None:
            raise HouseholdNotFoundError("User not found.")

        existing_household_member = self._household_member_repository.get_by_household_and_user_id(
            household_id=household.id,
            user_id=resolved_user_id,
        )
        if existing_household_member is not None:
            raise HouseholdConflictError("User is already linked to this household.")

        member = self._household_member_repository.create(
            household_id=household.id,
            user_id=resolved_user_id,
            display_name=(display_name or existing_user.name).strip(),
            role=role,
            status=HouseholdMemberStatus.ACTIVE,
            share_weight=share_weight,
        )
        recipients = [item.user_id for item in self._household_member_repository.list_by_household_id(household_id=household.id)]
        self._notify(
            recipient_user_ids=recipients,
            title="Household member added",
            message=f"{member.display_name} joined {household.name}.",
            household_id=household.id,
            focus="member_added",
            idempotency_key=f"household_member_added:{household.id}:{member.id}",
            email_subject=f"{member.display_name} was added to {household.name}",
            email_intro=f"{member.display_name} has been added to the shared household budget.",
            details={"member_id": member.id, "user_id": member.user_id},
        )
        return self._to_member_response(member)

    def update_household(
        self,
        *,
        current_user: User,
        household_id: str,
        name: str | None,
        target_amount_minor: int | None,
        budget_period: HouseholdBudgetPeriod | None,
        split_rule_type: HouseholdSplitRuleType | None,
    ) -> HouseholdResponse:
        _, actor_membership = self._require_active_membership(
            current_user=current_user,
            household_id=household_id,
        )
        self._require_owner(actor_membership=actor_membership)
        updated = self._household_repository.update(
            household_id=household_id,
            name=name,
            target_amount_minor=target_amount_minor,
            budget_period=budget_period,
            split_rule_type=split_rule_type,
        )
        if updated is None:
            raise HouseholdNotFoundError("Household not found.")
        member_count = len(
            self._household_member_repository.list_by_household_id(household_id=household_id)
        )
        recipients = [item.user_id for item in self._household_member_repository.list_by_household_id(household_id=household_id)]
        self._notify(
            recipient_user_ids=recipients,
            title="Shared budget updated",
            message=f"{updated.name} was updated. Budget and split settings may have changed.",
            household_id=updated.id,
            focus="household_updated",
            idempotency_key=f"household_updated:{updated.id}:{int(updated.updated_at.timestamp())}",
            email_subject=f"{updated.name} settings were updated",
            email_intro="the household budget settings were updated. Open Shared Budget to review the latest values.",
        )
        return self._to_household_response(updated, member_count=member_count)

    def update_member_weight(
        self,
        *,
        current_user: User,
        household_id: str,
        member_id: str,
        share_weight: int,
    ) -> HouseholdMemberResponse:
        _, actor_membership = self._require_active_membership(
            current_user=current_user,
            household_id=household_id,
        )
        self._require_owner(actor_membership=actor_membership)
        member = self._household_member_repository.update_share_weight(
            member_id=member_id,
            share_weight=share_weight,
        )
        if member is None or member.household_id != household_id:
            raise HouseholdNotFoundError("Household member not found.")
        recipients = [item.user_id for item in self._household_member_repository.list_by_household_id(household_id=household_id)]
        self._notify(
            recipient_user_ids=recipients,
            title="Household split weight updated",
            message=f"{member.display_name}'s split weight was updated to {member.share_weight}.",
            household_id=household_id,
            focus="member_weight_updated",
            idempotency_key=f"household_member_weight:{household_id}:{member.id}:{member.share_weight}",
            email_subject="A household split weight changed",
            email_intro=f"{member.display_name}'s household split weight was updated.",
            details={"member_id": member.id, "share_weight": member.share_weight},
        )
        return self._to_member_response(member)

    def deactivate_member(
        self,
        *,
        current_user: User,
        household_id: str,
        member_id: str,
    ) -> HouseholdMemberResponse:
        _, actor_membership = self._require_active_membership(
            current_user=current_user,
            household_id=household_id,
        )
        self._require_owner(actor_membership=actor_membership)
        member = self._household_member_repository.get_by_id(member_id=member_id)
        if member is None or member.household_id != household_id:
            raise HouseholdNotFoundError("Household member not found.")
        if member.role == HouseholdMemberRole.OWNER:
            raise HouseholdValidationError("The household owner cannot be deactivated.")
        updated = self._household_member_repository.deactivate(member_id=member_id)
        if updated is None:
            raise HouseholdNotFoundError("Household member not found.")
        recipients = [item.user_id for item in self._household_member_repository.list_by_household_id(household_id=household_id, include_inactive=True)]
        self._notify(
            recipient_user_ids=recipients,
            title="Household member removed",
            message=f"{updated.display_name} is no longer active in this household.",
            household_id=household_id,
            focus="member_deactivated",
            idempotency_key=f"household_member_deactivated:{household_id}:{updated.id}",
            email_subject=f"{updated.display_name} was removed from the household",
            email_intro=f"{updated.display_name} is no longer active in the shared household budget.",
            details={"member_id": updated.id, "user_id": updated.user_id},
        )
        return self._to_member_response(updated)

    def archive_household(
        self,
        *,
        current_user: User,
        household_id: str,
    ) -> HouseholdResponse:
        _, actor_membership = self._require_active_membership(
            current_user=current_user,
            household_id=household_id,
        )
        self._require_owner(actor_membership=actor_membership)
        archived = self._household_repository.archive(household_id=household_id)
        if archived is None:
            raise HouseholdNotFoundError("Household not found.")
        member_count = len(
            self._household_member_repository.list_by_household_id(
                household_id=household_id,
                include_inactive=True,
            )
        )
        recipients = [
            item.user_id
            for item in self._household_member_repository.list_by_household_id(
                household_id=household_id,
                include_inactive=True,
            )
        ]
        self._notify(
            recipient_user_ids=recipients,
            title="Shared budget archived",
            message=f"{archived.name} was archived and is no longer active.",
            household_id=household_id,
            focus="household_archived",
            idempotency_key=f"household_archived:{household_id}",
            email_subject=f"{archived.name} was archived",
            email_intro=f"{archived.name} was archived and the shared budgeting flow is now closed for that household.",
        )
        return self._to_household_response(archived, member_count=member_count)

    def resolve_period_window(
        self,
        *,
        period_start: date | None,
        period_end: date | None,
    ) -> HouseholdPeriodWindow:
        if period_start is not None and period_end is not None:
            if period_end < period_start:
                raise HouseholdValidationError("period_end must be on or after period_start.")
            return HouseholdPeriodWindow(period_start=period_start, period_end=period_end)

        today = date.today()
        start = today - timedelta(days=today.weekday())
        end = start + timedelta(days=6)
        return HouseholdPeriodWindow(period_start=start, period_end=end)

    def resolve_week_window_for_date(self, *, anchor_date: date) -> HouseholdPeriodWindow:
        start = anchor_date - timedelta(days=anchor_date.weekday())
        end = start + timedelta(days=6)
        return HouseholdPeriodWindow(period_start=start, period_end=end)

    def to_household_response(self, household: Household, *, member_count: int) -> HouseholdResponse:
        return self._to_household_response(household, member_count=member_count)

    def to_member_response(self, member: HouseholdMember) -> HouseholdMemberResponse:
        return self._to_member_response(member)

    def to_invitation_response(self, invitation: Invitation) -> HouseholdInvitationResponse:
        return self._to_invitation_response(invitation)

    def _notify(
        self,
        *,
        recipient_user_ids: list[str],
        title: str,
        message: str,
        household_id: str,
        focus: str,
        idempotency_key: str,
        email_subject: str,
        email_intro: str,
        details: dict[str, object] | None = None,
    ) -> None:
        if self._household_communication_service is None:
            return
        self._household_communication_service.notify(
            recipient_user_ids=recipient_user_ids,
            title=title,
            message=message,
            household_id=household_id,
            focus=focus,
            idempotency_key=idempotency_key,
            email_subject=email_subject,
            email_intro=email_intro,
            details=details,
        )

    def _notify_invitation(
        self,
        *,
        household: Household,
        inviter: User,
        invitation: Invitation,
        raw_token: str,
    ) -> None:
        if self._household_communication_service is None:
            return
        action_url = self._build_invitation_accept_url(raw_token)
        if invitation.invitee_user_id is not None:
            subject = f"You've been invited to join {household.name}"
            intro = (
                f"{inviter.name} invited you to join {household.name} on Safediet. "
                "Accept the invitation to start sharing grocery budgets, contributions, and meal costs."
            )
        else:
            subject = f"Join Safediet to accept your invitation to {household.name}"
            intro = (
                f"{inviter.name} invited you to join {household.name} on Safediet. "
                "Create your account, then accept the invitation to start sharing grocery budgets, contributions, and meal costs."
            )
        try:
            self._household_communication_service.notify_invitation(
                household_id=household.id,
                invitee_email=invitation.invitee_email,
                invitee_name=invitation.display_name,
                existing_user_id=invitation.invitee_user_id,
                title="Household invitation",
                message=f"{inviter.name} invited you to join {household.name}.",
                focus="household_invitation",
                idempotency_key=f"household_invitation:{invitation.id}",
                email_subject=subject,
                email_intro=intro,
                action_url=action_url,
            )
        except Exception as exc:
            raise HouseholdCommunicationError(
                "The invitation was created, but the email could not be delivered. Check the email configuration and try again."
            ) from exc

    def _resolve_member_user_id(
        self,
        *,
        user_id: str | None,
        contact: str | None,
    ) -> str:
        normalized_user_id = str(user_id or "").strip()
        if normalized_user_id:
            return normalized_user_id

        normalized_contact = str(contact or "").strip().lower()
        if not normalized_contact:
            raise HouseholdValidationError("Provide a user_id or the member's account email.")

        if "@" not in normalized_contact:
            raise HouseholdValidationError(
                "Use the member's Safediet account email to add them to the household."
            )

        existing_user = self._user_repository.find_by_email(normalized_contact)
        if existing_user is None:
            raise HouseholdNotFoundError(
                "No registered Safediet user was found for that email address."
            )
        return existing_user.id

    def _normalize_invitee_email(self, contact: str) -> str:
        normalized = str(contact or "").strip().lower()
        if not normalized:
            raise HouseholdValidationError("Provide the member's email address.")
        if "@" not in normalized:
            raise HouseholdValidationError("Use the member's email address to send a household invitation.")
        return normalized

    def _resolve_invitation_display_name(
        self,
        *,
        display_name: str | None,
        existing_user: User | None,
        invitee_email: str,
    ) -> str:
        normalized = str(display_name or "").strip()
        if normalized:
            return normalized
        if existing_user is not None and existing_user.name.strip():
            return existing_user.name.strip()
        local_part = invitee_email.split("@", 1)[0].replace(".", " ").replace("_", " ").strip()
        return local_part.title() or "New member"

    def _build_invitation_accept_url(self, token: str) -> str:
        settings = get_settings()
        return f"{settings.web_app_base_url.rstrip('/')}/household-invite/{token}"

    def _require_pending_invitation_by_token(
        self,
        token: str,
    ) -> tuple[Invitation, Household]:
        now = datetime.now(timezone.utc)
        invitation = self._invitation_repository.find_active_by_token_hash(
            token_hash=hash_invitation_token(token),
            now=now,
        )
        if invitation is None or invitation.invitation_type != InvitationType.HOUSEHOLD:
            raise HouseholdNotFoundError("Invitation not found or expired.")
        household = self._household_repository.get_by_id(household_id=invitation.context["household_id"])
        if household is None or household.status.value != "active":
            raise HouseholdNotFoundError("The invited household is no longer active.")
        return invitation, household

    def _require_active_membership(
        self,
        *,
        current_user: User,
        household_id: str,
    ) -> tuple[Household, HouseholdMember]:
        membership = self._household_member_repository.get_by_household_and_user_id(
            household_id=household_id,
            user_id=current_user.id,
        )
        if membership is None or membership.status != HouseholdMemberStatus.ACTIVE:
            raise HouseholdPermissionError("You do not have access to this household.")

        household = self._household_repository.get_by_id(household_id=household_id)
        if household is None:
            raise HouseholdNotFoundError("Household not found.")
        return household, membership

    @staticmethod
    def _require_owner(*, actor_membership: HouseholdMember) -> None:
        if actor_membership.role != HouseholdMemberRole.OWNER:
            raise HouseholdPermissionError("Only the household owner can perform this action.")

    @staticmethod
    def _to_household_response(household: Household, *, member_count: int) -> HouseholdResponse:
        return HouseholdResponse(
            id=household.id,
            name=household.name,
            currency=household.currency,
            status=household.status,
            budget_profile=HouseholdBudgetProfileResponse(
                period=household.budget_profile.period,
                target_amount_minor=household.budget_profile.target_amount_minor,
            ),
            default_split_rule=HouseholdSplitRuleResponse(
                type=household.default_split_rule.type,
                weights=household.default_split_rule.weights,
            ),
            member_count=member_count,
            created_at=household.created_at,
            updated_at=household.updated_at,
        )

    @staticmethod
    def _to_member_response(member: HouseholdMember) -> HouseholdMemberResponse:
        return HouseholdMemberResponse(
            id=member.id,
            user_id=member.user_id,
            display_name=member.display_name,
            role=member.role,
            status=member.status,
            share_weight=member.share_weight,
            created_at=member.created_at,
            updated_at=member.updated_at,
        )

    @staticmethod
    def _to_invitation_response(invitation: Invitation) -> HouseholdInvitationResponse:
        return HouseholdInvitationResponse(
            id=invitation.id,
            household_id=invitation.context["household_id"],
            invited_by_user_id=invitation.invited_by_user_id,
            invitee_email=invitation.invitee_email,
            invitee_user_id=invitation.invitee_user_id,
            display_name=invitation.display_name,
            role=HouseholdMemberRole(invitation.context["role"]),
            status=invitation.status,
            share_weight=int(invitation.context["share_weight"]),
            expires_at=invitation.expires_at,
            accepted_at=invitation.accepted_at,
            accepted_by_user_id=invitation.accepted_by_user_id,
            created_at=invitation.created_at,
            updated_at=invitation.updated_at,
        )
