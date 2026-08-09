def apply_category_discount(base_price_minor: int, discount_percent: float | None) -> tuple[int, float]:
    if not discount_percent or discount_percent <= 0:
        return base_price_minor, 0.0

    final_price_minor = int(round(base_price_minor * (1 - discount_percent / 100)))
    return max(final_price_minor, 0), discount_percent
