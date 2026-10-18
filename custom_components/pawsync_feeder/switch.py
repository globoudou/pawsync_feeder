"""Switches for Pawsync Feeder."""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from typing import Any

from homeassistant.components.switch import SwitchEntity, SwitchEntityDescription
from homeassistant.const import EntityCategory
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback

from .api import PawsyncClient, PawsyncDevice
from .const import DEFAULT_SLEEP_END, DEFAULT_SLEEP_START
from .coordinator import PawsyncConfigEntry, PawsyncCoordinator
from .entity import PawsyncEntity, as_bool, setup_device_entities

PARALLEL_UPDATES = 1


def sleep_mode(d: PawsyncDevice) -> dict[str, Any]:
    sm = d.prop.get("sleepMode")
    return sm if isinstance(sm, dict) else {}


def _set_sleep(client: PawsyncClient, d: PawsyncDevice, on: bool) -> Awaitable[None]:
    sm = sleep_mode(d)
    return client.set_sleep_mode(
        d,
        on,
        sm.get("startClkSec", DEFAULT_SLEEP_START),
        sm.get("endClkSec", DEFAULT_SLEEP_END),
    )


@dataclass(frozen=True, kw_only=True)
class PawsyncSwitchDescription(SwitchEntityDescription):
    value_fn: Callable[[PawsyncDevice], bool | None]
    set_fn: Callable[[PawsyncClient, PawsyncDevice, bool], Awaitable[None]]
    optimistic_fn: Callable[[bool], dict[str, Any]]


def _int_flag(d: PawsyncDevice, key: str) -> bool | None:
    return as_bool(d.prop.get(key))


SWITCHES: tuple[PawsyncSwitchDescription, ...] = (
    PawsyncSwitchDescription(
        key="smart_feeding",
        translation_key="smart_feeding",
        entity_category=EntityCategory.CONFIG,
        value_fn=lambda d: _int_flag(d, "intelligentFeedingSwitch"),
        set_fn=lambda c, d, on: c.set_smart_feeding(d, on),
        optimistic_fn=lambda on: {"intelligentFeedingSwitch": int(on)},
    ),
    PawsyncSwitchDescription(
        key="slow_feeding",
        translation_key="slow_feeding",
        entity_category=EntityCategory.CONFIG,
        value_fn=lambda d: _int_flag(d, "slowFeedSwitch"),
        set_fn=lambda c, d, on: c.set_slow_feeding(d, on),
        optimistic_fn=lambda on: {"slowFeedSwitch": int(on)},
    ),
    PawsyncSwitchDescription(
        key="precision_mode",
        translation_key="precision_mode",
        entity_category=EntityCategory.CONFIG,
        value_fn=lambda d: _int_flag(d, "accurateFeeding"),
        set_fn=lambda c, d, on: c.set_precision_mode(d, on),
        optimistic_fn=lambda on: {"accurateFeeding": int(on)},
    ),
    PawsyncSwitchDescription(
        key="sleep_mode",
        translation_key="sleep_mode",
        value_fn=lambda d: as_bool(sleep_mode(d).get("enable")),
        set_fn=_set_sleep,
        optimistic_fn=lambda on: {"sleepMode": {"enable": int(on)}},
    ),
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
        lambda c, d: [PawsyncSwitch(c, d, desc) for desc in SWITCHES],
    )


class PawsyncSwitch(PawsyncEntity, SwitchEntity):
    entity_description: PawsyncSwitchDescription

    def __init__(
        self,
        coordinator: PawsyncCoordinator,
        device: PawsyncDevice,
        description: PawsyncSwitchDescription,
    ) -> None:
        super().__init__(coordinator, device, description.key)
        self.entity_description = description

    @property
    def is_on(self) -> bool | None:
        return self.entity_description.value_fn(self.device)

    async def _set(self, on: bool) -> None:
        desc = self.entity_description
        await self._command(
            desc.set_fn(self.coordinator.client, self.device, on), desc.optimistic_fn(on)
        )

    async def async_turn_on(self, **kwargs: Any) -> None:
        await self._set(True)

    async def async_turn_off(self, **kwargs: Any) -> None:
        await self._set(False)
