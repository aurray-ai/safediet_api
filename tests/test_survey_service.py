from __future__ import annotations

import unittest
from datetime import datetime, timezone

from app.models.survey import (
    SurveyAnswer,
    Survey,
    SurveyResponse,
    SurveyRespondent,
    SurveyQuestion,
    SurveyQuestionConfig,
    SurveyQuestionOption,
    SurveyReportKey,
    SurveyQuestionType,
    SurveyQuestionValidation,
    SurveySection,
    SurveySettings,
    SurveyStatus,
    SurveyTheme,
)
from app.models.user import User, UserType
from app.schemas.survey import SurveyResponseSubmissionRequest, SurveyUpsertRequest
from app.services.survey_service import SurveyResponseConflictError, SurveyService, SurveyValidationError


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


def build_survey() -> Survey:
    now = utc_now()
    return Survey(
        id="survey-1",
        slug="customer-feedback",
        title="Customer Feedback",
        description="Tell us what you think.",
        status=SurveyStatus.PUBLISHED,
        owner_user_id="user-1",
        settings=SurveySettings(
            is_public=True,
            collect_email=True,
            require_auth=False,
            limit_one_response_per_user=False,
            limit_one_response_per_email=True,
            show_progress_bar=True,
            shuffle_question_order=False,
            confirmation_message="Thanks.",
            accepting_responses=True,
        ),
        theme=SurveyTheme(accent_color="#2f6fed", header_image_url="", font_family="inherit"),
        sections=[SurveySection(id="section_1", title="Page 1", description="", position=1)],
        questions=[
            SurveyQuestion(
                id="question_1",
                section_id="section_1",
                position=1,
                type=SurveyQuestionType.SHORT_TEXT,
                report_key=None,
                title="What is your name?",
                description="",
                required=True,
                options=[],
                validation=SurveyQuestionValidation(),
                config=SurveyQuestionConfig(),
            ),
            SurveyQuestion(
                id="question_2",
                section_id="section_1",
                position=2,
                type=SurveyQuestionType.SINGLE_CHOICE,
                report_key=None,
                title="How was delivery?",
                description="",
                required=True,
                options=[
                    SurveyQuestionOption(id="option_1", label="Great", value="great", position=1),
                    SurveyQuestionOption(id="option_2", label="Okay", value="okay", position=2),
                ],
                validation=SurveyQuestionValidation(),
                config=SurveyQuestionConfig(),
            ),
        ],
        version=1,
        response_count=0,
        published_at=now,
        closed_at=None,
        last_response_at=None,
        created_at=now,
        updated_at=now,
    )


