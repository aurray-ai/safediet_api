from __future__ import annotations

import unittest

from app.services.notification_copy_service import (
    _COPY_REGISTRY,
    NotificationCopyKey,
    NotificationCopyService,
)
from app.services.notification_service import NotificationService


def choose_first(items):
    return items[0]


class NotificationCopyServiceTests(unittest.TestCase):
    def test_each_supported_copy_family_has_at_least_ten_variants(self) -> None:
        self.assertGreaterEqual(len(_COPY_REGISTRY[NotificationCopyKey.UNSAVED_MEAL_PLAN_REMINDER]), 10)
        self.assertGreaterEqual(len(_COPY_REGISTRY[NotificationCopyKey.MEAL_PLAN_APPROVED]), 10)
        self.assertGreaterEqual(len(_COPY_REGISTRY[NotificationCopyKey.MEAL_SLOT_REMINDER]), 10)

    def test_unsaved_meal_plan_copy_renders_week_context(self) -> None:
        service = NotificationCopyService(chooser=choose_first)

        copy = service.for_unsaved_meal_plan_reminder(
            period_label="Jun 20 - 26",
            view_mode="week",
        )

        self.assertIn("weekly plan", copy.title.lower())
        self.assertIn("your Jun 20 - 26 weekly plan", copy.message)

    def test_approved_meal_plan_copy_renders_day_context(self) -> None:
        service = NotificationCopyService(chooser=choose_first)

        copy = service.for_meal_plan_approved(
            period_label="Thursday",
            view_mode="day",
        )

        self.assertIn("meal plan", copy.title.lower())
        self.assertIn("Your Thursday meal plan", copy.message)

    def test_meal_slot_reminder_copy_renders_meal_context(self) -> None:
        service = NotificationCopyService(chooser=choose_first)

        copy = service.for_meal_slot_reminder(
            meal_name="Greek Yogurt Bowl",
            meal_slot="breakfast",
            time_label="this morning",
        )

        self.assertEqual("Greek Yogurt Bowl", copy.title)
        self.assertIn("Greek Yogurt Bowl", copy.message)
        self.assertIn("this morning breakfast", copy.message)


class NotificationServiceCopyEntryPointTests(unittest.TestCase):
    def test_notification_service_exposes_unsaved_and_approved_copy_methods(self) -> None:
        copy_service = NotificationCopyService(chooser=choose_first)
        service = NotificationService(
            notification_repository=object(),
            saved_meal_plan_repository=object(),
            notification_copy_service=copy_service,
        )

        unsaved = service.unsaved_meal_plan_reminder_copy(period_label="Friday", view_mode="day")
        approved = service.meal_plan_approved_copy(period_label="Friday", view_mode="day")
        meal_slot = service.meal_slot_reminder_copy(
            meal_name="Chicken Rice Bowl",
            meal_slot="lunch",
            time_label="this afternoon",
        )

        self.assertTrue(unsaved.title)
        self.assertTrue(unsaved.message)
        self.assertTrue(approved.title)
        self.assertTrue(approved.message)
        self.assertTrue(meal_slot.title)
        self.assertTrue(meal_slot.message)
        self.assertIn("Friday meal plan", unsaved.message)
        self.assertIn("Friday meal plan", approved.message)
        self.assertIn("Chicken Rice Bowl", meal_slot.message)
