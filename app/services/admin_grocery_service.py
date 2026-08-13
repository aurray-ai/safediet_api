from datetime import datetime
from uuid import uuid4

from pymongo.errors import DuplicateKeyError

from app.core.nutrients import nutrient_metadata_payload
from app.models.grocery import CountryCode, CultureTag, GroceryCategory, GroceryProduct
from app.repositories.grocery_repository import GroceryRepository
from app.schemas.admin_grocery import (
    AdminGroceryBulkDeleteResponse,
    AdminCountryPricePayload,
    AdminCountryPriceSummary,
    AdminGroceryProductCreateRequest,
    AdminGroceryProductListItemResponse,
    AdminGroceryProductPayload,
    AdminGroceryProductResponse,
    AdminGroceryProductListResponse,
    AdminMetadataResponse,
    AdminNutritionSpecPayload,
)
from app.schemas.grocery import GroceryCategoryResponse
from app.services.grocery_catalog_embedding_service import (
    GroceryCatalogEmbeddingError,
    GroceryCatalogEmbeddingService,
)


class AdminGroceryCategoryNotFoundError(Exception):
    pass


class AdminGroceryProductNotFoundError(Exception):
    pass


class AdminGroceryProductAlreadyExistsError(Exception):
    pass


class AdminGroceryValidationError(Exception):
    pass


