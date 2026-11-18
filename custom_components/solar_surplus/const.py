"""Constants for the Solar Surplus integration."""

from __future__ import annotations

from datetime import timedelta
from enum import IntEnum, StrEnum
from typing import Final

DOMAIN: Final = "solar_surplus"
TITLE: Final = "Solar Surplus"

SUBENTRY_TYPE_CONSUMER: Final = "consumer"

################################################################################
# Hub configuration
################################################################################

CONF_GRID_POWER: Final = "grid_power"
#: Off (the default), a positive grid reading means power drawn from the grid.
CONF_GRID_EXPORT_POSITIVE: Final = "grid_export_positive"
CONF_BATTERY_POWER: Final = "battery_power"
#: Off (the default), a positive battery reading means the battery charges.
CONF_BATTERY_DISCHARGE_POSITIVE: Final = "battery_discharge_positive"
CONF_BATTERY_SOC: Final = "battery_soc"
#: Below this charge the battery comes first: what it charges with is not
#: handed out.
CONF_BATTERY_TARGET_SOC: Final = "battery_target_soc"
#: At or below this charge the battery counts as empty: drawing from the grid
#: then locks SG Ready heat pumps and blocks signals.
CONF_BATTERY_MIN_SOC: Final = "battery_min_soc"
#: How fast the battery can charge. Known, the part of it the battery does not
#: use yet is held back while it is below its target, instead of a consumer
#: taking it.
CONF_BATTERY_MAX_CHARGE: Final = "battery_max_charge_power"
CONF_FORECAST_ENTRIES: Final = "forecast_entries"
#: Held back from the surplus, so a consumer is not switched on by the last few
#: watts and then runs on the grid as soon as a cloud passes.
CONF_RESERVE: Final = "reserve"
#: What the house draws on its own, for reading the forecast: the expected
#: surplus of an hour is its forecast minus this.
CONF_BASE_LOAD: Final = "base_load"

#: From this much drawn from the grid, with the battery empty, SG Ready heat
#: pumps may be locked and signals say blocked.
CONF_SIGNAL_BLOCKED: Final = "signal_blocked"
#: Test mode: where to send what would have been switched. A `notify` action
#: or entity; without one, a persistent notification.
CONF_NOTIFY_TARGET: Final = "notify_target"

#: Positive battery power means discharging, as in the energy dashboard.
DEFAULT_BATTERY_DISCHARGE_POSITIVE: Final = True
DEFAULT_BATTERY_TARGET_SOC: Final = 90
DEFAULT_BATTERY_MIN_SOC: Final = 20
DEFAULT_RESERVE: Final = 100
DEFAULT_BASE_LOAD: Final = 400
DEFAULT_SIGNAL_BLOCKED: Final = 500

################################################################################
# Consumer configuration
################################################################################

CONF_NAME: Final = "name"
CONF_ADAPTER: Final = "adapter"
#: What the consumer draws when on. Used whenever there is no power sensor, and
#: always to decide whether it fits before it is switched on.
CONF_POWER: Final = "power"
CONF_POWER_SENSOR: Final = "power_sensor"
CONF_MIN_ON_TIME: Final = "min_on_time"
CONF_MIN_OFF_TIME: Final = "min_off_time"
CONF_ON_DELAY: Final = "on_delay"
CONF_OFF_DELAY: Final = "off_delay"

CONF_SWITCH_ENTITY: Final = "switch_entity"

CONF_NUMBER_ENTITY: Final = "number_entity"
CONF_MIN_POWER: Final = "min_power"
CONF_POWER_STEP: Final = "power_step"
#: How many watts one unit of the number is: 1 for a number in watts, 230 for
#: amperes on one phase, 690 on three.
CONF_WATTS_PER_UNIT: Final = "watts_per_unit"

CONF_SG_CONTACT_1: Final = "sg_contact_1"
CONF_SG_CONTACT_2: Final = "sg_contact_2"
CONF_SG_FORCED_POWER: Final = "sg_forced_power"
CONF_SG_LOCK: Final = "sg_lock"

CONF_ON_ENTITY: Final = "on_entity"
CONF_OFF_ENTITY: Final = "off_entity"
CONF_STATE_ENTITY: Final = "state_entity"

CONF_READY_ENTITY: Final = "ready_entity"
CONF_START_ENTITY: Final = "start_entity"
CONF_DEADLINE_ENTITY: Final = "deadline_entity"
CONF_DEADLINE_TIME: Final = "deadline_time"
CONF_RUN_TIME: Final = "run_time"
CONF_FINISH_POWER: Final = "finish_power"
CONF_FINISH_DELAY: Final = "finish_delay"
CONF_TURN_OFF_WHEN_DONE: Final = "turn_off_when_done"