def build_reporting_survey(
    *,
    question_ids: dict[str, str] | None = None,
    include_report_keys: bool = False,
    generic_titles: bool = False,
) -> Survey:
    now = utc_now()
    question_ids = question_ids or {
        "planning_frequency": "q1_meal_planning_frequency",
        "planning_difficulty": "q2_weekly_difficulty",
        "planning_challenge": "q3_biggest_planning_challenge",
        "household_size": "q4_household_size",
        "budget_cadence": "q5_budget_cadence",
        "budget_overrun_frequency": "q6_budget_overrun_frequency",
        "overspend_causes": "q7_overspend_causes",
        "feature_demand": "q13_time_savers",
        "total_time_spent": "q14_total_time_spent",
        "open_feedback": "q15_open_improvement",
    }
    report_keys = {
        "planning_frequency": SurveyReportKey.PLANNING_FREQUENCY,
        "planning_difficulty": SurveyReportKey.PLANNING_DIFFICULTY,
        "planning_challenge": SurveyReportKey.PLANNING_CHALLENGE,
        "household_size": SurveyReportKey.HOUSEHOLD_SIZE,
        "budget_cadence": SurveyReportKey.BUDGET_CADENCE,
        "budget_overrun_frequency": SurveyReportKey.BUDGET_OVERRUN_FREQUENCY,
        "overspend_causes": SurveyReportKey.OVERSPEND_CAUSES,
        "feature_demand": SurveyReportKey.FEATURE_DEMAND,
        "total_time_spent": SurveyReportKey.TOTAL_TIME_SPENT,
        "open_feedback": SurveyReportKey.OPEN_FEEDBACK,
    }
    option = lambda option_id, label, value, position: SurveyQuestionOption(  # noqa: E731
        id=option_id,
        label=label,
        value=value,
        position=position,
    )
    return Survey(
        id="survey-reporting",
        slug="safediet-user-research-survey",
        title="SafeDiet User Research Survey",
        description="Research",
        status=SurveyStatus.PUBLISHED,
        owner_user_id="user-1",
        settings=SurveySettings(
            is_public=True,
            collect_email=True,
            require_auth=False,
            limit_one_response_per_user=False,
            limit_one_response_per_email=True,
            show_progress_bar=True,
            shuffle_question_order=False,
            confirmation_message="Thanks.",
            accepting_responses=True,
        ),
        theme=SurveyTheme(accent_color="#2f6fed", header_image_url="", font_family="inherit"),
        sections=[SurveySection(id="section_1", title="Page 1", description="", position=1)],
        questions=[
            SurveyQuestion(
                id=question_ids["planning_frequency"],
                section_id="section_1",
                position=1,
                type=SurveyQuestionType.SINGLE_CHOICE,
                report_key=report_keys["planning_frequency"] if include_report_keys else None,
                title="Question A" if generic_titles else "Meal planning frequency",
                description="",
                required=True,
                options=[
                    option("q1_o1", "Every week", "every_week", 1),
                    option("q1_o2", "A few days at a time", "few_days", 2),
                ],
                validation=SurveyQuestionValidation(),
                config=SurveyQuestionConfig(),
            ),
            SurveyQuestion(
                id=question_ids["planning_difficulty"],
                section_id="section_1",
                position=2,
                type=SurveyQuestionType.LINEAR_SCALE,
                report_key=report_keys["planning_difficulty"] if include_report_keys else None,
                title="Question B" if generic_titles else "How difficult do you find planning meals for an entire week?",
                description="",
                required=True,
                options=[],
                validation=SurveyQuestionValidation(),
                config=SurveyQuestionConfig(scale_min=1, scale_max=5),
            ),
            SurveyQuestion(
                id=question_ids["planning_challenge"],
                section_id="section_1",
                position=3,
                type=SurveyQuestionType.SINGLE_CHOICE,
                report_key=report_keys["planning_challenge"] if include_report_keys else None,
                title="Question C" if generic_titles else "Biggest challenge",
                description="",
                required=True,
                options=[
                    option("q3_o1", "I don't have enough time", "not_enough_time", 1),
                    option("q3_o2", "I get bored eating the same meals", "meal_repetition", 2),
                ],
                validation=SurveyQuestionValidation(),
                config=SurveyQuestionConfig(),
            ),
            SurveyQuestion(
                id=question_ids["household_size"],
                section_id="section_1",
                position=4,
                type=SurveyQuestionType.SINGLE_CHOICE,
                report_key=report_keys["household_size"] if include_report_keys else None,
                title="Question D" if generic_titles else "Household size",
                description="",
                required=True,
                options=[
                    option("q4_o1", "Two people", "two", 1),
                    option("q4_o2", "Three to four people", "three_to_four", 2),
                ],
                validation=SurveyQuestionValidation(),
                config=SurveyQuestionConfig(),
            ),
            SurveyQuestion(
                id=question_ids["budget_cadence"],
                section_id="section_1",
                position=5,
                type=SurveyQuestionType.SINGLE_CHOICE,
                report_key=report_keys["budget_cadence"] if include_report_keys else None,
                title="Question E" if generic_titles else "Budget cadence",
                description="",
                required=True,
                options=[
                    option("q5_o1", "Yes, every week", "weekly", 1),
                    option("q5_o2", "No", "no", 2),
                ],
                validation=SurveyQuestionValidation(),
                config=SurveyQuestionConfig(),
            ),
            SurveyQuestion(
                id=question_ids["budget_overrun_frequency"],
                section_id="section_1",
                position=6,
                type=SurveyQuestionType.SINGLE_CHOICE,
                report_key=report_keys["budget_overrun_frequency"] if include_report_keys else None,
                title="Question F" if generic_titles else "Budget overrun frequency",
                description="",
                required=True,
                options=[
                    option("q6_o1", "Almost every week", "almost_every_week", 1),
                    option("q6_o2", "Sometimes", "sometimes", 2),
                    option("q6_o3", "I don't keep track", "dont_track", 3),
                ],
                validation=SurveyQuestionValidation(),
                config=SurveyQuestionConfig(),
            ),
            SurveyQuestion(
                id=question_ids["overspend_causes"],
                section_id="section_1",
                position=7,
                type=SurveyQuestionType.MULTIPLE_CHOICE,
                report_key=report_keys["overspend_causes"] if include_report_keys else None,
                title="Question G" if generic_titles else "Overspend causes",
                description="",
                required=True,
                options=[
                    option("q7_o1", "Impulse purchases", "impulse_purchases", 1),
                    option("q7_o2", "Poor meal planning", "poor_meal_planning", 2),
                ],
                validation=SurveyQuestionValidation(max_selections=3),
                config=SurveyQuestionConfig(),
            ),
            SurveyQuestion(
                id=question_ids["feature_demand"],
                section_id="section_1",
                position=8,
                type=SurveyQuestionType.MULTIPLE_CHOICE,
                report_key=report_keys["feature_demand"] if include_report_keys else None,
                title="Question H" if generic_titles else "Time savers",
                description="",
                required=True,
                options=[
                    option("q13_o1", "Automatic weekly meal planning", "automatic_meal_planning", 1),
                    option("q13_o2", "Automatic grocery lists", "automatic_grocery_lists", 2),
                    option("q13_o3", "Shared grocery lists with family or flatmates", "shared_lists", 3),
                ],
                validation=SurveyQuestionValidation(max_selections=3),
                config=SurveyQuestionConfig(),
            ),
            SurveyQuestion(
                id=question_ids["total_time_spent"],
                section_id="section_1",
                position=9,
                type=SurveyQuestionType.SINGLE_CHOICE,
                report_key=report_keys["total_time_spent"] if include_report_keys else None,
                title="Question I" if generic_titles else "Total time spent",
                description="",
                required=True,
                options=[
                    option("q14_o1", "1–2 hours", "1_to_2_hours", 1),
                    option("q14_o2", "More than 3 hours", "over_3_hours", 2),
                ],
                validation=SurveyQuestionValidation(),
                config=SurveyQuestionConfig(),
            ),
            SurveyQuestion(
                id=question_ids["open_feedback"],
                section_id="section_1",
                position=10,
                type=SurveyQuestionType.PARAGRAPH,
                report_key=report_keys["open_feedback"] if include_report_keys else None,
                title="Question J" if generic_titles else "Open improvement",
                description="",
                required=True,
                options=[],
                validation=SurveyQuestionValidation(),
                config=SurveyQuestionConfig(),
            ),
        ],
        version=1,
        response_count=2,
        published_at=now,
        closed_at=None,
        last_response_at=now,
        created_at=now,
        updated_at=now,
    )


