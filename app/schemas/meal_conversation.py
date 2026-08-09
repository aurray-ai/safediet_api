from datetime import date, datetime
from typing import Any, Literal

from pydantic import AliasChoices, BaseModel, ConfigDict, Field, model_validator

from app.models.grocery import CountryCode
from app.models.meal import MealType


class ConversationQuickActionResponse(BaseModel):
    id: str
    label: str = Field(min_length=1, max_length=80)
    action_type: str = Field(min_length=1, max_length=80)
    payload: dict[str, Any] = Field(default_factory=dict)


class ConversationUIBlockResponse(BaseModel):
    id: str
    block_type: str = Field(min_length=1, max_length=80)
    title: str | None = Field(default=None, max_length=120)
    payload: dict[str, Any] = Field(default_factory=dict)


class ConversationMessageResponse(BaseModel):
    id: str
    conversation_id: str
    role: str = Field(min_length=1, max_length=20)
    text: str = ""
    ui_blocks: list[ConversationUIBlockResponse] = Field(default_factory=list)
    quick_actions: list[ConversationQuickActionResponse] = Field(default_factory=list)
    metadata: dict[str, Any] = Field(default_factory=dict)
    created_at: datetime


class ConversationStateSummaryResponse(BaseModel):
    conversation_id: str
    agent_type: str
    status: str = Field(min_length=1, max_length=40)
    meal_type: MealType | None = None
    planned_meals: list[dict[str, Any]] = Field(default_factory=list)
    selected_meal_id: str | None = None
    selected_meal_name: str | None = None
    meal_source: str | None = None
    last_user_intent: str | None = None
    last_assistant_preview: str | None = None
    latest_ui_blocks: list[ConversationUIBlockResponse] = Field(default_factory=list)
    latest_quick_actions: list[ConversationQuickActionResponse] = Field(default_factory=list)
    latest_message_id: str | None = None
    message_count: int = Field(default=0, ge=0)
    country_code: CountryCode | None = None
    requested_culture: str | None = None
    last_message_at: datetime | None = None
    updated_at: datetime


class ConversationSummaryResponse(ConversationStateSummaryResponse):
    created_at: datetime


class CreateConversationRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    opening_message: str | None = Field(default=None, min_length=1, max_length=600)
    meal_type: MealType | None = None
    country_code: CountryCode | None = None


class CreateConversationResponse(BaseModel):
    conversation: ConversationSummaryResponse
    assistant_message: ConversationMessageResponse | None = None


class CurrentConversationResponse(BaseModel):
    conversation: ConversationSummaryResponse | None = None


class SendConversationMessageRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    text: str | None = Field(default=None, min_length=1, max_length=600)
    quick_action_id: str | None = Field(default=None, min_length=1, max_length=120)
    quick_action_type: str | None = Field(default=None, min_length=1, max_length=80)
    action_payload: dict[str, Any] = Field(default_factory=dict)

    @model_validator(mode="after")
    def validate_message_input(self) -> "SendConversationMessageRequest":
        if not self.text and not self.quick_action_type:
            raise ValueError("Either text or a quick action must be provided.")
        return self


class SendConversationMessageResponse(BaseModel):
    conversation: ConversationSummaryResponse
    user_message: ConversationMessageResponse
    assistant_message: ConversationMessageResponse


class SendConversationMessageAcceptedResponse(BaseModel):
    accepted: bool = True
    status: str = "processing"
    trace_id: str
    conversation: ConversationSummaryResponse
    user_message: ConversationMessageResponse


class ConversationMessagesResponse(BaseModel):
    items: list[ConversationMessageResponse]
    next_cursor: str | None = None


class MealPlannerRequest(BaseModel):
    model_config = ConfigDict(extra="forbid", populate_by_name=True)

    message: str = Field(min_length=1, max_length=600)
    request_type: str = Field(
        min_length=1,
        max_length=80,
        validation_alias=AliasChoices("request_type", "type"),
    )
    slot: MealType | None = None
    slots: list[MealType] = Field(default_factory=list)
    requested_culture: str | None = Field(default=None, min_length=1, max_length=80)
    country_code: CountryCode | None = None
    low_budget_mode: bool = False
    allow_custom_meal_creation: bool = False
    conversation_id: str | None = Field(default=None, min_length=1, max_length=120)
    candidate_limit_per_slot: int = Field(default=6, ge=1, le=12)
    effective_date: date | None = None
    selected_dates: list[date] = Field(default_factory=list)

    @model_validator(mode="after")
    def normalize_slots(self) -> "MealPlannerRequest":
        normalized_slots: list[MealType] = []
        if self.slot is not None:
            normalized_slots.append(self.slot)
        for item in self.slots:
            if item not in normalized_slots:
                normalized_slots.append(item)
        if not normalized_slots:
            raise ValueError("At least one slot must be provided.")
        self.slots = normalized_slots
        self.slot = normalized_slots[0] if len(normalized_slots) == 1 else None
        if self.requested_culture is not None:
            self.requested_culture = self.requested_culture.strip() or None
        if self.conversation_id is not None:
            self.conversation_id = self.conversation_id.strip() or None
        unique_selected_dates = sorted(set(self.selected_dates))
        if unique_selected_dates:
            if self.effective_date is None:
                self.effective_date = unique_selected_dates[0]
        elif self.effective_date is not None:
            unique_selected_dates = [self.effective_date]
        self.selected_dates = unique_selected_dates
        return self


class MealPlannerSearchTraceResponse(BaseModel):
    slot: MealType
    semantic_query: str
    candidate_count: int


class MealPlannerDraftUIBlockRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: str = Field(min_length=1, max_length=120)
    block_type: str = Field(min_length=1, max_length=80)
    title: str | None = Field(default=None, max_length=120)
    payload: dict[str, Any] = Field(default_factory=dict)


class MealPlannerDraftSaveRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    ui_block: MealPlannerDraftUIBlockRequest
    planned_meals: list[dict[str, Any]] = Field(default_factory=list)
    meal_type: MealType | None = None
    country_code: CountryCode | None = None
    requested_culture: str | None = Field(default=None, min_length=1, max_length=80)
    agent_type: str | None = Field(default=None, min_length=1, max_length=80)


class MealPlannerRunResponse(BaseModel):
    assistant_text: str
    turn_mode: Literal["conversation_reply", "clarification_request", "day_plan_generated", "day_plan_updated"]
    planned_meals: list[dict[str, Any]] = Field(default_factory=list)
    requested_culture: str | None = None
    bundle_summary: dict[str, Any] = Field(default_factory=dict)
    inventory_summary: dict[str, Any] = Field(default_factory=dict)
    cart_summary: dict[str, Any] = Field(default_factory=dict)
    ui_blocks: list[ConversationUIBlockResponse] = Field(default_factory=list)
    quick_actions: list[ConversationQuickActionResponse] = Field(default_factory=list)
    metadata: dict[str, Any] = Field(default_factory=dict)
    prepared_action_payload: dict[str, Any] = Field(default_factory=dict)
    semantic_queries: list[MealPlannerSearchTraceResponse] = Field(default_factory=list)


class MealPlannerRunAcceptedResponse(BaseModel):
    accepted: bool = True
    status: str = "processing"
    trace_id: str
    assistant_text: str
    request_type: str
    view_mode: Literal["day", "week"]
    effective_date: date | None = None
