from __future__ import annotations

from datetime import datetime
from typing import Any

from pydantic import BaseModel, Field, field_validator, model_validator

from app.models.survey import SurveyQuestionType, SurveyReportKey, SurveyStatus


class SurveySettingsPayload(BaseModel):
    is_public: bool = True
    collect_email: bool = False
    require_auth: bool = False
    limit_one_response_per_user: bool = False
    limit_one_response_per_email: bool = False
    show_progress_bar: bool = True
    shuffle_question_order: bool = False
    confirmation_message: str = "Thanks for completing this survey."
    accepting_responses: bool = True

    @field_validator("confirmation_message", mode="before")
    @classmethod
    def normalize_confirmation_message(cls, value: str) -> str:
        cleaned = str(value).strip()
        return cleaned or "Thanks for completing this survey."


class SurveyThemePayload(BaseModel):
    accent_color: str = "#2f6fed"
    header_image_url: str = ""
    font_family: str = "inherit"

    @field_validator("accent_color", "header_image_url", "font_family", mode="before")
    @classmethod
    def normalize_text(cls, value: str) -> str:
        return str(value).strip()


class SurveySectionPayload(BaseModel):
    id: str = Field(min_length=1, max_length=120)
    title: str = Field(min_length=1, max_length=160)
    description: str = Field(default="", max_length=1000)
    position: int = Field(ge=1)

    @field_validator("id", "title", "description", mode="before")
    @classmethod
    def normalize_text(cls, value: str) -> str:
        return str(value).strip()


class SurveyQuestionOptionPayload(BaseModel):
    id: str = Field(min_length=1, max_length=120)
    label: str = Field(min_length=1, max_length=160)
    value: str = Field(min_length=1, max_length=160)
    position: int = Field(ge=1)

    @field_validator("id", "label", "value", mode="before")
    @classmethod
    def normalize_text(cls, value: str) -> str:
        return str(value).strip()


class SurveyQuestionValidationPayload(BaseModel):
    min_length: int | None = Field(default=None, ge=0)
    max_length: int | None = Field(default=None, ge=1)
    min_value: float | None = None
    max_value: float | None = None
    max_selections: int | None = Field(default=None, ge=1)
    regex: str | None = Field(default=None, max_length=300)

    @field_validator("regex", mode="before")
    @classmethod
    def normalize_regex(cls, value: str | None) -> str | None:
        if value is None:
            return None
        cleaned = str(value).strip()
        return cleaned or None


class SurveyQuestionConfigPayload(BaseModel):
    placeholder: str | None = Field(default=None, max_length=200)
    allow_other: bool = False
    scale_min: int | None = None
    scale_max: int | None = None
    scale_min_label: str | None = Field(default=None, max_length=80)
    scale_max_label: str | None = Field(default=None, max_length=80)

    @field_validator("placeholder", "scale_min_label", "scale_max_label", mode="before")
    @classmethod
    def normalize_optional_text(cls, value: str | None) -> str | None:
        if value is None:
            return None
        cleaned = str(value).strip()
        return cleaned or None


class SurveyQuestionPayload(BaseModel):
    id: str = Field(min_length=1, max_length=120)
    section_id: str = Field(min_length=1, max_length=120)
    position: int = Field(ge=1)
    type: SurveyQuestionType
    report_key: SurveyReportKey | None = None
    title: str = Field(min_length=1, max_length=240)
    description: str = Field(default="", max_length=1000)
    required: bool = False
    options: list[SurveyQuestionOptionPayload] = Field(default_factory=list)
    validation: SurveyQuestionValidationPayload = Field(default_factory=SurveyQuestionValidationPayload)
    config: SurveyQuestionConfigPayload = Field(default_factory=SurveyQuestionConfigPayload)

    @field_validator("id", "section_id", "title", "description", mode="before")
    @classmethod
    def normalize_text(cls, value: str) -> str:
        return str(value).strip()

    @model_validator(mode="after")
    def validate_type_specific_fields(self) -> "SurveyQuestionPayload":
        choice_types = {
            SurveyQuestionType.SINGLE_CHOICE,
            SurveyQuestionType.MULTIPLE_CHOICE,
            SurveyQuestionType.DROPDOWN,
        }
        if self.type in choice_types and not self.options:
            raise ValueError("Choice questions must include at least one option.")
        if self.type not in choice_types and self.options:
            self.options = []

        if self.type == SurveyQuestionType.LINEAR_SCALE:
            scale_min = self.config.scale_min if self.config.scale_min is not None else 1
            scale_max = self.config.scale_max if self.config.scale_max is not None else 5
            if scale_max <= scale_min:
                raise ValueError("Linear scale max must be greater than min.")
            self.config.scale_min = scale_min
            self.config.scale_max = scale_max
        else:
            self.config.scale_min = None
            self.config.scale_max = None
            self.config.scale_min_label = None
            self.config.scale_max_label = None

        if self.type != SurveyQuestionType.MULTIPLE_CHOICE:
            self.validation.max_selections = None

        return self


