from __future__ import annotations

import hashlib
import unittest
from datetime import datetime, timezone

from app.models.grocery import CountryCode, CurrencyCode
from app.models.meal import (
    Meal,
    MealDifficulty,
    MealEstimatedCost,
    MealIngredient,
    MealNutritionSummary,
    MealRecipeStep,
    MealType,
)
from app.repositories.meal_repository import MealSearchCandidate
from app.services.meal_search_embedding_service import MealSearchEmbeddingServiceError
from app.services.meal_semantic_search_service import (
    MealSemanticSearchError,
    MealSemanticSearchService,
)


def _hash_document(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


class StubMealRepository:
    def __init__(self, candidates: list[MealSearchCandidate]) -> None:
        self._candidates = candidates
        self.embedding_updates: list[dict[str, object]] = []

    def list_semantic_search_candidates(
        self,
        *,
        meal_type: MealType | None,
        limit: int,
    ) -> list[MealSearchCandidate]:
        items = [
            candidate
            for candidate in self._candidates
            if meal_type is None or candidate.meal.meal_type == meal_type
        ]
        return items[:limit]

    def update_meal_search_embedding(
        self,
        *,
        meal_id: str,
        search_document: str,
        search_embedding: list[float],
        embedding_model: str,
    ) -> None:
        self.embedding_updates.append(
            {
                "meal_id": meal_id,
                "search_document": search_document,
                "search_embedding": list(search_embedding),
                "embedding_model": embedding_model,
            }
        )
        for index, candidate in enumerate(self._candidates):
            if candidate.meal.id != meal_id:
                continue
            self._candidates[index] = MealSearchCandidate(
                meal=candidate.meal,
                search_document=search_document,
                search_document_hash=_hash_document(search_document),
                search_embedding=tuple(search_embedding),
                search_embedding_model=embedding_model,
                search_embedding_source_hash=_hash_document(search_document),
                search_embedding_updated_at=datetime.now(timezone.utc),
            )


class StubEmbeddingService:
    def __init__(self, vector_by_text: dict[str, list[float]], *, model_name: str = "test-embed-1") -> None:
        self.model_name = model_name
        self._vector_by_text = vector_by_text
        self.embedded_texts: list[str] = []

    def embed_text(self, value: str) -> list[float]:
        self.embedded_texts.append(value)
        try:
            return list(self._vector_by_text[value])
        except KeyError as exc:
            raise MealSearchEmbeddingServiceError(f"Missing vector for {value}") from exc

    def embed_texts(self, values: list[str]) -> list[list[float]]:
        return [self.embed_text(value) for value in values]


def build_meal(
    *,
    meal_id: str,
    name: str,
    description: str,
    meal_type: MealType,
    culture_tags: list[str],
    diet_rules_supported: list[str],
    allergy_exclusions: list[str],
    protein_g: float,
    calories: int,
    total_minutes: int,
    cost_gbp: float,
) -> Meal:
    return Meal(
        id=meal_id,
        name=name,
        hero_image_url="https://example.com/meal.jpg",
        image_urls=["https://example.com/meal.jpg"],
        description=description,
        meal_type=meal_type,
        category_ids=[],
        culture_tags=culture_tags,
        diet_rules_supported=diet_rules_supported,
        allergy_exclusions=allergy_exclusions,
        prep_time_minutes=max(total_minutes // 2, 1),
        cook_time_minutes=max(total_minutes - (total_minutes // 2), 1),
        difficulty=MealDifficulty.EASY,
        servings=1,
        nutritional_specs=[],
        nutrition_summary=MealNutritionSummary(
            calories=calories,
            protein_g=protein_g,
            carbs_g=40,
            fat_g=20,
        ),
        estimated_costs=[
            MealEstimatedCost(
                country_code=CountryCode.UNITED_KINGDOM,
                currency_code=CurrencyCode.POUND_STERLING,
                amount=cost_gbp,
            )
        ],
        recipe_steps=["Cook and serve"],
        recipe_step_items=[MealRecipeStep(instruction="Cook and serve", ingredient_ids=[])],
        ingredient_items=[
            MealIngredient(
                id="ingredient-1",
                name="Eggs",
                quantity=2.0,
                unit="pcs",
                optional=False,
                linked_product_ids=[],
            )
        ],
        linked_product_ids=[],
        chef_available=False,
        is_active=True,
        created_at=datetime(2026, 6, 1, tzinfo=timezone.utc),
        updated_at=datetime(2026, 6, 10, tzinfo=timezone.utc),
    )


def build_candidate(
    *,
    meal: Meal,
    search_document: str,
    embedding: list[float] | None,
    embedding_model: str | None = "test-embed-1",
    source_hash: str | None = None,
) -> MealSearchCandidate:
    search_document_hash = _hash_document(search_document)
    return MealSearchCandidate(
        meal=meal,
        search_document=search_document,
        search_document_hash=search_document_hash,
        search_embedding=tuple(embedding) if embedding is not None else None,
        search_embedding_model=embedding_model if embedding is not None else None,
        search_embedding_source_hash=source_hash if embedding is not None else None,
        search_embedding_updated_at=datetime(2026, 6, 10, tzinfo=timezone.utc)
        if embedding is not None
        else None,
    )


class MealSemanticSearchServiceTests(unittest.TestCase):
    def test_search_prefers_embedding_similarity_then_domain_boosts(self) -> None:
        british_query = (
            "high protein British breakfast for weight gain that is affordable and filling. "
            "meal type breakfast. cuisine british. goal gain_weight. budget friendly affordable lower cost"
        )
        repo = StubMealRepository(
            [
                build_candidate(
                    meal=build_meal(
                        meal_id="meal-1",
                        name="Full Scottish Breakfast",
                        description="A hearty British breakfast with eggs, beans, toast, and turkey sausage.",
                        meal_type=MealType.BREAKFAST,
                        culture_tags=["british"],
                        diet_rules_supported=["halal"],
                        allergy_exclusions=["peanuts"],
                        protein_g=34,
                        calories=640,
                        total_minutes=25,
                        cost_gbp=3.9,
                    ),
                    search_document="british hearty breakfast eggs beans toast sausage high protein budget",
                    embedding=[0.98, 0.02],
                    source_hash=_hash_document(
                        "british hearty breakfast eggs beans toast sausage high protein budget"
                    ),
                ),
                build_candidate(
                    meal=build_meal(
                        meal_id="meal-2",
                        name="Berry Oat Bowl",
                        description="A light oat bowl with berries and yogurt.",
                        meal_type=MealType.BREAKFAST,
                        culture_tags=["american"],
                        diet_rules_supported=["vegetarian"],
                        allergy_exclusions=[],
                        protein_g=12,
                        calories=320,
                        total_minutes=10,
                        cost_gbp=4.8,
                    ),
                    search_document="berry oats yogurt light breakfast",
                    embedding=[0.12, 0.88],
                    source_hash=_hash_document("berry oats yogurt light breakfast"),
                ),
            ]
        )
        embeddings = StubEmbeddingService(
            {
                british_query: [1.0, 0.0],
            }
        )
        service = MealSemanticSearchService(repo, embeddings)

        results = service.search(
            semantic_query="high protein British breakfast for weight gain that is affordable and filling",
            meal_type="breakfast",
            requested_culture="british",
            diet_rules=["halal"],
            allergies=["peanuts"],
            country_code="GB",
            low_budget_mode=True,
            goal="gain_weight",
            limit=4,
        )

        self.assertEqual("meal-1", results[0].meal.id)
        self.assertGreater(results[0].semantic_score, 0.9)
        self.assertTrue(any("British" in reason for reason in results[0].why_it_matched))

    def test_search_raises_clean_error_when_candidates_lack_ready_embeddings(self) -> None:
        repo = StubMealRepository(
            [
                build_candidate(
                    meal=build_meal(
                        meal_id="meal-1",
                        name="Chicken Rice Bowl",
                        description="Simple chicken rice bowl.",
                        meal_type=MealType.LUNCH,
                        culture_tags=["british"],
                        diet_rules_supported=["halal"],
                        allergy_exclusions=["peanuts"],
                        protein_g=31,
                        calories=540,
                        total_minutes=20,
                        cost_gbp=4.2,
                    ),
                    search_document="quick chicken rice lunch budget",
                    embedding=None,
                ),
            ]
        )
        embeddings = StubEmbeddingService(
            {
                "quick affordable lunch. meal type lunch. goal maintain. budget friendly affordable lower cost": [1.0, 0.0],
            }
        )
        service = MealSemanticSearchService(repo, embeddings, embedding_batch_size=8)

        with self.assertRaises(MealSemanticSearchError):
            service.search(
                semantic_query="quick affordable lunch",
                meal_type="lunch",
                requested_culture=None,
                diet_rules=["halal"],
                allergies=["peanuts"],
                country_code="GB",
                low_budget_mode=True,
                goal="maintain",
                limit=3,
            )
    def test_search_raises_clean_error_when_embedding_service_is_unavailable(self) -> None:
        repo = StubMealRepository(
            [
                build_candidate(
                    meal=build_meal(
                        meal_id="meal-1",
                        name="Chicken Rice Bowl",
                        description="Simple chicken rice bowl.",
                        meal_type=MealType.LUNCH,
                        culture_tags=["british"],
                        diet_rules_supported=["halal"],
                        allergy_exclusions=["peanuts"],
                        protein_g=31,
                        calories=540,
                        total_minutes=20,
                        cost_gbp=4.2,
                    ),
                    search_document="quick chicken rice lunch budget",
                    embedding=None,
                ),
            ]
        )

        class FailingEmbeddingService:
            model_name = "test-embed-1"

            @staticmethod
            def embed_text(value: str) -> list[float]:
                raise MealSearchEmbeddingServiceError("Embeddings unavailable.")

            @staticmethod
            def embed_texts(values: list[str]) -> list[list[float]]:
                raise MealSearchEmbeddingServiceError("Embeddings unavailable.")

        service = MealSemanticSearchService(repo, FailingEmbeddingService())

        with self.assertRaises(MealSemanticSearchError):
            service.search(
                semantic_query="quick affordable lunch",
                meal_type="lunch",
                requested_culture=None,
                diet_rules=["halal"],
                allergies=["peanuts"],
                country_code="GB",
                low_budget_mode=True,
                goal="maintain",
                limit=3,
            )


if __name__ == "__main__":
    unittest.main()
