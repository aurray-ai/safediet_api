from dataclasses import dataclass

from app.models.grocery import (
    CountryCode,
    CountryPrice,
    CultureTag,
    GroceryCategory,
    GroceryProduct,
    NutrientType,
    NutrientUnit,
)
from app.repositories.grocery_repository import GroceryRepository
from app.schemas.grocery import (
    CountryPriceResponse,
    CultureMetadataResponse,
    GroceryCategoryResponse,
    GroceryProductDetailResponse,
    GroceryProductListItemResponse,
    GroceryProductListResponse,
    NutrientMetadataResponse,
    NutritionSpecResponse,
    ResolvedPriceResponse,
)
from app.services.pricing import apply_category_discount


class GroceryCategoryNotFoundError(Exception):
    pass


class GroceryProductNotFoundError(Exception):
    pass


@dataclass(frozen=True, slots=True)
class NutrientMetadata:
    nutrient_id: NutrientType
    slug: str
    display_name: str
    default_unit: NutrientUnit


NUTRIENT_REGISTRY: tuple[NutrientMetadata, ...] = (
    NutrientMetadata(NutrientType.PROTEIN, "protein", "Protein", NutrientUnit.GRAM),
    NutrientMetadata(NutrientType.CARBOHYDRATES, "carbohydrates", "Carbohydrates", NutrientUnit.GRAM),
    NutrientMetadata(NutrientType.FAT, "fat", "Fat", NutrientUnit.GRAM),
    NutrientMetadata(NutrientType.FIBER, "fiber", "Fiber", NutrientUnit.GRAM),
    NutrientMetadata(NutrientType.SUGAR, "sugar", "Sugar", NutrientUnit.GRAM),
    NutrientMetadata(NutrientType.SODIUM, "sodium", "Sodium", NutrientUnit.MILLIGRAM),
    NutrientMetadata(NutrientType.CALORIES, "calories", "Calories", NutrientUnit.KILOCALORIE),
    NutrientMetadata(NutrientType.SATURATED_FAT, "saturated_fat", "Saturated Fat", NutrientUnit.GRAM),
    NutrientMetadata(NutrientType.CALCIUM, "calcium", "Calcium", NutrientUnit.MILLIGRAM),
    NutrientMetadata(NutrientType.IRON, "iron", "Iron", NutrientUnit.MILLIGRAM),
    NutrientMetadata(NutrientType.POTASSIUM, "potassium", "Potassium", NutrientUnit.MILLIGRAM),
    NutrientMetadata(NutrientType.VITAMIN_C, "vitamin_c", "Vitamin C", NutrientUnit.MILLIGRAM),
    NutrientMetadata(NutrientType.VITAMIN_A, "vitamin_a", "Vitamin A", NutrientUnit.MILLIGRAM),
)


