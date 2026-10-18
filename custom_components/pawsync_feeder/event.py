"""Feeding events: one HA event per new entry in the feeder's activity log."""

from __future__ import annotations

from homeassistant.components.event import EventEntity
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback

from .api import PawsyncDevice
from .const import LOG_EATEN, LOG_MANUAL, LOG_PLANNED
from .coordinator import PawsyncConfigEntry, PawsyncCoordinator
from .entity import PawsyncEntity, setup_device_entities

PARALLEL_UPDATES = 0

EVENT_TYPES = {
    LOG_PLANNED: "scheduled_meal",
    LOG_MANUAL: "extra_meal",
    LOG_EATEN: "eaten",
}


async def async_setup_entry(
    hass: HomeAssistant,
    entry: PawsyncConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    setup_device_entities(
        entry.runtime_data, entry, async_add_entities, lambda c, d: [PawsyncFeedingEvent(c, d)]
    )


class PawsyncFeedingEvent(PawsyncEntity, EventEntity):
    _attr_translation_key = "feeding"
    _attr_event_types = list(EVENT_TYPES.values())
    _available_when_offline = True

    def __init__(self, coordinator: PawsyncCoordinator, device: PawsyncDevice) -> None:
        super().__init__(coordinator, device, "feeding")
        # Only entries newer than what exists at startup become events.
        self._last_ts = self._newest_ts()

    def _newest_ts(self) -> int:
        logs = self.coordinator.data.logs.get(self._device_id) or []
        return max((int(e.get("timestamp") or 0) for e in logs), default=0)

    @callback
    def _handle_coordinator_update(self) -> None:
        logs = self.coordinator.data.logs.get(self._device_id) or []
        new = sorted(
            (e for e in logs if int(e.get("timestamp") or 0) > self._last_ts),
            key=lambda e: int(e.get("timestamp") or 0),
        )
        for entry in new:
            event_type = EVENT_TYPES.get(entry.get("logType"))
            if event_type is None:
                continue
            attrs = {"amount": entry.get("value"), "timestamp": entry.get("timestamp")}
            if entry.get("durationInS"):
                attrs["duration"] = entry["durationInS"]
            self._trigger_event(event_type, attrs)
            self.async_write_ha_state()
        if new:
            self._last_ts = int(new[-1].get("timestamp") or self._last_ts)
        super()._handle_coordinator_update()
