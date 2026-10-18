"""End-to-end tests against the fake cloud."""

from __future__ import annotations

import time
from datetime import timedelta

import pytest
from homeassistant import config_entries
from homeassistant.const import CONF_EMAIL, CONF_PASSWORD, STATE_ON
from homeassistant.core import HomeAssistant
from homeassistant.data_entry_flow import FlowResultType
from homeassistant.helpers import device_registry as dr, entity_registry as er
from homeassistant.util import dt as dt_util
from pytest_homeassistant_custom_component.common import MockConfigEntry, async_fire_time_changed

from custom_components.pawsync_feeder.const import DOMAIN

from .conftest import DEVICE_ID

CREDS = {CONF_EMAIL: "me@example.com", CONF_PASSWORD: "secret"}


async def _setup(hass: HomeAssistant) -> MockConfigEntry:
    entry = MockConfigEntry(domain=DOMAIN, data=CREDS, unique_id="acc-1", title="me")
    entry.add_to_hass(hass)
    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()
    return entry


def _eid(hass: HomeAssistant, platform: str, key: str) -> str:
    eid = er.async_get(hass).async_get_entity_id(platform, DOMAIN, f"{DEVICE_ID}_{key}")
    assert eid, f"{platform}.{key} missing"
    return eid


async def test_config_flow(hass: HomeAssistant, cloud) -> None:
    result = await hass.config_entries.flow.async_init(DOMAIN, context={"source": config_entries.SOURCE_USER})
    assert result["type"] is FlowResultType.FORM
    cloud.password_ok = False
    result = await hass.config_entries.flow.async_configure(result["flow_id"], CREDS)
    assert result["errors"] == {"base": "invalid_auth"}
    cloud.password_ok = True
    result = await hass.config_entries.flow.async_configure(result["flow_id"], CREDS)
    assert result["type"] is FlowResultType.CREATE_ENTRY
    assert result["result"].unique_id == "acc-1"
    # the password is sent hashed, never in clear
    login_body = next(b for api, b in cloud.calls if api == "login")
    assert login_body["password"] != "secret" and len(login_body["password"]) == 64


async def test_entities_and_values(hass: HomeAssistant, cloud) -> None:
    await _setup(hass)
    assert hass.states.get(_eid(hass, "sensor", "bowl_weight")).state == "23"  # live, not cached 999
    assert hass.states.get(_eid(hass, "sensor", "hopper_level")).state == "50"
    assert hass.states.get(_eid(hass, "sensor", "eaten_today")).state in ("15", "15.0", "0", "0.0")
    pet = hass.states.get(_eid(hass, "sensor", "pet_weight"))
    assert pet.attributes["unit_of_measurement"] == "kg" and float(pet.state) == pytest.approx(4.2)
    assert "Moustache" in pet.name
    assert hass.states.get(_eid(hass, "binary_sensor", "online")).state == STATE_ON
    assert hass.states.get(_eid(hass, "binary_sensor", "bowl")).state == "off"
    assert hass.states.get(_eid(hass, "switch", "smart_feeding")).state == STATE_ON
    assert hass.states.get(_eid(hass, "time", "sleep_start")).state == "22:00:00"
    upd = hass.states.get(_eid(hass, "update", "firmware"))
    assert upd.state == STATE_ON and upd.attributes["latest_version"] == "1.0.7"
    dev = dr.async_get(hass).async_get_device({(DOMAIN, DEVICE_ID)})
    assert dev.model == "PPF-R361S-WEU" and dev.model_id == "VS_WB_PFM_PPF-R361S-WEU_EU"


async def test_feed_button_and_service(hass: HomeAssistant, cloud) -> None:
    await _setup(hass)
    await hass.services.async_call(
        "number", "set_value", {"entity_id": _eid(hass, "number", "portion"), "value": 22}, blocking=True
    )
    await hass.services.async_call("button", "press", {"entity_id": _eid(hass, "button", "feed")}, blocking=True)
    feeds = [b for api, b in cloud.calls if api == "manualFeeding"]
    assert feeds[-1]["serving1"] == 22 and feeds[-1]["cid"] == DEVICE_ID
    device = dr.async_get(hass).async_get_device({(DOMAIN, DEVICE_ID)})
    await hass.services.async_call(DOMAIN, "feed", {"device_id": device.id, "amount": 11}, blocking=True)
    feeds = [b for api, b in cloud.calls if api == "manualFeeding"]
    assert feeds[-1]["serving1"] == 11


