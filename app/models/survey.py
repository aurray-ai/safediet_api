from dataclasses import dataclass, field
from datetime import datetime
from enum import StrEnum
from typing import Any


class SurveyStatus(StrEnum):
    DRAFT = "draft"
    PUBLISHED = "published"
    CLOSED = "closed"


class SurveyQuestionType(StrEnum):
    SHORT_TEXT = "short_text"
    PARAGRAPH = "paragraph"
    SINGLE_CHOICE = "single_choice"
    MULTIPLE_CHOICE = "multiple_choice"
    DROPDOWN = "dropdown"
    LINEAR_SCALE = "linear_scale"
    EMAIL = "email"
    NUMBER = "number"
    DATE = "date"
    TIME = "time"


class SurveyReportKey(StrEnum):
    PLANNING_FREQUENCY = "planning_frequency"
    PLANNING_DIFFICULTY = "planning_difficulty"
    PLANNING_CHALLENGE = "planning_challenge"
    HOUSEHOLD_SIZE = "household_size"
    BUDGET_CADENCE = "budget_cadence"
    BUDGET_OVERRUN_FREQUENCY = "budget_overrun_frequency"
    OVERSPEND_CAUSES = "overspend_causes"
    FEATURE_DEMAND = "feature_demand"
    TOTAL_TIME_SPENT = "total_time_spent"
    OPEN_FEEDBACK = "open_feedback"


@dataclass(frozen=True, slots=True)
class SurveySettings:
    is_public: bool
    collect_email: bool
    require_auth: bool
    limit_one_response_per_user: bool
    limit_one_response_per_email: bool
    show_progress_bar: bool
    shuffle_question_order: bool
    confirmation_message: str
    accepting_responses: bool


@dataclass(frozen=True, slots=True)
class SurveyTheme:
    accent_color: str
    header_image_url: str
    font_family: str


@dataclass(frozen=True, slots=True)
class SurveySection:
    id: str
    title: str
    description: str
    position: int


@dataclass(frozen=True, slots=True)
class SurveyQuestionOption:
    id: str
    label: str
    value: str
    position: int


@dataclass(frozen=True, slots=True)
class SurveyQuestionValidation:
    min_length: int | None = None
    max_length: int | None = None
    min_value: float | None = None
    max_value: float | None = None
    max_selections: int | None = None
    regex: str | None = None


@dataclass(frozen=True, slots=True)
class SurveyQuestionConfig:
    placeholder: str | None = None
    allow_other: bool = False
    scale_min: int | None = None
    scale_max: int | None = None
    scale_min_label: str | None = None
    scale_max_label: str | None = None


@dataclass(frozen=True, slots=True)
class SurveyQuestion:
    id: str
    section_id: str
    position: int
    type: SurveyQuestionType
    report_key: SurveyReportKey | None
    title: str
    description: str
    required: bool
    options: list[SurveyQuestionOption] = field(default_factory=list)
    validation: SurveyQuestionValidation = field(default_factory=SurveyQuestionValidation)
    config: SurveyQuestionConfig = field(default_factory=SurveyQuestionConfig)


@dataclass(frozen=True, slots=True)
class Survey:
    id: str
    slug: str
    title: str
    description: str
    status: SurveyStatus
    owner_user_id: str
    settings: SurveySettings
    theme: SurveyTheme
    sections: list[SurveySection]
    questions: list[SurveyQuestion]
    version: int
    response_count: int
    published_at: datetime | None
    closed_at: datetime | None
    last_response_at: datetime | None
    created_at: datetime
    updated_at: datetime


@dataclass(frozen=True, slots=True)
class SurveyRespondent:
    user_id: str | None
    email: str | None
    name: str | None
    ip_hash: str | None
    user_agent: str | None


@dataclass(frozen=True, slots=True)
class SurveyAnswer:
    question_id: str
    type: SurveyQuestionType
    value: Any


@dataclass(frozen=True, slots=True)
class SurveyResponse:
    id: str
    survey_id: str
    survey_slug: str
    survey_version: int
    respondent: SurveyRespondent
    answers: list[SurveyAnswer]
    submitted_at: datetime
    created_at: datetime
