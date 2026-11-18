# Changelog

## Unreleased

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