class SurveyUpsertRequest(BaseModel):
    title: str = Field(min_length=1, max_length=200)
    slug: str = Field(min_length=1, max_length=160)
    description: str = Field(default="", max_length=4000)
    settings: SurveySettingsPayload = Field(default_factory=SurveySettingsPayload)
    theme: SurveyThemePayload = Field(default_factory=SurveyThemePayload)
    sections: list[SurveySectionPayload] = Field(default_factory=list, min_length=1)
    questions: list[SurveyQuestionPayload] = Field(default_factory=list)

    @field_validator("title", "slug", "description", mode="before")
    @classmethod
    def normalize_text(cls, value: str) -> str:
        return str(value).strip()

    @field_validator("slug", mode="after")
    @classmethod
    def normalize_slug(cls, value: str) -> str:
        normalized = "-".join(part for part in value.lower().replace("_", "-").split() if part)
        return normalized.strip("-")

    @model_validator(mode="after")
    def validate_relationships(self) -> "SurveyUpsertRequest":
        if not self.slug:
            raise ValueError("Slug is required.")

        section_ids = [section.id for section in self.sections]
        if len(set(section_ids)) != len(section_ids):
            raise ValueError("Section ids must be unique.")

        question_ids = [question.id for question in self.questions]
        if len(set(question_ids)) != len(question_ids):
            raise ValueError("Question ids must be unique.")

        section_id_set = set(section_ids)
        for question in self.questions:
            if question.section_id not in section_id_set:
                raise ValueError("Each question must belong to an existing section.")

        return self


class SurveyQuestionOptionResponse(BaseModel):
    id: str
    label: str
    value: str
    position: int


class SurveyQuestionValidationResponse(BaseModel):
    min_length: int | None = None
    max_length: int | None = None
    min_value: float | None = None
    max_value: float | None = None
    max_selections: int | None = None
    regex: str | None = None


class SurveyQuestionConfigResponse(BaseModel):
    placeholder: str | None = None
    allow_other: bool = False
    scale_min: int | None = None
    scale_max: int | None = None
    scale_min_label: str | None = None
    scale_max_label: str | None = None


class SurveyQuestionResponse(BaseModel):
    id: str
    section_id: str
    position: int
    type: SurveyQuestionType
    report_key: SurveyReportKey | None = None
    title: str
    description: str
    required: bool
    options: list[SurveyQuestionOptionResponse]
    validation: SurveyQuestionValidationResponse
    config: SurveyQuestionConfigResponse


class SurveySectionResponse(BaseModel):
    id: str
    title: str
    description: str
    position: int


class SurveySettingsResponse(BaseModel):
    is_public: bool
    collect_email: bool
    require_auth: bool
    limit_one_response_per_user: bool
    limit_one_response_per_email: bool
    show_progress_bar: bool
    shuffle_question_order: bool
    confirmation_message: str
    accepting_responses: bool


class SurveyThemeResponse(BaseModel):
    accent_color: str
    header_image_url: str
    font_family: str


class SurveyResponseBase(BaseModel):
    id: str
    slug: str
    title: str
    description: str
    status: SurveyStatus
    settings: SurveySettingsResponse
    theme: SurveyThemeResponse
    sections: list[SurveySectionResponse]
    questions: list[SurveyQuestionResponse]
    version: int
    response_count: int
    published_at: datetime | None
    closed_at: datetime | None
    last_response_at: datetime | None
    created_at: datetime
    updated_at: datetime


class AdminSurveyResponse(SurveyResponseBase):
    owner_user_id: str


class AdminSurveyListResponse(BaseModel):
    items: list[AdminSurveyResponse]
    total: int
    page: int
    page_size: int


class PublicSurveyResponse(SurveyResponseBase):
    pass


