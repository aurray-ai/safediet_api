from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from jose import JWTError

from app.cache.redis_cache import RedisCache
from app.core.security import decode_access_token
from app.db.mongodb import mongo_manager
from app.db.redis import redis_manager
from app.models.user import User, UserType
from app.repositories.push_device_repository import PushDeviceRepository
from app.repositories.address_repository import AddressRepository
from app.repositories.admin_customer_audit_repository import AdminCustomerAuditRepository
from app.repositories.cart_repository import CartRepository
from app.repositories.checkout_quote_repository import CheckoutQuoteRepository
from app.repositories.inventory_repository import InventoryRepository
from app.repositories.order_repository import OrderRepository
from app.repositories.payment_attempt_repository import PaymentAttemptRepository
from app.repositories.promotion_campaign_repository import PromotionCampaignRepository
from app.repositories.promotion_delivery_repository import PromotionDeliveryRepository
from app.repositories.promotion_draft_repository import PromotionDraftRepository
from app.repositories.refund_repository import RefundRepository
from app.repositories.subscription_account_repository import SubscriptionAccountRepository
from app.repositories.cached_meal_conversation_repository import CachedMealConversationRepository
from app.repositories.cached_discount_repository import CachedDiscountRepository
from app.repositories.cached_grocery_repository import CachedGroceryRepository
from app.repositories.cached_meal_repository import CachedMealRepository
from app.repositories.discount_audit_repository import DiscountAuditRepository
from app.repositories.discount_repository import DiscountRepository
from app.repositories.grocery_repository import GroceryRepository
from app.repositories.kitchen_repository import KitchenRepository
from app.repositories.meal_cart_repository import MealCartRepository
from app.repositories.meal_conversation_repository import MealConversationRepository
from app.repositories.meal_favorite_repository import MealFavoriteRepository
from app.repositories.meal_order_repository import MealOrderRepository
from app.repositories.meal_repository import MealRepository
from app.repositories.measurement_repository import MeasurementRepository
from app.repositories.notification_repository import NotificationRepository
from app.repositories.password_reset_token_repository import PasswordResetTokenRepository
from app.repositories.household_budget_contribution_repository import HouseholdBudgetContributionRepository
from app.repositories.household_expense_split_repository import HouseholdExpenseSplitRepository
from app.repositories.invitation_repository import InvitationRepository
from app.repositories.household_member_repository import HouseholdMemberRepository
from app.repositories.household_repository import HouseholdRepository
from app.repositories.household_shared_expense_repository import HouseholdSharedExpenseRepository
from app.repositories.saved_meal_plan_repository import SavedMealPlanRepository
from app.repositories.survey_repository import SurveyRepository
from app.repositories.survey_response_repository import SurveyResponseRepository
from app.repositories.user_pantry_repository import UserPantryRepository
from app.repositories.user_meal_usage_repository import UserMealUsageRepository
from app.repositories.user_repository import UserRepository
from app.repositories.wallet_account_repository import WalletAccountRepository
from app.repositories.wallet_ledger_repository import WalletLedgerRepository
from app.services.admin_meal_service import AdminMealService
from app.services.admin_promotion_service import AdminPromotionService
from app.services.auth_service import AuthService
from app.services.admin_grocery_service import AdminGroceryService
from app.services.address_service import AddressService
from app.services.admin_customer_service import AdminCustomerService
from app.services.billing_service import BillingService
from app.services.cart_service import CartService
from app.services.checkout_service import CheckoutService
from app.services.delivery_window_service import DeliveryWindowService
from app.services.meal_cart_service import MealCartService
from app.services.meal_checkout_service import MealCheckoutService
from app.services.meal_plan_checkout_service import MealPlanCheckoutService
from app.services.chef_fulfillment_service import ChefFulfillmentService
from app.services.meal_order_service import MealOrderService
from app.services.email_service import EmailService, build_email_sender
from app.services.notification_copy_service import NotificationCopyService
from app.services.order_fulfillment_communication_service import OrderFulfillmentCommunicationService
from app.services.subscription_communication_service import SubscriptionCommunicationService
from app.services.discount_service import DiscountService
from app.services.grocery_catalog_embedding_service import GroceryCatalogEmbeddingService
from app.services.grocery_service import GroceryService
from app.services.grocery_similar_products_service import GrocerySimilarProductsService
from app.services.household_budgeting_service import HouseholdBudgetingService
from app.services.household_communication_service import HouseholdCommunicationService
from app.services.household_service import HouseholdService
from app.services.inventory_service import InventoryService
from app.services.kitchen_service import KitchenService
from app.services.meal_conversation_service import MealConversationService
from app.services.meal_service import MealService
from app.services.media_storage_service import MediaStorageService
from app.services.meal_catalog_embedding_service import MealCatalogEmbeddingService
from app.services.measurement_service import MeasurementService
from app.services.meal_search_embedding_service import MealSearchEmbeddingService
from app.services.notification_service import NotificationService
from app.services.promotion_context_service import PromotionContextService
from app.services.promotion_delivery_service import PromotionDeliveryService
from app.services.promotion_generation_service import PromotionGenerationService
from app.services.promotion_review_service import PromotionReviewService
from app.services.push_device_service import PushDeviceService
from app.services.push_notification_service import PushNotificationService, build_push_notification_sender
from app.services.order_service import OrderService
from app.services.shopper_fulfillment_service import ShopperFulfillmentService
from app.services.staff_service import StaffService
from app.services.refund_service import RefundService
from app.services.saved_meal_plan_service import SavedMealPlanService
from app.services.goal_target_service import GoalTargetService
from app.services.stripe_billing_gateway import StripeBillingGateway
from app.services.survey_service import SurveyService
from app.services.user_meal_usage_service import UserMealUsageService
from app.services.user_pantry_service import UserPantryService
from app.core.config import Settings, get_settings

