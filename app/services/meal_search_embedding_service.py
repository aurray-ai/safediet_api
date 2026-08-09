from __future__ import annotations

from collections.abc import Sequence

try:
    from openai import OpenAI
except Exception:  # pragma: no cover - optional runtime dependency
    OpenAI = None


class MealSearchEmbeddingServiceError(Exception):
    pass


class MealSearchEmbeddingService:
    def __init__(
        self,
        *,
        api_key: str | None,
        model_name: str,
        timeout_seconds: float,
    ) -> None:
        self._api_key = api_key
        self._model_name = model_name
        self._timeout_seconds = timeout_seconds

    @property
    def model_name(self) -> str:
        return self._model_name

    def is_available(self) -> bool:
        return bool(self._api_key and OpenAI is not None)

    def embed_text(self, value: str) -> list[float]:
        vectors = self.embed_texts([value])
        if not vectors:
            raise MealSearchEmbeddingServiceError("Embedding service returned no vectors.")
        return vectors[0]

    def embed_texts(self, values: Sequence[str]) -> list[list[float]]:
        if not values:
            return []
        if not self.is_available():
            raise MealSearchEmbeddingServiceError(
                "Meal semantic search embeddings are not configured."
            )

        client = OpenAI(api_key=self._api_key, timeout=self._timeout_seconds)
        response = client.embeddings.create(
            model=self._model_name,
            input=[str(value) for value in values],
        )
        return [list(item.embedding) for item in response.data]
