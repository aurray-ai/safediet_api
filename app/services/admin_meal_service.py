from dataclasses import dataclass
from uuid import uuid4

from pymongo.errors import DuplicateKeyError

from app.models.grocery import CountryCode, CultureTag, GroceryProduct
from app.models.meal import Meal, MealCategory, MealDifficulty, MealType
from app.repositories.grocery_repository import GroceryRepository
from app.repositories.meal_repository import MealRepository
from app.schemas.admin_meal import (
    AdminIngredientConversionProfileOption,
    AdminMealBulkDeleteResponse,
    AdminMealCreateRequest,
    AdminMealEstimatedCostPayload,
    AdminMealEstimatedCostSummary,
    AdminMealIngredientPayload,
    AdminMealListItemResponse,
    AdminMealListResponse,
    AdminMealMetadataResponse,
    AdminMeasurementUnitOption,
    AdminMealRecipeStepPayload,
    AdminMealResponse,
    AdminMealSellingPricePayload,
)
from app.services.meal_catalog_embedding_service import MealCatalogEmbeddingService
from app.services.measurement_service import MeasurementService, MeasurementValidationError
from app.schemas.meal import MealCategoryResponse


class AdminMealCategoryNotFoundError(Exception):
    pass


class AdminMealNotFoundError(Exception):
    pass


class AdminMealAlreadyExistsError(Exception):
    pass


class AdminMealProductNotFoundError(Exception):
    pass


class AdminMealValidationError(Exception):
    pass


@dataclass(frozen=True, slots=True)
class SupportedCountry:
    country_code: CountryCode
    currency_code: str
    display_name: str


SUPPORTED_COUNTRIES: tuple[SupportedCountry, ...] = (
    SupportedCountry(CountryCode.NIGERIA, "NGN", "Nigeria"),
    SupportedCountry(CountryCode.UNITED_KINGDOM, "GBP", "United Kingdom"),
    SupportedCountry(CountryCode.INDIA, "INR", "India"),
)