bearer_scheme = HTTPBearer(auto_error=False)


def get_user_repository() -> UserRepository:
    return UserRepository(mongo_manager.users_collection())


def get_push_device_repository() -> PushDeviceRepository:
    return PushDeviceRepository(mongo_manager.push_devices_collection())


def get_address_repository() -> AddressRepository:
    return AddressRepository(mongo_manager.user_delivery_addresses_collection())


def get_cart_repository() -> CartRepository:
    return CartRepository(mongo_manager.grocery_carts_collection())


def get_checkout_quote_repository() -> CheckoutQuoteRepository:
    return CheckoutQuoteRepository(mongo_manager.grocery_checkout_quotes_collection())


def get_inventory_repository() -> InventoryRepository:
    return InventoryRepository(
        mongo_manager.grocery_inventory_items_collection(),
        mongo_manager.grocery_inventory_adjustments_collection(),
        mongo_manager.grocery_delivery_fee_rules_collection(),
    )


def get_order_repository() -> OrderRepository:
    return OrderRepository(mongo_manager.grocery_orders_collection())


def get_meal_order_repository() -> MealOrderRepository:
    return MealOrderRepository(mongo_manager.meal_orders_collection())


def get_payment_attempt_repository() -> PaymentAttemptRepository:
    return PaymentAttemptRepository(mongo_manager.grocery_payment_attempts_collection())


def get_refund_repository() -> RefundRepository:
    return RefundRepository(mongo_manager.grocery_refunds_collection())


def get_promotion_campaign_repository() -> PromotionCampaignRepository:
    return PromotionCampaignRepository(
        mongo_manager.promotion_campaigns_collection(),
        mongo_manager.promotion_campaign_users_collection(),
        mongo_manager.promotion_context_snapshots_collection(),
        mongo_manager.promotion_audit_logs_collection(),
    )


def get_promotion_draft_repository() -> PromotionDraftRepository:
    return PromotionDraftRepository(mongo_manager.promotion_drafts_collection())


def get_promotion_delivery_repository() -> PromotionDeliveryRepository:
    return PromotionDeliveryRepository(mongo_manager.promotion_deliveries_collection())


def get_redis_cache() -> RedisCache:
    settings = get_settings()
    return RedisCache(redis_manager.client(), log_hits=settings.cache_log_hits)


def get_grocery_repository() -> GroceryRepository:
    base_repository = GroceryRepository(
        mongo_manager.grocery_categories_collection(),
        mongo_manager.grocery_products_collection(),
    )
    settings = get_settings()
    return CachedGroceryRepository(
        base_repository=base_repository,
        cache=get_redis_cache(),
        entity_ttl_seconds=settings.cache_entity_ttl_seconds,
        query_ttl_seconds=settings.cache_query_ttl_seconds,
    )


def get_discount_repository() -> DiscountRepository:
    base_repository = DiscountRepository(mongo_manager.grocery_discounts_collection())
    settings = get_settings()
    return CachedDiscountRepository(
        base_repository=base_repository,
        cache=get_redis_cache(),
        entity_ttl_seconds=settings.cache_entity_ttl_seconds,
        query_ttl_seconds=settings.cache_query_ttl_seconds,
    )


def get_meal_repository() -> MealRepository:
    base_repository = MealRepository(
        mongo_manager.meal_categories_collection(),
        mongo_manager.meals_collection(),
    )
    settings = get_settings()
    return CachedMealRepository(
        base_repository=base_repository,
        cache=get_redis_cache(),
        entity_ttl_seconds=settings.cache_entity_ttl_seconds,
        query_ttl_seconds=settings.cache_query_ttl_seconds,
    )


def get_measurement_repository() -> MeasurementRepository:
    return MeasurementRepository(
        mongo_manager.measurement_units_collection(),
        mongo_manager.ingredient_conversion_profiles_collection(),
    )


def get_measurement_service(
    measurement_repository: MeasurementRepository = Depends(get_measurement_repository),
) -> MeasurementService:
    return MeasurementService(measurement_repository=measurement_repository)


def get_meal_conversation_repository() -> MealConversationRepository:
    base_repository = MealConversationRepository(
        mongo_manager.meal_planning_conversations_collection(),
        mongo_manager.meal_planning_messages_collection(),
    )
    settings = get_settings()
    return CachedMealConversationRepository(
        base_repository=base_repository,
        cache=get_redis_cache(),
        conversation_ttl_seconds=settings.planner_cache_conversation_ttl_seconds,
        recent_messages_ttl_seconds=settings.planner_cache_recent_messages_ttl_seconds,
        recent_messages_limit=settings.planner_cache_recent_messages_limit,
    )


def get_saved_meal_plan_repository() -> SavedMealPlanRepository:
    return SavedMealPlanRepository(mongo_manager.saved_meal_plans_collection())


