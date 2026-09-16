"""The Reef Report engine (Stage B, 0.7.198 — docs/reef-report-brainstorm.md).

Pure maths: ``compile_period`` takes a context of ledgers the integration
already keeps (maintenance completions, manual tests, recorder readings,
AWC runs, the feed log, hatchery history, culture journals, the coral diary,
the event ledger, the score log) plus a window, and returns the report as a
dict. No Home Assistant, no clock of its own, no storage — the same shape as
``nps.py`` / ``cultures.py`` / ``livestock.py`` so the fake-HA harness can
drive it from fixtures and the panel never re-derives a number.

Principles (brief §2): only what was logged — an untested parameter says so;
every figure carries the count it came from; nothing here guesses.
"""

from __future__ import annotations

import statistics
from datetime import date, datetime, timedelta, timezone
from typing import Any

# How far back the Water section looks for a trend: a week of tests is one or
# two readings, four weeks is a line.
TREND_DAYS = 28

# "Steady" tolerances — the range a parameter may wander over the trend
# window and still read as steady; twice that is drifting, beyond is
# swinging. Kit-precision numbers, not targets (targets are the sensor's
# min/max).
STEADY_TOLERANCE = {
    "alkalinity": 0.5,   # dKH
    "calcium": 30.0,     # ppm
    "magnesium": 60.0,   # ppm
    "nitrate": 5.0,      # ppm
    "phosphate": 0.03,   # ppm
    "salinity": 0.5,     # ppt
    "ph": 0.2,
    "temp": 0.8,         # °C
}

# The parameters whose fall between tests is consumption (the corals ate it).
CONSUMED = ("alkalinity", "calcium", "magnesium")

PARAM_LABELS = {
    "alkalinity": "Alkalinity", "calcium": "Calcium", "magnesium": "Magnesium",
    "nitrate": "Nitrate", "phosphate": "Phosphate", "salinity": "Salinity",
    "ph": "pH", "temp": "Temperature",
}

DAY_NAMES = ("Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday")


# --- small helpers -----------------------------------------------------------

def _f(value: Any, default: float = 0.0) -> float:
    try:
        if isinstance(value, bool):
            return default
        out = float(value)
    except (TypeError, ValueError):
        return default
    return out if out == out else default   # NaN guard


def _parse(value: Any) -> datetime | None:
    if isinstance(value, datetime):
        return value if value.tzinfo else value.replace(tzinfo=timezone.utc)
    if not isinstance(value, str) or not value:
        return None
    text = value.strip()
    if text.endswith("Z"):
        text = text[:-1] + "+00:00"
    try:
        parsed = datetime.fromisoformat(text)
    except ValueError:
        return None
    return parsed if parsed.tzinfo else parsed.replace(tzinfo=timezone.utc)


def _round(value: float | None, digits: int = 1) -> float | None:
    if value is None:
        return None
    return round(value, digits)


def _in(at: datetime | None, start: datetime, end: datetime) -> bool:
    return at is not None and start <= at < end


# --- the window ---------------------------------------------------------------

def period_bounds(now_local: datetime, week_start: int = 0, kind: str = "week",
                  which: str = "previous") -> dict[str, Any]:
    """The report window in the keeper's zone. ``kind`` week|month; ``which``
    previous (the last complete period) or current (the one in progress — a
    partial report, flagged). End is exclusive."""
    tz = now_local.tzinfo
    today = now_local.date()
    week_start = int(week_start) if isinstance(week_start, (int, float)) else 0
    week_start = max(0, min(6, week_start))
    if kind == "month":
        first_this = today.replace(day=1)
        if which == "current":
            start_d = first_this
            end_d = (first_this.replace(day=28) + timedelta(days=4)).replace(day=1)
        else:
            end_d = first_this
            start_d = (first_this - timedelta(days=1)).replace(day=1)
    else:
        kind = "week"
        offset = (today.weekday() - week_start) % 7
        this_start = today - timedelta(days=offset)
        if which == "current":
            start_d, end_d = this_start, this_start + timedelta(days=7)
        else:
            start_d, end_d = this_start - timedelta(days=7), this_start
    start = datetime(start_d.year, start_d.month, start_d.day, tzinfo=tz)
    end = datetime(end_d.year, end_d.month, end_d.day, tzinfo=tz)
    partial = which == "current"
    return {"kind": kind, "which": "current" if partial else "previous", "start": start, "end": end,
            "partial": partial, "label": _period_label(start_d, end_d - timedelta(days=1), kind),
            "weekStart": week_start, "days": (end_d - start_d).days}


def _period_label(start_d: date, last_d: date, kind: str) -> str:
    if kind == "month":
        return start_d.strftime("%B %Y")
    if start_d.month == last_d.month:
        return f"{start_d.day}–{last_d.day} {last_d.strftime('%B %Y')}"
    return f"{start_d.day} {start_d.strftime('%b')} – {last_d.day} {last_d.strftime('%b %Y')}"


# --- sections -----------------------------------------------------------------