DEFAULT_MIN_ON_TIME: Final = 10
DEFAULT_MIN_OFF_TIME: Final = 5
DEFAULT_ON_DELAY: Final = 60
DEFAULT_OFF_DELAY: Final = 120
DEFAULT_POWER_STEP: Final = 100
DEFAULT_WATTS_PER_UNIT: Final = 1
DEFAULT_DEADLINE_TIME: Final = "18:00:00"
DEFAULT_RUN_TIME: Final = 120
DEFAULT_FINISH_POWER: Final = 5
DEFAULT_FINISH_DELAY: Final = 5

################################################################################
# Timings
################################################################################

#: How often the allocation runs without a state change to trigger it.
TICK_INTERVAL: Final = timedelta(seconds=10)
#: A state change triggers a run, but not more often than this.
REFRESH_COOLDOWN: Final = 2.0
#: How long the forecast is reused before it is read again. The forecast
#: integrations themselves update far less often.
FORECAST_REFRESH: Final = timedelta(minutes=15)
#: Time constant of the surplus smoothing. A passing cloud or a kettle should
#: not switch a consumer.
SMOOTHING: Final = timedelta(seconds=30)
#: A deferrable consumer is not checked for having finished this early: it
#: draws little while it fills with water.
FINISH_GRACE: Final = timedelta(minutes=2)
#: SG Ready allows a utility lock of at most two hours, and the heat pump has
#: to be released in between.
SG_LOCK_MAX: Final = timedelta(hours=2)
SG_LOCK_PAUSE: Final = timedelta(hours=1)

################################################################################
# Panel
################################################################################

PANEL_URL_PATH: Final = "solar-surplus"
PANEL_ASSET_URL: Final = "/solar_surplus/solar-surplus-panel.js"
PANEL_COMPONENT_NAME: Final = "solar-surplus-panel"
PANEL_VERSION: Final = "0.1.0"
PANEL_ICON: Final = "mdi:solar-power-variant"
PANEL_TITLE: Final[dict[str, str]] = {"en": "Solar Surplus", "de": "Solarüberschuss"}

STORAGE_KEY: Final = DOMAIN
STORAGE_VERSION: Final = 1

################################################################################
# Enums
################################################################################


class AdapterType(StrEnum):
    """How a consumer is switched."""

    SWITCH = "switch"
    NUMBER = "number"
    SG_READY = "sg_ready"
    SCRIPT = "script"
    DEFERRABLE = "deferrable"
    #: Switches nothing: an energy signal, after SG Ready 1 to 4, that
    #: another integration follows.
    SIGNAL = "signal"


class Override(StrEnum):
    """A hand on a consumer: let the allocation decide, or not."""

    AUTO = "auto"
    ON = "on"
    OFF = "off"


class ConsumerState(StrEnum):
    """What a consumer is doing."""

    OFF = "off"
    ON = "on"
    LOCKED = "locked"
    WAITING = "waiting"
    RUNNING = "running"
    DONE = "done"
    IDLE = "idle"
    UNAVAILABLE = "unavailable"


class Reason(StrEnum):
    """Why a consumer is in its state."""

    OVERRIDE_ON = "override_on"
    OVERRIDE_OFF = "override_off"
    UNAVAILABLE = "unavailable"
    SURPLUS = "surplus"
    INSUFFICIENT_SURPLUS = "insufficient_surplus"
    ON_DELAY = "on_delay"
    OFF_DELAY = "off_delay"
    MIN_ON_TIME = "min_on_time"
    MIN_OFF_TIME = "min_off_time"
    FORCED_SURPLUS = "forced_surplus"
    GRID_IMPORT = "grid_import"
    LOCK_LIMIT = "lock_limit"
    NOT_READY = "not_ready"
    WAITING_FORECAST = "waiting_forecast"
    WAITING_DEADLINE = "waiting_deadline"
    DEADLINE = "deadline"
    RUNNING = "running"
    FINISHED = "finished"
    NO_DATA = "no_data"


class SgState(IntEnum):
    """The four SG Ready operating states."""

    LOCK = 1
    NORMAL = 2
    RECOMMENDED = 3
    FORCED = 4


class EnergySignal(StrEnum):
    """What a signal consumer tells, after SG Ready 1 to 4."""

    BLOCKED = "blocked"
    NORMAL = "normal"
    RECOMMENDED = "recommended"
    FORCED = "forced"


class DeferrablePhase(StrEnum):
    """Where a deferrable consumer is in its run."""

    IDLE = "idle"
    READY = "ready"
    RUNNING = "running"
    DONE = "done"
