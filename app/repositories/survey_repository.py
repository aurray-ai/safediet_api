from __future__ import annotations

from datetime import datetime, timezone
from typing import Any
from uuid import uuid4

from pymongo import DESCENDING
from pymongo.collection import Collection

from app.models.survey import (
    Survey,
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


class SurveyRepository:
    def __init__(self, collection: Collection[dict[str, Any]]) -> None:
        self._collection = collection

    def list_surveys(self, *, page: int, page_size: int, search: str | None = None) -> tuple[list[Survey], int]:
        query: dict[str, Any] = {}
        if search:
            normalized = search.strip()
            query["$or"] = [
                {"title": {"$regex": normalized, "$options": "i"}},
                {"description": {"$regex": normalized, "$options": "i"}},
                {"slug": {"$regex": normalized, "$options": "i"}},
            ]

        total = self._collection.count_documents(query)
        documents = (
            self._collection.find(query)
            .sort([("updated_at", DESCENDING), ("title", 1)])
            .skip((page - 1) * page_size)
            .limit(page_size)
        )
        return [self._to_model(document) for document in documents], total

    def get_by_id(self, *, survey_id: str) -> Survey | None:
        document = self._collection.find_one({"_id": survey_id})
        return None if document is None else self._to_model(document)

    def get_by_slug(self, *, slug: str) -> Survey | None:
        document = self._collection.find_one({"slug": slug})
        return None if document is None else self._to_model(document)

    def create_survey(
        self,
        *,
        owner_user_id: str,
        slug: str,
        title: str,
        description: str,
        settings: dict[str, Any],
        theme: dict[str, Any],
        sections: list[dict[str, Any]],
        questions: list[dict[str, Any]],
    ) -> Survey:
        now = datetime.now(timezone.utc)
        document = {
            "_id": uuid4().hex,
            "owner_user_id": owner_user_id,
            "slug": slug,
            "title": title,
            "description": description,
            "status": SurveyStatus.DRAFT.value,
            "settings": settings,
            "theme": theme,
            "sections": sections,
            "questions": questions,
            "version": 1,
            "response_count": 0,
            "published_at": None,
            "closed_at": None,
            "last_response_at": None,
            "created_at": now,
            "updated_at": now,
        }
        self._collection.insert_one(document)
        return self._to_model(document)

    def update_survey(
        self,
        *,
        survey_id: str,
        slug: str,
        title: str,
        description: str,
        settings: dict[str, Any],
        theme: dict[str, Any],
        sections: list[dict[str, Any]],
        questions: list[dict[str, Any]],
    ) -> Survey | None:
        self._collection.update_one(
            {"_id": survey_id},
            {
                "$set": {
                    "slug": slug,
                    "title": title,
                    "description": description,
                    "settings": settings,
                    "theme": theme,
                    "sections": sections,
                    "questions": questions,
                    "updated_at": datetime.now(timezone.utc),
                }
            },
        )
        return self.get_by_id(survey_id=survey_id)

    def delete_survey(self, *, survey_id: str) -> bool:
        result = self._collection.delete_one({"_id": survey_id})
        return result.deleted_count > 0

    def publish_survey(self, *, survey_id: str) -> Survey | None:
        now = datetime.now(timezone.utc)
        self._collection.update_one(
            {"_id": survey_id},
            {
                "$set": {
                    "status": SurveyStatus.PUBLISHED.value,
                    "published_at": now,
                    "closed_at": None,
                    "settings.accepting_responses": True,
                    "updated_at": now,
                }
            },
        )
        return self.get_by_id(survey_id=survey_id)

    def close_survey(self, *, survey_id: str) -> Survey | None:
        now = datetime.now(timezone.utc)
        self._collection.update_one(
            {"_id": survey_id},
            {
                "$set": {
                    "status": SurveyStatus.CLOSED.value,
                    "closed_at": now,
                    "settings.accepting_responses": False,
                    "updated_at": now,
                }
            },
        )
        return self.get_by_id(survey_id=survey_id)

    def record_response(self, *, survey_id: str, submitted_at: datetime) -> None:
        self._collection.update_one(
            {"_id": survey_id},
            {
                "$inc": {"response_count": 1},
                "$set": {
                    "last_response_at": submitted_at,
                    "updated_at": datetime.now(timezone.utc),
                },
            },
        )

    @staticmethod
    def _to_model(document: dict[str, Any]) -> Survey:
        return Survey(
            id=str(document["_id"]),
            slug=str(document.get("slug") or ""),
            title=str(document.get("title") or ""),
            description=str(document.get("description") or ""),
            status=SurveyStatus(str(document.get("status") or SurveyStatus.DRAFT.value)),
            owner_user_id=str(document.get("owner_user_id") or ""),
            settings=SurveySettings(**dict(document.get("settings") or {})),
            theme=SurveyTheme(**dict(document.get("theme") or {})),
            sections=[
                SurveySection(
                    id=str(section.get("id") or ""),
                    title=str(section.get("title") or ""),
                    description=str(section.get("description") or ""),
                    position=int(section.get("position") or 1),
                )
                for section in list(document.get("sections") or [])
            ],
            questions=[
                SurveyQuestion(
                    id=str(question.get("id") or ""),
                    section_id=str(question.get("section_id") or ""),
                    position=int(question.get("position") or 1),
                    type=SurveyQuestionType(
                        str(question.get("type") or SurveyQuestionType.SHORT_TEXT.value)
                    ),
                    report_key=SurveyRepository._parse_report_key(question.get("report_key")),
                    title=str(question.get("title") or ""),
                    description=str(question.get("description") or ""),
                    required=bool(question.get("required")),
                    options=[
                        SurveyQuestionOption(
                            id=str(option.get("id") or ""),
                            label=str(option.get("label") or ""),
                            value=str(option.get("value") or ""),
                            position=int(option.get("position") or 1),
                        )
                        for option in list(question.get("options") or [])
                    ],
                    validation=SurveyQuestionValidation(**dict(question.get("validation") or {})),
                    config=SurveyQuestionConfig(**dict(question.get("config") or {})),
                )
                for question in list(document.get("questions") or [])
            ],
            version=int(document.get("version") or 1),
            response_count=int(document.get("response_count") or 0),
            published_at=document.get("published_at"),
            closed_at=document.get("closed_at"),
            last_response_at=document.get("last_response_at"),
            created_at=document["created_at"],
            updated_at=document["updated_at"],
        )

    @staticmethod
    def _parse_report_key(value: Any) -> SurveyReportKey | None:
        if value is None:
            return None
        normalized = str(value).strip()
        if not normalized:
            return None
        try:
            return SurveyReportKey(normalized)
        except ValueError:
            return None