def maintenance_section(tasks: Any, completions: Any, start: datetime, end: datetime,
                        tank_l: float) -> dict[str, Any]:
    """What was ticked off: per task done/skipped and whether each tick came
    on time (within the cadence of the tick before it), water changed by hand
    and by the AWC. Untracked tasks count too — history outlives the toggle."""
    tasks = tasks if isinstance(tasks, dict) else {}
    completions = completions if isinstance(completions, dict) else {}
    by_task: list[dict[str, Any]] = []
    done = skipped = on_time = timed = 0
    litres = pct = 0.0
    hand_l = auto_l = 0.0
    by_source: dict[str, int] = {}
    for task_id in sorted(set(tasks) | set(completions)):
        task = tasks.get(task_id) if isinstance(tasks.get(task_id), dict) else {}
        rows = [r for r in (completions.get(task_id) or []) if isinstance(r, dict)]
        dated = sorted(((_parse(r.get("timestamp") or r.get("date")), r) for r in rows),
                       key=lambda p: p[0] or datetime.min.replace(tzinfo=timezone.utc))
        dated = [(at, r) for at, r in dated if at is not None]
        cadence_h = _f(task.get("cadenceHours"))
        cadence_d = _f(task.get("cadenceDays"), 7.0)
        cadence = timedelta(hours=cadence_h) if cadence_h > 0 else timedelta(days=cadence_d)
        t_done = t_skipped = t_late = 0
        t_litres = 0.0
        prev_done: datetime | None = None
        for at, row in dated:
            if row.get("skipped"):
                if _in(at, start, end):
                    t_skipped += 1
                continue
            if _in(at, start, end):
                t_done += 1
                src = str(row.get("source") or "hand")
                by_source[src] = by_source.get(src, 0) + 1
                vol = _f(row.get("volume"))
                unit = str(row.get("volumeUnit") or "pct")
                if vol > 0:
                    row_l = vol if unit == "L" else (vol / 100.0 * tank_l if tank_l > 0 else 0.0)
                    row_pct = vol if unit != "L" else (vol / tank_l * 100.0 if tank_l > 0 else 0.0)
                    t_litres += row_l
                    litres += row_l
                    pct += row_pct
                    if src == "awc":
                        auto_l += row_l
                    else:
                        hand_l += row_l
                if prev_done is not None and task.get("scheduleMode") != "fixed":
                    timed += 1
                    if at - prev_done <= cadence + timedelta(hours=1):
                        on_time += 1
                    else:
                        t_late += 1
            prev_done = at
        if t_done or t_skipped:
            by_task.append({"id": task_id, "label": str(task.get("label") or task_id), "done": t_done,
                            "skipped": t_skipped, "late": t_late, "litres": _round(t_litres) if t_litres else None,
                            "tracked": bool(task.get("enabled"))})
        done += t_done
        skipped += t_skipped
    by_task.sort(key=lambda t: (-t["done"], t["label"]))
    return {
        "done": done, "skipped": skipped, "tasks": by_task,
        "onSchedule": _round(on_time / timed * 100.0, 0) if timed else None, "timed": timed,
        "waterChangedL": _round(litres), "waterChangedPct": _round(pct) if tank_l > 0 else None,
        "handL": _round(hand_l), "autoL": _round(auto_l), "bySource": by_source,
    }


def _readings_for(param: str, manual: Any, sensors: Any) -> list[tuple[datetime, float, str]]:
    out: list[tuple[datetime, float, str]] = []
    for row in (manual.get(param) if isinstance(manual, dict) else None) or []:
        if not isinstance(row, dict):
            continue
        at = _parse(row.get("timestamp") or row.get("date"))
        if at is None:
            continue
        out.append((at, _f(row.get("value")), "test"))
    for row in (sensors.get(param) if isinstance(sensors, dict) else None) or []:
        if not isinstance(row, dict):
            continue
        at = _parse(row.get("t") or row.get("timestamp"))
        if at is None:
            continue
        out.append((at, _f(row.get("v") if "v" in row else row.get("value")), "sensor"))
    out.sort(key=lambda p: p[0])
    return out


def consumption_per_day(readings: list[tuple[datetime, float, str]]) -> dict[str, Any]:
    """The median fall per day between consecutive readings that FELL — a
    dose or a water change lifts the line and that pair is skipped. An
    estimate, and labelled one: it needs two falling pairs to say anything."""
    drops: list[float] = []
    for (a_at, a_v, _s1), (b_at, b_v, _s2) in zip(readings, readings[1:]):
        hours = (b_at - a_at).total_seconds() / 3600.0
        if hours < 2 or b_v >= a_v:
            continue
        drops.append((a_v - b_v) / hours * 24.0)
    if len(drops) < 2:
        return {"perDay": None, "pairs": len(drops)}
    return {"perDay": _round(statistics.median(drops), 3), "pairs": len(drops)}


