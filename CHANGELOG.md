# Changelog

## Unreleased

### Added

- **Plan**: with a forecast, the allocation is carried out for each forecast
  period ahead. The panel shows under the forecast when each consumer is
  expected to run, and the status sensors carry `expected_on` and
  `expected_off`.
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
