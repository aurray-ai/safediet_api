from __future__ import annotations

import math
from dataclasses import dataclass

from app.models.grocery import CountryCode
from app.models.meal import Meal, MealEstimatedCost, MealType
from app.repositories.meal_repository import MealRepository, MealSearchCandidate
from app.services.meal_search_embedding_service import (
    MealSearchEmbeddingService,
    MealSearchEmbeddingServiceError,
)


class MealSemanticSearchError(Exception):
    pass


@dataclass(frozen=True, slots=True)
class MealSemanticSearchItem:
    meal: Meal
    semantic_score: float
    why_it_matched: list[str]
    estimated_cost_amount: float | None


class MealSemanticSearchService:
    def __init__(
        self,
        meal_repository: MealRepository,
        embedding_service: MealSearchEmbeddingService,
        *,
        candidate_pool_limit: int = 180,
        embedding_batch_size: int = 24,
    ) -> None:
        self._meal_repository = meal_repository
        self._embedding_service = embedding_service
        self._candidate_pool_limit = max(candidate_pool_limit, 24)
        self._embedding_batch_size = max(embedding_batch_size, 1)

    def search(
        self,
        *,
        semantic_query: str,
        meal_type: str | None,
        requested_culture: str | None,
        diet_rules: list[str] | None,
        allergies: list[str] | None,
        country_code: str | None,
        low_budget_mode: bool,
        goal: str | None,
        limit: int,
    ) -> list[MealSemanticSearchItem]:
        resolved_meal_type = MealType(meal_type) if meal_type else None
        candidate_records = self._meal_repository.list_semantic_search_candidates(
            meal_type=resolved_meal_type,
            limit=max(limit * 12, self._candidate_pool_limit),
        )
        if not candidate_records:
            return []

        required_diet_rules = {str(item).strip().lower() for item in (diet_rules or []) if str(item).strip()}
        required_allergy_exclusions = {str(item).strip().lower() for item in (allergies or []) if str(item).strip()}
        filtered_candidates = [
            candidate
            for candidate in candidate_records
            if self._supports_constraints(
                candidate,
                required_diet_rules=required_diet_rules,
                required_allergy_exclusions=required_allergy_exclusions,
            )
        ]
        if not filtered_candidates:
            return []

        try:
            query_embedding = self._embedding_service.embed_text(
                self._build_query_context(
                    semantic_query=semantic_query,
                    meal_type=meal_type,
                    requested_culture=requested_culture,
                    goal=goal,
                    low_budget_mode=low_budget_mode,
                )
            )
        except MealSearchEmbeddingServiceError as exc:
            raise MealSemanticSearchError(str(exc)) from exc

        resolved_country_code = CountryCode(country_code) if country_code else None
        scored: list[MealSemanticSearchItem] = []
        missing_embedding_candidates = 0
        for candidate in filtered_candidates:
            if (
                not candidate.search_embedding
                or candidate.search_embedding_model != self._embedding_service.model_name
                or candidate.search_embedding_source_hash != candidate.search_document_hash
            ):
                missing_embedding_candidates += 1
                continue
            estimated_cost = self._resolved_cost_amount(
                candidate.meal.estimated_costs,
                resolved_country_code,
            )
            semantic_score = self._cosine_similarity(
                query_embedding,
                list(candidate.search_embedding or ()),
            )
            semantic_score, reasons = self._apply_domain_boosts(
                candidate=candidate,
                requested_culture=requested_culture,
                goal=goal,
                low_budget_mode=low_budget_mode,
                estimated_cost_amount=estimated_cost,
                semantic_score=semantic_score,
            )
            if semantic_score <= 0:
                continue
            scored.append(
                MealSemanticSearchItem(
                    meal=candidate.meal,
                    semantic_score=semantic_score,
                    why_it_matched=reasons,
                    estimated_cost_amount=estimated_cost,
                )
            )

        if not scored and missing_embedding_candidates > 0:
            raise MealSemanticSearchError(
                "Meal catalog embeddings are not ready for semantic search. Backfill meal embeddings first."
            )

        scored.sort(
            key=lambda item: (
                item.semantic_score,
                item.meal.nutrition_summary.protein_g,
                -(item.estimated_cost_amount or math.inf),
                -(item.meal.prep_time_minutes + item.meal.cook_time_minutes),
            ),
            reverse=True,
        )
        return scored[:limit]

    @staticmethod
    def _supports_constraints(
        candidate: MealSearchCandidate,
        *,
        required_diet_rules: set[str],
        required_allergy_exclusions: set[str],
    ) -> bool:
        supported_diet_rules = {
            str(item).strip().lower()
            for item in candidate.meal.diet_rules_supported
            if str(item).strip()
        }
        supported_allergy_exclusions = {
            str(item).strip().lower()
            for item in candidate.meal.allergy_exclusions
            if str(item).strip()
        }
        return (
            required_diet_rules.issubset(supported_diet_rules)
            and required_allergy_exclusions.issubset(supported_allergy_exclusions)
        )

    @staticmethod
    def _build_query_context(
        *,
        semantic_query: str,
        meal_type: str | None,
        requested_culture: str | None,
        goal: str | None,
        low_budget_mode: bool,
    ) -> str:
        parts = [
            semantic_query.strip(),
            f"meal type {meal_type}" if meal_type else "",
            f"cuisine {requested_culture}" if requested_culture else "",
            f"goal {goal}" if goal else "",
            "budget friendly affordable lower cost" if low_budget_mode else "",
        ]
        return ". ".join(part for part in parts if part)

    def _apply_domain_boosts(
        self,
        *,
        candidate: MealSearchCandidate,
        requested_culture: str | None,
        goal: str | None,
        low_budget_mode: bool,
        estimated_cost_amount: float | None,
        semantic_score: float,
    ) -> tuple[float, list[str]]:
        score = max(semantic_score, 0.0)
        reasons: list[str] = []
        normalized_culture = str(requested_culture or "").strip().lower()
        if normalized_culture and normalized_culture in {
            str(item).strip().lower() for item in candidate.meal.culture_tags
        }:
            score += 0.08
            reasons.append(f"Strong {normalized_culture.capitalize()} cuisine fit")

        protein = float(candidate.meal.nutrition_summary.protein_g)
        calories = int(candidate.meal.nutrition_summary.calories)
        normalized_goal = str(goal or "").strip().lower()

        if normalized_goal in {"gain_weight", "build_muscle"}:
            if protein >= 25:
                score += 0.07
                reasons.append("Supports a strong protein target")
            if calories >= 500:
                score += 0.05
                reasons.append("Fits a higher-energy goal")
        elif normalized_goal in {"lose_weight", "maintain"}:
            if protein >= 20:
                score += 0.04
                reasons.append("Supports a balanced protein target")
            if calories <= 700:
                score += 0.03
                reasons.append("Keeps calories in a practical range")

        if low_budget_mode and estimated_cost_amount is not None and estimated_cost_amount <= 4.5:
            score += 0.06
            reasons.append("Fits a lower-cost budget preference")

        if not reasons:
            reasons.append("Strong semantic match with the meal catalog")
        return min(score, 1.0), reasons[:3]

    @staticmethod
    def _cosine_similarity(left: list[float], right: list[float]) -> float:
        if not left or not right or len(left) != len(right):
            return 0.0
        numerator = sum(a * b for a, b in zip(left, right, strict=False))
        left_norm = math.sqrt(sum(value * value for value in left))
        right_norm = math.sqrt(sum(value * value for value in right))
        if left_norm <= 0 or right_norm <= 0:
            return 0.0
        return max(numerator / (left_norm * right_norm), 0.0)

    @staticmethod
    def _resolved_cost_amount(
        estimated_costs: list[MealEstimatedCost],
        country_code: CountryCode | None,
    ) -> float | None:
        if country_code is None:
            return None
        for cost in estimated_costs:
            if cost.country_code == country_code:
                return float(cost.amount)
        return None
