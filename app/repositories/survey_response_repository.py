from __future__ import annotations

from datetime import datetime, timezone
from typing import Any
from uuid import uuid4

from pymongo import DESCENDING
from pymongo.collection import Collection

from app.models.survey import SurveyAnswer, SurveyQuestionType, SurveyRespondent, SurveyResponse


class SurveyResponseRepository:
    def __init__(self, collection: Collection[dict[str, Any]]) -> None:
        self._collection = collection

    def create_response(
        self,
        *,
        survey_id: str,
        survey_slug: str,
        survey_version: int,
        respondent: dict[str, Any],
        answers: list[dict[str, Any]],
        submitted_at: datetime | None = None,
    ) -> SurveyResponse:
        now = submitted_at or datetime.now(timezone.utc)
        document = {
            "_id": uuid4().hex,
            "survey_id": survey_id,
            "survey_slug": survey_slug,
            "survey_version": survey_version,
            "respondent": respondent,
            "answers": answers,
            "submitted_at": now,
            "created_at": now,
        }
        self._collection.insert_one(document)
        return self._to_model(document)

    def list_responses(self, *, survey_id: str, limit: int = 100) -> tuple[list[SurveyResponse], int]:
        query = {"survey_id": survey_id}
        total = self._collection.count_documents(query)
        documents = self._collection.find(query).sort("submitted_at", DESCENDING).limit(limit)
        return [self._to_model(document) for document in documents], total

    def get_by_id(self, *, survey_id: str, response_id: str) -> SurveyResponse | None:
        document = self._collection.find_one({"_id": response_id, "survey_id": survey_id})
        return None if document is None else self._to_model(document)

    def has_response_for_user(self, *, survey_id: str, user_id: str) -> bool:
        return self._collection.find_one({"survey_id": survey_id, "respondent.user_id": user_id}) is not None

    def has_response_for_email(self, *, survey_id: str, email: str) -> bool:
        return self._collection.find_one({"survey_id": survey_id, "respondent.email": email}) is not None

    @staticmethod
    def _to_model(document: dict[str, Any]) -> SurveyResponse:
        respondent = dict(document.get("respondent") or {})
        return SurveyResponse(
            id=str(document["_id"]),
            survey_id=str(document.get("survey_id") or ""),
            survey_slug=str(document.get("survey_slug") or ""),
            survey_version=int(document.get("survey_version") or 1),
            respondent=SurveyRespondent(
                user_id=respondent.get("user_id"),
                email=respondent.get("email"),
                name=respondent.get("name"),
                ip_hash=respondent.get("ip_hash"),
                user_agent=respondent.get("user_agent"),
            ),
            answers=[
                SurveyAnswer(
                    question_id=str(answer.get("question_id") or ""),
                    type=SurveyQuestionType(
                        str(answer.get("type") or SurveyQuestionType.SHORT_TEXT.value)
                    ),
                    value=answer.get("value"),
                )
                for answer in list(document.get("answers") or [])
            ],
            submitted_at=document["submitted_at"],
            created_at=document["created_at"],
        )
