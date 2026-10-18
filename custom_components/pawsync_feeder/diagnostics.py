"""Diagnostics (credentials and personal data redacted)."""

from __future__ import annotations

from dataclasses import asdict
from typing import Any

from homeassistant.components.diagnostics import async_redact_data
from homeassistant.const import CONF_EMAIL, CONF_PASSWORD
from homeassistant.core import HomeAssistant

from .coordinator import PawsyncConfigEntry

TO_REDACT = {
    CONF_EMAIL,
    CONF_PASSWORD,
    "token",
    "accountId",
    "accountID",
    "wifiName",
    "wifiMac",
    "mac",
    "macID",
    "ip",
    "petAvatarIcon",
    "deviceImg",
    "image",
    "image_url",
    "uuid",
}


async def async_get_config_entry_diagnostics(
    hass: HomeAssistant, entry: PawsyncConfigEntry
) -> dict[str, Any]:
    data = entry.runtime_data.data
    return async_redact_data(
        {
            "entry": {"data": dict(entry.data), "options": dict(entry.options)},
            "devices": {k: asdict(v) for k, v in data.devices.items()},
            "pets": data.pets,
            "logs": data.logs,
            "firmware": data.firmware,
        },
        TO_REDACT,
    )