def get_survey_repository() -> SurveyRepository:
    return SurveyRepository(mongo_manager.surveys_collection())


def get_survey_response_repository() -> SurveyResponseRepository:
    return SurveyResponseRepository(mongo_manager.survey_responses_collection())


def get_user_pantry_repository() -> UserPantryRepository:
    return UserPantryRepository(mongo_manager.user_pantry_items_collection())


def get_kitchen_repository() -> KitchenRepository:
    return KitchenRepository(
        mongo_manager.user_kitchen_stock_lots_collection(),
        mongo_manager.user_kitchen_movements_collection(),
        mongo_manager.meal_plan_inventory_allocations_collection(),
    )


def get_notification_repository() -> NotificationRepository:
    return NotificationRepository(mongo_manager.notifications_collection())


def get_password_reset_token_repository() -> PasswordResetTokenRepository:
    return PasswordResetTokenRepository(mongo_manager.password_reset_tokens_collection())


def get_household_repository() -> HouseholdRepository:
    return HouseholdRepository(mongo_manager.households_collection())


def get_household_member_repository() -> HouseholdMemberRepository:
    return HouseholdMemberRepository(mongo_manager.household_members_collection())


def get_invitation_repository() -> InvitationRepository:
    return InvitationRepository(mongo_manager.invitations_collection())


def get_household_budget_contribution_repository() -> HouseholdBudgetContributionRepository:
    return HouseholdBudgetContributionRepository(
        mongo_manager.household_budget_contributions_collection()
    )


def get_household_shared_expense_repository() -> HouseholdSharedExpenseRepository:
    return HouseholdSharedExpenseRepository(mongo_manager.household_shared_expenses_collection())


def get_household_expense_split_repository() -> HouseholdExpenseSplitRepository:
    return HouseholdExpenseSplitRepository(mongo_manager.household_expense_splits_collection())


def get_user_meal_usage_repository() -> UserMealUsageRepository:
    return UserMealUsageRepository(mongo_manager.user_meal_usage_entries_collection())


def get_subscription_account_repository() -> SubscriptionAccountRepository:
    return SubscriptionAccountRepository(mongo_manager.subscription_accounts_collection())


def get_wallet_account_repository() -> WalletAccountRepository:
    return WalletAccountRepository(mongo_manager.wallet_accounts_collection())


def get_wallet_ledger_repository() -> WalletLedgerRepository:
    return WalletLedgerRepository(mongo_manager.wallet_ledger_entries_collection())


def get_goal_target_service() -> GoalTargetService:
    return GoalTargetService()


def get_stripe_billing_gateway() -> StripeBillingGateway:
    return StripeBillingGateway(settings=get_settings())


def get_auth_service(
    user_repository: UserRepository = Depends(get_user_repository),
    password_reset_token_repository: PasswordResetTokenRepository = Depends(
        get_password_reset_token_repository
    ),
) -> AuthService:
    return AuthService(
        user_repository=user_repository,
        email_service=get_email_service(),
        password_reset_token_repository=password_reset_token_repository,
        settings=get_settings(),
    )


def get_email_service() -> EmailService:
    settings = get_settings()
    return EmailService(
        sender=build_email_sender(settings),
        web_app_base_url=settings.web_app_base_url,
    )


def get_grocery_service(
    grocery_repository: GroceryRepository = Depends(get_grocery_repository),
    discount_repository: DiscountRepository = Depends(get_discount_repository),
) -> GroceryService:
    return GroceryService(grocery_repository=grocery_repository, discount_repository=discount_repository)


def get_discount_audit_repository() -> DiscountAuditRepository:
    return DiscountAuditRepository(mongo_manager.grocery_discount_audit_logs_collection())


def get_discount_service(
    discount_repository: DiscountRepository = Depends(get_discount_repository),
    grocery_repository: GroceryRepository = Depends(get_grocery_repository),
    audit_repository: DiscountAuditRepository = Depends(get_discount_audit_repository),
    user_repository: UserRepository = Depends(get_user_repository),
) -> DiscountService:
    return DiscountService(
        discount_repository=discount_repository,
        grocery_repository=grocery_repository,
        audit_repository=audit_repository,
        user_repository=user_repository,
    )


def _get_push_notification_service_dependency(
    push_device_repository: PushDeviceRepository = Depends(get_push_device_repository),
) -> PushNotificationService:
    return PushNotificationService(
        push_device_repository=push_device_repository,
        sender=build_push_notification_sender(get_settings()),
    )


def get_household_communication_service(
    notification_repository: NotificationRepository = Depends(get_notification_repository),
    user_repository: UserRepository = Depends(get_user_repository),
    push_notification_service: PushNotificationService = Depends(
        _get_push_notification_service_dependency
    ),
) -> HouseholdCommunicationService:
    return HouseholdCommunicationService(
        notification_repository=notification_repository,
        user_repository=user_repository,
        email_service=get_email_service(),
        push_notification_service=push_notification_service,
    )


