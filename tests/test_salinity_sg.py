"""Salinity specific-gravity (SG) support.

Reefers who measure salinity with a hydrometer (e.g. Tropic Marin) read specific
gravity, not ppt. Salinity is ALWAYS stored canonically in ppt so reef-score,
dosing and AWC keep working; SG is an input/display convenience. These tests pin
the two guarantees that protect that:

  1. the SG<->ppt conversion math (const helpers), and
  2. `_normalise_core_config` canonicalising SG -> ppt for every save path
     (panel save, CSV import, and the `record_manual_reading` service), keeping
     the "SG" display hint and staying IDEMPOTENT (never double-converting).

Run standalone (no pytest needed):   python3 tests/test_salinity_sg.py
Or with pytest if installed:          pytest tests/
"""

from __future__ import annotations

import os
import sys
from types import SimpleNamespace

_HERE = os.path.dirname(os.path.abspath(__file__))
_ROOT = os.path.dirname(_HERE)

sys.path.insert(0, _HERE)
import _ha_stubs  # noqa: E402

_ha_stubs.install()

sys.path.insert(0, os.path.join(_ROOT, "custom_components"))
import openreef as integration  # noqa: E402  (runs __init__.py with stubs installed)
from _fake_ha import FakeEntry, FakeHass, run  # noqa: E402

const = integration.const
normalise = integration._normalise_core_config
CONF_SETTINGS = integration.CONF_SETTINGS

TS = "2026-06-01T19:30:00Z"


def _approx(a: float, b: float, tol: float = 1e-6) -> bool:
    return abs(float(a) - float(b)) <= tol


def _salinity(out: dict) -> list[dict]:
    return out["manualReadings"]["salinity"]


# --- conversion math --------------------------------------------------------- #

def test_anchor_point_35ppt_is_1_0264_sg():
    assert _approx(const.salinity_sg_to_ppt(1.0264), 35.0, tol=1e-3)
    assert _approx(const.salinity_ppt_to_sg(35.0), 1.0264, tol=1e-4)


def test_conversion_matches_hobby_table():
    # Widely published reef SG table points (25 C reference).
    assert _approx(const.salinity_sg_to_ppt(1.025), 33.14, tol=0.05)
    assert _approx(const.salinity_sg_to_ppt(1.020), 26.52, tol=0.05)


def test_conversion_round_trips():
    for sg in (1.0150, 1.0210, 1.0264, 1.0270):
        assert _approx(const.salinity_ppt_to_sg(const.salinity_sg_to_ppt(sg)), sg, tol=1e-9)


def test_looks_like_sg_discriminates_by_magnitude():
    assert const.salinity_value_looks_like_sg(1.0264) is True
    assert const.salinity_value_looks_like_sg(1.000) is True
    assert const.salinity_value_looks_like_sg(35.0) is False
    assert const.salinity_value_looks_like_sg(26.5) is False
    assert const.salinity_value_looks_like_sg("nonsense") is False


# --- normalise: the backend-authoritative chokepoint ------------------------- #

def test_normalise_canonicalises_explicit_sg_unit():
    out = normalise({"manualReadings": {"salinity": [
        {"id": "a", "timestamp": TS, "value": 1.0264, "unit": "SG", "source": "Tropic Marin"},
    ]}})
    row = _salinity(out)[0]
    assert _approx(row["value"], 35.0, tol=1e-3)   # stored as ppt
    assert row["unit"] == "ppt"                      # canonical unit
    assert row["displayUnit"] == "SG"                # hint preserved for the panel
    assert row["source"] == "Tropic Marin"


def test_normalise_canonicalises_via_displayunit_field():
    # Panel sends the SG hint even if it already labelled the unit, magnitude SG.
    out = normalise({"manualReadings": {"salinity": [
        {"id": "b", "timestamp": TS, "value": 1.025, "unit": "ppt", "displayUnit": "SG"},
    ]}})
    row = _salinity(out)[0]
    assert _approx(row["value"], 33.14, tol=0.05)
    assert row["unit"] == "ppt"
    assert row["displayUnit"] == "SG"


