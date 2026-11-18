"""Set the development instance up: a user, the simulated sun, Solar Surplus.

Run by `make dev` next to Home Assistant. It waits for it to answer, then goes
through onboarding and the integrations' own config flows over the REST API,
the way the frontend would. Whatever is already there is left alone, so it is
safe to run against an instance that was set up before.
"""

from __future__ import annotations

import json
import sys
import time
import urllib.error
import urllib.parse
import urllib.request

BASE = "http://127.0.0.1:8123"
CLIENT = BASE + "/"
USER = {"name": "Dev", "username": "dev", "password": "dev", "language": "en"}

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


def main() -> None:
    wait_for_home_assistant()
    token = onboard()

    sun = entry_of(token, "dev_solar")
    if sun is None:
        flow(token, "/api/config/config_entries/flow", "dev_solar")
        sun = entry_of(token, "dev_solar")

    if entry_of(token, "solar_surplus") is not None:
        print("Solar Surplus is set up already.")
        return
    hub = flow(
        token,
        "/api/config/config_entries/flow",
        "solar_surplus",
        {
            "grid_power": "sensor.dev_grid",
            "grid_export_positive": False,
            "battery_power": "sensor.dev_battery",
            "battery_discharge_positive": True,
            "battery_soc": "sensor.dev_battery_soc",
            "battery_capacity": 10,
            "forecast_entries": [sun["entry_id"]],
            "reserve": 100,
            "base_load": 400,
        },
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
