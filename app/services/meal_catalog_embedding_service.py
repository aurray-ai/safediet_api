from __future__ import annotations

from dataclasses import dataclass

from app.repositories.meal_repository import MealRepository
from app.services.meal_search_embedding_service import (
    MealSearchEmbeddingService,
    MealSearchEmbeddingServiceError,
)


class MealCatalogEmbeddingError(Exception):
    pass


@dataclass(frozen=True, slots=True)
class MealCatalogEmbeddingResult:
    meal_id: str
    search_document: str
    embedding_model: str


class MealCatalogEmbeddingService:
    def __init__(
        self,
        meal_repository: MealRepository,
        embedding_service: MealSearchEmbeddingService,
    ) -> None:
        self._meal_repository = meal_repository
        self._embedding_service = embedding_service

    def create_embedding_payload(
        self,
        *,
        search_document: str,
    ) -> dict[str, object]:
        try:
            vector = self._embedding_service.embed_text(search_document)
        except MealSearchEmbeddingServiceError as exc:
            raise MealCatalogEmbeddingError(str(exc)) from exc
        return {
            "search_document": search_document,
            "search_embedding": vector,
            "search_embedding_model": self._embedding_service.model_name,
            "search_embedding_source_hash": self._meal_repository.hash_search_document(
                search_document
            ),
        }

    def backfill_meal_embedding(self, *, meal_id: str) -> MealCatalogEmbeddingResult:
        candidate = self._meal_repository.get_meal_search_candidate_by_id(meal_id)
        if candidate is None:
            raise MealCatalogEmbeddingError(f"Meal '{meal_id}' was not found.")
        payload = self.create_embedding_payload(search_document=candidate.search_document)
        self._meal_repository.update_meal_search_embedding(
            meal_id=meal_id,
            search_document=str(payload["search_document"]),
            search_embedding=list(payload["search_embedding"]),
            embedding_model=str(payload["search_embedding_model"]),
        )
        return MealCatalogEmbeddingResult(
            meal_id=meal_id,
            search_document=str(payload["search_document"]),
            embedding_model=str(payload["search_embedding_model"]),
        )
