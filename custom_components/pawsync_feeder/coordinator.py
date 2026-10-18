"""Data coordinator for Pawsync Feeder."""

from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import Any

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import ConfigEntryAuthFailed
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed
from homeassistant.util import dt as dt_util

from .api import (
    PawsyncAuthError,
    PawsyncClient,
    PawsyncDevice,
    PawsyncError,
)
from .const import (
    CONF_SCAN_INTERVAL,
    DEFAULT_PORTION_G,
    DEFAULT_SCAN_INTERVAL,
    DOMAIN,
    FIRMWARE_REFRESH_HOURS,
)

_LOGGER = logging.getLogger(__name__)

type PawsyncConfigEntry = ConfigEntry[PawsyncCoordinator]


@dataclass
class PawsyncData:
    """Snapshot of the account."""

    devices: dict[str, PawsyncDevice] = field(default_factory=dict)
    pets: dict[str, dict[str, Any]] = field(default_factory=dict)
    logs: dict[str, list[dict[str, Any]]] = field(default_factory=dict)
    firmware: dict[str, list[dict[str, Any]]] = field(default_factory=dict)

    def pet_for(self, device: PawsyncDevice) -> dict[str, Any] | None:
        if device.pet_id in (None, "", 0):
            return None
        return self.pets.get(str(device.pet_id))


class PawsyncCoordinator(DataUpdateCoordinator[PawsyncData]):
    """Polls the Pawsync cloud for every feeder of the account."""

    config_entry: PawsyncConfigEntry

    def __init__(
        self, hass: HomeAssistant, entry: PawsyncConfigEntry, client: PawsyncClient
    ) -> None:
        super().__init__(
            hass,
            _LOGGER,
            config_entry=entry,
            name=DOMAIN,
            update_interval=timedelta(
                minutes=entry.options.get(CONF_SCAN_INTERVAL, DEFAULT_SCAN_INTERVAL)
            ),
        )
        self.client = client
        self._firmware_checked: datetime | None = None
        self._firmware: dict[str, list[dict[str, Any]]] = {}
        # Per-device extra meal size, driven by the "portion" number entity.
        self.portions: dict[str, int] = {}

    def portion_for(self, device_id: str) -> int:
        return self.portions.get(device_id, DEFAULT_PORTION_G)

    async def _async_update_data(self) -> PawsyncData:
        try:
            return await self._fetch()
        except PawsyncAuthError as err:
            raise ConfigEntryAuthFailed(str(err)) from err
        except PawsyncError as err:
            raise UpdateFailed(str(err)) from err

    async def _fetch(self) -> PawsyncData:
        client = self.client
        devices = await client.get_devices()

        # Live status for every feeder, in parallel. A failing feeder keeps its
        # cached properties instead of failing the whole refresh.
        statuses = await asyncio.gather(
            *(client.get_device_status(d) for d in devices), return_exceptions=True
        )
        for device, status in zip(devices, statuses, strict=True):
            if isinstance(status, PawsyncAuthError):
                raise status
            if isinstance(status, Exception):
                _LOGGER.debug("Live status unavailable for %s: %s", device.device_id, status)
                continue
            device.prop.update(status)

        midnight = dt_util.start_of_local_day()
        start_ts = int(min(midnight.timestamp(), dt_util.utcnow().timestamp() - 86400))
        pets_res, *logs_res = await asyncio.gather(
            client.get_pets(),
            *(client.get_pet_logs(d.device_id, start_ts) for d in devices),
            return_exceptions=True,
        )
        for res in (pets_res, *logs_res):
            if isinstance(res, PawsyncAuthError):
                raise res

        previous = self.data or PawsyncData()
        pets = (
            {str(p.get("petId")): p for p in pets_res}
            if not isinstance(pets_res, Exception)
            else previous.pets
        )
        logs: dict[str, list[dict[str, Any]]] = {}
        for device, res in zip(devices, logs_res, strict=True):
            logs[device.device_id] = (
                res if not isinstance(res, Exception) else previous.logs.get(device.device_id, [])
            )

        now = dt_util.utcnow()
        if devices and (
            self._firmware_checked is None
            or now - self._firmware_checked > timedelta(hours=FIRMWARE_REFRESH_HOURS)
        ):
            try:
                self._firmware = await client.get_firmware([d.device_id for d in devices])
                self._firmware_checked = now
            except PawsyncAuthError:
                raise
            except PawsyncError as err:
                _LOGGER.debug("Firmware check failed: %s", err)

        return PawsyncData(
            devices={d.device_id: d for d in devices},
            pets=pets,
            logs=logs,
            firmware=self._firmware,
        )