async def test_switch_and_sleep(hass: HomeAssistant, cloud) -> None:
    await _setup(hass)
    eid = _eid(hass, "switch", "sleep_mode")
    await hass.services.async_call("switch", "turn_on", {"entity_id": eid}, blocking=True)
    body = [b for api, b in cloud.calls if api == "setPetSleepMode"][-1]
    assert body["enable"] == 1 and body["startClkSec"] == 79200 and body["endClkSec"] == 25200
    assert hass.states.get(eid).state == STATE_ON  # optimistic
    await hass.services.async_call(
        "time", "set_value", {"entity_id": _eid(hass, "time", "sleep_end"), "time": "06:30"}, blocking=True
    )
    body = [b for api, b in cloud.calls if api == "setPetSleepMode"][-1]
    assert body == {**body, "enable": 1, "startClkSec": 79200, "endClkSec": 6 * 3600 + 1800}
    await hass.services.async_call(
        "switch", "turn_off", {"entity_id": _eid(hass, "switch", "precision_mode")}, blocking=True
    )
    assert [b for api, b in cloud.calls if api == "setIAccurateFeedingMode"][-1]["enable"] == 0


async def test_token_refresh_and_events(hass: HomeAssistant, cloud) -> None:
    await _setup(hass)
    ev = _eid(hass, "event", "feeding")
    assert hass.states.get(ev).state == "unknown"  # history is not replayed
    cloud.expire_token_once = True
    cloud.logs.insert(0, {"logType": "manualFeeding", "timestamp": int(time.time()), "value": 11})
    logins = sum(1 for api, _ in cloud.calls if api == "login")
    async_fire_time_changed(hass, dt_util.utcnow() + timedelta(minutes=6))
    await hass.async_block_till_done(wait_background_tasks=True)
    assert sum(1 for api, _ in cloud.calls if api == "login") == logins + 1
    state = hass.states.get(ev)
    assert state.attributes["event_type"] == "extra_meal" and state.attributes["amount"] == 11


async def test_auth_failure_starts_reauth(hass: HomeAssistant, cloud) -> None:
    cloud.password_ok = False
    entry = MockConfigEntry(domain=DOMAIN, data=CREDS, unique_id="acc-1")
    entry.add_to_hass(hass)
    await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()
    assert entry.state is config_entries.ConfigEntryState.SETUP_ERROR
    flows = hass.config_entries.flow.async_progress()
    assert flows and flows[0]["context"]["source"] == "reauth"
    cloud.password_ok = True
    result = await hass.config_entries.flow.async_configure(flows[0]["flow_id"], {CONF_PASSWORD: "new"})
    assert result["reason"] == "reauth_successful"


async def test_hopper_and_diagnostics(hass: HomeAssistant, cloud) -> None:
    entry = await _setup(hass)
    await hass.services.async_call(
        "number", "set_value", {"entity_id": _eid(hass, "number", "hopper_volume"), "value": 3000}, blocking=True
    )
    assert [b for api, b in cloud.calls if api == "updatePetContentSize"][-1]["volume_ml"] == 3000.0
    assert hass.states.get(_eid(hass, "sensor", "food_days_left")).state == "25"
    from custom_components.pawsync_feeder.diagnostics import async_get_config_entry_diagnostics

    diag = await async_get_config_entry_diagnostics(hass, entry)
    assert diag["entry"]["data"][CONF_PASSWORD] == "**REDACTED**"
    assert "secret" not in str(diag) and "me@example.com" not in str(diag)


async def test_card_served(hass: HomeAssistant, cloud, hass_client) -> None:
    from homeassistant.components.frontend import DATA_EXTRA_MODULE_URL
    from homeassistant.setup import async_setup_component

    assert await async_setup_component(hass, "frontend", {})
    await _setup(hass)
    urls = hass.data[DATA_EXTRA_MODULE_URL].urls
    assert any(u.startswith("/pawsync_feeder/pawsync-feeder-card.js") for u in urls)
    client = await hass_client()
    resp = await client.get("/pawsync_feeder/pawsync-feeder-card.js")
    assert resp.status == 200
    assert "pawsync-feeder-card" in await resp.text()


async def test_odd_flag_formats(hass: HomeAssistant, cloud) -> None:
    cloud.status["accurateFeeding"] = {"enable": True, "level": 2}
    cloud.status["slowFeedSwitch"] = "on"
    cloud.status["sleepMode"] = {"enable": "1", "startClkSec": "79200", "endClkSec": 25200}
    await _setup(hass)
    assert hass.states.get(_eid(hass, "switch", "precision_mode")).state == STATE_ON
    assert hass.states.get(_eid(hass, "switch", "slow_feeding")).state == STATE_ON
    assert hass.states.get(_eid(hass, "switch", "sleep_mode")).state == STATE_ON
    assert hass.states.get(_eid(hass, "time", "sleep_start")).state == "22:00:00"
