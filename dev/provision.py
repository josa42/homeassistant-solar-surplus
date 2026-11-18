"""Set the development instance up: a user, the simulated sun, the energy
dashboard, and Solar Surplus.

Run by `make dev` next to Home Assistant. It waits for it to answer, then goes
through onboarding and the integrations' own config flows over the REST API,
the way the frontend would; the energy dashboard and its history go over the
websocket API. Whatever is already there is left alone, so it is safe to run
against an instance that was set up before.

Solar Surplus is given none of the meters: it reads them from the energy
dashboard. Fourteen days of a made-up house go into the dashboard's
statistics, so the base load is learned from the start.
"""

from __future__ import annotations

import asyncio
import json
import math
import random
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from datetime import UTC, datetime, timedelta
from zoneinfo import ZoneInfo

import aiohttp

BASE = "http://127.0.0.1:8123"
CLIENT = BASE + "/"
USER = {"name": "Dev", "username": "dev", "password": "dev", "language": "en"}

WEBSOCKET = "ws://127.0.0.1:8123/api/websocket"
#: The meters of the energy dashboard, as the configuration makes them.
SOLAR_ENERGY = "sensor.dev_solar_energy"
GRID_IMPORT = "sensor.dev_grid_import_energy"
GRID_EXPORT = "sensor.dev_grid_export_energy"
BATTERY_OUT = "sensor.dev_battery_discharge_energy"
BATTERY_IN = "sensor.dev_battery_charge_energy"
BATTERY_CAPACITY = 10
HISTORY_DAYS = 14
#: As configuration.yaml has it.
ZONE = ZoneInfo("Europe/Berlin")

TIMINGS = {"min_on_time": 1, "min_off_time": 1, "on_delay": 10, "off_delay": 30}
CONSUMERS = [
    (
        "switch",
        {
            "name": "Heating rod",
            "power": 2000,
            "switch_entity": "input_boolean.dev_heating_rod",
            **TIMINGS,
        },
    ),
    (
        "sg_ready",
        {
            "name": "Heat pump",
            "power": 1200,
            "sg_contact_1": "input_boolean.dev_sg_ready_a",
            "sg_contact_2": "input_boolean.dev_sg_ready_b",
            "sg_forced_power": 1500,
            "sg_lock": False,
            **TIMINGS,
        },
    ),
    (
        "signal",
        {
            "name": "Climate control",
            "power": 600,
            "power_sensor": "sensor.dev_climate_power",
            "sg_forced_power": 1500,
            "sg_lock": False,
            **TIMINGS,
        },
    ),
    (
        "number",
        {
            "name": "Wallbox",
            "power": 3000,
            "number_entity": "input_number.dev_wallbox_current",
            "min_power": 1000,
            "power_step": 100,
            "watts_per_unit": 1,
            **TIMINGS,
        },
    ),
    (
        "deferrable",
        {
            "name": "Washer",
            "power": 500,
            "ready_entity": "input_boolean.dev_washer_ready",
            "start_entity": "input_boolean.dev_washer_plug",
            "deadline_time": "18:00:00",
            "run_time": 90,
            "finish_power": 5,
            "finish_delay": 5,
            "turn_off_when_done": True,
            "wait_for_best": True,
            "on_delay": 10,
        },
    ),
]


def request(method, path, body=None, token=None, form=False):
    headers = {}
    data = None
    if body is not None:
        if form:
            data = urllib.parse.urlencode(body).encode()
            headers["Content-Type"] = "application/x-www-form-urlencoded"
        else:
            data = json.dumps(body).encode()
            headers["Content-Type"] = "application/json"
    if token:
        headers["Authorization"] = f"Bearer {token}"
    req = urllib.request.Request(BASE + path, data=data, headers=headers, method=method)
    try:
        with urllib.request.urlopen(req, timeout=30) as response:
            text = response.read().decode()
            return json.loads(text) if text else None
    except urllib.error.HTTPError as err:
        raise SystemExit(f"{method} {path}: {err.code} {err.read().decode()}") from err


def wait_for_home_assistant() -> None:
    for _ in range(180):
        try:
            urllib.request.urlopen(BASE + "/manifest.json", timeout=2)
            return
        except OSError:
            time.sleep(1)
    raise SystemExit("Home Assistant did not come up")


def token_for(code: str) -> str:
    tokens = request(
        "POST",
        "/auth/token",
        {"grant_type": "authorization_code", "code": code, "client_id": CLIENT},
        form=True,
    )
    return tokens["access_token"]


