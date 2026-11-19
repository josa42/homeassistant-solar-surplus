# Changelog

## Unreleased

### Added

- **A traffic light for the dashboard says whether now is a good time to use
  power.** `sensor.solar_surplus_traffic_light` is `plenty` from *Traffic light
  green from* (1000 W) of surplus, `low` below that, and `grid` once more
  would come from the grid or the battery. It goes by the surplus before the
  consumers, since a variable consumer gives way to a kettle switched on by
  hand.

### Fixed

- A forecast that leaves the night out, as Forecast.Solar does, is filled in
  with hours of nothing, so the plan and the battery's expected charge go
  through the night instead of jumping to the morning.
- The panel's forecast runs from midnight to midnight also where the forecast
  leaves the night out, and the line of the current time passes behind the
  axis labels and the consumers' names instead of over them.

## 0.3.0 - 2026-11-18

### Added

- **Plan**: with a forecast, the allocation is carried out for each forecast
  period ahead. The panel shows under the forecast when each consumer is
  expected to run, and the status sensors carry `expected_on` and
  `expected_off`.
- The panel's forecast shows a whole day, today by default with a line at the
  current time, and steps through the last seven days and the days the
  forecast covers. Below it, each consumer's track shows what ran, from the
  history, next to what is expected to run, with a legend for the colors.
  With a battery SoC sensor, a line over the bars shows the battery's charge.
- **Battery capacity**: known, the plan follows the battery's charge through
  the forecast, charging it first below its target, and the panel continues the
  line of its charge with what the plan expects.
- **From the energy dashboard**: the grid power, the battery power, charge
  and capacity, and the solar forecast are read from the energy dashboard
  when left empty, and followed when it changes. The grid power is no longer
  required when the dashboard has it.
- The panel's forecast has a power axis, and a charge axis next to the
  battery's line, and shows every consumer, also one that did not run and is
  not expected to.
- **Learned base load**: with grid and solar in the energy dashboard, the plan
  learns the base load for each hour of the day from the past days, less what
  Solar Surplus switched on. The setting counts for hours without enough
  history, and the panel's line follows the hours.
- **Best window** for deferrable consumers: the start where the forecast covers
  most of the run, before the deadline, shown with its expected solar share as
  `recommended_start` and `solar_share`. With *Wait for the best window* on, the
  default, they start from there rather than on the first surplus.

### Changed

- **Signals** are no longer blocked while drawing from the grid unless asked
  to, like SG Ready heat pumps: whatever follows them may need to run anyway.

## 0.2.0 - 2026-11-18

### Added

- **Signals**, a kind of consumer that switches nothing: it is decided like an
  SG Ready heat pump and publishes what it would set as its own energy signal
  sensor, for another integration to follow. Each signal has its own place in
  the priority order, its own power and timings, and counts what follows it as
  its own draw.

### Removed

- **BREAKING:** The hub's energy signal, `sensor.solar_surplus_energy_signal`,
  and its settings under **Configure**. Add a signal consumer instead, and point
  whatever followed the old sensor to the new one. *Blocked from grid import of*
  moved to the house's settings.

### Changed

- **Battery power** is read as positive when discharging by default, as in the
  energy dashboard. Entries set up before keep the direction they were set up
  with.

## 0.1.0 - 2026-11-18

### Added

- **Setup** of the house: the grid power sensor, optionally a battery and a
  solar forecast, and the reserve held back from the surplus.
- **Consumers**, added one by one on the integration's page: switched,
  variable, SG Ready, through scripts, and deferrable.
- **Allocation by priority**: the surplus goes to the consumers in order, with
  delays, minimum on and off times and the reserve as hysteresis so nothing
  flaps. Variable consumers take what is left in steps, SG Ready heat pumps step
  up to forced, and deferrable consumers start on surplus or in time for their
  deadline.
- **Solar forecast** from any integration that feeds the energy dashboard.
- **Entities**: the surplus, the forecast, a status and a mode per consumer, and
  a switch to only show what would be done.
- **Energy signal**, an enum sensor after SG Ready (`blocked`, `normal`,
  `recommended`, `forced`) for other integrations to follow.
- **Panel** in the sidebar: the surplus, the forecast, and every consumer in
  priority order with what it does and why. The order is changed by dragging,
  and each consumer can be put on Auto, On or Off.
- **Diagnostics** with the configuration, the order and the last decision.
- **Test mode**, which switches nothing and sends a notification of what would
  be switched, to a notify action or entity or as a persistent notification.
  The decisions are carried out in a simulation of the house meanwhile.
