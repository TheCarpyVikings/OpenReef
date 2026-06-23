"""ICP test importer — unit tests for the pure normalisation/flag/fan-out/drift
logic (custom_components/openreef/icp.py) and the two websocket handlers.

icp.py is pure stdlib so it tests cleanly. The websocket handlers are exercised
with the fake-HA harness; we stub the heavy _async_save_config scheduling machinery
(covered elsewhere) with a minimal normalise-and-persist seam so the tests isolate
the handler's real job: validate → store → fan out / delete.

Run standalone:  python3 tests/test_icp.py
"""

from __future__ import annotations

import os
import sys

_HERE = os.path.dirname(os.path.abspath(__file__))
_ROOT = os.path.dirname(_HERE)

sys.path.insert(0, _HERE)
import _ha_stubs  # noqa: E402

_ha_stubs.install()

sys.path.insert(0, os.path.join(_ROOT, "custom_components"))
import openreef as integration  # noqa: E402
from openreef import icp  # noqa: E402
from openreef.const import (  # noqa: E402
    ICP_CORE_PARAM_MAP,
    ICP_ELEMENTS,
    ICP_REPORTS_MAX,
    MVP_SENSORS,
)

from _fake_ha import FakeConnection, FakeEntry, FakeHass, run  # noqa: E402

CONF_SETTINGS = integration.CONF_SETTINGS
normalise = integration._normalise_core_config


# --- fixtures ---------------------------------------------------------------- #

def _triton_raw(report_id="icp:triton:20260601", sample_date="2026-06-01T00:00:00Z", sample_type="tank"):
    """A representative client-parsed Triton report (pre-backend-normalisation)."""
    return {
        "id": report_id,
        "lab": "Triton",
        "adapter": "triton_csv",
        "method": "ICP-OES",
        "sampleType": sample_type,
        "sampleDate": sample_date,
        "testId": "TR-123456",
        "source": {"fileName": "triton.csv"},
        "elements": [
            {"symbol": "Ca", "rawValue": 410, "rawUnit": "mg/L"},
            {"symbol": "Mg", "rawValue": 1320, "rawUnit": "mg/L"},
            {"symbol": "KH", "rawValue": 7.9, "rawUnit": "dKH"},
            {"symbol": "NO3", "rawValue": 5.2, "rawUnit": "mg/L"},
            {"symbol": "PO4", "rawValue": 0.04, "rawUnit": "mg/L"},
            {"label": "Kupfer", "rawValue": 0.5, "rawUnit": "µg/L"},   # German label → Cu
            {"symbol": "Si", "rawValue": 0.05, "rawUnit": "mg/L"},     # mg/L → ppb (×1000)
            {"symbol": "I", "rawValue": "<0.01", "rawUnit": "mg/L"},   # below detection
        ],
    }


def _ati_raw(report_id="icp:ati:20260610", sample_date="2026-06-10T00:00:00Z", sample_type="tank"):
    """A compact ATI-style report carrying lab display fields and a BDL row."""
    return {
        "id": report_id,
        "lab": "ATI",
        "adapter": "ati_pdf_text",
        "method": "ICP-OES",
        "sampleType": sample_type,
        "sampleDate": sample_date,
        "elements": [
            {"symbol": "Ca", "rawValue": 445, "rawUnit": "mg/l", "labGroup": "Major elements", "labName": "Calcium", "labResult": "445", "labUnit": "mg/l"},
            {"symbol": "Mg", "rawValue": 1403, "rawUnit": "mg/l", "labGroup": "Major elements", "labName": "Magnesium", "labResult": "1403", "labUnit": "mg/l"},
            {"symbol": "PO4", "rawValue": 0.08, "rawUnit": "mg/l", "labGroup": "Nutrients", "labName": "Phosphate", "labResult": "0.08", "labUnit": "mg/l"},
            {"symbol": "Al", "rawValue": 20.26, "rawUnit": "µg/l", "labGroup": "Pollutants", "labName": "Aluminium", "labResult": "20.26", "labUnit": "µg/l"},
            {"symbol": "Ni", "rawValue": "---", "rawUnit": "µg/l", "labGroup": "Minor elements", "labName": "Nickel", "labResult": "---", "labUnit": "µg/l"},
        ],
    }


