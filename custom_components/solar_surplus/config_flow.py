"""Config flow: the house's meters, test mode, and each consumer."""

from __future__ import annotations

from typing import Any

import voluptuous as vol
from homeassistant.config_entries import (
    ConfigEntry,
    ConfigFlow,
    ConfigFlowResult,
    ConfigSubentryFlow,
    OptionsFlow,
    SubentryFlowResult,
)
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers import selector
from homeassistant.loader import IntegrationNotFound, async_get_integration

from .const import (
    CONF_ADAPTER,
    CONF_BASE_LOAD,
    CONF_BATTERY_CAPACITY,
    CONF_BATTERY_DISCHARGE_POSITIVE,
    CONF_BATTERY_MAX_CHARGE,
    CONF_BATTERY_MIN_SOC,
    CONF_BATTERY_POWER,
    CONF_BATTERY_SOC,
    CONF_BATTERY_TARGET_SOC,
    CONF_DEADLINE_ENTITY,
    CONF_DEADLINE_TIME,
    CONF_FINISH_DELAY,
    CONF_FINISH_POWER,
    CONF_FORECAST_ENTRIES,
    CONF_GRID_EXPORT_POSITIVE,
    CONF_GRID_POWER,
    CONF_MIN_OFF_TIME,
    CONF_MIN_ON_TIME,
    CONF_MIN_POWER,
    CONF_NAME,
    CONF_NOTIFY_TARGET,
    CONF_NUMBER_ENTITY,
    CONF_OFF_DELAY,
    CONF_OFF_ENTITY,
    CONF_ON_DELAY,
    CONF_ON_ENTITY,
    CONF_POWER,
    CONF_POWER_SENSOR,
    CONF_POWER_STEP,
    CONF_READY_ENTITY,
    CONF_RESERVE,
    CONF_RUN_TIME,
    CONF_SG_CONTACT_1,
    CONF_SG_CONTACT_2,
    CONF_SG_FORCED_POWER,
    CONF_SG_LOCK,
    CONF_SIGNAL_BLOCKED,
    CONF_START_ENTITY,
    CONF_STATE_ENTITY,
    CONF_SWITCH_ENTITY,
    CONF_TURN_OFF_WHEN_DONE,
    CONF_WAIT_FOR_BEST,
    CONF_WATTS_PER_UNIT,
    DEFAULT_BASE_LOAD,
    DEFAULT_BATTERY_DISCHARGE_POSITIVE,
    DEFAULT_BATTERY_MIN_SOC,
    DEFAULT_BATTERY_TARGET_SOC,
    DEFAULT_DEADLINE_TIME,
    DEFAULT_FINISH_DELAY,
    DEFAULT_FINISH_POWER,
    DEFAULT_MIN_OFF_TIME,
    DEFAULT_MIN_ON_TIME,
    DEFAULT_OFF_DELAY,
    DEFAULT_ON_DELAY,
    DEFAULT_POWER_STEP,
    DEFAULT_RESERVE,
    DEFAULT_RUN_TIME,
    DEFAULT_SIGNAL_BLOCKED,
    DEFAULT_WATTS_PER_UNIT,
    DOMAIN,
    SUBENTRY_TYPE_CONSUMER,
    TITLE,
    AdapterType,
)

#: The keys of the first step, which the options flow changes as one.
HUB_KEYS = (
    CONF_GRID_POWER,
    CONF_GRID_EXPORT_POSITIVE,
    CONF_BATTERY_POWER,
    CONF_BATTERY_DISCHARGE_POSITIVE,
    CONF_BATTERY_SOC,
    CONF_BATTERY_TARGET_SOC,
    CONF_BATTERY_MIN_SOC,
    CONF_BATTERY_MAX_CHARGE,
    CONF_BATTERY_CAPACITY,
    CONF_SIGNAL_BLOCKED,
    CONF_FORECAST_ENTRIES,
    CONF_RESERVE,
    CONF_BASE_LOAD,
)

#: The entities a consumer is switched through. Two consumers on one entity
#: would fight over it, so each may be used by one consumer only.
CONTROLLED_KEYS = (
    CONF_SWITCH_ENTITY,
    CONF_NUMBER_ENTITY,
    CONF_SG_CONTACT_1,
    CONF_SG_CONTACT_2,
    CONF_ON_ENTITY,
    CONF_START_ENTITY,
)

SWITCH_DOMAINS = ["switch", "input_boolean", "light"]
ACTION_DOMAINS = ["script", "button", "input_button", "scene"]

################################################################################
# Selectors
################################################################################


