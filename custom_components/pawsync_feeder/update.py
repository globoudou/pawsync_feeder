"""Firmware update entity (read-only: install from the Pawsync app)."""

from __future__ import annotations

from typing import Any

from homeassistant.components.update import UpdateDeviceClass, UpdateEntity
from homeassistant.const import EntityCategory
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback

from .api import PawsyncDevice
from .coordinator import PawsyncConfigEntry, PawsyncCoordinator
from .entity import PawsyncEntity, firmware_version, setup_device_entities

PARALLEL_UPDATES = 0


async def async_setup_entry(
    hass: HomeAssistant,
    entry: PawsyncConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    setup_device_entities(
        entry.runtime_data, entry, async_add_entities, lambda c, d: [PawsyncFirmware(c, d)]
    )


class PawsyncFirmware(PawsyncEntity, UpdateEntity):
    _attr_device_class = UpdateDeviceClass.FIRMWARE
    _attr_entity_category = EntityCategory.DIAGNOSTIC
    _attr_translation_key = "firmware"
    _available_when_offline = True

    def __init__(self, coordinator: PawsyncCoordinator, device: PawsyncDevice) -> None:
        super().__init__(coordinator, device, "firmware")

    def _main_info(self) -> dict[str, Any] | None:
        infos = self.coordinator.data.firmware.get(self._device_id) or []
        return next(
            (i for i in infos if i.get("pluginName") in ("mainFw", None) or i.get("isMainFw")),
            infos[0] if infos else None,
        )

    @property
    def installed_version(self) -> str | None:
        info = self._main_info()
        return firmware_version(self.device) or (info or {}).get("currentVersion")

    @property
    def latest_version(self) -> str | None:
        infos = self.coordinator.data.firmware.get(self._device_id) or []
        pending = [i for i in infos if (i.get("upgradeLevel") or 0) > 0]
        if not pending:
            return self.installed_version
        main = next((i for i in pending if i.get("pluginName") == "mainFw"), pending[0])
        return main.get("latestVersion") or self.installed_version

    @property
    def release_summary(self) -> str | None:
        infos = self.coordinator.data.firmware.get(self._device_id) or []
        notes = [
            f"{i.get('pluginName')}: {i.get('latestVersion')} — {i.get('releaseNotes') or ''}".strip()
            for i in infos
            if (i.get("upgradeLevel") or 0) > 0
        ]
        return "\n".join(notes)[:255] or None