def _fauna_raw(report_id="icp:fauna:20260620", sample_date="2026-06-20T00:00:00Z", sample_type="tank"):
    """A compact Fauna Marin-style report with mg/l nutrients."""
    return {
        "id": report_id,
        "lab": "Fauna Marin",
        "adapter": "fauna_marin_csv",
        "method": "ICP-OES",
        "sampleType": sample_type,
        "sampleDate": sample_date,
        "elements": [
            {"symbol": "Ca", "rawValue": "420", "rawUnit": "mg/l", "labGroup": "Macro elements", "labName": "Calcium", "labResult": "420", "labUnit": "mg/l"},
            {"symbol": "PO4", "rawValue": "0.095", "rawUnit": "mg/l", "labGroup": "Nutrients", "labName": "Phosphate calculated", "labResult": "0.095", "labUnit": "mg/l"},
            {"symbol": "Si", "rawValue": "0.035", "rawUnit": "mg/l", "labGroup": "Nutrients", "labName": "Silicon", "labResult": "0.035", "labUnit": "mg/l"},
        ],
    }


def _element(report, symbol):
    return next(e for e in report["elements"] if e["symbol"] == symbol)


# --- unit normalisation ------------------------------------------------------ #

def test_unit_conversions_basic():
    assert icp.to_canonical("Ca", 410, "mg/L") == 410      # ppm canonical, mg/L == ppm
    assert icp.to_canonical("Ca", 410, "ppm") == 410
    assert icp.to_canonical("Cu", 5, "µg/L") == 5          # ppb canonical
    assert icp.to_canonical("Cu", 0.005, "mg/L") == 5      # mg/L → ppb ×1000


def test_si_mg_per_litre_does_not_become_1000x():
    # Si is µg/L (ppb) on most labs but mg/L on some — the per-element trap.
    assert icp.to_canonical("Si", 0.05, "mg/L") == 50      # 0.05 mg/L = 50 µg/L
    assert icp.to_canonical("Si", 50, "µg/L") == 50        # already canonical


def test_kh_meq_per_litre_to_dkh():
    assert icp.to_canonical("KH", 2.5, "meq/L") == 7.0     # 2.5 meq/L ≈ 7 dKH
    assert icp.to_canonical("KH", 7.9, "dKH") == 7.9


def test_mojibaked_micro_unit_normalises():
    # Triton's CSV emits "Âµg/l" (UTF-8 µ decoded as Latin-1). It must read as µg/L.
    raw = {"lab": "Triton", "sampleType": "tank", "sampleDate": "2026-06-06", "elements": [
        {"symbol": "Al", "rawValue": 2.0, "rawUnit": "Âµg/l"},      # already ppb → 2.0
        {"symbol": "Si", "rawValue": 0.2, "rawUnit": "Âmg/l"},      # mg/L → ppb ×1000 = 200
    ]}
    by = {e["symbol"]: e for e in icp.normalise_report(raw)["elements"]}
    assert by["Al"]["value"] == 2.0 and by["Al"]["unit"] == "ppb"
    assert by["Si"]["value"] == 200.0


def test_species_not_coerced():
    # P vs PO4 and S vs SO4 are distinct registry entries, never merged.
    assert "P" in ICP_ELEMENTS and "PO4" in ICP_ELEMENTS
    assert "S" in ICP_ELEMENTS and "SO4" in ICP_ELEMENTS
    assert icp.match_symbol("phosphate") == "PO4"
    assert icp.match_symbol("phosphorus") == "P"
    assert ICP_ELEMENTS["P"]["unit"] != ICP_ELEMENTS["PO4"]["unit"]


