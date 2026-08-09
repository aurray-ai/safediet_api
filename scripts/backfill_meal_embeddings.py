import argparse

from app.core.config import get_settings
from app.db.mongodb import mongo_manager
from app.repositories.meal_repository import MealRepository
from app.services.meal_catalog_embedding_service import (
    MealCatalogEmbeddingError,
    MealCatalogEmbeddingService,
)
from app.services.meal_search_embedding_service import MealSearchEmbeddingService


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Backfill semantic search embeddings for catalog meals."
    )
    parser.add_argument("--meal-id", default=None, help="Optional single meal id to backfill.")
    parser.add_argument(
        "--only-missing",
        action="store_true",
        help="Only backfill meals with missing or stale embeddings.",
    )
    args = parser.parse_args()

    settings = get_settings()
    mongo_manager.connect()
    try:
        meal_repository = MealRepository(
            mongo_manager.meal_categories_collection(),
            mongo_manager.meals_collection(),
        )
        embedding_service = MealSearchEmbeddingService(
            api_key=(
                settings.openai_api_key.get_secret_value()
                if settings.openai_api_key is not None
                else None
            ),
            model_name=settings.openai_meal_search_embedding_model,
            timeout_seconds=settings.openai_meal_search_embedding_timeout_seconds,
        )
        catalog_embedding_service = MealCatalogEmbeddingService(
            meal_repository=meal_repository,
            embedding_service=embedding_service,
        )

        query: dict[str, object] = {}
        if args.meal_id:
            query["_id"] = args.meal_id

        processed = 0
        skipped = 0
        failed = 0
        for document in mongo_manager.meals_collection().find(query, {"_id": 1}):
            meal_id = str(document["_id"])
            if args.only_missing:
                candidate = meal_repository.get_meal_search_candidate_by_id(meal_id)
                if candidate is not None and (
                    candidate.search_embedding
                    and candidate.search_embedding_model == embedding_service.model_name
                    and candidate.search_embedding_source_hash == candidate.search_document_hash
                ):
                    skipped += 1
                    continue
            try:
                catalog_embedding_service.backfill_meal_embedding(meal_id=meal_id)
                processed += 1
            except MealCatalogEmbeddingError as exc:
                failed += 1
                print(f"FAILED {meal_id}: {exc}")

        print(
            f"Meal embedding backfill complete. processed={processed} skipped={skipped} failed={failed}"
        )
    finally:
        mongo_manager.close()


if __name__ == "__main__":
    main()
