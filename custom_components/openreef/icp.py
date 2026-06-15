"""ICP test importer — normalisation, flagging, fan-out and drift logic ("the lab brain").

Like :mod:`spawning`, this module is a **pure, dependency-free, side-effect-free**
computation (stdlib only — no Home Assistant, no network). The panel parses a lab
file (CSV/PDF/xlsx) client-side and posts a structured ``report`` dict; everything
that turns that into trustworthy, stored data happens here so a buggy or hostile
client can't poison the readings that feed reef-score and dosing:

  * :func:`normalise_report` — validate/clamp one report, resolve every lab label
    to a canonical element symbol, normalise units **per element** (the only thing
    that defeats the Si/P mg-vs-µg 1000× trap), detect below-detection markers, and
    recompute every status flag authoritatively.
  * :func:`core_fanout` — emit the overlapping core params (Alk/Ca/Mg/NO3/PO4/Sal)
    as ordinary ``manualReadings`` rows tagged ``source="ICP:<lab>"``, so the
    existing reef-score / dosing / trend code consumes them unchanged. Tank samples
    only — a bundled RO/DI analysis must never pollute tank trends.
  * :func:`drift_check` — compare an ICP value against the user's recent *non-ICP*
    test-kit trend and flag a divergence (ICP as a calibration check, not a driver
    of the consumption regression).

Units are normalised per element against the canonical unit in
:data:`~.const.ICP_ELEMENTS` (ppm = mg/L, ppb = µg/L). Lab labels (incl. German)
map to symbols via each element's alias list.
"""

from __future__ import annotations

import math
import re
from datetime import datetime, timedelta, timezone
from typing import Any

from .const import (
    ICP_CORE_PARAM_MAP,
    ICP_DRIFT_TOLERANCE,
    ICP_DRIFT_WINDOW_DAYS,
    ICP_ELEMENTS,
    ICP_REPORT_ELEMENTS_MAX,
    ICP_TEMPLATES_MAX,
)

# --------------------------------------------------------------------------- #
# Label / unit normalisation
# --------------------------------------------------------------------------- #
# Transliterate German element names to the ascii spelling used in the alias
# lists (ä→ae, ö→oe, ü→ue, ß→ss), so "Alkalinität" → "alkalinitaet" etc.
_FOLD = str.maketrans({"ä": "ae", "ö": "oe", "ü": "ue", "ß": "ss"})


def _norm(value: Any) -> str:
    """Fold a lab label/alias to a comparison key: lowercase, drop any parenthetical
    (e.g. units in "Calcium (mg/l)"), transliterate German, keep alphanumerics only."""
    s = str(value).strip().lower()
    s = re.sub(r"\(.*?\)", " ", s)
    s = s.translate(_FOLD)
    return re.sub(r"[^a-z0-9]+", "", s)


def _norm_unit(unit: Any) -> str:
    """Normalise a unit string: lowercase, strip the 'Â' mojibake some labs emit
    before µ (UTF-8 µ decoded as Latin-1 → 'Âµ'), fold both micro signs to 'u',
    drop spaces. So 'Âµg/l', 'µg/L' and 'ug/l' all become 'ug/l'."""
    s = str(unit or "").strip().lower().replace("Â", "").replace("â", "")
    s = s.replace("µ", "u").replace("μ", "u")
    return re.sub(r"\s+", "", s)


# Build the alias → canonical-symbol index once. Each element's own lowercased
# symbol is also a key, so even an element with a thin alias list still resolves.
_ALIAS_INDEX: dict[str, str] = {}
for _sym, _meta in ICP_ELEMENTS.items():
    for _alias in [*_meta.get("aliases", []), _sym]:
        _key = _norm(_alias)
        if _key:
            _ALIAS_INDEX.setdefault(_key, _sym)


def match_symbol(label: Any) -> str | None:
    """Resolve a lab label/symbol to a canonical registry symbol, or None."""
    if label is None:
        return None
    return _ALIAS_INDEX.get(_norm(label))


# µg/L-per-unit factor for concentration units; None for non-concentration units.
_CONC = {
    "mg/l": 1000.0, "mgl": 1000.0, "ppm": 1000.0, "mg/kg": 1000.0,
    "ug/l": 1.0, "ugl": 1.0, "ppb": 1.0, "ug/kg": 1.0,
    "g/l": 1_000_000.0, "gl": 1_000_000.0,
}


def _conc_factor(unit: Any) -> float | None:
    return _CONC.get(_norm_unit(unit))


