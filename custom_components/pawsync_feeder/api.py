"""Async client for the Pawsync cloud API (VeSync platform).

The protocol was reverse-engineered by the community (jasonmeisel/pawsync-hass,
smcneece/pawsync-hass). This module re-implements it as a self-contained,
per-account client:

* no module-level mutable state (several accounts can coexist),
* automatic re-authentication and single retry when the token expires,
* request timeouts and typed exceptions,
* time zone / country / language taken from the caller (Home Assistant config),
  so "today" statistics and schedules match the user's locale,
* the auth token never reaches the logs.
"""

from __future__ import annotations

import asyncio
import hashlib
import logging
import secrets
import time
from dataclasses import dataclass, field
from typing import Any

import aiohttp

_LOGGER = logging.getLogger(__name__)

DEFAULT_BASE_URL = "https://smartapi.pawsync.com"
APP_ID = "psybfyca"
CLIENT_VERSION = "Pawsync 1.1.32"
OS_INFO = "Android 15"
REQUEST_TIMEOUT = 20

# Error codes returned by the API when the token is no longer valid.
TOKEN_INVALID_CODES = {-11008800, -11012022, 4001004}


class PawsyncError(Exception):
    """Base error."""


class PawsyncConnectionError(PawsyncError):
    """Network / HTTP / unparsable response."""


class PawsyncAuthError(PawsyncError):
    """Credentials rejected."""


class PawsyncApiError(PawsyncError):
    """The API answered with a non-zero code."""

    def __init__(self, method: str, code: Any, msg: str | None) -> None:
        super().__init__(f"{method}: code={code} msg={msg}")
        self.method = method
        self.code = code
        self.msg = msg


@dataclass
class PawsyncDevice:
    """A feeder as returned by deviceList4Pet, enriched with live status."""

    device_id: str
    name: str
    model: str
    config_model: str
    image: str | None
    pet_id: str | int | None
    connection_type: str | None
    prop: dict[str, Any] = field(default_factory=dict)

    @classmethod
    def from_api(cls, raw: dict[str, Any]) -> PawsyncDevice:
        return cls(
            device_id=str(raw["deviceId"]),
            name=raw.get("deviceName") or "Pawsync",
            model=raw.get("deviceModel") or "",
            config_model=raw.get("configModel") or "",
            image=raw.get("deviceImg") or raw.get("deviceDefaultImg"),
            pet_id=raw.get("petId"),
            connection_type=raw.get("connectionType"),
            prop=dict(raw.get("deviceProp") or {}),
        )


def _is_token_error(payload: dict[str, Any]) -> bool:
    code = payload.get("code")
    if code in TOKEN_INVALID_CODES:
        return True
    msg = str(payload.get("msg") or "").lower()
    return code not in (0, None) and "token" in msg


