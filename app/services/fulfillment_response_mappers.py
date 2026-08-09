from app.models.meal_order import MealOrder
from app.models.order import Order
from app.schemas.fulfillment import (
    AssignmentHistoryEntryResponse,
    GroceryOrderFulfillmentItemResponse,
    GroceryOrderFulfillmentResponse,
    MealOrderFulfillmentItemResponse,
    MealOrderFulfillmentResponse,
)


def _assignment_history_response(order) -> list[AssignmentHistoryEntryResponse]:
    return [
        AssignmentHistoryEntryResponse(
            action=entry.action,
            worker_id=entry.worker_id,
            actor_user_id=entry.actor_user_id,
            note=entry.note,
            created_at=entry.created_at,
        )
        for entry in order.assignment_history
    ]


def meal_order_to_fulfillment_response(order: MealOrder) -> MealOrderFulfillmentResponse:
    return MealOrderFulfillmentResponse(
        id=order.id,
        order_number=order.order_number,
        user_id=order.user_id,
        status=order.status.value,
        currency=order.currency,
        items=[
            MealOrderFulfillmentItemResponse(
                id=item.id,
                meal_id=item.meal_id,
                meal_name=item.meal_name,
                img_url=item.img_url,
                servings=item.servings,
                unit_price_minor=item.unit_price_minor,
                line_total_minor=item.line_total_minor,
                currency=item.currency,
                delivery_date=item.delivery_date,
                slot=item.slot,
            )
            for item in order.items
        ],
        total_minor=order.pricing_summary.total_minor,
        fulfillment_status=order.fulfillment_status.value,
        assigned_worker_id=order.assigned_worker_id,
        assigned_by=order.assigned_by,
        assigned_at=order.assigned_at,
        assignment_history=_assignment_history_response(order),
        metadata=order.metadata,
        created_at=order.created_at,
        updated_at=order.updated_at,
    )


def order_to_fulfillment_response(order: Order) -> GroceryOrderFulfillmentResponse:
    return GroceryOrderFulfillmentResponse(
        id=order.id,
        order_number=order.order_number,
        user_id=order.user_id,
        status=order.status.value,
        currency=order.currency,
        items=[
            GroceryOrderFulfillmentItemResponse(
                id=item.id,
                product_id=item.product_id,
                product_name=item.product_name,
                img_url=item.img_url,
                quantity=item.quantity,
                unit_label=item.unit_label,
                unit_price_minor=item.unit_price_minor,
                line_total_minor=item.line_total_minor,
                currency=item.currency,
                source_meal_id=item.source_meal_id,
            )
            for item in order.items
        ],
        total_minor=order.pricing_summary.total_minor,
        fulfillment_status=order.fulfillment_status.value,
        assigned_worker_id=order.assigned_worker_id,
        assigned_by=order.assigned_by,
        assigned_at=order.assigned_at,
        assignment_history=_assignment_history_response(order),
        metadata=order.metadata,
        created_at=order.created_at,
        updated_at=order.updated_at,
    )
