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


def _day_text(value: Any) -> str:
    """"16 Sep" — the day a figure came from, for the copy that names it."""
    at = _parse(value)
    return f"{at.day} {at.strftime('%b')}" if at else ""


def _source_text(source: Any, label: str = "") -> str:
    return "the sensor" if source == "sensor" else "your test"


# --- the window ---------------------------------------------------------------

def period_bounds(now_local: datetime, week_start: int = 0, kind: str = "week",
                  which: str = "previous", anchor: date | None = None) -> dict[str, Any]:
    """The report window in the keeper's zone. ``kind`` week|month; ``which``
    previous (the last complete period) or current (the one in progress — a
    partial report, flagged). ``anchor`` picks the period containing that
    date instead (a stored week re-read from the ledgers). End is exclusive."""
    tz = now_local.tzinfo
    today = now_local.date()
    week_start = int(week_start) if isinstance(week_start, (int, float)) else 0
    week_start = max(0, min(6, week_start))
    if anchor is not None:
        which = "current" if anchor >= today else "anchored"
        today = anchor
    if kind == "month":
        first_this = today.replace(day=1)
        if which == "current" or which == "anchored":
            start_d = first_this
            end_d = (first_this.replace(day=28) + timedelta(days=4)).replace(day=1)
        else:
            end_d = first_this
            start_d = (first_this - timedelta(days=1)).replace(day=1)
    else:
        kind = "week"
        offset = (today.weekday() - week_start) % 7
        this_start = today - timedelta(days=offset)
        if which in ("current", "anchored"):
            start_d, end_d = this_start, this_start + timedelta(days=7)
        else:
            start_d, end_d = this_start - timedelta(days=7), this_start
    start = datetime(start_d.year, start_d.month, start_d.day, tzinfo=tz)
    end = datetime(end_d.year, end_d.month, end_d.day, tzinfo=tz)
    partial = which == "current" or (anchor is not None and end_d > now_local.date())
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
        t_done = t_skipped = t_late = t_timed = 0
        t_litres = 0.0
        t_slip: list[float] = []
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
                    t_timed += 1
                    if at - prev_done <= cadence + timedelta(hours=1):
                        on_time += 1
                    else:
                        t_late += 1
                        t_slip.append((at - prev_done - cadence).total_seconds() / 86400.0)
            prev_done = at
        if t_done or t_skipped:
            by_task.append({"id": task_id, "label": str(task.get("label") or task_id), "done": t_done,
                            "skipped": t_skipped, "late": t_late, "timed": t_timed,
                            "slipDays": _round(sum(t_slip) / len(t_slip)) if t_slip else None,
                            "litres": _round(t_litres) if t_litres else None,
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
        last_test = next((r for r in reversed(rows) if r[0] < end and r[2] == "test"), None)
        last_sensor = next((r for r in reversed(rows) if r[0] < end and r[2] == "sensor"), None)
        lo = info.get("min")
        hi = info.get("max")
        entry: dict[str, Any] = {
            "id": param, "label": str(info.get("label") or PARAM_LABELS.get(param, param)),
            "unit": str(info.get("unit") or ""),
            "tests": len([r for r in in_period if r[2] == "test"]),
            "sensorSamples": len([r for r in in_period if r[2] == "sensor"]),
            "latest": _round(latest_before_end[1], 3) if latest_before_end else None,
            "latestAt": latest_before_end[0].isoformat() if latest_before_end else None,
            # Where the latest figure came from — the copy names it, so a probe
            # reading 25 ppt is never mistaken for a refractometer's.
            "latestSource": latest_before_end[2] if latest_before_end else None,
            "latestTest": {"value": _round(last_test[1], 3), "at": last_test[0].isoformat()} if last_test else None,
            "latestSensor": {"value": _round(last_sensor[1], 3), "at": last_sensor[0].isoformat()} if last_sensor else None,
            "disagree": None, "farOut": False,
            "daysSince": _round((end - latest_before_end[0]).total_seconds() / 86400.0, 1) if latest_before_end else None,
            "range": {"min": lo, "max": hi} if isinstance(lo, (int, float)) and isinstance(hi, (int, float)) else None,
            "inRange": None, "band": "untested", "change": None, "low": None, "high": None,
            "points": [{"t": r[0].isoformat(), "v": _round(r[1], 3), "src": r[2]} for r in window][-40:],
        }
        if latest_before_end and entry["range"]:
            entry["inRange"] = bool(lo <= latest_before_end[1] <= hi)
            width = max(0.0, float(hi) - float(lo))
            entry["farOut"] = bool(latest_before_end[1] < lo - width or latest_before_end[1] > hi + width)
        # The probe against the kit: the sensor sample nearest the latest test
        # (within a day), apart by more than twice the steady tolerance.
        if last_test and last_test[0] >= min(start, trend_start):
            tol = STEADY_TOLERANCE.get(param, 0.0)
            near = [r for r in rows if r[2] == "sensor" and abs((r[0] - last_test[0]).total_seconds()) <= 86400]
            if tol and near:
                nearest = min(near, key=lambda r: abs((r[0] - last_test[0]).total_seconds()))
                gap = nearest[1] - last_test[1]
                if abs(gap) > 2 * tol:
                    entry["disagree"] = {"delta": _round(gap, 3), "test": _round(last_test[1], 3),
                                         "sensor": _round(nearest[1], 3), "at": last_test[0].isoformat()}
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
    added: list[dict[str, Any]] = []
    grades: dict[str, int] = {}
    for cid, coral in corals.items():
        if not isinstance(coral, dict):
            continue
        if _in(_parse(coral.get("addedAt")), start, end):
            added.append({"id": str(cid), "name": str(coral.get("name") or cid)})
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
    return {"colonies": len(corals), "checkins": n_checks, "feeds": n_feeds, "grades": grades, "moved": moved, "added": added}


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
                         "type": str(row.get("type") or "info"), "kind": row.get("kind"),
                         "count": max(1, int(_f(row.get("count"), 1)))})
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
         actions: list[dict[str, str]] | None = None, size: str = "small") -> dict[str, Any]:
    return {"id": rid, "size": size, "priority": priority, "title": title, "evidence": evidence,
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
            band = f"{rng.get('min')}–{rng.get('max')} {unit}".strip()
            when = _day_text(prm.get("latestAt"))
            dis = prm.get("disagree")
            if prm.get("latestSource") == "sensor" and (prm.get("farOut") or dis):
                # A probe far outside its band, or one the kit contradicts, is
                # a probe (or a unit) to check — never a tank to chase.
                said = (f"; your test on {_day_text(dis.get('at'))} said {dis.get('test')} {unit}".rstrip()
                        if dis else "")
                recs.append(_rec(f"check_{pid}", 11, f"Check the {label.lower()} reading",
                                 f"The sensor read {prm.get('latest')} {unit} on {when}, "
                                 f"{'far outside' if prm.get('farOut') else 'outside'} {band}{said}. "
                                 "A probe or a unit problem is likelier than the tank.",
                                 "5 min", "Nothing gets chased that was never wrong.",
                                 [{"action": "tab", "id": "settings", "label": "Check the sensor"}]))
            else:
                recs.append(_rec(f"range_{pid}", 12, f"Bring {label.lower()} back into range",
                                 f"Latest {prm.get('latest')} {unit} from {_source_text(prm.get('latestSource'))}"
                                 f"{' on ' + when if when else ''}; the range is {band}.",
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
    raised = sorted({r["id"] for r in recs})
    recs = [r for r in recs if r["id"] not in hidden]
    recs.sort(key=lambda r: (r["priority"], r["id"]))
    calm = not recs
    if calm:
        recs.append(_rec("keep_rhythm", 99, "Keep the rhythm", "Nothing in this period asked for a change.",
                         "none", "The reef likes it this way.", []))
    kept = recs[:SMALL_RECS_MAX]
    for r in kept:
        r.pop("priority", None)
    return {"items": kept, "calm": calm, "snoozed": sorted(hidden), "raised": raised, "size": "small"}


def snapshot(report: dict[str, Any]) -> dict[str, Any]:
    """The compact record a report leaves behind (brief §2.5): the headline
    numbers, the counts, one line per parameter, the recommendations by
    title — a few hundred bytes, kept for 26 weeks / 12 months where the
    ledgers it read will have rolled over."""
    period = report.get("period") or {}
    score = (report.get("headline") or {}).get("score") or {}
    ws = report.get("score") or {}
    did = report.get("did") or {}
    m = did.get("maintenance") or {}
    start = str(period.get("start") or "")
    return {
        "id": f"{period.get('kind', 'week')}:{start[:10]}",
        "kind": str(period.get("kind") or "week"), "start": start, "end": str(period.get("end") or ""),
        "label": str(period.get("label") or ""), "generatedAt": str(report.get("generatedAt") or ""),
        "weekScore": {"total": ws.get("total"), "condition": ws.get("condition"), "consistency": ws.get("consistency")},
        "health": {"average": score.get("average"), "latest": score.get("latest"), "delta": score.get("delta"), "stamps": score.get("stamps")},
        "verdict": str((report.get("headline") or {}).get("verdict") or ""),
        "did": {"done": m.get("done", 0), "skipped": m.get("skipped", 0), "onSchedule": m.get("onSchedule"),
                "waterChangedL": m.get("waterChangedL"), "awcRuns": (did.get("awc") or {}).get("runs", 0),
                "tests": (did.get("tests") or {}).get("count", 0), "feeds": (did.get("feeds") or {}).get("count", 0),
                "hatches": did.get("hatches", 0), "cultureFeeds": did.get("cultureFeeds", 0), "coralCheckins": did.get("coralCheckins", 0)},
        "water": [{"id": prm.get("id"), "latest": prm.get("latest"), "source": prm.get("latestSource"), "band": prm.get("band"),
                   "inRange": prm.get("inRange"), "consumption": (prm.get("consumption") or {}).get("perDay")}
                  for prm in (report.get("water") or {}).get("parameters") or []],
        "recommendations": [{"id": r.get("id"), "title": r.get("title")} for r in (report.get("recommendations") or {}).get("items") or []],
        "warnings": int(((report.get("happened") or {}).get("byType") or {}).get("warning") or 0),
        "nextCount": int((report.get("next") or {}).get("count") or 0),
        "notes": list(report.get("notes") or [])[:4],
    }


def push_text(report: dict[str, Any]) -> tuple[str, str]:
    """The headline block as a phone push (decision 4): score, delta, verdict,
    the counts, the top recommendation, where to read it."""
    period = report.get("period") or {}
    ws = report.get("score") or {}
    score = (report.get("headline") or {}).get("score") or {}
    did = report.get("did") or {}
    m = did.get("maintenance") or {}
    kind = "Monthly" if period.get("kind") == "month" else "Weekly"
    total = ws.get("total")
    title = f"OpenReef {kind} Reef Report · {period.get('label', '')}".strip()
    head = f"Week Score {total}" if total is not None and period.get("kind") != "month" else (f"Score {total}" if total is not None else "No score yet")
    if ws.get("condition") is not None and ws.get("consistency") is not None:
        head += f" (condition {ws['condition']} · consistency {ws['consistency']})"
    month_delta = ((report.get("month") or {}).get("trend") or {}).get("deltas", {}).get("total")
    if period.get("kind") == "month" and isinstance(month_delta, int) and month_delta:
        head += f", {'up' if month_delta > 0 else 'down'} {abs(month_delta)} on last month"
    if score.get("average") is not None:
        head += f" · Reef Health avg {int(score['average'])}"
        if score.get("delta") is not None and score["delta"] != 0:
            head += f", {'up' if score['delta'] > 0 else 'down'} {abs(int(score['delta']))}"
    counts = [f"{m.get('done', 0)} chores" + (f" ({int(m['onSchedule'])} % on time)" if m.get("onSchedule") is not None else "")]
    if m.get("waterChangedL"):
        counts.append(f"{m['waterChangedL']:g} L water changed")
    counts.append(f"{(did.get('tests') or {}).get('count', 0)} tests")
    recs = (report.get("recommendations") or {}).get("items") or []
    lines = [head, (report.get("headline") or {}).get("verdict") or "", " · ".join(counts)]
    if recs and recs[0].get("id") != "keep_rhythm":
        lines.append(f"Top: {recs[0].get('title')}")
    lines.append("Open OpenReef → Home → Reef Report.")
    return title, "\n".join(line for line in lines if line)


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


# --- The monthly report (Stage F, brief §3.2) -----------------------------------

# Readings behind a month: the two months before it, so the consumption trend
# has three calendar months to compare.
MONTH_LOOKBACK_DAYS = 92
BIG_RECS_MAX = 3

# Consumables, calibrations and services ranked by age (brief §3.2, Equipment
# ageing) — the built-in task ids; a keeper's own tasks are not guessed at.
AGEING_TASKS = {
    "replace_carbon": "consumable", "replace_gfo": "consumable", "replace_filter_sock": "consumable",
    "replace_rodi": "consumable", "calibrate_ph": "calibration", "calibrate_salinity": "calibration",
    "clean_pumps": "service", "inspect_ato": "service", "clean_skimmer": "service",
}
PROBE_CALIBRATION_TASK = {"ph": "calibrate_ph", "salinity": "calibrate_salinity"}


def lookback_days(kind: str) -> int:
    return MONTH_LOOKBACK_DAYS if kind == "month" else TREND_DAYS


def _month_start(d: date, back: int = 0) -> date:
    year, month = d.year, d.month - back
    while month <= 0:
        month += 12
        year -= 1
    return date(year, month, 1)


def _next_month(d: date) -> date:
    return (d.replace(day=28) + timedelta(days=4)).replace(day=1)


def _snap_num(row: Any, block: str, key: str) -> Any:
    inner = row.get(block) if isinstance(row.get(block), dict) else {}
    value = inner.get(key)
    return value if isinstance(value, (int, float)) and not isinstance(value, bool) else None


def trend_section(items: Any, period: dict[str, Any], this_score: dict[str, Any],
                  this_health: dict[str, Any]) -> dict[str, Any]:
    """The score over months: the stored monthly snapshots before this one
    plus this compile, month-over-month deltas, and the weeks stored inside
    the month. Only what was stored — a month never written up is a gap."""
    rows = [r for r in (items if isinstance(items, list) else []) if isinstance(r, dict)]
    start_d, end_d = period["start"].date(), period["end"].date()
    this_id = f"month:{start_d.isoformat()}"
    months: list[dict[str, Any]] = []
    weeks: list[dict[str, Any]] = []
    for r in rows:
        try:
            d = date.fromisoformat(str(r.get("start"))[:10])
        except ValueError:
            continue
        if r.get("kind") == "month" and r.get("id") != this_id and d < start_d:
            months.append({"id": r.get("id"), "label": str(r.get("label") or d.strftime("%B %Y")), "start": d.isoformat(),
                           "total": _snap_num(r, "weekScore", "total"), "condition": _snap_num(r, "weekScore", "condition"),
                           "consistency": _snap_num(r, "weekScore", "consistency"), "health": _snap_num(r, "health", "average")})
        elif r.get("kind") == "week" and start_d - timedelta(days=6) <= d < end_d:
            weeks.append({"start": d.isoformat(), "label": str(r.get("label") or ""), "total": _snap_num(r, "weekScore", "total")})
    months.sort(key=lambda m: m["start"])
    months = months[-5:]
    weeks.sort(key=lambda w: w["start"])
    current = {"id": this_id, "label": period["label"], "start": start_d.isoformat(), "current": True,
               "total": this_score.get("total"), "condition": this_score.get("condition"),
               "consistency": this_score.get("consistency"), "health": this_health.get("average")}
    prev = months[-1] if months else None
    deltas: dict[str, int | None] = {}
    for key in ("total", "condition", "consistency", "health"):
        a, b = (prev or {}).get(key), current.get(key)
        deltas[key] = int(round(b - a)) if isinstance(a, (int, float)) and isinstance(b, (int, float)) else None
    return {"months": months + [current], "deltas": deltas, "previous": prev["label"] if prev else None, "weeks": weeks}


def cadence_drift(maintenance: dict[str, Any]) -> dict[str, Any]:
    """Which chores slid (late ticks against the tick before, ranked by the
    share that were late) and which streaks held — from the month's own
    per-task rows, so every figure is a count."""
    late: list[dict[str, Any]] = []
    held: list[dict[str, Any]] = []
    for t in (maintenance.get("tasks") if isinstance(maintenance.get("tasks"), list) else []):
        if not isinstance(t, dict):
            continue
        done = int(t.get("done") or 0)
        timed = int(t.get("timed") or 0)
        n_late = int(t.get("late") or 0)
        if done < 2:
            continue
        share = n_late / timed if timed else 0.0
        if n_late and (n_late >= 2 or share >= 0.5):
            late.append({"id": t["id"], "label": t["label"], "done": done, "timed": timed, "late": n_late,
                         "skipped": int(t.get("skipped") or 0), "lateShare": _round(share * 100.0, 0),
                         "slipDays": t.get("slipDays")})
        elif not n_late and not t.get("skipped") and t.get("tracked"):
            held.append({"id": t["id"], "label": t["label"], "done": done})
    late.sort(key=lambda r: (-(r["lateShare"] or 0), -r["late"], r["label"]))
    held.sort(key=lambda r: (-r["done"], r["label"]))
    return {"late": late[:5], "held": held[:6]}


def consumption_trend(manual: Any, sensors: Any, meta: Any, period: dict[str, Any], months: int = 3) -> dict[str, Any]:
    """Alk / Ca / Mg demand per calendar month, this month and the two
    before — the median fall a day inside each month, from the same
    estimator the week uses. Rising demand is growth; falling is the doser
    or the corals to check. Needs two falling pairs in a month to say."""
    meta = meta if isinstance(meta, dict) else {}
    start_d = period["start"].date()
    tz = period["start"].tzinfo
    out: list[dict[str, Any]] = []
    for param in CONSUMED:
        rows = _readings_for(param, manual, sensors)
        blocks: list[dict[str, Any]] = []
        for back in range(months - 1, -1, -1):
            m0 = _month_start(start_d, back)
            m1 = _next_month(m0)
            s = datetime(m0.year, m0.month, m0.day, tzinfo=tz)
            e = datetime(m1.year, m1.month, m1.day, tzinfo=tz)
            window = [r for r in rows if _in(r[0], s, e)]
            est = consumption_per_day(window)
            blocks.append({"label": m0.strftime("%b"), "start": m0.isoformat(), "perDay": est["perDay"],
                           "pairs": est["pairs"], "readings": len(window)})
        known = [b for b in blocks if b["perDay"] is not None]
        change = None
        direction = "unknown"
        if len(known) >= 2 and known[0]["perDay"]:
            change = _round((known[-1]["perDay"] - known[0]["perDay"]) / known[0]["perDay"] * 100.0, 0)
            direction = "rising" if change >= 30 else "falling" if change <= -30 else "level"
        info = meta.get(param) if isinstance(meta.get(param), dict) else {}
        out.append({"id": param, "label": str(info.get("label") or PARAM_LABELS[param]), "unit": str(info.get("unit") or ""),
                    "months": blocks, "changePct": change, "direction": direction,
                    "from": known[0] if known else None, "to": known[-1] if known else None})
    return {"parameters": out}


def water_ledger(maintenance: dict[str, Any], awc: dict[str, Any], plan_daily_l: Any, usual_weekly_l: Any,
                 tank_l: float, days: int, salt_state: Any, salt_history: Any,
                 start: datetime, end: datetime) -> dict[str, Any]:
    """Water changed against the AWC's plan (when a schedule is on) and
    against the keeper's recent rate; salt used from the stock ledger's
    debits and what is left. Nothing here is a target OpenReef invented."""
    changed = _f(maintenance.get("waterChangedL"))
    planned = _round(_f(plan_daily_l) * days) if _f(plan_daily_l) > 0 else None
    usual = _round(_f(usual_weekly_l) * days / 7.0) if _f(usual_weekly_l) > 0 else None
    met = None if planned is None else bool(changed >= planned * 0.9)
    salt_state = salt_state if isinstance(salt_state, dict) else {}
    used = 0.0
    for row in (salt_history if isinstance(salt_history, list) else []):
        if not isinstance(row, dict):
            continue
        delta = _f(row.get("delta"))
        if delta < 0 and _in(_parse(row.get("at")), start, end):
            used -= delta
    return {
        "changedL": _round(changed), "handL": _round(_f(maintenance.get("handL"))), "autoL": _round(_f(maintenance.get("autoL"))),
        "pctOfTank": _round(changed / tank_l * 100.0, 0) if tank_l > 0 and changed else None,
        "awcRuns": int(_f(awc.get("runs"))), "plannedL": planned, "met": met,
        "shortfallL": _round(planned - changed) if planned is not None and changed < planned else None,
        "usualL": usual,
        "salt": {"tracked": bool(salt_state.get("tracked")), "usedKg": _round(used, 2) if used else None,
                 "onHandKg": salt_state.get("kg") if salt_state.get("tracked") else None,
                 "weeksLeft": salt_state.get("weeksLeft") if salt_state.get("tracked") else None,
                 "low": bool(salt_state.get("low") or salt_state.get("empty"))},
    }


def testing_discipline(manual: Any, schedules: Any, meta: Any, start: datetime, end: datetime) -> dict[str, Any]:
    """Tests per parameter against the cadence the keeper set (Settings →
    Manual tests), the longest gap, and the weekday the keeper's tests
    actually land on — the honest suggestion for a test day."""
    meta = meta if isinstance(meta, dict) else {}
    days = (end - start).days or 1
    tz = start.tzinfo
    params: list[dict[str, Any]] = []
    weekday_counts = [0] * 7
    total_tests = 0
    for param, rows in (manual if isinstance(manual, dict) else {}).items():
        for at, _v, _s in _readings_for(str(param), {param: rows}, {}):
            if _in(at, start, end):
                weekday_counts[(at.astimezone(tz) if tz else at).weekday()] += 1
                total_tests += 1
    expected_total = 0
    for param, sched in (schedules if isinstance(schedules, dict) else {}).items():
        if not isinstance(sched, dict) or not sched.get("enabled"):
            continue
        cadence = max(1, int(_f(sched.get("cadenceDays"), 14)))
        stamps = sorted(r[0] for r in _readings_for(str(param), manual, {}) if _in(r[0], start, end))
        expected = max(1, int(round(days / cadence)))
        expected_total += expected
        gaps: list[float] = []
        prev = start
        for at in [*stamps, end]:
            gaps.append((at - prev).total_seconds() / 86400.0)
            prev = at
        longest = max(gaps) if gaps else float(days)
        info = meta.get(param) if isinstance(meta.get(param), dict) else {}
        params.append({"id": str(param), "label": str(info.get("label") or PARAM_LABELS.get(str(param), param)),
                       "cadenceDays": cadence, "expected": expected, "tests": len(stamps),
                       "ratio": _round(min(1.0, len(stamps) / expected) * 100.0, 0),
                       "longestGapDays": _round(longest, 0), "onCadence": bool(longest <= cadence * 1.5)})
    params.sort(key=lambda p: (p["ratio"], p["label"]))
    overall = _round(sum(p["ratio"] for p in params) / len(params), 0) if params else None
    best = max(range(7), key=lambda i: weekday_counts[i]) if total_tests else None
    return {"parameters": params, "scheduled": len(params), "overallRatio": overall,
            "tests": total_tests, "expected": expected_total,
            "bestDay": DAY_NAMES[best] if best is not None else None,
            "bestDayShare": _round(weekday_counts[best] / total_tests * 100.0, 0) if total_tests else None}


def _icp_brief(at: datetime, row: dict[str, Any]) -> dict[str, Any]:
    els = [e for e in (row.get("elements") if isinstance(row.get("elements"), list) else []) if isinstance(e, dict)]
    flagged = [{"symbol": e.get("symbol"), "name": e.get("name"), "value": e.get("value"), "unit": e.get("unit"),
                "status": e.get("status")} for e in els if e.get("status") in ("low", "high", "contaminant")]
    return {"id": row.get("id"), "lab": row.get("lab"), "date": at.date().isoformat(), "elements": len(els),
            "flagged": flagged[:12], "flaggedCount": len(flagged)}


def icp_section(reports: Any, start: datetime, end: datetime) -> dict[str, Any]:
    """The month's ICP against the one before it: the elements that moved
    materially (15 % or a unit floor) or changed status. No ICP in the
    month: how long since the last, and nothing compared."""
    rows: list[tuple[datetime, dict[str, Any]]] = []
    for r in (reports if isinstance(reports, list) else []):
        if not isinstance(r, dict) or r.get("sampleType") == "rodi":
            continue
        at = _parse(r.get("sampleDate")) or _parse(r.get("importedAt"))
        if at is not None:
            rows.append((at, r))
    rows.sort(key=lambda p: p[0])
    before_end = [p for p in rows if p[0] < end]
    latest = before_end[-1] if before_end else None
    previous = before_end[-2] if len(before_end) >= 2 else None
    in_period = bool(latest and _in(latest[0], start, end))
    movers: list[dict[str, Any]] = []
    if in_period and latest and previous:
        prev_by = {e.get("symbol"): e for e in (previous[1].get("elements") or []) if isinstance(e, dict)}
        for e in (latest[1].get("elements") or []):
            if not isinstance(e, dict):
                continue
            pe = prev_by.get(e.get("symbol"))
            if not pe:
                continue
            a, b = pe.get("value"), e.get("value")
            if not all(isinstance(v, (int, float)) and not isinstance(v, bool) for v in (a, b)):
                continue
            unit = str(e.get("unit") or "")
            floor = 0.02 if e.get("symbol") == "PO4" else 0.5 if unit == "dKH" else 1.0 if unit == "ppm" else 5.0 if unit == "ppb" else 0.0
            material = abs(b - a) >= max(floor, (abs(a) + abs(b)) / 2.0 * 0.15)
            if material or e.get("status") != pe.get("status"):
                movers.append({"symbol": e.get("symbol"), "name": e.get("name"), "from": _round(a, 3), "to": _round(b, 3),
                               "unit": unit, "pct": _round((b - a) / a * 100.0, 0) if a else None,
                               "statusFrom": pe.get("status"), "statusTo": e.get("status")})
        movers.sort(key=lambda m: -abs(m["pct"] or 0))
    return {"any": bool(rows), "inPeriod": in_period,
            "latest": _icp_brief(*latest) if latest else None, "previous": _icp_brief(*previous) if previous else None,
            "movers": movers[:8], "daysSinceLast": _round((end - latest[0]).total_seconds() / 86400.0, 0) if latest else None}


def equipment_ageing(tasks: Any, completions: Any, end: datetime, filters: Any) -> dict[str, Any]:
    """Consumables, calibrations and services by age against their cadence,
    and the RODI stages by litres through them. Ranked worst first; a task
    never logged says so rather than pretending an age."""
    tasks = tasks if isinstance(tasks, dict) else {}
    completions = completions if isinstance(completions, dict) else {}
    items: list[dict[str, Any]] = []
    for task_id, task in tasks.items():
        kind = AGEING_TASKS.get(str(task_id))
        if not kind or not isinstance(task, dict):
            continue
        rows = [r for r in (completions.get(task_id) or []) if isinstance(r, dict) and not r.get("skipped")]
        if not task.get("enabled") and not rows:
            continue
        cadence = _f(task.get("cadenceDays"), 30.0) or 30.0
        done = [d for d in (_parse(r.get("timestamp") or r.get("date")) for r in rows) if d is not None and d < end]
        last = max(done) if done else None
        age = (end - last).total_seconds() / 86400.0 if last else None
        ratio = age / cadence if age is not None else None
        status = "never" if last is None else "overdue" if ratio >= 1.5 else "due" if ratio >= 1.0 else "ok"
        items.append({"id": str(task_id), "label": str(task.get("label") or task_id), "kind": kind, "cadenceDays": int(cadence),
                      "lastAt": last.isoformat() if last else None, "ageDays": _round(age, 0), "ratio": _round(ratio, 2), "status": status})
    items.sort(key=lambda i: (0 if i["ratio"] is not None else 1, -(i["ratio"] or 0), i["label"]))
    stages: list[dict[str, Any]] = []
    for f in (filters if isinstance(filters, list) else []):
        if not isinstance(f, dict):
            continue
        rated, used = _f(f.get("ratedLitres")), _f(f.get("litresProcessed"))
        changed = _parse(f.get("changedAt"))
        stages.append({"id": str(f.get("id") or ""), "label": str(f.get("label") or f.get("type") or "filter"),
                       "usedPct": _round(used / rated * 100.0, 0) if rated > 0 else None, "litres": _round(used, 0),
                       "ageDays": _round((end - changed).total_seconds() / 86400.0, 0) if changed else None,
                       "status": ("overdue" if used >= rated else "due" if used >= rated * 0.8 else "ok") if rated > 0 else "untracked"})
    return {"items": items, "filters": stages}


def goals_check(previous: Any, raised: set[str]) -> dict[str, Any]:
    """What last month's report recommended and whether it happened: a
    recommendation the rules no longer raise is cleared; one they still
    raise is open. Read from the stored snapshot, judged by this compile."""
    prev = previous if isinstance(previous, dict) else None
    if not prev:
        return {"from": None, "items": [], "cleared": 0, "open": 0}
    items = []
    for rec in (prev.get("recommendations") if isinstance(prev.get("recommendations"), list) else []):
        rid = str((rec or {}).get("id") or "") if isinstance(rec, dict) else ""
        if not rid or rid == "keep_rhythm":
            continue
        items.append({"id": rid, "title": str(rec.get("title") or rid), "status": "open" if rid in raised else "cleared"})
    return {"from": prev.get("label"), "items": items,
            "cleared": len([i for i in items if i["status"] == "cleared"]), "open": len([i for i in items if i["status"] == "open"])}


def month_sections(ctx: dict[str, Any], report: dict[str, Any]) -> dict[str, Any]:
    period = ctx["period"]
    start, end = period["start"], period["end"]
    m = report["did"]["maintenance"]
    return {
        "trend": trend_section(ctx.get("items"), period, report.get("score") or {}, report["headline"]["score"]),
        "drift": cadence_drift(m),
        "consumption": consumption_trend(ctx.get("manualReadings"), ctx.get("sensorReadings"), ctx.get("paramMeta"), period),
        "water": water_ledger(m, report["did"]["awc"], ctx.get("awcPlanDailyL"), ctx.get("usualWeeklyL"), _f(ctx.get("tankL")),
                              int(period["days"]), ctx.get("saltState"), ctx.get("saltHistory"), start, end),
        "testing": testing_discipline(ctx.get("manualReadings"), ctx.get("testSchedules"), ctx.get("paramMeta"), start, end),
        "icp": icp_section(ctx.get("icpReports"), start, end),
        "ageing": equipment_ageing(ctx.get("tasks"), ctx.get("completions"), end, ctx.get("rodiFilters")),
    }


def recommend_big(report: dict[str, Any], snoozed: Any = None, now: datetime | None = None,
                  history: Any = None) -> dict[str, Any]:
    """The structural recommendations a month of evidence supports (brief
    §5, big): each names the month's figures, the effort, the effect and the
    screen. Capped at three; snoozed ids stay out; one recommended three
    months running is promoted to the top and says so."""
    now = now or datetime.now(timezone.utc)
    snoozed = snoozed if isinstance(snoozed, dict) else {}
    hidden = {rid for rid, until in snoozed.items() if (_parse(until) or now) > now}
    month = report.get("month") or {}
    water = report.get("water") or {}
    living = report.get("living") or {}
    recs: list[dict[str, Any]] = []

    def big(rid: str, pri: int, title: str, evidence: str, effort: str, effect: str, actions: list[dict[str, str]]) -> None:
        recs.append(_rec(rid, pri, title, evidence, effort, effect, actions, size="big"))

    ageing_by = {i["id"]: i for i in (month.get("ageing") or {}).get("items") or []}
    for prm in water.get("parameters") or []:
        dis = prm.get("disagree")
        task_id = PROBE_CALIBRATION_TASK.get(str(prm.get("id")))
        if not dis or not task_id:
            continue
        age = ageing_by.get(task_id) or {}
        if age.get("status") in (None, "never", "due", "overdue") or (age.get("ageDays") or 0) >= 60:
            big(f"calibrate_{prm['id']}", 8, f"Recalibrate the {str(prm.get('label')).lower()} probe",
                f"The probe and the kit disagree by {abs(_f(dis.get('delta'))):g} {prm.get('unit') or ''}".rstrip()
                + (f"; last calibrated {age['ageDays']:g} days ago." if age.get("ageDays") is not None else "; no calibration logged."),
                "15 min", "One number for the tank, not two.",
                [{"action": "report-task", "id": task_id, "label": "Open the task"}])
    hatches = living.get("hatches") or {}
    if (hatches.get("harvested") or 0) >= 4 and (hatches.get("avgLateHours") or 0) > 6:
        big("hatch_capacity", 10, "Add a hatchery or lengthen the hatch cadence",
            f"{hatches['harvested']} harvests ran {hatches['avgLateHours']:g} h past the clock on average this month.",
            "an evening", "Brine at its yolkiest without chasing the clock.",
            [{"action": "tab", "id": "hatchery", "label": "Open the hatchery"}])
    for prm in (month.get("consumption") or {}).get("parameters") or []:
        frm, to = prm.get("from") or {}, prm.get("to") or {}
        if prm.get("direction") == "rising":
            big(f"demand_up_{prm['id']}", 12, f"Raise the daily {str(prm['label']).lower()} plan — the corals are growing",
                f"Consumption {frm.get('perDay'):g} → {to.get('perDay'):g} {prm.get('unit')}/day, {frm.get('label')} to {to.get('label')} (+{prm.get('changePct'):g} %).",
                "10 min", "The line stops sagging between tests.", [{"action": "tab", "id": "dosing", "label": "Open dosing"}])
        elif prm.get("direction") == "falling":
            big(f"demand_down_{prm['id']}", 14, f"Check the doser and the corals — {str(prm['label']).lower()} demand fell",
                f"Consumption {frm.get('perDay'):g} → {to.get('perDay'):g} {prm.get('unit')}/day, {frm.get('label')} to {to.get('label')} ({prm.get('changePct'):g} %).",
                "15 min", "A stalled pump or a sulking colony found this month, not next.",
                [{"action": "tab", "id": "dosing", "label": "Open dosing"}])
    ledger = month.get("water") or {}
    if ledger.get("plannedL") and _f(ledger.get("changedL")) < _f(ledger.get("plannedL")) * 0.75:
        big("water_plan", 16, "Raise the AWC volume or lower its plan — pick one",
            f"{_f(ledger.get('changedL')):g} L changed against {_f(ledger.get('plannedL')):g} L planned.",
            "5 min", "A plan the tank actually gets.", [{"action": "tab", "id": "awc", "label": "Open AWC"}])
    testing = month.get("testing") or {}
    if (testing.get("scheduled") or 0) >= 2 and testing.get("overallRatio") is not None and testing["overallRatio"] < 60:
        best = testing.get("bestDay")
        big("test_day", 18, "Set a test day" + (f" — {best} fits your completions" if best else ""),
            f"{testing.get('tests', 0)} of {testing.get('expected', 0)} scheduled tests logged this month"
            + (f"; {testing.get('bestDayShare'):g} % of the ones you did fell on a {best}." if best else "."),
            "no extra time", "Every parameter with a trend; the chemistry part of the score filled in.",
            [{"action": "tab", "id": "manual", "label": "Log a test"}])
    salt = ledger.get("salt") or {}
    if salt.get("tracked") and salt.get("weeksLeft") is not None and _f(salt.get("weeksLeft")) < 8:
        big("salt_stock", 20, "Order salt",
            f"About {_f(salt.get('weeksLeft')):g} weeks of salt left at your water-change rate ({_f(salt.get('onHandKg')):g} kg).",
            "5 min", "No batch waits on a delivery.", [{"action": "tab", "id": "mixing", "label": "Open the mixing station"}])
    for row in (month.get("drift") or {}).get("late") or []:
        if row.get("done", 0) >= 3 and (row.get("lateShare") or 0) >= 50:
            big(f"cadence_{row['id']}", 22, f"Lengthen {row['label']}'s cadence or fix its day",
                f"{row['late']} of {row.get('timed') or row['done']} ticks came late"
                + (f", {row['slipDays']:g} d past the cadence on average." if row.get("slipDays") is not None else "."),
                "2 min", "A chore that stops sliding — or a cadence that tells the truth.",
                [{"action": "report-task", "id": row["id"], "label": "Open the task"}])
    for item in (month.get("ageing") or {}).get("items") or []:
        if item.get("status") == "overdue":
            big(f"ageing_{item['id']}", 24, f"{item['label']}: {item['ageDays']:g} days on a {item['cadenceDays']}-day cadence",
                f"Last logged {_day_text(item.get('lastAt'))}.", "varies", "Media doing its job; a probe reading the truth.",
                [{"action": "report-task", "id": item["id"], "label": "Open the task"}])
    for stage in (month.get("ageing") or {}).get("filters") or []:
        if stage.get("status") == "overdue":
            big(f"filter_{stage['id'] or stage['label']}", 26, f"Change the {stage['label']} — {stage['usedPct']:g} % of its rated litres",
                f"{stage['litres']:g} L through it.", "20 min", "RODI that is actually pure.",
                [{"action": "tab", "id": "mixing", "label": "Open the mixing station"}])
    icp = month.get("icp") or {}
    if icp.get("any") and not icp.get("inPeriod") and (icp.get("daysSinceLast") or 0) >= 120:
        big("icp_due", 30, "Send off an ICP sample", f"The last ICP was {icp['daysSinceLast']:g} days ago.",
            "a sample and a stamp", "Trace elements checked against a lab, not a guess.",
            [{"action": "tab", "id": "icp", "label": "Open ICP"}])
    raised = sorted({r["id"] for r in recs})
    # Promotion: recommended in the two stored months before this one too.
    earlier = [set(str((rec or {}).get("id") or "") for rec in (snap.get("recommendations") or []) if isinstance(rec, dict))
               for snap in (history if isinstance(history, list) else [])[:2] if isinstance(snap, dict)]
    for r in recs:
        if len(earlier) >= 2 and all(r["id"] in ids for ids in earlier):
            r["promoted"] = True
            r["priority"] = -1
            r["evidence"] = r["evidence"].rstrip() + " Third month running."
    recs = [r for r in recs if r["id"] not in hidden]
    recs.sort(key=lambda r: (r["priority"], r["id"]))
    calm = not recs
    if calm:
        recs.append(_rec("keep_rhythm", 99, "Keep the rhythm", "Nothing in this month asked for a change.",
                         "none", "The reef likes it this way.", [], size="big"))
    kept = recs[:BIG_RECS_MAX]
    for r in kept:
        r.pop("priority", None)
    return {"items": kept, "calm": calm, "snoozed": sorted(hidden), "raised": raised, "size": "big"}


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
    -- month reports (Stage F) --
    items                         the stored snapshots (reports.items)
    testSchedules                 manualTests.schedules
    icpReports                    icpReports
    saltState, saltHistory        mixing salt stock state + its ledger
    rodiFilters                   mixingStation.rodi.filters
    awcPlanDailyL, usualWeeklyL   the AWC schedule's litres a day; the keeper's recent weekly litres
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
    if period["kind"] == "month":
        # Stage F: the month's own sections, the BIG recommendations, and
        # last month's recommendations checked against this compile.
        report["month"] = month_sections(ctx, report)
        start_d = start.date()
        history = sorted((r for r in (ctx.get("items") if isinstance(ctx.get("items"), list) else [])
                          if isinstance(r, dict) and r.get("kind") == "month" and str(r.get("start") or "")[:10] < start_d.isoformat()),
                         key=lambda r: str(r.get("start")), reverse=True)
        big = recommend_big(report, ctx.get("snoozedRecs"), now, history)
        small = recommend(report, ctx.get("snoozedRecs"), now)
        report["month"]["goals"] = goals_check(history[0] if history else None, set(big["raised"]) | set(small["raised"]))
        report["recommendations"] = big
    else:
        report["recommendations"] = recommend(report, ctx.get("snoozedRecs"), now)
    return report


# --- Share (Stage G, brief §7 G) -------------------------------------------------
# One rendition of the report as text — the panel copies it as Markdown, the
# backend sends it plain to a notify target (Telegram, the companion app) in
# chunks under Telegram's message limit. Built from the compiled report only,
# so the shared text and the viewer never disagree.

SHARE_CHUNK_LIMIT = 3800
BAND_WORDS = {"steady": "steady", "drifting": "drifting", "swinging": "swinging", "single": "one reading", "untested": "not tested"}


def _fmt(value: Any, digits: int = 1) -> str:
    if value is None or isinstance(value, bool):
        return "—"
    if isinstance(value, (int, float)):
        number = round(float(value), digits)
        return f"{int(number)}" if number.is_integer() else f"{number:g}"
    return str(value)


def _delta_words(delta: Any, against: str) -> str:
    if not isinstance(delta, (int, float)) or isinstance(delta, bool):
        return ""
    if delta == 0:
        return f"level with {against}"
    return f"{'up' if delta > 0 else 'down'} {abs(int(round(delta)))} on {against}"


def text_blocks(report: dict[str, Any]) -> list[tuple]:
    """The report as blocks: ("title", text), ("h", text), ("lines", [..]),
    ("ul", [..]), ("table", [headers], [[cells]..]). Every section the
    viewer shows, in its order, with nothing the ledgers did not say."""
    period = report.get("period") or {}
    month = period.get("kind") == "month"
    kind = "Monthly" if month else "Weekly"
    ws = report.get("score") or {}
    hs = (report.get("headline") or {}).get("score") or {}
    did = report.get("did") or {}
    m = did.get("maintenance") or {}
    awc = did.get("awc") or {}
    tests = did.get("tests") or {}
    feeds = did.get("feeds") or {}
    blocks: list[tuple] = [("title", f"{kind} Reef Report · {period.get('label', '')}".strip() + (" (in progress)" if period.get("partial") else ""))]
    head: list[str] = []
    if ws.get("total") is not None:
        line = f"{'Month' if month else 'Week'} Score {ws['total']}/100"
        if ws.get("condition") is not None and ws.get("consistency") is not None:
            line += f" (condition {ws['condition']} · consistency {ws['consistency']})"
        trend_delta = ((report.get("month") or {}).get("trend") or {}).get("deltas", {}).get("total")
        if month and isinstance(trend_delta, int):
            line += f", {_delta_words(trend_delta, 'last month')}"
        head.append(line)
    if hs.get("average") is not None:
        line = f"Reef Health average {int(hs['average'])}/100"
        if hs.get("delta") is not None:
            line += f", {_delta_words(hs['delta'], 'the period before')}"
        line += f" · stamped on {hs.get('stamps', 0)} of {period.get('days', 7)} days"
        head.append(line)
    verdict = (report.get("headline") or {}).get("verdict")
    if verdict:
        head.append(str(verdict))
    blocks.append(("lines", head))
    recs = report.get("recommendations") or {}
    items = recs.get("items") or []
    if items:
        calm = bool(recs.get("calm"))
        blocks.append(("h", ("This month" if month else "This week") if calm else f"Recommendations · {recs.get('size') or 'small'}"))
        blocks.append(("ul", [f"{r.get('title')}" + (" (third month running)" if r.get("promoted") else "")
                              + f" — {r.get('evidence')}" + (f" ({r.get('effort')} · {r.get('effect')})" if r.get("effort") else "")
                              for r in items]))
    mn = report.get("month") if month and isinstance(report.get("month"), dict) else None
    if mn:
        goals = mn.get("goals") or {}
        blocks.append(("h", "Last month's plan"))
        if goals.get("items"):
            blocks.append(("ul", [f"{g.get('title')} — {'cleared' if g.get('status') == 'cleared' else 'still open'}" for g in goals["items"]]))
        else:
            blocks.append(("lines", ["Nothing to check — last month asked for no change." if goals.get("from") else "No stored month before this one."]))
        trend = mn.get("trend") or {}
        months = trend.get("months") or []
        if len(months) > 1:
            blocks.append(("h", "Score over months"))
            blocks.append(("table", ["Month", "Score", "Condition", "Consistency", "Reef Health"],
                           [[str(x.get("label")), _fmt(x.get("total"), 0), _fmt(x.get("condition"), 0), _fmt(x.get("consistency"), 0), _fmt(x.get("health"), 0)] for x in months]))
    blocks.append(("h", "What you did"))
    lines = [f"{m.get('done', 0)} chores ticked off" + (f", {m['skipped']} skipped" if m.get("skipped") else "")
             + (f", {int(m['onSchedule'])} % on time" if m.get("onSchedule") is not None else "")]
    if m.get("waterChangedL"):
        lines.append(f"Water changed {_fmt(m['waterChangedL'])} L ({_fmt(m.get('handL'))} L by hand, {_fmt(m.get('autoL'))} L auto"
                     + (f", {_fmt(m['waterChangedPct'], 0)} % of the tank" if m.get("waterChangedPct") else "") + ")")
    if awc.get("runs"):
        lines.append(f"{awc['runs']} automatic change{'s' if awc['runs'] != 1 else ''}, {_fmt(awc.get('drainedL'))} L drained")
    lines.append(f"{tests.get('count', 0)} test{'s' if tests.get('count', 0) != 1 else ''}" + (f": {', '.join(tests.get('parameters') or [])}" if tests.get("parameters") else ""))
    if feeds.get("available"):
        lines.append(f"{feeds.get('count', 0)} feeds ({feeds.get('hand', 0)} by hand, {feeds.get('pump', 0)} by pump)")
    blocks.append(("lines", lines))
    task_rows = [[str(t.get("label")), str(t.get("done", 0)), str(t.get("late") or ""), str(t.get("skipped") or ""),
                  f"{_fmt(t['litres'])} L" if t.get("litres") else ""] for t in m.get("tasks") or []]
    if task_rows:
        blocks.append(("table", ["Task", "Done", "Late", "Skipped", "Water"], task_rows))
    if mn:
        drift = mn.get("drift") or {}
        if drift.get("late") or drift.get("held"):
            blocks.append(("h", "Cadence drift"))
            if drift.get("late"):
                blocks.append(("ul", [f"{t.get('label')}: {t.get('late')} of {t.get('timed') or t.get('done')} late"
                                      + (f", {_fmt(t['slipDays'])} d past the cadence on average" if t.get("slipDays") is not None else "")
                                      for t in drift["late"]]))
            if drift.get("held"):
                blocks.append(("lines", ["Streaks held: " + ", ".join(f"{h.get('label')} ({h.get('done')})" for h in drift["held"])]))
    water = report.get("water") or {}
    rows = []
    for p in water.get("parameters") or []:
        unit = str(p.get("unit") or "")
        latest = "—"
        if p.get("latest") is not None:
            latest = f"{_fmt(p['latest'], 3)} {unit}".strip()
            if p.get("latestAt"):
                latest += f" ({'sensor' if p.get('latestSource') == 'sensor' else 'test'}, {_day_text(p.get('latestAt'))})"
        rng = "" if p.get("inRange") is None else ("in range" if p["inRange"] else "OUT OF RANGE")
        cons = p.get("consumption") or {}
        cons_text = f"{_fmt(cons['perDay'], 3)} {unit}/day est." if cons.get("perDay") is not None else ""
        rows.append([str(p.get("label")), latest, BAND_WORDS.get(str(p.get("band")), str(p.get("band") or "")), rng, cons_text])
    if rows:
        blocks.append(("h", "Water"))
        blocks.append(("table", ["Parameter", "Latest", "Stability", "Range", "Consumption"], rows))
    if water.get("untested"):
        blocks.append(("lines", [f"Not tested this period: {', '.join(water['untested'])}."]))
    if mn:
        cons = (mn.get("consumption") or {}).get("parameters") or []
        if any(any(b.get("perDay") is not None for b in p.get("months") or []) for p in cons):
            blocks.append(("h", "Consumption trend"))
            blocks.append(("table", ["Parameter", *[b.get("label") for b in (cons[0].get("months") or [])], "Change"],
                           [[f"{p.get('label')} ({p.get('unit')}/day)", *[_fmt(b.get("perDay"), 3) for b in p.get("months") or []],
                             (f"{p.get('direction')}" + (f" ({'+' if p['changePct'] > 0 else ''}{_fmt(p['changePct'], 0)} %)" if p.get("changePct") is not None else ""))]
                            for p in cons]))
        ledger = mn.get("water") or {}
        blocks.append(("h", "Water ledger"))
        wl = [f"{_fmt(ledger.get('changedL'))} L changed ({_fmt(ledger.get('handL'))} L by hand, {_fmt(ledger.get('autoL'))} L auto"
              + (f", {_fmt(ledger['pctOfTank'], 0)} % of the tank" if ledger.get("pctOfTank") else "") + ")"]
        if ledger.get("plannedL"):
            wl.append(f"Against the AWC plan: {_fmt(ledger['plannedL'])} L planned — " + ("met" if ledger.get("met") else f"{_fmt(ledger.get('shortfallL'))} L short"))
        elif ledger.get("usualL"):
            wl.append(f"Your recent rate says {_fmt(ledger['usualL'])} L a month.")
        salt = ledger.get("salt") or {}
        if salt.get("tracked"):
            wl.append(f"Salt: {_fmt(salt.get('usedKg'), 2) if salt.get('usedKg') else 'none'} used, {_fmt(salt.get('onHandKg'))} kg on hand"
                      + (f", about {_fmt(salt['weeksLeft'], 0)} weeks at your rate" if salt.get("weeksLeft") is not None else "") + ".")
        blocks.append(("lines", wl))
        testing = mn.get("testing") or {}
        if testing.get("parameters"):
            blocks.append(("h", "Testing discipline"))
            blocks.append(("table", ["Parameter", "Tests", "Longest gap", "Cadence"],
                           [[str(p.get("label")), f"{p.get('tests')} of {p.get('expected')} (every {p.get('cadenceDays')} d)",
                             f"{_fmt(p.get('longestGapDays'), 0)} d", "kept" if p.get("onCadence") else "slipped"] for p in testing["parameters"]]))
            if testing.get("bestDay"):
                blocks.append(("lines", [f"Your tests land on a {testing['bestDay']} ({_fmt(testing.get('bestDayShare'), 0)} % of them)."]))
        icp = mn.get("icp") or {}
        blocks.append(("h", "ICP"))
        if not icp.get("any"):
            blocks.append(("lines", ["No ICP reports imported yet."]))
        elif not icp.get("inPeriod"):
            latest = icp.get("latest") or {}
            blocks.append(("lines", [f"No ICP this month — the last ({latest.get('lab')}, {latest.get('date')}) was {_fmt(icp.get('daysSinceLast'), 0)} days before the month's end."]))
        else:
            latest = icp.get("latest") or {}
            prev = icp.get("previous")
            blocks.append(("lines", [f"{latest.get('lab')} · {latest.get('date')} · {latest.get('elements')} elements · "
                                     + (f"{latest.get('flaggedCount')} flagged: " + ", ".join(f"{f.get('name') or f.get('symbol')} {_fmt(f.get('value'), 3)} {f.get('unit') or ''} {f.get('status')}".strip() for f in latest.get("flagged") or []) if latest.get("flaggedCount") else "nothing flagged")
                                     + (f" · against {prev.get('lab')} · {prev.get('date')}" if prev else " · no earlier ICP to compare")]))
            if icp.get("movers"):
                blocks.append(("table", ["Moved", "Before", "Now", "Change"],
                               [[str(mv.get("name") or mv.get("symbol")), f"{_fmt(mv.get('from'), 3)} {mv.get('unit') or ''} {mv.get('statusFrom') or ''}".strip(),
                                 f"{_fmt(mv.get('to'), 3)} {mv.get('unit') or ''} {mv.get('statusTo') or ''}".strip(),
                                 f"{'+' if (mv.get('pct') or 0) > 0 else ''}{_fmt(mv.get('pct'), 0)} %" if mv.get("pct") is not None else "—"] for mv in icp["movers"]]))
    living = report.get("living") or {}
    h = living.get("hatches") or {}
    c = living.get("cultures") or {}
    co = living.get("corals") or {}
    live_lines = []
    if h.get("harvested") or h.get("started"):
        live_lines.append(f"Hatchery: {h.get('harvested', 0)} harvest{'s' if h.get('harvested', 0) != 1 else ''}, {h.get('started', 0)} started"
                          + (f", ~{_fmt(h['avgActualHours'], 0)} h a hatch" if h.get("avgActualHours") else "")
                          + (f", {_fmt(h['avgLateHours'])} h past the clock on average" if (h.get("avgLateHours") or 0) > 0 else ""))
    for jar in c.get("jars") or []:
        live_lines.append(f"{jar.get('name')}: {jar.get('feeds', 0)} feeds, {jar.get('looks', 0)} looks, {jar.get('harvests', 0)} harvests"
                          + (f", {jar['skips']} skipped" if jar.get("skips") else "") + (f", {jar['signs']} sign{'s' if jar['signs'] != 1 else ''}" if jar.get("signs") else "")
                          + (", crashed" if jar.get("crashed") else "") + (", restarted" if jar.get("restarts") else ""))
    if co.get("colonies"):
        grades = ", ".join(f"{n} × {g}" for g, n in sorted((co.get("grades") or {}).items()))
        live_lines.append(f"Corals: {co.get('checkins', 0)} looks, {co.get('feeds', 0)} target feeds across {co['colonies']} colon{'y' if co['colonies'] == 1 else 'ies'}"
                          + (f"; grades {grades}" if grades else "") + (f"; new: {', '.join(a.get('name') for a in co['added'])}" if co.get("added") else ""))
        for mv in co.get("moved") or []:
            live_lines.append(f"  {mv.get('name')}: {mv.get('from')} → {mv.get('to')}")
    if live_lines:
        blocks.append(("h", "Living reef"))
        blocks.append(("lines", live_lines))
    if mn:
        ageing = mn.get("ageing") or {}
        if ageing.get("items") or ageing.get("filters"):
            blocks.append(("h", "Equipment ageing"))
            if ageing.get("items"):
                blocks.append(("table", ["Item", "Age", "Cadence", "State"],
                               [[str(i.get("label")), f"{_fmt(i['ageDays'], 0)} d" if i.get("ageDays") is not None else "—", f"{i.get('cadenceDays')} d",
                                 {"ok": "fine", "never": "never logged"}.get(str(i.get("status")), str(i.get("status")))] for i in ageing["items"]]))
            if ageing.get("filters"):
                blocks.append(("lines", ["RODI stages: " + ", ".join(f"{f.get('label')} {_fmt(f['usedPct'], 0)} %" if f.get("usedPct") is not None else str(f.get("label")) for f in ageing["filters"])]))
    ev = report.get("happened") or {}
    blocks.append(("h", "What happened"))
    by_type = ev.get("byType") or {}
    ev_lines = [f"{ev.get('count', 0)} event{'s' if ev.get('count', 0) != 1 else ''}" + (" · " + ", ".join(f"{n} {t}" for t, n in sorted(by_type.items())) if by_type else "")]
    blocks.append(("lines", ev_lines))
    ev_rows = [f"{_day_text(r.get('at'))} · {r.get('message')}" + (f" ×{r['count']}" if (r.get("count") or 1) > 1 else "") for r in (ev.get("rows") or [])[:12]]
    if ev_rows:
        blocks.append(("ul", ev_rows))
    nxt = report.get("next") or {}
    blocks.append(("h", "The next two weeks" if month else "Next week"))
    day_lines = [f"{d.get('label')}: " + ", ".join(str(i.get("label")) for i in d.get("items") or []) for d in nxt.get("days") or []]
    blocks.append(("ul", day_lines) if day_lines else ("lines", ["Nothing falls due in the window."]))
    if report.get("notes"):
        blocks.append(("h", "Notes"))
        blocks.append(("ul", [str(n) for n in report["notes"]]))
    return blocks


def markdown(report: dict[str, Any]) -> str:
    out: list[str] = []
    for block in text_blocks(report):
        kind = block[0]
        if kind == "title":
            out.append(f"# {block[1]}")
        elif kind == "h":
            out.append(f"## {block[1]}")
        elif kind == "lines":
            out.append("  \n".join(str(line) for line in block[1] if line))
        elif kind == "ul":
            out.append("\n".join(f"- {line}" for line in block[1] if line))
        elif kind == "table":
            headers, rows = block[1], block[2]
            cells = lambda row: "| " + " | ".join(str(c).replace("|", "/") for c in row) + " |"  # noqa: E731
            out.append("\n".join([cells(headers), "|" + "---|" * len(headers), *[cells(r) for r in rows]]))
    return "\n\n".join(part for part in out if part) + "\n"


def plain_text(report: dict[str, Any]) -> str:
    """The same blocks with no markup — safe for any notify target."""
    out: list[str] = []
    for block in text_blocks(report):
        kind = block[0]
        if kind == "title":
            out.append(str(block[1]).upper())
        elif kind == "h":
            out.append(str(block[1]).upper())
        elif kind == "lines":
            out.append("\n".join(str(line) for line in block[1] if line))
        elif kind == "ul":
            out.append("\n".join(f"- {line}" for line in block[1] if line))
        elif kind == "table":
            headers, rows = block[1], block[2]
            out.append("\n".join([" · ".join(str(h) for h in headers), *[" · ".join(str(c) for c in r if str(c) != "") for r in rows]]))
    return "\n\n".join(part for part in out if part) + "\n"


def share_chunks(text: str, limit: int = SHARE_CHUNK_LIMIT) -> list[str]:
    """Split at blank lines (then at line ends) so no message exceeds
    ``limit`` characters and none breaks mid-line."""
    limit = max(200, int(limit))
    chunks: list[str] = []
    current = ""
    for para in text.split("\n\n"):
        if len(para) > limit:
            for line in para.split("\n"):
                if len(current) + len(line) + 1 > limit and current:
                    chunks.append(current.rstrip())
                    current = ""
                current += line + "\n"
            continue
        if len(current) + len(para) + 2 > limit and current:
            chunks.append(current.rstrip())
            current = ""
        current += para + "\n\n"
    if current.strip():
        chunks.append(current.rstrip())
    return chunks or [text.rstrip()]
