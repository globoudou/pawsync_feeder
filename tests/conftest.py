"""Fixtures: a fake Pawsync cloud served through aioclient_mock."""

from __future__ import annotations

import time
from typing import Any

import pytest
from pytest_homeassistant_custom_component.test_util.aiohttp import (
    AiohttpClientMockResponse,
)
from yarl import URL

BASE = "https://smartapi.pawsync.com/pet/api"
DEVICE_ID = "feeder-1"


@pytest.fixture(autouse=True)
def auto_enable_custom_integrations(enable_custom_integrations):
    yield


class FakeCloud:
    """Minimal stateful Pawsync cloud."""

    def __init__(self) -> None:
        now = int(time.time())
        self.password_ok = True
        self.expire_token_once = False
        self.calls: list[tuple[str, dict[str, Any]]] = []
        self.status: dict[str, Any] = {
            "bowlWeight": 23,
            "desiccantRemainTime": 12,
            "bowlConnected": "normal",
            "intelligentFeedingSwitch": 1,
            "slowFeedSwitch": 0,
            "accurateFeeding": 1,
            "sleepMode": {"enable": 0, "startClkSec": 79200, "endClkSec": 25200},
        }
        self.logs = [
            {"logType": "planFeeding", "timestamp": now - 3600, "value": 20},
            {"logType": "takeFood", "timestamp": now - 3000, "value": 15, "durationInS": 90},
        ]

    def device(self) -> dict[str, Any]:
        return {
            "deviceName": "Gamelle",
            "deviceImg": "https://img/x.png",
            "deviceDefaultImg": "",
            "deviceId": DEVICE_ID,
            "connectionType": "wifi",
            "secondaryCategory": "feeder",
            "deviceModel": "PPF-R361S-WEU",
            "configModel": "VS_WB_PFM_PPF-R361S-WEU_EU",
            "bizId": "b",
            "petId": 7,
            "deviceProp": {
                "connectionStatus": "online",
                "contentInPot": 50,
                "powerAdapter": 1,
                "wifiRssi": -60,
                "alertCount": 0,
                "petFood": {"bucketSurplus": 900, "contentRemainTime": 18, "lastFeedingAmount": 20},
                "scheduleInfo": {"nextTime": 64800, "nextMount": 20, "totalMealG": 60},
                "firmwareInfos": [{"isMainFw": True, "pluginName": "mainFw", "version": "1.0.5"}],
                "bowlWeight": 999,  # stale cached value, must be overridden by live status
            },
        }

    async def handle(self, method: str, url: URL, data: Any) -> AiohttpClientMockResponse:
        api = str(url).rsplit("/", 1)[-1]
        if api == "bypassV2":
            api = data["payload"]["method"]
            token = data.get("token")
            body = data["payload"]["data"]
        else:
            token = data["context"].get("token")
            body = data["data"]
        self.calls.append((api, body))

        def ok(result: Any) -> AiohttpClientMockResponse:
            return AiohttpClientMockResponse(method, url, json={"code": 0, "msg": "ok", "result": result})

        if api == "login":
            if not self.password_ok:
                return AiohttpClientMockResponse(method, url, json={"code": -11201000, "msg": "bad password", "result": None})
            return ok({"accountId": "acc-1", "token": "tok"})
        if token != "tok":
            return AiohttpClientMockResponse(method, url, json={"code": -11008800, "msg": "token expired"})
        if self.expire_token_once and api == "deviceList4Pet":
            self.expire_token_once = False
            return AiohttpClientMockResponse(method, url, json={"code": -11008800, "msg": "token expired"})
        if api == "deviceList4Pet":
            return ok({"list": [self.device()]})
        if api == "getPetDeviceStatus":
            return ok({"code": 0, "result": dict(self.status)})
        if api == "getPetList":
            return ok({"petList": [{"petId": 7, "petName": "Moustache", "weightInG": 4200,
                                    "todayFoodIntakeInG": 15, "targetFoodIntakeInG": 60,
                                    "todayFoodIntakeTimes": 1}]})
        if api == "getPetLogList":
            return ok({"petLogList": list(self.logs)})
        if api == "getFirmwareUpdateInfoList":
            return ok({"wifiInfoList": [{"deviceId": DEVICE_ID, "firmUpdateInfos": [
                {"pluginName": "mainFw", "currentVersion": "1.0.5", "latestVersion": "1.0.7", "upgradeLevel": 1, "releaseNotes": "fixes"}]}]})
        if api == "manualFeeding":
            return ok({"code": 0, "result": {}})
        if api in ("setIntelligentFeedingMode", "setPetSlowFeedMode", "setIAccurateFeedingMode",
                   "setPetSleepMode", "setFeedingBowlToZero", "playPetVoice", "updatePetDesiccantInfo"):
            return ok({"code": 0, "result": {}})
        if api == "updatePetContentSize":
            return ok({"code": 0, "result": {"daysRemain": 25, "contentInPot": 80}})
        return AiohttpClientMockResponse(method, url, json={"code": -1, "msg": f"unknown {api}"})


@pytest.fixture
def cloud(aioclient_mock) -> FakeCloud:
    fake = FakeCloud()
    for svc, m in (
        ("userManaged", "login"),
        ("deviceManaged", "deviceList4Pet"),
        ("deviceManaged", "bypassV2"),
        ("deviceManaged", "getFirmwareUpdateInfoList"),
        ("petManaged", "getPetList"),
        ("petDeviceManaged", "getPetLogList"),
    ):
        aioclient_mock.post(f"{BASE}/{svc}/v1/{m}", side_effect=fake.handle)
    return fake