def build_reporting_responses(*, question_ids: dict[str, str] | None = None) -> list[SurveyResponse]:
    now = utc_now()
    question_ids = question_ids or {
        "planning_frequency": "q1_meal_planning_frequency",
        "planning_difficulty": "q2_weekly_difficulty",
        "planning_challenge": "q3_biggest_planning_challenge",
        "household_size": "q4_household_size",
        "budget_cadence": "q5_budget_cadence",
        "budget_overrun_frequency": "q6_budget_overrun_frequency",
        "overspend_causes": "q7_overspend_causes",
        "feature_demand": "q13_time_savers",
        "total_time_spent": "q14_total_time_spent",
        "open_feedback": "q15_open_improvement",
    }
    return [
        SurveyResponse(
            id="response-1",
            survey_id="survey-reporting",
            survey_slug="safediet-user-research-survey",
            survey_version=1,
            respondent=SurveyRespondent(
                user_id=None,
                email="first@example.com",
                name="First",
                ip_hash=None,
                user_agent="pytest",
            ),
            answers=[
                SurveyAnswer(question_id=question_ids["planning_frequency"], type=SurveyQuestionType.SINGLE_CHOICE, value="every_week"),
                SurveyAnswer(question_id=question_ids["planning_difficulty"], type=SurveyQuestionType.LINEAR_SCALE, value=2),
                SurveyAnswer(question_id=question_ids["planning_challenge"], type=SurveyQuestionType.SINGLE_CHOICE, value="not_enough_time"),
                SurveyAnswer(question_id=question_ids["household_size"], type=SurveyQuestionType.SINGLE_CHOICE, value="two"),
                SurveyAnswer(question_id=question_ids["budget_cadence"], type=SurveyQuestionType.SINGLE_CHOICE, value="weekly"),
                SurveyAnswer(question_id=question_ids["budget_overrun_frequency"], type=SurveyQuestionType.SINGLE_CHOICE, value="almost_every_week"),
                SurveyAnswer(question_id=question_ids["overspend_causes"], type=SurveyQuestionType.MULTIPLE_CHOICE, value=["impulse_purchases", "poor_meal_planning"]),
                SurveyAnswer(question_id=question_ids["feature_demand"], type=SurveyQuestionType.MULTIPLE_CHOICE, value=["automatic_meal_planning", "shared_lists"]),
                SurveyAnswer(question_id=question_ids["total_time_spent"], type=SurveyQuestionType.SINGLE_CHOICE, value="over_3_hours"),
                SurveyAnswer(question_id=question_ids["open_feedback"], type=SurveyQuestionType.PARAGRAPH, value="Need a cheaper way to shop and shared lists to save money."),
            ],
            submitted_at=now,
            created_at=now,
        ),
        SurveyResponse(
            id="response-2",
            survey_id="survey-reporting",
            survey_slug="safediet-user-research-survey",
            survey_version=1,
            respondent=SurveyRespondent(
                user_id=None,
                email="second@example.com",
                name="Second",
                ip_hash=None,
                user_agent="pytest",
            ),
            answers=[
                SurveyAnswer(question_id=question_ids["planning_frequency"], type=SurveyQuestionType.SINGLE_CHOICE, value="few_days"),
                SurveyAnswer(question_id=question_ids["planning_difficulty"], type=SurveyQuestionType.LINEAR_SCALE, value=4),
                SurveyAnswer(question_id=question_ids["planning_challenge"], type=SurveyQuestionType.SINGLE_CHOICE, value="not_enough_time"),
                SurveyAnswer(question_id=question_ids["household_size"], type=SurveyQuestionType.SINGLE_CHOICE, value="two"),
                SurveyAnswer(question_id=question_ids["budget_cadence"], type=SurveyQuestionType.SINGLE_CHOICE, value="no"),
                SurveyAnswer(question_id=question_ids["budget_overrun_frequency"], type=SurveyQuestionType.SINGLE_CHOICE, value="sometimes"),
                SurveyAnswer(question_id=question_ids["overspend_causes"], type=SurveyQuestionType.MULTIPLE_CHOICE, value=["impulse_purchases"]),
                SurveyAnswer(question_id=question_ids["feature_demand"], type=SurveyQuestionType.MULTIPLE_CHOICE, value=["automatic_meal_planning", "automatic_grocery_lists"]),
                SurveyAnswer(question_id=question_ids["total_time_spent"], type=SurveyQuestionType.SINGLE_CHOICE, value="1_to_2_hours"),
                SurveyAnswer(question_id=question_ids["open_feedback"], type=SurveyQuestionType.PARAGRAPH, value="Groceries are expensive and I need better budget suggestions."),
            ],
            submitted_at=now,
            created_at=now,
        ),
    ]