def _entity(
    domain: str | list[str], device_class: str | None = None, multiple: bool = False
):
    config = selector.EntitySelectorConfig(domain=domain, multiple=multiple)
    if device_class is not None:
        config = selector.EntitySelectorConfig(
            domain=domain, device_class=device_class, multiple=multiple
        )
    return selector.EntitySelector(config)


def _number(unit: str, maximum: float = 100000, step: float = 1, minimum: float = 0):
    return selector.NumberSelector(
        selector.NumberSelectorConfig(
            min=minimum,
            max=maximum,
            step=step,
            unit_of_measurement=unit,
            mode=selector.NumberSelectorMode.BOX,
        )
    )


def _watts(maximum: float = 100000):
    return _number("W", maximum)


def _bool():
    return selector.BooleanSelector()


def _suggest(key: str, values: dict[str, Any]) -> vol.Optional:
    """An optional field that shows its current value and can be cleared."""
    return vol.Optional(key, description={"suggested_value": values.get(key)})


def _default(key: str, values: dict[str, Any], default: Any) -> vol.Required:
    return vol.Required(key, default=values.get(key, default))


def _prune(user_input: dict[str, Any]) -> dict[str, Any]:
    """Drop what was left empty, so it is not stored as an empty value."""
    return {
        key: value for key, value in user_input.items() if value not in (None, "", [])
    }


################################################################################
# Schemas
################################################################################


def hub_schema(
    values: dict[str, Any], forecast_options: list[selector.SelectOptionDict]
) -> vol.Schema:
    """The house: grid, battery, forecast and the margins."""
    fields: dict[Any, Any] = {
        vol.Required(
            CONF_GRID_POWER, default=values.get(CONF_GRID_POWER, vol.UNDEFINED)
        ): _entity("sensor", "power"),
        _default(CONF_GRID_EXPORT_POSITIVE, values, False): _bool(),
        _suggest(CONF_BATTERY_POWER, values): _entity("sensor", "power"),
        _default(
            CONF_BATTERY_DISCHARGE_POSITIVE, values, DEFAULT_BATTERY_DISCHARGE_POSITIVE
        ): _bool(),
        _suggest(CONF_BATTERY_SOC, values): _entity("sensor", "battery"),
        _default(CONF_BATTERY_TARGET_SOC, values, DEFAULT_BATTERY_TARGET_SOC): _number(
            "%", 100
        ),
        _default(CONF_BATTERY_MIN_SOC, values, DEFAULT_BATTERY_MIN_SOC): _number(
            "%", 100
        ),
        _suggest(CONF_BATTERY_MAX_CHARGE, values): _watts(),
        _suggest(CONF_BATTERY_CAPACITY, values): _number("kWh", 1000, 0.1),
        _default(CONF_SIGNAL_BLOCKED, values, DEFAULT_SIGNAL_BLOCKED): _watts(),
    }
    if forecast_options:
        fields[_suggest(CONF_FORECAST_ENTRIES, values)] = selector.SelectSelector(
            selector.SelectSelectorConfig(
                options=forecast_options,
                multiple=True,
                mode=selector.SelectSelectorMode.LIST,
            )
        )
    fields[_default(CONF_RESERVE, values, DEFAULT_RESERVE)] = _watts(10000)
    fields[_default(CONF_BASE_LOAD, values, DEFAULT_BASE_LOAD)] = _watts(10000)
    return vol.Schema(fields)


def notify_schema(
    values: dict[str, Any], notify_options: list[selector.SelectOptionDict]
) -> vol.Schema:
    """Where test mode sends what it would have switched."""
    return vol.Schema(
        {
            _suggest(CONF_NOTIFY_TARGET, values): selector.SelectSelector(
                selector.SelectSelectorConfig(
                    options=notify_options,
                    custom_value=True,
                    mode=selector.SelectSelectorMode.DROPDOWN,
                )
            ),
        }
    )


def _consumer_head(values: dict[str, Any]) -> dict[Any, Any]:
    return {
        vol.Required(
            CONF_NAME, default=values.get(CONF_NAME, vol.UNDEFINED)
        ): selector.TextSelector(),
        vol.Required(
            CONF_POWER, default=values.get(CONF_POWER, vol.UNDEFINED)
        ): _watts(),
        _suggest(CONF_POWER_SENSOR, values): _entity("sensor", "power"),
    }


