from dataclasses import dataclass
from typing import Literal

from app.models.grocery import CountryCode, CurrencyCode, GroceryProduct
from app.models.meal import Meal, MealCategory, MealType
from app.repositories.grocery_repository import GroceryRepository
from app.repositories.meal_favorite_repository import MealFavoriteRepository
from app.repositories.meal_repository import MealRepository
from app.schemas.meal import (
    LinkedGroceryProductResponse,
    MealCategoryResponse,
    MealDetailResponse,
    MealEstimatedCostResponse,
    MealIngredientResponse,
    MealListItemResponse,
    MealListResponse,
    MealNutritionSummaryResponse,
    MealRecipeStepResponse,
)

MealSortOption = Literal["popular", "price_low_high", "price_high_low", "rating", "quickest"]
MealBudgetTier = Literal["$", "$$", "$$$", "$$$$"]


class MealCategoryNotFoundError(Exception):
    pass


class MealNotFoundError(Exception):
    pass


@dataclass(frozen=True, slots=True)
class ResolvedMealCost:
    country_code: CountryCode
    currency_code: CurrencyCode
    amount: float


class MealService:
    def __init__(
        self,
        meal_repository: MealRepository,
        grocery_repository: GroceryRepository,
        meal_favorite_repository: MealFavoriteRepository,
    ) -> None:
        self._meal_repository = meal_repository
        self._grocery_repository = grocery_repository
        self._meal_favorite_repository = meal_favorite_repository

    def list_categories(self) -> list[MealCategoryResponse]:
        return [
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

    def list_meals(
        self,
        *,
        country: CountryCode | None,
        meal_type: MealType | None,
        category_id: str | None,
        culture: str | None,
        cuisine: str | None = None,
        dietary: list[str] | None = None,
        nutrition_focus: list[str] | None = None,
        cook_time_max: int | None = None,
        budget_tier: MealBudgetTier | None = None,
        sort: MealSortOption | None = None,
        search: str | None,
        page: int,
        page_size: int,
        current_user_id: str | None = None,
    ) -> MealListResponse:
        if category_id and self._meal_repository.get_category(category_id) is None:
            raise MealCategoryNotFoundError

        meals, total = self._meal_repository.list_meals(
            meal_type=meal_type,
            category_id=category_id,
            culture=cuisine or culture,
            dietary=dietary,
            nutrition_focus=nutrition_focus,
            cook_time_max=cook_time_max,
            budget_tier=budget_tier,
            country=country,
            sort=sort,
            search=search,
            page=page,
            page_size=page_size,
        )
        favorited_meal_ids = (
            self._meal_favorite_repository.list_favorited_meal_ids(user_id=current_user_id)
            if current_user_id is not None
            else set()
        )

        return MealListResponse(
            items=[
                self._to_list_item_response(meal, country, is_favorited=meal.id in favorited_meal_ids)
                for meal in meals
            ],
            total=total,
            page=page,
            page_size=page_size,
        )

    def get_meal(
        self,
        meal_id: str,
        *,
        country: CountryCode | None,
        current_user_id: str | None = None,
    ) -> MealDetailResponse:
        meal = self._meal_repository.get_meal(meal_id)
        if meal is None:
            raise MealNotFoundError

        is_favorited = (
            self._meal_favorite_repository.is_favorited(user_id=current_user_id, meal_id=meal_id)
            if current_user_id is not None
            else False
        )
        linked_products = self._grocery_repository.list_products_by_ids(meal.linked_product_ids)
        list_item = self._to_list_item_response(meal, country, is_favorited=is_favorited)

        return MealDetailResponse(
            **list_item.model_dump(),
            diet_rules_supported=meal.diet_rules_supported,
            allergy_exclusions=meal.allergy_exclusions,
            recipe_steps=meal.recipe_steps,
            recipe_step_items=[
                MealRecipeStepResponse(
                    instruction=step.instruction,
                    ingredient_ids=step.ingredient_ids,
                    image_url=step.image_url,
                )
                for step in meal.recipe_step_items
            ],
            ingredient_items=[
                MealIngredientResponse(
                    id=ingredient.id,
                    name=ingredient.name,
                    quantity=ingredient.quantity,
                    unit=ingredient.unit,
                    optional=ingredient.optional,
                    linked_product_ids=ingredient.linked_product_ids,
                    measurement_type=ingredient.measurement_type,
                    unit_code=ingredient.unit_code,
                    canonical_quantity=ingredient.canonical_quantity,
                    canonical_unit=ingredient.canonical_unit,
                    conversion_profile_id=ingredient.conversion_profile_id,
                    scaling_behavior=ingredient.scaling_behavior,
                    rounding_rule=ingredient.rounding_rule,
                )
                for ingredient in meal.ingredient_items
            ],
            linked_product_ids=meal.linked_product_ids,
            linked_products=[
                LinkedGroceryProductResponse(
                    id=product.id,
                    name=product.product,
                    img_url=product.img_url,
                    resolved_price=self._resolve_product_price(product, country),
                )
                for product in linked_products
            ],
        )

    def favorite_meal(self, *, user_id: str, meal_id: str) -> None:
        if self._meal_repository.get_meal(meal_id) is None:
            raise MealNotFoundError
        self._meal_favorite_repository.add(user_id=user_id, meal_id=meal_id)

    def unfavorite_meal(self, *, user_id: str, meal_id: str) -> None:
        self._meal_favorite_repository.remove(user_id=user_id, meal_id=meal_id)

    def _to_list_item_response(
        self,
        meal: Meal,
        country: CountryCode | None,
        *,
        is_favorited: bool = False,
    ) -> MealListItemResponse:
        return MealListItemResponse(
            id=meal.id,
            name=meal.name,
            hero_image_url=meal.hero_image_url,
            image_urls=meal.image_urls,
            description=meal.description,
            meal_type=meal.meal_type,
            category_ids=meal.category_ids,
            culture_tags=meal.culture_tags,
            prep_time_minutes=meal.prep_time_minutes,
            cook_time_minutes=meal.cook_time_minutes,
            difficulty=meal.difficulty,
            servings=meal.servings,
            nutrition_summary=MealNutritionSummaryResponse(
                calories=meal.nutrition_summary.calories,
                protein_g=meal.nutrition_summary.protein_g,
                carbs_g=meal.nutrition_summary.carbs_g,
                fat_g=meal.nutrition_summary.fat_g,
            ),
            resolved_estimated_cost=self._resolve_meal_cost(meal, country),
            resolved_selling_price=self._resolve_meal_selling_price(meal, country),
            rating_average=meal.rating_average,
            rating_count=meal.rating_count,
            highlight_tags=meal.highlight_tags,
            is_favorited=is_favorited,
            chef_available=meal.chef_available,
        )

    @staticmethod
    def _to_estimated_cost_response(resolved_cost: ResolvedMealCost) -> MealEstimatedCostResponse:
        return MealEstimatedCostResponse(
            country_code=resolved_cost.country_code,
            currency_code=resolved_cost.currency_code,
            amount=resolved_cost.amount,
        )

    def _resolve_meal_cost(
        self,
        meal: Meal,
        country: CountryCode | None,
    ) -> MealEstimatedCostResponse | None:
        if country is None:
            return None

        cost = next(
            (
                entry
                for entry in meal.estimated_costs
                if entry.country_code == country
            ),
            None,
        )
        if cost is None:
            return None

        return self._to_estimated_cost_response(
            ResolvedMealCost(
                country_code=cost.country_code,
                currency_code=cost.currency_code,
                amount=cost.amount,
            )
        )

    def _resolve_meal_selling_price(
        self,
        meal: Meal,
        country: CountryCode | None,
    ) -> MealEstimatedCostResponse | None:
        if country is None:
            return None

        price = next(
            (entry for entry in meal.selling_prices if entry.country_code == country),
            None,
        )
        if price is None:
            return None

        return self._to_estimated_cost_response(
            ResolvedMealCost(
                country_code=price.country_code,
                currency_code=price.currency_code,
                amount=price.amount_minor / 100,
            )
        )

    def _resolve_product_price(
        self,
        product: GroceryProduct,
        country: CountryCode | None,
    ) -> MealEstimatedCostResponse | None:
        if country is None:
            return None

        price = next(
            (
                entry
                for entry in product.prices
                if entry.is_active and entry.country_code == country
            ),
            None,
        )
        if price is None:
            return None

        return self._to_estimated_cost_response(
            ResolvedMealCost(
                country_code=price.country_code,
                currency_code=price.currency_code,
                amount=price.amount,
            )
        )