def water_section(manual: Any, sensors: Any, meta: Any, start: datetime, end: datetime,
                  params: tuple[str, ...] | None = None) -> dict[str, Any]:
    """Per parameter: what was tested this period, the four-week line, a
    stability band and — for the consumed three — the fall per day."""
    meta = meta if isinstance(meta, dict) else {}
    params = params or tuple(PARAM_LABELS)
    trend_start = end - timedelta(days=TREND_DAYS)
    out: list[dict[str, Any]] = []
    untested: list[str] = []
    for param in params:
        info = meta.get(param) if isinstance(meta.get(param), dict) else {}
        rows = _readings_for(param, manual, sensors)
        in_period = [r for r in rows if _in(r[0], start, end)]
        window = [r for r in rows if _in(r[0], trend_start, end)]
        latest = rows[-1] if rows else None
        latest_before_end = next((r for r in reversed(rows) if r[0] < end), None)
        lo = info.get("min")
        hi = info.get("max")
        entry: dict[str, Any] = {
            "id": param, "label": str(info.get("label") or PARAM_LABELS.get(param, param)),
            "unit": str(info.get("unit") or ""),
            "tests": len([r for r in in_period if r[2] == "test"]),
            "sensorSamples": len([r for r in in_period if r[2] == "sensor"]),
            "latest": _round(latest_before_end[1], 3) if latest_before_end else None,
            "latestAt": latest_before_end[0].isoformat() if latest_before_end else None,
            "daysSince": _round((end - latest_before_end[0]).total_seconds() / 86400.0, 1) if latest_before_end else None,
            "range": {"min": lo, "max": hi} if isinstance(lo, (int, float)) and isinstance(hi, (int, float)) else None,
            "inRange": None, "band": "untested", "change": None, "low": None, "high": None,
            "points": [{"t": r[0].isoformat(), "v": _round(r[1], 3), "src": r[2]} for r in window][-40:],
        }
        if latest_before_end and entry["range"]:
            entry["inRange"] = bool(lo <= latest_before_end[1] <= hi)
        values = [r[1] for r in window]
        if not in_period:
            entry["band"] = "untested"
            untested.append(entry["label"])
        elif len(values) < 2:
            entry["band"] = "single"
        else:
            spread = max(values) - min(values)
            tol = STEADY_TOLERANCE.get(param, 0.0)
            entry["low"], entry["high"] = _round(min(values), 3), _round(max(values), 3)
            entry["change"] = _round(window[-1][1] - window[0][1], 3)
            entry["band"] = "steady" if tol and spread <= tol else "drifting" if tol and spread <= 2 * tol else "swinging"
        if param in CONSUMED:
            entry["consumption"] = consumption_per_day(window)
        entry["latestIsFromPeriod"] = bool(in_period)
        del latest
        out.append(entry)
    return {"parameters": out, "untested": untested,
            "tested": [e["label"] for e in out if e["tests"] or e["sensorSamples"]]}


def hatches_section(history: Any, vessels: Any, start: datetime, end: datetime) -> dict[str, Any]:
    vessels = vessels if isinstance(vessels, dict) else {}
    rows = [r for r in (history if isinstance(history, list) else []) if isinstance(r, dict)]
    harvested = [r for r in rows if _in(_parse(r.get("harvestedAt")), start, end)]
    started = [r for r in rows if _in(_parse(r.get("startedAt")), start, end)]
    actual = [_f(r.get("actualHours")) for r in harvested if _f(r.get("actualHours")) > 0]
    planned_gap = [_f(r.get("actualHours")) - _f(r.get("plannedHours")) for r in harvested
                   if _f(r.get("actualHours")) > 0 and _f(r.get("plannedHours")) > 0]
    per_vessel: dict[str, int] = {}
    for r in harvested:
        vid = str(r.get("vesselId") or "v1")
        per_vessel[vid] = per_vessel.get(vid, 0) + 1
    return {
        "started": len(started), "harvested": len(harvested),
        "avgActualHours": _round(sum(actual) / len(actual)) if actual else None,
        "avgLateHours": _round(sum(planned_gap) / len(planned_gap)) if planned_gap else None,
        "enriched": len([r for r in harvested if r.get("enriched")]),
        "byVessel": [{"id": vid, "name": str((vessels.get(vid) or {}).get("name") or vid), "harvests": n}
                     for vid, n in sorted(per_vessel.items())],
    }


def cultures_section(jars: Any, start: datetime, end: datetime) -> dict[str, Any]:
    """Each jar's journal for the period: feeds, looks, harvests, skipped
    feeds, signs, restarts and crashes — taken-back rows never count."""
    jars = jars if isinstance(jars, dict) else {}
    out: list[dict[str, Any]] = []
    totals = {"feeds": 0, "looks": 0, "harvests": 0, "skips": 0, "signs": 0, "restarts": 0, "crashed": 0}
    for jid, jar in sorted(jars.items()):
        if not isinstance(jar, dict):
            continue
        counts = dict.fromkeys(totals, 0)
        harvest_ml = 0.0
        signs: list[str] = []
        for row in (jar.get("history") if isinstance(jar.get("history"), list) else []):
            if not isinstance(row, dict) or row.get("undoneAt"):
                continue
            at = _parse(row.get("at"))
            if not _in(at, start, end):
                continue
            event = str(row.get("event") or "")
            if row.get("fed") is True or event == "feed":
                counts["feeds"] += 1
            if row.get("tint"):
                counts["looks"] += 1
            if row.get("harvested") is True or event == "harvest":
                counts["harvests"] += 1
                harvest_ml += _f(row.get("ml"))
            if row.get("skipped") is True or event == "skip_feed":
                counts["skips"] += 1
            if row.get("sign"):
                counts["signs"] += 1
                signs.append(str(row.get("sign")))
            if event in ("restart", "seeded"):
                counts["restarts"] += 1
            if event == "crashed":
                counts["crashed"] += 1
        for key, n in counts.items():
            totals[key] += n
        out.append({"id": str(jid), "name": str(jar.get("name") or jid), **counts,
                    "harvestMl": _round(harvest_ml, 0) if harvest_ml else None, "signList": signs[:6]})
    return {"jars": out, **totals}


