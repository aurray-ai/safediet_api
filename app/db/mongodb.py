import logging
import time
from typing import Any

from pymongo import ASCENDING, DESCENDING, MongoClient
from pymongo.collection import Collection
from pymongo.database import Database
from pymongo.errors import OperationFailure, PyMongoError, ServerSelectionTimeoutError

from app.core.config import get_settings

logger = logging.getLogger(__name__)


class MongoDatabaseManager:
    def __init__(self) -> None:
        self._client: MongoClient[dict[str, Any]] | None = None
        self._database: Database[dict[str, Any]] | None = None

    def connect(self) -> None:
        if self._client is not None and self._database is not None:
            return

        settings = get_settings()
        last_error: Exception | None = None

        for attempt in range(1, settings.mongodb_connect_retries + 1):
            client = MongoClient(
                settings.mongodb_url,
                tz_aware=True,
                serverSelectionTimeoutMS=settings.mongodb_server_selection_timeout_ms,
                connectTimeoutMS=settings.mongodb_connect_timeout_ms,
                socketTimeoutMS=settings.mongodb_socket_timeout_ms,
            )
            try:
                client.admin.command("ping")
                self._client = client
                self._database = client[settings.mongodb_database]
                logger.info(
                    "Connected to MongoDB database '%s' on attempt %s/%s.",
                    settings.mongodb_database,
                    attempt,
                    settings.mongodb_connect_retries,
                )
                return
            except (ServerSelectionTimeoutError, PyMongoError) as exc:
                last_error = exc
                client.close()
                logger.warning(
                    "MongoDB connection attempt %s/%s failed: %s",
                    attempt,
                    settings.mongodb_connect_retries,
                    exc,
                )
                if attempt < settings.mongodb_connect_retries:
                    time.sleep(settings.mongodb_connect_retry_delay_seconds)

        raise RuntimeError(
            "Could not connect to MongoDB after "
            f"{settings.mongodb_connect_retries} attempts."
        ) from last_error

    def close(self) -> None:
        if self._client is None:
            return

        self._client.close()
        self._client = None
        self._database = None
        logger.info("Closed MongoDB connection.")

    def database(self) -> Database[dict[str, Any]]:
        if self._database is None:
            raise RuntimeError("MongoDB is not connected.")
        return self._database

    def users_collection(self) -> Collection[dict[str, Any]]:
        return self.database()["users"]

    def grocery_categories_collection(self) -> Collection[dict[str, Any]]:
        return self.database()["grocery_categories"]

    def grocery_products_collection(self) -> Collection[dict[str, Any]]:
        return self.database()["grocery_products"]

    def grocery_inventory_items_collection(self) -> Collection[dict[str, Any]]:
        return self.database()["grocery_inventory_items"]

    def grocery_inventory_adjustments_collection(self) -> Collection[dict[str, Any]]:
        return self.database()["grocery_inventory_adjustments"]

    def grocery_delivery_fee_rules_collection(self) -> Collection[dict[str, Any]]:
        return self.database()["grocery_delivery_fee_rules"]

    def grocery_carts_collection(self) -> Collection[dict[str, Any]]:
        return self.database()["grocery_carts"]

    def user_delivery_addresses_collection(self) -> Collection[dict[str, Any]]:
        return self.database()["user_delivery_addresses"]

    def grocery_checkout_quotes_collection(self) -> Collection[dict[str, Any]]:
        return self.database()["grocery_checkout_quotes"]

    def grocery_orders_collection(self) -> Collection[dict[str, Any]]:
        return self.database()["grocery_orders"]

    def grocery_payment_attempts_collection(self) -> Collection[dict[str, Any]]:
        return self.database()["grocery_payment_attempts"]

    def grocery_refunds_collection(self) -> Collection[dict[str, Any]]:
        return self.database()["grocery_refunds"]

    def push_devices_collection(self) -> Collection[dict[str, Any]]:
        return self.database()["push_devices"]

    def meal_categories_collection(self) -> Collection[dict[str, Any]]:
        return self.database()["meal_categories"]

    def meals_collection(self) -> Collection[dict[str, Any]]:
        return self.database()["meals"]

    def meal_favorites_collection(self) -> Collection[dict[str, Any]]:
        return self.database()["meal_favorites"]

    def meal_carts_collection(self) -> Collection[dict[str, Any]]:
        return self.database()["meal_carts"]

    def meal_orders_collection(self) -> Collection[dict[str, Any]]:
        return self.database()["meal_orders"]

    def measurement_units_collection(self) -> Collection[dict[str, Any]]:
        return self.database()["measurement_units"]

    def ingredient_conversion_profiles_collection(self) -> Collection[dict[str, Any]]:
        return self.database()["ingredient_conversion_profiles"]

    def meal_planning_conversations_collection(self) -> Collection[dict[str, Any]]:
        return self.database()["meal_planning_conversations"]

    def meal_planning_messages_collection(self) -> Collection[dict[str, Any]]:
        return self.database()["meal_planning_messages"]

    def saved_meal_plans_collection(self) -> Collection[dict[str, Any]]:
        return self.database()["saved_meal_plans"]

    def user_pantry_items_collection(self) -> Collection[dict[str, Any]]:
        return self.database()["user_pantry_items"]

    def user_kitchen_stock_lots_collection(self) -> Collection[dict[str, Any]]:
        return self.database()["user_kitchen_stock_lots"]

    def user_kitchen_movements_collection(self) -> Collection[dict[str, Any]]:
        return self.database()["user_kitchen_movements"]

    def meal_plan_inventory_allocations_collection(self) -> Collection[dict[str, Any]]:
        return self.database()["meal_plan_inventory_allocations"]

    def notifications_collection(self) -> Collection[dict[str, Any]]:
        return self.database()["notifications"]

    def password_reset_tokens_collection(self) -> Collection[dict[str, Any]]:
        return self.database()["password_reset_tokens"]

    def user_meal_usage_entries_collection(self) -> Collection[dict[str, Any]]:
        return self.database()["user_meal_usage_entries"]

    def meal_planner_monitoring_runs_collection(self) -> Collection[dict[str, Any]]:
        return self.database()["meal_planner_monitoring_runs"]

    def meal_planner_monitoring_events_collection(self) -> Collection[dict[str, Any]]:
        return self.database()["meal_planner_monitoring_events"]

    def promotion_campaigns_collection(self) -> Collection[dict[str, Any]]:
        return self.database()["promotion_campaigns"]

    def promotion_campaign_users_collection(self) -> Collection[dict[str, Any]]:
        return self.database()["promotion_campaign_users"]

    def promotion_context_snapshots_collection(self) -> Collection[dict[str, Any]]:
        return self.database()["promotion_context_snapshots"]

    def promotion_drafts_collection(self) -> Collection[dict[str, Any]]:
        return self.database()["promotion_drafts"]

    def promotion_deliveries_collection(self) -> Collection[dict[str, Any]]:
        return self.database()["promotion_deliveries"]

    def promotion_audit_logs_collection(self) -> Collection[dict[str, Any]]:
        return self.database()["promotion_audit_logs"]

    def category_discount_audit_logs_collection(self) -> Collection[dict[str, Any]]:
        return self.database()["category_discount_audit_logs"]

    def admin_customer_audit_logs_collection(self) -> Collection[dict[str, Any]]:
        return self.database()["admin_customer_audit_logs"]

    def subscription_accounts_collection(self) -> Collection[dict[str, Any]]:
        return self.database()["subscription_accounts"]

    def wallet_accounts_collection(self) -> Collection[dict[str, Any]]:
        return self.database()["wallet_accounts"]

    def wallet_ledger_entries_collection(self) -> Collection[dict[str, Any]]:
        return self.database()["wallet_ledger_entries"]

    def households_collection(self) -> Collection[dict[str, Any]]:
        return self.database()["households"]

    def household_members_collection(self) -> Collection[dict[str, Any]]:
        return self.database()["household_members"]

    def invitations_collection(self) -> Collection[dict[str, Any]]:
        return self.database()["invitations"]

    def surveys_collection(self) -> Collection[dict[str, Any]]:
        return self.database()["surveys"]

    def survey_responses_collection(self) -> Collection[dict[str, Any]]:
        return self.database()["survey_responses"]

    def household_budget_contributions_collection(self) -> Collection[dict[str, Any]]:
        return self.database()["household_budget_contributions"]

    def household_shared_expenses_collection(self) -> Collection[dict[str, Any]]:
        return self.database()["household_shared_expenses"]

    def household_expense_splits_collection(self) -> Collection[dict[str, Any]]:
        return self.database()["household_expense_splits"]

    def ensure_indexes(self) -> None:
        self.users_collection().create_index(
            [("email", ASCENDING)],
            name="uq_users_email",
            unique=True,
        )
        self.push_devices_collection().create_index(
            [("user_id", ASCENDING), ("platform", ASCENDING), ("device_token", ASCENDING)],
            name="uq_push_devices_user_platform_token",
            unique=True,
        )
        self.push_devices_collection().create_index(
            [("user_id", ASCENDING), ("is_active", ASCENDING), ("updated_at", DESCENDING)],
            name="ix_push_devices_user_active_updated",
        )
        self.push_devices_collection().create_index(
            [("locations", ASCENDING)],
            name="ix_push_devices_locations",
        )
        self.push_devices_collection().create_index(
            [("delivery_types", ASCENDING)],
            name="ix_push_devices_delivery_types",
        )
        self.grocery_categories_collection().create_index(
            [("slug", ASCENDING)],
            name="uq_grocery_categories_slug",
            unique=True,
        )
        self.grocery_categories_collection().create_index(
            [("sort_order", ASCENDING)],
            name="ix_grocery_categories_sort_order",
        )
        self.grocery_products_collection().create_index(
            [("category_id", ASCENDING)],
            name="ix_grocery_products_category_id",
        )
        self.grocery_products_collection().create_index(
            [("sort_order", ASCENDING), ("is_active", ASCENDING)],
            name="ix_grocery_products_sort_active",
        )
        self.grocery_products_collection().create_index(
            [("product", ASCENDING)],
            name="ix_grocery_products_product",
        )
        self.grocery_products_collection().create_index(
            [("culture_tags", ASCENDING)],
            name="ix_grocery_products_culture_tags",
        )
        self.grocery_products_collection().create_index(
            [("is_active", ASCENDING)],
            name="ix_grocery_products_is_active",
        )
        self.grocery_products_collection().create_index(
            [("product", "text"), ("product_tags", "text")],
            name="ix_grocery_products_text",
        )
        self.measurement_units_collection().create_index(
            [("code", ASCENDING)],
            name="uq_measurement_units_code",
            unique=True,
        )
        self.measurement_units_collection().create_index(
            [("sort_order", ASCENDING), ("is_active", ASCENDING)],
            name="ix_measurement_units_sort_active",
        )
        self.ingredient_conversion_profiles_collection().create_index(
            [("unit_code", ASCENDING), ("ingredient_name", ASCENDING)],
            name="ix_conversion_profiles_unit_ingredient",
        )
        self.ingredient_conversion_profiles_collection().create_index(
            [("is_active", ASCENDING), ("name", ASCENDING)],
            name="ix_conversion_profiles_active_name",
        )
        self.grocery_inventory_items_collection().create_index(
            [("store_id", ASCENDING), ("product_id", ASCENDING)],
            name="uq_grocery_inventory_store_product",
            unique=True,
        )
        self.grocery_inventory_items_collection().create_index(
            [("sku", ASCENDING)],
            name="uq_grocery_inventory_sku",
            unique=True,
        )
        self.grocery_inventory_items_collection().create_index(
            [("is_active", ASCENDING), ("available_quantity", ASCENDING)],
            name="ix_grocery_inventory_active_available",
        )
        self.grocery_inventory_adjustments_collection().create_index(
            [("inventory_item_id", ASCENDING), ("created_at", DESCENDING)],
            name="ix_grocery_inventory_adjustments_inventory_created",
        )
        self.grocery_inventory_adjustments_collection().create_index(
            [("reference_type", ASCENDING), ("reference_id", ASCENDING)],
            name="ix_grocery_inventory_adjustments_reference",
        )
        self.grocery_delivery_fee_rules_collection().create_index(
            [("store_id", ASCENDING), ("currency", ASCENDING), ("min_weight_grams", ASCENDING)],
            name="ix_grocery_delivery_fee_rules_store_currency_weight",
        )
        self.grocery_carts_collection().create_index(
            [("user_id", ASCENDING), ("status", ASCENDING)],
            name="uq_grocery_carts_user_status",
            unique=True,
            partialFilterExpression={"status": "active"},
        )
        self.grocery_carts_collection().create_index(
            [("expires_at", ASCENDING)],
            name="ix_grocery_carts_expires_at",
        )
        self.user_delivery_addresses_collection().create_index(
            [("user_id", ASCENDING), ("is_default", ASCENDING)],
            name="ix_user_delivery_addresses_user_default",
        )
        self.user_delivery_addresses_collection().create_index(
            [("user_id", ASCENDING), ("updated_at", DESCENDING)],
            name="ix_user_delivery_addresses_user_updated",
        )
        self.grocery_checkout_quotes_collection().create_index(
            [("user_id", ASCENDING), ("created_at", DESCENDING)],
            name="ix_grocery_checkout_quotes_user_created",
        )
        self.grocery_checkout_quotes_collection().create_index(
            [("expires_at", ASCENDING)],
            name="ix_grocery_checkout_quotes_expires_at",
            expireAfterSeconds=0,
        )
        self.grocery_orders_collection().create_index(
            [("order_number", ASCENDING)],
            name="uq_grocery_orders_order_number",
            unique=True,
        )
        self.grocery_orders_collection().create_index(
            [("user_id", ASCENDING), ("created_at", DESCENDING)],
            name="ix_grocery_orders_user_created",
        )
        self.grocery_orders_collection().create_index(
            [("status", ASCENDING), ("updated_at", DESCENDING)],
            name="ix_grocery_orders_status_updated",
        )
        self.grocery_payment_attempts_collection().create_index(
            [("idempotency_key", ASCENDING)],
            name="uq_grocery_payment_attempts_idempotency_key",
            unique=True,
        )
        self._ensure_grocery_payment_attempt_provider_intent_index()
        self.grocery_payment_attempts_collection().create_index(
            [("order_id", ASCENDING)],
            name="ix_grocery_payment_attempts_order_id",
        )
        self.grocery_refunds_collection().create_index(
            [("idempotency_key", ASCENDING)],
            name="uq_grocery_refunds_idempotency_key",
            unique=True,
        )
        self.grocery_refunds_collection().create_index(
            [("order_id", ASCENDING), ("created_at", DESCENDING)],
            name="ix_grocery_refunds_order_created",
        )
        self.meal_categories_collection().create_index(
            [("slug", ASCENDING)],
            name="uq_meal_categories_slug",
            unique=True,
        )
        self.meal_categories_collection().create_index(
            [("sort_order", ASCENDING)],
            name="ix_meal_categories_sort_order",
        )
        self.meals_collection().create_index(
            [("meal_type", ASCENDING)],
            name="ix_meals_meal_type",
        )
        self.meals_collection().create_index(
            [("meal_types", ASCENDING)],
            name="ix_meals_meal_types",
        )
        self.meals_collection().create_index(
            [("category_ids", ASCENDING)],
            name="ix_meals_category_ids",
        )
        self.meals_collection().create_index(
            [("culture_tags", ASCENDING)],
            name="ix_meals_culture_tags",
        )
        self.meals_collection().create_index(
            [("is_active", ASCENDING)],
            name="ix_meals_is_active",
        )
        self.meals_collection().create_index(
            [("name", "text"), ("description", "text")],
            name="ix_meals_text",
        )
        self.meal_favorites_collection().create_index(
            [("user_id", ASCENDING), ("meal_id", ASCENDING)],
            name="uq_meal_favorites_user_meal",
            unique=True,
        )
        self.meal_carts_collection().create_index(
            [("user_id", ASCENDING), ("status", ASCENDING)],
            name="uq_meal_carts_user_status",
            unique=True,
            partialFilterExpression={"status": "active"},
        )
        self.meal_carts_collection().create_index(
            [("expires_at", ASCENDING)],
            name="ix_meal_carts_expires_at",
        )
        self.meal_orders_collection().create_index(
            [("order_number", ASCENDING)],
            name="uq_meal_orders_order_number",
            unique=True,
        )
        self.meal_orders_collection().create_index(
            [("user_id", ASCENDING), ("created_at", DESCENDING)],
            name="ix_meal_orders_user_created",
        )
        self.meal_orders_collection().create_index(
            [("status", ASCENDING), ("updated_at", DESCENDING)],
            name="ix_meal_orders_status_updated",
        )
        self.meal_planning_conversations_collection().create_index(
            [("user_id", ASCENDING), ("updated_at", DESCENDING)],
            name="ix_meal_planning_conversations_user_updated",
        )
        self.meal_planning_conversations_collection().create_index(
            [("agent_type", ASCENDING), ("status", ASCENDING)],
            name="ix_meal_planning_conversations_agent_status",
        )
        self.meal_planning_conversations_collection().create_index(
            [("user_id", ASCENDING), ("user_goal", ASCENDING), ("updated_at", DESCENDING)],
            name="ix_meal_planning_conversations_user_goal_updated",
        )
        self.meal_planning_conversations_collection().create_index(
            [
                ("user_id", ASCENDING),
                ("status", ASCENDING),
                ("user_goal", ASCENDING),
                ("current_summary.meal_type", ASCENDING),
                ("updated_at", DESCENDING),
            ],
            name="ix_meal_planning_conversations_user_status_goal_meal_type",
        )
        self.meal_planning_messages_collection().create_index(
            [("conversation_id", ASCENDING), ("created_at", ASCENDING)],
            name="ix_meal_planning_messages_conversation_created",
        )
        self.meal_planning_messages_collection().create_index(
            [("conversation_id", ASCENDING), ("created_at", DESCENDING), ("_id", DESCENDING)],
            name="ix_meal_planning_messages_conversation_created_desc",
        )
        self.saved_meal_plans_collection().create_index(
            [("user_id", ASCENDING), ("source_snapshot_id", ASCENDING)],
            name="uq_saved_meal_plans_user_snapshot",
            unique=True,
        )
        self.saved_meal_plans_collection().create_index(
            [("user_id", ASCENDING), ("updated_at", DESCENDING)],
            name="ix_saved_meal_plans_user_updated",
        )
        self.saved_meal_plans_collection().create_index(
            [("user_id", ASCENDING), ("effective_date", ASCENDING), ("view_mode", ASCENDING), ("updated_at", DESCENDING)],
            name="ix_saved_meal_plans_user_effective_date_view_mode_updated",
        )
        self.saved_meal_plans_collection().create_index(
            [("user_id", ASCENDING), ("week_start", ASCENDING), ("view_mode", ASCENDING), ("updated_at", DESCENDING)],
            name="ix_saved_meal_plans_user_week_start_view_mode_updated",
        )
        self.saved_meal_plans_collection().create_index(
            [("view_mode", ASCENDING), ("updated_at", DESCENDING)],
            name="ix_saved_meal_plans_view_mode_updated",
        )
        self.user_pantry_items_collection().create_index(
            [("user_id", ASCENDING), ("product_id", ASCENDING)],
            name="uq_user_pantry_items_user_product",
            unique=True,
        )
        self.user_pantry_items_collection().create_index(
            [("user_id", ASCENDING), ("updated_at", DESCENDING)],
            name="ix_user_pantry_items_user_updated",
        )
        self.user_kitchen_stock_lots_collection().create_index(
            [("user_id", ASCENDING), ("product_id", ASCENDING), ("source_type", ASCENDING)],
            name="ix_user_kitchen_stock_user_product_source",
        )
        self.user_kitchen_stock_lots_collection().create_index(
            [("user_id", ASCENDING), ("source_type", ASCENDING), ("source_id", ASCENDING)],
            name="uq_user_kitchen_stock_user_source",
            unique=True,
            partialFilterExpression={"source_id": {"$type": "string"}},
        )
        self.user_kitchen_stock_lots_collection().create_index(
            [("user_id", ASCENDING), ("updated_at", DESCENDING)],
            name="ix_user_kitchen_stock_user_updated",
        )
        self.user_kitchen_movements_collection().create_index(
            [("user_id", ASCENDING), ("created_at", DESCENDING)],
            name="ix_user_kitchen_movements_user_created",
        )
        self.user_kitchen_movements_collection().create_index(
            [("user_id", ASCENDING), ("product_id", ASCENDING), ("created_at", DESCENDING)],
            name="ix_user_kitchen_movements_user_product_created",
        )
        self.meal_plan_inventory_allocations_collection().create_index(
            [("user_id", ASCENDING), ("saved_plan_id", ASCENDING), ("status", ASCENDING)],
            name="ix_meal_plan_allocations_user_plan_status",
        )
        self.meal_plan_inventory_allocations_collection().create_index(
            [("user_id", ASCENDING), ("effective_date", ASCENDING), ("slot", ASCENDING)],
            name="ix_meal_plan_allocations_user_date_slot",
        )
        self.notifications_collection().create_index(
            [("recipient_user_ids", ASCENDING), ("created_at", DESCENDING)],
            name="ix_notifications_recipient_created",
        )
        self.notifications_collection().create_index(
            [("idempotency_key", ASCENDING)],
            name="uq_notifications_idempotency_key",
            unique=True,
            sparse=True,
        )
        self.notifications_collection().create_index(
            [("read_by_user_ids", ASCENDING)],
            name="ix_notifications_read_by_user_ids",
        )
        self.password_reset_tokens_collection().create_index(
            [("token_hash", ASCENDING)],
            name="uq_password_reset_tokens_hash",
            unique=True,
        )
        self.password_reset_tokens_collection().create_index(
            [("user_id", ASCENDING), ("created_at", DESCENDING)],
            name="ix_password_reset_tokens_user_created",
        )
        self.password_reset_tokens_collection().create_index(
            [("expires_at", ASCENDING)],
            name="ix_password_reset_tokens_expires_at",
        )
        self.user_meal_usage_entries_collection().create_index(
            [("user_id", ASCENDING), ("effective_date", ASCENDING), ("meal_slot", ASCENDING)],
            name="uq_user_meal_usage_entries_user_date_slot",
            unique=True,
        )
        self.user_meal_usage_entries_collection().create_index(
            [("user_id", ASCENDING), ("week_start", ASCENDING)],
            name="ix_user_meal_usage_entries_user_week_start",
        )
        self.user_meal_usage_entries_collection().create_index(
            [("user_id", ASCENDING), ("updated_at", DESCENDING)],
            name="ix_user_meal_usage_entries_user_updated",
        )
        self.meal_planner_monitoring_runs_collection().create_index(
            [("user_id", ASCENDING), ("created_at", DESCENDING)],
            name="ix_meal_planner_monitoring_runs_user_created",
        )
        self.meal_planner_monitoring_runs_collection().create_index(
            [("trace_id", ASCENDING), ("created_at", DESCENDING)],
            name="ix_meal_planner_monitoring_runs_trace_created",
        )
        self.meal_planner_monitoring_runs_collection().create_index(
            [("status", ASCENDING), ("updated_at", DESCENDING)],
            name="ix_meal_planner_monitoring_runs_status_updated",
        )
        self.meal_planner_monitoring_events_collection().create_index(
            [("run_id", ASCENDING), ("created_at", ASCENDING)],
            name="ix_meal_planner_monitoring_events_run_created",
        )
        self.meal_planner_monitoring_events_collection().create_index(
            [("trace_id", ASCENDING), ("created_at", ASCENDING)],
            name="ix_meal_planner_monitoring_events_trace_created",
        )
        self.meal_planner_monitoring_events_collection().create_index(
            [("user_id", ASCENDING), ("created_at", DESCENDING)],
            name="ix_meal_planner_monitoring_events_user_created",
        )
        self.meal_planner_monitoring_events_collection().create_index(
            [("step_id", ASCENDING), ("created_at", ASCENDING)],
            name="ix_meal_planner_monitoring_events_step_created",
        )
        self.promotion_campaigns_collection().create_index(
            [("created_by_admin_id", ASCENDING), ("created_at", DESCENDING)],
            name="ix_promotion_campaigns_admin_created",
        )
        self.promotion_campaigns_collection().create_index(
            [("status", ASCENDING), ("updated_at", DESCENDING)],
            name="ix_promotion_campaigns_status_updated",
        )
        self.promotion_campaign_users_collection().create_index(
            [("campaign_id", ASCENDING), ("user_id", ASCENDING)],
            name="uq_promotion_campaign_users_campaign_user",
            unique=True,
        )
        self.promotion_context_snapshots_collection().create_index(
            [("campaign_id", ASCENDING), ("user_id", ASCENDING), ("created_at", DESCENDING)],
            name="ix_promotion_context_snapshots_campaign_user_created",
        )
        self.promotion_drafts_collection().create_index(
            [("campaign_id", ASCENDING), ("user_id", ASCENDING), ("generation_version", DESCENDING)],
            name="uq_promotion_drafts_campaign_user_generation",
            unique=True,
        )
        self.promotion_drafts_collection().create_index(
            [("campaign_id", ASCENDING), ("status", ASCENDING), ("updated_at", DESCENDING)],
            name="ix_promotion_drafts_campaign_status_updated",
        )
        self.promotion_deliveries_collection().create_index(
            [("campaign_id", ASCENDING), ("created_at", DESCENDING)],
            name="ix_promotion_deliveries_campaign_created",
        )
        self.promotion_deliveries_collection().create_index(
            [("delivery_status", ASCENDING), ("sent_at", DESCENDING)],
            name="ix_promotion_deliveries_status_sent",
        )
        self.promotion_audit_logs_collection().create_index(
            [("campaign_id", ASCENDING), ("created_at", DESCENDING)],
            name="ix_promotion_audit_logs_campaign_created",
        )
        self.category_discount_audit_logs_collection().create_index(
            [("category_id", ASCENDING), ("created_at", DESCENDING)],
            name="ix_category_discount_audit_logs_category_created",
        )
        self.admin_customer_audit_logs_collection().create_index(
            [("user_id", ASCENDING), ("created_at", DESCENDING)],
            name="ix_admin_customer_audit_logs_user_created",
        )
        self.subscription_accounts_collection().create_index(
            [("user_id", ASCENDING)],
            name="uq_subscription_accounts_user_id",
            unique=True,
        )
        self.subscription_accounts_collection().create_index(
            [("status", ASCENDING), ("updated_at", DESCENDING)],
            name="ix_subscription_accounts_status_updated",
        )
        self.wallet_accounts_collection().create_index(
            [("user_id", ASCENDING)],
            name="uq_wallet_accounts_user_id",
            unique=True,
        )
        self.wallet_accounts_collection().create_index(
            [("status", ASCENDING), ("updated_at", DESCENDING)],
            name="ix_wallet_accounts_status_updated",
        )
        self.wallet_ledger_entries_collection().create_index(
            [("user_id", ASCENDING), ("created_at", DESCENDING)],
            name="ix_wallet_ledger_entries_user_created",
        )
        self.wallet_ledger_entries_collection().create_index(
            [("wallet_account_id", ASCENDING), ("created_at", DESCENDING)],
            name="ix_wallet_ledger_entries_wallet_created",
        )
        self._ensure_wallet_ledger_idempotency_index()
        try:
            self.households_collection().drop_index("uq_households_owner_active")
        except OperationFailure:
            pass
        self.households_collection().create_index(
            [("owner_user_id", ASCENDING), ("status", ASCENDING)],
            name="ix_households_owner_status",
        )
        self.households_collection().create_index(
            [("status", ASCENDING), ("updated_at", DESCENDING)],
            name="ix_households_status_updated",
        )
        self.household_members_collection().create_index(
            [("household_id", ASCENDING), ("user_id", ASCENDING)],
            name="uq_household_members_household_user",
            unique=True,
        )
        try:
            self.household_members_collection().drop_index("uq_household_members_user_active")
        except OperationFailure:
            pass
        self.household_members_collection().create_index(
            [("user_id", ASCENDING), ("status", ASCENDING)],
            name="ix_household_members_user_status",
        )
        self.household_members_collection().create_index(
            [("household_id", ASCENDING), ("status", ASCENDING), ("updated_at", DESCENDING)],
            name="ix_household_members_household_status_updated",
        )
        self.invitations_collection().create_index(
            [("token_hash", ASCENDING)],
            name="uq_invitations_token_hash",
            unique=True,
        )
        self.invitations_collection().create_index(
            [("invitation_type", ASCENDING), ("context.household_id", ASCENDING), ("invitee_email", ASCENDING)],
            name="uq_invitations_household_email_pending",
            unique=True,
            partialFilterExpression={"status": "pending", "invitation_type": "household"},
        )
        self.invitations_collection().create_index(
            [("invitation_type", ASCENDING), ("invitee_email", ASCENDING)],
            name="uq_invitations_staff_email_pending",
            unique=True,
            partialFilterExpression={"status": "pending", "invitation_type": "staff"},
        )
        self.invitations_collection().create_index(
            [("invitation_type", ASCENDING), ("status", ASCENDING), ("created_at", DESCENDING)],
            name="ix_invitations_type_status_created",
        )
        self.invitations_collection().create_index(
            [("invitee_email", ASCENDING), ("status", ASCENDING), ("updated_at", DESCENDING)],
            name="ix_invitations_email_status_updated",
        )
        self.household_budget_contributions_collection().create_index(
            [("household_id", ASCENDING), ("period_start", DESCENDING), ("period_end", DESCENDING)],
            name="ix_household_budget_contributions_household_period",
        )
        self.household_budget_contributions_collection().create_index(
            [("member_id", ASCENDING), ("period_start", DESCENDING)],
            name="ix_household_budget_contributions_member_period",
        )
        self.household_shared_expenses_collection().create_index(
            [("household_id", ASCENDING), ("effective_date", DESCENDING)],
            name="ix_household_shared_expenses_household_effective_date",
        )
        self.household_shared_expenses_collection().create_index(
            [("linked_order_id", ASCENDING)],
            name="ix_household_shared_expenses_linked_order",
            sparse=True,
        )
        self.household_expense_splits_collection().create_index(
            [("expense_id", ASCENDING), ("member_id", ASCENDING)],
            name="uq_household_expense_splits_expense_member",
            unique=True,
        )
        self.household_expense_splits_collection().create_index(
            [("household_id", ASCENDING), ("member_id", ASCENDING), ("created_at", DESCENDING)],
            name="ix_household_expense_splits_household_member_created",
        )
        self.surveys_collection().create_index(
            [("slug", ASCENDING)],
            name="uq_surveys_slug",
            unique=True,
        )
        self.surveys_collection().create_index(
            [("status", ASCENDING), ("updated_at", DESCENDING)],
            name="ix_surveys_status_updated",
        )
        self.survey_responses_collection().create_index(
            [("survey_id", ASCENDING), ("submitted_at", DESCENDING)],
            name="ix_survey_responses_survey_submitted",
        )
        self.survey_responses_collection().create_index(
            [("survey_id", ASCENDING), ("respondent.user_id", ASCENDING)],
            name="ix_survey_responses_survey_user",
        )
        self.survey_responses_collection().create_index(
            [("survey_id", ASCENDING), ("respondent.email", ASCENDING)],
            name="ix_survey_responses_survey_email",
        )
        logger.info("MongoDB indexes ensured.")

    def _ensure_wallet_ledger_idempotency_index(self) -> None:
        collection = self.wallet_ledger_entries_collection()
        try:
            collection.update_many(
                {"idempotency_key": None},
                {"$unset": {"idempotency_key": ""}},
            )
            try:
                collection.drop_index("uq_wallet_ledger_entries_idempotency_key")
            except OperationFailure:
                pass
            collection.create_index(
                [("idempotency_key", ASCENDING)],
                name="uq_wallet_ledger_entries_idempotency_key",
                unique=True,
                partialFilterExpression={"idempotency_key": {"$type": "string"}},
            )
        except PyMongoError as exc:
            logger.warning(
                "Skipped wallet ledger idempotency index maintenance due to database error: %s",
                exc,
            )

    def _ensure_grocery_payment_attempt_provider_intent_index(self) -> None:
        collection = self.grocery_payment_attempts_collection()
        try:
            collection.update_many(
                {"provider_payment_intent_id": None},
                {"$unset": {"provider_payment_intent_id": ""}},
            )
            try:
                collection.drop_index("uq_grocery_payment_attempts_provider_intent")
            except OperationFailure:
                pass
            collection.create_index(
                [("provider", ASCENDING), ("provider_payment_intent_id", ASCENDING)],
                name="uq_grocery_payment_attempts_provider_intent",
                unique=True,
                partialFilterExpression={"provider_payment_intent_id": {"$type": "string"}},
            )
        except PyMongoError as exc:
            logger.warning(
                "Skipped grocery payment attempt provider intent index maintenance due to database error: %s",
                exc,
            )


mongo_manager = MongoDatabaseManager()