class StubSurveyRepository:
    def __init__(self) -> None:
        self.survey = build_survey()
        self.recorded_response: dict[str, object] | None = None

    def list_surveys(self, **_kwargs):
        return [self.survey], 1

    def get_by_id(self, *, survey_id: str):
        return self.survey if survey_id == self.survey.id else None

    def get_by_slug(self, *, slug: str):
        return self.survey if slug == self.survey.slug else None

    def create_survey(self, **_kwargs):
        return self.survey

    def update_survey(self, **_kwargs):
        return self.survey

    def delete_survey(self, *, survey_id: str):
        return survey_id == self.survey.id

    def publish_survey(self, *, survey_id: str):
        return self.survey if survey_id == self.survey.id else None

    def close_survey(self, *, survey_id: str):
        return self.survey if survey_id == self.survey.id else None

    def record_response(self, *, survey_id: str, submitted_at: datetime):
        self.recorded_response = {"survey_id": survey_id, "submitted_at": submitted_at}


class StubSurveyResponseRepository:
    def __init__(self) -> None:
        self.has_email = False
        self.created_payload: dict[str, object] | None = None
        self.responses: list[SurveyResponse] = []

    def create_response(self, **kwargs):
        self.created_payload = dict(kwargs)
        now = utc_now()
        return type(
            "Response",
            (),
            {
                "id": "response-1",
                "survey_id": kwargs["survey_id"],
                "survey_slug": kwargs["survey_slug"],
                "survey_version": kwargs["survey_version"],
                "respondent": type(
                    "Respondent",
                    (),
                    {
                        "user_id": kwargs["respondent"]["user_id"],
                        "email": kwargs["respondent"]["email"],
                        "name": kwargs["respondent"]["name"],
                        "ip_hash": kwargs["respondent"]["ip_hash"],
                        "user_agent": kwargs["respondent"]["user_agent"],
                    },
                )(),
                "answers": [
                    type(
                        "Answer",
                        (),
                        {
                            "question_id": answer["question_id"],
                            "type": SurveyQuestionType(answer["type"]),
                            "value": answer["value"],
                        },
                    )()
                    for answer in kwargs["answers"]
                ],
                "submitted_at": now,
                "created_at": now,
            },
        )()

    def list_responses(self, *, survey_id: str, limit: int = 100):
        items = [response for response in self.responses if response.survey_id == survey_id][:limit]
        return items, len(items)

    def get_by_id(self, *, survey_id: str, response_id: str):
        return None

    def has_response_for_user(self, *, survey_id: str, user_id: str):
        return False

    def has_response_for_email(self, *, survey_id: str, email: str):
        return self.has_email


