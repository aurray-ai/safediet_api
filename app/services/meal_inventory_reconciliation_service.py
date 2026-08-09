from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from app.models.user_pantry_item import UserPantryItem


@dataclass(frozen=True, slots=True)
class ReconciledDemand:
    slot: str
    meal_id: str
    product_id: str
    product_name: str
    required_quantity: float
    unit: str
    used_from_pantry: float
    remaining_shortage: float
    is_shared: bool


class MealInventoryReconciliationService:
    def reconcile(
        self,
        *,
        product_demands: list[dict[str, Any]],
        pantry_items: list[UserPantryItem],
    ) -> dict[str, Any]:
        remaining_by_product = {
            item.product_id: {
                "product_id": item.product_id,
                "product_name": item.product_name,
                "quantity": float(item.quantity),
                "unit": item.unit,
            }
            for item in pantry_items
        }

        used_items: list[dict[str, Any]] = []
        shortages: list[dict[str, Any]] = []
        for demand in product_demands:
            product_id = str(demand.get("product_id") or "")
            required_quantity = float(demand.get("required_quantity") or 0)
            unit = str(demand.get("unit") or "")
            pantry_entry = remaining_by_product.get(product_id)
            available_quantity = 0.0
            if pantry_entry and str(pantry_entry.get("unit") or "") == unit:
                available_quantity = float(pantry_entry.get("quantity") or 0)

            used_from_pantry = min(required_quantity, available_quantity)
            if pantry_entry and used_from_pantry > 0:
                pantry_entry["quantity"] = max(available_quantity - used_from_pantry, 0.0)
                used_items.append(
                    {
                        "product_id": product_id,
                        "product_name": demand.get("product_name"),
                        "image_url": demand.get("image_url"),
                        "slot": demand.get("slot"),
                        "meal_id": demand.get("meal_id"),
                        "used_quantity": round(used_from_pantry, 2),
                        "unit": unit,
                    }
                )

            remaining_shortage = max(required_quantity - used_from_pantry, 0.0)
            if remaining_shortage > 0:
                shortages.append(
                    {
                        **demand,
                        "remaining_shortage": round(remaining_shortage, 2),
                        "used_from_pantry": round(used_from_pantry, 2),
                    }
                )

        remaining_items = [
            {
                "product_id": item["product_id"],
                "product_name": item["product_name"],
                "remaining_quantity": round(float(item["quantity"]), 2),
                "unit": item["unit"],
                "is_depleted": float(item["quantity"]) <= 0,
            }
            for item in remaining_by_product.values()
        ]
        depleted_count = sum(1 for item in remaining_items if item["is_depleted"])
        return {
            "used_items": used_items,
            "remaining_items": remaining_items,
            "shortages": shortages,
            "used_items_count": len(used_items),
            "depleted_items_count": depleted_count,
        }
