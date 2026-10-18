"""Buttons for Pawsync Feeder."""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from typing import Any

from homeassistant.components.button import ButtonEntity, ButtonEntityDescription
from homeassistant.const import EntityCategory
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback

from .api import PawsyncDevice
from .coordinator import PawsyncConfigEntry, PawsyncCoordinator
from .entity import PawsyncEntity, setup_device_entities

PARALLEL_UPDATES = 1


@dataclass(frozen=True, kw_only=True)
class PawsyncButtonDescription(ButtonEntityDescription):
    press_fn: Callable[[PawsyncCoordinator, PawsyncDevice], Awaitable[Any]]
    optimistic: dict[str, Any] | None = None
    refresh: bool = False


BUTTONS: tuple[PawsyncButtonDescription, ...] = (
    PawsyncButtonDescription(
        key="feed",
        translation_key="feed",
        press_fn=lambda c, d: c.client.feed(d, c.portion_for(d.device_id)),
        refresh=True,
    ),
    PawsyncButtonDescription(
        key="meal_call",
        translation_key="meal_call",
        press_fn=lambda c, d: c.client.play_meal_call(d),
    ),
    PawsyncButtonDescription(
        key="tare_scale",
        translation_key="tare_scale",
        entity_category=EntityCategory.CONFIG,
        press_fn=lambda c, d: c.client.tare_scale(d),
        optimistic={"bowlWeight": 0},
    ),
    PawsyncButtonDescription(
        key="reset_desiccant",
        translation_key="reset_desiccant",
        entity_category=EntityCategory.CONFIG,
        press_fn=lambda c, d: c.client.reset_desiccant(d),
        optimistic={"desiccantRemainTime": 30},
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
        lambda c, d: [PawsyncButton(c, d, desc) for desc in BUTTONS],
    )


class PawsyncButton(PawsyncEntity, ButtonEntity):
    entity_description: PawsyncButtonDescription

    def __init__(
        self,
        coordinator: PawsyncCoordinator,
        device: PawsyncDevice,
        description: PawsyncButtonDescription,
    ) -> None:
        super().__init__(coordinator, device, description.key)
        self.entity_description = description

    async def async_press(self) -> None:
        desc = self.entity_description
        await self._command(desc.press_fn(self.coordinator, self.device), desc.optimistic)
        if desc.refresh:
            await self.coordinator.async_request_refresh()
