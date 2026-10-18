"""Base entity for Pawsync Feeder."""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from typing import Any

from homeassistant.core import callback
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .api import PawsyncAuthError, PawsyncDevice, PawsyncError
from .const import DOMAIN, MANUFACTURER
from .coordinator import PawsyncCoordinator


def firmware_version(device: PawsyncDevice, main: bool = True) -> str | None:
    for fw in device.prop.get("firmwareInfos") or []:
        if main and fw.get("isMainFw"):
            return fw.get("version")
        if not main and fw.get("pluginName") == "mcuFw":
            return fw.get("version")
    return None


def is_online(device: PawsyncDevice) -> bool | None:
    status = device.prop.get("connectionStatus")
    if status is None:
        return None
    return str(status).lower() == "online"


class PawsyncEntity(CoordinatorEntity[PawsyncCoordinator]):
    """An entity bound to one feeder."""

    _attr_has_entity_name = True
    # Entities that keep working (or must stay visible) while the feeder is offline.
    _available_when_offline = False

    def __init__(self, coordinator: PawsyncCoordinator, device: PawsyncDevice, key: str) -> None:
        super().__init__(coordinator)
        self._device_id = device.device_id
        self._attr_unique_id = f"{device.device_id}_{key}"
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, device.device_id)},
            name=device.name,
            manufacturer=MANUFACTURER,
            model=device.model or None,
            model_id=device.config_model or None,
            sw_version=firmware_version(device),
        )

    @property
    def device(self) -> PawsyncDevice:
        return self.coordinator.data.devices[self._device_id]

    @property
    def available(self) -> bool:
        if not super().available or self._device_id not in self.coordinator.data.devices:
            return False
        if self._available_when_offline:
            return True
        return is_online(self.device) is not False

    async def _command(
        self, call: Awaitable[Any], optimistic: dict[str, Any] | None = None
    ) -> Any:
        """Run a cloud command, map errors, apply optimistic state."""
        try:
            result = await call
        except PawsyncAuthError as err:
            self.coordinator.config_entry.async_start_reauth(self.hass)
            raise HomeAssistantError(
                translation_domain=DOMAIN, translation_key="auth_failed"
            ) from err
        except PawsyncError as err:
            raise HomeAssistantError(
                translation_domain=DOMAIN,
                translation_key="command_failed",
                translation_placeholders={"error": str(err)},
            ) from err
        if optimistic:
            # The cloud status lags behind the device: reflect the change at once.
            _deep_update(self.device.prop, optimistic)
            self.coordinator.async_update_listeners()
        return result


def setup_device_entities(
    coordinator: PawsyncCoordinator,
    entry: Any,
    async_add_entities: Callable[[list[Any]], None],
    factory: Callable[[PawsyncCoordinator, PawsyncDevice], list[Any]],
) -> None:
    """Add entities for current feeders, and for feeders added to the account later."""
    known: set[str] = set()

    @callback
    def _add_new() -> None:
        new = [d for d_id, d in coordinator.data.devices.items() if d_id not in known]
        if not new:
            return
        entities: list[Any] = []
        for device in new:
            known.add(device.device_id)
            entities.extend(factory(coordinator, device))
        if entities:
            async_add_entities(entities)

    _add_new()
    entry.async_on_unload(coordinator.async_add_listener(_add_new))


def _deep_update(target: dict[str, Any], src: dict[str, Any]) -> None:
    for key, value in src.items():
        if isinstance(value, dict) and isinstance(target.get(key), dict):
            _deep_update(target[key], value)
        else:
            target[key] = value