def get_household_service(
    household_repository: HouseholdRepository = Depends(get_household_repository),
    household_member_repository: HouseholdMemberRepository = Depends(get_household_member_repository),
    invitation_repository: InvitationRepository = Depends(get_invitation_repository),
    user_repository: UserRepository = Depends(get_user_repository),
    household_communication_service: HouseholdCommunicationService = Depends(
        get_household_communication_service
    ),
) -> HouseholdService:
    return HouseholdService(
        household_repository=household_repository,
        household_member_repository=household_member_repository,
        invitation_repository=invitation_repository,
        user_repository=user_repository,
        household_communication_service=household_communication_service,
    )


def get_household_budgeting_service(
    household_service: HouseholdService = Depends(get_household_service),
    household_repository: HouseholdRepository = Depends(get_household_repository),
    household_member_repository: HouseholdMemberRepository = Depends(get_household_member_repository),
    household_budget_contribution_repository: HouseholdBudgetContributionRepository = Depends(
        get_household_budget_contribution_repository
    ),
    household_shared_expense_repository: HouseholdSharedExpenseRepository = Depends(
        get_household_shared_expense_repository
    ),
    household_expense_split_repository: HouseholdExpenseSplitRepository = Depends(
        get_household_expense_split_repository
    ),
    household_communication_service: HouseholdCommunicationService = Depends(
        get_household_communication_service
    ),
    order_repository: OrderRepository = Depends(get_order_repository),
    meal_order_repository: MealOrderRepository = Depends(get_meal_order_repository),
) -> HouseholdBudgetingService:
    return HouseholdBudgetingService(
        household_service=household_service,
        household_repository=household_repository,
        household_member_repository=household_member_repository,
        household_budget_contribution_repository=household_budget_contribution_repository,
        household_shared_expense_repository=household_shared_expense_repository,
        household_expense_split_repository=household_expense_split_repository,
        household_communication_service=household_communication_service,
        order_repository=order_repository,
        meal_order_repository=meal_order_repository,
    )


def get_grocery_search_embedding_service() -> MealSearchEmbeddingService:
    settings = get_settings()
    return MealSearchEmbeddingService(
        api_key=(
            settings.openai_api_key.get_secret_value()
            if settings.openai_api_key is not None
            else None
        ),
        model_name=settings.openai_grocery_search_embedding_model,
        timeout_seconds=settings.openai_grocery_search_embedding_timeout_seconds,
    )


def get_grocery_catalog_embedding_service(
    grocery_repository: GroceryRepository = Depends(get_grocery_repository),
) -> GroceryCatalogEmbeddingService:
    return GroceryCatalogEmbeddingService(
        grocery_repository=grocery_repository,
        embedding_service=get_grocery_search_embedding_service(),
    )


def get_admin_grocery_service(
    grocery_repository: GroceryRepository = Depends(get_grocery_repository),
    grocery_catalog_embedding_service: GroceryCatalogEmbeddingService = Depends(
        get_grocery_catalog_embedding_service
    ),
) -> AdminGroceryService:
    return AdminGroceryService(
        grocery_repository=grocery_repository,
        grocery_catalog_embedding_service=grocery_catalog_embedding_service,
    )


def get_meal_search_embedding_service() -> MealSearchEmbeddingService:
    settings = get_settings()
    return MealSearchEmbeddingService(
        api_key=(
            settings.openai_api_key.get_secret_value()
            if settings.openai_api_key is not None
            else None
        ),
        model_name=settings.openai_meal_search_embedding_model,
        timeout_seconds=settings.openai_meal_search_embedding_timeout_seconds,
    )


def get_meal_catalog_embedding_service(
    meal_repository: MealRepository = Depends(get_meal_repository),
) -> MealCatalogEmbeddingService:
    return MealCatalogEmbeddingService(
        meal_repository=meal_repository,
        embedding_service=get_meal_search_embedding_service(),
    )


def get_admin_meal_service(
    meal_repository: MealRepository = Depends(get_meal_repository),
    grocery_repository: GroceryRepository = Depends(get_grocery_repository),
    measurement_service: MeasurementService = Depends(get_measurement_service),
    meal_catalog_embedding_service: MealCatalogEmbeddingService = Depends(
        get_meal_catalog_embedding_service
    ),
) -> AdminMealService:
    return AdminMealService(
        meal_repository=meal_repository,
        grocery_repository=grocery_repository,
        measurement_service=measurement_service,
        meal_catalog_embedding_service=meal_catalog_embedding_service,
    )


def get_media_storage_service() -> MediaStorageService:
    return MediaStorageService(settings=get_settings())


def get_meal_favorite_repository() -> MealFavoriteRepository:
    return MealFavoriteRepository(mongo_manager.meal_favorites_collection())


def get_meal_cart_repository() -> MealCartRepository:
    return MealCartRepository(mongo_manager.meal_carts_collection())


def get_meal_service(
    meal_repository: MealRepository = Depends(get_meal_repository),
    grocery_repository: GroceryRepository = Depends(get_grocery_repository),
    meal_favorite_repository: MealFavoriteRepository = Depends(get_meal_favorite_repository),
) -> MealService:
    return MealService(
        meal_repository=meal_repository,
        grocery_repository=grocery_repository,
        meal_favorite_repository=meal_favorite_repository,
    )