def corals_section(corals: Any, checkins: Any, feeds: Any, states: Any,
                   start: datetime, end: datetime) -> dict[str, Any]:
    """Looks and feeds logged in the period, the grade spread now, and the
    colonies whose score moved between the last look before the period and
    the last look inside it (from the diary's own scorer, handed in)."""
    corals = corals if isinstance(corals, dict) else {}
    checkins = checkins if isinstance(checkins, dict) else {}
    feeds = feeds if isinstance(feeds, dict) else {}
    states = states if isinstance(states, dict) else {}
    n_checks = n_feeds = 0
    moved: list[dict[str, Any]] = []
    grades: dict[str, int] = {}
    for cid, coral in corals.items():
        if not isinstance(coral, dict):
            continue
        rows = [r for r in (checkins.get(cid) or []) if isinstance(r, dict) and not r.get("undoneAt")]
        n_checks += len([r for r in rows if _in(_parse(r.get("at")), start, end)])
        n_feeds += len([r for r in (feeds.get(cid) or []) if isinstance(r, dict) and not r.get("undoneAt")
                        and _in(_parse(r.get("at")), start, end)])
        state = states.get(cid) if isinstance(states.get(cid), dict) else {}
        grade = str(state.get("grade") or "")
        if grade:
            grades[grade] = grades.get(grade, 0) + 1
        before = state.get("scoreBefore")
        after = state.get("score")
        if isinstance(before, (int, float)) and isinstance(after, (int, float)) and abs(after - before) >= 5:
            moved.append({"id": str(cid), "name": str(coral.get("name") or cid), "from": int(before), "to": int(after)})
    moved.sort(key=lambda m: m["to"] - m["from"])
    return {"colonies": len(corals), "checkins": n_checks, "feeds": n_feeds, "grades": grades, "moved": moved}


def feed_counts_in(feed_log: dict[str, Any], start: datetime, end: datetime) -> dict[str, int]:
    """The feed log's rows recounted INSIDE the window (the log's own totals
    cover its whole span): feeds, by hand vs pump, taken back."""
    counts = {"feeds": 0, "hand": 0, "pump": 0, "undone": 0}
    lo, hi = start.date().isoformat(), end.date().isoformat()
    for row in (feed_log.get("rows") if isinstance(feed_log.get("rows"), list) else []):
        if not isinstance(row, dict):
            continue
        day = str(row.get("date") or "")
        if not (lo <= day < hi):
            continue
        if row.get("undone"):
            counts["undone"] += 1
            continue
        counts["feeds"] += 1
        how = str(row.get("how") or "hand")
        counts[how if how in ("hand", "pump") else "hand"] += 1
    return counts


def events_section(events: Any, start: datetime, end: datetime, limit: int = 40) -> dict[str, Any]:
    rows = []
    for row in (events if isinstance(events, list) else []):
        if not isinstance(row, dict):
            continue
        at = _parse(row.get("at"))
        if _in(at, start, end):
            rows.append({"at": at.isoformat(), "message": str(row.get("message") or ""),
                         "type": str(row.get("type") or "info"), "kind": row.get("kind")})
    rows.sort(key=lambda r: r["at"], reverse=True)
    types: dict[str, int] = {}
    for r in rows:
        types[r["type"]] = types.get(r["type"], 0) + 1
    return {"count": len(rows), "byType": types, "rows": rows[:limit]}


def score_section(score_log: Any, start: datetime, end: datetime) -> dict[str, Any]:
    """The Reef Health stamps inside the period vs the period before: latest,
    average, how many days had one — a day the panel never opened is a gap,
    said as such."""
    rows = []
    for row in (score_log if isinstance(score_log, list) else []):
        if not isinstance(row, dict):
            continue
        try:
            d = date.fromisoformat(str(row.get("date")))
        except ValueError:
            continue
        rows.append((d, _f(row.get("total")), row.get("parts") if isinstance(row.get("parts"), dict) else {}))
    days = (end - start).days or 1
    span = timedelta(days=days)
    inside = [r for r in rows if start.date() <= r[0] < end.date()]
    before = [r for r in rows if (start - span).date() <= r[0] < start.date()]
    inside.sort(key=lambda r: r[0])
    avg = sum(r[1] for r in inside) / len(inside) if inside else None
    prev = sum(r[1] for r in before) / len(before) if before else None
    parts: dict[str, list[float]] = {}
    for _d, _t, p in inside:
        for k, v in p.items():
            parts.setdefault(str(k), []).append(_f(v))
    return {
        "latest": int(inside[-1][1]) if inside else None,
        "average": _round(avg, 0) if avg is not None else None,
        "previousAverage": _round(prev, 0) if prev is not None else None,
        "delta": _round(avg - prev, 0) if avg is not None and prev is not None else None,
        "stamps": len(inside), "gaps": max(0, days - len(inside)),
        "parts": {k: _round(sum(v) / len(v), 0) for k, v in parts.items()},
        "series": [{"date": r[0].isoformat(), "total": int(r[1])} for r in inside],
    }


