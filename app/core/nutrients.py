from __future__ import annotations

from dataclasses import dataclass
from typing import Iterable

from app.models.grocery import NutritionSpec, NutrientType, NutrientUnit


@dataclass(frozen=True, slots=True)
class NutrientMetadata:
    id: NutrientType
    slug: str
    display_name: str
    default_unit: NutrientUnit


NUTRIENT_METADATA: tuple[NutrientMetadata, ...] = (
    NutrientMetadata(NutrientType.PROTEIN, "protein", "Protein", NutrientUnit.GRAM),
    NutrientMetadata(NutrientType.CARBOHYDRATES, "carbohydrates", "Carbohydrates", NutrientUnit.GRAM),
    NutrientMetadata(NutrientType.FAT, "fat", "Fat", NutrientUnit.GRAM),
    NutrientMetadata(NutrientType.FIBER, "fiber", "Fiber", NutrientUnit.GRAM),
    NutrientMetadata(NutrientType.SUGAR, "sugar", "Sugar", NutrientUnit.GRAM),
    NutrientMetadata(NutrientType.SODIUM, "sodium", "Sodium", NutrientUnit.MILLIGRAM),
    NutrientMetadata(NutrientType.CALORIES, "calories", "Calories", NutrientUnit.KILOCALORIE),
    NutrientMetadata(NutrientType.SATURATED_FAT, "saturated_fat", "Saturated Fat", NutrientUnit.GRAM),
    NutrientMetadata(NutrientType.CALCIUM, "calcium", "Calcium", NutrientUnit.MILLIGRAM),
    NutrientMetadata(NutrientType.IRON, "iron", "Iron", NutrientUnit.MILLIGRAM),
    NutrientMetadata(NutrientType.POTASSIUM, "potassium", "Potassium", NutrientUnit.MILLIGRAM),
    NutrientMetadata(NutrientType.VITAMIN_C, "vitamin_c", "Vitamin C", NutrientUnit.MILLIGRAM),
    NutrientMetadata(NutrientType.VITAMIN_A, "vitamin_a", "Vitamin A", NutrientUnit.MILLIGRAM),
)


def nutrient_metadata_payload() -> list[dict[str, int | str]]:
    return [
        {
            "id": int(item.id),
            "slug": item.slug,
            "display_name": item.display_name,
            "default_unit": item.default_unit.value,
        }
        for item in NUTRIENT_METADATA
    ]


def derive_macro_summary(
    nutritional_specs: Iterable[NutritionSpec | dict[str, object]],
) -> dict[str, int | float]:
    calories = 0.0
    protein_g = 0.0
    carbs_g = 0.0
    fat_g = 0.0

    for spec in nutritional_specs:
        if isinstance(spec, NutritionSpec):
            nutrient_id = spec.nutrient_id
            amount = float(spec.amount)
        else:
            raw_nutrient_id = spec.get("nutrient_id")
            if raw_nutrient_id is None:
                continue
            nutrient_id = NutrientType(int(raw_nutrient_id))
            amount = float(spec.get("amount", 0) or 0)

        if nutrient_id == NutrientType.CALORIES:
            calories += amount
        elif nutrient_id == NutrientType.PROTEIN:
            protein_g += amount
        elif nutrient_id == NutrientType.CARBOHYDRATES:
            carbs_g += amount
        elif nutrient_id == NutrientType.FAT:
            fat_g += amount

    return {
        "calories": int(round(calories)),
        "protein_g": round(protein_g, 1),
        "carbs_g": round(carbs_g, 1),
        "fat_g": round(fat_g, 1),
    }
