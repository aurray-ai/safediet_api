from __future__ import annotations

import math
import re
from typing import Any

from app.models.grocery import CountryCode, GroceryProduct
from app.repositories.grocery_repository import GroceryRepository


class MealPlanCostingService:
    def __init__(self, grocery_repository: GroceryRepository) -> None:
        self._grocery_repository = grocery_repository

    def build_product_demands(
        self,
        *,
        meals_by_slot: dict[str, dict[str, Any]],
        household_size: int,
    ) -> dict[str, Any]:
        product_ids: list[str] = []
        demands: list[dict[str, Any]] = []
        shared_counts: dict[str, int] = {}

        for slot, meal in meals_by_slot.items():
            servings = self._normalized_float(meal.get("servings")) or 1.0
            planned_servings = self._normalized_float(meal.get("planned_servings"))
            target_servings = planned_servings if planned_servings is not None and planned_servings > 0 else max(float(household_size), 1.0)
            scale_factor = target_servings / max(servings, 1.0)
            for ingredient in list(meal.get("ingredient_items") or []):
                linked_product_ids = [str(item) for item in list(ingredient.get("linked_product_ids") or []) if str(item).strip()]
                product_id = linked_product_ids[0] if linked_product_ids else ""
                if not product_id:
                    continue
                product_ids.append(product_id)
                shared_counts[product_id] = shared_counts.get(product_id, 0) + 1
                quantity = self._normalized_float(ingredient.get("quantity")) or 0.0
                unit = str(ingredient.get("unit") or "").strip().lower()
                demands.append(
                    {
                        "slot": slot,
                        "meal_id": str(meal.get("id") or ""),
                        "meal_name": str(meal.get("name") or ""),
                        "product_id": product_id,
                        "product_name": str(ingredient.get("name") or ""),
                        "required_quantity": round(quantity * scale_factor, 2),
                        "unit": unit,
                        "is_shared": False,
                    }
                )

        products = self._grocery_repository.list_products_by_ids(list(dict.fromkeys(product_ids)))
        products_by_id = {product.id: product for product in products}
        for demand in demands:
            demand["is_shared"] = shared_counts.get(demand["product_id"], 0) > 1
            product = products_by_id.get(demand["product_id"])
            if product is not None:
                demand["product_name"] = product.product
                demand["image_url"] = product.img_url

        return {
            "product_demands": demands,
            "products_by_id": products_by_id,
            "shared_product_count": sum(1 for count in shared_counts.values() if count > 1),
        }

    def summarize_cart(
        self,
        *,
        shortages: list[dict[str, Any]],
        products_by_id: dict[str, GroceryProduct],
        country_code: str | None,
        target_budget: float | None = None,
        minimum_budget_scale: float = 0.35,
    ) -> dict[str, Any]:
        resolved_country = CountryCode(str(country_code)) if country_code else None
        buy_items: list[dict[str, Any]] = []
        total_cost = 0.0
        currency_code: str | None = None

        aggregated_shortages: dict[tuple[str, str], dict[str, Any]] = {}
        for shortage in shortages:
            product_id = str(shortage.get("product_id") or "")
            unit = str(shortage.get("unit") or "")
            key = (product_id, unit)
            entry = aggregated_shortages.setdefault(
                key,
                {
                    "product_id": product_id,
                    "product_name": shortage.get("product_name"),
                    "image_url": shortage.get("image_url"),
                    "required_quantity": 0.0,
                    "unit": unit,
                    "is_shared": False,
                    "slots": [],
                    "meal_ids": [],
                },
            )
            entry["required_quantity"] += float(shortage.get("remaining_shortage") or 0)
            entry["is_shared"] = bool(entry["is_shared"] or shortage.get("is_shared"))
            slot = str(shortage.get("slot") or "")
            meal_id = str(shortage.get("meal_id") or "")
            if slot and slot not in entry["slots"]:
                entry["slots"].append(slot)
            if meal_id and meal_id not in entry["meal_ids"]:
                entry["meal_ids"].append(meal_id)

        shortage_entries = list(aggregated_shortages.values())
        budget_adjusted = False
        budget_adjustment_factor = 1.0
        shared_item_preservation_bonus = 0.12
        original_estimated_total_cost = self._estimated_cart_total(
            shortages=shortage_entries,
            products_by_id=products_by_id,
            country_code=resolved_country,
        )
        if (
            target_budget is not None
            and target_budget > 0
            and original_estimated_total_cost is not None
            and original_estimated_total_cost > target_budget
        ):
            budget_adjusted = True
            budget_adjustment_factor = max(
                min(target_budget / original_estimated_total_cost, 1.0),
                minimum_budget_scale,
            )
            shortage_entries = [
                {
                    **shortage,
                    "original_required_quantity": round(float(shortage.get("required_quantity") or 0.0), 2),
                    "adjustment_factor": round(
                        min(
                            1.0,
                            budget_adjustment_factor
                            + (shared_item_preservation_bonus if shortage.get("is_shared") else 0.0),
                        ),
                        3,
                    ),
                    "required_quantity": round(
                        float(shortage.get("required_quantity") or 0.0)
                        * min(
                            1.0,
                            budget_adjustment_factor
                            + (shared_item_preservation_bonus if shortage.get("is_shared") else 0.0),
                        ),
                        2,
                    ),
                }
                for shortage in shortage_entries
            ]

        for shortage in shortage_entries:
            product = products_by_id.get(str(shortage.get("product_id") or ""))
            required_quantity = float(shortage.get("required_quantity") or 0)
            if product is None:
                buy_items.append(
                    {
                        "product_id": shortage.get("product_id"),
                        "product_name": shortage.get("product_name"),
                        "image_url": shortage.get("image_url"),
                        "slots": list(shortage.get("slots") or []),
                        "meal_ids": list(shortage.get("meal_ids") or []),
                        "required_quantity": round(required_quantity, 2),
                        "unit": shortage.get("unit"),
                        "estimated_units_to_buy": None,
                        "estimated_cost": None,
                        "original_required_quantity": shortage.get("original_required_quantity"),
                        "adjustment_factor": shortage.get("adjustment_factor"),
                        "is_shared": bool(shortage.get("is_shared")),
                    }
                )
                continue

            price = self._preferred_price(product=product, country_code=resolved_country)
            pack_quantity, pack_unit = self._parse_pack_quantity(price.price_unit if price is not None else None)
            unit = str(shortage.get("unit") or "")
            estimated_units_to_buy = 1
            estimated_cost = None
            if price is not None:
                currency_code = price.currency_code.value
                if pack_quantity and pack_unit and pack_unit == unit and required_quantity > 0:
                    estimated_units_to_buy = max(int(math.ceil(required_quantity / pack_quantity)), 1)
                estimated_cost = round(float(price.amount) * estimated_units_to_buy, 2)
                total_cost += estimated_cost

            buy_items.append(
                {
                    "product_id": product.id,
                    "product_name": product.product,
                    "image_url": product.img_url,
                    "slots": list(shortage.get("slots") or []),
                    "meal_ids": list(shortage.get("meal_ids") or []),
                    "required_quantity": round(required_quantity, 2),
                    "unit": unit,
                    "estimated_units_to_buy": estimated_units_to_buy,
                    "estimated_cost": estimated_cost,
                    "formatted_estimated_cost": self._format_currency(estimated_cost, currency_code) if estimated_cost is not None else None,
                    "original_required_quantity": shortage.get("original_required_quantity"),
                    "adjustment_factor": shortage.get("adjustment_factor"),
                    "is_shared": bool(shortage.get("is_shared")),
                }
            )

        shared_items = [item for item in buy_items if item.get("is_shared")]
        return {
            "items_to_buy_count": len(buy_items),
            "buy_items": buy_items,
            "shared_items": shared_items,
            "estimated_total_cost": round(total_cost, 2),
            "currency_code": currency_code,
            "formatted_estimated_total_cost": self._format_currency(total_cost, currency_code) if currency_code and buy_items else None,
            "budget_adjusted": budget_adjusted,
            "budget_adjustment_factor": round(budget_adjustment_factor, 3),
            "target_budget": round(target_budget, 2) if target_budget is not None else None,
            "original_estimated_total_cost": (
                round(original_estimated_total_cost, 2)
                if original_estimated_total_cost is not None
                else None
            ),
            "formatted_original_estimated_total_cost": self._format_currency(
                original_estimated_total_cost,
                currency_code,
            ) if currency_code and original_estimated_total_cost is not None else None,
        }

    def _estimated_cart_total(
        self,
        *,
        shortages: list[dict[str, Any]],
        products_by_id: dict[str, GroceryProduct],
        country_code: CountryCode | None,
    ) -> float | None:
        total_cost = 0.0
        has_priced_item = False
        for shortage in shortages:
            product = products_by_id.get(str(shortage.get("product_id") or ""))
            if product is None:
                continue
            price = self._preferred_price(product=product, country_code=country_code)
            if price is None:
                continue
            required_quantity = float(shortage.get("required_quantity") or 0)
            pack_quantity, pack_unit = self._parse_pack_quantity(price.price_unit)
            unit = str(shortage.get("unit") or "")
            estimated_units_to_buy = 1
            if pack_quantity and pack_unit and pack_unit == unit and required_quantity > 0:
                estimated_units_to_buy = max(int(math.ceil(required_quantity / pack_quantity)), 1)
            total_cost += float(price.amount) * estimated_units_to_buy
            has_priced_item = True
        if not has_priced_item:
            return None
        return round(total_cost, 2)

    @staticmethod
    def _normalized_float(value: Any) -> float | None:
        try:
            if value in (None, ""):
                return None
            return float(value)
        except (TypeError, ValueError):
            return None

    @staticmethod
    def _parse_pack_quantity(price_unit: str | None) -> tuple[float | None, str | None]:
        if not price_unit:
            return None, None
        match = re.search(r"(\d+(?:\.\d+)?)\s*(kg|g|ml|l|unit|pack|pcs?)", price_unit.lower())
        if not match:
            return None, None
        quantity = float(match.group(1))
        unit = match.group(2)
        if unit == "kg":
            return quantity * 1000, "g"
        if unit == "l":
            return quantity * 1000, "ml"
        if unit in {"pc", "pcs", "pack"}:
            return quantity, "unit"
        return quantity, unit

    @staticmethod
    def _format_currency(amount: float | None, currency_code: str | None) -> str | None:
        if amount is None or not currency_code:
            return None
        symbols = {
            "GBP": "£",
            "NGN": "₦",
            "INR": "₹",
        }
        symbol = symbols.get(currency_code.upper(), currency_code.upper() + " ")
        return f"{symbol}{amount:,.2f}"

    @staticmethod
    def _preferred_price(product: GroceryProduct, country_code: CountryCode | None):
        if country_code is not None:
            for price in product.prices:
                if price.is_active and price.country_code == country_code:
                    return price
        for price in product.prices:
            if price.is_active:
                return price
        return None