def test_normalise_autocorrects_sg_magnitude_mislabelled_as_ppt():
    # Value sits in SG magnitude but the unit column wrongly says ppt: a reef tank
    # is never ~1 ppt, so treat it as SG rather than poisoning the canonical value.
    out = normalise({"manualReadings": {"salinity": [
        {"id": "c", "timestamp": TS, "value": 1.0264, "unit": "ppt"},
    ]}})
    row = _salinity(out)[0]
    assert _approx(row["value"], 35.0, tol=1e-3)
    assert row["displayUnit"] == "SG"


def test_normalise_preserves_already_canonical_ppt_with_sg_hint():
    # value is already ppt (panel converted before save) but tagged SG: keep the
    # hint, do NOT reconvert.
    out = normalise({"manualReadings": {"salinity": [
        {"id": "d", "timestamp": TS, "value": 35.0, "unit": "ppt", "displayUnit": "SG"},
    ]}})
    row = _salinity(out)[0]
    assert _approx(row["value"], 35.0, tol=1e-9)
    assert row["displayUnit"] == "SG"


def test_normalise_is_idempotent_for_sg():
    config = {"manualReadings": {"salinity": [
        {"id": "e", "timestamp": TS, "value": 1.0264, "unit": "SG"},
    ]}}
    once = normalise(config)
    twice = normalise(once)
    r1, r2 = _salinity(once)[0], _salinity(twice)[0]
    assert _approx(r1["value"], 35.0, tol=1e-3)
    assert _approx(r1["value"], r2["value"], tol=1e-9)   # second pass does not move it
    assert r2["displayUnit"] == "SG"


def test_normalise_leaves_plain_ppt_untouched():
    out = normalise({"manualReadings": {"salinity": [
        {"id": "f", "timestamp": TS, "value": 34.5, "unit": "ppt"},
    ]}})
    row = _salinity(out)[0]
    assert _approx(row["value"], 34.5, tol=1e-9)
    assert row["unit"] == "ppt"
    assert "displayUnit" not in row     # no SG hint for a normal ppt reading


def test_normalise_does_not_touch_other_parameters():
    # A calcium value that happens to be small must never be SG-converted.
    out = normalise({"manualReadings": {"alkalinity": [
        {"id": "g", "timestamp": TS, "value": 8.2, "unit": "dKH"},
    ]}})
    row = out["manualReadings"]["alkalinity"][0]
    assert _approx(row["value"], 8.2, tol=1e-9)
    assert "displayUnit" not in row


# --- service path: record_manual_reading canonicalises via the same chokepoint - #

def _entry_with_salinity():
    return FakeEntry(options={CONF_SETTINGS: {}})


def test_record_manual_reading_service_canonicalises_sg():
    entry = _entry_with_salinity()
    hass = FakeHass(entries=[entry])
    call = SimpleNamespace(data={
        "parameter": "salinity",
        "value": 1.0264,
        "unit": "SG",
        "timestamp": TS,
        "source": "Tropic Marin",
    })
    run(integration._handle_record_manual_reading(hass, call))
    saved = entry.options[CONF_SETTINGS]["manualReadings"]["salinity"]
    assert len(saved) == 1
    assert _approx(saved[0]["value"], 35.0, tol=1e-3)
    assert saved[0]["unit"] == "ppt"
    assert saved[0]["displayUnit"] == "SG"


# --- tiny standalone runner (so this works without pytest installed) --------- #

def _main() -> int:
    tests = sorted(
        (name, obj)
        for name, obj in globals().items()
        if name.startswith("test_") and callable(obj)
    )
    passed = 0
    failed = []
    for name, fn in tests:
        try:
            fn()
            passed += 1
            print(f"  PASS  {name}")
        except Exception as exc:  # noqa: BLE001 - report everything
            failed.append(name)
            print(f"  FAIL  {name}: {type(exc).__name__}: {exc}")
    print(f"\n{passed}/{len(tests)} passed", "" if not failed else f"— FAILED: {', '.join(failed)}")
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(_main())
