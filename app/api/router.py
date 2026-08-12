from fastapi import APIRouter

from app.core.config import get_settings
from app.api.v1.endpoints.admin_cache import router as admin_cache_router
from app.api.v1.endpoints.admin_customers import router as admin_customers_router
from app.api.v1.endpoints.admin_discounts import router as admin_discounts_router
from app.api.v1.endpoints.admin_fulfillment import router as admin_fulfillment_router
from app.api.v1.endpoints.admin_groceries import router as admin_groceries_router
from app.api.v1.endpoints.admin_grocery_orders import router as admin_grocery_orders_router
from app.api.v1.endpoints.admin_inventory import router as admin_inventory_router
from app.api.v1.endpoints.admin_meal_orders import router as admin_meal_orders_router
from app.api.v1.endpoints.admin_meals import router as admin_meals_router
from app.api.v1.endpoints.admin_promotions import router as admin_promotions_router
from app.api.v1.endpoints.admin_staff import router as admin_staff_router
from app.api.v1.endpoints.addresses import router as addresses_router
from app.api.v1.endpoints.auth import router as auth_router
from app.api.v1.endpoints.billing import router as billing_router
from app.api.v1.endpoints.cart import router as cart_router
from app.api.v1.endpoints.checkout import router as checkout_router
from app.api.v1.endpoints.chef_orders import router as chef_orders_router
from app.api.v1.endpoints.groceries import router as groceries_router
from app.api.v1.endpoints.health import router as health_router
from app.api.v1.endpoints.households import router as households_router
from app.api.v1.endpoints.kitchen import router as kitchen_router
from app.api.v1.endpoints.meal_cart import router as meal_cart_router
from app.api.v1.endpoints.meal_checkout import router as meal_checkout_router
from app.api.v1.endpoints.meal_conversations import router as meal_conversations_router
from app.api.v1.endpoints.meal_orders import router as meal_orders_router
from app.api.v1.endpoints.meal_plan_cart_bridge import router as meal_plan_cart_bridge_router
from app.api.v1.endpoints.meal_plan_checkout import router as meal_plan_checkout_router
from app.api.v1.endpoints.meal_planner import router as meal_planner_router
from app.api.v1.endpoints.meal_planner_monitoring import router as meal_planner_monitoring_router
from app.api.v1.endpoints.meals import router as meals_router
from app.api.v1.endpoints.notifications import router as notifications_router
from app.api.v1.endpoints.orders import router as orders_router
from app.api.v1.endpoints.push_devices import router as push_devices_router
from app.api.v1.endpoints.realtime import router as realtime_router
from app.api.v1.endpoints.saved_meal_plans import router as saved_meal_plans_router
from app.api.v1.endpoints.shopper_orders import router as shopper_orders_router
from app.api.v1.endpoints.surveys import router as surveys_router
from app.api.v1.endpoints.user_meal_usage import router as user_meal_usage_router
from app.api.v1.endpoints.user_pantry import router as user_pantry_router
from app.api.v1.endpoints.admin_surveys import router as admin_surveys_router

settings = get_settings()

api_router = APIRouter()
api_router.include_router(health_router)
api_router.include_router(auth_router, prefix=settings.api_v1_prefix)
api_router.include_router(billing_router, prefix=settings.api_v1_prefix)
api_router.include_router(addresses_router, prefix=settings.api_v1_prefix)
api_router.include_router(cart_router, prefix=settings.api_v1_prefix)
api_router.include_router(checkout_router, prefix=settings.api_v1_prefix)
api_router.include_router(chef_orders_router, prefix=settings.api_v1_prefix)
api_router.include_router(groceries_router, prefix=settings.api_v1_prefix)
api_router.include_router(households_router, prefix=settings.api_v1_prefix)
api_router.include_router(meals_router, prefix=settings.api_v1_prefix)
api_router.include_router(meal_cart_router, prefix=settings.api_v1_prefix)
api_router.include_router(meal_checkout_router, prefix=settings.api_v1_prefix)
api_router.include_router(meal_orders_router, prefix=settings.api_v1_prefix)
api_router.include_router(meal_plan_cart_bridge_router, prefix=settings.api_v1_prefix)
api_router.include_router(meal_plan_checkout_router, prefix=settings.api_v1_prefix)
api_router.include_router(meal_conversations_router, prefix=settings.api_v1_prefix)
api_router.include_router(meal_planner_router, prefix=settings.api_v1_prefix)
api_router.include_router(meal_planner_monitoring_router, prefix=settings.api_v1_prefix)
api_router.include_router(saved_meal_plans_router, prefix=settings.api_v1_prefix)
api_router.include_router(shopper_orders_router, prefix=settings.api_v1_prefix)
api_router.include_router(surveys_router, prefix=settings.api_v1_prefix)
api_router.include_router(kitchen_router, prefix=settings.api_v1_prefix)
api_router.include_router(user_meal_usage_router, prefix=settings.api_v1_prefix)
api_router.include_router(user_pantry_router, prefix=settings.api_v1_prefix)
api_router.include_router(notifications_router, prefix=settings.api_v1_prefix)
api_router.include_router(orders_router, prefix=settings.api_v1_prefix)
api_router.include_router(realtime_router, prefix=settings.api_v1_prefix)
api_router.include_router(push_devices_router, prefix=settings.api_v1_prefix)
api_router.include_router(admin_cache_router, prefix=settings.api_v1_prefix)
api_router.include_router(admin_customers_router, prefix=settings.api_v1_prefix)
api_router.include_router(admin_discounts_router, prefix=settings.api_v1_prefix)
api_router.include_router(admin_fulfillment_router, prefix=settings.api_v1_prefix)
api_router.include_router(admin_groceries_router, prefix=settings.api_v1_prefix)
api_router.include_router(admin_inventory_router, prefix=settings.api_v1_prefix)
api_router.include_router(admin_grocery_orders_router, prefix=settings.api_v1_prefix)
api_router.include_router(admin_meal_orders_router, prefix=settings.api_v1_prefix)
api_router.include_router(admin_meals_router, prefix=settings.api_v1_prefix)
api_router.include_router(admin_promotions_router, prefix=settings.api_v1_prefix)
api_router.include_router(admin_staff_router, prefix=settings.api_v1_prefix)
api_router.include_router(admin_surveys_router, prefix=settings.api_v1_prefix)
