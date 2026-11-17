"""The translation files have to agree with each other and with the code.

A missing key does not fail anywhere at runtime: Home Assistant shows the key
itself, so a form quietly turns into a list of identifiers.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest

from custom_components.solar_surplus.config_flow import (
    CONSUMER_SCHEMAS,
    adapter_schema,
    hub_schema,
    signal_schema,
)
from custom_components.solar_surplus.const import AdapterType

BASE = Path("custom_components/solar_surplus")
LANGUAGES = ("en", "de")
FORECAST_OPTIONS = [{"value": "entry", "label": "Forecast"}]


def load(name: str) -> dict[str, Any]:
    return json.loads((BASE / name).read_text(encoding="utf-8"))


def keys(value: Any, prefix: str = "") -> set[str]:
    if not isinstance(value, dict):
        return {prefix}
    found: set[str] = set()
    for key, child in value.items():
        found |= keys(child, f"{prefix}.{key}" if prefix else key)
    return found


def test_strings_and_english_are_the_same() -> None:
    assert load("strings.json") == load("translations/en.json")


@pytest.mark.parametrize("language", LANGUAGES)
def test_every_language_has_every_key(language: str) -> None:
    assert keys(load(f"translations/{language}.json")) == keys(load("strings.json"))


@pytest.mark.parametrize("language", LANGUAGES)
def test_nothing_is_left_untranslated(language: str) -> None:
    def walk(value: Any, path: str) -> None:
        if isinstance(value, dict):
            for key, child in value.items():
                walk(child, f"{path}.{key}")
        else:
            assert isinstance(value, str) and value.strip(), f"{path} is empty"

    walk(load(f"translations/{language}.json"), language)


@pytest.mark.parametrize("language", LANGUAGES)
def test_every_adapter_can_be_chosen(language: str) -> None:
    options = load(f"translations/{language}.json")["selector"]["adapter"]["options"]
    assert set(options) == {adapter.value for adapter in AdapterType}


def schema_keys(schema: Any) -> set[str]:
    """Every field name a form will ask for."""
    return {str(marker) for marker in schema.schema}


@pytest.mark.parametrize("language", LANGUAGES)
def test_every_form_field_has_a_label(language: str) -> None:
    data = load(f"translations/{language}.json")
    subentry_steps = data["config_subentries"]["consumer"]["step"]
    forms = [
        (hub_schema({}, FORECAST_OPTIONS), data["config"]["step"]["user"]["data"]),
        (hub_schema({}, FORECAST_OPTIONS), data["options"]["step"]["inputs"]["data"]),
        (signal_schema({}), data["options"]["step"]["energy_signal"]["data"]),
        (adapter_schema(), subentry_steps["user"]["data"]),
    ]
    forms += [
        (schema({}), subentry_steps[adapter.value]["data"])
        for adapter, schema in CONSUMER_SCHEMAS.items()
    ]
    for schema, labels in forms:
        missing = schema_keys(schema) - set(labels)
        assert not missing, f"no label for {sorted(missing)}"
