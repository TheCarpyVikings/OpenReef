"""The frozen entity-binding contract, machine-checked for the first time.

The panel's auto-bind discovers a doser by entity-id suffixes; the suffix table
lives in three places that historically drifted apart until nothing could bind:
the panel's DOSER_BINDING_SUFFIXES, const.py's DOSING_BINDING_ROLES, and the
design doc's §6 table (docs/manual/kalk-doser-esphome-design.md). These tests
pin all three to each other and to reality (real HA domains only — the rev-1
contract shipped a `text_sensor.` domain that does not exist in HA).

Run standalone:  python3 tests/test_entity_contract.py
Or with pytest:  pytest tests/
"""

from __future__ import annotations

import os
import re
import sys

_HERE = os.path.dirname(os.path.abspath(__file__))
_ROOT = os.path.dirname(_HERE)

sys.path.insert(0, _HERE)
import _ha_stubs  # noqa: E402

_ha_stubs.install()

sys.path.insert(0, os.path.join(_ROOT, "custom_components"))
from openreef.const import DOSING_BINDING_ROLES  # noqa: E402

_PANEL = os.path.join(_ROOT, "custom_components", "openreef", "frontend", "openreef-panel.js")
_DOC = os.path.join(_ROOT, "docs", "manual", "kalk-doser-esphome-design.md")
_REF_YAML = os.path.join(_ROOT, "docs", "manual", "awc-esphome-reference.yaml")

# Domains that exist in Home Assistant for ESPHome-created entities. There is
# deliberately no "text_sensor" here: ESPHome text sensors register as sensor.
_REAL_DOMAINS = {"sensor", "binary_sensor", "number", "switch", "button"}


def _panel_suffix_map() -> dict[str, str]:
    src = open(_PANEL, encoding="utf-8").read()
    block = re.search(r"DOSER_BINDING_SUFFIXES\(\)\s*\{\s*return\s*\{(.*?)\};", src, re.S)
    assert block, "DOSER_BINDING_SUFFIXES not found in the panel"
    return dict(re.findall(r"(\w+):\s*\"([a-z_]+\.[a-z0-9_]+)\"", block.group(1)))


def _doc_table_rows() -> dict[str, str]:
    src = open(_DOC, encoding="utf-8").read()
    rows = re.findall(r"\|\s*`(\w+)`\s*\|\s*`([a-z_]+)\.<p>(_[a-z0-9_]+)`\s*\|", src)
    return {role: f"{domain}.{suffix}" for role, domain, suffix in rows}


def test_panel_suffixes_cover_every_backend_role():
    panel = _panel_suffix_map()
    assert set(panel) == set(DOSING_BINDING_ROLES), (
        f"panel-vs-const drift: only-panel={set(panel) - set(DOSING_BINDING_ROLES)}, "
        f"only-const={set(DOSING_BINDING_ROLES) - set(panel)}"
    )


def test_panel_suffix_domains_are_real_ha_domains():
    for role, pattern in _panel_suffix_map().items():
        domain = pattern.split(".", 1)[0]
        assert domain in _REAL_DOMAINS, (
            f"{role}: '{domain}.' is not a real HA domain — the rev-1 text_sensor bug class"
        )


def test_doc_table_matches_the_panel_exactly():
    panel = _panel_suffix_map()
    doc = _doc_table_rows()
    assert set(doc) == set(panel), (
        f"doc-vs-panel drift: only-doc={set(doc) - set(panel)}, only-panel={set(panel) - set(doc)}"
    )
    mismatches = {role: (doc[role], panel[role]) for role in doc if doc[role] != panel[role]}
    assert not mismatches, f"suffix mismatches (doc, panel): {mismatches}"


def test_reference_yaml_keeps_the_friendly_name_contract():
    # Contract rev 2: without friendly_name a verbatim build yields prefix-less
    # ids; the reference node must set it (auto-bind's suffix scan depends on it).
    src = open(_REF_YAML, encoding="utf-8").read()
    assert re.search(r"^\s*friendly_name:\s*\S+", src, re.M), (
        "awc-esphome-reference.yaml lost its friendly_name — part of the frozen contract (rev 2)"
    )


def _main() -> int:
    tests = sorted(
        (name, obj) for name, obj in globals().items()
        if name.startswith("test_") and callable(obj)
    )
    passed = 0
    failed = []
    for name, fn in tests:
        try:
            fn()
            passed += 1
            print(f"  PASS  {name}")
        except Exception as exc:  # noqa: BLE001
            failed.append(name)
            print(f"  FAIL  {name}: {type(exc).__name__}: {exc}")
    print(f"\n{passed}/{len(tests)} passed", "" if not failed else f"— FAILED: {', '.join(failed)}")
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(_main())
