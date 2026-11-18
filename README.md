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

[![Open your Home Assistant instance and open a repository inside the Home Assistant Community Store.](https://my.home-assistant.io/badges/hacs_repository.svg)](https://my.home-assistant.io/redirect/hacs_repository/?owner=josa42&repository=homeassistant-solar-surplus&category=integration)

### Requirements

- Home Assistant **2026.9.0** or newer
- A power sensor at the grid connection
- Optional: a battery's power and charge, and a solar forecast from
  [Forecast.Solar](https://www.home-assistant.io/integrations/forecast_solar/),
  [Solcast](https://github.com/BJReplay/ha-solcast-solar) or any other
  integration that feeds the forecast of the energy dashboard

### HACS by hand

The button above does this for you. Without it:

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

The meters and where test mode sends its notifications can be changed later under **Configure**, each consumer under its own **Change this
consumer**.

### The house

| Setting | Default | What it does |
| --- | --- | --- |
| Grid power | | The meter at the grid connection. Positive means drawing from the grid, unless *Grid power is positive when exporting* is on. |
| Battery power | | Optional. Positive means the battery discharges, as in the energy dashboard. Inverters differ: turn off *Battery power is positive when discharging* if yours counts charging as positive. With no sun and nothing drawn from the grid, the battery discharges, and that tells which way the sensor counts. |
| Battery charge | | Optional. The battery's state of charge. |
| Battery first up to | 90 % | Below this charge, what the battery charges with is not handed out. |
| Battery counts as empty at | 20 % | At or below this, drawing from the grid locks SG Ready heat pumps and blocks signals. |
| Battery maximum charge power | | Optional. Known, the part of it the battery does not use yet is held back for it while it is below *Battery first up to*. |
| Blocked from grid import of | 500 W | Drawing this much from the grid with the battery empty, or without one, locks SG Ready heat pumps and blocks signals, if they are allowed to be. |
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
| Signal | nothing: a sensor of its own that another integration follows | a heat pump's climate control |

All but the deferrable kind have the same four timings:

| Setting | Default | What it does |
| --- | --- | --- |
| Minimum on time | 10 min | Once on, it stays on at least this long. |
| Minimum off time | 5 min | Once off, it stays off at least this long. |
| Switch on after | 60 s | Enough surplus has to hold this long before it is switched on. |
| Switch off after | 120 s | Too little surplus has to hold this long before it is switched off. |

A **variable** consumer's power is the most it may take. *Minimum power* is the
least it runs with, *Power step* the steps above that, and *Watts per unit*
converts to the number's own unit: 1 for watts, 230 for amperes on one phase,
690 on three. A number that cannot go to zero, such as a wallbox's charging
current, needs its *Enable switch*: it is what turns the consumer off.

An **SG Ready** heat pump's power is what it draws when recommended. *Forced from
additional* is the surplus beyond that which makes it forced; left empty it is
never forced. *Lock while drawing from the grid* allows the lock (state 1).

A **signal** switches nothing. It is decided like an SG Ready heat pump, and
what it would set is published as `sensor.<consumer>_energy_signal`, for an
integration that reacts to it as the heat pump would, see [Signals](#signals).
Its power is what the consumer following it draws extra when recommended, and
its power sensor what that consumer really draws. It is never blocked unless
*Blocked while drawing from the grid* is turned on: whatever follows it, such as
a heating, may well need to run on the grid.

A **deferrable** consumer has its own settings:

| Setting | Default | What it does |
| --- | --- | --- |
| Ready while | | A `binary_sensor`, `input_boolean` or `switch` that is on while the consumer waits to be started. An `input_boolean` is turned off again once the run is done. |
| Start with | | A switch is turned on, a script, button or scene is run. |
| Done by (entity) | | Optional. A `datetime`, `input_datetime`, `time` or timestamp `sensor`. |
| Done by | 18:00 | The deadline without an entity: the next time of day after it became ready. |
| Run time | 120 min | How long a run takes. The latest start is the deadline minus this. |
| Done below / Done after | 5 W / 5 min | With a power sensor, the run is done once it draws less for this long. |
| Turn off when done | on | Turn a start switch off after the run, so the next start is a fresh one. |
| Start after | 60 s | Enough surplus has to hold this long before it is started. |

Its power should be what it draws on average while it runs: it starts once that
much surplus is there.

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
| `switch.solar_surplus_control` | Off, every decision is still made and shown, but nothing is switched. It keeps its state across a restart. |
| `switch.solar_surplus_test_mode` | On, nothing is switched, and what would be is sent as a notification. See [Test mode](#test-mode). It keeps its state across a restart. |

Each consumer gets a device of its own:

| Entity | What it shows |
| --- | --- |
| `sensor.<consumer>_status` | `off`, `on`, `locked`, `waiting`, `running`, `done`, `idle` (not ready) or `unavailable`. The `reason` attribute says why, the others give the figures behind it: the power `needed`, the surplus `available` at its place in the order, `until` when a delay or minimum time runs out, and for a deferrable consumer its `deadline`, `latest_start` and `expected_start`. |
| `select.<consumer>_mode` | `auto` lets the allocation decide, `on` and `off` put a hand on it. |
| `sensor.<consumer>_energy_signal` | Only for a signal: what it tells, see below. |

### Signals

A signal is a consumer that switches nothing. Its
`sensor.<consumer>_energy_signal` is meant for another integration to follow,
such as the climate control of a heat pump, which heats a little more while
there is surplus. It is an enum sensor after the SG Ready states 1 to 4, with
text states so it is not taken for a measurement:

| State | SG Ready | When |
| --- | --- | --- |
| `blocked` | 1 | The house draws at least *Blocked from grid import of* (500 W), the battery is empty or there is none, and *Blocked while drawing from the grid* is on. Use only what is necessary. |
| `normal` | 2 | Anything else. |
| `recommended` | 3 | Its power fits the surplus left at its place in the order. Extra consumption is welcome. |
| `forced` | 4 | *Forced from additional* fits on top of that. Use whatever you can. |

Each signal sits in the priority order like any consumer, with its own power
and its own timings, so two integrations that follow the surplus each get their
own signal and their own place. What the consumer following it draws counts as
the signal's own, from its power sensor or else its power, so the signal does
not switch itself off once it is followed. Without a grid reading the sensor is
`unavailable` rather than a guess. Test mode does not change it.

### Test mode

To see what Solar Surplus would do before it switches anything, turn on
`switch.solar_surplus_test_mode`, or **Test mode** in the panel. Nothing is
switched then. Instead, each decision is carried out in a simulation of the
house, and what it would have switched comes as a notification:

```
Solar Surplus: Test mode
Heating rod: On (Enough surplus)
Heat pump: Recommended (Enough surplus)
Wallbox: 1300 W (Enough surplus)
```

The simulation goes on from there as if the consumers had been switched: a
consumer turned on stays on, and what it would draw is taken off the grid
reading, so the next consumer does not get the same surplus a second time. The
status sensors and the panel show the simulated house. Switching a consumer by
hand is taken over. A variable consumer is reported when it turns on or off,
not each time its power follows the surplus. A finished deferrable run counts
its ready entity as off until it really goes off. A signal is reported with
what it would tell, and its sensor stays where it is.

Notifications go to the notify action or entity set under **Configure** →
**Test mode**, such as `notify.mobile_app_phone`. Without one, or if it does not
exist, they show up as persistent notifications in the sidebar.

With control off, test mode sends nothing: nothing would be switched. When test
mode is turned off, the real house is read again, and the consumers start their
minimum times afresh.

<br><br>

## Panel

The integration adds **Solar Surplus** to the sidebar. It shows:

- the surplus (smoothed, and what it is right now), the grid, the battery, what
  is handed out and what is left
- the forecast for the next hours as bars, against the line of base load and
  reserve that a forecast hour has to clear before it counts as surplus
- every consumer in priority order, with what it is doing, why, and the figures
  behind it: the surplus it saw at its place, until when a delay or minimum time
  runs, and for a deferrable consumer by when it starts at the latest and by
  when it is done, and for a signal what it tells

Admins can change the order by dragging a row or with its arrows, put a hand on
a consumer (Auto, On, Off), and turn control and test mode on or off. Everyone
else sees the same, read-only.

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
   order goes first, because everything above it was served before it. A
   consumer that waits out its delay to switch on already holds its power, so
   one below it does not take that in the meantime.
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
  least *Blocked from grid import of* with the battery empty, for at most two
  hours at a time and with an hour's pause in between.
- **Signals** are decided the same way, but only publish what they would set.
  They stay blocked for as long as the house draws from the grid.
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

## Not in this version

The allocation is greedy by priority, not an optimizer. There are no electricity
prices or tariffs, no
electric vehicle charging logic beyond a variable consumer (evcc does that
better), and consumers are added and changed on the integration's page, not in
the panel.

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

The development configuration (`config.template.yaml`) fakes a house: set
*Dev solar excess* to what the house would export with every consumer off, and
the *Dev grid* meter follows from it and from what the fake consumers draw
(heating rod 2000 W, heat pump 1200 W recommended and 2700 W forced, the wallbox
what it is set to, the washer 500 W). Add consumers with those entities and
powers to watch the allocation work.

Without Docker, the same instance runs from the test virtual environment:
link `config/custom_components` to `../custom_components` and start
`venv/bin/hass -c config`.

<br><br>

## License

MIT, see [LICENSE](LICENSE).