def test_german_labels_resolve():
    assert icp.match_symbol("Kupfer") == "Cu"
    assert icp.match_symbol("Alkalinität") == "KH"
    assert icp.match_symbol("Calcium (mg/l)") == "Ca"
    assert icp.match_symbol("Molybdän") == "Mo"
    assert icp.match_symbol("totally-not-an-element") is None


# --- value parsing / BDL ----------------------------------------------------- #

def test_below_detection_markers_never_zero():
    assert icp.parse_value("<0.01") == (None, True, 0.01)
    assert icp.parse_value("n.d.") == (None, True, None)
    assert icp.parse_value("n.n.") == (None, True, None)
    assert icp.parse_value("0") == (0.0, False, None)       # a real zero is NOT bdl
    assert icp.parse_value("") == (None, False, None)


def test_dash_runs_are_below_detection():
    # ATI prints "---" for not-detected; treat any run of dashes as bdl, never 0.
    assert icp.parse_value("---") == (None, True, None)
    assert icp.parse_value("--") == (None, True, None)
    assert icp.parse_value("—") == (None, True, None)


def test_lab_status_honoured_else_range_with_bdl_precedence():
    raw = {"lab": "ATI", "sampleType": "tank", "sampleDate": "2026-04-20", "elements": [
        {"symbol": "Zn", "rawValue": 18.33, "rawUnit": "µg/L", "labStatus": "high", "labTarget": "1.96"},
        {"symbol": "Al", "rawValue": 20.26, "rawUnit": "µg/L", "labStatus": "ok"},   # canonical=contaminant
        {"symbol": "Ni", "rawValue": "---", "rawUnit": "µg/L", "labStatus": "low"},  # bdl beats labStatus
        {"symbol": "Ca", "rawValue": 300, "rawUnit": "mg/L", "labStatus": "bogus"},  # invalid → range
    ]}
    by = {e["symbol"]: e for e in icp.normalise_report(raw)["elements"]}
    assert by["Zn"]["status"] == "high" and by["Zn"]["usedRange"] == "lab"
    assert by["Zn"]["target"] == 1.96                       # ideal normalised (µg/L → ppb)
    assert by["Al"]["status"] == "ok"                       # lab verdict honoured over canonical
    assert by["Ni"]["bdl"] is True and by["Ni"]["status"] == "bdl"
    assert by["Ca"]["status"] == "low"                      # invalid labStatus → canonical range


def test_decimal_comma_and_thousands():
    assert icp._to_float("1,23") == 1.23                    # EU decimal
    assert icp._to_float("1.234,56") == 1234.56             # EU thousands + decimal
    assert icp._to_float("1,234.56") == 1234.56             # US thousands + decimal
    assert icp._to_float("11000") == 11000


# --- flagging ---------------------------------------------------------------- #

def test_flag_statuses():
    assert icp.flag_element("major", 300, False, None, {"low": 380, "high": 450}) == "low"
    assert icp.flag_element("major", 470, False, None, {"low": 380, "high": 450}) == "high"
    assert icp.flag_element("major", 410, False, None, {"low": 380, "high": 450}) == "ok"
    assert icp.flag_element("heavy_metal", 50, False, None, {"low": 0, "high": 5}) == "contaminant"
    assert icp.flag_element("heavy_metal", 3, False, None, None) == "contaminant"  # unranged detection
    assert icp.flag_element("trace", 100, False, None, None) == "unknown"          # no range, not metal
    assert icp.flag_element("major", None, True, None, {"low": 1, "high": 2}) == "bdl"


def test_lab_range_overrides_canonical():
    # 470 ppm Ca: above the OpenReef canonical 450 (→ high) but inside a lab's own
    # 400-500 range (→ ok). Lab range wins and usedRange records it.
    raw = {
        "lab": "X", "sampleType": "tank", "sampleDate": "2026-06-01",
        "elements": [{"symbol": "Ca", "rawValue": 470, "rawUnit": "mg/L",
                      "labRange": {"low": 400, "high": 500}}],
    }
    ca = _element(icp.normalise_report(raw), "Ca")
    assert ca["usedRange"] == "lab" and ca["status"] == "ok"

    raw["elements"][0].pop("labRange")
    ca2 = _element(icp.normalise_report(raw), "Ca")
    assert ca2["usedRange"] == "canonical" and ca2["status"] == "high"