def _timings(values: dict[str, Any]) -> dict[Any, Any]:
    return {
        _default(CONF_MIN_ON_TIME, values, DEFAULT_MIN_ON_TIME): _number("min", 1440),
        _default(CONF_MIN_OFF_TIME, values, DEFAULT_MIN_OFF_TIME): _number("min", 1440),
        _default(CONF_ON_DELAY, values, DEFAULT_ON_DELAY): _number("s", 3600),
        _default(CONF_OFF_DELAY, values, DEFAULT_OFF_DELAY): _number("s", 3600),
    }


def switch_schema(values: dict[str, Any]) -> vol.Schema:
    """A consumer switched on and off, such as a heating rod."""
    return vol.Schema(
        {
            **_consumer_head(values),
            vol.Required(
                CONF_SWITCH_ENTITY,
                default=values.get(CONF_SWITCH_ENTITY, vol.UNDEFINED),
            ): _entity(SWITCH_DOMAINS),
            **_timings(values),
        }
    )


def number_schema(values: dict[str, Any]) -> vol.Schema:
    """A consumer whose power is set through a number, such as a wallbox."""
    return vol.Schema(
        {
            **_consumer_head(values),
            vol.Required(
                CONF_NUMBER_ENTITY,
                default=values.get(CONF_NUMBER_ENTITY, vol.UNDEFINED),
            ): _entity(["number", "input_number"]),
            _default(CONF_MIN_POWER, values, 0): _watts(),
            _default(CONF_POWER_STEP, values, DEFAULT_POWER_STEP): _watts(10000),
            _default(CONF_WATTS_PER_UNIT, values, DEFAULT_WATTS_PER_UNIT): _number(
                "W", 10000, 0.01, 0.01
            ),
            _suggest(CONF_SWITCH_ENTITY, values): _entity(SWITCH_DOMAINS),
            **_timings(values),
        }
    )


def sg_ready_schema(values: dict[str, Any]) -> vol.Schema:
    """A heat pump with the two SG Ready contacts."""
    return vol.Schema(
        {
            **_consumer_head(values),
            vol.Required(
                CONF_SG_CONTACT_1, default=values.get(CONF_SG_CONTACT_1, vol.UNDEFINED)
            ): _entity(SWITCH_DOMAINS),
            vol.Required(
                CONF_SG_CONTACT_2, default=values.get(CONF_SG_CONTACT_2, vol.UNDEFINED)
            ): _entity(SWITCH_DOMAINS),
            _suggest(CONF_SG_FORCED_POWER, values): _watts(),
            _default(CONF_SG_LOCK, values, False): _bool(),
            **_timings(values),
        }
    )


def script_schema(values: dict[str, Any]) -> vol.Schema:
    """A consumer started and stopped by scripts, buttons or scenes."""
    return vol.Schema(
        {
            **_consumer_head(values),
            vol.Required(
                CONF_ON_ENTITY, default=values.get(CONF_ON_ENTITY, vol.UNDEFINED)
            ): _entity(ACTION_DOMAINS),
            vol.Required(
                CONF_OFF_ENTITY, default=values.get(CONF_OFF_ENTITY, vol.UNDEFINED)
            ): _entity(ACTION_DOMAINS),
            _suggest(CONF_STATE_ENTITY, values): _entity(
                ["binary_sensor", "switch", "input_boolean"]
            ),
            **_timings(values),
        }
    )


def deferrable_schema(values: dict[str, Any]) -> vol.Schema:
    """A consumer that waits to be started, such as a washing machine."""
    return vol.Schema(
        {
            **_consumer_head(values),
            vol.Required(
                CONF_READY_ENTITY, default=values.get(CONF_READY_ENTITY, vol.UNDEFINED)
            ): _entity(["binary_sensor", "input_boolean", "switch"]),
            vol.Required(
                CONF_START_ENTITY, default=values.get(CONF_START_ENTITY, vol.UNDEFINED)
            ): _entity([*SWITCH_DOMAINS, *ACTION_DOMAINS]),
            _suggest(CONF_DEADLINE_ENTITY, values): _entity(
                ["datetime", "input_datetime", "time", "sensor"]
            ),
            _default(
                CONF_DEADLINE_TIME, values, DEFAULT_DEADLINE_TIME
            ): selector.TimeSelector(),
            _default(CONF_RUN_TIME, values, DEFAULT_RUN_TIME): _number("min", 1440),
            _default(CONF_FINISH_POWER, values, DEFAULT_FINISH_POWER): _watts(10000),
            _default(CONF_FINISH_DELAY, values, DEFAULT_FINISH_DELAY): _number(
                "min", 120
            ),
            _default(CONF_TURN_OFF_WHEN_DONE, values, True): _bool(),
            _default(CONF_WAIT_FOR_BEST, values, True): _bool(),
            _default(CONF_ON_DELAY, values, DEFAULT_ON_DELAY): _number("s", 3600),
        }
    )


