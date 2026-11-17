"""The manifest has to agree with the package it describes.

A domain that does not match the directory name loads as a different
integration than every other file assumes, and the failure shows up far from
its cause.
"""

from __future__ import annotations

import json
from pathlib import Path

from custom_components.solar_surplus.const import DOMAIN

PACKAGE = Path("custom_components/solar_surplus")
REPO_URL = "https://github.com/josa42/homeassistant-solar-surplus"


def _manifest() -> dict:
    return json.loads((PACKAGE / "manifest.json").read_text(encoding="utf-8"))


def test_domain_matches_package_directory() -> None:
    assert _manifest()["domain"] == PACKAGE.name == DOMAIN


def test_required_keys_present() -> None:
    manifest = _manifest()
    for key in ("name", "version", "codeowners", "iot_class", "integration_type"):
        assert manifest[key], f"manifest is missing {key}"


def test_links_point_at_this_repository() -> None:
    manifest = _manifest()
    assert manifest["documentation"] == REPO_URL
    assert manifest["issue_tracker"] == f"{REPO_URL}/issues"


def test_keys_are_sorted_the_way_hassfest_expects() -> None:
    keys = list(_manifest())
    assert keys[:2] == ["domain", "name"]
    assert keys[2:] == sorted(keys[2:])