def test_triton_lab_display_fields_survive_normalise_and_renormalise():
    raw = _triton_raw()
    raw["elements"].extend([
        {
            "symbol": "La",
            "rawValue": ".00",
            "rawUnit": "µg/l",
            "labGroup": "Unwanted heavy metals",
            "labName": "Lanthanum",
            "labResult": ".00",
            "labUnit": "µg/l",
            "labSetpoint": "0",
        },
        {
            "symbol": "S",
            "rawValue": "925.00",
            "rawUnit": "mg/l",
            "labGroup": "Macro-Elements",
            "labName": "Sulphur",
            "labResult": "925.00",
            "labUnit": "mg/l",
            "labSetpoint": "900",
        },
    ])
    report = icp.normalise_report(raw)
    la = _element(report, "La")
    sulphur = _element(report, "S")

    assert la["category"] == "trace"                       # canonical logic remains intact
    assert la["labGroup"] == "Unwanted heavy metals"        # Triton display grouping survives
    assert la["labResult"] == ".00"
    assert sulphur["name"] == "Sulfur"                      # OpenReef canonical spelling
    assert sulphur["labName"] == "Sulphur"                  # Triton display spelling
    assert sulphur["labSetpoint"] == "900"

    again = icp.normalise_report(report)
    assert _element(again, "La")["labGroup"] == "Unwanted heavy metals"
    assert _element(again, "S")["labName"] == "Sulphur"


def test_ati_lab_display_fields_survive_with_bdl_status():
    raw = {"lab": "ATI", "sampleType": "tank", "sampleDate": "2026-04-20", "elements": [
        {
            "symbol": "Mn",
            "rawValue": "---",
            "rawUnit": "µg/l",
            "labStatus": "low",
            "labGroup": "Minor elements",
            "labName": "Manganese",
            "labResult": "---",
            "labUnit": "µg/l",
            "labSetpoint": "Ideal value: 0.98 µg/l",
            "labStatusLabel": "BELOW NORMAL",
            "labAssessment": "Attention",
        },
    ]}
    mn = _element(icp.normalise_report(raw), "Mn")
    assert mn["status"] == "bdl"                         # canonical BDL is preserved
    assert mn["labStatus"] == "low"                      # ATI verdict survives for display
    assert mn["labGroup"] == "Minor elements"
    assert mn["labResult"] == "---"
    assert mn["labSetpoint"] == "Ideal value: 0.98 µg/l"
    assert mn["labStatusLabel"] == "BELOW NORMAL"
    assert mn["labAssessment"] == "Attention"

    again = icp.normalise_report({"lab": "ATI", "elements": [mn]})
    assert _element(again, "Mn")["labStatusLabel"] == "BELOW NORMAL"


def test_fauna_marin_lab_display_fields_and_mg_l_species_survive():
    raw = {"lab": "Fauna Marin", "adapter": "fauna_marin_csv", "sampleType": "tank", "sampleDate": "2026-06-09", "elements": [
        {"symbol": "Si", "rawValue": "0.035", "rawUnit": "mg/l", "labGroup": "Nutrients", "labName": "Silicon", "labResult": "0.035", "labUnit": "mg/l"},
        {"symbol": "P", "rawValue": "0.0312", "rawUnit": "mg/l", "labGroup": "Nutrients", "labName": "Phosphorus", "labResult": "0.0312", "labUnit": "mg/l"},
        {"symbol": "PO4", "rawValue": "0.0956592", "rawUnit": "mg/l", "labGroup": "Nutrients", "labName": "Phosphate calculated", "labResult": "0.0956592", "labUnit": "mg/l"},
        {"symbol": "I", "rawValue": "0.0902", "rawUnit": "mg/l", "labGroup": "Trace elements", "labName": "Iodine", "labResult": "0.0902", "labUnit": "mg/l"},
    ]}
    report = icp.normalise_report(raw)
    si = _element(report, "Si")
    phosphorus = _element(report, "P")
    phosphate = _element(report, "PO4")
    iodine = _element(report, "I")

    assert si["value"] == 35.0 and si["unit"] == "ppb"
    assert phosphorus["value"] == 31.2 and phosphorus["unit"] == "ppb"
    assert phosphate["value"] == 0.095659 and phosphate["unit"] == "ppm"
    assert iodine["value"] == 90.2 and iodine["unit"] == "ppb"
    assert phosphate["labName"] == "Phosphate calculated"
    assert iodine["labGroup"] == "Trace elements"

    again = icp.normalise_report(report)
    assert _element(again, "PO4")["labResult"] == "0.0956592"


