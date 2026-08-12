from __future__ import annotations

import math
from dataclasses import dataclass

from app.models.grocery import GroceryProduct
from app.repositories.grocery_repository import GroceryRepository


@dataclass(frozen=True, slots=True)
class GrocerySimilarProductItem:
    product: GroceryProduct
    similarity_score: float


class GrocerySimilarProductsService:
    def __init__(
        self,
        grocery_repository: GroceryRepository,
        *,
        candidate_pool_limit: int = 60,
    ) -> None:
        self._grocery_repository = grocery_repository
        self._candidate_pool_limit = max(candidate_pool_limit, 12)

    def find_similar(self, *, product_id: str, limit: int) -> list[GrocerySimilarProductItem]:
        anchor = self._grocery_repository.get_product_search_candidate_by_id(product_id)
        if anchor is None or not anchor.search_embedding:
            return []

        candidates = self._grocery_repository.list_similar_product_candidates(
            category_id=anchor.product.category_id,
            exclude_product_id=product_id,
            limit=max(limit * 6, self._candidate_pool_limit),
        )
        if not candidates:
            return []

        scored: list[GrocerySimilarProductItem] = []
        for candidate in candidates:
            if (
                not candidate.search_embedding
                or candidate.search_embedding_model != anchor.search_embedding_model
            ):
                continue
            score = self._cosine_similarity(
                list(anchor.search_embedding),
                list(candidate.search_embedding),
            )
            if score <= 0:
                continue
            scored.append(GrocerySimilarProductItem(product=candidate.product, similarity_score=score))

        scored.sort(key=lambda item: item.similarity_score, reverse=True)
        return scored[:limit]

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
