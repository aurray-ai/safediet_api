from datetime import datetime
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, field_validator


class PromotionContentPayload(BaseModel):
    model_config = ConfigDict(extra="forbid")

    title: str = Field(min_length=1, max_length=160)
    short_message: str = Field(default="", max_length=400)
    full_message: str = Field(default="", max_length=4000)
    summary: str = Field(default="", max_length=600)
    highlights: list[str] = Field(default_factory=list)
    cta_primary: str = Field(default="", max_length=80)
    cta_secondary: str = Field(default="", max_length=80)
    delivery_type: str = Field(min_length=1, max_length=80)
    location: str = Field(min_length=1, max_length=120)
    specs: list[dict[str, str]] = Field(default_factory=list)
    image_urls: list[str] = Field(default_factory=list)
    meal_data: dict[str, Any] = Field(default_factory=dict)
    grocery_data: dict[str, Any] = Field(default_factory=dict)
    metadata: dict[str, Any] = Field(default_factory=dict)

    @field_validator(
        "title",
        "short_message",
        "full_message",
        "summary",
        "cta_primary",
        "cta_secondary",
        "delivery_type",
        "location",
        mode="before",
    )
    @classmethod
    def normalize_text(cls, value: str) -> str:
        return str(value).strip()

    @field_validator("highlights", "image_urls", mode="before")
    @classmethod
    def normalize_string_list(cls, value: list[str]) -> list[str]:
        normalized: list[str] = []
        for item in value:
            cleaned = str(item).strip()
            if cleaned and cleaned not in normalized:
                normalized.append(cleaned)
        return normalized


class PromotionCampaignCreateRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: str = Field(min_length=1, max_length=160)
    promotion_type: str = Field(min_length=1, max_length=80)
    delivery_type: str = Field(min_length=1, max_length=80)
    target_location: str = Field(min_length=1, max_length=120)
    admin_instruction: str = Field(min_length=1, max_length=4000)
    tone: str = Field(default="balanced", min_length=1, max_length=80)
    constraints: dict[str, Any] = Field(default_factory=dict)

    @field_validator("name", "promotion_type", "delivery_type", "target_location", "admin_instruction", "tone", mode="before")
    @classmethod
    def normalize_create_text(cls, value: str) -> str:
        return str(value).strip()


class PromotionCampaignUpdateRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: str | None = Field(default=None, min_length=1, max_length=160)
    promotion_type: str | None = Field(default=None, min_length=1, max_length=80)
    delivery_type: str | None = Field(default=None, min_length=1, max_length=80)
    target_location: str | None = Field(default=None, min_length=1, max_length=120)
    admin_instruction: str | None = Field(default=None, min_length=1, max_length=4000)
    tone: str | None = Field(default=None, min_length=1, max_length=80)
    constraints: dict[str, Any] | None = None
    status: str | None = Field(default=None, min_length=1, max_length=80)

    @field_validator(
        "name",
        "promotion_type",
        "delivery_type",
        "target_location",
        "admin_instruction",
        "tone",
        "status",
        mode="before",
    )
    @classmethod
    def normalize_optional_text(cls, value: str | None) -> str | None:
        if value is None:
            return None
        cleaned = str(value).strip()
        return cleaned or None


class PromotionCampaignResponse(BaseModel):
    id: str
    name: str
    created_by_admin_id: str
    status: str
    promotion_type: str
    delivery_type: str
    target_location: str
    admin_instruction: str
    tone: str
    constraints: dict[str, Any]
    selected_user_count: int
    created_at: datetime
    updated_at: datetime


class PromotionCampaignListResponse(BaseModel):
    items: list[PromotionCampaignResponse]
    total: int
    page: int
    page_size: int


class PromotionCampaignUsersAddRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    user_ids: list[str] = Field(default_factory=list, min_length=1)

    @field_validator("user_ids", mode="before")
    @classmethod
    def normalize_user_ids(cls, value: list[str]) -> list[str]:
        normalized: list[str] = []
        for user_id in value:
            cleaned = str(user_id).strip()
            if cleaned and cleaned not in normalized:
                normalized.append(cleaned)
        return normalized


class PromotionSelectableUserResponse(BaseModel):
    id: str
    name: str
    email: str
    user_types: list[str]
    created_at: datetime


class PromotionSelectableUsersListResponse(BaseModel):
    items: list[PromotionSelectableUserResponse]
    total: int
    page: int
    page_size: int


class PromotionUserConversationSummaryResponse(BaseModel):
    conversation_id: str
    agent_type: str
    status: str
    meal_type: str | None = None
    requested_culture: str | None = None
    last_user_message_preview: str | None = None
    last_assistant_preview: str | None = None
    latest_plan_summary: str | None = None
    message_count: int
    last_message_at: datetime | None = None
    updated_at: datetime | None = None
    created_at: datetime


class PromotionUserMessageSummaryResponse(BaseModel):
    id: str
    role: str
    text: str
    created_at: datetime | None = None


