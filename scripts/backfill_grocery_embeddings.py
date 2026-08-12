import argparse

from app.core.config import get_settings
from app.db.mongodb import mongo_manager
from app.repositories.grocery_repository import GroceryRepository
from app.services.grocery_catalog_embedding_service import (
    GroceryCatalogEmbeddingError,
    GroceryCatalogEmbeddingService,
)
from app.services.meal_search_embedding_service import MealSearchEmbeddingService


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Backfill semantic search embeddings for grocery products."
    )
    parser.add_argument("--product-id", default=None, help="Optional single product id to backfill.")
    parser.add_argument(
        "--only-missing",
        action="store_true",
        help="Only backfill products with missing or stale embeddings.",
    )
    args = parser.parse_args()

    settings = get_settings()
    mongo_manager.connect()
    try:
        grocery_repository = GroceryRepository(
            mongo_manager.grocery_categories_collection(),
            mongo_manager.grocery_products_collection(),
        )
        embedding_service = MealSearchEmbeddingService(
            api_key=(
                settings.openai_api_key.get_secret_value()
                if settings.openai_api_key is not None
                else None
            ),
            model_name=settings.openai_grocery_search_embedding_model,
            timeout_seconds=settings.openai_grocery_search_embedding_timeout_seconds,
        )
        catalog_embedding_service = GroceryCatalogEmbeddingService(
            grocery_repository=grocery_repository,
            embedding_service=embedding_service,
        )

        query: dict[str, object] = {}
        if args.product_id:
            query["_id"] = args.product_id

        processed = 0
        skipped = 0
        failed = 0
        for document in mongo_manager.grocery_products_collection().find(query, {"_id": 1}):
            product_id = str(document["_id"])
            if args.only_missing:
                candidate = grocery_repository.get_product_search_candidate_by_id(product_id)
                if candidate is not None and (
                    candidate.search_embedding
                    and candidate.search_embedding_model == embedding_service.model_name
                    and candidate.search_embedding_source_hash == candidate.search_document_hash
                ):
                    skipped += 1
                    continue
            try:
                catalog_embedding_service.backfill_product_embedding(product_id=product_id)
                processed += 1
            except GroceryCatalogEmbeddingError as exc:
                failed += 1
                print(f"FAILED {product_id}: {exc}")

        print(
            f"Grocery embedding backfill complete. processed={processed} skipped={skipped} failed={failed}"
        )
    finally:
        mongo_manager.close()


if __name__ == "__main__":
    main()
