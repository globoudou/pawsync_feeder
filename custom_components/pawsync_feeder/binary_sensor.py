"""Binary sensors for Pawsync Feeder."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

from homeassistant.components.binary_sensor import (
    BinarySensorDeviceClass,
    BinarySensorEntity,
    BinarySensorEntityDescription,
)
from homeassistant.const import EntityCategory
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback

from .api import PawsyncDevice
from .coordinator import PawsyncConfigEntry, PawsyncCoordinator
from .entity import PawsyncEntity, as_bool, as_int, is_online, setup_device_entities

PARALLEL_UPDATES = 0


def _bowl_problem(d: PawsyncDevice) -> bool | None:
    state = d.prop.get("bowlConnected")
    if state is None:
        return None
    return str(state).lower() != "normal"


def _flag(d: PawsyncDevice, key: str) -> bool | None:
    return as_bool(d.prop.get(key))


def _desiccant_expired(d: PawsyncDevice) -> bool | None:
    days = d.prop.get("desiccantRemainTime")
    days = as_int(days)
    return None if days is None else days <= 0


@dataclass(frozen=True, kw_only=True)
class PawsyncBinaryDescription(BinarySensorEntityDescription):
    value_fn: Callable[[PawsyncDevice], bool | None]
    required_key: str | None = None
    available_offline: bool = False


BINARY_SENSORS: tuple[PawsyncBinaryDescription, ...] = (
    PawsyncBinaryDescription(
        key="online",
        device_class=BinarySensorDeviceClass.CONNECTIVITY,
        entity_category=EntityCategory.DIAGNOSTIC,
        value_fn=is_online,
        available_offline=True,
    ),
    PawsyncBinaryDescription(
        key="bowl",
        translation_key="bowl",
        device_class=BinarySensorDeviceClass.PROBLEM,
        value_fn=_bowl_problem,
    ),
    PawsyncBinaryDescription(
        key="power_adapter",
        translation_key="power_adapter",
        device_class=BinarySensorDeviceClass.PLUG,
        entity_category=EntityCategory.DIAGNOSTIC,
        value_fn=lambda d: _flag(d, "powerAdapter"),
        required_key="powerAdapter",
    ),
    PawsyncBinaryDescription(
        key="desiccant",
        translation_key="desiccant",
        device_class=BinarySensorDeviceClass.PROBLEM,
        value_fn=_desiccant_expired,
    ),
)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: PawsyncConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    def factory(coordinator: PawsyncCoordinator, device: PawsyncDevice) -> list[Any]:
        return [
            PawsyncBinarySensor(coordinator, device, desc)
            for desc in BINARY_SENSORS
            if desc.required_key is None or desc.required_key in device.prop
        ]

    setup_device_entities(entry.runtime_data, entry, async_add_entities, factory)


class PawsyncBinarySensor(PawsyncEntity, BinarySensorEntity):
    entity_description: PawsyncBinaryDescription

    def __init__(
        self,
        coordinator: PawsyncCoordinator,
        device: PawsyncDevice,
        description: PawsyncBinaryDescription,
    ) -> None:
        super().__init__(coordinator, device, description.key)
        self.entity_description = description
        self._available_when_offline = description.available_offline

    @property
    def is_on(self) -> bool | None:
        return self.entity_description.value_fn(self.device)
