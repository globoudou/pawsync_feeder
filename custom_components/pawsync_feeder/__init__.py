"""Pawsync Feeder integration for Home Assistant."""

from __future__ import annotations

import logging
from pathlib import Path

import voluptuous as vol
from homeassistant.const import (
    ATTR_DEVICE_ID,
    CONF_EMAIL,
    CONF_PASSWORD,
    EVENT_HOMEASSISTANT_STARTED,
)
from homeassistant.core import Event, HomeAssistant, ServiceCall
from homeassistant.exceptions import (
    ConfigEntryAuthFailed,
    ConfigEntryNotReady,
    ServiceValidationError,
)
from homeassistant.helpers import config_validation as cv
from homeassistant.helpers import device_registry as dr
from homeassistant.helpers.aiohttp_client import async_get_clientsession
from homeassistant.helpers.typing import ConfigType
from homeassistant.loader import async_get_integration

from .api import PawsyncAuthError, PawsyncClient, PawsyncError
from .const import (
    ATTR_AMOUNT,
    DOMAIN,
    MAX_PORTION_G,
    MIN_PORTION_G,
    PLATFORMS,
    SERVICE_FEED,
)
from .coordinator import PawsyncConfigEntry, PawsyncCoordinator

_LOGGER = logging.getLogger(__name__)

CONFIG_SCHEMA = cv.config_entry_only_config_schema(DOMAIN)

FEED_SCHEMA = vol.Schema(
    {
        vol.Required(ATTR_DEVICE_ID): vol.All(cv.ensure_list, [cv.string]),
        vol.Optional(ATTR_AMOUNT): vol.All(
            vol.Coerce(int), vol.Range(min=MIN_PORTION_G, max=MAX_PORTION_G)
        ),
    }
)


def build_client(hass: HomeAssistant, email: str, password: str) -> PawsyncClient:
    """Client localised with the Home Assistant settings."""
    return PawsyncClient(
        async_get_clientsession(hass),
        email,
        password,
        time_zone=hass.config.time_zone,
        country=(hass.config.country or "FR").upper(),
        language=(hass.config.language or "fr").split("-")[0],
    )


CARD_URL = "/pawsync_feeder/pawsync-feeder-card.js"
CARD_FILE = Path(__file__).parent / "www" / "pawsync-feeder-card.js"


CARD_REGISTERED = f"{DOMAIN}_card_registered"


async def _async_register_card(hass: HomeAssistant) -> None:
    """Serve the Lovelace card and load it in every dashboard (once)."""
    if hass.data.get(CARD_REGISTERED):
        return
    if hass.http is None:
        _LOGGER.warning("HTTP server not ready, Pawsync card not registered yet")
        return
    hass.data[CARD_REGISTERED] = True
    from homeassistant.components.frontend import add_extra_js_url
    from homeassistant.components.http import StaticPathConfig

    try:
        version = (await async_get_integration(hass, DOMAIN)).version
        if not CARD_FILE.is_file():
            raise FileNotFoundError(CARD_FILE)
        await hass.http.async_register_static_paths(
            [StaticPathConfig(CARD_URL, str(CARD_FILE), cache_headers=False)]
        )
        add_extra_js_url(hass, f"{CARD_URL}?v={version}")
    except Exception:
        _LOGGER.exception("Pawsync card could not be registered")
        hass.data[CARD_REGISTERED] = False
        return
    _LOGGER.warning("Pawsync card registered at %s (v%s)", CARD_URL, version)


async def async_setup(hass: HomeAssistant, config: ConfigType) -> bool:
    """Register the feed action (works across all accounts) and the dashboard card."""
    await _async_register_card(hass)
    if not hass.data.get(CARD_REGISTERED):
        # Frontend not loaded yet at this point of the boot: retry once HA has started.
        async def _late_register(_event: Event) -> None:
            await _async_register_card(hass)

        hass.bus.async_listen_once(EVENT_HOMEASSISTANT_STARTED, _late_register)

    async def _feed(call: ServiceCall) -> None:
        registry = dr.async_get(hass)
        for device_id in call.data[ATTR_DEVICE_ID]:
            device_entry = registry.async_get(device_id)
            feeder_id = next(
                (ident for dom, ident in (device_entry.identifiers if device_entry else ()) if dom == DOMAIN),
                None,
            )
            coordinator: PawsyncCoordinator | None = None
            for entry in hass.config_entries.async_loaded_entries(DOMAIN):
                if feeder_id in entry.runtime_data.data.devices:
                    coordinator = entry.runtime_data
                    break
            if feeder_id is None or coordinator is None:
                raise ServiceValidationError(
                    translation_domain=DOMAIN,
                    translation_key="unknown_device",
                    translation_placeholders={"device_id": device_id},
                )
            device = coordinator.data.devices[feeder_id]
            amount = call.data.get(ATTR_AMOUNT, coordinator.portion_for(feeder_id))
            try:
                await coordinator.client.feed(device, amount)
            except PawsyncAuthError as err:
                coordinator.config_entry.async_start_reauth(hass)
                raise ServiceValidationError(
                    translation_domain=DOMAIN, translation_key="auth_failed"
                ) from err
            except PawsyncError as err:
                raise ServiceValidationError(
                    translation_domain=DOMAIN,
                    translation_key="command_failed",
                    translation_placeholders={"error": str(err)},
                ) from err
            await coordinator.async_request_refresh()

    hass.services.async_register(DOMAIN, SERVICE_FEED, _feed, schema=FEED_SCHEMA)
    return True


async def async_setup_entry(hass: HomeAssistant, entry: PawsyncConfigEntry) -> bool:
    await _async_register_card(hass)
    client = build_client(hass, entry.data[CONF_EMAIL], entry.data[CONF_PASSWORD])
    try:
        await client.login()
    except PawsyncAuthError as err:
        raise ConfigEntryAuthFailed(str(err)) from err
    except PawsyncError as err:
        raise ConfigEntryNotReady(str(err)) from err

    coordinator = PawsyncCoordinator(hass, entry, client)
    await coordinator.async_config_entry_first_refresh()
    entry.runtime_data = coordinator

    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    return True


async def async_unload_entry(hass: HomeAssistant, entry: PawsyncConfigEntry) -> bool:
    return await hass.config_entries.async_unload_platforms(entry, PLATFORMS)


async def async_remove_config_entry_device(
    hass: HomeAssistant, entry: PawsyncConfigEntry, device_entry: dr.DeviceEntry
) -> bool:
    """Allow deleting a feeder that is no longer on the account."""
    return not any(
        dom == DOMAIN and ident in entry.runtime_data.data.devices
        for dom, ident in device_entry.identifiers
    )
