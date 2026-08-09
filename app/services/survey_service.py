from __future__ import annotations

import csv
import io
import re
from dataclasses import asdict
from hashlib import sha256
from typing import Any

from app.data.survey_templates import get_admin_survey_templates
from app.models.survey import Survey, SurveyQuestion, SurveyQuestionType, SurveyReportKey, SurveyResponse, SurveyStatus
from app.models.user import User
from app.repositories.survey_repository import SurveyRepository
from app.repositories.survey_response_repository import SurveyResponseRepository
from app.schemas.survey import (
    AdminSurveyListResponse,
    AdminSurveyResponse,
    AdminSurveyResponseListResponse,
    AdminSurveyTemplateListResponse,
    PublicSurveyResponse,
    SurveyAnalyticsResponse,
    SurveyAnswerResponse,
    SurveyBudgetRiskReportResponse,
    SurveyCoreReportOverviewResponse,
    SurveyCoreReportsResponse,
    SurveyFeedbackSnippetResponse,
    SurveyFeatureDemandReportResponse,
    SurveyMealPlanningReportResponse,
    SurveyOpenFeedbackReportResponse,
    SurveyQuestionAnalyticsResponse,
    SurveyQuestionConfigResponse,
    SurveyQuestionOptionResponse,
    SurveyQuestionResponse,
    SurveyQuestionValidationResponse,
    SurveyRankedItemResponse,
    SurveyReportMetricResponse,
    SurveyRespondentResponse,
    SurveyResponseBase,
    SurveySectionResponse,
    SurveySegmentDemandResponse,
    SurveySettingsResponse,
    SurveySubmissionResponse,
    SurveyThemeResponse,
    SurveyThemeShareResponse,
    SurveyResponseSubmissionRequest,
    SurveyUpsertRequest,
)


class SurveyNotFoundError(Exception):
    pass


class SurveySlugConflictError(Exception):
    pass


class SurveyValidationError(Exception):
    pass


class SurveyResponseConflictError(Exception):
    pass


class SurveyAccessError(Exception):
    pass


FEEDBACK_THEMES = [
    (
        "Save money",
        ["save", "cheap", "cheaper", "expensive", "budget", "cost", "money", "afford", "price"],
    ),
    (
        "Save time",
        ["time", "quick", "faster", "busy", "easier", "convenient", "speed", "hours"],
    ),
    (
        "Easier planning",
        ["plan", "planning", "meal plan", "cook", "ideas", "decide", "recipes", "inspiration"],
    ),
    (
        "Reduce waste",
        ["waste", "leftover", "leftovers", "spoil", "expired", "use what i have", "ingredients"],
    ),
    (
        "Shared coordination",
        ["share", "shared", "family", "flatmate", "roommate", "household", "split", "paid", "coordinate"],
    ),
]

REPORT_QUESTION_KEYS = (
    "planning_frequency",
    "planning_difficulty",
    "planning_challenge",
    "household_size",
    "budget_cadence",
    "budget_overrun_frequency",
    "overspend_causes",
    "feature_demand",
    "total_time_spent",
    "open_feedback",
)


