# Solar Surplus

[![License](https://img.shields.io/github/license/josa42/homeassistant-solar-surplus?style=flat-square)](LICENSE)
[![HACS Custom](https://img.shields.io/badge/HACS-Custom-41BDF5.svg?style=flat-square)](https://hacs.xyz/)

A Home Assistant integration that hands the power your solar panels produce
beyond what the house uses to the consumers you choose, in the order you choose,
and can always tell you why a consumer is on or off.

> [!NOTE]
> Nothing is released yet.

<br><br>

## Installation

### Requirements

- Home Assistant **2026.9.0** or newer
- A power sensor at the grid connection
- Optional: a battery's power and charge, and a solar forecast from
  [Forecast.Solar](https://www.home-assistant.io/integrations/forecast_solar/),
  [Solcast](https://github.com/BJReplay/ha-solcast-solar) or any other
  integration that feeds the forecast of the energy dashboard

### HACS

1. Open HACS, then **Custom repositories** in the menu
2. Add `https://github.com/josa42/homeassistant-solar-surplus` as an
   **Integration**
3. Install **Solar Surplus** and restart Home Assistant

<br><br>

## Configuration

1. Go to **Settings** → **Devices & Services**
2. Click **+ Add Integration** and search for "Solar Surplus"
3. Choose the grid power sensor, and the battery and forecast if you have them
4. Add each consumer through **Add a consumer** on the integration's page

The meters and the energy signal can be changed later under **Configure**, each
consumer under its own **Change this consumer**.

### The house

| Setting | Default | What it does |
| --- | --- | --- |
| Grid power | | The meter at the grid connection. Positive means drawing from the grid, unless *Grid power is positive when exporting* is on. |
| Battery power | | Optional. Positive means the battery charges, unless *Battery power is positive when discharging* is on. |
| Battery charge | | Optional. The battery's state of charge. |
| Battery first up to | 90 % | Below this charge, what the battery charges with is not handed out. |
| Battery counts as empty at | 20 % | At or below this, drawing from the grid blocks the energy signal. |
| Battery maximum charge power | | Optional. Known, the part of it the battery does not use yet is held back for it while it is below *Battery first up to*. |
| Solar forecast | | Optional. One or more config entries that provide a solar forecast for the energy dashboard. Several are added up. |
| Reserve | 100 W | Held back from the surplus. It is also the hysteresis: a consumer switches on only if this much is still exported afterwards, and off once the house draws from the grid. |
| Base load | 400 W | What the house draws on its own. The expected surplus of an hour is its forecast minus this and the reserve. |

### Consumers

Every consumer has a name, a **power** and optionally a **power sensor**. The
power is what it draws when on: it decides whether the consumer fits, and stands
in for its draw while there is no power sensor. With a sensor, a consumer that
is on counts with what it really draws, which matters for a heating rod whose
thermostat has cut out.

| Kind | Switched through | For |
| --- | --- | --- |
| Switched | a `switch`, `input_boolean` or `light` | a heating rod, a pool pump, a smart plug |
| Variable | a `number` or `input_number`, optionally with an enable switch | a wallbox, a heating rod with a power stage |
| SG Ready | two contacts, as `switch` or `input_boolean` | a heat pump |
| Scripts | a `script`, `button`, `input_button` or `scene` each for on and off, optionally an entity that says whether it is on | an air conditioner, anything with an API |
| Deferrable | a ready entity and a start entity | a washing machine, a dryer, a dishwasher |

All but the deferrable kind have the same four timings:

| Setting | Default | What it does |
| --- | --- | --- |
| Minimum on time | 10 min | Once on, it stays on at least this long. |
| Minimum off time | 5 min | Once off, it stays off at least this long. |
| Switch on after | 60 s | Enough surplus has to hold this long before it is switched on. |
| Switch off after | 120 s | Too little surplus has to hold this long before it is switched off. |

<br><br>

## Entities

The hub's device:

| Entity | What it shows |
| --- | --- |
| `sensor.solar_surplus_surplus` | The surplus that is handed out, after smoothing and the reserve |
| `sensor.solar_surplus_allocated_power` | What the consumers take of it |
| `sensor.solar_surplus_remaining_surplus` | What is left after them |
| `sensor.solar_surplus_forecast_remaining_today` | The solar energy still expected today (only with a forecast) |
| `sensor.solar_surplus_forecast_power` | The solar power the forecast expects right now (only with a forecast) |
| `sensor.solar_surplus_energy_signal` | The energy signal, see below |
| `switch.solar_surplus_control` | Off, every decision is still made and shown, but nothing is switched. It keeps its state across a restart. |

Each consumer gets a device of its own:

| Entity | What it shows |
| --- | --- |
| `sensor.<consumer>_status` | `off`, `on`, `locked`, `waiting`, `running`, `done`, `idle` (not ready) or `unavailable`. The `reason` attribute says why, the others give the figures behind it: the power `needed`, the surplus `available` at its place in the order, `until` when a delay or minimum time runs out, and for a deferrable consumer its `deadline`, `latest_start` and `expected_start`. |
| `select.<consumer>_mode` | `auto` lets the allocation decide, `on` and `off` put a hand on it. |

### Energy signal

`sensor.solar_surplus_energy_signal` is meant for other integrations to follow,
such as a climate controller that heats a little more while there is surplus.
It is an enum sensor after the SG Ready states 1 to 4, with text states so it is
not taken for a measurement:

| State | SG Ready | When |
| --- | --- | --- |
| `blocked` | 1 | The house draws at least *Blocked from grid import of* (500 W) and the battery is empty or there is none. Consumers should use only what is necessary. |
| `normal` | 2 | Anything else. |
| `recommended` | 3 | At least *Recommended from* (500 W) is left. Extra consumption is welcome. |
| `forced` | 4 | At least *Forced from* (2000 W) is left, or the recommended surplus with the battery at *Forced with the battery at* (95 %). Use whatever you can. |

It sits in the priority order like a consumer, last unless it is moved in the
panel: the consumers above it are served before it sees what is left, the ones
below it after. It takes nothing away from them. The draw of the *consumers that
follow the signal*, if their power sensors are given, is added back, so the
signal does not switch itself off when they react to it.

It rises after *Rise after* (120 s) and falls after *Fall after* (300 s), and
holds each state at least *Hold each state at least* (10 min). Whoever follows it
can take it at its word. Without a grid reading it is `unavailable` rather than
a guess.

Attributes: `reason` (`pv_surplus`, `battery_full`, `grid_import`,
`low_battery` or `none`), `since`, and `until` while recommended or forced, when
the forecast expects the surplus to end.

These are set under **Configure** → **Energy signal**.

<br><br>

## How it decides

Every 10 seconds, and whenever a meter or a consumer changes, the integration
runs once through all consumers.

1. **The surplus** is what the house exports, plus what the consumers it
   controls draw right now, since that would be exported if they were off. What
   the battery feeds the house is subtracted. What the battery charges with is
   added once the battery is at *Battery first up to*; below that it is not, and
   if its maximum charge power is known, the part of it the battery does not use
   yet is held back too. The reserve is subtracted last.
2. **Rises are smoothed**, over about 30 seconds, so a gap in the clouds does not
   switch anything on. A fall counts at once.
3. **The consumers are served in priority order.** Each takes the power it needs
   if it fits, and leaves the rest to the ones below it. A consumer that is on
   keeps running until the house draws from the grid; then the one lowest in the
   order goes first, because everything above it was served before it.
4. **Nothing flaps.** A consumer switches on only once enough surplus has held
   for *Switch on after*, and off once too little has held for *Switch off
   after*. Between switching it keeps its minimum on and off times. A consumer
   switched by hand gets them too, so it is not switched back at once.

Each kind adds its own rules:

- **Variable** consumers take all of what is left, between their minimum power
  and their power, in whole steps, and follow the surplus up and down while they
  run. *Watts per unit* converts to the number's own unit, such as 230 for
  amperes on one phase.
- **SG Ready** heat pumps are *recommended* (state 3) when their power fits and
  *forced* (state 4) when the forced threshold fits on top. With *Lock while
  drawing from the grid* on, they are locked (state 1) while the house draws at
  least the energy signal's blocked threshold with the battery empty, for at
  most two hours at a time and with an hour's pause in between.
- **Scripts** run the on or the off entity. Without an entity that says whether
  the consumer is on, it counts as what it was last told.
- **Deferrable** consumers wait until their ready entity is on. Then they start
  as soon as their power fits, and at the latest at the deadline minus their run
  time. Once started they are never stopped. A run is done once the power sensor
  stays below *Done below* for *Done after*, or without a sensor once the run
  time is over. A start switch is then turned off, if asked to, and a ready
  `input_boolean` is turned off as well; while the ready entity stays on, it is
  not started again. The deadline comes from a `datetime`, `input_datetime`,
  `time` or timestamp `sensor`; a time of day is its next occurrence after the
  consumer became ready, and without an entity the configured time is used.
  While a consumer waits, the forecast says when enough surplus is expected.

With a hand on a consumer (*Mode* on or off, or the panel) the allocation leaves
it alone: on is on, off is off, at once. A deferrable consumer set to on starts
now.

The first run after a start only reads: nothing is written until the
integration has seen every consumer once. After a restart every consumer starts
its minimum times afresh, but a deferrable consumer halfway through its run is
remembered.

<br><br>

## Development

```bash
make install    # create the venv and install the test dependencies
make test       # run the tests
make lint       # run ruff
make dev-up     # start a local Home Assistant on http://localhost:8123
make dev-logs   # follow its logs
make dev-down   # stop it
```

`make dev-up` mounts `custom_components/` into the container, so a
`make dev-restart` picks up code changes.

<br><br>

## License

MIT, see [LICENSE](LICENSE).
