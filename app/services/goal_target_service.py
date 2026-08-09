from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True, slots=True)
class GoalTargetSnapshot:
    weekly_budget: int
    daily_calories: int
    protein_g: int
    carbs_g: int
    fat_g: int


@dataclass(frozen=True, slots=True)
class _Anchor:
    weekly_budget: float
    calories: float
    protein_g: float
    carbs_g: float
    fat_g: float


@dataclass(frozen=True, slots=True)
class _InterpolatedValues:
    daily_calories: int
    protein_g: int
    carbs_g: int
    fat_g: int


class GoalTargetService:
    def calculate_from_user_configuration(
        self,
        user_configuration: dict[str, Any],
    ) -> GoalTargetSnapshot:
        goal = str(user_configuration.get("goal") or "Maintain").strip() or "Maintain"
        weekly_budget = self._normalized_int(user_configuration.get("weekly_budget")) or 0
        age = self._normalized_int(user_configuration.get("age"))
        weight_kg = self._normalized_float(user_configuration.get("weight_kg"))

        anchors = self._anchors_for_goal(goal)
        clamped_budget = min(
            max(float(weekly_budget), anchors[0].weekly_budget),
            anchors[-1].weekly_budget,
        )
        interpolated = self._interpolate(budget=clamped_budget, anchors=anchors)
        personalized = self._personalize(
            base=interpolated,
            goal=goal,
            age=age,
            weight_kg=weight_kg,
        )
        return GoalTargetSnapshot(
            weekly_budget=int(clamped_budget),
            daily_calories=personalized.daily_calories,
            protein_g=personalized.protein_g,
            carbs_g=personalized.carbs_g,
            fat_g=personalized.fat_g,
        )

    def _anchors_for_goal(self, goal: str) -> list[_Anchor]:
        if goal == "Weight Gain":
            return [
                _Anchor(25, 1700, 70, 180, 35),
                _Anchor(40, 1815, 95, 220, 45),
                _Anchor(60, 2265, 120, 320, 55),
                _Anchor(85, 2780, 145, 390, 70),
                _Anchor(110, 3100, 165, 440, 80),
            ]
        if goal == "Muscle Building":
            return [
                _Anchor(30, 1640, 90, 160, 40),
                _Anchor(45, 1722, 115, 180, 48),
                _Anchor(70, 2122, 145, 250, 58),
                _Anchor(95, 2502, 175, 300, 68),
                _Anchor(120, 2807, 195, 335, 75),
            ]
        if goal == "Weight Loss":
            return [
                _Anchor(20, 1075, 80, 110, 35),
                _Anchor(35, 1310, 95, 145, 40),
                _Anchor(50, 1592, 115, 180, 48),
                _Anchor(70, 1915, 130, 220, 55),
                _Anchor(90, 2110, 145, 250, 60),
            ]
        return [
            _Anchor(20, 1258, 75, 150, 38),
            _Anchor(35, 1506, 90, 190, 44),
            _Anchor(55, 1808, 105, 230, 52),
            _Anchor(75, 2100, 120, 270, 60),
            _Anchor(95, 2312, 135, 300, 68),
        ]

    def _interpolate(
        self,
        *,
        budget: float,
        anchors: list[_Anchor],
    ) -> _InterpolatedValues:
        first = anchors[0]
        last = anchors[-1]
        if budget <= first.weekly_budget:
            return self._rounded_values(first)
        if budget >= last.weekly_budget:
            return self._rounded_values(last)

        for left, right in zip(anchors, anchors[1:]):
            if budget < left.weekly_budget or budget > right.weekly_budget:
                continue
            ratio = (budget - left.weekly_budget) / (right.weekly_budget - left.weekly_budget)
            return _InterpolatedValues(
                daily_calories=int(round(left.calories + (right.calories - left.calories) * ratio)),
                protein_g=int(round(left.protein_g + (right.protein_g - left.protein_g) * ratio)),
                carbs_g=int(round(left.carbs_g + (right.carbs_g - left.carbs_g) * ratio)),
                fat_g=int(round(left.fat_g + (right.fat_g - left.fat_g) * ratio)),
            )
        return self._rounded_values(last)

    def _personalize(
        self,
        *,
        base: _InterpolatedValues,
        goal: str,
        age: int | None,
        weight_kg: float | None,
    ) -> _InterpolatedValues:
        if weight_kg is None or weight_kg <= 0:
            return base

        protein_floor = max(float(base.protein_g), weight_kg * self._protein_multiplier(goal))
        fat_floor = max(float(base.fat_g), weight_kg * self._fat_multiplier(goal))
        calorie_floor = max(float(base.daily_calories), weight_kg * self._calorie_multiplier(goal, age))
        derived_carbs = max(float(base.carbs_g), (calorie_floor - (4 * protein_floor) - (9 * fat_floor)) / 4)
        return _InterpolatedValues(
            daily_calories=int(round(calorie_floor)),
            protein_g=int(round(protein_floor)),
            carbs_g=int(round(max(derived_carbs, 0))),
            fat_g=int(round(fat_floor)),
        )

    @staticmethod
    def _rounded_values(anchor: _Anchor) -> _InterpolatedValues:
        return _InterpolatedValues(
            daily_calories=int(round(anchor.calories)),
            protein_g=int(round(anchor.protein_g)),
            carbs_g=int(round(anchor.carbs_g)),
            fat_g=int(round(anchor.fat_g)),
        )

    @staticmethod
    def _protein_multiplier(goal: str) -> float:
        if goal == "Weight Gain":
            return 1.6
        if goal == "Muscle Building":
            return 1.8
        if goal == "Weight Loss":
            return 1.5
        return 1.2

    @staticmethod
    def _fat_multiplier(goal: str) -> float:
        if goal == "Weight Gain":
            return 0.7
        if goal == "Muscle Building":
            return 0.6
        if goal == "Weight Loss":
            return 0.5
        return 0.6

    @staticmethod
    def _calorie_multiplier(goal: str, age: int | None) -> float:
        if age is not None and age >= 50:
            age_adjustment = -1.5
        elif age is not None and age >= 35:
            age_adjustment = -0.5
        else:
            age_adjustment = 0.0

        if goal == "Weight Gain":
            return 32 + age_adjustment
        if goal == "Muscle Building":
            return 30 + age_adjustment
        if goal == "Weight Loss":
            return 24 + age_adjustment
        return 28 + age_adjustment

    @staticmethod
    def _normalized_int(value: Any) -> int | None:
        if value in (None, ""):
            return None
        try:
            return int(value)
        except (TypeError, ValueError):
            return None

    @staticmethod
    def _normalized_float(value: Any) -> float | None:
        if value in (None, ""):
            return None
        try:
            return float(value)
        except (TypeError, ValueError):
            return None
