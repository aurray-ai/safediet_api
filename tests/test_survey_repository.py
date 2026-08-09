from __future__ import annotations

import unittest
from datetime import datetime, timezone

from app.repositories.survey_repository import SurveyRepository


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


def build_document(*, report_key: str | None) -> dict:
    now = utc_now()
    return {
        "_id": "survey-1",
        "slug": "customer-feedback",
        "title": "Customer Feedback",
        "description": "Tell us what you think.",
        "status": "draft",
        "owner_user_id": "user-1",
        "settings": {
            "is_public": True,
            "collect_email": False,
            "require_auth": False,
            "limit_one_response_per_user": False,
            "limit_one_response_per_email": False,
            "show_progress_bar": True,
            "shuffle_question_order": False,
            "confirmation_message": "Thanks.",
            "accepting_responses": True,
        },
        "theme": {
            "accent_color": "#2f6fed",
            "header_image_url": "",
            "font_family": "inherit",
        },
        "sections": [
            {
                "id": "section_1",
                "title": "Page 1",
                "description": "",
                "position": 1,
            }
        ],
        "questions": [
            {
                "id": "question_1",
                "section_id": "section_1",
                "position": 1,
                "type": "single_choice",
                "report_key": report_key,
                "title": "Meal planning frequency",
                "description": "",
                "required": True,
                "options": [
                    {
                        "id": "option_1",
                        "label": "Every week",
                        "value": "every_week",
                        "position": 1,
                    }
                ],
                "validation": {},
                "config": {},
            }
        ],
        "version": 1,
        "response_count": 0,
        "published_at": None,
        "closed_at": None,
        "last_response_at": None,
        "created_at": now,
        "updated_at": now,
    }


class SurveyRepositoryTests(unittest.TestCase):
    def test_to_model_keeps_valid_report_key(self) -> None:
        survey = SurveyRepository._to_model(build_document(report_key="planning_frequency"))

        self.assertIsNotNone(survey.questions[0].report_key)
        self.assertEqual("planning_frequency", survey.questions[0].report_key.value)

    def test_to_model_ignores_invalid_report_key(self) -> None:
        survey = SurveyRepository._to_model(build_document(report_key="legacy-custom-value"))

        self.assertIsNone(survey.questions[0].report_key)


if __name__ == "__main__":
    unittest.main()