def next_section(upcoming: Any, start: datetime, days: int = 7) -> dict[str, Any]:
    """The plan: what falls due in the next ``days`` from ``start`` (the
    period's end for a previous-period report), by local day."""
    rows = []
    for item in (upcoming if isinstance(upcoming, list) else []):
        if not isinstance(item, dict):
            continue
        at = _parse(item.get("dueAt"))
        if at is None:
            continue
        local = at.astimezone(start.tzinfo) if start.tzinfo else at
        if at < start:
            bucket, label = "now", "Already due"
        elif at < start + timedelta(days=days):
            bucket, label = local.date().isoformat(), DAY_NAMES[local.weekday()]
        else:
            continue
        rows.append({"id": str(item.get("id") or ""), "label": str(item.get("label") or item.get("id") or ""),
                     "dueAt": at.isoformat(), "day": bucket, "dayLabel": label, "status": str(item.get("status") or ""),
                     "source": item.get("source")})
    rows.sort(key=lambda r: r["dueAt"])
    by_day: list[dict[str, Any]] = []
    for r in rows:
        if by_day and by_day[-1]["day"] == r["day"]:
            by_day[-1]["items"].append(r)
        else:
            by_day.append({"day": r["day"], "label": r["dayLabel"], "items": [r]})
    return {"count": len(rows), "days": by_day}


# --- the Reef Week Score (brief §3.3) -------------------------------------------

SCORE_PARTS = (
    ("chemistry", "Chemistry stability", 30, "condition"),
    ("care", "Care consistency", 25, "consistency"),
    ("nutrition", "Nutrition", 15, "consistency"),
    ("livestock", "Livestock wellbeing", 15, "condition"),
    ("reliability", "System reliability", 15, "consistency"),
)

BAND_SCORE = {"steady": 100, "drifting": 70, "swinging": 35}
GRADE_SCORE = {"A": 100, "B": 80, "C": 60, "D": 40, "F": 20}


def _avg(values: list[float]) -> float | None:
    return sum(values) / len(values) if values else None


def _part(pid: str, score: float | None, why: str, raise_: str) -> dict[str, Any]:
    label, weight, side = next((lb, w, sd) for i, lb, w, sd in SCORE_PARTS if i == pid)
    return {"id": pid, "label": label, "weight": weight, "side": side,
            "score": int(round(score)) if score is not None else None,
            "available": score is not None, "why": why, "raise": raise_}


