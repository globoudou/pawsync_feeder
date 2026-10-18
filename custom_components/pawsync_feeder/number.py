"""Number entities for Pawsync Feeder."""

from __future__ import annotations

from homeassistant.components.number import (
    NumberDeviceClass,
    NumberEntity,
    NumberEntityDescription,
    NumberMode,
    RestoreNumber,
)
from homeassistant.const import EntityCategory, UnitOfMass, UnitOfVolume
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback

from .api import PawsyncDevice
from .const import (
    DEFAULT_PORTION_G,
    HOPPER_CAPACITY_ML,
    HOPPER_MIN_ML,
    MAX_PORTION_G,
    MIN_PORTION_G,
)
from .coordinator import PawsyncConfigEntry, PawsyncCoordinator
from .entity import PawsyncEntity, setup_device_entities

PARALLEL_UPDATES = 1

PORTION = NumberEntityDescription(
    key="portion",
    translation_key="portion",
    entity_category=EntityCategory.CONFIG,
    native_min_value=MIN_PORTION_G,
    native_max_value=MAX_PORTION_G,
    native_step=1,
    native_unit_of_measurement=UnitOfMass.GRAMS,
    device_class=NumberDeviceClass.WEIGHT,
    mode=NumberMode.BOX,
)

HOPPER = NumberEntityDescription(
    key="hopper_volume",
    translation_key="hopper_volume",
    entity_category=EntityCategory.CONFIG,
    native_min_value=HOPPER_MIN_ML,
    native_max_value=HOPPER_CAPACITY_ML,
    native_step=100,
    native_unit_of_measurement=UnitOfVolume.MILLILITERS,
    device_class=NumberDeviceClass.VOLUME,
    mode=NumberMode.SLIDER,
)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: PawsyncConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    setup_device_entities(
        entry.runtime_data,
        entry,
        async_add_entities,
        lambda c, d: [PawsyncPortion(c, d, PORTION), PawsyncHopperVolume(c, d, HOPPER)],
    )


class PawsyncPortion(PawsyncEntity, RestoreNumber):
    """Size of the "extra meal" (button and service default). Stored locally."""

    _available_when_offline = True

    def __init__(
        self,
        coordinator: PawsyncCoordinator,
        device: PawsyncDevice,
        description: NumberEntityDescription,
    ) -> None:
        super().__init__(coordinator, device, description.key)
        self.entity_description = description

    async def async_added_to_hass(self) -> None:
        await super().async_added_to_hass()
        last = await self.async_get_last_number_data()
        value = DEFAULT_PORTION_G
        if last is not None and last.native_value is not None:
            value = int(last.native_value)
        self.coordinator.portions[self._device_id] = value

    @property
    def native_value(self) -> float:
        return self.coordinator.portion_for(self._device_id)

    async def async_set_native_value(self, value: float) -> None:
        self.coordinator.portions[self._device_id] = int(value)
        self.async_write_ha_state()


class PawsyncHopperVolume(PawsyncEntity, NumberEntity):
    """Declare how much food is in the hopper after a refill (drives the days-left estimate)."""

    def __init__(
        self,
        coordinator: PawsyncCoordinator,
        device: PawsyncDevice,
        description: NumberEntityDescription,
    ) -> None:
        super().__init__(coordinator, device, description.key)
        self.entity_description = description

    @property
    def native_value(self) -> float | None:
        pct = self.device.prop.get("contentInPot")
        if pct is None:
            return None
        return round(float(pct) / 100 * HOPPER_CAPACITY_ML)

    async def async_set_native_value(self, value: float) -> None:
        result = await self._command(
            self.coordinator.client.set_hopper_volume(self.device, value),
            {"contentInPot": round(value / HOPPER_CAPACITY_ML * 100)},
        )
        if isinstance(result, dict) and "daysRemain" in result:
            self.device.prop.setdefault("petFood", {})["contentRemainTime"] = result["daysRemain"]
            self.coordinator.async_update_listeners()
