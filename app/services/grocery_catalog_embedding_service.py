from __future__ import annotations

from dataclasses import dataclass

from app.repositories.grocery_repository import GroceryRepository
from app.services.meal_search_embedding_service import (
    MealSearchEmbeddingService,
    MealSearchEmbeddingServiceError,
)


class GroceryCatalogEmbeddingError(Exception):
    pass


@dataclass(frozen=True, slots=True)
class GroceryCatalogEmbeddingResult:
    product_id: str
    search_document: str
    embedding_model: str


class GroceryCatalogEmbeddingService:
    def __init__(
        self,
        grocery_repository: GroceryRepository,
        embedding_service: MealSearchEmbeddingService,
    ) -> None:
        self._grocery_repository = grocery_repository
        self._embedding_service = embedding_service

    def create_embedding_payload(
        self,
        *,
        search_document: str,
    ) -> dict[str, object]:
        try:
            vector = self._embedding_service.embed_text(search_document)
        except MealSearchEmbeddingServiceError as exc:
            raise GroceryCatalogEmbeddingError(str(exc)) from exc
        return {
            "search_document": search_document,
            "search_embedding": vector,
            "search_embedding_model": self._embedding_service.model_name,
            "search_embedding_source_hash": self._grocery_repository.hash_search_document(
                search_document
            ),
        }

    def backfill_product_embedding(self, *, product_id: str) -> GroceryCatalogEmbeddingResult:
        candidate = self._grocery_repository.get_product_search_candidate_by_id(product_id)
        if candidate is None:
            raise GroceryCatalogEmbeddingError(f"Grocery product '{product_id}' was not found.")
        payload = self.create_embedding_payload(search_document=candidate.search_document)
        self._grocery_repository.update_product_search_embedding(
            product_id=product_id,
            search_document=str(payload["search_document"]),
            search_embedding=list(payload["search_embedding"]),
            embedding_model=str(payload["search_embedding_model"]),
        )
        return GroceryCatalogEmbeddingResult(
            product_id=product_id,
            search_document=str(payload["search_document"]),
            embedding_model=str(payload["search_embedding_model"]),
        )