class SurveyAnswerSubmission(BaseModel):
    question_id: str = Field(min_length=1, max_length=120)
    value: Any

    @field_validator("question_id", mode="before")
    @classmethod
    def normalize_question_id(cls, value: str) -> str:
        return str(value).strip()


class SurveyResponseSubmissionRequest(BaseModel):
    respondent_email: str | None = Field(default=None, max_length=240)
    respondent_name: str | None = Field(default=None, max_length=200)
    answers: list[SurveyAnswerSubmission] = Field(default_factory=list)

    @field_validator("respondent_email", "respondent_name", mode="before")
    @classmethod
    def normalize_optional_text(cls, value: str | None) -> str | None:
        if value is None:
            return None
        cleaned = str(value).strip()
        return cleaned or None


class SurveyAnswerResponse(BaseModel):
    question_id: str
    type: SurveyQuestionType
    value: Any


class SurveyRespondentResponse(BaseModel):
    user_id: str | None
    email: str | None
    name: str | None
    user_agent: str | None


class SurveySubmissionResponse(BaseModel):
    id: str
    survey_id: str
    survey_slug: str
    survey_version: int
    respondent: SurveyRespondentResponse
    answers: list[SurveyAnswerResponse]
    submitted_at: datetime
    created_at: datetime


class AdminSurveyResponseListResponse(BaseModel):
    items: list[SurveySubmissionResponse]
    total: int
    survey_id: str


class SurveyQuestionAnalyticsResponse(BaseModel):
    question_id: str
    title: str
    type: SurveyQuestionType
    response_count: int
    choice_counts: dict[str, int] = Field(default_factory=dict)


class SurveyReportMetricResponse(BaseModel):
    label: str
    value: str
    detail: str


class SurveyRankedItemResponse(BaseModel):
    label: str
    count: int
    percent: int


class SurveySegmentDemandResponse(BaseModel):
    segment: str
    top_feature: str
    top_feature_percent: int
    response_count: int


class SurveyFeedbackSnippetResponse(BaseModel):
    text: str
    tags: list[str]
    tone: str
    urgency: str


class SurveyThemeShareResponse(BaseModel):
    label: str
    count: int
    percent: int


class SurveyCoreReportOverviewResponse(BaseModel):
    top_blocker: str
    top_feature: str
    dominant_theme: str
    top_issue_share: int
    feature_demand_share: int
    theme_share: int


class SurveyMealPlanningReportResponse(BaseModel):
    metrics: list[SurveyReportMetricResponse]
    frequency: list[SurveyRankedItemResponse]
    challenges: list[SurveyRankedItemResponse]
    segments: list[SurveyRankedItemResponse]


class SurveyBudgetRiskReportResponse(BaseModel):
    metrics: list[SurveyReportMetricResponse]
    cadence: list[SurveyRankedItemResponse]
    overspend_frequency: list[SurveyRankedItemResponse]
    overspend_causes: list[SurveyRankedItemResponse]


class SurveyFeatureDemandReportResponse(BaseModel):
    metrics: list[SurveyReportMetricResponse]
    features: list[SurveyRankedItemResponse]
    time_bands: list[SurveyRankedItemResponse]
    segment_demand: list[SurveySegmentDemandResponse]


class SurveyOpenFeedbackReportResponse(BaseModel):
    metrics: list[SurveyReportMetricResponse]
    themes: list[SurveyThemeShareResponse]
    sentiment: list[SurveyThemeShareResponse]
    urgency: list[SurveyThemeShareResponse]
    snippets: list[SurveyFeedbackSnippetResponse]


class SurveyCoreReportsResponse(BaseModel):
    has_responses: bool
    response_count: int
    overview: SurveyCoreReportOverviewResponse
    meal_planning: SurveyMealPlanningReportResponse
    budget_risk: SurveyBudgetRiskReportResponse
    feature_demand: SurveyFeatureDemandReportResponse
    open_feedback: SurveyOpenFeedbackReportResponse


class SurveyAnalyticsResponse(BaseModel):
    survey_id: str
    total_responses: int
    latest_response_at: datetime | None
    question_stats: list[SurveyQuestionAnalyticsResponse]
    core_reports: SurveyCoreReportsResponse


class SurveyTemplateResponse(BaseModel):
    template_id: str
    name: str
    description: str
    survey: SurveyUpsertRequest


class AdminSurveyTemplateListResponse(BaseModel):
    items: list[SurveyTemplateResponse]
