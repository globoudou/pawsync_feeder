"""Sleep schedule (time entities) for Pawsync Feeder."""

from __future__ import annotations

from datetime import time

from homeassistant.components.time import TimeEntity, TimeEntityDescription
from homeassistant.const import EntityCategory
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback

from .api import PawsyncDevice
from .const import DEFAULT_SLEEP_END, DEFAULT_SLEEP_START
from .coordinator import PawsyncConfigEntry, PawsyncCoordinator
from .entity import PawsyncEntity, as_bool, as_int, setup_device_entities
from .switch import sleep_mode

PARALLEL_UPDATES = 1

START = "startClkSec"
END = "endClkSec"

DESCRIPTIONS = (
    TimeEntityDescription(
        key="sleep_start", translation_key="sleep_start", entity_category=EntityCategory.CONFIG
    ),
    TimeEntityDescription(
        key="sleep_end", translation_key="sleep_end", entity_category=EntityCategory.CONFIG
    ),
)


def secs_to_time(secs: int) -> time:
    secs = int(secs) % 86400
    return time(secs // 3600, (secs % 3600) // 60)


def time_to_secs(value: time) -> int:
    return value.hour * 3600 + value.minute * 60


async def async_setup_entry(
    hass: HomeAssistant,
    entry: PawsyncConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    setup_device_entities(
        entry.runtime_data,
        entry,
        async_add_entities,
        lambda c, d: [PawsyncSleepTime(c, d, desc) for desc in DESCRIPTIONS],
    )


class PawsyncSleepTime(PawsyncEntity, TimeEntity):
    def __init__(
        self,
        coordinator: PawsyncCoordinator,
        device: PawsyncDevice,
        description: TimeEntityDescription,
    ) -> None:
        super().__init__(coordinator, device, description.key)
        self.entity_description = description
        self._field = START if description.key == "sleep_start" else END

    @property
    def native_value(self) -> time | None:
        sm = sleep_mode(self.device)
        secs = as_int(sm.get(self._field))
        return None if secs is None else secs_to_time(secs)

    async def async_set_value(self, value: time) -> None:
        sm = sleep_mode(self.device)
        start = sm.get(START, DEFAULT_SLEEP_START)
        end = sm.get(END, DEFAULT_SLEEP_END)
        if self._field == START:
            start = time_to_secs(value)
        else:
            end = time_to_secs(value)
        enabled = bool(as_bool(sm.get("enable", 0)))
        await self._command(
            self.coordinator.client.set_sleep_mode(self.device, enabled, start, end),
            {"sleepMode": {START: start, END: end}},
        )