def get_meal_cart_service(
    meal_cart_repository: MealCartRepository = Depends(get_meal_cart_repository),
    meal_repository: MealRepository = Depends(get_meal_repository),
    address_repository: AddressRepository = Depends(get_address_repository),
    settings: Settings = Depends(get_settings),
) -> MealCartService:
    return MealCartService(
        meal_cart_repository=meal_cart_repository,
        meal_repository=meal_repository,
        address_repository=address_repository,
        default_currency=settings.meal_default_currency,
        cart_ttl_seconds=settings.meal_cart_ttl_seconds,
        max_servings_per_line=settings.meal_max_servings_per_line,
    )


def get_survey_service(
    survey_repository: SurveyRepository = Depends(get_survey_repository),
    survey_response_repository: SurveyResponseRepository = Depends(get_survey_response_repository),
) -> SurveyService:
    return SurveyService(
        survey_repository=survey_repository,
        survey_response_repository=survey_response_repository,
    )


def get_user_meal_usage_service(
    user_meal_usage_repository: UserMealUsageRepository = Depends(get_user_meal_usage_repository),
    goal_target_service: GoalTargetService = Depends(get_goal_target_service),
) -> UserMealUsageService:
    return UserMealUsageService(
        user_meal_usage_repository=user_meal_usage_repository,
        goal_target_service=goal_target_service,
    )


def get_kitchen_service(
    kitchen_repository: KitchenRepository = Depends(get_kitchen_repository),
    user_pantry_repository: UserPantryRepository = Depends(get_user_pantry_repository),
    order_repository: OrderRepository = Depends(get_order_repository),
    saved_meal_plan_repository: SavedMealPlanRepository = Depends(get_saved_meal_plan_repository),
) -> KitchenService:
    return KitchenService(
        kitchen_repository=kitchen_repository,
        user_pantry_repository=user_pantry_repository,
        order_repository=order_repository,
        saved_meal_plan_repository=saved_meal_plan_repository,
    )


def get_meal_conversation_service(
    user_repository: UserRepository = Depends(get_user_repository),
    meal_conversation_repository: MealConversationRepository = Depends(get_meal_conversation_repository),
    meal_repository: MealRepository = Depends(get_meal_repository),
    grocery_repository: GroceryRepository = Depends(get_grocery_repository),
    saved_meal_plan_repository: SavedMealPlanRepository = Depends(get_saved_meal_plan_repository),
    user_pantry_repository: UserPantryRepository = Depends(get_user_pantry_repository),
    kitchen_service: KitchenService = Depends(get_kitchen_service),
    user_meal_usage_service: UserMealUsageService = Depends(get_user_meal_usage_service),
) -> MealConversationService:
    return MealConversationService(
        settings=get_settings(),
        user_repository=user_repository,
        meal_conversation_repository=meal_conversation_repository,
        meal_repository=meal_repository,
        grocery_repository=grocery_repository,
        saved_meal_plan_repository=saved_meal_plan_repository,
        user_pantry_repository=user_pantry_repository,
        kitchen_service=kitchen_service,
        user_meal_usage_service=user_meal_usage_service,
    )


def get_saved_meal_plan_service(
    saved_meal_plan_repository: SavedMealPlanRepository = Depends(get_saved_meal_plan_repository),
    meal_repository: MealRepository = Depends(get_meal_repository),
    grocery_repository: GroceryRepository = Depends(get_grocery_repository),
    user_pantry_repository: UserPantryRepository = Depends(get_user_pantry_repository),
    kitchen_service: KitchenService = Depends(get_kitchen_service),
    user_meal_usage_service: UserMealUsageService = Depends(get_user_meal_usage_service),
) -> SavedMealPlanService:
    return SavedMealPlanService(
        saved_meal_plan_repository=saved_meal_plan_repository,
        meal_repository=meal_repository,
        grocery_repository=grocery_repository,
        user_pantry_repository=user_pantry_repository,
        kitchen_service=kitchen_service,
        user_meal_usage_service=user_meal_usage_service,
    )


def get_user_pantry_service(
    kitchen_service: KitchenService = Depends(get_kitchen_service),
) -> UserPantryService:
    return UserPantryService(kitchen_service=kitchen_service)


def get_address_service(
    address_repository: AddressRepository = Depends(get_address_repository),
) -> AddressService:
    return AddressService(address_repository=address_repository)


def get_inventory_service(
    inventory_repository: InventoryRepository = Depends(get_inventory_repository),
    grocery_repository: GroceryRepository = Depends(get_grocery_repository),
    discount_repository: DiscountRepository = Depends(get_discount_repository),
    settings: Settings = Depends(get_settings),
) -> InventoryService:
    return InventoryService(
        inventory_repository=inventory_repository,
        grocery_repository=grocery_repository,
        discount_repository=discount_repository,
        default_store_id=settings.grocery_default_store_id,
    )


def get_cart_service(
    cart_repository: CartRepository = Depends(get_cart_repository),
    grocery_repository: GroceryRepository = Depends(get_grocery_repository),
    inventory_repository: InventoryRepository = Depends(get_inventory_repository),
    address_repository: AddressRepository = Depends(get_address_repository),
    inventory_service: InventoryService = Depends(get_inventory_service),
    saved_meal_plan_repository: SavedMealPlanRepository = Depends(get_saved_meal_plan_repository),
    subscription_account_repository: SubscriptionAccountRepository = Depends(get_subscription_account_repository),
    settings: Settings = Depends(get_settings),
) -> CartService:
    return CartService(
        cart_repository=cart_repository,
        grocery_repository=grocery_repository,
        inventory_repository=inventory_repository,
        address_repository=address_repository,
        inventory_service=inventory_service,
        saved_meal_plan_repository=saved_meal_plan_repository,
        subscription_account_repository=subscription_account_repository,
        default_store_id=settings.grocery_default_store_id,
        default_currency=settings.grocery_default_currency,
        free_delivery_subtotal_minor=settings.grocery_free_delivery_subtotal_minor,
        cart_ttl_seconds=settings.grocery_cart_ttl_seconds,
        max_quantity_per_line=settings.grocery_max_quantity_per_line,
    )


