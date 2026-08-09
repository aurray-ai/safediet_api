from __future__ import annotations

import json
import logging
from typing import Any

try:
    from langchain_core.messages import AIMessage, HumanMessage, SystemMessage, ToolMessage
    from langchain_core.tools import StructuredTool
    from langchain_openai import ChatOpenAI
except Exception:  # pragma: no cover - optional runtime dependency
    AIMessage = None
    HumanMessage = None
    SystemMessage = None
    ToolMessage = None
    StructuredTool = None
    ChatOpenAI = None

from app.agents.meal_conversation.tools import (
    AssessBudgetTool,
    AssessNutritionTool,
    CreateMealDraftTool,
    GetMealDetailTool,
    GetUserSavedMealPlansTool,
    LoadMemoryTool,
    MapGroceryProductsTool,
    SemanticSearchMealsTool,
    SelectExistingMealTool,
)
from app.models.user import User
from app.repositories.grocery_repository import GroceryRepository
from app.repositories.meal_conversation_repository import MealConversationRepository
from app.repositories.meal_repository import MealRepository
from app.repositories.saved_meal_plan_repository import SavedMealPlanRepository
from app.repositories.user_repository import UserRepository
from app.services.meal_search_embedding_service import MealSearchEmbeddingService
from app.services.meal_semantic_search_service import MealSemanticSearchService

logger = logging.getLogger(__name__)


class MealConversationRuntime:
    def __init__(
        self,
        *,
        user_repository: UserRepository,
        meal_repository: MealRepository,
        grocery_repository: GroceryRepository,
        meal_conversation_repository: MealConversationRepository,
        saved_meal_plan_repository: SavedMealPlanRepository,
        openai_api_key: str | None,
        model_name: str,
        timeout_seconds: float,
        embedding_model_name: str,
        embedding_timeout_seconds: float,
        semantic_candidate_pool_limit: int,
        semantic_embedding_batch_size: int,
    ) -> None:
        self._user_repository = user_repository
        self._meal_repository = meal_repository
        self._grocery_repository = grocery_repository
        self._meal_conversation_repository = meal_conversation_repository
        self._saved_meal_plan_repository = saved_meal_plan_repository
        self._openai_api_key = openai_api_key
        self._model_name = model_name
        self._timeout_seconds = timeout_seconds
        self._active_user_id: str | None = None

        self._meal_search_embedding_service = MealSearchEmbeddingService(
            api_key=openai_api_key,
            model_name=embedding_model_name,
            timeout_seconds=embedding_timeout_seconds,
        )
        self.semantic_search_meals = SemanticSearchMealsTool(
            MealSemanticSearchService(
                meal_repository,
                self._meal_search_embedding_service,
                candidate_pool_limit=semantic_candidate_pool_limit,
                embedding_batch_size=semantic_embedding_batch_size,
            )
        )
        self.get_meal_detail = GetMealDetailTool(meal_repository, grocery_repository)
        self.get_user_saved_meal_plans = GetUserSavedMealPlansTool(
            saved_meal_plan_repository,
            current_user_id_provider=lambda: self._active_user_id,
        )
        self.select_existing_meal = SelectExistingMealTool()
        self.create_meal_draft = CreateMealDraftTool(grocery_repository)
        self.map_grocery_products = MapGroceryProductsTool(grocery_repository)
        self.assess_nutrition = AssessNutritionTool(meal_repository)
        self.assess_budget = AssessBudgetTool(meal_repository)
        self.load_memory = LoadMemoryTool(meal_conversation_repository)
        self.tool_registry = {
            self.semantic_search_meals.name: self.semantic_search_meals,
            self.get_meal_detail.name: self.get_meal_detail,
            self.get_user_saved_meal_plans.name: self.get_user_saved_meal_plans,
            self.select_existing_meal.name: self.select_existing_meal,
            self.create_meal_draft.name: self.create_meal_draft,
            self.map_grocery_products.name: self.map_grocery_products,
            self.assess_nutrition.name: self.assess_nutrition,
            self.assess_budget.name: self.assess_budget,
            self.load_memory.name: self.load_memory,
        }

    def get_user(self, user_id: str) -> User | None:
        return self._user_repository.find_by_id(user_id)

    def set_active_user_id(self, user_id: str | None) -> None:
        self._active_user_id = str(user_id).strip() if user_id else None

    @property
    def model_name(self) -> str:
        return self._model_name

    def supports_llm(self) -> bool:
        return bool(
            self._openai_api_key
            and ChatOpenAI is not None
            and HumanMessage is not None
        )

    def build_model(self):
        if not self.supports_llm():
            return None

        return ChatOpenAI(
            model=self._model_name,
            api_key=self._openai_api_key,
            timeout=self._timeout_seconds,
            temperature=0,
        )

    def build_model_with_tools(
        self,
        *,
        constraint_state: dict[str, Any],
    ):
        model = self.build_model()
        if model is None or StructuredTool is None:
            return None
        tools = self._langchain_tools()
        return "", model.bind_tools(tools, parallel_tool_calls=False)

    def _langchain_tools(self) -> list[Any]:
        if StructuredTool is None:
            return []
        return [
            StructuredTool.from_function(
                name=self.semantic_search_meals.name,
                description=self.semantic_search_meals.description,
                func=self.semantic_search_meals.execute,
            ),
            StructuredTool.from_function(
                name=self.get_meal_detail.name,
                description=self.get_meal_detail.description,
                func=self.get_meal_detail.execute,
            ),
            StructuredTool.from_function(
                name=self.get_user_saved_meal_plans.name,
                description=self.get_user_saved_meal_plans.description,
                func=self.get_user_saved_meal_plans.execute,
            ),
            StructuredTool.from_function(
                name=self.select_existing_meal.name,
                description=self.select_existing_meal.description,
                func=self.select_existing_meal.execute,
            ),
            StructuredTool.from_function(
                name=self.create_meal_draft.name,
                description=self.create_meal_draft.description,
                func=self.create_meal_draft.execute,
            ),
            StructuredTool.from_function(
                name=self.map_grocery_products.name,
                description=self.map_grocery_products.description,
                func=self.map_grocery_products.execute,
            ),
            StructuredTool.from_function(
                name=self.assess_nutrition.name,
                description=self.assess_nutrition.description,
                func=self.assess_nutrition.execute,
            ),
            StructuredTool.from_function(
                name=self.assess_budget.name,
                description=self.assess_budget.description,
                func=self.assess_budget.execute,
            ),
            StructuredTool.from_function(
                name=self.load_memory.name,
                description=self.load_memory.description,
                func=self.load_memory.execute,
            ),
        ]

    def execute_tool(self, name: str, args: dict[str, Any]) -> dict[str, Any]:
        tool = self.tool_registry.get(name)
        if tool is None:
            return {"error": f"Unknown tool: {name}"}
        try:
            return tool.execute(**args)
        except Exception as exc:  # pragma: no cover - runtime fault protection
            logger.exception("Meal conversation tool '%s' failed.", name)
            return {"error": str(exc)}

    @staticmethod
    def to_tool_message_payload(result: dict[str, Any]) -> str:
        try:
            return json.dumps(result, default=str)
        except Exception:
            return str(result)
