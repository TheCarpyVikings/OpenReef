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
    return report