def onboard() -> str:
    """Onboard, or log in if that was done before. Returns an access token."""
    try:
        with urllib.request.urlopen(BASE + "/api/onboarding", timeout=10) as response:
            steps = {step["step"]: step["done"] for step in json.load(response)}
    except urllib.error.HTTPError as err:
        if err.code != 404:
            raise
        # Once onboarding is done and Home Assistant restarted, it is gone.
        steps = {"user": True}
    if not steps.get("user"):
        code = request("POST", "/api/onboarding/users", {"client_id": CLIENT, **USER})
        token = token_for(code["auth_code"])
        for step in ("core_config", "analytics"):
            if not steps.get(step):
                request("POST", f"/api/onboarding/{step}", {}, token)
        if not steps.get("integration"):
            request(
                "POST",
                "/api/onboarding/integration",
                {"client_id": CLIENT, "redirect_uri": CLIENT},
                token,
            )
        return token
    flow = request(
        "POST",
        "/auth/login_flow",
        {
            "client_id": CLIENT,
            "handler": ["homeassistant", None],
            "redirect_uri": CLIENT,
        },
    )
    flow = request(
        "POST",
        f"/auth/login_flow/{flow['flow_id']}",
        {
            "username": USER["username"],
            "password": USER["password"],
            "client_id": CLIENT,
        },
    )
    return token_for(flow["result"])


def flow(token, path, handler, *answers):
    result = request("POST", path, {"handler": handler}, token)
    for answer in answers:
        if result.get("type") != "form":
            break
        result = request("POST", f"{path}/{result['flow_id']}", answer, token)
    if result.get("type") != "create_entry":
        raise SystemExit(f"{handler}: {result}")
    return result


def entry_of(token, domain):
    entries = request("GET", "/api/config/config_entries/entry", token=token)
    return next((e for e in entries if e["domain"] == domain), None)


async def websocket(token: str, *messages: dict) -> list:
    """Send messages over the websocket API, one after the other."""
    results = []
    async with (
        aiohttp.ClientSession() as session,
        session.ws_connect(WEBSOCKET) as ws,
    ):
        await ws.receive_json()
        await ws.send_json({"type": "auth", "access_token": token})
        if (await ws.receive_json())["type"] != "auth_ok":
            raise SystemExit("websocket: not allowed in")
        for number, message in enumerate(messages, start=1):
            await ws.send_json({"id": number, **message})
            reply = await ws.receive_json()
            if not reply.get("success"):
                raise SystemExit(f"{message['type']}: {reply.get('error')}")
            results.append(reply.get("result"))
    return results


def energy_preferences(forecast_entry: str) -> dict:
    """The energy dashboard over the dev meters."""
    return {
        "energy_sources": [
            {
                "type": "grid",
                "stat_energy_from": GRID_IMPORT,
                "stat_energy_to": GRID_EXPORT,
                "cost_adjustment_day": 0,
                "power_config": {"stat_rate": "sensor.dev_grid"},
            },
            {
                "type": "solar",
                "stat_energy_from": SOLAR_ENERGY,
                "stat_rate": "sensor.dev_solar_power",
                "config_entry_solar_forecast": [forecast_entry],
            },
            {
                "type": "battery",
                "stat_energy_from": BATTERY_OUT,
                "stat_energy_to": BATTERY_IN,
                "power_config": {"stat_rate": "sensor.dev_battery"},
                "stat_soc": "sensor.dev_battery_soc",
                "capacity": BATTERY_CAPACITY,
            },
        ],
    }


#: What the made-up house draws on its own through the day, in W.
HOUSE = [250, 230, 220, 220, 230, 260, 400, 700, 550, 450, 420, 500,
         900, 650, 450, 420, 450, 600, 1100, 900, 700, 500, 350, 280]  # fmt: skip