def to_canonical(symbol: str, value: float | None, raw_unit: Any) -> float | None:
    """Convert a value in ``raw_unit`` to the element's canonical unit.

    Conversion is **per element** (driven by the registry's canonical unit), which
    is what stops a lab reporting Si/P in mg/L from being stored 1000× too high
    next to a lab that reports µg/L. KH in mmol/L or meq/L is converted to dKH.
    """
    if value is None:
        return None
    meta = ICP_ELEMENTS.get(symbol)
    canon = meta["unit"] if meta else (str(raw_unit or ""))
    rf, cf = _conc_factor(raw_unit), _conc_factor(canon)
    if rf is not None and cf is not None:
        return round(value * rf / cf, 6)
    if symbol == "KH" and _norm_unit(raw_unit) in ("mmol/l", "meq/l"):
        return round(value * 2.8, 6)  # 1 meq/L ≈ 2.8 dKH
    return value


# --------------------------------------------------------------------------- #
# Value parsing (numbers, decimal-comma, below-detection markers)
# --------------------------------------------------------------------------- #
_BDL_WORDS = {
    "nd", "n.d.", "nn", "n.n.", "bdl", "<lod", "notdetected", "na", "n/a",
    "-", "--", "—", "–", "n.a.",
}


def _to_float(raw: Any) -> float | None:
    """Parse a number tolerant of decimal-comma and stray comparator/whitespace."""
    s = str(raw).strip().replace(" ", "").replace(" ", "").lstrip("<>=~")
    if not s:
        return None
    if "," in s and "." in s:
        # Both present: the LAST separator is the decimal one, so US "1,234.56"
        # and EU "1.234,56" both parse to 1234.56.
        if s.rfind(",") > s.rfind("."):
            s = s.replace(".", "").replace(",", ".")
        else:
            s = s.replace(",", "")
    elif "," in s:
        s = s.replace(",", ".")          # 1,23 → 1.23 (EU decimal comma)
    try:
        v = float(s)
    except ValueError:
        return None
    return None if (math.isnan(v) or math.isinf(v)) else v


def parse_value(raw: Any) -> tuple[float | None, bool, float | None]:
    """Return ``(value, bdl, threshold)``.

    Below-detection markers ("<0.01", "n.d.", "n.n.") yield ``(None, True, thresh)``
    — never 0 — preserving the detection threshold when given as "<x".
    """
    if raw is None:
        return (None, False, None)
    if isinstance(raw, bool):
        return (None, False, None)
    if isinstance(raw, (int, float)):
        return (None, False, None) if (math.isnan(raw) or math.isinf(raw)) else (float(raw), False, None)
    s = str(raw).strip()
    if not s:
        return (None, False, None)
    if s.startswith("<"):
        return (None, True, _to_float(s[1:]))
    stripped = s.lower().replace(" ", "")
    # below-detection words, or a run of dashes ("---" is ATI's "not detected")
    if stripped in _BDL_WORDS or (stripped and all(ch in "-–—" for ch in stripped)):
        return (None, True, None)
    num = _to_float(s)
    return (None, False, None) if num is None else (num, False, None)


# --------------------------------------------------------------------------- #
# Flagging
# --------------------------------------------------------------------------- #
def _valid_range(r: Any) -> bool:
    return isinstance(r, dict) and (r.get("low") is not None or r.get("high") is not None)


def used_range(lab_range: Any, canonical_range: Any) -> str:
    """Which range drove the flag: the lab's own if present, else OpenReef canonical."""
    if _valid_range(lab_range):
        return "lab"
    if _valid_range(canonical_range):
        return "canonical"
    return "none"


def flag_element(
    category: str,
    value: float | None,
    bdl: bool,
    lab_range: Any,
    canonical_range: Any,
) -> str:
    """Status ∈ low | ok | high | contaminant | bdl | unknown.

    Heavy metals/contaminants flag "contaminant" above their threshold (or on any
    detection when no threshold is known). Everything else flags low/high against
    the lab range when present, else the OpenReef canonical range.
    """
    if bdl:
        return "bdl"
    if value is None:
        return "unknown"
    rng = lab_range if _valid_range(lab_range) else (canonical_range if _valid_range(canonical_range) else None)
    if category == "heavy_metal":
        high = rng.get("high") if rng else None
        if high is None:
            return "contaminant"
        return "contaminant" if value > high else "ok"
    if rng is None:
        return "unknown"
    low, high = rng.get("low"), rng.get("high")
    if low is not None and value < low:
        return "low"
    if high is not None and value > high:
        return "high"
    return "ok"