def get_notification_service(
    notification_repository: NotificationRepository = Depends(get_notification_repository),
    saved_meal_plan_repository: SavedMealPlanRepository = Depends(get_saved_meal_plan_repository),
) -> NotificationService:
    return NotificationService(
        notification_repository=notification_repository,
        saved_meal_plan_repository=saved_meal_plan_repository,
    )


def get_subscription_communication_service(
    notification_repository: NotificationRepository = Depends(get_notification_repository),
    user_repository: UserRepository = Depends(get_user_repository),
    push_notification_service: PushNotificationService = Depends(
        _get_push_notification_service_dependency
    ),
) -> SubscriptionCommunicationService:
    return SubscriptionCommunicationService(
        notification_repository=notification_repository,
        user_repository=user_repository,
        email_service=get_email_service(),
        push_notification_service=push_notification_service,
        notification_copy_service=NotificationCopyService(),
    )


def get_billing_service(
    subscription_repository: SubscriptionAccountRepository = Depends(get_subscription_account_repository),
    wallet_account_repository: WalletAccountRepository = Depends(get_wallet_account_repository),
    wallet_ledger_repository: WalletLedgerRepository = Depends(get_wallet_ledger_repository),
    subscription_communication_service: SubscriptionCommunicationService = Depends(
        get_subscription_communication_service
    ),
) -> BillingService:
    return BillingService(
        subscription_repository=subscription_repository,
        wallet_account_repository=wallet_account_repository,
        wallet_ledger_repository=wallet_ledger_repository,
        subscription_communication_service=subscription_communication_service,
    )


def get_admin_customer_audit_repository() -> AdminCustomerAuditRepository:
    return AdminCustomerAuditRepository(mongo_manager.admin_customer_audit_logs_collection())


def get_admin_customer_service(
    user_repository: UserRepository = Depends(get_user_repository),
    subscription_repository: SubscriptionAccountRepository = Depends(get_subscription_account_repository),
    order_repository: OrderRepository = Depends(get_order_repository),
    meal_order_repository: MealOrderRepository = Depends(get_meal_order_repository),
    billing_service: BillingService = Depends(get_billing_service),
    stripe_gateway: StripeBillingGateway = Depends(get_stripe_billing_gateway),
    admin_customer_audit_repository: AdminCustomerAuditRepository = Depends(
        get_admin_customer_audit_repository
    ),
) -> AdminCustomerService:
    return AdminCustomerService(
        user_repository=user_repository,
        subscription_repository=subscription_repository,
        order_repository=order_repository,
        meal_order_repository=meal_order_repository,
        billing_service=billing_service,
        stripe_gateway=stripe_gateway,
        admin_customer_audit_repository=admin_customer_audit_repository,
    )


def get_delivery_window_service() -> DeliveryWindowService:
    return DeliveryWindowService()


def get_checkout_service(
    cart_service: CartService = Depends(get_cart_service),
    cart_repository: CartRepository = Depends(get_cart_repository),
    checkout_quote_repository: CheckoutQuoteRepository = Depends(get_checkout_quote_repository),
    order_repository: OrderRepository = Depends(get_order_repository),
    payment_attempt_repository: PaymentAttemptRepository = Depends(get_payment_attempt_repository),
    grocery_repository: GroceryRepository = Depends(get_grocery_repository),
    inventory_repository: InventoryRepository = Depends(get_inventory_repository),
    address_repository: AddressRepository = Depends(get_address_repository),
    inventory_service: InventoryService = Depends(get_inventory_service),
    billing_service: BillingService = Depends(get_billing_service),
    stripe_gateway: StripeBillingGateway = Depends(get_stripe_billing_gateway),
    delivery_window_service: DeliveryWindowService = Depends(get_delivery_window_service),
    settings: Settings = Depends(get_settings),
) -> CheckoutService:
    return CheckoutService(
        cart_service=cart_service,
        cart_repository=cart_repository,
        checkout_quote_repository=checkout_quote_repository,
        order_repository=order_repository,
        payment_attempt_repository=payment_attempt_repository,
        grocery_repository=grocery_repository,
        inventory_repository=inventory_repository,
        address_repository=address_repository,
        inventory_service=inventory_service,
        billing_service=billing_service,
        stripe_gateway=stripe_gateway,
        delivery_window_service=delivery_window_service,
        default_store_id=settings.grocery_default_store_id,
        default_currency=settings.grocery_default_currency,
        free_delivery_subtotal_minor=settings.grocery_free_delivery_subtotal_minor,
        delivery_timezone_name=settings.grocery_delivery_default_timezone,
        quote_ttl_seconds=settings.grocery_checkout_quote_ttl_seconds,
        cancellation_window_minutes=settings.grocery_order_cancellation_window_minutes,
    )


