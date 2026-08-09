from __future__ import annotations

import unittest
from datetime import datetime, timezone

from app.services.checkout_service import CheckoutService


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


def build_line_item(*, base_price_minor: int, current_unit_price_minor: int, discount_percent_applied: float) -> dict:
    return {
        "id": "cart-item-1",
        "product_id": "product-1",
        "category_id": "cat-1",
        "product_name": "Chicken breast",
        "img_url": "",
        "quantity": 2,
        "unit_label": "pack",
        "unit_weight_grams": 500,
        "current_unit_price_minor": current_unit_price_minor,
        "base_price_minor": base_price_minor,
        "discount_percent_applied": discount_percent_applied,
        "currency": "GBP",
        "allow_substitutions": True,
        "source_meal_ids": [],
    }


class CheckoutOrderItemSnapshotTests(unittest.TestCase):
    def test_order_item_snapshot_freezes_base_price_and_discount_at_time_of_purchase(self) -> None:
        line_item = build_line_item(base_price_minor=1000, current_unit_price_minor=900, discount_percent_applied=10.0)

        snapshots = CheckoutService._build_order_items([line_item])

        snapshot = snapshots[0]
        self.assertEqual(1000, snapshot["base_price_minor"])
        self.assertEqual(900, snapshot["unit_price_minor"])
        self.assertEqual(10.0, snapshot["discount_percent_applied"])
        self.assertEqual(1800, snapshot["line_total_minor"])

    def test_order_item_snapshot_is_independent_of_later_category_discount_changes(self) -> None:
        # The quote line item captures the discount that was live when the item was priced.
        original_line_item = build_line_item(
            base_price_minor=1000, current_unit_price_minor=900, discount_percent_applied=10.0
        )
        first_order_snapshot = CheckoutService._build_order_items([original_line_item])[0]

        # Simulate the category's discount changing (e.g. admin resets it) after that order exists.
        # A brand-new quote for a fresh cart would reflect the new rate...
        new_rate_line_item = build_line_item(
            base_price_minor=1000, current_unit_price_minor=1000, discount_percent_applied=0.0
        )
        second_order_snapshot = CheckoutService._build_order_items([new_rate_line_item])[0]

        # ...but re-running the snapshot builder on the ORIGINAL line item (as would happen if the
        # original order were ever reconstructed) must still yield the original frozen values.
        replayed_original_snapshot = CheckoutService._build_order_items([original_line_item])[0]

        self.assertEqual(first_order_snapshot["discount_percent_applied"], replayed_original_snapshot["discount_percent_applied"])
        self.assertEqual(first_order_snapshot["unit_price_minor"], replayed_original_snapshot["unit_price_minor"])
        self.assertNotEqual(second_order_snapshot["discount_percent_applied"], first_order_snapshot["discount_percent_applied"])

    def test_order_item_snapshot_defaults_base_price_for_pre_migration_quotes(self) -> None:
        legacy_line_item = {
            "id": "cart-item-1",
            "product_id": "product-1",
            "category_id": "cat-1",
            "product_name": "Chicken breast",
            "img_url": "",
            "quantity": 1,
            "unit_label": "pack",
            "unit_weight_grams": 500,
            "current_unit_price_minor": 1000,
            "currency": "GBP",
            "allow_substitutions": True,
            "source_meal_ids": [],
        }

        snapshot = CheckoutService._build_order_items([legacy_line_item])[0]

        self.assertEqual(1000, snapshot["base_price_minor"])
        self.assertEqual(0.0, snapshot["discount_percent_applied"])


if __name__ == "__main__":
    unittest.main()