class GroceryService:
    def __init__(self, grocery_repository: GroceryRepository) -> None:
        self._grocery_repository = grocery_repository

    def list_categories(self) -> list[GroceryCategoryResponse]:
        return [
            GroceryCategoryResponse(
                id=category.id,
                slug=category.slug.value,
                name=category.name,
                icon_name=category.icon_name,
                img_url=category.img_url,
                description=category.description,
                sort_order=category.sort_order,
            )
            for category in self._grocery_repository.list_categories()
        ]

    def list_products_by_category(
        self,
        *,
        category_id: str,
        country: CountryCode | None,
        culture: CultureTag | None,
        search: str | None,
        product_tag: str | None,
        sort: str | None,
        page: int,
        page_size: int,
    ) -> GroceryProductListResponse:
        category = self._grocery_repository.get_category(category_id)
        if category is None:
            raise GroceryCategoryNotFoundError

        products, total = self._grocery_repository.list_products_by_category(
            category_id=category_id,
            culture_tag=culture,
            search=search,
            product_tag=product_tag,
            sort=sort,
            page=page,
            page_size=page_size,
        )

        return GroceryProductListResponse(
            items=[
                GroceryProductListItemResponse(
                    id=product.id,
                    category_id=product.category_id,
                    img_url=product.img_url,
                    product=product.product,
                    sort_order=product.sort_order,
                    product_tags=product.product_tags,
                    culture_tags=product.culture_tags,
                    nutritional_specs=[
                        NutritionSpecResponse(
                            nutrient_id=spec.nutrient_id,
                            amount=spec.amount,
                            unit=spec.unit,
                        )
                        for spec in product.nutritional_specs
                    ],
                    resolved_price=self._resolve_price_response(product, country, category),
                )
                for product in products
            ],
            total=total,
            page=page,
            page_size=page_size,
        )

    def list_products(
        self,
        *,
        country: CountryCode | None,
        culture: CultureTag | None,
        search: str | None,
        product_tag: str | None,
        category_id: str | None,
        sort: str | None,
        page: int,
        page_size: int,
    ) -> GroceryProductListResponse:
        category_cache: dict[str, GroceryCategory | None] = {}
        if category_id:
            category = self._grocery_repository.get_category(category_id)
            if category is None:
                raise GroceryCategoryNotFoundError
            category_cache[category_id] = category

        products, total = self._grocery_repository.list_products(
            category_id=category_id,
            culture_tag=culture,
            search=search,
            product_tag=product_tag,
            sort=sort,
            page=page,
            page_size=page_size,
        )

        return GroceryProductListResponse(
            items=[
                GroceryProductListItemResponse(
                    id=product.id,
                    category_id=product.category_id,
                    img_url=product.img_url,
                    product=product.product,
                    sort_order=product.sort_order,
                    product_tags=product.product_tags,
                    culture_tags=product.culture_tags,
                    nutritional_specs=[
                        NutritionSpecResponse(
                            nutrient_id=spec.nutrient_id,
                            amount=spec.amount,
                            unit=spec.unit,
                        )
                        for spec in product.nutritional_specs
                    ],
                    resolved_price=self._resolve_price_response(
                        product, country, self._resolve_category(product.category_id, category_cache)
                    ),
                )
                for product in products
            ],
            total=total,
            page=page,
            page_size=page_size,
        )

    def get_product(self, product_id: str) -> GroceryProductDetailResponse:
        product = self._grocery_repository.get_product(product_id)
        if product is None:
            raise GroceryProductNotFoundError

        category = self._grocery_repository.get_category(product.category_id)

        prices: list[CountryPriceResponse] = []
        for price in product.prices:
            member_amount, discount_percent = self._resolve_member_pricing(
                category=category, base_amount=price.amount
            )
            prices.append(
                CountryPriceResponse(
                    country_code=price.country_code,
                    currency_code=price.currency_code,
                    amount=price.amount,
                    price_unit=price.price_unit,
                    member_amount=member_amount,
                    discount_percent=discount_percent,
                    source=price.source,
                    updated_at=price.updated_at,
                    is_active=price.is_active,
                    region=price.region,
                    city=price.city,
                )
            )

        return GroceryProductDetailResponse(
            id=product.id,
            category_id=product.category_id,
            img_url=product.img_url,
            product=product.product,
            sort_order=product.sort_order,
            product_tags=product.product_tags,
            culture_tags=product.culture_tags,
            nutritional_specs=[
                NutritionSpecResponse(
                    nutrient_id=spec.nutrient_id,
                    amount=spec.amount,
                    unit=spec.unit,
                )
                for spec in product.nutritional_specs
            ],
            prices=prices,
            description=product.description,
        )

    def list_cultures(self) -> list[CultureMetadataResponse]:
        return [
            CultureMetadataResponse(
                value=culture,
                display_name=culture.value.replace("_", " ").title(),
            )
            for culture in CultureTag
        ]

    def list_nutrients(self) -> list[NutrientMetadataResponse]:
        return [
            NutrientMetadataResponse(
                id=metadata.nutrient_id,
                slug=metadata.slug,
                display_name=metadata.display_name,
                default_unit=metadata.default_unit,
            )
            for metadata in NUTRIENT_REGISTRY
        ]

    def _resolve_category(
        self,
        category_id: str,
        cache: dict[str, GroceryCategory | None],
    ) -> GroceryCategory | None:
        if category_id not in cache:
            cache[category_id] = self._grocery_repository.get_category(category_id)
        return cache[category_id]

    def _resolve_price_response(
        self,
        product: GroceryProduct,
        country: CountryCode | None,
        category: GroceryCategory | None,
    ) -> ResolvedPriceResponse | None:
        if country is None:
            return None

        price = next(
            (
                candidate
                for candidate in product.prices
                if candidate.is_active and candidate.country_code == country
            ),
            None,
        )
        if price is None:
            return None

        return self._to_resolved_price(price, category=category)

    def _to_resolved_price(
        self,
        price: CountryPrice,
        *,
        category: GroceryCategory | None,
    ) -> ResolvedPriceResponse:
        member_amount, discount_percent = self._resolve_member_pricing(
            category=category, base_amount=price.amount
        )

        return ResolvedPriceResponse(
            country_code=price.country_code,
            currency_code=price.currency_code,
            amount=price.amount,
            price_unit=price.price_unit,
            member_amount=member_amount,
            discount_percent=discount_percent,
        )

    def _resolve_member_pricing(
        self,
        *,
        category: GroceryCategory | None,
        base_amount: float,
    ) -> tuple[float | None, float | None]:
        if category is None or not category.discount_percent:
            return None, None

        base_price_minor = int(round(base_amount * 100))
        final_price_minor, effective_percent = apply_category_discount(base_price_minor, category.discount_percent)
        return final_price_minor / 100, effective_percent