def signal_schema(values: dict[str, Any]) -> vol.Schema:
    """An energy signal that another integration follows, such as a heat pump's."""
    return vol.Schema(
        {
            **_consumer_head(values),
            _suggest(CONF_SG_FORCED_POWER, values): _watts(),
            _default(CONF_SG_LOCK, values, False): _bool(),
            **_timings(values),
        }
    )


CONSUMER_SCHEMAS = {
    AdapterType.SWITCH: switch_schema,
    AdapterType.NUMBER: number_schema,
    AdapterType.SG_READY: sg_ready_schema,
    AdapterType.SCRIPT: script_schema,
    AdapterType.DEFERRABLE: deferrable_schema,
    AdapterType.SIGNAL: signal_schema,
}


def adapter_schema() -> vol.Schema:
    """The first step of a new consumer: how it is switched."""
    return vol.Schema(
        {
            vol.Required(CONF_ADAPTER): selector.SelectSelector(
                selector.SelectSelectorConfig(
                    options=[adapter.value for adapter in AdapterType],
                    translation_key=CONF_ADAPTER,
                    mode=selector.SelectSelectorMode.LIST,
                )
            )
        }
    )


def notify_options(hass: HomeAssistant) -> list[selector.SelectOptionDict]:
    """The notify actions and entities, such as the companion app's."""
    actions = [
        selector.SelectOptionDict(value=f"notify.{name}", label=f"notify.{name}")
        for name in sorted(hass.services.async_services_for_domain("notify"))
        if name not in ("send_message", "persistent_notification")
    ]
    entities = [
        selector.SelectOptionDict(
            value=state.entity_id, label=f"{state.name} ({state.entity_id})"
        )
        for state in sorted(hass.states.async_all("notify"), key=lambda s: s.name)
    ]
    return actions + entities


async def forecast_entry_options(
    hass: HomeAssistant,
) -> list[selector.SelectOptionDict]:
    """The config entries that can tell a solar forecast.

    Any integration with an energy platform can: Forecast.Solar, Solcast, Open
    Meteo Solar Forecast and others. They are read through it, so none of them
    is special here.
    """
    options: list[selector.SelectOptionDict] = []
    for entry in hass.config_entries.async_entries():
        if entry.domain == DOMAIN:
            continue
        try:
            integration = await async_get_integration(hass, entry.domain)
        except IntegrationNotFound:
            continue
        if integration.platforms_exists(["energy"]):
            label = (
                f"{entry.title} ({integration.name})"
                if entry.title != integration.name
                else entry.title
            )
            options.append(selector.SelectOptionDict(value=entry.entry_id, label=label))
    return options


################################################################################
# Flows
################################################################################