class PawsyncClient:
    """One authenticated Pawsync account."""

    def __init__(
        self,
        session: aiohttp.ClientSession,
        email: str,
        password: str,
        *,
        time_zone: str = "Europe/Paris",
        country: str = "FR",
        language: str = "fr",
        base_url: str = DEFAULT_BASE_URL,
    ) -> None:
        self._session = session
        self._email = email
        # The app sends SHA-256(password); the clear password is never transmitted.
        self._password_hash = hashlib.sha256(password.encode()).hexdigest()
        self._time_zone = time_zone
        self._country = country
        self._language = language
        self._base_url = base_url.rstrip("/")
        # Stable terminal id: the server reuses the same session across restarts
        # instead of piling up sessions (which logs the phone app out).
        self._terminal_id = hashlib.sha256(email.encode()).hexdigest()[:32]
        self.account_id: str | None = None
        self._token: str | None = None
        self._login_lock = asyncio.Lock()

    # ------------------------------------------------------------------ helpers

    @staticmethod
    def _trace_id() -> str:
        return f"PET{secrets.token_hex(8)}-{secrets.randbelow(100000):05d}"

    def _context(self, method: str) -> dict[str, Any]:
        ctx: dict[str, Any] = {
            "acceptLanguage": self._language,
            "appID": APP_ID,
            "clientInfo": "API",
            "clientType": "pawsync",
            "clientVersion": CLIENT_VERSION,
            "debugMode": "false",
            "method": method,
            "osInfo": OS_INFO,
            "terminalId": self._terminal_id,
            "timeZone": self._time_zone,
            "traceId": self._trace_id(),
            "userCountryCode": self._country,
        }
        if self._token:
            ctx["accountID"] = self.account_id
            ctx["token"] = self._token
        return ctx

    async def _raw_post(self, url: str, body: dict[str, Any], method: str) -> dict[str, Any]:
        try:
            async with self._session.post(
                url, json=body, timeout=aiohttp.ClientTimeout(total=REQUEST_TIMEOUT)
            ) as resp:
                if resp.status >= 500:
                    raise PawsyncConnectionError(f"{method}: HTTP {resp.status}")
                try:
                    payload = await resp.json(content_type=None)
                except (aiohttp.ContentTypeError, ValueError) as err:
                    raise PawsyncConnectionError(f"{method}: invalid JSON") from err
        except (TimeoutError, aiohttp.ClientError) as err:
            raise PawsyncConnectionError(f"{method}: {err!r}") from err
        if not isinstance(payload, dict):
            raise PawsyncConnectionError(f"{method}: unexpected payload")
        return payload

    # --------------------------------------------------------------------- auth

    async def login(self) -> str:
        """Authenticate; returns the account id."""
        async with self._login_lock:
            self._token = None
            body = {
                "context": self._context("login"),
                "data": {"email": self._email, "password": self._password_hash},
            }
            payload = await self._raw_post(
                f"{self._base_url}/pet/api/userManaged/v1/login", body, "login"
            )
            result = payload.get("result")
            if payload.get("code") != 0 or not result:
                code = payload.get("code")
                _LOGGER.debug("Login refused: code=%s msg=%s", code, payload.get("msg"))
                if code is None:
                    raise PawsyncConnectionError("login: malformed answer")
                # Any explicit refusal at login is treated as a credentials problem.
                raise PawsyncAuthError(payload.get("msg") or f"code {code}")
            self.account_id = str(result["accountId"])
            self._token = result["token"]
            return self.account_id

    async def _ensure_login(self) -> None:
        if self._token is None:
            await self.login()

    # ------------------------------------------------------------------ requests

    async def _call(self, service: str, method: str, data: dict[str, Any] | None = None) -> Any:
        """Standard REST-like call; returns ``result``."""
        await self._ensure_login()
        for attempt in (1, 2):
            body = {"context": self._context(method), "data": data or {}}
            payload = await self._raw_post(
                f"{self._base_url}/pet/api/{service}/v1/{method}", body, method
            )
            if attempt == 1 and _is_token_error(payload):
                _LOGGER.debug("%s: token expired, logging in again", method)
                await self.login()
                continue
            if payload.get("code") != 0:
                raise PawsyncApiError(method, payload.get("code"), payload.get("msg"))
            return payload.get("result")
        raise PawsyncAuthError(method)  # pragma: no cover

    async def _bypass(
        self, device: PawsyncDevice, method: str, data: dict[str, Any] | None = None
    ) -> dict[str, Any]:
        """Device command through the VeSync ``bypassV2`` envelope; returns inner result."""
        await self._ensure_login()
        for attempt in (1, 2):
            body = {
                "acceptLanguage": self._language,
                "accountID": self.account_id,
                "appID": APP_ID,
                "appVersion": CLIENT_VERSION,
                "debugMode": "false",
                "method": "bypassV2",
                "phoneBrand": "",
                "phoneOS": OS_INFO,
                "timeZone": self._time_zone,
                "token": self._token,
                "traceId": self._trace_id(),
                "userCountryCode": self._country,
                "cid": device.device_id,
                "configModule": device.config_model,
                "payload": {
                    "data": {
                        **(data or {}),
                        "cid": device.device_id,
                        "configModule": device.config_model,
                    },
                    "method": method,
                    "source": "APP",
                },
            }
            payload = await self._raw_post(
                f"{self._base_url}/pet/api/deviceManaged/v1/bypassV2", body, method
            )
            if attempt == 1 and _is_token_error(payload):
                _LOGGER.debug("%s: token expired, logging in again", method)
                await self.login()
                continue
            if payload.get("code") != 0:
                raise PawsyncApiError(method, payload.get("code"), payload.get("msg"))
            inner = payload.get("result") or {}
            if isinstance(inner, dict) and inner.get("code") not in (0, None):
                raise PawsyncApiError(method, inner.get("code"), inner.get("msg"))
            return (inner.get("result") if isinstance(inner, dict) else None) or {}
        raise PawsyncAuthError(method)  # pragma: no cover

    # --------------------------------------------------------------------- reads

    async def get_devices(self) -> list[PawsyncDevice]:
        result = await self._call("deviceManaged", "deviceList4Pet")
        return [PawsyncDevice.from_api(d) for d in (result or {}).get("list") or []]

    async def get_device_status(self, device: PawsyncDevice) -> dict[str, Any]:
        """Live readings (bowl scale, desiccant, switches...)."""
        return await self._bypass(device, "getPetDeviceStatus")

    async def get_pets(self) -> list[dict[str, Any]]:
        result = await self._call("petManaged", "getPetList")
        return (result or {}).get("petList") or []

    async def get_pet_logs(
        self, device_id: str, start_ts: int | None = None, page_size: int = 100
    ) -> list[dict[str, Any]]:
        end_ts = int(time.time())
        result = await self._call(
            "petDeviceManaged",
            "getPetLogList",
            {
                "deviceId": device_id,
                "endTimestamp": end_ts,
                "objectType": 0,
                "pageSize": page_size,
                "startTimestamp": start_ts if start_ts is not None else end_ts - 86400,
            },
        )
        logs = (result or {}).get("petLogList") or []
        return sorted(logs, key=lambda e: e.get("timestamp") or 0, reverse=True)

    async def get_firmware(self, device_ids: list[str]) -> dict[str, list[dict[str, Any]]]:
        result = await self._call(
            "deviceManaged", "getFirmwareUpdateInfoList", {"deviceIdList": device_ids}
        )
        return {
            str(item["deviceId"]): item.get("firmUpdateInfos") or []
            for item in (result or {}).get("wifiInfoList") or []
        }

    # ------------------------------------------------------------------ commands

    async def feed(self, device: PawsyncDevice, grams: int) -> dict[str, Any]:
        return await self._bypass(device, "manualFeeding", {"serving1": int(grams)})

    async def set_smart_feeding(self, device: PawsyncDevice, on: bool) -> None:
        await self._bypass(device, "setIntelligentFeedingMode", {"enable": int(on)})

    async def set_slow_feeding(self, device: PawsyncDevice, on: bool) -> None:
        await self._bypass(device, "setPetSlowFeedMode", {"enable": int(on)})

    async def set_precision_mode(self, device: PawsyncDevice, on: bool) -> None:
        # Capital "I" is what the app really sends.
        await self._bypass(device, "setIAccurateFeedingMode", {"enable": int(on)})

    async def set_sleep_mode(
        self, device: PawsyncDevice, enable: bool, start_sec: int, end_sec: int
    ) -> None:
        # The device silently ignores the command unless all three fields are sent.
        await self._bypass(
            device,
            "setPetSleepMode",
            {"enable": int(enable), "startClkSec": int(start_sec), "endClkSec": int(end_sec)},
        )

    async def tare_scale(self, device: PawsyncDevice) -> None:
        await self._bypass(device, "setFeedingBowlToZero")

    async def play_meal_call(self, device: PawsyncDevice) -> None:
        await self._bypass(device, "playPetVoice")

    async def reset_desiccant(self, device: PawsyncDevice, days: int = 30) -> None:
        await self._bypass(device, "updatePetDesiccantInfo", {"remainTime": int(days)})

    async def set_hopper_volume(self, device: PawsyncDevice, volume_ml: float) -> dict[str, Any]:
        return await self._bypass(
            device, "updatePetContentSize", {"type": 0, "volume_ml": float(volume_ml)}
        )
