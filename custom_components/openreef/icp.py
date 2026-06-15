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
from datetime import datetime, timezone
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
    """Normalise a unit string: lowercase, fold both micro signs to 'u', drop spaces."""
    s = str(unit or "").strip().lower().replace("µ", "u").replace("μ", "u")
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
    if s.lower().replace(" ", "") in _BDL_WORDS:
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
    return {
        "symbol": sym,
        "name": name,
        "category": category,
        "rawValue": value,
        "rawUnit": raw_unit,
        "value": canonical_value,
        "unit": canon_unit,
        "bdl": bdl,
        "threshold": _f(threshold),
        "labRange": lab_range,
        "usedRange": used_range(lab_range, canonical_range),
        "status": flag_element(category, canonical_value, bdl, lab_range, canonical_range),
    }


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