class SurveyServiceTests(unittest.TestCase):
    def test_submit_response_normalizes_email_and_answers(self) -> None:
        survey_repository = StubSurveyRepository()
        response_repository = StubSurveyResponseRepository()
        service = SurveyService(
            survey_repository=survey_repository,  # type: ignore[arg-type]
            survey_response_repository=response_repository,  # type: ignore[arg-type]
        )
        payload = SurveyResponseSubmissionRequest.model_validate(
            {
                "respondent_email": " ADA@EXAMPLE.COM ",
                "respondent_name": "Ada",
                "answers": [
                    {"question_id": "question_1", "value": " Ada "},
                    {"question_id": "question_2", "value": "great"},
                ],
            }
        )

        response = service.submit_response(
            slug="customer-feedback",
            payload=payload,
            current_user=None,
            request_ip="127.0.0.1",
            user_agent="pytest",
        )

        self.assertEqual("ada@example.com", response.respondent.email)
        self.assertEqual("Ada", response.answers[0].value)
        self.assertEqual("great", response.answers[1].value)
        self.assertIsNotNone(survey_repository.recorded_response)

    def test_submit_response_rejects_duplicate_email(self) -> None:
        service = SurveyService(
            survey_repository=StubSurveyRepository(),  # type: ignore[arg-type]
            survey_response_repository=StubSurveyResponseRepository(),  # type: ignore[arg-type]
        )
        service._survey_response_repository.has_email = True  # type: ignore[attr-defined]
        payload = SurveyResponseSubmissionRequest.model_validate(
            {
                "respondent_email": "ada@example.com",
                "answers": [
                    {"question_id": "question_1", "value": "Ada"},
                    {"question_id": "question_2", "value": "great"},
                ],
            }
        )

        with self.assertRaises(SurveyResponseConflictError):
            service.submit_response(
                slug="customer-feedback",
                payload=payload,
                current_user=None,
                request_ip=None,
                user_agent=None,
            )

    def test_validate_payload_requires_continuous_section_positions(self) -> None:
        payload = SurveyUpsertRequest.model_validate(
            {
                "title": "Broken",
                "slug": "broken",
                "sections": [
                    {"id": "section_1", "title": "Page 1", "description": "", "position": 2},
                ],
                "questions": [],
            }
        )

        with self.assertRaises(SurveyValidationError):
            SurveyService._validate_payload(payload)

    def test_get_analytics_returns_core_reports(self) -> None:
        survey_repository = StubSurveyRepository()
        survey_repository.survey = build_reporting_survey()
        response_repository = StubSurveyResponseRepository()
        response_repository.responses = build_reporting_responses()
        service = SurveyService(
            survey_repository=survey_repository,  # type: ignore[arg-type]
            survey_response_repository=response_repository,  # type: ignore[arg-type]
        )

        analytics = service.get_analytics("survey-reporting")

        self.assertEqual(2, analytics.total_responses)
        self.assertEqual("I don't have enough time", analytics.core_reports.overview.top_blocker)
        self.assertEqual("Automatic weekly meal planning", analytics.core_reports.overview.top_feature)
        self.assertEqual("Save money", analytics.core_reports.overview.dominant_theme)
        self.assertEqual("50%", analytics.core_reports.meal_planning.metrics[0].value)
        self.assertEqual("3.0/5", analytics.core_reports.meal_planning.metrics[1].value)
        self.assertEqual("100%", analytics.core_reports.feature_demand.metrics[0].detail.split(" ")[0])
        self.assertEqual("100%", analytics.core_reports.open_feedback.metrics[1].value)
        self.assertEqual("50%", analytics.core_reports.feature_demand.metrics[2].value)
        self.assertEqual("Impulse purchases", analytics.core_reports.budget_risk.overspend_causes[0].label)

    def test_get_analytics_resolves_template_questions_without_fixed_ids(self) -> None:
        custom_ids = {
            "planning_frequency": "custom-plan-frequency",
            "planning_difficulty": "custom-plan-difficulty",
            "planning_challenge": "custom-plan-challenge",
            "household_size": "custom-household-size",
            "budget_cadence": "custom-budget-cadence",
            "budget_overrun_frequency": "custom-budget-overrun",
            "overspend_causes": "custom-overspend-causes",
            "feature_demand": "custom-feature-demand",
            "total_time_spent": "custom-total-time",
            "open_feedback": "custom-open-feedback",
        }
        survey_repository = StubSurveyRepository()
        survey_repository.survey = build_reporting_survey(question_ids=custom_ids)
        response_repository = StubSurveyResponseRepository()
        response_repository.responses = build_reporting_responses(question_ids=custom_ids)
        service = SurveyService(
            survey_repository=survey_repository,  # type: ignore[arg-type]
            survey_response_repository=response_repository,  # type: ignore[arg-type]
        )

        analytics = service.get_analytics("survey-reporting")

        self.assertEqual("I don't have enough time", analytics.core_reports.overview.top_blocker)
        self.assertEqual("Automatic weekly meal planning", analytics.core_reports.overview.top_feature)
        self.assertEqual("Save money", analytics.core_reports.overview.dominant_theme)
        self.assertEqual("50%", analytics.core_reports.meal_planning.metrics[0].value)

    def test_get_analytics_prefers_explicit_report_keys(self) -> None:
        survey_repository = StubSurveyRepository()
        survey_repository.survey = build_reporting_survey(include_report_keys=True, generic_titles=True)
        response_repository = StubSurveyResponseRepository()
        response_repository.responses = build_reporting_responses()
        service = SurveyService(
            survey_repository=survey_repository,  # type: ignore[arg-type]
            survey_response_repository=response_repository,  # type: ignore[arg-type]
        )

        analytics = service.get_analytics("survey-reporting")

        self.assertEqual("I don't have enough time", analytics.core_reports.overview.top_blocker)
        self.assertEqual("Automatic weekly meal planning", analytics.core_reports.overview.top_feature)
        self.assertEqual("Save money", analytics.core_reports.overview.dominant_theme)


if __name__ == "__main__":
    unittest.main()