def get_order_service(
    order_repository: OrderRepository = Depends(get_order_repository),
    grocery_repository: GroceryRepository = Depends(get_grocery_repository),
) -> OrderService:
    return OrderService(
        order_repository=order_repository,
        grocery_repository=grocery_repository,
    )


def get_meal_order_service(
    meal_order_repository: MealOrderRepository = Depends(get_meal_order_repository),
) -> MealOrderService:
    return MealOrderService(meal_order_repository=meal_order_repository)


def get_meal_checkout_service(
    meal_cart_service: MealCartService = Depends(get_meal_cart_service),
    meal_cart_repository: MealCartRepository = Depends(get_meal_cart_repository),
    checkout_quote_repository: CheckoutQuoteRepository = Depends(get_checkout_quote_repository),
    meal_order_repository: MealOrderRepository = Depends(get_meal_order_repository),
    payment_attempt_repository: PaymentAttemptRepository = Depends(get_payment_attempt_repository),
    address_repository: AddressRepository = Depends(get_address_repository),
    billing_service: BillingService = Depends(get_billing_service),
    stripe_gateway: StripeBillingGateway = Depends(get_stripe_billing_gateway),
    delivery_window_service: DeliveryWindowService = Depends(get_delivery_window_service),
    settings: Settings = Depends(get_settings),
) -> MealCheckoutService:
    return MealCheckoutService(
        meal_cart_service=meal_cart_service,
        meal_cart_repository=meal_cart_repository,
        checkout_quote_repository=checkout_quote_repository,
        meal_order_repository=meal_order_repository,
        payment_attempt_repository=payment_attempt_repository,
        address_repository=address_repository,
        billing_service=billing_service,
        stripe_gateway=stripe_gateway,
        delivery_window_service=delivery_window_service,
        default_currency=settings.meal_default_currency,
        delivery_timezone_name=settings.meal_delivery_default_timezone,
        express_delivery_fee_minor=settings.meal_express_delivery_fee_minor,
        quote_ttl_seconds=settings.meal_checkout_quote_ttl_seconds,
        cancellation_window_minutes=settings.meal_order_cancellation_window_minutes,
    )


def get_meal_plan_checkout_service(
    saved_meal_plan_repository: SavedMealPlanRepository = Depends(get_saved_meal_plan_repository),
    saved_meal_plan_service: SavedMealPlanService = Depends(get_saved_meal_plan_service),
    meal_repository: MealRepository = Depends(get_meal_repository),
    checkout_quote_repository: CheckoutQuoteRepository = Depends(get_checkout_quote_repository),
    meal_order_repository: MealOrderRepository = Depends(get_meal_order_repository),
    payment_attempt_repository: PaymentAttemptRepository = Depends(get_payment_attempt_repository),
    address_repository: AddressRepository = Depends(get_address_repository),
    billing_service: BillingService = Depends(get_billing_service),
    stripe_gateway: StripeBillingGateway = Depends(get_stripe_billing_gateway),
    settings: Settings = Depends(get_settings),
) -> MealPlanCheckoutService:
    return MealPlanCheckoutService(
        saved_meal_plan_repository=saved_meal_plan_repository,
        meal_repository=meal_repository,
        checkout_quote_repository=checkout_quote_repository,
        meal_order_repository=meal_order_repository,
        payment_attempt_repository=payment_attempt_repository,
        address_repository=address_repository,
        billing_service=billing_service,
        saved_meal_plan_service=saved_meal_plan_service,
        stripe_gateway=stripe_gateway,
        default_currency=settings.meal_default_currency,
        quote_ttl_seconds=settings.meal_checkout_quote_ttl_seconds,
        cancellation_window_minutes=settings.meal_order_cancellation_window_minutes,
    )


def get_refund_service(
    order_repository: OrderRepository = Depends(get_order_repository),
    refund_repository: RefundRepository = Depends(get_refund_repository),
    billing_service: BillingService = Depends(get_billing_service),
    stripe_gateway: StripeBillingGateway = Depends(get_stripe_billing_gateway),
) -> RefundService:
    return RefundService(
        order_repository=order_repository,
        refund_repository=refund_repository,
        billing_service=billing_service,
        stripe_gateway=stripe_gateway,
    )


def get_promotion_context_service(
    meal_conversation_repository: MealConversationRepository = Depends(get_meal_conversation_repository),
) -> PromotionContextService:
    return PromotionContextService(meal_conversation_repository=meal_conversation_repository)


def get_admin_promotion_service(
    campaign_repository: PromotionCampaignRepository = Depends(get_promotion_campaign_repository),
    user_repository: UserRepository = Depends(get_user_repository),
    meal_conversation_repository: MealConversationRepository = Depends(get_meal_conversation_repository),
    promotion_context_service: PromotionContextService = Depends(get_promotion_context_service),
) -> AdminPromotionService:
    return AdminPromotionService(
        campaign_repository=campaign_repository,
        user_repository=user_repository,
        meal_conversation_repository=meal_conversation_repository,
        promotion_context_service=promotion_context_service,
    )