# --- report normalisation ---------------------------------------------------- #

def test_normalise_report_recomputes_status_ignoring_client():
    raw = _triton_raw()
    raw["elements"][0]["status"] = "contaminant"   # client lies about Ca
    report = icp.normalise_report(raw)
    assert _element(report, "Ca")["status"] == "ok"           # recomputed (410 ∈ 380-450)
    assert _element(report, "Cu")["status"] == "ok"           # 0.5 µg/L ≤ 5
    assert _element(report, "Si")["value"] == 50              # normalised mg/L→ppb
    i_el = _element(report, "I")
    assert i_el["bdl"] is True and i_el["value"] is None       # never 0


def test_normalise_report_drops_malformed_and_empty():
    assert icp.normalise_report({"lab": "X", "elements": []}) is None
    assert icp.normalise_report("nonsense") is None
    raw = {"lab": "X", "sampleType": "tank", "sampleDate": "2026-06-01",
           "elements": ["junk", {"no_symbol": 1}, {"symbol": "Ca", "rawValue": 410, "rawUnit": "mg/L"}]}
    report = icp.normalise_report(raw)
    assert len(report["elements"]) == 1 and report["elements"][0]["symbol"] == "Ca"


def test_normalise_report_defaults_sampletype_tank():
    raw = _triton_raw()
    raw.pop("sampleType")
    assert icp.normalise_report(raw)["sampleType"] == "tank"


# --- fan-out ----------------------------------------------------------------- #

def test_core_fanout_shape_units_and_ids():
    report = icp.normalise_report(_triton_raw())
    fan = icp.core_fanout(report)
    assert set(fan) == {"calcium", "magnesium", "alkalinity", "nitrate", "phosphate"}
    cal = fan["calcium"][0]
    assert cal["value"] == 410 and cal["source"] == "ICP:Triton"
    assert cal["id"] == "icp:triton:20260601:calcium"
    # fan-out units must match the MVP sensor units so trends/dosing render right
    assert fan["calcium"][0]["unit"] == MVP_SENSORS["calcium"]["unit"]       # ppm
    assert fan["alkalinity"][0]["unit"] == MVP_SENSORS["alkalinity"]["unit"]  # dKH


def test_rodi_sample_does_not_fan_out():
    report = icp.normalise_report(_triton_raw(sample_type="rodi"))
    assert icp.core_fanout(report) == {}


def test_core_param_symbols_all_in_registry():
    for symbol in ICP_CORE_PARAM_MAP:
        assert symbol in ICP_ELEMENTS, f"{symbol} missing from ICP_ELEMENTS"


# --- drift check ------------------------------------------------------------- #

def test_drift_flags_divergence_and_excludes_icp_source():
    report = icp.normalise_report(_triton_raw())  # KH (alk) = 7.9
    manual = {
        "alkalinity": [
            {"value": 9.0, "timestamp": "2026-05-30T12:00:00Z", "source": "Hanna"},
            {"value": 9.0, "timestamp": "2026-05-28T12:00:00Z", "source": "Hanna"},
            {"value": 6.0, "timestamp": "2026-04-01T12:00:00Z", "source": "Hanna"},   # out of window
            {"value": 7.9, "timestamp": "2026-06-01T00:00:00Z", "source": "ICP:Triton"},  # excluded
        ],
        "calcium": [{"value": 410, "timestamp": "2026-05-30T12:00:00Z", "source": "Trident"}],
    }
    drift = icp.drift_check(report, manual)
    alk = next(d for d in drift if d["parameter"] == "alkalinity")
    assert alk["kitValue"] == 9.0 and alk["icpValue"] == 7.9 and alk["direction"] == "icp_lower"
    # calcium agrees (410 vs 410) → not flagged
    assert not any(d["parameter"] == "calcium" for d in drift)


