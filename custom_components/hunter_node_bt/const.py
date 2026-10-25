"""Constants for the Hunter NODE-BT integration."""

from __future__ import annotations

DOMAIN = "hunter_node_bt"

# Config / options keys
CONF_PIN = "pin"
CONF_DEFAULT_RUN_TIME = "default_run_time"  # minutes
CONF_SCAN_INTERVAL = "scan_interval"  # minutes

DEFAULT_PIN = 0
DEFAULT_RUN_TIME_MIN = 10
DEFAULT_SCAN_INTERVAL_MIN = 10
DEFAULT_SCAN_INTERVAL = 600  # seconds (10 minutes for battery preservation)

MAX_RAIN_DELAY_DAYS = 30
MAX_SEASON_ADJUST = 300  # percent
MAX_RUN_TIME_MIN = 240

# GATT UUIDs (Nordic UART Service used as a UART bridge)
NUS_SERVICE = "6e400001-b5a3-f393-e0a9-e50e24dcca9e"
MSG_RX = "6e400002-b5a3-f393-e0a9-e50e24dcca9e"  # write without response (app -> device)
MSG_TX = "6e400003-b5a3-f393-e0a9-e50e24dcca9e"  # notify (device -> app)

PIN_SERVICE = "0ed3e3d3-8cd8-4f29-8fec-a7d3a2c5443e"
PIN_CHAR = "4c9dbe52-3566-4dfc-a299-4ea1353970e2"  # write + notify

# Station run states (StationState.State)
STATION_STATE_IDLE = 0
STATION_STATE_WAITING = 1
STATION_STATE_SUSPENDED = 2
STATION_STATE_RUNNING = 3
STATION_STATE_SOAKING = 4
STATION_STATE_DELAY = 5
STATION_STATE_COMPLETE = 6

STATION_STATES = {
    STATION_STATE_IDLE: "idle",
    STATION_STATE_WAITING: "waiting",
    STATION_STATE_SUSPENDED: "suspended",
    STATION_STATE_RUNNING: "running",
    STATION_STATE_SOAKING: "soaking",
    STATION_STATE_DELAY: "delay",
    STATION_STATE_COMPLETE: "complete",
}

ACTIVE_STATES = {STATION_STATE_RUNNING, STATION_STATE_SOAKING}  # valve considered open

# Controller states (ControllerState enum)
CONTROLLER_STATES = {
    0: "idle",
    1: "manual_station",
    2: "system_off",
    3: "programmable_off",
    4: "rain_off",
    5: "rain_delay",
    6: "soil_off",
    7: "program_a_running",
    8: "program_b_running",
    9: "program_c_running",
    10: "manual_run_all",
    11: "manual_program_a",
    12: "manual_program_b",
    13: "manual_program_c",
}