class AdminMealService:
    def __init__(
        self,
        meal_repository: MealRepository,
        grocery_repository: GroceryRepository,
        measurement_service: MeasurementService,
        meal_catalog_embedding_service: MealCatalogEmbeddingService,
    ) -> None:
        self._meal_repository = meal_repository
        self._grocery_repository = grocery_repository
        self._measurement_service = measurement_service
        self._meal_catalog_embedding_service = meal_catalog_embedding_service

    def get_metadata(self) -> AdminMealMetadataResponse:
        categories = [
            MealCategoryResponse(
                id=category.id,
                slug=category.slug.value,
                name=category.name,
                description=category.description,
                img_url=category.img_url,
                sort_order=category.sort_order,
            )
            for category in self._meal_repository.list_categories()
        ]
        cultures = [
            {"value": culture.value, "display_name": culture.value.replace("_", " ").title()}
            for culture in CultureTag
        ]
        meal_types = [
            {"value": meal_type.value, "display_name": meal_type.value.replace("_", " ").title()}
            for meal_type in MealType
        ]
        difficulties = [
            {"value": difficulty.value, "display_name": difficulty.value.replace("_", " ").title()}
            for difficulty in MealDifficulty
        ]
        products, _ = self._grocery_repository.list_all_products(page=1, page_size=1000)
        measurement_units = self._measurement_service.list_units()
        conversion_profiles = self._measurement_service.list_conversion_profiles()

        return AdminMealMetadataResponse(
            categories=categories,
            cultures=cultures,
            meal_types=meal_types,
            difficulties=difficulties,
            supported_countries=[
                {
                    "country_code": item.country_code.value,
                    "currency_code": item.currency_code,
                    "display_name": item.display_name,
                }
                for item in SUPPORTED_COUNTRIES
            ],
            products=[
                {
                    "id": product.id,
                    "name": product.product,
                    "category_id": product.category_id,
                    "img_url": product.img_url,
                }
                for product in products
            ],
            measurement_units=[
                AdminMeasurementUnitOption(
                    code=item.code,
                    display_name=item.display_name,
                    measurement_type=item.measurement_type,
                    canonical_unit=item.canonical_unit,
                    multiplier_to_canonical=item.multiplier_to_canonical,
                    is_fractional_allowed=item.is_fractional_allowed,
                    default_rounding_rule=item.default_rounding_rule,
                    aliases=item.aliases,
                )
                for item in measurement_units
            ],
            ingredient_conversion_profiles=[
                AdminIngredientConversionProfileOption(
                    id=item.id,
                    name=item.name,
                    ingredient_name=item.ingredient_name,
                    linked_product_ids=item.linked_product_ids,
                    unit_code=item.unit_code,
                    canonical_quantity=item.canonical_quantity,
                    canonical_unit=item.canonical_unit,
                    notes=item.notes,
                )
                for item in conversion_profiles
            ],
        )

    def list_meals(
        self,
        *,
        page: int,
        page_size: int,
        search: str | None = None,
        meal_type: MealType | None = None,
        category_id: str | None = None,
    ) -> AdminMealListResponse:
        meals, total = self._meal_repository.list_all_meal_summaries(
            page=page,
            page_size=page_size,
            search=search,
            meal_type=meal_type,
            category_id=category_id,
        )
        return AdminMealListResponse(
            items=[
                AdminMealListItemResponse(
                    id=meal["id"],
                    name=meal["name"],
                    hero_image_url=meal["hero_image_url"],
                    meal_type=meal["meal_type"],
                    category_ids=meal["category_ids"],
                    prep_time_minutes=meal["prep_time_minutes"],
                    cook_time_minutes=meal["cook_time_minutes"],
                    servings=meal["servings"],
                    estimated_cost=self._to_estimated_cost_summary(meal.get("estimated_costs", [])),
                    is_active=bool(meal.get("is_active", True)),
                )
                for meal in meals
            ],
            total=total,
            page=page,
            page_size=page_size,
        )

    def get_meal(self, meal_id: str) -> AdminMealResponse:
        meal = self._meal_repository.get_meal_by_id(meal_id)
        if meal is None:
            raise AdminMealNotFoundError
        return self._to_response(meal)

    def create_meal(self, payload: AdminMealCreateRequest) -> AdminMealResponse:
        self._ensure_categories_exist(payload.category_ids)
        linked_product_ids = self._validate_and_collect_linked_products(payload.ingredient_items)
        normalized_ingredients = self._normalize_ingredient_measurements(payload.ingredient_items)
        self._validate_meal_payload(payload, linked_product_ids)

        meal_id = self._generate_meal_id(payload.name)
        payload_kwargs = self._payload_kwargs(payload, linked_product_ids, normalized_ingredients)
        embedding_payload = self._meal_catalog_embedding_service.create_embedding_payload(
            search_document=self._meal_repository.build_search_document(payload_kwargs)
        )
        try:
            meal = self._meal_repository.create_meal(
                meal_id=meal_id,
                **payload_kwargs,
                **embedding_payload,
            )
        except DuplicateKeyError as exc:
            raise AdminMealAlreadyExistsError from exc
        return self._to_response(meal)

    def update_meal(self, *, meal_id: str, payload: AdminMealCreateRequest) -> AdminMealResponse:
        self._ensure_categories_exist(payload.category_ids)
        linked_product_ids = self._validate_and_collect_linked_products(payload.ingredient_items)
        normalized_ingredients = self._normalize_ingredient_measurements(payload.ingredient_items)
        self._validate_meal_payload(payload, linked_product_ids)
        payload_kwargs = self._payload_kwargs(payload, linked_product_ids, normalized_ingredients)
        embedding_payload = self._meal_catalog_embedding_service.create_embedding_payload(
            search_document=self._meal_repository.build_search_document(payload_kwargs)
        )
        meal = self._meal_repository.update_meal(
            meal_id=meal_id,
            **payload_kwargs,
            **embedding_payload,
        )
        if meal is None:
            raise AdminMealNotFoundError
        return self._to_response(meal)

    def delete_meal(self, meal_id: str) -> None:
        deleted = self._meal_repository.delete_meal(meal_id)
        if not deleted:
            raise AdminMealNotFoundError

    def delete_meals(self, meal_ids: list[str]) -> AdminMealBulkDeleteResponse:
        existing_meal_ids: list[str] = []
        missing_meal_ids: list[str] = []

        for meal_id in meal_ids:
            if self._meal_repository.get_meal_by_id(meal_id) is None:
                missing_meal_ids.append(meal_id)
            else:
                existing_meal_ids.append(meal_id)

        deleted_count = self._meal_repository.delete_meals(existing_meal_ids)
        if deleted_count != len(existing_meal_ids):
            raise AdminMealValidationError("Some selected meals could not be deleted.")

        return AdminMealBulkDeleteResponse(
            deleted_meal_ids=existing_meal_ids,
            missing_meal_ids=missing_meal_ids,
            deleted_count=deleted_count,
        )

    def _ensure_categories_exist(self, category_ids: list[str]) -> list[MealCategory]:
        categories: list[MealCategory] = []
        for category_id in category_ids:
            category = self._meal_repository.get_category(category_id)
            if category is None:
                raise AdminMealCategoryNotFoundError
            categories.append(category)
        return categories

    def _validate_and_collect_linked_products(
        self,
        ingredient_items: list[AdminMealIngredientPayload],
    ) -> list[str]:
        linked_product_ids: list[str] = []
        for ingredient in ingredient_items:
            for product_id in ingredient.linked_product_ids:
                product = self._grocery_repository.get_product_by_id(product_id)
                if product is None:
                    raise AdminMealProductNotFoundError
                if product.id not in linked_product_ids:
                    linked_product_ids.append(product.id)
        return linked_product_ids

    @staticmethod
    def _generate_meal_id(meal_name: str) -> str:
        normalized = "_".join(meal_name.strip().lower().split())
        return f"meal_{normalized}_{uuid4().hex[:8]}"

    @staticmethod
    def _validate_meal_payload(
        payload: AdminMealCreateRequest,
        linked_product_ids: list[str],
    ) -> None:
        if not payload.image_urls:
            raise AdminMealValidationError("Each meal must include at least one image.")
        if not payload.estimated_costs:
            raise AdminMealValidationError("Each meal must include at least one estimated cost.")
        if not linked_product_ids:
            raise AdminMealValidationError(
                "Link at least one ingredient to a real grocery product so the planner can ground the meal."
            )

    @staticmethod
    def _to_estimated_cost_summary(
        estimated_costs: list[dict[str, object]],
    ) -> AdminMealEstimatedCostSummary | None:
        if not estimated_costs:
            return None

        primary_cost = estimated_costs[0]
        return AdminMealEstimatedCostSummary(
            currency_code=primary_cost["currency_code"],
            amount=float(primary_cost["amount"]),
        )

    @staticmethod
    def _payload_kwargs(
        payload: AdminMealCreateRequest,
        linked_product_ids: list[str],
        normalized_ingredients: list[dict[str, object]],
    ) -> dict[str, object]:
        return {
            "name": payload.name,
            "hero_image_url": payload.hero_image_url,
            "image_urls": payload.image_urls,
            "nutritional_specs": [],
            "description": payload.description,
            "meal_type": payload.meal_type.value,
            "meal_types": [meal_type.value for meal_type in payload.meal_types],
            "category_ids": payload.category_ids,
            "culture_tags": [culture.value for culture in payload.culture_tags],
            "diet_rules_supported": payload.diet_rules_supported,
            "allergy_exclusions": payload.allergy_exclusions,
            "prep_time_minutes": payload.prep_time_minutes,
            "cook_time_minutes": payload.cook_time_minutes,
            "difficulty": payload.difficulty.value,
            "servings": payload.servings,
            "nutrition_summary": payload.nutrition_summary.model_dump(mode="json"),
            "estimated_costs": [
                {
                    "country_code": cost.country_code.value,
                    "currency_code": cost.currency_code.value,
                    "amount": cost.amount,
                }
                for cost in payload.estimated_costs
            ],
            "selling_prices": [
                {
                    "country_code": price.country_code.value,
                    "currency_code": price.currency_code.value,
                    "amount_minor": price.amount_minor,
                }
                for price in payload.selling_prices
            ],
            "rating_average": payload.rating_average,
            "rating_count": payload.rating_count,
            "highlight_tags": [tag.value for tag in payload.highlight_tags],
            "recipe_steps": payload.recipe_steps,
            "recipe_step_items": [
                {
                    "instruction": step.instruction,
                    "ingredient_ids": step.ingredient_ids,
                    "image_url": step.image_url,
                }
                for step in payload.recipe_step_items
            ],
            "ingredient_items": normalized_ingredients,
            "linked_product_ids": linked_product_ids,
            "chef_available": payload.chef_available,
            "is_active": payload.is_active,
        }

    def _normalize_ingredient_measurements(
        self,
        ingredient_items: list[AdminMealIngredientPayload],
    ) -> list[dict[str, object]]:
        normalized_items: list[dict[str, object]] = []
        try:
            for ingredient in ingredient_items:
                resolved = self._measurement_service.resolve_ingredient_measurement(
                    quantity=ingredient.quantity,
                    unit=ingredient.unit,
                    unit_code=ingredient.unit_code,
                    measurement_type=ingredient.measurement_type.value if ingredient.measurement_type else None,
                    canonical_quantity=ingredient.canonical_quantity,
                    canonical_unit=ingredient.canonical_unit,
                    conversion_profile_id=ingredient.conversion_profile_id,
                    scaling_behavior=ingredient.scaling_behavior.value if ingredient.scaling_behavior else None,
                    rounding_rule=ingredient.rounding_rule.value if ingredient.rounding_rule else None,
                )
                normalized_items.append(
                    {
                        "id": ingredient.id,
                        "name": ingredient.name,
                        "quantity": ingredient.quantity,
                        "unit": resolved.display_unit,
                        "optional": ingredient.optional,
                        "linked_product_ids": ingredient.linked_product_ids,
                        "measurement_type": resolved.measurement_type.value,
                        "unit_code": resolved.unit_code,
                        "canonical_quantity": resolved.canonical_quantity,
                        "canonical_unit": resolved.canonical_unit,
                        "conversion_profile_id": resolved.conversion_profile_id,
                        "scaling_behavior": resolved.scaling_behavior.value,
                        "rounding_rule": resolved.rounding_rule.value if resolved.rounding_rule else None,
                    }
                )
        except MeasurementValidationError as exc:
            raise AdminMealValidationError(str(exc)) from exc
        return normalized_items

    @staticmethod
    def _to_response(meal: Meal) -> AdminMealResponse:
        return AdminMealResponse(
            id=meal.id,
            name=meal.name,
            hero_image_url=meal.hero_image_url,
            image_urls=meal.image_urls,
            description=meal.description,
            meal_type=meal.meal_type,
            meal_types=meal.meal_types or [meal.meal_type],
            category_ids=meal.category_ids,
            culture_tags=meal.culture_tags,
            diet_rules_supported=meal.diet_rules_supported,
            allergy_exclusions=meal.allergy_exclusions,
            prep_time_minutes=meal.prep_time_minutes,
            cook_time_minutes=meal.cook_time_minutes,
            difficulty=meal.difficulty,
            servings=meal.servings,
            nutrition_summary={
                "calories": meal.nutrition_summary.calories,
                "protein_g": meal.nutrition_summary.protein_g,
                "carbs_g": meal.nutrition_summary.carbs_g,
                "fat_g": meal.nutrition_summary.fat_g,
            },
            estimated_costs=[
                AdminMealEstimatedCostPayload(
                    country_code=cost.country_code,
                    currency_code=cost.currency_code,
                    amount=cost.amount,
                )
                for cost in meal.estimated_costs
            ],
            selling_prices=[
                AdminMealSellingPricePayload(
                    country_code=price.country_code,
                    currency_code=price.currency_code,
                    amount_minor=price.amount_minor,
                )
                for price in meal.selling_prices
            ],
            rating_average=meal.rating_average,
            rating_count=meal.rating_count,
            highlight_tags=meal.highlight_tags,
            recipe_steps=meal.recipe_steps,
            ingredient_items=[
                AdminMealIngredientPayload(
                    id=item.id,
                    name=item.name,
                    quantity=item.quantity,
                    unit=item.unit,
                    optional=item.optional,
                    linked_product_ids=item.linked_product_ids,
                    measurement_type=item.measurement_type,
                    unit_code=item.unit_code,
                    canonical_quantity=item.canonical_quantity,
                    canonical_unit=item.canonical_unit,
                    conversion_profile_id=item.conversion_profile_id,
                    scaling_behavior=item.scaling_behavior,
                    rounding_rule=item.rounding_rule,
                )
                for item in meal.ingredient_items
            ],
            recipe_step_items=[
                AdminMealRecipeStepPayload(
                    instruction=step.instruction,
                    ingredient_ids=step.ingredient_ids,
                    image_url=step.image_url,
                )
                for step in meal.recipe_step_items
            ],
            linked_product_ids=meal.linked_product_ids,
            chef_available=meal.chef_available,
            is_active=meal.is_active,
            created_at=meal.created_at,
            updated_at=meal.updated_at,
        )