class SurveyService:
    def __init__(
        self,
        survey_repository: SurveyRepository,
        survey_response_repository: SurveyResponseRepository,
    ) -> None:
        self._survey_repository = survey_repository
        self._survey_response_repository = survey_response_repository

    def list_surveys(self, *, page: int, page_size: int, search: str | None = None) -> AdminSurveyListResponse:
        items, total = self._survey_repository.list_surveys(page=page, page_size=page_size, search=search)
        return AdminSurveyListResponse(
            items=[self._to_admin_response(item) for item in items],
            total=total,
            page=page,
            page_size=page_size,
        )

    def list_templates(self) -> AdminSurveyTemplateListResponse:
        return get_admin_survey_templates()

    def get_admin_survey(self, survey_id: str) -> AdminSurveyResponse:
        survey = self._survey_repository.get_by_id(survey_id=survey_id)
        if survey is None:
            raise SurveyNotFoundError
        return self._to_admin_response(survey)

    def create_survey(self, *, owner_user_id: str, payload: SurveyUpsertRequest) -> AdminSurveyResponse:
        self._ensure_unique_slug(slug=payload.slug)
        self._validate_payload(payload)
        survey = self._survey_repository.create_survey(
            owner_user_id=owner_user_id,
            slug=payload.slug,
            title=payload.title,
            description=payload.description,
            settings=payload.settings.model_dump(),
            theme=payload.theme.model_dump(),
            sections=[section.model_dump() for section in payload.sections],
            questions=[question.model_dump() for question in payload.questions],
        )
        return self._to_admin_response(survey)

    def update_survey(self, *, survey_id: str, payload: SurveyUpsertRequest) -> AdminSurveyResponse:
        existing = self._survey_repository.get_by_id(survey_id=survey_id)
        if existing is None:
            raise SurveyNotFoundError
        self._ensure_unique_slug(slug=payload.slug, current_survey_id=survey_id)
        self._validate_payload(payload)
        survey = self._survey_repository.update_survey(
            survey_id=survey_id,
            slug=payload.slug,
            title=payload.title,
            description=payload.description,
            settings=payload.settings.model_dump(),
            theme=payload.theme.model_dump(),
            sections=[section.model_dump() for section in payload.sections],
            questions=[question.model_dump() for question in payload.questions],
        )
        if survey is None:
            raise SurveyNotFoundError
        return self._to_admin_response(survey)

    def delete_survey(self, survey_id: str) -> None:
        deleted = self._survey_repository.delete_survey(survey_id=survey_id)
        if not deleted:
            raise SurveyNotFoundError

    def publish_survey(self, survey_id: str) -> AdminSurveyResponse:
        survey = self._survey_repository.get_by_id(survey_id=survey_id)
        if survey is None:
            raise SurveyNotFoundError
        if not survey.questions:
            raise SurveyValidationError("A survey must contain at least one question before publishing.")
        updated = self._survey_repository.publish_survey(survey_id=survey_id)
        if updated is None:
            raise SurveyNotFoundError
        return self._to_admin_response(updated)

    def close_survey(self, survey_id: str) -> AdminSurveyResponse:
        updated = self._survey_repository.close_survey(survey_id=survey_id)
        if updated is None:
            raise SurveyNotFoundError
        return self._to_admin_response(updated)

    def get_public_survey(self, slug: str) -> PublicSurveyResponse:
        survey = self._survey_repository.get_by_slug(slug=slug)
        if survey is None:
            raise SurveyNotFoundError
        if not survey.settings.is_public:
            raise SurveyAccessError("This survey is not publicly available.")
        if survey.status == SurveyStatus.DRAFT:
            raise SurveyAccessError("This survey is not published yet.")
        return self._to_public_response(survey)

    def submit_response(
        self,
        *,
        slug: str,
        payload: SurveyResponseSubmissionRequest,
        current_user: User | None,
        request_ip: str | None,
        user_agent: str | None,
    ) -> SurveySubmissionResponse:
        survey = self._survey_repository.get_by_slug(slug=slug)
        if survey is None:
            raise SurveyNotFoundError
        normalized_email = (
            payload.respondent_email.lower()
            if payload.respondent_email
            else current_user.email.lower() if current_user is not None else None
        )
        respondent_name = payload.respondent_name or (current_user.name if current_user is not None else None)
        self._ensure_can_accept_responses(
            survey=survey,
            current_user=current_user,
            email=normalized_email,
        )

        answer_map = {answer.question_id: answer.value for answer in payload.answers}
        normalized_answers: list[dict[str, Any]] = []
        for question in sorted(survey.questions, key=lambda item: item.position):
            value = answer_map.get(question.id)
            normalized_value = self._validate_answer(question=question, value=value)
            if normalized_value is None and not question.required:
                continue
            normalized_answers.append(
                {
                    "question_id": question.id,
                    "type": question.type.value,
                    "value": normalized_value,
                }
            )

        created = self._survey_response_repository.create_response(
            survey_id=survey.id,
            survey_slug=survey.slug,
            survey_version=survey.version,
            respondent={
                "user_id": current_user.id if current_user is not None else None,
                "email": normalized_email,
                "name": respondent_name,
                "ip_hash": self._hash_ip(request_ip),
                "user_agent": user_agent,
            },
            answers=normalized_answers,
        )
        self._survey_repository.record_response(survey_id=survey.id, submitted_at=created.submitted_at)
        return self._to_submission_response(created)

    def list_responses(self, survey_id: str) -> AdminSurveyResponseListResponse:
        survey = self._survey_repository.get_by_id(survey_id=survey_id)
        if survey is None:
            raise SurveyNotFoundError
        items, total = self._survey_response_repository.list_responses(survey_id=survey_id)
        return AdminSurveyResponseListResponse(
            items=[self._to_submission_response(item) for item in items],
            total=total,
            survey_id=survey_id,
        )

    def get_response(self, *, survey_id: str, response_id: str) -> SurveySubmissionResponse:
        response = self._survey_response_repository.get_by_id(survey_id=survey_id, response_id=response_id)
        if response is None:
            raise SurveyNotFoundError
        return self._to_submission_response(response)

    def get_analytics(self, survey_id: str) -> SurveyAnalyticsResponse:
        survey = self._survey_repository.get_by_id(survey_id=survey_id)
        if survey is None:
            raise SurveyNotFoundError
        responses, total = self._survey_response_repository.list_responses(survey_id=survey_id, limit=1000)

        question_stats: list[SurveyQuestionAnalyticsResponse] = []
        for question in survey.questions:
            relevant_answers = [
                answer.value
                for response in responses
                for answer in response.answers
                if answer.question_id == question.id
            ]
            choice_counts: dict[str, int] = {}
            if question.type in {
                SurveyQuestionType.SINGLE_CHOICE,
                SurveyQuestionType.MULTIPLE_CHOICE,
                SurveyQuestionType.DROPDOWN,
            }:
                for answer_value in relevant_answers:
                    if isinstance(answer_value, list):
                        for entry in answer_value:
                            key = str(entry)
                            choice_counts[key] = choice_counts.get(key, 0) + 1
                    else:
                        key = str(answer_value)
                        choice_counts[key] = choice_counts.get(key, 0) + 1
            question_stats.append(
                SurveyQuestionAnalyticsResponse(
                    question_id=question.id,
                    title=question.title,
                    type=question.type,
                    response_count=len(relevant_answers),
                    choice_counts=choice_counts,
                )
            )

        return SurveyAnalyticsResponse(
            survey_id=survey_id,
            total_responses=total,
            latest_response_at=responses[0].submitted_at if responses else None,
            question_stats=question_stats,
            core_reports=self._build_core_reports(survey=survey, responses=responses),
        )

    def _build_core_reports(
        self,
        *,
        survey: Survey,
        responses: list[SurveyResponse],
    ) -> SurveyCoreReportsResponse:
        response_count = len(responses)
        has_responses = response_count > 0
        resolved_questions = self._resolve_report_questions(survey)

        planning_frequency_question = resolved_questions["planning_frequency"]
        planning_difficulty_question = resolved_questions["planning_difficulty"]
        planning_challenge_question = resolved_questions["planning_challenge"]
        household_size_question = resolved_questions["household_size"]
        budget_cadence_question = resolved_questions["budget_cadence"]
        budget_overrun_question = resolved_questions["budget_overrun_frequency"]
        overspend_cause_question = resolved_questions["overspend_causes"]
        feature_demand_question = resolved_questions["feature_demand"]
        total_time_question = resolved_questions["total_time_spent"]
        open_feedback_question = resolved_questions["open_feedback"]

        planning_frequency = self._count_single_choice(
            question=planning_frequency_question,
            responses=responses,
            question_id=planning_frequency_question.id if planning_frequency_question is not None else None,
        )
        top_planning_frequency = self._top_ranked_item(planning_frequency)

        planning_challenges = self._sorted_ranked_items(
            self._count_single_choice(
                question=planning_challenge_question,
                responses=responses,
                question_id=planning_challenge_question.id if planning_challenge_question is not None else None,
            )
        )
        household_segments = self._sorted_ranked_items(
            self._count_single_choice(
                question=household_size_question,
                responses=responses,
                question_id=household_size_question.id if household_size_question is not None else None,
            )
        )

        budget_cadence = self._count_single_choice(
            question=budget_cadence_question,
            responses=responses,
            question_id=budget_cadence_question.id if budget_cadence_question is not None else None,
        )
        overspend_frequency = self._count_single_choice(
            question=budget_overrun_question,
            responses=responses,
            question_id=budget_overrun_question.id if budget_overrun_question is not None else None,
        )
        overspend_causes = self._count_multi_choice(
            question=overspend_cause_question,
            responses=responses,
            question_id=overspend_cause_question.id if overspend_cause_question is not None else None,
        )

        feature_demand = self._count_multi_choice(
            question=feature_demand_question,
            responses=responses,
            question_id=feature_demand_question.id if feature_demand_question is not None else None,
        )
        time_bands = self._count_single_choice(
            question=total_time_question,
            responses=responses,
            question_id=total_time_question.id if total_time_question is not None else None,
        )

        planning_difficulty_average = self._average_number(
            responses=responses,
            question_id=planning_difficulty_question.id if planning_difficulty_question is not None else None,
        )
        budget_setter_count = self._count_matching_responses(
            responses=responses,
            question_id=budget_cadence_question.id if budget_cadence_question is not None else None,
            matches=lambda value: value in {"weekly", "monthly"},
        )
        overspend_risk_count = self._count_matching_responses(
            responses=responses,
            question_id=budget_overrun_question.id if budget_overrun_question is not None else None,
            matches=lambda value: value in {"almost_every_week", "sometimes"},
        )
        no_tracking_count = self._count_matching_responses(
            responses=responses,
            question_id=budget_overrun_question.id if budget_overrun_question is not None else None,
            matches=lambda value: value == "dont_track",
        )
        repeat_meal_fatigue_count = self._count_matching_responses(
            responses=responses,
            question_id=planning_challenge_question.id if planning_challenge_question is not None else None,
            matches=lambda value: value == "meal_repetition",
        )
        shared_list_demand_count = sum(
            1
            for response in responses
            if "shared_lists"
            in self._as_string_list(
                self._get_response_answer(response, feature_demand_question.id if feature_demand_question is not None else None)
            )
        )
        cost_splitting_demand_count = sum(
            1
            for response in responses
            if "automatic_cost_splitting"
            in self._as_string_list(
                self._get_response_answer(response, feature_demand_question.id if feature_demand_question is not None else None)
            )
        )

        feature_selections = sum(item.count for item in feature_demand)
        top_feature = self._top_ranked_item(feature_demand)
        top_blocker = self._top_ranked_item(planning_challenges)

        feedback = self._count_feedback(
            responses=responses,
            question_id=open_feedback_question.id if open_feedback_question is not None else None,
        )
        dominant_theme = self._top_theme_share(feedback["themes"])

        segment_demand: list[SurveySegmentDemandResponse] = []
        if household_size_question is not None:
            for option in household_size_question.options:
                segment_responses = [
                    response
                    for response in responses
                    if self._as_string(
                        self._get_response_answer(response, household_size_question.id if household_size_question is not None else None)
                    )
                    == option.value
                ]
                if not segment_responses:
                    continue
                segment_features = self._count_multi_choice(
                    question=feature_demand_question,
                    responses=segment_responses,
                    question_id=feature_demand_question.id if feature_demand_question is not None else None,
                )
                segment_top_feature = self._top_ranked_item(segment_features)
                segment_demand.append(
                    SurveySegmentDemandResponse(
                        segment=option.label,
                        top_feature=segment_top_feature.label if segment_top_feature is not None else "No feature data",
                        top_feature_percent=segment_top_feature.percent if segment_top_feature is not None else 0,
                        response_count=len(segment_responses),
                    )
                )

        return SurveyCoreReportsResponse(
            has_responses=has_responses,
            response_count=response_count,
            overview=SurveyCoreReportOverviewResponse(
                top_blocker=top_blocker.label if top_blocker is not None else "No response data",
                top_feature=top_feature.label if top_feature is not None else "No response data",
                dominant_theme=dominant_theme.label if dominant_theme is not None else "No response data",
                top_issue_share=top_blocker.percent if top_blocker is not None else 0,
                feature_demand_share=top_feature.percent if top_feature is not None else 0,
                theme_share=dominant_theme.percent if dominant_theme is not None else 0,
            ),
            meal_planning=SurveyMealPlanningReportResponse(
                metrics=[
                    SurveyReportMetricResponse(
                        label="Planning frequency",
                        value=f"{top_planning_frequency.percent}%" if top_planning_frequency is not None else "--",
                        detail=(
                            f"{top_planning_frequency.label} is the leading habit"
                            if top_planning_frequency is not None
                            else "No planning responses yet"
                        ),
                    ),
                    SurveyReportMetricResponse(
                        label="Difficulty score",
                        value=f"{planning_difficulty_average:.1f}/5" if planning_difficulty_average is not None else "--",
                        detail=(
                            "Average difficulty across all respondents"
                            if planning_difficulty_average is not None
                            else "No difficulty responses yet"
                        ),
                    ),
                    SurveyReportMetricResponse(
                        label="Top blocker",
                        value=top_blocker.label if top_blocker is not None else "--",
                        detail=(
                            f"{top_blocker.percent}% of respondents selected this issue"
                            if top_blocker is not None
                            else "No blocker responses yet"
                        ),
                    ),
                    SurveyReportMetricResponse(
                        label="Repeat meal fatigue",
                        value=f"{self._percent(repeat_meal_fatigue_count, response_count)}%" if has_responses else "--",
                        detail="Respondents citing meal repetition as the main pain point",
                    ),
                ],
                frequency=planning_frequency,
                challenges=planning_challenges,
                segments=household_segments,
            ),
            budget_risk=SurveyBudgetRiskReportResponse(
                metrics=[
                    SurveyReportMetricResponse(
                        label="Budget setters",
                        value=f"{self._percent(budget_setter_count, response_count)}%" if has_responses else "--",
                        detail="Respondents who set a weekly or monthly grocery budget",
                    ),
                    SurveyReportMetricResponse(
                        label="Overspend risk",
                        value=f"{self._percent(overspend_risk_count, response_count)}%" if has_responses else "--",
                        detail="Respondents who overspend almost every week or sometimes",
                    ),
                    SurveyReportMetricResponse(
                        label="Top overspend cause",
                        value=overspend_causes[0].label if overspend_causes else "--",
                        detail=(
                            f"{overspend_causes[0].percent}% of respondents mention this"
                            if overspend_causes
                            else "No overspend cause data yet"
                        ),
                    ),
                    SurveyReportMetricResponse(
                        label="Spend not tracked",
                        value=f"{self._percent(no_tracking_count, response_count)}%" if has_responses else "--",
                        detail="Respondents who do not track their grocery spend",
                    ),
                ],
                cadence=budget_cadence,
                overspend_frequency=overspend_frequency,
                overspend_causes=overspend_causes,
            ),
            feature_demand=SurveyFeatureDemandReportResponse(
                metrics=[
                    SurveyReportMetricResponse(
                        label="Top requested feature",
                        value=top_feature.label if top_feature is not None else "--",
                        detail=(
                            f"{top_feature.percent}% of respondents selected this"
                            if top_feature is not None
                            else "No feature demand data yet"
                        ),
                    ),
                    SurveyReportMetricResponse(
                        label="Demand concentration",
                        value=(
                            f"{self._percent(sum(item.count for item in feature_demand[:3]), feature_selections)}%"
                            if feature_selections > 0
                            else "--"
                        ),
                        detail="Share of all feature selections captured by the top three ideas",
                    ),
                    SurveyReportMetricResponse(
                        label="Shared-list demand",
                        value=f"{self._percent(shared_list_demand_count, response_count)}%" if has_responses else "--",
                        detail="Respondents who want shared grocery lists",
                    ),
                    SurveyReportMetricResponse(
                        label="Cost-splitting demand",
                        value=f"{self._percent(cost_splitting_demand_count, response_count)}%" if has_responses else "--",
                        detail="Respondents who want automatic cost splitting",
                    ),
                ],
                features=feature_demand,
                time_bands=time_bands,
                segment_demand=segment_demand,
            ),
            open_feedback=SurveyOpenFeedbackReportResponse(
                metrics=[
                    SurveyReportMetricResponse(
                        label="Top theme",
                        value=dominant_theme.label if dominant_theme is not None else "--",
                        detail=(
                            f"{dominant_theme.percent}% of text responses include this theme"
                            if dominant_theme is not None
                            else "No text feedback yet"
                        ),
                    ),
                    SurveyReportMetricResponse(
                        label="Cost-saving mentions",
                        value=self._theme_percent(feedback["themes"], "Save money"),
                        detail="Text responses mentioning affordability, budget, or price pressure",
                    ),
                    SurveyReportMetricResponse(
                        label="Time-saving mentions",
                        value=self._theme_percent(feedback["themes"], "Save time"),
                        detail="Text responses asking for faster planning or shopping",
                    ),
                    SurveyReportMetricResponse(
                        label="Coordination mentions",
                        value=self._theme_percent(feedback["themes"], "Shared coordination"),
                        detail="Text responses about family or flatmate coordination",
                    ),
                ],
                themes=feedback["themes"],
                sentiment=feedback["sentiment"],
                urgency=feedback["urgency"],
                snippets=feedback["snippets"],
            ),
        )

    @classmethod
    def _resolve_report_questions(cls, survey: Survey) -> dict[str, SurveyQuestion | None]:
        resolved: dict[str, SurveyQuestion | None] = {key: None for key in REPORT_QUESTION_KEYS}
        remaining = list(survey.questions)

        matchers = {
            "planning_frequency": lambda question: question.type == SurveyQuestionType.SINGLE_CHOICE
            and cls._has_any_option_value(question, "every_week", "few_days"),
            "planning_difficulty": lambda question: question.type == SurveyQuestionType.LINEAR_SCALE
            and cls._matches_title(question, "difficult", "plan", "meal"),
            "planning_challenge": lambda question: question.type == SurveyQuestionType.SINGLE_CHOICE
            and cls._has_any_option_value(question, "not_enough_time", "meal_repetition"),
            "household_size": lambda question: question.type == SurveyQuestionType.SINGLE_CHOICE
            and cls._has_any_option_value(question, "two", "three_to_four"),
            "budget_cadence": lambda question: question.type == SurveyQuestionType.SINGLE_CHOICE
            and cls._has_any_option_value(question, "weekly", "monthly"),
            "budget_overrun_frequency": lambda question: question.type == SurveyQuestionType.SINGLE_CHOICE
            and cls._has_any_option_value(question, "almost_every_week", "dont_track"),
            "overspend_causes": lambda question: question.type == SurveyQuestionType.MULTIPLE_CHOICE
            and cls._has_any_option_value(question, "impulse_purchases", "poor_meal_planning"),
            "feature_demand": lambda question: question.type == SurveyQuestionType.MULTIPLE_CHOICE
            and cls._has_any_option_value(question, "automatic_meal_planning", "shared_lists"),
            "total_time_spent": lambda question: question.type == SurveyQuestionType.SINGLE_CHOICE
            and cls._has_any_option_value(question, "1_to_2_hours", "over_3_hours"),
            "open_feedback": lambda question: question.type in {SurveyQuestionType.PARAGRAPH, SurveyQuestionType.SHORT_TEXT}
            and (
                cls._matches_title(question, "improve")
                or cls._matches_title(question, "improvement")
                or cls._matches_title(question, "one thing")
            ),
        }

        for key in REPORT_QUESTION_KEYS:
            for question in list(remaining):
                if question.report_key == SurveyReportKey(key):
                    resolved[key] = question
                    remaining.remove(question)
                    break
            if resolved[key] is not None:
                continue
            for question in list(remaining):
                if matchers[key](question):
                    resolved[key] = question
                    remaining.remove(question)
                    break

        return resolved

    @staticmethod
    def _get_response_answer(response: SurveyResponse, question_id: str | None) -> Any:
        if question_id is None:
            return None
        for answer in response.answers:
            if answer.question_id == question_id:
                return answer.value
        return None

    @staticmethod
    def _as_string(value: Any) -> str | None:
        if not isinstance(value, str):
            return None
        normalized = value.strip()
        return normalized or None

    @classmethod
    def _as_string_list(cls, value: Any) -> list[str]:
        if isinstance(value, list):
            return [str(entry).strip() for entry in value if str(entry).strip()]
        normalized = cls._as_string(value)
        return [normalized] if normalized is not None else []

    @staticmethod
    def _as_number(value: Any) -> float | None:
        if isinstance(value, (int, float)) and not isinstance(value, bool):
            return float(value)
        if isinstance(value, str):
            try:
                return float(value)
            except ValueError:
                return None
        return None

    @staticmethod
    def _percent(count: int, total: int) -> int:
        if total <= 0:
            return 0
        return round((count / total) * 100)

    @classmethod
    def _count_single_choice(
        cls,
        *,
        question: SurveyQuestion | None,
        responses: list[SurveyResponse],
        question_id: str | None,
    ) -> list[SurveyRankedItemResponse]:
        if question is None or question_id is None:
            return []

        counts: dict[str, int] = {}
        for response in responses:
            answer = cls._as_string(cls._get_response_answer(response, question_id))
            if answer is None:
                continue
            counts[answer] = counts.get(answer, 0) + 1

        answered_count = sum(counts.values())
        return [
            SurveyRankedItemResponse(
                label=option.label,
                count=counts.get(option.value, 0),
                percent=cls._percent(counts.get(option.value, 0), answered_count),
            )
            for option in question.options
        ]

    @classmethod
    def _count_multi_choice(
        cls,
        *,
        question: SurveyQuestion | None,
        responses: list[SurveyResponse],
        question_id: str | None,
    ) -> list[SurveyRankedItemResponse]:
        if question is None or question_id is None:
            return []

        counts: dict[str, int] = {}
        answered_count = 0
        for response in responses:
            answers = cls._as_string_list(cls._get_response_answer(response, question_id))
            if not answers:
                continue
            answered_count += 1
            for answer in answers:
                counts[answer] = counts.get(answer, 0) + 1

        return cls._sorted_ranked_items(
            [
                SurveyRankedItemResponse(
                    label=option.label,
                    count=counts.get(option.value, 0),
                    percent=cls._percent(counts.get(option.value, 0), answered_count),
                )
                for option in question.options
            ]
        )

    @classmethod
    def _average_number(cls, *, responses: list[SurveyResponse], question_id: str | None) -> float | None:
        if question_id is None:
            return None
        values = [
            value
            for value in (
                cls._as_number(cls._get_response_answer(response, question_id))
                for response in responses
            )
            if value is not None
        ]
        if not values:
            return None
        return sum(values) / len(values)

    @classmethod
    def _count_matching_responses(
        cls,
        *,
        responses: list[SurveyResponse],
        question_id: str | None,
        matches: Any,
    ) -> int:
        if question_id is None:
            return 0
        count = 0
        for response in responses:
            answer = cls._as_string(cls._get_response_answer(response, question_id))
            if answer is not None and matches(answer):
                count += 1
        return count

    @staticmethod
    def _sorted_ranked_items(items: list[SurveyRankedItemResponse]) -> list[SurveyRankedItemResponse]:
        return sorted(items, key=lambda item: (-item.count, item.label))

    @staticmethod
    def _top_ranked_item(items: list[SurveyRankedItemResponse]) -> SurveyRankedItemResponse | None:
        return sorted(items, key=lambda item: (-item.count, item.label))[0] if items else None

    @staticmethod
    def _classify_tone(text: str) -> str:
        normalized = text.lower()
        positive_words = ["better", "help", "easier", "improve", "good", "great", "love", "simple"]
        negative_words = ["hard", "difficult", "expensive", "waste", "forget", "chaos", "stress", "annoying"]
        positive_score = sum(1 for word in positive_words if word in normalized)
        negative_score = sum(1 for word in negative_words if word in normalized)
        if negative_score > positive_score:
            return "negative"
        if positive_score > negative_score:
            return "positive"
        return "neutral"

    @staticmethod
    def _classify_urgency(text: str) -> str:
        normalized = text.lower()
        if any(word in normalized for word in ["need", "must", "every", "always", "hard", "difficult", "expensive", "chaos"]):
            return "high"
        if any(word in normalized for word in ["maybe", "sometimes", "could", "would be nice"]):
            return "low"
        return "medium"

    @staticmethod
    def _extract_themes(text: str) -> list[str]:
        normalized = text.lower()
        matches = [
            label
            for label, keywords in FEEDBACK_THEMES
            if any(keyword in normalized for keyword in keywords)
        ]
        return matches or ["Other"]

    @classmethod
    def _count_feedback(cls, *, responses: list[SurveyResponse], question_id: str | None) -> dict[str, Any]:
        if question_id is None:
            return {
                "themes": [],
                "sentiment": [],
                "urgency": [],
                "snippets": [],
            }
        items = [
            value
            for value in (
                cls._as_string(cls._get_response_answer(response, question_id))
                for response in responses
            )
            if value is not None
        ]

        theme_counts: dict[str, int] = {}
        sentiment_counts: dict[str, int] = {}
        urgency_counts: dict[str, int] = {}
        snippets: list[SurveyFeedbackSnippetResponse] = []

        for index, text in enumerate(items):
            tags = cls._extract_themes(text)
            tone = cls._classify_tone(text)
            urgency = cls._classify_urgency(text)

            for tag in tags:
                theme_counts[tag] = theme_counts.get(tag, 0) + 1
            sentiment_counts[tone] = sentiment_counts.get(tone, 0) + 1
            urgency_counts[urgency] = urgency_counts.get(urgency, 0) + 1

            if index < 4:
                snippets.append(
                    SurveyFeedbackSnippetResponse(
                        text=text,
                        tags=tags,
                        tone=tone,
                        urgency=urgency,
                    )
                )

        total = len(items)

        return {
            "themes": cls._theme_shares(theme_counts, total),
            "sentiment": cls._theme_shares(sentiment_counts, total),
            "urgency": cls._theme_shares(urgency_counts, total),
            "snippets": snippets,
        }

    @classmethod
    def _theme_shares(cls, counts: dict[str, int], total: int) -> list[SurveyThemeShareResponse]:
        return sorted(
            [
                SurveyThemeShareResponse(
                    label=label,
                    count=count,
                    percent=cls._percent(count, total),
                )
                for label, count in counts.items()
            ],
            key=lambda item: (-item.count, item.label),
        )

    @staticmethod
    def _top_theme_share(items: list[SurveyThemeShareResponse]) -> SurveyThemeShareResponse | None:
        return sorted(items, key=lambda item: (-item.count, item.label))[0] if items else None

    @staticmethod
    def _theme_percent(items: list[SurveyThemeShareResponse], label: str) -> str:
        for item in items:
            if item.label == label:
                return f"{item.percent}%"
        return "--"

    @staticmethod
    def _normalize_text(value: str) -> str:
        return re.sub(r"[^a-z0-9]+", " ", value.lower()).strip()

    @classmethod
    def _matches_title(cls, question: SurveyQuestion, *needles: str) -> bool:
        haystack = cls._normalize_text(question.title)
        return all(cls._normalize_text(needle) in haystack for needle in needles)

    @staticmethod
    def _has_any_option_value(question: SurveyQuestion, *values: str) -> bool:
        option_values = {option.value for option in question.options}
        return any(value in option_values for value in values)

    def export_responses_csv(self, survey_id: str) -> str:
        survey = self._survey_repository.get_by_id(survey_id=survey_id)
        if survey is None:
            raise SurveyNotFoundError
        responses, _ = self._survey_response_repository.list_responses(survey_id=survey_id, limit=5000)
        buffer = io.StringIO()
        writer = csv.writer(buffer)
        writer.writerow(
            [
                "response_id",
                "submitted_at",
                "respondent_email",
                "respondent_name",
                *[question.title for question in survey.questions],
            ]
        )
        for response in responses:
            answer_map = {answer.question_id: answer.value for answer in response.answers}
            row = [
                response.id,
                response.submitted_at.isoformat(),
                response.respondent.email or "",
                response.respondent.name or "",
            ]
            for question in survey.questions:
                value = answer_map.get(question.id)
                row.append(", ".join(str(item) for item in value) if isinstance(value, list) else ("" if value is None else str(value)))
            writer.writerow(row)
        return buffer.getvalue()

    def _ensure_unique_slug(self, *, slug: str, current_survey_id: str | None = None) -> None:
        existing = self._survey_repository.get_by_slug(slug=slug)
        if existing is None:
            return
        if current_survey_id is not None and existing.id == current_survey_id:
            return
        raise SurveySlugConflictError

    @staticmethod
    def _validate_payload(payload: SurveyUpsertRequest) -> None:
        ordered_sections = sorted(payload.sections, key=lambda item: item.position)
        if ordered_sections[0].position != 1:
            raise SurveyValidationError("Sections must start at position 1.")
        for index, section in enumerate(ordered_sections, start=1):
            if section.position != index:
                raise SurveyValidationError("Section positions must be continuous.")

        grouped_questions: dict[str, list[int]] = {}
        for question in payload.questions:
            grouped_questions.setdefault(question.section_id, []).append(question.position)
        for positions in grouped_questions.values():
            if sorted(positions) != list(range(1, len(positions) + 1)):
                raise SurveyValidationError("Question positions must be continuous within each section.")

    def _ensure_can_accept_responses(
        self,
        *,
        survey: Survey,
        current_user: User | None,
        email: str | None,
    ) -> None:
        if survey.status != SurveyStatus.PUBLISHED or not survey.settings.accepting_responses:
            raise SurveyValidationError("This survey is not accepting responses.")
        if survey.settings.require_auth and current_user is None:
            raise SurveyAccessError("Authentication is required to answer this survey.")
        normalized_email = email.lower() if email else None
        if survey.settings.collect_email and not normalized_email and current_user is None:
            raise SurveyValidationError("Email is required for this survey.")
        if survey.settings.limit_one_response_per_user and current_user is not None:
            if self._survey_response_repository.has_response_for_user(
                survey_id=survey.id,
                user_id=current_user.id,
            ):
                raise SurveyResponseConflictError("You have already submitted a response to this survey.")
        if survey.settings.limit_one_response_per_email and normalized_email:
            if self._survey_response_repository.has_response_for_email(
                survey_id=survey.id,
                email=normalized_email,
            ):
                raise SurveyResponseConflictError("A response has already been submitted for this email.")

    def _validate_answer(self, *, question: SurveyQuestion, value: Any) -> Any:
        if value in (None, ""):
            if question.required:
                raise SurveyValidationError(f"Question '{question.title}' is required.")
            return None

        if question.type in {SurveyQuestionType.SHORT_TEXT, SurveyQuestionType.PARAGRAPH}:
            normalized = str(value).strip()
            self._validate_text_constraints(question=question, value=normalized)
            return normalized
        if question.type == SurveyQuestionType.EMAIL:
            normalized = str(value).strip().lower()
            if not re.fullmatch(r"[^@\s]+@[^@\s]+\.[^@\s]+", normalized):
                raise SurveyValidationError(f"Question '{question.title}' must be a valid email.")
            self._validate_text_constraints(question=question, value=normalized)
            return normalized
        if question.type == SurveyQuestionType.NUMBER:
            try:
                normalized_number = float(value)
            except (TypeError, ValueError) as exc:
                raise SurveyValidationError(f"Question '{question.title}' must be a number.") from exc
            if question.validation.min_value is not None and normalized_number < question.validation.min_value:
                raise SurveyValidationError(f"Question '{question.title}' is below the allowed minimum.")
            if question.validation.max_value is not None and normalized_number > question.validation.max_value:
                raise SurveyValidationError(f"Question '{question.title}' is above the allowed maximum.")
            return normalized_number
        if question.type in {SurveyQuestionType.DATE, SurveyQuestionType.TIME}:
            return str(value).strip()
        if question.type == SurveyQuestionType.LINEAR_SCALE:
            try:
                normalized_scale = int(value)
            except (TypeError, ValueError) as exc:
                raise SurveyValidationError(f"Question '{question.title}' must be a whole number.") from exc
            scale_min = question.config.scale_min if question.config.scale_min is not None else 1
            scale_max = question.config.scale_max if question.config.scale_max is not None else 5
            if normalized_scale < scale_min or normalized_scale > scale_max:
                raise SurveyValidationError(f"Question '{question.title}' is outside the allowed scale.")
            return normalized_scale
        if question.type in {SurveyQuestionType.SINGLE_CHOICE, SurveyQuestionType.DROPDOWN}:
            normalized = str(value).strip()
            allowed = {option.value for option in question.options}
            if normalized not in allowed:
                raise SurveyValidationError(f"Question '{question.title}' contains an invalid selection.")
            return normalized
        if question.type == SurveyQuestionType.MULTIPLE_CHOICE:
            if not isinstance(value, list):
                raise SurveyValidationError(f"Question '{question.title}' must be a list of selections.")
            normalized = [str(item).strip() for item in value if str(item).strip()]
            allowed = {option.value for option in question.options}
            if any(item not in allowed for item in normalized):
                raise SurveyValidationError(f"Question '{question.title}' contains an invalid selection.")
            if question.required and not normalized:
                raise SurveyValidationError(f"Question '{question.title}' is required.")
            if question.validation.max_selections is not None and len(normalized) > question.validation.max_selections:
                raise SurveyValidationError(f"Question '{question.title}' exceeds the maximum selections.")
            return normalized
        return value

    @staticmethod
    def _validate_text_constraints(*, question: SurveyQuestion, value: str) -> None:
        if question.validation.min_length is not None and len(value) < question.validation.min_length:
            raise SurveyValidationError(f"Question '{question.title}' is shorter than the allowed minimum.")
        if question.validation.max_length is not None and len(value) > question.validation.max_length:
            raise SurveyValidationError(f"Question '{question.title}' is longer than the allowed maximum.")
        if question.validation.regex is not None and not re.fullmatch(question.validation.regex, value):
            raise SurveyValidationError(f"Question '{question.title}' does not match the expected format.")

    @staticmethod
    def _hash_ip(request_ip: str | None) -> str | None:
        if not request_ip:
            return None
        return sha256(request_ip.encode("utf-8")).hexdigest()

    def _to_admin_response(self, survey: Survey) -> AdminSurveyResponse:
        base = self._to_base_response(survey)
        return AdminSurveyResponse(**base.model_dump(), owner_user_id=survey.owner_user_id)

    def _to_public_response(self, survey: Survey) -> PublicSurveyResponse:
        return PublicSurveyResponse(**self._to_base_response(survey).model_dump())

    @staticmethod
    def _to_base_response(survey: Survey) -> SurveyResponseBase:
        return SurveyResponseBase(
            id=survey.id,
            slug=survey.slug,
            title=survey.title,
            description=survey.description,
            status=survey.status,
            settings=SurveySettingsResponse(**asdict(survey.settings)),
            theme=SurveyThemeResponse(**asdict(survey.theme)),
            sections=[SurveySectionResponse(**asdict(section)) for section in survey.sections],
            questions=[
                SurveyQuestionResponse(
                    id=question.id,
                    section_id=question.section_id,
                    position=question.position,
                    type=question.type,
                    report_key=question.report_key,
                    title=question.title,
                    description=question.description,
                    required=question.required,
                    options=[SurveyQuestionOptionResponse(**asdict(option)) for option in question.options],
                    validation=SurveyQuestionValidationResponse(**asdict(question.validation)),
                    config=SurveyQuestionConfigResponse(**asdict(question.config)),
                )
                for question in survey.questions
            ],
            version=survey.version,
            response_count=survey.response_count,
            published_at=survey.published_at,
            closed_at=survey.closed_at,
            last_response_at=survey.last_response_at,
            created_at=survey.created_at,
            updated_at=survey.updated_at,
        )

    @staticmethod
    def _to_submission_response(response: SurveyResponse) -> SurveySubmissionResponse:
        return SurveySubmissionResponse(
            id=response.id,
            survey_id=response.survey_id,
            survey_slug=response.survey_slug,
            survey_version=response.survey_version,
            respondent=SurveyRespondentResponse(
                user_id=response.respondent.user_id,
                email=response.respondent.email,
                name=response.respondent.name,
                user_agent=response.respondent.user_agent,
            ),
            answers=[
                SurveyAnswerResponse(
                    question_id=answer.question_id,
                    type=answer.type,
                    value=answer.value,
                )
                for answer in response.answers
            ],
            submitted_at=response.submitted_at,
            created_at=response.created_at,
        )