def week_score(report: dict[str, Any]) -> dict[str, Any]:
    """Five explainable parts, weighted, each with a why line and what would
    raise it. A part with no data scores NEUTRAL — it drops out of the
    weighting and says so — never a hidden zero. Two totals: condition
    (chemistry, livestock) and consistency (care, nutrition, reliability),
    so "the tank is fine, you are slipping" reads as its own sentence."""
    water = report.get("water") or {}
    did = report.get("did") or {}
    m = did.get("maintenance") or {}
    living = report.get("living") or {}
    happened = report.get("happened") or {}
    parts: list[dict[str, Any]] = []

    # Chemistry: every parameter with a band; a reading out of range caps it.
    scored = []
    words = []
    for prm in water.get("parameters") or []:
        base = BAND_SCORE.get(prm.get("band"))
        if base is None:
            continue
        if prm.get("inRange") is False:
            base = min(base, 50)
        scored.append(base)
        if prm.get("band") != "steady" or prm.get("inRange") is False:
            words.append(f"{prm.get('label')} {prm.get('band')}{' and out of range' if prm.get('inRange') is False else ''}")
    untested = water.get("untested") or []
    chem = _avg(scored)
    parts.append(_part("chemistry", chem,
                       ("Nothing tested with a trend yet." if chem is None else
                        f"{len(scored)} parameter{'s' if len(scored) != 1 else ''} with a trend; " + (", ".join(words) if words else "all steady and in range") + "."),
                       (f"Test {', '.join(untested[:3])}." if untested else "Keep testing on the cadence; steady beats perfect.")))

    # Care: on time, tests logged vs parameters tracked, water changed.
    care_bits = []
    care_words = []
    if m.get("timed"):
        care_bits.append(float(m.get("onSchedule") or 0))
        care_words.append(f"{int(m.get('onSchedule') or 0)} % of chores on time")
    total_params = len(water.get("parameters") or [])
    tested = len(water.get("tested") or [])
    # Coverage counts once the keeper is logging at all; a period with no
    # tests AND no chores is "no data", not "zero care".
    if total_params and (tested or m.get("done")):
        care_bits.append(tested / total_params * 100.0)
        care_words.append(f"{tested} of {total_params} parameters tested")
    if m.get("done") or (did.get("awc") or {}).get("runs"):
        changed = (m.get("waterChangedL") or 0) > 0 or (did.get("awc") or {}).get("runs")
        care_bits.append(100.0 if changed else 30.0)
        care_words.append("water changed" if changed else "no water changed")
    care = _avg(care_bits)
    parts.append(_part("care", care, ("Nothing logged to judge." if care is None else "; ".join(care_words) + "."),
                       "Tick chores on their day, test every tracked parameter once, change some water."))

    # Nutrition: feeds happened, hatches on the clock, cultures without signs.
    nut_bits = []
    nut_words = []
    feeds = did.get("feeds") or {}
    if feeds.get("available"):
        n = int(feeds.get("count") or 0)
        nut_bits.append(100.0 if n >= 7 else 70.0 if n >= 3 else 40.0 if n else 10.0)
        nut_words.append(f"{n} feed{'s' if n != 1 else ''} logged")
    hatches = living.get("hatches") or {}
    if hatches.get("harvested"):
        late = hatches.get("avgLateHours")
        nut_bits.append(100.0 if late is None or late <= 2 else 70.0 if late <= 6 else 40.0)
        nut_words.append(f"{hatches['harvested']} hatch{'es' if hatches['harvested'] != 1 else ''}" + (f", {late:g} h past the clock" if late and late > 2 else " on the clock"))
    cultures = living.get("cultures") or {}
    if any((j.get("feeds") or j.get("looks") or j.get("harvests")) for j in cultures.get("jars") or []):
        nut_bits.append(30.0 if cultures.get("crashed") else 70.0 if cultures.get("signs") else 100.0)
        nut_words.append("a culture crashed" if cultures.get("crashed") else f"{cultures['signs']} culture sign{'s' if cultures['signs'] != 1 else ''}" if cultures.get("signs") else "cultures clean")
    nut = _avg(nut_bits)
    parts.append(_part("nutrition", nut, ("No feeds, hatches or culture entries logged." if nut is None else "; ".join(nut_words) + "."),
                       "Feed on the windows, start hatches at the plan's time, look at the jars daily."))

    # Livestock: the grade spread now, a drop costs.
    corals = living.get("corals") or {}
    grades = corals.get("grades") or {}
    graded = [GRADE_SCORE[g] for g, n in grades.items() if g in GRADE_SCORE for _ in range(int(n))]
    live = _avg(graded)
    drops = [mv for mv in corals.get("moved") or [] if mv.get("to", 0) < mv.get("from", 0)]
    if live is not None and drops:
        live = max(0.0, live - 10.0 * len(drops))
    parts.append(_part("livestock", live,
                       ("No colonies graded yet." if live is None else
                        ", ".join(f"{n} × {g}" for g, n in sorted(grades.items())) + (f"; {len(drops)} dropped" if drops else "") + "."),
                       "Look at every colony on its cadence; a look is what lets a grade rise."))

    # Reliability: a quiet log is a good log.
    by_type = happened.get("byType") or {}
    warnings = int(by_type.get("warning") or 0)
    criticals = int(by_type.get("critical") or 0) + int(by_type.get("error") or 0)
    rel = max(20.0, 100.0 - 15.0 * warnings - 30.0 * criticals)
    parts.append(_part("reliability", rel,
                       ("Nothing on the log." if not (warnings or criticals) else
                        f"{warnings} warning{'s' if warnings != 1 else ''}" + (f", {criticals} critical" if criticals else "") + " on the log."),
                       "Clear the warnings the log names; fewer surprises, higher score."))

    def weighted(side: str | None) -> int | None:
        picked = [pt for pt in parts if pt["available"] and (side is None or pt["side"] == side)]
        if not picked:
            return None
        return int(round(sum(pt["score"] * pt["weight"] for pt in picked) / sum(pt["weight"] for pt in picked)))

    return {"total": weighted(None), "condition": weighted("condition"), "consistency": weighted("consistency"),
            "parts": parts, "neutral": [pt["label"] for pt in parts if not pt["available"]]}


# --- Recommendations, small (brief §5) ------------------------------------------

SMALL_RECS_MAX = 3


def _rec(rid: str, priority: int, title: str, evidence: str, effort: str, effect: str,
         actions: list[dict[str, str]] | None = None) -> dict[str, Any]:
    return {"id": rid, "size": "small", "priority": priority, "title": title, "evidence": evidence,
            "effort": effort, "effect": effect, "actions": actions or []}


