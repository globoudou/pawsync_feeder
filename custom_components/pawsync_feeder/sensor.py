"""Sensors for Pawsync Feeder."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Any

from homeassistant.components.sensor import (
    SensorDeviceClass,
    SensorEntity,
    SensorEntityDescription,
    SensorStateClass,
)
from homeassistant.const import (
    PERCENTAGE,
    SIGNAL_STRENGTH_DECIBELS_MILLIWATT,
    EntityCategory,
    UnitOfMass,
    UnitOfTime,
)
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback
from homeassistant.util import dt as dt_util

from .api import PawsyncDevice
from .const import DISPENSE_LOG_TYPES, LOG_EATEN
from .coordinator import PawsyncConfigEntry, PawsyncCoordinator, PawsyncData
from .entity import PawsyncEntity, firmware_version, setup_device_entities

PARALLEL_UPDATES = 0


def _food(d: PawsyncDevice) -> dict[str, Any]:
    return d.prop.get("petFood") or {}


def _schedule(d: PawsyncDevice) -> dict[str, Any]:
    return d.prop.get("scheduleInfo") or {}


def _logs(d: PawsyncDevice, data: PawsyncData) -> list[dict[str, Any]]:
    return data.logs.get(d.device_id, [])


def _last(logs: list[dict[str, Any]], types: tuple[str, ...]) -> dict[str, Any] | None:
    return next((e for e in logs if e.get("logType") in types), None)


def _ts(entry: dict[str, Any] | None) -> datetime | None:
    if not entry or entry.get("timestamp") is None:
        return None
    return dt_util.utc_from_timestamp(int(entry["timestamp"]))


def _sum_today(logs: list[dict[str, Any]], types: tuple[str, ...]) -> float:
    start = dt_util.start_of_local_day().timestamp()
    return sum(
        e.get("value") or 0
        for e in logs
        if e.get("logType") in types and (e.get("timestamp") or 0) >= start
    )


def _next_meal(d: PawsyncDevice) -> datetime | None:
    secs = _schedule(d).get("nextTime")
    if secs is None or secs < 0:
        return None
    when = dt_util.start_of_local_day() + timedelta(seconds=int(secs))
    if when < dt_util.now() - timedelta(minutes=1):
        when += timedelta(days=1)
    return when


def _pet_value(key: str) -> Callable[[PawsyncDevice, PawsyncData], Any]:
    return lambda d, data: (data.pet_for(d) or {}).get(key)


def _hopper_percent(d: PawsyncDevice) -> Any:
    return d.prop.get("contentInPot")


@dataclass(frozen=True, kw_only=True)
class PawsyncSensorDescription(SensorEntityDescription):
    value_fn: Callable[[PawsyncDevice, PawsyncData], Any]
    pet: bool = False
    available_offline: bool = False


GRAMS = {
    "native_unit_of_measurement": UnitOfMass.GRAMS,
    "device_class": SensorDeviceClass.WEIGHT,
    "suggested_display_precision": 0,
}

SENSORS: tuple[PawsyncSensorDescription, ...] = (
    # --- Food ---------------------------------------------------------------
    PawsyncSensorDescription(
        key="bowl_weight",
        translation_key="bowl_weight",
        state_class=SensorStateClass.MEASUREMENT,
        value_fn=lambda d, _: d.prop.get("bowlWeight"),
        **GRAMS,
    ),
    PawsyncSensorDescription(
        key="hopper_level",
        translation_key="hopper_level",
        native_unit_of_measurement=PERCENTAGE,
        state_class=SensorStateClass.MEASUREMENT,
        value_fn=lambda d, _: _hopper_percent(d),
    ),
    PawsyncSensorDescription(
        key="hopper_remaining",
        translation_key="hopper_remaining",
        state_class=SensorStateClass.MEASUREMENT,
        value_fn=lambda d, _: _food(d).get("bucketSurplus"),
        **GRAMS,
    ),
    PawsyncSensorDescription(
        key="food_days_left",
        translation_key="food_days_left",
        native_unit_of_measurement=UnitOfTime.DAYS,
        device_class=SensorDeviceClass.DURATION,
        state_class=SensorStateClass.MEASUREMENT,
        value_fn=lambda d, _: _food(d).get("contentRemainTime"),
    ),
    PawsyncSensorDescription(
        key="desiccant_days_left",
        translation_key="desiccant_days_left",
        native_unit_of_measurement=UnitOfTime.DAYS,
        device_class=SensorDeviceClass.DURATION,
        value_fn=lambda d, _: d.prop.get("desiccantRemainTime"),
    ),
    # --- Schedule -----------------------------------------------------------
    PawsyncSensorDescription(
        key="next_meal",
        translation_key="next_meal",
        device_class=SensorDeviceClass.TIMESTAMP,
        value_fn=lambda d, _: _next_meal(d),
    ),
    PawsyncSensorDescription(
        key="next_meal_amount",
        translation_key="next_meal_amount",
        value_fn=lambda d, _: _schedule(d).get("nextMount"),
        **GRAMS,
    ),
    PawsyncSensorDescription(
        key="planned_daily_total",
        translation_key="planned_daily_total",
        value_fn=lambda d, _: _schedule(d).get("totalMealG"),
        **GRAMS,
    ),
    # --- Activity (from the feeding log) -------------------------------------
    PawsyncSensorDescription(
        key="last_dispensed",
        translation_key="last_dispensed",
        device_class=SensorDeviceClass.TIMESTAMP,
        value_fn=lambda d, data: _ts(_last(_logs(d, data), DISPENSE_LOG_TYPES)),
    ),
    PawsyncSensorDescription(
        key="last_dispensed_amount",
        translation_key="last_dispensed_amount",
        value_fn=lambda d, data: (_last(_logs(d, data), DISPENSE_LOG_TYPES) or {}).get("value")
        if _last(_logs(d, data), DISPENSE_LOG_TYPES)
        else _food(d).get("lastFeedingAmount"),
        **GRAMS,
    ),
    PawsyncSensorDescription(
        key="dispensed_today",
        translation_key="dispensed_today",
        state_class=SensorStateClass.TOTAL_INCREASING,
        value_fn=lambda d, data: _sum_today(_logs(d, data), DISPENSE_LOG_TYPES),
        **GRAMS,
    ),
    PawsyncSensorDescription(
        key="last_eaten",
        translation_key="last_eaten",
        device_class=SensorDeviceClass.TIMESTAMP,
        value_fn=lambda d, data: _ts(_last(_logs(d, data), (LOG_EATEN,))),
    ),
    PawsyncSensorDescription(
        key="last_eaten_amount",
        translation_key="last_eaten_amount",
        value_fn=lambda d, data: (_last(_logs(d, data), (LOG_EATEN,)) or {}).get("value"),
        **GRAMS,
    ),
    PawsyncSensorDescription(
        key="last_meal_duration",
        translation_key="last_meal_duration",
        native_unit_of_measurement=UnitOfTime.SECONDS,
        device_class=SensorDeviceClass.DURATION,
        suggested_unit_of_measurement=UnitOfTime.MINUTES,
        suggested_display_precision=1,
        value_fn=lambda d, data: next(
            (
                e["durationInS"]
                for e in _logs(d, data)
                if e.get("logType") == LOG_EATEN and (e.get("durationInS") or 0) > 0
            ),
            None,
        ),
    ),
    PawsyncSensorDescription(
        key="eaten_today",
        translation_key="eaten_today",
        state_class=SensorStateClass.TOTAL_INCREASING,
        value_fn=lambda d, data: _sum_today(_logs(d, data), (LOG_EATEN,)),
        **GRAMS,
    ),
    # --- Pet profile -------------------------------------------------------------
    PawsyncSensorDescription(
        key="pet_weight",
        translation_key="pet_weight",
        state_class=SensorStateClass.MEASUREMENT,
        native_unit_of_measurement=UnitOfMass.GRAMS,
        device_class=SensorDeviceClass.WEIGHT,
        suggested_unit_of_measurement=UnitOfMass.KILOGRAMS,
        suggested_display_precision=2,
        value_fn=_pet_value("weightInG"),
        pet=True,
    ),
    PawsyncSensorDescription(
        key="pet_intake_today",
        translation_key="pet_intake_today",
        state_class=SensorStateClass.TOTAL_INCREASING,
        value_fn=_pet_value("todayFoodIntakeInG"),
        pet=True,
        **GRAMS,
    ),
    PawsyncSensorDescription(
        key="pet_intake_target",
        translation_key="pet_intake_target",
        value_fn=_pet_value("targetFoodIntakeInG"),
        pet=True,
        **GRAMS,
    ),
    PawsyncSensorDescription(
        key="pet_meals_today",
        translation_key="pet_meals_today",
        state_class=SensorStateClass.TOTAL_INCREASING,
        value_fn=_pet_value("todayFoodIntakeTimes"),
        pet=True,
    ),
    # --- Diagnostics ----------------------------------------------------------
    PawsyncSensorDescription(
        key="alerts",
        translation_key="alerts",
        state_class=SensorStateClass.MEASUREMENT,
        value_fn=lambda d, _: d.prop.get("alertCount"),
    ),
    PawsyncSensorDescription(
        key="battery",
        native_unit_of_measurement=PERCENTAGE,
        device_class=SensorDeviceClass.BATTERY,
        state_class=SensorStateClass.MEASUREMENT,
        entity_category=EntityCategory.DIAGNOSTIC,
        value_fn=lambda d, _: d.prop.get("batteryPercent"),
        available_offline=True,
    ),
    PawsyncSensorDescription(
        key="wifi_signal",
        translation_key="wifi_signal",
        native_unit_of_measurement=SIGNAL_STRENGTH_DECIBELS_MILLIWATT,
        device_class=SensorDeviceClass.SIGNAL_STRENGTH,
        state_class=SensorStateClass.MEASUREMENT,
        entity_category=EntityCategory.DIAGNOSTIC,
        entity_registry_enabled_default=False,
        value_fn=lambda d, _: d.prop.get("wifiRssi"),
    ),
    PawsyncSensorDescription(
        key="mcu_firmware",
        translation_key="mcu_firmware",
        entity_category=EntityCategory.DIAGNOSTIC,
        entity_registry_enabled_default=False,
        value_fn=lambda d, _: firmware_version(d, main=False),
        available_offline=True,
    ),
)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: PawsyncConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    def factory(coordinator: PawsyncCoordinator, device: PawsyncDevice) -> list[Any]:
        has_pet = coordinator.data.pet_for(device) is not None
        return [
            PawsyncSensor(coordinator, device, desc)
            for desc in SENSORS
            if (not desc.pet or has_pet)
            and not (desc.key == "battery" and "batteryPercent" not in device.prop)
        ]

    setup_device_entities(entry.runtime_data, entry, async_add_entities, factory)


class PawsyncSensor(PawsyncEntity, SensorEntity):
    entity_description: PawsyncSensorDescription

    def __init__(
        self,
        coordinator: PawsyncCoordinator,
        device: PawsyncDevice,
        description: PawsyncSensorDescription,
    ) -> None:
        super().__init__(coordinator, device, description.key)
        self.entity_description = description
        self._available_when_offline = description.available_offline
        if description.pet:
            pet = coordinator.data.pet_for(device) or {}
            self._attr_translation_placeholders = {"pet": pet.get("petName") or "Pet"}
            if pet.get("petAvatarIcon"):
                self._attr_entity_picture = pet["petAvatarIcon"]

    @property
    def native_value(self) -> Any:
        return self.entity_description.value_fn(self.device, self.coordinator.data)