# --------------------------------------------------------------------------- #
# Report normalisation
# --------------------------------------------------------------------------- #
def _clamp_str(value: Any, limit: int) -> str:
    return ("" if value is None else str(value)).strip()[:limit]


def _f(value: Any) -> float | None:
    try:
        v = float(value)
    except (TypeError, ValueError):
        return None
    return None if (math.isnan(v) or math.isinf(v)) else v


def _clean_range(raw: Any) -> dict[str, float] | None:
    if not isinstance(raw, dict):
        return None
    low, high = _f(raw.get("low")), _f(raw.get("high"))
    if low is None and high is None:
        return None
    return {"low": low, "high": high}


def _clean_ts(value: Any) -> str:
    return value.strip()[:40] if isinstance(value, str) and value.strip() else ""


def _make_report_id(lab: str, sample_date: str, imported_at: str) -> str:
    stamp = (sample_date or imported_at or "na")[:19].replace(":", "").replace(" ", "")
    return f"icp:{_norm(lab) or 'lab'}:{stamp or 'na'}"[:120]


def _normalise_element(item: Any) -> dict[str, Any] | None:
    if not isinstance(item, dict):
        return None
    # Resolve a canonical symbol from symbol → name → label.
    sym = _clamp_str(item.get("symbol"), 24) or None
    matched = match_symbol(sym) if sym else None
    if matched is None:
        matched = match_symbol(item.get("name")) or match_symbol(item.get("label"))
    if matched:
        sym = matched
    if not sym:
        return None  # an element with no identifier cannot be stored
    meta = ICP_ELEMENTS.get(sym)
    category = meta["category"] if meta else "unknown"
    name = meta["name"] if meta else (_clamp_str(item.get("name"), 60) or sym)
    raw_unit = _clamp_str(item.get("rawUnit") or item.get("unit"), 12)
    canon_unit = meta["unit"] if meta else raw_unit
    value, bdl, threshold = parse_value(item.get("rawValue", item.get("value")))
    canonical_value = to_canonical(sym, value, raw_unit) if value is not None else None
    lab_range = _clean_range(item.get("labRange"))
    canonical_range = meta["range"] if meta else None
    # The lab's own ideal/target value (a single point, e.g. ATI "Ideal value: 412.9 mg/l").
    target_value, _, _ = parse_value(item.get("labTarget"))
    target = to_canonical(sym, target_value, raw_unit) if target_value is not None else None
    # Some labs (ATI) print their own verdict word per element; honour it when given
    # (the user's "lab assessment when present, else canonical range" rule). bdl wins.
    lab_status = item.get("labStatus")
    if not (isinstance(lab_status, str) and lab_status in ("low", "ok", "high", "contaminant")):
        lab_status = None
    if bdl:
        status, used = "bdl", used_range(lab_range, canonical_range)
    elif lab_status is not None:
        status, used = lab_status, "lab"
    else:
        status = flag_element(category, canonical_value, bdl, lab_range, canonical_range)
        used = used_range(lab_range, canonical_range)
    out = {
        "symbol": sym,
        "name": name,
        "category": category,
        "rawValue": value,
        "rawUnit": raw_unit,
        "value": canonical_value,
        "unit": canon_unit,
        "bdl": bdl,
        "threshold": _f(threshold),
        "target": target,
        "labRange": lab_range,
        "usedRange": used,
        "status": status,
    }
    for key, limit in (
        ("labGroup", 80),
        ("labName", 80),
        ("labResult", 40),
        ("labUnit", 20),
        ("labSetpoint", 80),
        ("labStatusLabel", 40),
        ("labAssessment", 40),
    ):
        cleaned = _clamp_str(item.get(key), limit)
        if cleaned:
            out[key] = cleaned
    if lab_status is not None:
        out["labStatus"] = lab_status
    return out


