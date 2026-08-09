from __future__ import annotations

from typing import Any

from app.models.grocery import CountryCode
from app.repositories.grocery_repository import GroceryRepository


class MapGroceryProductsTool:
    name = "map_grocery_products"
    description = (
        "Load grocery product cards from known product_ids. "
        "Use this only when the final response still needs grocery sourcing blocks."
    )

    def __init__(self, grocery_repository: GroceryRepository) -> None:
        self._grocery_repository = grocery_repository

    def execute(
        self,
        *,
        slot: str,
        product_ids: list[str],
        country_code: str | None = None,
    ) -> dict[str, Any]:
        resolved_country = CountryCode(country_code) if country_code else None
        products = self._grocery_repository.list_products_by_ids(product_ids)
        return {
            "slot": slot,
            "items": [
                {
                    "id": product.id,
                    "name": product.product,
                    "img_url": product.img_url,
                    "category_id": product.category_id,
                    "resolved_price": self._resolved_price(product, resolved_country),
                }
                for product in products
            ]
        }

    @staticmethod
    def _resolved_price(product, country_code: CountryCode | None) -> dict[str, Any] | None:
        if country_code is None:
            return None
        for price in product.prices:
            if price.is_active and price.country_code == country_code:
                return {
                    "country_code": price.country_code.value,
                    "currency_code": price.currency_code.value,
                    "amount": price.amount,
                }
        return None