class SolarSurplusConfigFlow(ConfigFlow, domain=DOMAIN):
    """Set up the house."""

    VERSION = 1

    async def async_step_user(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """The meters and the forecast."""
        if user_input is not None:
            return self.async_create_entry(title=TITLE, data=_prune(user_input))
        options = await forecast_entry_options(self.hass)
        return self.async_show_form(step_id="user", data_schema=hub_schema({}, options))

    @classmethod
    @callback
    def async_get_supported_subentry_types(
        cls, config_entry: ConfigEntry
    ) -> dict[str, type[ConfigSubentryFlow]]:
        return {SUBENTRY_TYPE_CONSUMER: ConsumerSubentryFlow}

    @staticmethod
    @callback
    def async_get_options_flow(config_entry: ConfigEntry) -> OptionsFlow:
        return SolarSurplusOptionsFlow()


class SolarSurplusOptionsFlow(OptionsFlow):
    """Change the meters or test mode after setup."""

    async def async_step_init(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        return self.async_show_menu(
            step_id="init", menu_options=["inputs", "test_mode"]
        )

    def _values(self) -> dict[str, Any]:
        return {**self.config_entry.data, **self.config_entry.options}

    def _save(
        self, user_input: dict[str, Any], keys: tuple[str, ...]
    ) -> ConfigFlowResult:
        options = {
            key: value
            for key, value in self.config_entry.options.items()
            if key not in keys
        }
        options.update(_prune(user_input))
        # Setup stored these in the data, and options are laid over it. Left
        # there, a field cleared here would show the setup value through.
        data = {
            key: value
            for key, value in self.config_entry.data.items()
            if key not in keys
        }
        # One update, so the entry reloads once; creating the entry below then
        # finds the options already in place.
        self.hass.config_entries.async_update_entry(
            self.config_entry, data=data, options=options
        )
        return self.async_create_entry(data=options)

    async def async_step_inputs(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """The meters and the forecast."""
        if user_input is not None:
            return self._save(user_input, HUB_KEYS)
        options = await forecast_entry_options(self.hass)
        return self.async_show_form(
            step_id="inputs", data_schema=hub_schema(self._values(), options)
        )

    async def async_step_test_mode(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Where test mode sends its notifications."""
        if user_input is not None:
            return self._save(user_input, (CONF_NOTIFY_TARGET,))
        return self.async_show_form(
            step_id="test_mode",
            data_schema=notify_schema(self._values(), notify_options(self.hass)),
        )


class ConsumerSubentryFlow(ConfigSubentryFlow):
    """Add or change one consumer."""

    _adapter: AdapterType
    _reconfiguring = False

    async def async_step_user(
        self, user_input: dict[str, Any] | None = None
    ) -> SubentryFlowResult:
        """Choose how the consumer is switched."""
        if user_input is not None:
            self._adapter = AdapterType(user_input[CONF_ADAPTER])
            return await self._async_step_adapter(None)
        return self.async_show_form(step_id="user", data_schema=adapter_schema())

    async def async_step_reconfigure(
        self, user_input: dict[str, Any] | None = None
    ) -> SubentryFlowResult:
        """Change a consumer, keeping how it is switched."""
        subentry = self._get_reconfigure_subentry()
        self._adapter = AdapterType(subentry.data[CONF_ADAPTER])
        self._reconfiguring = True
        return await self._async_step_adapter(None)

    async def async_step_switch(
        self, user_input: dict[str, Any] | None = None
    ) -> SubentryFlowResult:
        return await self._async_step_adapter(user_input)

    async def async_step_number(
        self, user_input: dict[str, Any] | None = None
    ) -> SubentryFlowResult:
        return await self._async_step_adapter(user_input)

    async def async_step_sg_ready(
        self, user_input: dict[str, Any] | None = None
    ) -> SubentryFlowResult:
        return await self._async_step_adapter(user_input)

    async def async_step_script(
        self, user_input: dict[str, Any] | None = None
    ) -> SubentryFlowResult:
        return await self._async_step_adapter(user_input)

    async def async_step_deferrable(
        self, user_input: dict[str, Any] | None = None
    ) -> SubentryFlowResult:
        return await self._async_step_adapter(user_input)

    async def async_step_signal(
        self, user_input: dict[str, Any] | None = None
    ) -> SubentryFlowResult:
        return await self._async_step_adapter(user_input)

    async def _async_step_adapter(
        self, user_input: dict[str, Any] | None
    ) -> SubentryFlowResult:
        schema = CONSUMER_SCHEMAS[self._adapter]
        step_id = self._adapter.value
        if user_input is None:
            values = (
                dict(self._get_reconfigure_subentry().data)
                if self._reconfiguring
                else {}
            )
            return self.async_show_form(step_id=step_id, data_schema=schema(values))

        data = {**_prune(user_input), CONF_ADAPTER: self._adapter.value}
        if errors := self._validate(data):
            return self.async_show_form(
                step_id=step_id, data_schema=schema(data), errors=errors
            )
        if self._reconfiguring:
            return self.async_update_and_abort(
                self._get_entry(),
                self._get_reconfigure_subentry(),
                title=data[CONF_NAME],
                data=data,
            )
        return self.async_create_entry(title=data[CONF_NAME], data=data)

    def _validate(self, data: dict[str, Any]) -> dict[str, str]:
        errors: dict[str, str] = {}
        excluding = (
            self._get_reconfigure_subentry().subentry_id
            if self._reconfiguring
            else None
        )
        taken = {
            subentry.data.get(key)
            for subentry_id, subentry in self._get_entry().subentries.items()
            if subentry_id != excluding
            for key in CONTROLLED_KEYS
        } - {None}
        for key in CONTROLLED_KEYS:
            if data.get(key) in taken:
                errors[key] = "already_controlled"
        if data.get(CONF_SG_CONTACT_1) and data.get(CONF_SG_CONTACT_1) == data.get(
            CONF_SG_CONTACT_2
        ):
            errors[CONF_SG_CONTACT_2] = "same_contact"
        if data.get(CONF_MIN_POWER, 0) > data[CONF_POWER]:
            errors[CONF_MIN_POWER] = "min_above_power"
        return errors