def test_drift_empty_without_kit_history():
    report = icp.normalise_report(_triton_raw())
    assert icp.drift_check(report, {}) == []


# --- config normalisation ---------------------------------------------------- #

def test_normalise_core_config_caps_icp_reports():
    reports = [_triton_raw(report_id=f"icp:t:{i:03d}") for i in range(ICP_REPORTS_MAX + 12)]
    out = normalise({"icpReports": reports})
    assert len(out["icpReports"]) == ICP_REPORTS_MAX
    assert isinstance(out["icpTemplates"], list)


def test_normalise_core_config_drops_bad_icp():
    out = normalise({"icpReports": "not a list"})
    assert out["icpReports"] == []


def test_normalise_core_config_sanitises_icp_dashboard_filters():
    out = normalise({
        "icpDashboard": {
            "includedLabs": ["ATI", "ATI", "", "Fauna Marin"],
            "range": "bogus",
            "group": "major/minor",
            "symbol": "Mg",
        }
    })
    assert out["icpDashboard"] == {
        "includedLabs": ["ATI", "Fauna Marin"],
        "range": "all",
        "group": "major_minor",
        "symbol": "Mg",
    }


# --- ICP v2 dashboard -------------------------------------------------------- #

def test_dashboard_series_unifies_labs_and_excludes_rodi():
    reports = [
        icp.normalise_report(_triton_raw()),
        icp.normalise_report(_ati_raw()),
        icp.normalise_report(_fauna_raw()),
        icp.normalise_report(_triton_raw(report_id="icp:triton:rodi", sample_type="rodi")),
    ]
    payload = icp.dashboard_payload(
        reports,
        {},
        {"range": "all", "group": "core", "symbol": "Ca"},
        now=icp._parse_dt("2026-06-30T00:00:00Z"),
    )
    assert payload["summary"]["reports"] == 4
    assert payload["summary"]["tankReports"] == 3
    assert payload["summary"]["filteredTankReports"] == 3
    assert payload["selectedSeries"]["symbol"] == "Ca"
    assert [point["lab"] for point in payload["selectedSeries"]["points"]] == [
        "Triton",
        "ATI",
        "Fauna Marin",
    ]
    triton_lab = next(item for item in payload["labs"] if item["lab"] == "Triton")
    assert triton_lab["count"] == 2 and triton_lab["tankCount"] == 1


def test_dashboard_brand_filter_is_dashboard_only_not_fanout():
    triton = icp.normalise_report(_triton_raw())
    ati = icp.normalise_report(_ati_raw())
    payload = icp.dashboard_payload(
        [triton, ati],
        {},
        {"includedLabs": ["ATI"], "range": "all", "group": "core", "symbol": "Ca"},
        now=icp._parse_dt("2026-06-30T00:00:00Z"),
    )
    assert [point["lab"] for point in payload["selectedSeries"]["points"]] == ["ATI"]
    # Dashboard filters do not change the stored report's normal core fan-out.
    fan = icp.core_fanout(triton)
    assert "calcium" in fan and fan["calcium"][0]["source"] == "ICP:Triton"


def test_dashboard_preserves_bdl_details_but_skips_line_points():
    report = icp.normalise_report(_ati_raw())
    payload = icp.dashboard_payload(
        [report],
        {},
        {"range": "all", "group": "all", "symbol": "Ni"},
        now=icp._parse_dt("2026-06-30T00:00:00Z"),
    )
    nickel = payload["selectedSeries"]
    assert nickel["symbol"] == "Ni"
    assert nickel["points"] == []
    assert len(nickel["bdlPoints"]) == 1
    assert nickel["bdlPoints"][0]["labResult"] == "---"


