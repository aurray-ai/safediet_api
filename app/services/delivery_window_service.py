from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime, timedelta, timezone
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError


@dataclass(frozen=True, slots=True)
class DeliveryWindowOption:
    window_id: str
    label: str
    starts_at: datetime
    ends_at: datetime
    is_default: bool = False


@dataclass(frozen=True, slots=True)
class DeliveryWindowSpec:
    window_id: str
    label_prefix: str
    start_hour: int
    end_hour: int
    day_offset: int = 0
    is_default: bool = False


class DeliveryWindowService:
    def build_windows(
        self,
        *,
        timezone_name: str,
        specs: list[DeliveryWindowSpec],
    ) -> list[DeliveryWindowOption]:
        try:
            tzinfo = ZoneInfo(timezone_name or "Europe/London")
        except ZoneInfoNotFoundError:
            tzinfo = timezone.utc

        today = datetime.now(timezone.utc).astimezone(tzinfo).date()
        return [
            self._window_for_local_date(
                date_value=today + timedelta(days=spec.day_offset),
                start_hour=spec.start_hour,
                end_hour=spec.end_hour,
                prefix=spec.label_prefix,
                window_id=spec.window_id,
                tzinfo=tzinfo,
                is_default=spec.is_default,
            )
            for spec in specs
        ]

    @staticmethod
    def _window_for_local_date(
        *,
        date_value: date,
        start_hour: int,
        end_hour: int,
        prefix: str,
        window_id: str,
        tzinfo,
        is_default: bool = False,
    ) -> DeliveryWindowOption:
        starts_at = datetime(
            date_value.year,
            date_value.month,
            date_value.day,
            start_hour,
            0,
            tzinfo=tzinfo,
        ).astimezone(timezone.utc)
        ends_at = datetime(
            date_value.year,
            date_value.month,
            date_value.day,
            end_hour,
            0,
            tzinfo=tzinfo,
        ).astimezone(timezone.utc)
        return DeliveryWindowOption(
            window_id=window_id,
            label=f"{prefix}, {DeliveryWindowService._hour_label(start_hour)} - {DeliveryWindowService._hour_label(end_hour)}",
            starts_at=starts_at,
            ends_at=ends_at,
            is_default=is_default,
        )

    @staticmethod
    def _hour_label(hour: int) -> str:
        suffix = "AM" if hour < 12 else "PM"
        normalized_hour = hour % 12 or 12
        return f"{normalized_hour}:00 {suffix}"