class PromotionUserCampaignMembershipResponse(BaseModel):
    campaign_id: str
    context_status: str
    generation_status: str
    review_status: str
    delivery_status: str
    context_snapshot: "PromotionContextSnapshotResponse | None" = None


class PromotionUserProfileResponse(BaseModel):
    id: str
    name: str
    email: str
    user_types: list[str]
    created_at: datetime
    user_configuration: dict[str, Any] = Field(default_factory=dict)
    profile_snapshot: dict[str, Any] = Field(default_factory=dict)
    preference_snapshot: dict[str, Any] = Field(default_factory=dict)
    eligibility_snapshot: dict[str, Any] = Field(default_factory=dict)
    source_refs: dict[str, Any] = Field(default_factory=dict)
    recent_conversations: list[PromotionUserConversationSummaryResponse] = Field(default_factory=list)
    recent_messages: list[PromotionUserMessageSummaryResponse] = Field(default_factory=list)
    campaign_membership: PromotionUserCampaignMembershipResponse | None = None


class PromotionCampaignUserSummaryResponse(BaseModel):
    user_id: str
    user_name: str
    email: str
    context_status: str
    generation_status: str
    review_status: str
    delivery_status: str
    last_activity_at: datetime | None = None
    latest_conversation_summary: str | None = None
    latest_plan_summary: str | None = None
    agent_type: str | None = None
    requested_culture: str | None = None
    has_more_context: bool = False


class PromotionCampaignUsersListResponse(BaseModel):
    items: list[PromotionCampaignUserSummaryResponse]
    total: int


class PromotionContextSnapshotResponse(BaseModel):
    id: str
    campaign_id: str
    user_id: str
    conversation_summary: str | None = None
    recent_messages_summary: list[dict[str, Any]] = Field(default_factory=list)
    latest_plan_summary: str | None = None
    profile_snapshot: dict[str, Any] = Field(default_factory=dict)
    preference_snapshot: dict[str, Any] = Field(default_factory=dict)
    eligibility_snapshot: dict[str, Any] = Field(default_factory=dict)
    source_refs: dict[str, Any] = Field(default_factory=dict)
    created_at: datetime


class PromotionContextRefreshResponse(BaseModel):
    campaign_id: str
    refreshed_count: int


class PromotionGenerateResponse(BaseModel):
    campaign_id: str
    generated_count: int
    failed_count: int


class PromotionDraftResponse(BaseModel):
    id: str
    campaign_id: str
    user_id: str
    user_name: str | None = None
    status: str
    generation_version: int
    edit_version: int
    generated_payload: PromotionContentPayload
    working_payload: PromotionContentPayload
    approved_payload: PromotionContentPayload | None = None
    is_admin_edited: bool
    edited_by_admin_id: str | None = None
    edited_at: datetime | None = None
    approved_by_admin_id: str | None = None
    approved_at: datetime | None = None
    validation_warnings: list[str] = Field(default_factory=list)
    failure_reason: str | None = None
    created_at: datetime
    updated_at: datetime


class PromotionDraftListResponse(BaseModel):
    items: list[PromotionDraftResponse]
    total: int


class PromotionDraftUpdateRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    working_payload: PromotionContentPayload


class PromotionDraftActionResponse(BaseModel):
    draft_id: str
    status: str


class PromotionBulkApproveRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    draft_ids: list[str] = Field(default_factory=list, min_length=1)

    @field_validator("draft_ids", mode="before")
    @classmethod
    def normalize_draft_ids(cls, value: list[str]) -> list[str]:
        normalized: list[str] = []
        for draft_id in value:
            cleaned = str(draft_id).strip()
            if cleaned and cleaned not in normalized:
                normalized.append(cleaned)
        return normalized


class PromotionDeliverResponse(BaseModel):
    campaign_id: str
    queued_count: int
    delivered_count: int
    failed_count: int


class PromotionDeliveryResponse(BaseModel):
    id: str
    campaign_id: str
    draft_id: str
    user_id: str
    delivery_type: str
    location: str
    payload_sent: dict[str, Any]
    delivery_status: str
    trace_id: str | None = None
    chat_message_id: str | None = None
    sent_at: datetime | None = None
    failure_reason: str | None = None
    created_at: datetime
    updated_at: datetime


class PromotionDeliveryListResponse(BaseModel):
    items: list[PromotionDeliveryResponse]
    total: int


class PromotionAuditLogResponse(BaseModel):
    id: str
    campaign_id: str
    draft_id: str | None = None
    user_id: str | None = None
    actor_admin_id: str
    action: str
    before_payload: dict[str, Any] | None = None
    after_payload: dict[str, Any] | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)
    created_at: datetime


class PromotionAuditLogListResponse(BaseModel):
    items: list[PromotionAuditLogResponse]
    total: int


PromotionUserCampaignMembershipResponse.model_rebuild()