def normalise_report(raw: Any) -> dict[str, Any] | None:
    """Validate and canonicalise one ICP report. Returns None if unusable.

    Idempotent: re-running on its own output yields the same report (values are
    recomputed from the preserved raw value + raw unit).
    """
    if not isinstance(raw, dict):
        return None
    raw_elems = raw.get("elements")
    elements = []
    if isinstance(raw_elems, list):
        for item in raw_elems[:ICP_REPORT_ELEMENTS_MAX]:
            el = _normalise_element(item)
            if el is not None:
                elements.append(el)
    if not elements:
        return None

    lab = _clamp_str(raw.get("lab"), 60) or "Unknown"
    sample_type = raw.get("sampleType")
    if sample_type not in ("tank", "rodi", "unknown"):
        sample_type = "tank"  # default to tank (fans out); user can re-mark as RO/DI
    sample_date = _clean_ts(raw.get("sampleDate")) or _clean_ts(raw.get("date"))
    imported_at = _clean_ts(raw.get("importedAt"))
    rid = _clamp_str(raw.get("id"), 120) or _make_report_id(lab, sample_date, imported_at)
    src = raw.get("source") if isinstance(raw.get("source"), dict) else {}
    return {
        "id": rid,
        "lab": lab,
        "adapter": _clamp_str(raw.get("adapter"), 40),
        "method": _clamp_str(raw.get("method"), 20),
        "sampleType": sample_type,
        "sampleDate": sample_date,
        "importedAt": imported_at,
        "testId": _clamp_str(raw.get("testId"), 60),
        "tank": _clamp_str(raw.get("tank"), 60),
        "notes": _clamp_str(raw.get("notes"), 500),
        "source": {
            "fileName": _clamp_str(src.get("fileName"), 160),
            "portalUrl": _clamp_str(src.get("portalUrl"), 200),
        },
        "elements": elements,
    }


def normalise_templates(templates: Any) -> list[dict[str, Any]]:
    """Sanitise saved generic-mapper templates."""
    if not isinstance(templates, list):
        return []
    out: list[dict[str, Any]] = []
    for item in templates[:ICP_TEMPLATES_MAX]:
        if not isinstance(item, dict):
            continue
        tid = _clamp_str(item.get("id"), 80)
        if not tid:
            continue
        col_map = item.get("columnMap")
        clean_map = {}
        if isinstance(col_map, dict):
            for key, val in list(col_map.items())[:200]:
                clean_map[_clamp_str(key, 80)] = _clamp_str(val, 40)
        out.append({
            "id": tid,
            "label": _clamp_str(item.get("label"), 80) or tid,
            "labGuess": _clamp_str(item.get("labGuess"), 60),
            "delimiter": _clamp_str(item.get("delimiter"), 4),
            "decimal": _clamp_str(item.get("decimal"), 2),
            "columnMap": clean_map,
        })
    return out


# --------------------------------------------------------------------------- #
# Fan-out into the existing core reading streams
# --------------------------------------------------------------------------- #
def core_fanout(report: Any) -> dict[str, list[dict[str, Any]]]:
    """Map a stored report's overlapping core params to ``manualReadings`` rows.

    Returns ``{param_id: [reading, ...]}``. Tank samples only — RO/DI and unknown
    samples fan out nothing. Reading ids are deterministic (``<report.id>:<param>``)
    so a re-import dedups and a delete can back-link and remove them.
    """
    out: dict[str, list[dict[str, Any]]] = {}
    if not isinstance(report, dict) or report.get("sampleType") != "tank":
        return out
    ts = report.get("sampleDate") or report.get("importedAt") or ""
    if not ts:
        return out
    rid = report.get("id") or "icp"
    lab = report.get("lab") or "ICP"
    method, test_id = report.get("method") or "", report.get("testId") or ""
    note = " · ".join(p for p in (method, f"test {test_id}" if test_id else "") if p) or "ICP import"
    for el in report.get("elements", []):
        if not isinstance(el, dict) or el.get("bdl") or el.get("value") is None:
            continue
        param = ICP_CORE_PARAM_MAP.get(el.get("symbol"))
        if not param:
            continue
        out.setdefault(param, []).append({
            "id": f"{rid}:{param}"[:120],
            "timestamp": ts,
            "value": el["value"],
            "unit": el.get("unit") or "",
            "source": f"ICP:{lab}"[:80],
            "notes": note[:500],
        })
    return out


# --------------------------------------------------------------------------- #
# Drift / calibration check (ICP vs the user's frequent test-kit trend)
# --------------------------------------------------------------------------- #
def _parse_dt(value: Any) -> datetime | None:
    if not isinstance(value, str) or not value.strip():
        return None
    text = value.strip().replace("Z", "+00:00")
    for candidate in (text, text[:10]):
        try:
            dt = datetime.fromisoformat(candidate)
        except ValueError:
            continue
        return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)
    return None


