from dataclasses import dataclass
from datetime import datetime


@dataclass(frozen=True, slots=True)
class MealFavorite:
    id: str
    user_id: str
    meal_id: str
    created_at: datetime