def test_dashboard_keeps_species_and_unit_traps_separate():
    report = icp.normalise_report({
        "lab": "Fauna Marin",
        "sampleType": "tank",
        "sampleDate": "2026-06-20",
        "elements": [
            {"symbol": "P", "rawValue": "0.0312", "rawUnit": "mg/l"},
            {"symbol": "PO4", "rawValue": "0.0956592", "rawUnit": "mg/l"},
            {"symbol": "S", "rawValue": "900", "rawUnit": "mg/l"},
            {"symbol": "SO4", "rawValue": "2700", "rawUnit": "mg/l"},
        ],
    })
    payload = icp.dashboard_payload([report], {}, {"range": "all", "group": "all", "symbol": "P"})
    assert payload["series"]["P"]["points"][0]["value"] == 31.2
    assert payload["series"]["PO4"]["points"][0]["value"] == 0.095659
    assert payload["series"]["S"]["points"][0]["value"] == 900.0
    assert payload["series"]["SO4"]["points"][0]["value"] == 2700.0


def test_dashboard_analysis_cards_are_separate_openreef_interpretations():
    reports = [
        icp.normalise_report(_ati_raw(report_id="icp:ati:1", sample_date="2026-06-01T00:00:00Z")),
        icp.normalise_report(_ati_raw(report_id="icp:ati:2", sample_date="2026-06-20T00:00:00Z")),
    ]
    payload = icp.dashboard_payload(
        reports,
        {},
        {"range": "all", "group": "pollutants", "symbol": "Al"},
        now=icp._parse_dt("2026-06-30T00:00:00Z"),
    )
    assert any(card["kind"] == "contaminant" for card in payload["analysisCards"])
    assert payload["selectedSeries"]["symbol"] == "Al"


# --- websocket handlers ------------------------------------------------------ #
# Stub the heavy save machinery (scheduling, notifications) with a minimal seam
# that still runs the real _normalise_core_config and persists to entry.options.

async def _fake_save(hass, entry, config):
    normalised = integration._normalise_core_config(config)
    entry.options = {**entry.options, CONF_SETTINGS: normalised}
    return normalised


integration._async_save_config = _fake_save


def _import(hass, conn, msg_id, raw):
    run(integration.websocket_import_icp_report(hass, conn, {"id": msg_id, "report": raw}))


def _dashboard(hass, conn, msg_id, settings=None):
    msg = {"id": msg_id}
    if settings is not None:
        msg["settings"] = settings
    integration.websocket_icp_dashboard(hass, conn, msg)


def test_ws_import_persists_and_fans_out():
    entry = FakeEntry(options={CONF_SETTINGS: {}})
    hass = FakeHass(entries=[entry])
    conn = FakeConnection()
    _import(hass, conn, 1, _triton_raw())
    assert not conn.errors, conn.error_codes
    payload = conn.results[0].payload
    assert payload["success"] is True
    saved = entry.options[CONF_SETTINGS]
    assert len(saved["icpReports"]) == 1 and saved["icpReports"][0]["lab"] == "Triton"
    cal = saved["manualReadings"]["calcium"]
    icp_rows = [r for r in cal if r["source"] == "ICP:Triton"]
    assert len(icp_rows) == 1 and icp_rows[0]["value"] == 410
    assert icp_rows[0]["id"].endswith(":calcium")


def test_ws_import_is_idempotent():
    entry = FakeEntry(options={CONF_SETTINGS: {}})
    hass = FakeHass(entries=[entry])
    _import(hass, FakeConnection(), 1, _triton_raw())
    _import(hass, FakeConnection(), 2, _triton_raw())   # same report id again
    saved = entry.options[CONF_SETTINGS]
    assert len(saved["icpReports"]) == 1
    icp_rows = [r for r in saved["manualReadings"]["calcium"] if r["source"].startswith("ICP")]
    assert len(icp_rows) == 1