def _kit_baseline(rows: Any, ref: datetime | None) -> float | None:
    """Median of the user's recent NON-ICP readings for a param, within the window."""
    if not isinstance(rows, list):
        return None
    values: list[float] = []
    for row in rows:
        if not isinstance(row, dict):
            continue
        if str(row.get("source") or "").upper().startswith("ICP"):
            continue
        val = _f(row.get("value"))
        if val is None:
            continue
        if ref is not None:
            ts = _parse_dt(row.get("timestamp"))
            if ts is not None and abs((ts - ref).days) > ICP_DRIFT_WINDOW_DAYS:
                continue
        values.append(val)
    if not values:
        return None
    values.sort()
    mid = len(values) // 2
    return values[mid] if len(values) % 2 else (values[mid - 1] + values[mid]) / 2.0


def drift_check(report: Any, manual_readings: Any) -> list[dict[str, Any]]:
    """Flag core params where the ICP value diverges from the kit trend beyond tolerance."""
    out: list[dict[str, Any]] = []
    if not isinstance(report, dict) or not isinstance(manual_readings, dict):
        return out
    ref = _parse_dt(report.get("sampleDate")) or _parse_dt(report.get("importedAt"))
    by_symbol = {el.get("symbol"): el for el in report.get("elements", []) if isinstance(el, dict)}
    for symbol, param in ICP_CORE_PARAM_MAP.items():
        tol = ICP_DRIFT_TOLERANCE.get(param)
        if tol is None:
            continue
        el = by_symbol.get(symbol)
        if not el or el.get("bdl") or el.get("value") is None:
            continue
        baseline = _kit_baseline(manual_readings.get(param), ref)
        if baseline is None:
            continue
        delta = el["value"] - baseline
        if abs(delta) > tol:
            out.append({
                "parameter": param,
                "icpValue": round(el["value"], 3),
                "kitValue": round(baseline, 3),
                "delta": round(delta, 3),
                "tolerance": tol,
                "direction": "icp_higher" if delta > 0 else "icp_lower",
            })
    return out


# --------------------------------------------------------------------------- #
# ICP v2 dashboard payload (read-only analysis layer)
# --------------------------------------------------------------------------- #
_DASHBOARD_RANGE_DAYS = {"90d": 90, "180d": 180, "365d": 365, "all": None}
_DASHBOARD_GROUPS = (
    ("core", "Core"),
    ("nutrients", "Nutrients"),
    ("major_minor", "Major / Minor"),
    ("trace", "Trace"),
    ("pollutants", "Pollutants"),
    ("organics", "Organics"),
    ("all", "All"),
)
_DASHBOARD_GROUP_ALIASES = {
    "major/minor": "major_minor",
    "major-minor": "major_minor",
    "majorMinor": "major_minor",
    "nutrient": "nutrients",
    "pollutant": "pollutants",
    "organic": "organics",
}
_DASHBOARD_CORE_SYMBOLS = tuple(ICP_CORE_PARAM_MAP.keys())
_DASHBOARD_INSIGHT_LIMIT = 8


def normalise_dashboard_settings(raw: Any) -> dict[str, Any]:
    """Sanitise the optional ICP dashboard filter block.

    Empty ``includedLabs`` means "all labs". These settings drive the dashboard
    payload only; they deliberately do not change ICP fan-out, reef score, or dosing.
    """
    raw = raw if isinstance(raw, dict) else {}
    included: list[str] = []
    labs = raw.get("includedLabs")
    if isinstance(labs, list):
        seen: set[str] = set()
        for lab in labs[:20]:
            clean = _clamp_str(lab, 60)
            key = clean.lower()
            if clean and key not in seen:
                seen.add(key)
                included.append(clean)
    rng = raw.get("range")
    if rng not in _DASHBOARD_RANGE_DAYS:
        rng = "all"
    group = _DASHBOARD_GROUP_ALIASES.get(str(raw.get("group") or ""), raw.get("group"))
    if group not in {item[0] for item in _DASHBOARD_GROUPS}:
        group = "core"
    symbol = _clamp_str(raw.get("symbol"), 24) or "Ca"
    return {
        "includedLabs": included,
        "range": rng,
        "group": group,
        "symbol": symbol,
    }


def _report_dt(report: Any) -> datetime | None:
    if not isinstance(report, dict):
        return None
    return _parse_dt(report.get("sampleDate")) or _parse_dt(report.get("importedAt"))


def _report_date(report: Any, dt: datetime | None = None) -> str:
    text = ""
    if isinstance(report, dict):
        text = str(report.get("sampleDate") or report.get("importedAt") or "").strip()
    if text:
        return text
    return dt.isoformat() if dt is not None else ""