class AdminGroceryService:
    def __init__(
        self,
        grocery_repository: GroceryRepository,
        grocery_catalog_embedding_service: GroceryCatalogEmbeddingService | None = None,
    ) -> None:
        self._grocery_repository = grocery_repository
        self._grocery_catalog_embedding_service = grocery_catalog_embedding_service

    def get_metadata(self) -> AdminMetadataResponse:
        categories = [
            GroceryCategoryResponse(
                id=category.id,
                slug=category.slug.value,
                name=category.name,
                icon_name=category.icon_name,
                img_url=category.img_url,
                description=category.description,
                sort_order=category.sort_order,
            )
            for category in self._grocery_repository.list_all_categories()
        ]
        cultures = [
            {"value": culture.value, "display_name": culture.value.replace("_", " ").title()}
            for culture in CultureTag
        ]
        nutrients = nutrient_metadata_payload()
        supported_countries = [
            {"country_code": CountryCode.NIGERIA.value, "currency_code": "NGN", "display_name": "Nigeria"},
            {"country_code": CountryCode.UNITED_KINGDOM.value, "currency_code": "GBP", "display_name": "United Kingdom"},
            {"country_code": CountryCode.INDIA.value, "currency_code": "INR", "display_name": "India"},
        ]

        return AdminMetadataResponse(
            categories=categories,
            cultures=cultures,
            nutrients=nutrients,
            supported_countries=supported_countries,
        )

    def list_products(
        self,
        *,
        page: int,
        page_size: int,
        search: str | None = None,
        category_id: str | None = None,
    ) -> AdminGroceryProductListResponse:
        products, total = self._grocery_repository.list_all_product_summaries(
            page=page,
            page_size=page_size,
            search=search,
            category_id=category_id,
        )
        category_lookup = {
            category.id: category.name
            for category in self._grocery_repository.list_all_categories()
        }
        return AdminGroceryProductListResponse(
            items=[
                AdminGroceryProductListItemResponse(
                    id=product["id"],
                    category_id=product["category_id"],
                    category_name=category_lookup.get(product["category_id"], product["category_id"]),
                    img_url=product["img_url"],
                    product=product["product"],
                    price=self._to_price_summary(product.get("prices", [])),
                    is_active=bool(product.get("is_active", True)),
                )
                for product in products
            ],
            total=total,
            page=page,
            page_size=page_size,
        )

    def get_product(self, product_id: str) -> AdminGroceryProductResponse:
        product = self._grocery_repository.get_product_by_id(product_id)
        if product is None:
            raise AdminGroceryProductNotFoundError
        return self._to_response(product)

    def create_product(self, payload: AdminGroceryProductCreateRequest) -> AdminGroceryProductResponse:
        self._ensure_category_exists(payload.category_id)
        product_id = self._generate_product_id(payload.product)
        self._validate_product_payload(payload)
        payload_kwargs = self._payload_kwargs(payload)
        embedding_payload = self._build_embedding_payload(payload_kwargs)
        try:
            product = self._grocery_repository.create_product(
                product_id=product_id,
                **payload_kwargs,
                **embedding_payload,
            )
        except DuplicateKeyError as exc:
            raise AdminGroceryProductAlreadyExistsError from exc
        return self._to_response(product)

    def update_product(
        self,
        *,
        product_id: str,
        payload: AdminGroceryProductPayload,
    ) -> AdminGroceryProductResponse:
        self._ensure_category_exists(payload.category_id)
        self._validate_product_payload(payload)
        payload_kwargs = self._payload_kwargs(payload)
        embedding_payload = self._build_embedding_payload(payload_kwargs)
        product = self._grocery_repository.update_product(
            product_id=product_id,
            **payload_kwargs,
            **embedding_payload,
        )
        if product is None:
            raise AdminGroceryProductNotFoundError
        return self._to_response(product)

    def delete_product(self, product_id: str) -> None:
        deleted = self._grocery_repository.delete_product(product_id)
        if not deleted:
            raise AdminGroceryProductNotFoundError

    def delete_products(self, product_ids: list[str]) -> AdminGroceryBulkDeleteResponse:
        existing_product_ids: list[str] = []
        missing_product_ids: list[str] = []

        for product_id in product_ids:
            if self._grocery_repository.get_product_by_id(product_id) is None:
                missing_product_ids.append(product_id)
            else:
                existing_product_ids.append(product_id)

        deleted_count = self._grocery_repository.delete_products(existing_product_ids)
        if deleted_count != len(existing_product_ids):
            raise AdminGroceryValidationError("Some selected grocery products could not be deleted.")

        return AdminGroceryBulkDeleteResponse(
            deleted_product_ids=existing_product_ids,
            missing_product_ids=missing_product_ids,
            deleted_count=deleted_count,
        )

    def _ensure_category_exists(self, category_id: str) -> GroceryCategory:
        category = self._grocery_repository.get_category(category_id)
        if category is None:
            raise AdminGroceryCategoryNotFoundError
        return category

    def _build_embedding_payload(self, payload_kwargs: dict[str, object]) -> dict[str, object]:
        if self._grocery_catalog_embedding_service is None:
            return {}
        search_document = self._grocery_repository.build_search_document(payload_kwargs)
        try:
            return self._grocery_catalog_embedding_service.create_embedding_payload(
                search_document=search_document
            )
        except GroceryCatalogEmbeddingError:
            return {}

    @staticmethod
    def _generate_product_id(product_name: str) -> str:
        normalized = "_".join(product_name.strip().lower().split())
        return f"prod_{normalized}_{uuid4().hex[:8]}"

    @staticmethod
    def _validate_product_payload(payload: AdminGroceryProductPayload) -> None:
        if not payload.img_url.strip():
            raise AdminGroceryValidationError("Each product must include an image.")

        if not any(price.amount > 0 for price in payload.prices):
            raise AdminGroceryValidationError("Each product must include at least one price entry.")

    @staticmethod
    def _payload_kwargs(payload: AdminGroceryProductPayload) -> dict[str, object]:
        return {
            "category_id": payload.category_id,
            "img_url": payload.img_url,
            "product": payload.product,
            "product_tags": payload.product_tags,
            "sort_order": payload.sort_order,
            "culture_tags": [culture.value for culture in payload.culture_tags],
            "nutritional_specs": [
                {
                    "nutrient_id": int(spec.nutrient_id),
                    "amount": spec.amount,
                    "unit": spec.unit.value,
                }
                for spec in payload.nutritional_specs
            ],
            "prices": [
                {
                    "country_code": price.country_code.value,
                    "currency_code": price.currency_code.value,
                    "amount": price.amount,
                    "price_unit": price.price_unit,
                    "source": price.source,
                    "is_active": price.is_active,
                    "region": price.region,
                    "city": price.city,
                }
                for price in payload.prices
            ],
            "description": payload.description,
            "is_active": payload.is_active,
        }

    @staticmethod
    def _to_price_summary(prices: list[dict[str, object]]) -> AdminCountryPriceSummary | None:
        if not prices:
            return None

        active_price = next((price for price in prices if bool(price.get("is_active", True))), prices[0])
        return AdminCountryPriceSummary(
            currency_code=active_price["currency_code"],
            amount=float(active_price["amount"]),
            price_unit=str(active_price["price_unit"]),
        )

    @staticmethod
    def _to_response(product: GroceryProduct) -> AdminGroceryProductResponse:
        return AdminGroceryProductResponse(
            id=product.id,
            category_id=product.category_id,
            img_url=product.img_url,
            product=product.product,
            description=product.description,
            sort_order=product.sort_order,
            product_tags=product.product_tags,
            culture_tags=product.culture_tags,
            nutritional_specs=[
                AdminNutritionSpecPayload(
                    nutrient_id=spec.nutrient_id,
                    amount=spec.amount,
                    unit=spec.unit,
                )
                for spec in product.nutritional_specs
            ],
            prices=[
                AdminCountryPricePayload(
                    country_code=price.country_code,
                    currency_code=price.currency_code,
                    amount=price.amount,
                    price_unit=price.price_unit,
                    source=price.source,
                    is_active=price.is_active,
                    region=price.region,
                    city=price.city,
                )
                for price in product.prices
            ],
            is_active=product.is_active,
            created_at=product.created_at,
            updated_at=product.updated_at,
        )