def test_ws_delete_removes_report_and_fanned_rows():
    entry = FakeEntry(options={CONF_SETTINGS: {}})
    hass = FakeHass(entries=[entry])
    _import(hass, FakeConnection(), 1, _triton_raw())
    conn = FakeConnection()
    run(integration.websocket_delete_icp_report(hass, conn, {"id": 2, "reportId": "icp:triton:20260601"}))
    assert not conn.errors, conn.error_codes
    saved = entry.options[CONF_SETTINGS]
    assert saved["icpReports"] == []
    assert all(not r["source"].startswith("ICP") for r in saved["manualReadings"].get("calcium", []))


def test_ws_import_not_configured():
    conn = FakeConnection()
    _import(FakeHass(entries=[]), conn, 1, _triton_raw())
    assert "not_configured" in conn.error_codes


def test_ws_import_invalid_report_errors():
    entry = FakeEntry(options={CONF_SETTINGS: {}})
    conn = FakeConnection()
    _import(FakeHass(entries=[entry]), conn, 1, {"lab": "X", "elements": []})
    assert "invalid_report" in conn.error_codes


def test_ws_import_preserves_existing_manual_readings():
    existing = {"calcium": [{"id": "kit:1", "timestamp": "2026-05-30T12:00:00Z",
                             "value": 412, "unit": "ppm", "source": "Trident"}]}
    entry = FakeEntry(options={CONF_SETTINGS: {"manualReadings": existing}})
    hass = FakeHass(entries=[entry])
    _import(hass, FakeConnection(), 1, _triton_raw())
    cal = entry.options[CONF_SETTINGS]["manualReadings"]["calcium"]
    sources = {r["source"] for r in cal}
    assert "Trident" in sources and "ICP:Triton" in sources   # kit row not clobbered


def test_ws_reimport_with_corrected_date_moves_report_and_fanned_rows():
    """Editing an imported report's sample date (the panel's "Save date" re-imports
    the same report id with a new date) updates the report in place AND re-stamps the
    fanned core readings to the corrected day — not the original/import date."""
    entry = FakeEntry(options={CONF_SETTINGS: {}})
    hass = FakeHass(entries=[entry])
    _import(hass, FakeConnection(), 1, _triton_raw(sample_date="2026-06-01"))
    saved = entry.options[CONF_SETTINGS]
    assert len(saved["icpReports"]) == 1
    assert saved["icpReports"][0]["sampleDate"] == "2026-06-01"
    cal_before = [r for r in saved["manualReadings"]["calcium"] if r["source"] == "ICP:Triton"]
    assert len(cal_before) == 1 and cal_before[0]["timestamp"] == "2026-06-01"

    # Same report id, corrected date.
    _import(hass, FakeConnection(), 2, _triton_raw(sample_date="2026-05-20"))
    saved = entry.options[CONF_SETTINGS]
    assert len(saved["icpReports"]) == 1                        # replaced, not duplicated
    assert saved["icpReports"][0]["sampleDate"] == "2026-05-20"
    cal_after = [r for r in saved["manualReadings"]["calcium"] if r["source"] == "ICP:Triton"]
    assert len(cal_after) == 1 and cal_after[0]["timestamp"] == "2026-05-20"   # re-fanned to new day


def test_ws_icp_dashboard_returns_filtered_payload():
    entry = FakeEntry(options={CONF_SETTINGS: {"icpReports": [_triton_raw(), _ati_raw()]}})
    hass = FakeHass(entries=[entry])
    conn = FakeConnection()
    _dashboard(hass, conn, 1, {"includedLabs": ["ATI"], "range": "all", "group": "core", "symbol": "Ca"})
    assert not conn.errors, conn.error_codes
    payload = conn.results[0].payload
    assert payload["settings"]["includedLabs"] == ["ATI"]
    assert payload["selectedSeries"]["symbol"] == "Ca"
    assert [point["lab"] for point in payload["selectedSeries"]["points"]] == ["ATI"]


# --- tiny standalone runner -------------------------------------------------- #

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