def recommend(report: dict[str, Any], snoozed: Any = None, now: datetime | None = None) -> dict[str, Any]:
    """Rule-based, explainable, capped: each recommendation names the evidence
    line it came from, the effort, the expected effect and the screen to do
    it on. Snoozed ids stay out until their stamp passes. A calm week gets a
    calm line and one habit at most."""
    now = now or datetime.now(timezone.utc)
    snoozed = snoozed if isinstance(snoozed, dict) else {}
    hidden = {rid for rid, until in snoozed.items() if (_parse(until) or now) > now}
    water = report.get("water") or {}
    did = report.get("did") or {}
    m = did.get("maintenance") or {}
    living = report.get("living") or {}
    score = report.get("headline", {}).get("score") or {}
    recs: list[dict[str, Any]] = []
    manual_tab = [{"action": "tab", "id": "manual", "label": "Log a test"}]
    for prm in water.get("parameters") or []:
        pid, label = prm.get("id"), prm.get("label")
        unit = prm.get("unit") or ""
        if prm.get("band") == "untested" and pid in ("alkalinity", "calcium", "magnesium", "nitrate", "phosphate", "salinity"):
            since = prm.get("daysSince")
            pri = 10 if pid == "alkalinity" else 30
            recs.append(_rec(f"test_{pid}", pri, f"Test {label.lower()} this week",
                             f"Last test {int(since)} days before the period's end." if since is not None else "Never logged.",
                             "5 min", "A trend to read and the chemistry part of the score filled in.", manual_tab))
        if prm.get("band") == "swinging":
            recs.append(_rec(f"steady_{pid}", 15, f"Steady {label.lower()}",
                             f"Swung {prm.get('low')}–{prm.get('high')} {unit} over four weeks; steady is within {STEADY_TOLERANCE.get(pid, 0)} {unit}.".strip(),
                             "15 min", "Stability is what the corals feel; the chemistry part of the score follows.", manual_tab))
        if prm.get("inRange") is False and prm.get("latestIsFromPeriod"):
            rng = prm.get("range") or {}
            recs.append(_rec(f"range_{pid}", 12, f"Bring {label.lower()} back into range",
                             f"Latest {prm.get('latest')} {unit}; the range is {rng.get('min')}–{rng.get('max')} {unit}.".strip(),
                             "15 min", "Back inside the band the tank was set up for.", manual_tab))
    for task in m.get("tasks") or []:
        if not task.get("tracked"):
            continue
        if task.get("late", 0) >= 2 or (task.get("late", 0) >= 1 and task.get("done", 0) <= 2):
            recs.append(_rec(f"late_{task['id']}", 40, f"Do {task['label']} on its day",
                             f"{task['late']} of {task['done']} ticks came after the cadence.",
                             "no extra time", "The on-time rate, and a chore that stops sliding.",
                             [{"action": "report-task", "id": task["id"], "label": "Open the task"}]))
        if task.get("skipped", 0) >= 2:
            recs.append(_rec(f"skipped_{task['id']}", 45, f"Stop skipping {task['label']}",
                             f"Skipped {task['skipped']} times this period.", "varies",
                             "Either do it or lengthen its cadence — a skip is neither.",
                             [{"action": "report-task", "id": task["id"], "label": "Open the task"}]))
    if (m.get("done") or m.get("timed")) and not (m.get("waterChangedL") or 0) and not (did.get("awc") or {}).get("runs"):
        recs.append(_rec("water_change", 35, "Change some water this week", "No water change logged this period.",
                         "30 min", "Nutrients export, trace elements back in.",
                         [{"action": "tab", "id": "maintenance", "label": "Open Maintenance"}]))
    hatches = living.get("hatches") or {}
    if hatches.get("harvested") and (hatches.get("avgLateHours") or 0) > 3:
        recs.append(_rec("hatch_late", 25, "Start the hatch at the plan's time",
                         f"Harvests ran {hatches['avgLateHours']:g} h past the clock on average.",
                         "no extra time", "Brine at its yolkiest, and the next batch on schedule.",
                         [{"action": "tab", "id": "hatchery", "label": "Open the hatchery"}]))
    for jar in (living.get("cultures") or {}).get("jars") or []:
        if jar.get("crashed"):
            recs.append(_rec(f"culture_{jar['id']}", 8, f"Restart {jar['name']} from a clean jar", "The journal logged a crash.",
                             "20 min", "A live culture again.", [{"action": "tab", "id": "cultures", "label": "Open cultures"}]))
        elif jar.get("signs"):
            recs.append(_rec(f"culture_{jar['id']}", 20, f"Look at {jar['name']} today",
                             f"{jar['signs']} sign{'s' if jar['signs'] != 1 else ''} logged: {', '.join(jar.get('signList') or [])}.",
                             "5 min", "A crash caught early is a purge, not a restart.",
                             [{"action": "tab", "id": "cultures", "label": "Open cultures"}]))
    for mv in (living.get("corals") or {}).get("moved") or []:
        if mv.get("to", 0) < mv.get("from", 0):
            recs.append(_rec(f"coral_{mv['id']}", 18, f"Look closer at {mv['name']}", f"Score {mv['from']} → {mv['to']} this period.",
                             "5 min", "A colony sliding is caught while it is still a colony.",
                             [{"action": "tab", "id": "corals", "label": "Open the diary"}]))
    days = int((report.get("period") or {}).get("days") or 7)
    if (score.get("gaps") or 0) >= max(3, days - 2):
        recs.append(_rec("stamps", 50, "Open the panel once a day",
                         f"Reef Health was stamped on {score.get('stamps') or 0} of {days} days.",
                         "1 min", "A score line with no gaps — and the report can say more.", []))
    recs = [r for r in recs if r["id"] not in hidden]
    recs.sort(key=lambda r: (r["priority"], r["id"]))
    calm = not recs
    if calm:
        recs.append(_rec("keep_rhythm", 99, "Keep the rhythm", "Nothing in this period asked for a change.",
                         "none", "The reef likes it this way.", []))
    kept = recs[:SMALL_RECS_MAX]
    for r in kept:
        r.pop("priority", None)
    return {"items": kept, "calm": calm, "snoozed": sorted(hidden)}