def _dashboard_group_matches(symbol: str, category: str, group: str) -> bool:
    if group == "all":
        return True
    if group == "core":
        return symbol in _DASHBOARD_CORE_SYMBOLS
    if group == "nutrients":
        return category == "nutrient"
    if group == "major_minor":
        return category in ("major", "minor")
    if group == "trace":
        return category == "trace"
    if group == "pollutants":
        return category == "heavy_metal"
    if group == "organics":
        return category == "organic"
    return False


def _symbol_sort_key(symbol: str) -> tuple[int, str]:
    order = {sym: index for index, sym in enumerate(ICP_ELEMENTS)}
    return (order.get(symbol, len(order) + 1), symbol.lower())


def _element_meta(symbol: str, fallback: Any = None) -> dict[str, Any]:
    meta = ICP_ELEMENTS.get(symbol)
    fallback = fallback if isinstance(fallback, dict) else {}
    return {
        "symbol": symbol,
        "name": meta.get("name") if meta else (fallback.get("name") or fallback.get("labName") or symbol),
        "category": meta.get("category") if meta else (fallback.get("category") or "unknown"),
        "unit": meta.get("unit") if meta else (fallback.get("unit") or fallback.get("rawUnit") or ""),
    }


def _dashboard_point(report: dict[str, Any], element: dict[str, Any], dt: datetime) -> dict[str, Any]:
    value = _f(element.get("value"))
    return {
        "reportId": _clamp_str(report.get("id"), 120),
        "date": _report_date(report, dt),
        "time": int(dt.timestamp() * 1000),
        "lab": _clamp_str(report.get("lab"), 60) or "Unknown",
        "value": value,
        "unit": _clamp_str(element.get("unit"), 20),
        "bdl": bool(element.get("bdl")),
        "threshold": _f(element.get("threshold")),
        "status": _clamp_str(element.get("status"), 20),
        "labName": _clamp_str(element.get("labName"), 80),
        "labResult": _clamp_str(element.get("labResult"), 40),
        "labUnit": _clamp_str(element.get("labUnit"), 20),
        "sampleType": _clamp_str(report.get("sampleType"), 20),
    }