def made_up_history(end: datetime) -> dict[str, list[tuple[datetime, float]]]:
    """Hourly energy of a house with the dev array and battery, in kWh.

    Each day has its own clouds and the house its own whims, and the battery
    takes the surplus and covers the rest as far as it goes.
    """
    rng = random.Random(42)
    hours: dict[str, list[tuple[datetime, float]]] = {
        key: []
        for key in (SOLAR_ENERGY, GRID_IMPORT, GRID_EXPORT, BATTERY_OUT, BATTERY_IN)
    }
    charge = BATTERY_CAPACITY * 500.0
    start = end - timedelta(days=HISTORY_DAYS)
    clouds = 0.0
    hour = start
    while hour < end:
        local = hour.astimezone(ZONE)
        if local.hour == 0 or hour == start:
            clouds = rng.choice((0.0, 0.1, 0.3, 0.6, 0.9))
        middle = local.hour + 0.5
        sun = math.sin(math.pi * (middle - 6) / 14) ** 1.5 if 6 < middle < 20 else 0
        solar = 8000 * sun * (1 - 0.8 * clouds)
        house = HOUSE[local.hour] * rng.uniform(0.8, 1.25)
        spare = solar - house
        if spare > 0:
            into = min(spare, 3000, BATTERY_CAPACITY * 1000 - charge)
            out = 0.0
        else:
            into = 0.0
            out = min(-spare, 3000, charge - BATTERY_CAPACITY * 100)
        charge += into - out
        grid = house + into - out - solar
        for key, watts in (
            (SOLAR_ENERGY, solar),
            (GRID_IMPORT, max(grid, 0)),
            (GRID_EXPORT, max(-grid, 0)),
            (BATTERY_OUT, out),
            (BATTERY_IN, into),
        ):
            hours[key].append((hour, round(watts / 1000, 3)))
        hour += timedelta(hours=1)
    return hours


def import_message(statistic_id: str, hours: list[tuple[datetime, float]]) -> dict:
    """Import hourly energy, as a meter that starts at 0 kWh after it.

    The state stays at 0, where the freshly made meter starts, so the
    statistics carry on from the history without a jump.
    """
    total = 0.0
    stats = []
    for start, energy in hours:
        total += energy
        stats.append({"start": start.isoformat(), "state": 0, "sum": round(total, 3)})
    return {
        "type": "recorder/import_statistics",
        "metadata": {
            "mean_type": 0,
            "has_sum": True,
            "name": None,
            "source": "recorder",
            "statistic_id": statistic_id,
            "unit_class": "energy",
            "unit_of_measurement": "kWh",
        },
        "stats": stats,
    }


async def set_up_energy_dashboard(token: str, forecast_entry: str) -> None:
    """The energy dashboard and its made-up past, unless there is one."""
    try:
        (prefs,) = await websocket(token, {"type": "energy/get_prefs"})
    except SystemExit as err:
        # A fresh instance has no preferences at all yet.
        if "not_found" not in str(err):
            raise
        prefs = {}
    if prefs.get("energy_sources"):
        print("The energy dashboard is set up already.")
        return
    # Up to the hour before this one: the recorder makes the statistics of the
    # hours from the start of Home Assistant on itself.
    end = datetime.now(UTC).replace(minute=0, second=0, microsecond=0)
    end -= timedelta(hours=1)
    history = made_up_history(end)
    await websocket(
        token,
        *(import_message(key, hours) for key, hours in history.items()),
        {"type": "energy/save_prefs", **energy_preferences(forecast_entry)},
    )
    # The recorder writes them in its own time; the base load is learned from
    # them as soon as Solar Surplus starts.
    for _ in range(30):
        (rows,) = await websocket(
            token,
            {
                "type": "recorder/statistics_during_period",
                "start_time": (end - timedelta(days=1)).isoformat(),
                "statistic_ids": [SOLAR_ENERGY],
                "period": "hour",
            },
        )
        if rows.get(SOLAR_ENERGY):
            break
        await asyncio.sleep(1)
    print(f"The energy dashboard is set up with {HISTORY_DAYS} days of history.")


def main() -> None:
    wait_for_home_assistant()
    token = onboard()

    sun = entry_of(token, "dev_solar")
    if sun is None:
        flow(token, "/api/config/config_entries/flow", "dev_solar")
        sun = entry_of(token, "dev_solar")
    asyncio.run(set_up_energy_dashboard(token, sun["entry_id"]))

    if entry_of(token, "solar_surplus") is not None:
        print("Solar Surplus is set up already.")
        return
    # The meters and the forecast come from the energy dashboard.
    hub = flow(
        token,
        "/api/config/config_entries/flow",
        "solar_surplus",
        {"reserve": 100, "base_load": 400},
    )
    entry_id = hub["result"]["entry_id"]
    for adapter, data in CONSUMERS:
        flow(
            token,
            "/api/config/config_entries/subentries/flow",
            [entry_id, "consumer"],
            {"adapter": adapter},
            data,
        )
    print(f"Solar Surplus is set up with {len(CONSUMERS)} consumers.")


if __name__ == "__main__":
    try:
        main()
    except SystemExit as err:
        print(f"Provisioning failed: {err}", file=sys.stderr)
        raise
