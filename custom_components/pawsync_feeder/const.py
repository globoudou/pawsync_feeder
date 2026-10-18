"""Constants for the Pawsync Feeder integration."""

from __future__ import annotations

from homeassistant.const import Platform

DOMAIN = "pawsync_feeder"
MANUFACTURER = "Pawsync"

PLATFORMS: list[Platform] = [
    Platform.BINARY_SENSOR,
    Platform.BUTTON,
    Platform.EVENT,
    Platform.NUMBER,
    Platform.SENSOR,
    Platform.SWITCH,
    Platform.TIME,
    Platform.UPDATE,
]

CONF_SCAN_INTERVAL = "scan_interval"
DEFAULT_SCAN_INTERVAL = 5  # minutes
MIN_SCAN_INTERVAL = 1
MAX_SCAN_INTERVAL = 60

FIRMWARE_REFRESH_HOURS = 6

# Extra meal portion (grams). One app "portion" is ~11 g.
DEFAULT_PORTION_G = 11
MIN_PORTION_G = 1
MAX_PORTION_G = 110

# Hopper capacity of the PPF-R361S (3.6 L) — used to convert the fill percentage.
HOPPER_CAPACITY_ML = 3600
HOPPER_MIN_ML = 0

DEFAULT_SLEEP_START = 22 * 3600
DEFAULT_SLEEP_END = 7 * 3600

LOG_PLANNED = "planFeeding"
LOG_MANUAL = "manualFeeding"
LOG_EATEN = "takeFood"
DISPENSE_LOG_TYPES = (LOG_PLANNED, LOG_MANUAL)

SERVICE_FEED = "feed"
ATTR_AMOUNT = "amount"