def _filtered_dashboard_reports(
    reports: Any,
    settings: dict[str, Any],
    now: datetime,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    all_reports: list[dict[str, Any]] = []
    tank_reports: list[dict[str, Any]] = []
    included_labs = {lab.lower() for lab in settings.get("includedLabs", [])}
    days = _DASHBOARD_RANGE_DAYS.get(settings.get("range"))
    cutoff = now - timedelta(days=days) if days is not None else None
    if not isinstance(reports, list):
        return all_reports, tank_reports
    for report in reports:
        if not isinstance(report, dict):
            continue
        dt = _report_dt(report)
        lab = _clamp_str(report.get("lab"), 60) or "Unknown"
        all_reports.append(report)
        if report.get("sampleType") != "tank":
            continue
        if included_labs and lab.lower() not in included_labs:
            continue
        if cutoff is not None and dt is not None and dt < cutoff:
            continue
        if dt is None:
            continue
        tank_reports.append(report)
    tank_reports.sort(key=lambda item: _report_dt(item) or datetime.min.replace(tzinfo=timezone.utc))
    return all_reports, tank_reports


def _lab_counts(reports: list[dict[str, Any]]) -> list[dict[str, Any]]:
    by_lab: dict[str, dict[str, Any]] = {}
    for report in reports:
        lab = _clamp_str(report.get("lab"), 60) or "Unknown"
        rec = by_lab.setdefault(lab, {"lab": lab, "count": 0, "tankCount": 0, "latest": ""})
        rec["count"] += 1
        if report.get("sampleType") == "tank":
            rec["tankCount"] += 1
        date = _report_date(report, _report_dt(report))
        if date and date > rec["latest"]:
            rec["latest"] = date
    return sorted(by_lab.values(), key=lambda item: item["lab"].lower())


def _build_series(reports: list[dict[str, Any]]) -> dict[str, dict[str, Any]]:
    series: dict[str, dict[str, Any]] = {}
    for report in reports:
        dt = _report_dt(report)
        if dt is None:
            continue
        for element in report.get("elements", []):
            if not isinstance(element, dict):
                continue
            symbol = _clamp_str(element.get("symbol"), 24)
            if not symbol:
                continue
            meta = _element_meta(symbol, element)
            rec = series.setdefault(
                symbol,
                {
                    **meta,
                    "points": [],
                    "bdlPoints": [],
                    "reportCount": 0,
                    "labs": [],
                },
            )
            lab = _clamp_str(report.get("lab"), 60) or "Unknown"
            if lab not in rec["labs"]:
                rec["labs"].append(lab)
            rec["reportCount"] += 1
            point = _dashboard_point(report, element, dt)
            if point["bdl"] or point["value"] is None:
                rec["bdlPoints"].append(point)
            else:
                rec["points"].append(point)
    for rec in series.values():
        rec["points"].sort(key=lambda point: point["time"])
        rec["bdlPoints"].sort(key=lambda point: point["time"])
        rec["labs"].sort(key=str.lower)
    return dict(sorted(series.items(), key=lambda item: _symbol_sort_key(item[0])))


def _dashboard_groups(series: dict[str, dict[str, Any]]) -> list[dict[str, Any]]:
    groups: list[dict[str, Any]] = []
    for group_id, label in _DASHBOARD_GROUPS:
        symbols = [
            symbol for symbol, rec in series.items()
            if _dashboard_group_matches(symbol, rec.get("category", "unknown"), group_id)
        ]
        groups.append({"id": group_id, "label": label, "symbols": symbols})
    return groups


def _material_delta(symbol: str, a: float, b: float) -> float:
    param = ICP_CORE_PARAM_MAP.get(symbol)
    if param in ICP_DRIFT_TOLERANCE:
        return ICP_DRIFT_TOLERANCE[param]
    unit = ICP_ELEMENTS.get(symbol, {}).get("unit")
    avg = (abs(a) + abs(b)) / 2.0
    floor = 0.02 if symbol == "PO4" else (1.0 if unit == "ppm" else 5.0)
    return max(floor, avg * 0.15)


def _analysis_card(kind: str, severity: str, title: str, summary: str, detail: str = "", symbol: str = "") -> dict[str, Any]:
    return {
        "kind": kind,
        "severity": severity,
        "title": title,
        "summary": summary,
        "detail": detail,
        "symbol": symbol,
    }


def _dashboard_analysis_cards(
    reports: list[dict[str, Any]],
    manual_readings: Any,
    series: dict[str, dict[str, Any]],
) -> list[dict[str, Any]]:
    cards: list[dict[str, Any]] = []

    for report in sorted(reports, key=lambda item: _report_date(item, _report_dt(item)), reverse=True):
        for drift in drift_check(report, manual_readings):
            param = drift["parameter"]
            direction = "above" if drift["delta"] > 0 else "below"
            cards.append(_analysis_card(
                "drift",
                "warning",
                "Kit/probe drift",
                f"{param.title()} ICP is {abs(drift['delta'])} {direction} your recent kit/probe median.",
                f"ICP {drift['icpValue']} vs recent non-ICP {drift['kitValue']} (tolerance {drift['tolerance']}).",
            ))
            if len(cards) >= 2:
                break
        if len(cards) >= 2:
            break

    for symbol, rec in series.items():
        points = rec.get("points", [])
        found = False
        for idx, first in enumerate(points):
            for second in points[idx + 1:]:
                if second["time"] - first["time"] > 30 * 24 * 60 * 60 * 1000:
                    break
                if first["lab"] == second["lab"]:
                    continue
                delta = abs(first["value"] - second["value"])
                if delta > _material_delta(symbol, first["value"], second["value"]):
                    cards.append(_analysis_card(
                        "cross_lab",
                        "warning",
                        "Cross-lab disagreement",
                        f"{rec['name']} differs materially between {first['lab']} and {second['lab']}.",
                        f"{first['lab']} {round(first['value'], 4)} {rec['unit']} vs {second['lab']} {round(second['value'], 4)} {rec['unit']} within 30 days.",
                        symbol,
                    ))
                    found = True
                    break
            if found:
                break
        if len(cards) >= _DASHBOARD_INSIGHT_LIMIT:
            return cards[:_DASHBOARD_INSIGHT_LIMIT]

    for symbol, rec in series.items():
        points = rec.get("points", [])
        if len(points) < 3:
            continue
        recent = points[-3:]
        values = [point["value"] for point in recent]
        rising = all(values[i] > values[i - 1] for i in range(1, len(values)))
        falling = all(values[i] < values[i - 1] for i in range(1, len(values)))
        if not (rising or falling):
            continue
        delta = values[-1] - values[0]
        if abs(delta) <= _material_delta(symbol, values[0], values[-1]):
            continue
        direction = "rising" if rising else "falling"
        severity = "warning" if recent[-1].get("status") in ("low", "high", "contaminant") else "info"
        cards.append(_analysis_card(
            "trend",
            severity,
            "Trend movement",
            f"{rec['name']} has been {direction} across the last 3 tank ICP reports.",
            f"Moved from {round(values[0], 4)} to {round(values[-1], 4)} {rec['unit']}.",
            symbol,
        ))
        if len(cards) >= _DASHBOARD_INSIGHT_LIMIT:
            return cards[:_DASHBOARD_INSIGHT_LIMIT]

    contaminant_counts: dict[str, list[dict[str, Any]]] = {}
    for report in reports:
        for element in report.get("elements", []):
            if not isinstance(element, dict):
                continue
            symbol = _clamp_str(element.get("symbol"), 24)
            if element.get("category") == "heavy_metal" and element.get("status") == "contaminant":
                contaminant_counts.setdefault(symbol, []).append(element)
    for symbol, items in contaminant_counts.items():
        if len(items) < 2:
            continue
        meta = _element_meta(symbol, items[-1])
        cards.append(_analysis_card(
            "contaminant",
            "critical",
            "Contaminant review",
            f"{meta['name']} has repeated OpenReef contaminant flags.",
            "OpenReef interpretation only: check recent hardware changes, magnets, pumps, clips, media, and source water before reacting.",
            symbol,
        ))
        if len(cards) >= _DASHBOARD_INSIGHT_LIMIT:
            return cards[:_DASHBOARD_INSIGHT_LIMIT]

    for symbol, rec in series.items():
        points = rec.get("points", [])
        if len(points) != 1:
            continue
        latest = points[-1]
        if latest.get("status") not in ("low", "high", "contaminant"):
            continue
        cards.append(_analysis_card(
            "retest",
            "info",
            "Retest prompt",
            f"{rec['name']} has one odd ICP value without trend support yet.",
            "Treat as a recheck cue before making any major correction.",
            symbol,
        ))
        if len(cards) >= _DASHBOARD_INSIGHT_LIMIT:
            return cards[:_DASHBOARD_INSIGHT_LIMIT]

    recurring_metals = sorted(
        symbol for symbol, items in contaminant_counts.items()
        if len(items) >= 2 and symbol in {"Al", "Cu", "Sn", "Pb", "Hg", "Cd", "Ni", "Zn"}
    )
    if recurring_metals and len(cards) < _DASHBOARD_INSIGHT_LIMIT:
        cards.append(_analysis_card(
            "maintenance",
            "warning",
            "Maintenance clue",
            f"Recurring metals: {', '.join(recurring_metals)}.",
            "Evidence-only prompt: inspect magnets, pump shafts, clips, rust points, media, and RO/DI before choosing a fix.",
        ))

    return cards[:_DASHBOARD_INSIGHT_LIMIT]


def dashboard_payload(
    reports: Any,
    manual_readings: Any | None = None,
    settings: Any | None = None,
    now: datetime | None = None,
) -> dict[str, Any]:
    """Build the unified cross-brand ICP dashboard payload.

    This is a separate OpenReef analysis layer over stored lab-faithful reports.
    It only uses tank-water reports for trend series; RO/DI reports remain visible
    in the raw report list but do not influence dashboard trends.
    """
    settings = normalise_dashboard_settings(settings)
    now = now or datetime.now(timezone.utc)
    if now.tzinfo is None:
        now = now.replace(tzinfo=timezone.utc)
    all_reports, tank_reports = _filtered_dashboard_reports(reports, settings, now)
    series = _build_series(tank_reports)
    groups = _dashboard_groups(series)
    groups_by_id = {group["id"]: group for group in groups}
    selected_group = groups_by_id.get(settings["group"]) or groups_by_id["core"]
    available_symbols = selected_group["symbols"]
    if available_symbols and settings["symbol"] not in available_symbols:
        settings["symbol"] = available_symbols[0] if available_symbols else settings["symbol"]
    selected = series.get(settings["symbol"]) if settings["symbol"] in available_symbols else None
    latest = ""
    point_count = 0
    for rec in series.values():
        point_count += len(rec.get("points", []))
        for point in [*rec.get("points", []), *rec.get("bdlPoints", [])]:
            if point.get("date") and point["date"] > latest:
                latest = point["date"]

    return {
        "settings": settings,
        "labs": _lab_counts(all_reports),
        "groups": groups,
        "series": series,
        "selectedSeries": selected,
        "summary": {
            "reports": len(all_reports),
            "tankReports": len([r for r in all_reports if r.get("sampleType") == "tank"]),
            "filteredTankReports": len(tank_reports),
            "elements": len(series),
            "points": point_count,
            "latest": latest,
        },
        "analysisCards": _dashboard_analysis_cards(tank_reports, manual_readings or {}, series),
    }
