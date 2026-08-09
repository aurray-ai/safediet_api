from __future__ import annotations

from dataclasses import dataclass

from app.data.measurement_seed import (
    DEFAULT_INGREDIENT_CONVERSION_PROFILE_SEEDS,
    DEFAULT_MEASUREMENT_UNIT_SEEDS,
)
from app.models.measurement import (
    IngredientConversionProfile,
    MeasurementType,
    MeasurementUnitDefinition,
    RoundingRule,
    ScalingBehavior,
)
from app.repositories.measurement_repository import MeasurementRepository


class MeasurementValidationError(Exception):
    pass


@dataclass(frozen=True, slots=True)
class ResolvedIngredientMeasurement:
    display_quantity: float
    display_unit: str
    measurement_type: MeasurementType
    unit_code: str
    canonical_quantity: float
    canonical_unit: str
    conversion_profile_id: str | None
    scaling_behavior: ScalingBehavior
    rounding_rule: RoundingRule | None


class MeasurementService:
    _seed_units_by_code = {
        str(seed["code"]): seed
        for seed in DEFAULT_MEASUREMENT_UNIT_SEEDS
    }
    _seed_aliases = {
        str(alias).strip().lower(): str(seed["code"])
        for seed in DEFAULT_MEASUREMENT_UNIT_SEEDS
        for alias in list(seed.get("aliases", []))
    }
    _seed_profiles_by_id = {
        str(seed["id"]): seed
        for seed in DEFAULT_INGREDIENT_CONVERSION_PROFILE_SEEDS
    }

    def __init__(self, measurement_repository: MeasurementRepository) -> None:
        self._measurement_repository = measurement_repository

    def list_units(self) -> list[MeasurementUnitDefinition]:
        return self._measurement_repository.list_units()

    def list_conversion_profiles(self) -> list[IngredientConversionProfile]:
        return self._measurement_repository.list_conversion_profiles()

    @classmethod
    def normalize_unit_code(cls, value: str | None) -> str | None:
        if value is None:
            return None
        cleaned = value.strip().lower()
        if not cleaned:
            return None
        return cls._seed_aliases.get(cleaned, cleaned)

    @classmethod
    def default_unit_seed(cls, unit_code: str) -> dict[str, object] | None:
        return cls._seed_units_by_code.get(unit_code)

    @classmethod
    def default_profile_seed(cls, profile_id: str) -> dict[str, object] | None:
        return cls._seed_profiles_by_id.get(profile_id)

    def resolve_ingredient_measurement(
        self,
        *,
        quantity: float,
        unit: str,
        unit_code: str | None,
        measurement_type: str | None,
        canonical_quantity: float | None,
        canonical_unit: str | None,
        conversion_profile_id: str | None,
        scaling_behavior: str | None,
        rounding_rule: str | None,
    ) -> ResolvedIngredientMeasurement:
        resolved_unit_code = self.normalize_unit_code(unit_code or unit)
        if not resolved_unit_code:
            raise MeasurementValidationError("Each ingredient must include a supported measurement unit.")

        unit_definition = self._measurement_repository.get_unit_by_code(resolved_unit_code)
        if unit_definition is None:
            seed = self.default_unit_seed(resolved_unit_code)
            if seed is None:
                raise MeasurementValidationError(f"Unsupported measurement unit '{resolved_unit_code}'.")
            unit_definition = MeasurementUnitDefinition(
                code=str(seed["code"]),
                display_name=str(seed["display_name"]),
                measurement_type=MeasurementType(str(seed["measurement_type"])),
                canonical_unit=str(seed["canonical_unit"]),
                multiplier_to_canonical=float(seed["multiplier_to_canonical"]),
                is_fractional_allowed=bool(seed["is_fractional_allowed"]),
                default_rounding_rule=RoundingRule(str(seed["default_rounding_rule"])),
                sort_order=int(seed["sort_order"]),
                aliases=[str(item) for item in list(seed["aliases"])],
                is_active=bool(seed["is_active"]),
                created_at=None,  # type: ignore[arg-type]
                updated_at=None,  # type: ignore[arg-type]
            )

        profile = None
        if conversion_profile_id:
            profile = self._measurement_repository.get_conversion_profile(conversion_profile_id)
            if profile is None:
                seed = self.default_profile_seed(conversion_profile_id)
                if seed is None:
                    raise MeasurementValidationError("Selected ingredient conversion profile was not found.")
                profile = IngredientConversionProfile(
                    id=str(seed["id"]),
                    name=str(seed["name"]),
                    ingredient_name=str(seed["ingredient_name"]),
                    linked_product_ids=[str(item) for item in list(seed["linked_product_ids"])],
                    unit_code=str(seed["unit_code"]),
                    canonical_quantity=float(seed["canonical_quantity"]),
                    canonical_unit=str(seed["canonical_unit"]),
                    notes=str(seed["notes"]),
                    is_active=bool(seed["is_active"]),
                    created_at=None,  # type: ignore[arg-type]
                    updated_at=None,  # type: ignore[arg-type]
                )
            if profile.unit_code != resolved_unit_code:
                raise MeasurementValidationError("Conversion profile unit does not match the selected measurement unit.")

        resolved_measurement_type = (
            MeasurementType(str(measurement_type))
            if measurement_type
            else unit_definition.measurement_type
        )
        resolved_scaling_behavior = (
            ScalingBehavior(str(scaling_behavior))
            if scaling_behavior
            else (ScalingBehavior.DISCRETE if not unit_definition.is_fractional_allowed else ScalingBehavior.LINEAR)
        )
        resolved_rounding_rule = (
            RoundingRule(str(rounding_rule))
            if rounding_rule
            else unit_definition.default_rounding_rule
        )

        if profile is not None:
            resolved_canonical_unit = profile.canonical_unit
            resolved_canonical_quantity = quantity * profile.canonical_quantity
        else:
            resolved_canonical_unit = canonical_unit or unit_definition.canonical_unit
            resolved_canonical_quantity = (
                float(canonical_quantity)
                if canonical_quantity is not None and canonical_unit
                else quantity * unit_definition.multiplier_to_canonical
            )

        return ResolvedIngredientMeasurement(
            display_quantity=quantity,
            display_unit=unit.strip() or unit_definition.code,
            measurement_type=resolved_measurement_type,
            unit_code=unit_definition.code,
            canonical_quantity=float(resolved_canonical_quantity),
            canonical_unit=str(resolved_canonical_unit),
            conversion_profile_id=profile.id if profile is not None else None,
            scaling_behavior=resolved_scaling_behavior,
            rounding_rule=resolved_rounding_rule,
        )