def get_promotion_generation_service(
    settings: Settings = Depends(get_settings),
    campaign_repository: PromotionCampaignRepository = Depends(get_promotion_campaign_repository),
    draft_repository: PromotionDraftRepository = Depends(get_promotion_draft_repository),
    user_repository: UserRepository = Depends(get_user_repository),
) -> PromotionGenerationService:
    return PromotionGenerationService(
        settings=settings,
        campaign_repository=campaign_repository,
        draft_repository=draft_repository,
        user_repository=user_repository,
    )


def get_promotion_review_service(
    campaign_repository: PromotionCampaignRepository = Depends(get_promotion_campaign_repository),
    draft_repository: PromotionDraftRepository = Depends(get_promotion_draft_repository),
) -> PromotionReviewService:
    return PromotionReviewService(
        campaign_repository=campaign_repository,
        draft_repository=draft_repository,
    )


def get_promotion_delivery_service(
    campaign_repository: PromotionCampaignRepository = Depends(get_promotion_campaign_repository),
    draft_repository: PromotionDraftRepository = Depends(get_promotion_draft_repository),
    delivery_repository: PromotionDeliveryRepository = Depends(get_promotion_delivery_repository),
    meal_conversation_repository: MealConversationRepository = Depends(get_meal_conversation_repository),
    notification_repository: NotificationRepository = Depends(get_notification_repository),
) -> PromotionDeliveryService:
    return PromotionDeliveryService(
        campaign_repository=campaign_repository,
        draft_repository=draft_repository,
        delivery_repository=delivery_repository,
        meal_conversation_repository=meal_conversation_repository,
        notification_repository=notification_repository,
    )


def get_push_device_service(
    push_device_repository: PushDeviceRepository = Depends(get_push_device_repository),
) -> PushDeviceService:
    return PushDeviceService(push_device_repository=push_device_repository)


def get_push_notification_service(
    push_device_repository: PushDeviceRepository = Depends(get_push_device_repository),
) -> PushNotificationService:
    return _get_push_notification_service_dependency(
        push_device_repository=push_device_repository
    )


def get_order_fulfillment_communication_service(
    notification_repository: NotificationRepository = Depends(get_notification_repository),
    user_repository: UserRepository = Depends(get_user_repository),
    email_service: EmailService = Depends(get_email_service),
    push_notification_service: PushNotificationService = Depends(get_push_notification_service),
    settings: Settings = Depends(get_settings),
) -> OrderFulfillmentCommunicationService:
    return OrderFulfillmentCommunicationService(
        notification_repository=notification_repository,
        user_repository=user_repository,
        email_service=email_service,
        push_notification_service=push_notification_service,
        notification_copy_service=NotificationCopyService(),
        web_app_base_url=settings.web_app_base_url,
    )


def get_chef_fulfillment_service(
    meal_order_repository: MealOrderRepository = Depends(get_meal_order_repository),
    user_repository: UserRepository = Depends(get_user_repository),
    communication_service: OrderFulfillmentCommunicationService = Depends(get_order_fulfillment_communication_service),
) -> ChefFulfillmentService:
    return ChefFulfillmentService(
        meal_order_repository=meal_order_repository,
        user_repository=user_repository,
        communication_service=communication_service,
    )


def get_shopper_fulfillment_service(
    order_repository: OrderRepository = Depends(get_order_repository),
    user_repository: UserRepository = Depends(get_user_repository),
    communication_service: OrderFulfillmentCommunicationService = Depends(get_order_fulfillment_communication_service),
) -> ShopperFulfillmentService:
    return ShopperFulfillmentService(
        order_repository=order_repository,
        user_repository=user_repository,
        communication_service=communication_service,
    )


def get_staff_service(
    user_repository: UserRepository = Depends(get_user_repository),
    invitation_repository: InvitationRepository = Depends(get_invitation_repository),
) -> StaffService:
    return StaffService(
        user_repository=user_repository,
        invitation_repository=invitation_repository,
        email_service=get_email_service(),
        settings=get_settings(),
    )


def get_current_user(
    credentials: HTTPAuthorizationCredentials | None = Depends(bearer_scheme),
    user_repository: UserRepository = Depends(get_user_repository),
) -> User:
    if credentials is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Authentication required.",
        )

    try:
        user_id = decode_access_token(credentials.credentials)
    except JWTError as exc:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid or expired access token.",
        ) from exc

    user = user_repository.find_by_id(user_id)
    if user is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Authenticated user not found.",
        )
    return user


def require_platform_user(
    current_user: User = Depends(get_current_user),
) -> User:
    if UserType.PLATFORM_USER not in current_user.user_types:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Platform user access required.",
        )
    return current_user


def require_chef_user(
    current_user: User = Depends(get_current_user),
) -> User:
    if UserType.CHEF not in current_user.user_types:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Chef access required.",
        )
    return current_user


def require_shopper_user(
    current_user: User = Depends(get_current_user),
) -> User:
    if UserType.SHOPPER not in current_user.user_types:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Shopper access required.",
        )
    return current_user


def get_optional_current_user(
    credentials: HTTPAuthorizationCredentials | None = Depends(bearer_scheme),
    user_repository: UserRepository = Depends(get_user_repository),
) -> User | None:
    if credentials is None:
        return None

    try:
        user_id = decode_access_token(credentials.credentials)
    except JWTError as exc:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid or expired access token.",
        ) from exc

    user = user_repository.find_by_id(user_id)
    if user is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Authenticated user not found.",
        )
    return user


