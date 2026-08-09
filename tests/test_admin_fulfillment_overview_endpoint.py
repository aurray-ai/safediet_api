from __future__ import annotations

import unittest
from datetime import datetime, timezone

from app.api.v1.endpoints.admin_fulfillment import get_fulfillment_overview
from app.models.user import User, UserType


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


def make_admin() -> User:
    return User(
        id="admin-1",
        name="Admin",
        email="admin@example.com",
        password_hash="x",
        user_types=[UserType.PLATFORM_USER],
        user_configuration={},
        created_at=utc_now(),
    )


class StubChefFulfillmentService:
    def get_overview(self):
        return {"unassigned": 2, "in_progress": 3, "completed_this_week": 4}


class StubShopperFulfillmentService:
    def get_overview(self):
        return {"unassigned": 1, "in_progress": 5, "completed_this_week": 6}


class AdminFulfillmentOverviewEndpointTests(unittest.TestCase):
    def test_get_fulfillment_overview_combines_both_tracks(self) -> None:
        response = get_fulfillment_overview(
            _=make_admin(),
            chef_fulfillment_service=StubChefFulfillmentService(),
            shopper_fulfillment_service=StubShopperFulfillmentService(),
        )

        self.assertEqual(2, response.chef.unassigned)
        self.assertEqual(3, response.chef.in_progress)
        self.assertEqual(4, response.chef.completed_this_week)
        self.assertEqual(1, response.shopper.unassigned)
        self.assertEqual(5, response.shopper.in_progress)
        self.assertEqual(6, response.shopper.completed_this_week)


if __name__ == "__main__":
    unittest.main()