def verdict(report: dict[str, Any]) -> str:
    """One calm sentence, from the numbers — the only place the report is
    allowed a voice, and never on a warning."""
    did = report["did"]["maintenance"]
    water = report["water"]
    events = report["happened"]
    warnings = events["byType"].get("warning", 0) + events["byType"].get("critical", 0)
    bits: list[str] = []
    if did["done"]:
        sched = did.get("onSchedule")
        bits.append(f"{did['done']} chore{'s' if did['done'] != 1 else ''} ticked off"
                    + (f", {int(sched)} % on time" if sched is not None else ""))
    else:
        bits.append("nothing ticked off")
    if water["untested"] and len(water["untested"]) == len(water["parameters"]):
        bits.append("no water tests logged")
    elif water["untested"]:
        bits.append(f"{len(water['untested'])} parameter{'s' if len(water['untested']) != 1 else ''} untested")
    elif water["parameters"]:
        swinging = [p["label"] for p in water["parameters"] if p["band"] == "swinging"]
        bits.append(f"{swinging[0]} swinging" if swinging else "water steady")
    if warnings:
        bits.append(f"{warnings} warning{'s' if warnings != 1 else ''} on the log")
    line = ", ".join(bits)
    return line[0].upper() + line[1:] + "." if line else "A quiet period."


def compile_period(ctx: dict[str, Any]) -> dict[str, Any]:
    """The report. ``ctx`` (all optional but ``period``):

    period            period_bounds(...) output
    now               aware datetime
    tankL             float
    tasks, completions            maintenance.tasks / .completions
    manualReadings                manualReadings (per parameter)
    sensorReadings                {param: [{t, v}]} from the recorder / the panel
    paramMeta                     {param: {label, unit, min, max}}
    awcHistory                    awc.history
    feedLog                       nps.feed_log output for the period (or None)
    hatchHistory, hatchVessels
    cultureJars                   {jid: {name, history}}
    corals, checkins, coralFeeds, coralStates ({cid: {score, grade, scoreBefore}})
    events, scoreLog
    upcoming                      [{id, label, dueAt, status, source}] from the maintenance evaluator
    """
    period = ctx["period"]
    start, end = period["start"], period["end"]
    now = ctx.get("now") or datetime.now(timezone.utc)
    tank_l = _f(ctx.get("tankL"))
    maintenance = maintenance_section(ctx.get("tasks"), ctx.get("completions"), start, end, tank_l)
    awc_runs = [r for r in (ctx.get("awcHistory") if isinstance(ctx.get("awcHistory"), list) else [])
                if isinstance(r, dict) and _in(_parse(r.get("completedAt")), start, end)]
    feed_log = ctx.get("feedLog") if isinstance(ctx.get("feedLog"), dict) else {}
    feed_counts = feed_counts_in(feed_log, start, end)
    water = water_section(ctx.get("manualReadings"), ctx.get("sensorReadings"), ctx.get("paramMeta"), start, end)
    hatches = hatches_section(ctx.get("hatchHistory"), ctx.get("hatchVessels"), start, end)
    cultures = cultures_section(ctx.get("cultureJars"), start, end)
    corals = corals_section(ctx.get("corals"), ctx.get("checkins"), ctx.get("coralFeeds"), ctx.get("coralStates"), start, end)
    happened = events_section(ctx.get("events"), start, end)
    score = score_section(ctx.get("scoreLog"), start, end)
    plan_from = end if not period.get("partial") else now
    nxt = next_section(ctx.get("upcoming"), plan_from, 7 if period["kind"] == "week" else 14)
    report = {
        "version": 1,
        "generatedAt": now.isoformat(),
        "period": {"kind": period["kind"], "which": period["which"], "start": start.isoformat(),
                   "end": end.isoformat(), "label": period["label"], "partial": period["partial"],
                   "days": period["days"], "weekStart": period["weekStart"]},
        "headline": {"score": score, "verdict": ""},
        "did": {
            "maintenance": maintenance,
            "awc": {"runs": len(awc_runs), "partial": len([r for r in awc_runs if r.get("partial")]),
                    "drainedL": _round(sum(_f(r.get("drainedL")) for r in awc_runs)),
                    "filledL": _round(sum(_f(r.get("filledL")) for r in awc_runs))},
            "tests": {"count": sum(p["tests"] for p in water["parameters"]),
                      "parameters": [p["label"] for p in water["parameters"] if p["tests"]]},
            "feeds": {"count": int(_f(feed_counts.get("feeds"))), "hand": int(_f(feed_counts.get("hand"))),
                      "pump": int(_f(feed_counts.get("pump"))), "undone": int(_f(feed_counts.get("undone"))),
                      "available": bool(feed_log)},
            "hatches": hatches["harvested"], "cultureFeeds": cultures["feeds"], "coralCheckins": corals["checkins"],
        },
        "water": water,
        "living": {"hatches": hatches, "cultures": cultures, "corals": corals},
        "happened": happened,
        "next": nxt,
        "notes": [],
    }
    notes = report["notes"]
    if water["untested"]:
        notes.append(f"Not tested this period: {', '.join(water['untested'])}.")
    if score["gaps"] and score["stamps"]:
        notes.append(f"Reef Health was stamped on {score['stamps']} of {period['days']} days — the panel was closed on the rest.")
    elif not score["stamps"]:
        notes.append("No Reef Health stamps this period — open the panel once a day and the score line fills in.")
    if not feed_log:
        notes.append("Feeding log not available for this period.")
    if maintenance["timed"] == 0 and maintenance["done"]:
        notes.append("On-time rate needs a previous tick to compare against — it will read from next period.")
    report["headline"]["verdict"] = verdict(report)
    # Stage D: the Week Score and the small recommendations, both from the
    # compiled report so a fixture drives them too.
    report["score"] = week_score(report)
    report["recommendations"] = recommend(report, ctx.get("snoozedRecs"), now)
    return report
