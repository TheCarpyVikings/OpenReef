"""Automatic Water Change — the volume/dilution/scheduling engine ("the maths").

Like :mod:`spawning` and :mod:`icp`, this module is a **pure, dependency-free,
side-effect-free** computation (stdlib only — no Home Assistant, no I/O). All the
arithmetic that decides *how long to run a pump*, *how much water is left*, *how
far a parameter will dilute*, *whether the pumps have drifted*, and *when the next
scheduled change is due* lives here so it is trivially unit-testable and identical
in CI and on a Pi. The orchestration layer in ``__init__.py`` reads live Home
Assistant state, calls these functions, and actuates switches; it owns no maths.

Design stance (from the AWC research briefing)
----------------------------------------------
* **Volume-primary, sensor-arbitrated.** We drive changes by *calibrated volume*
  (the Apex DOS / Kamoer model — the only architecture that can report "litres
  changed" and "litres remaining"), and use physical float/cutoff sensors to
  *arbitrate* that estimate, not to drive the change. The dominant real-world
  failure of this architecture is silent **calibration drift**, so drift
  detection (:func:`drift_pct`) and cumulative **net-imbalance** tracking
  (:func:`net_imbalance_state`) are first-class.
* **Honest dilution maths.** Continuous (trickle) exchange is a series of
  infinitesimal changes and is therefore *slightly less efficient per litre* than
  one equal batch — e.g. 1%/day for 30 days removes ~25.9% of the original water,
  not 30% (``1 - e^(-0.30)``). We surface the real maths rather than the naive
  sum (:func:`batch_removed`, :func:`continuous_removed`).
* **Two-stage calibration.** Each pump has a base ml/s plus an *exchange-
  correction factor* so the OUT and IN pumps can be volume-matched despite
  different tube lengths/heights (Kamoer's key accuracy step).

Sources: Randy Holmes-Farley, "Water Changes in Reef Aquaria" (Reefkeeping,
2005); the dilution derivation at imsolidstate.com; BRS/Neptune DOS AWC setup;
Kamoer X2SR two-stage calibration. The dilution identities below were independently
re-derived and verified during research.
"""

from __future__ import annotations

import math
from datetime import datetime, time as dt_time, timedelta
from typing import Any, Iterable

# --------------------------------------------------------------------------- #
# Engine defaults (the *config* clamps live in const.py; these are the maths
# defaults so the engine is callable in isolation / in tests).
# --------------------------------------------------------------------------- #
ANOMALY_WARN_MULT = 2.0      # warn when a leg runs >2x its expected time
ANOMALY_ABORT_MULT = 3.0     # abort+latch when a leg runs >3x its expected time
DRIFT_WARN_PCT = 10.0        # |model vs sensor| beyond this ⇒ recalibration prompt
DEFAULT_NET_IMBALANCE_L = 2.0  # cumulative drain≠fill litres before we warn

_WEEKDAYS = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"]


# --------------------------------------------------------------------------- #
# Small helpers
# --------------------------------------------------------------------------- #
def _f(value: Any, default: float = 0.0) -> float:
    """Coerce to float, falling back to ``default`` on junk."""
    try:
        out = float(value)
    except (TypeError, ValueError):
        return default
    if math.isnan(out) or math.isinf(out):
        return default
    return out


def parse_hhmm(value: Any, default_minutes: int = 0) -> int:
    """'HH:MM' → minutes since midnight (0–1439); ``default_minutes`` on junk."""
    try:
        hh, mm = str(value).split(":")
        return (int(hh) % 24) * 60 + (int(mm) % 60)
    except (ValueError, AttributeError):
        return default_minutes


def within_window(minute: int, start: int, end: int) -> bool:
    """Is ``minute`` inside [start, end)? Handles windows that wrap past midnight.
    ``start == end`` is treated as a 24h window (always within)."""
    minute %= 1440
    start %= 1440
    end %= 1440
    if start == end:
        return True
    if start < end:
        return start <= minute < end
    return minute >= start or minute < end


def window_minutes(start: int, end: int) -> int:
    """Length of a [start, end) window in minutes (24h when start == end)."""
    length = (end - start) % 1440
    return length or 1440


# --------------------------------------------------------------------------- #
# Calibration & pump-run primitive
# --------------------------------------------------------------------------- #
def runtime_for_volume_s(
    litres: float, ml_per_s: float, exchange_factor: float = 1.0, spin_up_ml: float = 0.0
) -> float:
    """Seconds to move ``litres`` at ``ml_per_s`` (the core pump-run primitive).

    ``exchange_factor`` is the per-pump two-stage correction (Kamoer-style): a
    multiplier on runtime so a pump whose *effective* throughput differs from its
    bench ml/s (longer tube, more head) still moves the intended volume. 1.0 = no
    correction. Returns 0.0 for a non-positive rate (caller must treat as "pump
    not calibrated").

    ``spin_up_ml`` is the per-dose priming/startup offset from the linear calibration
    ``volume = slope·t + intercept`` — the small volume a peristaltic pump over- or
    under-delivers on top of the steady rate because of motor spin-up / roller
    settling. We invert the fit: ``t = (V − spin_up_ml) / rate · factor`` (clamped
    ≥ 0). This is *negligible* on litre-scale changes but dominant on the tens-of-mL
    hourly micro-doses (a fixed few-mL offset is ~6.5% of a 40 mL dose and grows as the
    dose shrinks), so applying it is what keeps small doses volume-accurate. Default
    0.0 ⇒ identical to the pure-rate behaviour (back-compatible). NB: only the primed
    startup term belongs here — a one-time dry-tube *fill* volume must NOT be folded in
    (it would over-correct every primed run), which is why the config splits ``spinUpMl``
    (per dose, here) from ``primeMl`` (first run after an air purge, not here)."""
    rate = _f(ml_per_s)
    if rate <= 0:
        return 0.0
    factor = _f(exchange_factor, 1.0)
    if factor <= 0:
        factor = 1.0
    net_ml = _f(litres) * 1000.0 - _f(spin_up_ml)
    return max(0.0, net_ml / rate * factor)


def volume_for_runtime_l(
    seconds: float, ml_per_s: float, exchange_factor: float = 1.0, spin_up_ml: float = 0.0
) -> float:
    """Litres moved by running ``seconds`` at ``ml_per_s`` — inverse of
    :func:`runtime_for_volume_s` (``V = t·rate/factor + spin_up``). Used to account a
    partial / aborted run. Pass the pump's ``spin_up_ml`` when accounting a run that
    *started* (the offset is incurred once, at start); leave it 0 when converting a
    *remaining*-time tail, where no further start occurs."""
    factor = _f(exchange_factor, 1.0)
    if factor <= 0:
        factor = 1.0
    secs = _f(seconds)
    if secs <= 0:
        return 0.0
    return max(0.0, (secs * _f(ml_per_s) / factor + _f(spin_up_ml)) / 1000.0)


def ml_per_s_from_run(volume_ml: float, seconds: float) -> float:
    """Single-point calibration: dispensed ``volume_ml`` over ``seconds`` → ml/s."""
    secs = _f(seconds)
    if secs <= 0:
        return 0.0
    return max(0.0, _f(volume_ml) / secs)


def calibrate_linear(points: Iterable[Any]) -> dict[str, float]:
    """Optional multi-point calibration: fit ``volume_ml = slope*seconds + intercept``
    by least squares over 2+ ``(seconds, volume_ml)`` points.

    ``slope`` is the steady-state ml/s; ``intercept`` captures the pump's priming /
    startup offset that a single multiplier misses (lab practice). Falls back to a
    pure single-point slope (intercept 0) when given one point. Returns
    ``{"mlPerS", "interceptMl", "points"}``."""
    pts = [(_f(s), _f(v)) for s, v in points]
    pts = [(s, v) for s, v in pts if s > 0]
    n = len(pts)
    if n == 0:
        return {"mlPerS": 0.0, "interceptMl": 0.0, "points": 0}
    if n == 1:
        s, v = pts[0]
        return {"mlPerS": v / s, "interceptMl": 0.0, "points": 1}
    sx = sum(s for s, _ in pts)
    sy = sum(v for _, v in pts)
    sxx = sum(s * s for s, _ in pts)
    sxy = sum(s * v for s, v in pts)
    # Ill-conditioned fits: with the run durations clustered together, least
    # squares amplifies measurement noise into wild slopes (two ~30 s runs can
    # yield a 2.3x-wrong rate with a huge negative intercept — and anomaly
    # detection can't catch it, since expected runtimes derive from the same
    # fit). Require a meaningful time spread; otherwise fall back to the robust
    # through-origin slope.
    smin = min(s for s, _ in pts)
    smax = max(s for s, _ in pts)
    if (smax - smin) < max(1.0, 0.1 * (sx / n)):
        return {"mlPerS": max(0.0, sy / sx) if sx else 0.0, "interceptMl": 0.0, "points": n}
    denom = n * sxx - sx * sx
    if denom == 0:
        return {"mlPerS": sy / sx if sx else 0.0, "interceptMl": 0.0, "points": n}
    slope = (n * sxy - sx * sy) / denom
    intercept = (sy - slope * sx) / n
    return {"mlPerS": max(0.0, slope), "interceptMl": intercept, "points": n}


# --------------------------------------------------------------------------- #
# Reservoir accounting (dead-reckoning) — the "litres remaining" UX
# --------------------------------------------------------------------------- #
def reservoir_remaining_l(container_l: float, dispensed_ml: float) -> float:
    """Litres left after dispensing ``dispensed_ml`` from a ``container_l`` reservoir
    (clamped to ≥ 0). Primary, sensor-arbitrated estimate."""
    return max(0.0, _f(container_l) - _f(dispensed_ml) / 1000.0)


def reservoir_percent(container_l: float, remaining_l: float) -> float:
    """Remaining fraction as 0–100, for the fill-level visual."""
    cap = _f(container_l)
    if cap <= 0:
        return 0.0
    return max(0.0, min(100.0, _f(remaining_l) / cap * 100.0))


def days_of_supply(remaining_l: float, daily_use_l: float) -> float | None:
    """Days of premixed saltwater left at the current daily change rate, or None
    when the rate is zero (infinite supply)."""
    rate = _f(daily_use_l)
    if rate <= 0:
        return None
    return max(0.0, _f(remaining_l) / rate)


def changes_remaining(remaining_l: float, per_change_l: float) -> float | None:
    """Whole changes left in the reservoir, or None when per-change volume is zero."""
    per = _f(per_change_l)
    if per <= 0:
        return None
    return max(0.0, _f(remaining_l) / per)


# --------------------------------------------------------------------------- #
# Dilution maths — honest projections (no naive "30 x 1% = 30%")
# --------------------------------------------------------------------------- #
def batch_fraction_remaining(x: float, n: float) -> float:
    """Fraction of the *original* water (or any conserved dissolved substance)
    remaining after ``n`` batch changes of fraction ``x``: ``(1 - x)^n``."""
    frac = max(0.0, min(1.0, _f(x)))
    return (1.0 - frac) ** max(0.0, _f(n))


def batch_removed(x: float, n: float) -> float:
    """Fraction removed after ``n`` batch changes of fraction ``x``."""
    return 1.0 - batch_fraction_remaining(x, n)


def continuous_remaining(v_exchanged_l: float, v_tank_l: float) -> float:
    """Well-mixed exponential decay: fraction of original water remaining after a
    *continuous* exchange of ``v_exchanged_l`` on a ``v_tank_l`` tank:
    ``e^(-V_exchanged / V_tank)``."""
    vt = _f(v_tank_l)
    if vt <= 0:
        return 1.0
    return math.exp(-max(0.0, _f(v_exchanged_l)) / vt)


def continuous_removed(v_exchanged_l: float, v_tank_l: float) -> float:
    """Fraction removed by a continuous exchange — the honest counterpart to the
    naive sum. 1%/day x 30 days on equal tank volume ⇒ ~0.259, not 0.30."""
    return 1.0 - continuous_remaining(v_exchanged_l, v_tank_l)


def litres_to_reach_target_continuous(v_tank_l: float, current: float, target: float) -> float | None:
    """Litres of continuous exchange needed to bring a conserved contaminant from
    ``current`` to ``target`` (both same units): ``-V_tank * ln(target/current)``.
    None when the target is unreachable by dilution (target ≥ current, or ≤ 0)."""
    vt = _f(v_tank_l)
    cur = _f(current)
    tgt = _f(target)
    if vt <= 0 or cur <= 0 or tgt <= 0 or tgt >= cur:
        return None
    return -vt * math.log(tgt / cur)


def steady_state(production_per_period: float, change_fraction_per_period: float, source: float = 0.0) -> float | None:
    """Where a contaminant plateaus under regular changes:
    ``production / change_fraction + source_water_level``. None when the change
    fraction is zero (no ceiling). NB: assumes a *conserved* substance — for
    biologically consumed nutrients (nitrate/phosphate) this is an upper bound."""
    frac = max(0.0, min(1.0, _f(change_fraction_per_period)))
    if frac <= 0:
        return None
    return _f(production_per_period) / frac + _f(source)


# --------------------------------------------------------------------------- #
# Safety maths — anomaly, drift, net-imbalance
# --------------------------------------------------------------------------- #
def anomaly_verdict(
    elapsed_s: float,
    expected_s: float,
    warn_mult: float = ANOMALY_WARN_MULT,
    abort_mult: float = ANOMALY_ABORT_MULT,
) -> str:
    """Time-vs-baseline check (the AutoAqua QST / HYDROS pattern). Because we know
    the expected runtime from calibration, a leg running far longer than expected
    simultaneously catches an empty reservoir, a clogged/kinked tube, and a stuck
    sensor. Returns ``"ok"`` | ``"warn"`` | ``"abort"``. With no expected baseline
    (uncalibrated) we cannot judge ⇒ ``"ok"`` (other interlocks still apply)."""
    exp = _f(expected_s)
    if exp <= 0:
        return "ok"
    ratio = _f(elapsed_s) / exp
    if ratio >= max(warn_mult, abort_mult):
        return "abort"
    if ratio >= warn_mult:
        return "warn"
    return "ok"


def drift_pct(model_dispensed_ml: float, actual_volume_ml: float) -> float | None:
    """Calibration drift: when a reservoir float trips, the pump *model* claims it
    dispensed ``model_dispensed_ml`` while the *known* usable volume between floats
    was ``actual_volume_ml``. Returns the signed % error of the model vs reality
    (positive ⇒ model over-estimates ⇒ pump is actually moving less than calibrated
    — the classic tube-fatigue/scale drift). None when no reference volume."""
    actual = _f(actual_volume_ml)
    if actual <= 0:
        return None
    return (_f(model_dispensed_ml) - actual) / actual * 100.0


def drift_state(
    model_dispensed_ml: float, actual_volume_ml: float, warn_pct: float = DRIFT_WARN_PCT
) -> dict[str, Any]:
    """Drift verdict for the panel: ``{driftPct, status, recalibrate}``."""
    pct = drift_pct(model_dispensed_ml, actual_volume_ml)
    if pct is None:
        return {"driftPct": None, "status": "unknown", "recalibrate": False}
    over = abs(pct) >= _f(warn_pct, DRIFT_WARN_PCT)
    return {
        "driftPct": round(pct, 1),
        "status": "warning" if over else "ok",
        "recalibrate": over,
    }


def net_imbalance_from_totals(
    drained_l: float, filled_l: float, threshold_l: float = DEFAULT_NET_IMBALANCE_L
) -> dict[str, Any]:
    """Net-imbalance verdict from cumulative drain/fill totals.

    Returns ``{drainedL, filledL, netL, status, suggestedTrimL}`` where ``netL`` =
    filled − drained (negative ⇒ net drained ⇒ salinity-drop risk) and
    ``suggestedTrimL`` is the litres to add to the next fill (or remove, if
    negative) to rebalance."""
    drained = max(0.0, _f(drained_l))
    filled = max(0.0, _f(filled_l))
    net = filled - drained
    # threshold <= 0 disables the check (matches the sibling caps' "0 = off"
    # convention); it previously meant "warn always".
    threshold = _f(threshold_l, DEFAULT_NET_IMBALANCE_L)
    over = threshold > 0 and abs(net) >= threshold
    return {
        "drainedL": round(drained, 3),
        "filledL": round(filled, 3),
        "netL": round(net, 3),
        "status": "warning" if over else "ok",
        "suggestedTrimL": round(-net, 3),  # add this much fill to get back to balance
    }


def net_imbalance_state(
    events: Iterable[Any], threshold_l: float = DEFAULT_NET_IMBALANCE_L
) -> dict[str, Any]:
    """Cumulative drain-vs-fill tracking — the anti-salinity-drift leapfrog (pure
    software, no probe). Each event is ``{"drainedL", "filledL"}``. If, over time,
    we drain more than we fill, the ATO tops the deficit with *fresh* water and
    salinity slowly crashes (the verified Apex/Kamoer failure). We log the net and,
    when it exceeds ``threshold_l``, warn and suggest a corrective trim on the next
    change.

    NB: summing a CAPPED event list is only honest while the list holds every change —
    at high-frequency micro-change cadence (24/day fills a 100-event history in ~4 days)
    the persistent ledger totals must be used instead (see
    :func:`net_imbalance_from_totals` and the ``ledger`` block in :func:`summary`)."""
    drained = 0.0
    filled = 0.0
    for ev in events:
        drained += max(0.0, _f((ev or {}).get("drainedL")))
        filled += max(0.0, _f((ev or {}).get("filledL")))
    return net_imbalance_from_totals(drained, filled, threshold_l)


# --------------------------------------------------------------------------- #
# Schedule resolution — "fully flexible": litres OR %, per day OR per week
# --------------------------------------------------------------------------- #
def resolve_period_litres(schedule: dict[str, Any], tank_volume_l: float) -> float:
    """The litres to change over the schedule's *period* (day or week), resolving a
    percent amount against ``tank_volume_l``."""
    sched = schedule or {}
    amount = max(0.0, _f(sched.get("amount")))
    if str(sched.get("amountUnit", "litres")).lower() == "percent":
        return max(0.0, _f(tank_volume_l) * amount / 100.0)
    return amount


def slot_minutes_for_day(schedule: dict[str, Any]) -> list[int]:
    """Sorted minutes-since-midnight of one active day's run slots.

    ``times`` mode (the default) reads the explicit HH:MM list. ``interval`` mode —
    the micro-change cadence — generates ``windowStart + k·everyMinutes`` for every
    slot strictly inside the window (start inclusive, end exclusive). A wrapped
    window's post-midnight slots land as early-morning minutes of the same calendar
    day; equal start/end means the full day (24 hourly slots at 60 min)."""
    sched = schedule or {}
    if str(sched.get("mode", "times")).lower() == "interval":
        ws = parse_hhmm(sched.get("windowStart", "01:00"))
        we = parse_hhmm(sched.get("windowEnd", "05:00"))
        every = int(_f(sched.get("everyMinutes"), 60) or 60)
        every = max(15, min(1440, every))
        length = (we - ws) % 1440 or 1440
        mins: list[int] = []
        k = 0
        while k * every < length:
            mins.append((ws + k * every) % 1440)
            k += 1
        return sorted(set(mins))
    times = sched.get("times") or [sched.get("startTime", "02:00")]
    return sorted({parse_hhmm(t) for t in times if t})


def runs_per_week(schedule: dict[str, Any]) -> int:
    """How many discrete batch runs occur per week = (active days) x (slots/day).
    Continuous schedules return 0 (they don't run as discrete batches).

    This is the count of times :func:`is_due` fires in a week — each allowed day, at
    each daily slot — and it is period-agnostic (a *weekly* amount is still delivered
    across ``n_days x n_slots`` runs). Using ``max(n_days, n_slots)`` here under-counts
    the runs and makes :func:`per_change_litres` over-dose (e.g. Mon/Wed x 06:00/18:00
    would split a weekly amount across 2 slots but actually run 4 times ⇒ ~2x change)."""
    sched = schedule or {}
    if str(sched.get("method", "")).startswith("continuous"):
        return 0
    days = sched.get("days") or _WEEKDAYS
    n_days = len([d for d in days if d in _WEEKDAYS]) or len(_WEEKDAYS)
    return n_days * max(1, len(slot_minutes_for_day(sched)))


def per_change_litres(schedule: dict[str, Any], tank_volume_l: float) -> float:
    """Litres to move in a single batch run, spreading the period amount across the
    period's run-slots. For ``period == "day"`` the daily amount is split across the
    day's slots; for ``period == "week"`` the weekly amount is split across all
    weekly run-slots. Interval mode divides across its generated window slots the
    same way — 0.96 L/day every hour across a full day is 40 ml per change."""
    sched = schedule or {}
    period_l = resolve_period_litres(sched, tank_volume_l)
    period = str(sched.get("period", "day")).lower()
    if period == "week":
        slots = max(1, runs_per_week(sched))
        return period_l / slots
    return period_l / max(1, len(slot_minutes_for_day(sched)))


def daily_equivalent_litres(schedule: dict[str, Any], tank_volume_l: float) -> float:
    """Average litres/day this schedule changes — drives days-of-supply and the
    dilution projection regardless of method/period.

    Batch schedules honour day-of-week restrictions: a "4 L per day, Mondays only"
    schedule averages 4/7 L/day, not 4 (the naive period read made every projection
    up to 7x optimistic). Continuous has no run-slots, so the plain period read stands."""
    sched = schedule or {}
    period_l = resolve_period_litres(sched, tank_volume_l)
    period_daily = period_l if str(sched.get("period", "day")).lower() == "day" else period_l / 7.0
    if str(sched.get("method", "")).startswith("continuous"):
        return period_daily
    return per_change_litres(sched, tank_volume_l) * runs_per_week(sched) / 7.0


def continuous_tick_ml(
    daily_litres: float, window_start: int, window_end: int, tick_seconds: float
) -> float:
    """ml to exchange on one continuous-mode tick: the day's litres spread evenly
    across the active window. ``window_start``/``window_end`` are minutes since
    midnight (wrap-aware); a tick fires every ``tick_seconds`` while in-window."""
    win_min = window_minutes(int(window_start), int(window_end))
    win_s = win_min * 60.0
    if win_s <= 0:
        return 0.0
    tick = max(0.0, _f(tick_seconds))
    return max(0.0, _f(daily_litres) * 1000.0 * tick / win_s)


def schedule_text(schedule: dict[str, Any], tank_volume_l: float) -> str:
    """One-line plain-language description of what the schedule actually does —
    the panel's honesty line: '≈ 40 ml every hour (01:00–05:00), 0.96 L/day,
    drain ∥ fill'. Never jargon, never raw config fields."""
    sched = schedule or {}
    if not sched.get("enabled"):
        return "Schedule off — manual changes only"
    per = per_change_litres(sched, tank_volume_l)
    daily = daily_equivalent_litres(sched, tank_volume_l)
    method_txt = ("drain ∥ fill" if str(sched.get("method", "")) == "batch_simultaneous"
                  else "drain then fill")
    vol_txt = f"≈ {per * 1000:.0f} ml" if per < 1.0 else f"{per:g} L"
    if str(sched.get("mode", "times")).lower() == "interval":
        every = int(_f(sched.get("everyMinutes"), 60) or 60)
        if every == 60:
            cadence = "every hour"
        elif every % 60 == 0:
            cadence = f"every {every // 60} h"
        else:
            cadence = f"every {every} min"
        ws = str(sched.get("windowStart", "01:00"))
        we = str(sched.get("windowEnd", "05:00"))
        window = "" if parse_hhmm(ws) == parse_hhmm(we) else f" ({ws}–{we})"
        head = f"{vol_txt} {cadence}{window}"
    else:
        times = [t for t in (sched.get("times") or [sched.get("startTime", "02:00")]) if t]
        days = [d for d in (sched.get("days") or []) if d in _WEEKDAYS]
        days_txt = "" if not days or len(days) == 7 else " on " + "/".join(days)
        head = f"{vol_txt} at {', '.join(times)}{days_txt}"
    return f"{head}, {daily:.2f} L/day, {method_txt}"


def next_run(schedule: dict[str, Any], last_run: datetime | None, now: datetime) -> datetime | None:
    """Next due datetime for a *batch* schedule strictly after ``now`` (and after
    ``last_run`` if given), honouring days-of-week and one or more daily times.
    Returns None for disabled or continuous schedules. Mirrors the modeSchedule
    evaluator's day/time semantics. ``now``/``last_run`` are naive-local or aware;
    comparisons use them as-is (caller passes a consistent tz)."""
    sched = schedule or {}
    if not sched.get("enabled", True):
        return None
    if str(sched.get("method", "")).startswith("continuous"):
        return None
    minutes = slot_minutes_for_day(sched)
    if not minutes:
        return None
    allowed_days = sched.get("days")
    allowed = {_WEEKDAYS.index(d) for d in allowed_days if d in _WEEKDAYS} if allowed_days else set(range(7))
    if not allowed:
        allowed = set(range(7))
    for day_offset in range(0, 8):
        target_date = (now + timedelta(days=day_offset)).date()
        if target_date.weekday() not in allowed:
            continue
        for minute in minutes:
            # Build the candidate as a wall-clock time on the target DATE rather
            # than replace()-ing hours on an aware datetime: timedelta arithmetic
            # preserves the *old* UTC offset across a DST boundary, so the naive
            # form displayed 02:00 slots as 01:00/03:00 for the week of the
            # changeover. zoneinfo tzinfo attached to a combine() localises
            # correctly (naive inputs keep tzinfo=None — unchanged behaviour).
            candidate = datetime.combine(
                target_date, dt_time(minute // 60, minute % 60), tzinfo=now.tzinfo
            )
            if candidate <= now:
                continue
            if last_run is not None and candidate <= last_run:
                continue
            return candidate
    return None


# --------------------------------------------------------------------------- #
# State-machine decisions — pure, so the async orchestrator in __init__.py owns
# no logic, only actuation. ``cfg`` is the normalised automaticWaterChange dict;
# ``live`` is a snapshot of the booleans the orchestrator reads from HA:
#   {leak, highLevel, freshEmpty, wasteFull, returnPumpIssue, inFeedMode}
# --------------------------------------------------------------------------- #
def _live(live: dict[str, Any] | None, key: str) -> bool:
    return bool((live or {}).get(key))


def plan_leg(
    method: str, drained_ml: float, filled_ml: float, target_ml: float, tick_ml: float
) -> dict[str, Any] | None:
    """Decide the next pump leg given progress so far. Returns
    ``{"pumps": [...], "sliceMl": ...}`` or None when the change is complete.

    This also IS the resume-to-balance logic: fed the persisted drained/filled, it
    naturally drives whichever side is behind — so a power-loss mid-change resumes
    toward a balanced drain==fill==target.
      * continuous          — both pumps, a ``tick_ml`` slice, kept matched
      * batch_simultaneous  — both pumps, the whole remaining slice at once
      * batch_sequential    — all drain first, then all fill
    """
    target = max(0.0, _f(target_ml))
    drained = max(0.0, _f(drained_ml))
    filled = max(0.0, _f(filled_ml))
    eps = 1e-6
    if drained >= target - eps and filled >= target - eps:
        return None
    if method == "batch_sequential":
        if drained < target - eps:
            return {"pumps": ["drain"], "sliceMl": target - drained}
        return {"pumps": ["fill"], "sliceMl": target - filled}
    if method == "continuous":
        behind = max(drained, filled)
        slice_ml = min(max(0.0, _f(tick_ml)), target - behind)
        if slice_ml <= eps:
            slice_ml = target - behind
        return {"pumps": ["drain", "fill"], "sliceMl": slice_ml}
    # batch_simultaneous (default): both pumps, remaining volume in one leg
    remaining = target - min(drained, filled)
    return {"pumps": ["drain", "fill"], "sliceMl": remaining}


def exchange_side_progress(
    remaining_s: float, ml_per_s: float, exchange_factor: float, target_ml: float
) -> tuple[float, bool]:
    """Simultaneous mode: dead-reckoned volume (ml) one pump has moved, given the
    seconds remaining until its OWN scheduled stop. Each pump has an independent timer
    sized to move exactly ``target_ml`` at its calibrated rate, so neither over-pumps —
    the fix for the shared-timer problem that got simultaneous deferred. Returns
    ``(volume_ml, done)``; ``done`` is volume-aware (also true at/over target or for a
    non-positive rate) so an uncalibrated/finished side never reads 'not done'."""
    target = max(0.0, _f(target_ml))
    rem_s = _f(remaining_s)
    rate = _f(ml_per_s)
    if rem_s <= 0 or rate <= 0:
        return target, True
    remaining_ml = volume_for_runtime_l(rem_s, rate, exchange_factor) * 1000.0
    vol = min(max(0.0, target - max(0.0, remaining_ml)), target)
    return vol, vol >= target - 1e-6


def exchange_imbalance_exceeds(
    drained_ml: float, filled_ml: float, cap_litres: float, baseline_ml: float = 0.0
) -> bool:
    """True when the *new* sump excursion this leg exceeds the cap. We measure
    divergence relative to the gap that existed when the leg began (``baseline_ml``),
    not the cumulative drain/fill totals — so a resume-to-balance leg (which starts with
    a large pre-existing gap it is *correcting*) is never aborted, and a fresh leg
    (baseline 0) is bounded by the cap. The start-time guard
    (:func:`simultaneous_max_excursion_l`) prevents a fresh leg from ever needing to hit
    this. ``cap_litres <= 0`` disables the check."""
    cap = _f(cap_litres)
    if cap <= 0:
        return False
    gap = abs(_f(drained_ml) - _f(filled_ml))
    new_divergence = gap - abs(_f(baseline_ml))
    return new_divergence > cap * 1000.0 + 1e-6


def simultaneous_max_excursion_l(cfg: dict[str, Any], target_l: float) -> float:
    """Predicted worst-case sump excursion (litres) for a *fresh* simultaneous change of
    ``target_l``: the faster pump finishes and stops while the slower is still mid-way,
    so the peak |drained − filled| = ``target · (1 − t_fast/t_slow)``. Used as a start
    guard — if this exceeds the imbalance cap, the pumps are too rate-mismatched to run
    simultaneously at this size (use sequential, or rate-match). Uncalibrated ⇒ worst
    case (the calibration guard blocks first anyway)."""
    target = max(0.0, _f(target_l))
    if target <= 0:
        return 0.0
    pumps = (cfg or {}).get("pumps", {}) if isinstance((cfg or {}).get("pumps"), dict) else {}
    drain = pumps.get("drain", {}) if isinstance(pumps.get("drain"), dict) else {}
    fill = pumps.get("fill", {}) if isinstance(pumps.get("fill"), dict) else {}
    drain_rt = runtime_for_volume_s(target, drain.get("mlPerS"), drain.get("exchangeFactor", 1.0), drain.get("spinUpMl", 0.0))
    fill_rt = runtime_for_volume_s(target, fill.get("mlPerS"), fill.get("exchangeFactor", 1.0), fill.get("spinUpMl", 0.0))
    if drain_rt <= 0 or fill_rt <= 0:
        return target
    t_fast, t_slow = min(drain_rt, fill_rt), max(drain_rt, fill_rt)
    return target * (1.0 - t_fast / t_slow)


def leg_runtime_s(slice_l: float, cfg: dict[str, Any], roles: Iterable[str]) -> float:
    """Wall-clock seconds for a leg that runs ``roles`` concurrently for ``slice_l``
    litres each — the max of the per-pump runtimes (they run together)."""
    pumps = (cfg or {}).get("pumps", {})
    longest = 0.0
    for role in roles:
        pump = pumps.get(role, {}) if isinstance(pumps, dict) else {}
        longest = max(longest, runtime_for_volume_s(
            slice_l, pump.get("mlPerS"), pump.get("exchangeFactor", 1.0), pump.get("spinUpMl", 0.0)
        ))
    return longest


def exceeds_single_change_cap(cfg: dict[str, Any], litres: float) -> bool:
    """True when a requested change exceeds the configured max single-change % of
    tank volume (the salinity-swing guardrail). No cap when tank volume unset."""
    cfg = cfg or {}
    tank = _f(cfg.get("tankVolumeLitres"))
    if tank <= 0:
        return False
    pct = _f((cfg.get("safety") or {}).get("maxSingleChangePercent"), 100.0)
    return _f(litres) > tank * pct / 100.0 + 1e-6


def start_guard_reasons(
    cfg: dict[str, Any], live: dict[str, Any], now_minutes: int, manual: bool = False
) -> list[dict[str, str]]:
    """Reasons a change must NOT start now. ``severity`` is ``"fault"`` for hazards
    that should latch (leak, display overfill) and ``"block"`` for benign deferrals.
    A manual run bypasses the quiet-hours and feed-mode *convenience* guards but never
    the hardware/safety ones."""
    cfg = cfg or {}
    pumps = cfg.get("pumps", {}) if isinstance(cfg.get("pumps"), dict) else {}
    guards = cfg.get("guards", {}) if isinstance(cfg.get("guards"), dict) else {}
    state = cfg.get("state", {}) if isinstance(cfg.get("state"), dict) else {}
    out: list[dict[str, str]] = []

    if state.get("fault"):
        out.append({"code": "latched", "severity": "block",
                    "message": f"A latched fault must be cleared first: {state.get('fault')}"})
    if state.get("status") == "paused":
        out.append({"code": "paused", "severity": "block",
                    "message": "A water change is paused; resume or stop it before starting another"})
    if _live(live, "leak"):
        out.append({"code": "leak", "severity": "fault", "message": "Leak detected"})
    if _live(live, "highLevel"):
        out.append({"code": "high_level", "severity": "fault",
                    "message": "Display high-level cutoff is active"})
    # Fail-closed: a CONFIGURED flood-hazard sensor that has gone unavailable is a blind
    # spot with no backend backstop — refuse to start until it reports again. "block" not
    # "fault": a flaky sensor defers the change, it doesn't latch the feature.
    if _live(live, "leakUnknown"):
        out.append({"code": "leak_unavailable", "severity": "block",
                    "message": "Leak sensor is unavailable — refusing to start blind"})
    if _live(live, "highLevelUnknown"):
        out.append({"code": "high_level_unavailable", "severity": "block",
                    "message": "Display high-level sensor is unavailable — refusing to start blind"})
    if _live(live, "freshEmpty"):
        out.append({"code": "fresh_empty", "severity": "block",
                    "message": "Fresh saltwater reservoir is empty"})
    if _live(live, "wasteFull"):
        out.append({"code": "waste_full", "severity": "block",
                    "message": "Waste reservoir is full"})
    for role in ("drain", "fill"):
        pump = pumps.get(role, {}) if isinstance(pumps.get(role), dict) else {}
        if not pump.get("switchEntity"):
            out.append({"code": "no_pump_entity", "severity": "block",
                        "message": f"No {role} pump entity configured"})
        elif _f(pump.get("mlPerS")) <= 0:
            out.append({"code": "no_calibration", "severity": "block",
                        "message": f"{role.capitalize()} pump is not calibrated"})
    if guards.get("blockOnReturnPumpIssue", True) and _live(live, "returnPumpIssue"):
        out.append({"code": "return_pump", "severity": "block",
                    "message": "Return flow is not confirmed"})
    if not manual:
        if guards.get("blockDuringFeed", True) and _live(live, "inFeedMode"):
            out.append({"code": "feed_mode", "severity": "block",
                        "message": "Feed mode is active"})
        if guards.get("quietHoursEnabled") and not within_window(
            int(now_minutes), parse_hhmm(guards.get("quietStart"), 60),
            parse_hhmm(guards.get("quietEnd"), 300),
        ):
            out.append({"code": "quiet_hours", "severity": "block",
                        "message": "Outside the allowed quiet-hours window"})
    return out


def reservoir_preflight_reasons(cfg: dict[str, Any], target_litres: float) -> list[dict[str, str]]:
    """Dead-reckoned reservoir guards before a change starts.

    Float sensors are still the hardware arbiters, but OpenReef's own reservoir model
    should never knowingly start a change it does not have fresh/waste capacity for.
    """
    target_ml = _f(target_litres) * 1000.0
    if target_ml <= 0:
        return []
    reservoirs = (cfg or {}).get("reservoirs", {}) if isinstance((cfg or {}).get("reservoirs"), dict) else {}
    fresh = reservoirs.get("fresh", {}) if isinstance(reservoirs.get("fresh"), dict) else {}
    waste = reservoirs.get("waste", {}) if isinstance(reservoirs.get("waste"), dict) else {}
    out: list[dict[str, str]] = []

    remaining = _f(fresh.get("remainingMl"))
    if remaining + 1e-6 < target_ml:
        out.append({"code": "fresh_insufficient", "severity": "block",
                    "message": "Fresh saltwater reservoir does not have enough recorded volume"})

    waste_capacity = _f(waste.get("capacityLitres")) * 1000.0
    if waste_capacity <= 0:
        out.append({"code": "waste_capacity_unknown", "severity": "block",
                    "message": "Waste reservoir capacity must be set before running AWC"})
    else:
        available = waste_capacity - _f(waste.get("filledMl"))
        if available + 1e-6 < target_ml:
            out.append({"code": "waste_insufficient", "severity": "block",
                        "message": "Waste reservoir does not have enough recorded free capacity"})
    return out


def in_run_safety(
    cfg: dict[str, Any], live: dict[str, Any], needs_drain: bool, needs_fill: bool
) -> dict[str, Any]:
    """Safety verdict checked at every leg boundary. Faults LATCH (two-tier policy);
    benign reservoir/return-flow limits PAUSE for auto-resume. Returns
    ``{"action": "ok"|"pause"|"fault", "reason": str, "latch": bool}``."""
    cfg = cfg or {}
    guards = cfg.get("guards", {}) if isinstance(cfg.get("guards"), dict) else {}
    if _live(live, "leak"):
        # Master kill — a leak fails-closed ALL pumps incl. the return pump, since a
        # leak the level sensors can't see (cracked sump, blown union) means any pump
        # running makes it worse.
        return {"action": "fault", "reason": "Leak detected — all pumps stopped",
                "latch": True, "masterKill": True}
    if _live(live, "highLevel"):
        return {"action": "fault", "reason": "Display high-level cutoff — change aborted",
                "latch": True, "masterKill": False}
    # Fail-closed: a configured flood-hazard sensor going unavailable mid-change means we
    # are pumping blind — PAUSE (auto-resume when it recovers), never latch on flakiness.
    if _live(live, "leakUnknown"):
        return {"action": "pause", "reason": "Leak sensor unavailable — paused until it recovers",
                "latch": False, "masterKill": False}
    if _live(live, "highLevelUnknown"):
        return {"action": "pause",
                "reason": "Display high-level sensor unavailable — paused until it recovers",
                "latch": False, "masterKill": False}
    if needs_fill and _live(live, "freshEmpty"):
        return {"action": "pause", "reason": "Fresh saltwater reservoir empty",
                "latch": False, "masterKill": False}
    if needs_drain and _live(live, "wasteFull"):
        return {"action": "pause", "reason": "Waste reservoir full",
                "latch": False, "masterKill": False}
    if guards.get("blockOnReturnPumpIssue", True) and _live(live, "returnPumpIssue"):
        return {"action": "pause", "reason": "Return flow not confirmed",
                "latch": False, "masterKill": False}
    return {"action": "ok", "reason": "", "latch": False, "masterKill": False}


# --------------------------------------------------------------------------- #
# Panel-facing summary — the "intelligence layer" derived values (reservoir
# levels, days remaining, net-imbalance, honest dilution projection, and
# calibration/tubing-age nags). Pure; the WS handler passes `now`.
# --------------------------------------------------------------------------- #
def _parse_iso(value: Any) -> datetime | None:
    if not value:
        return None
    try:
        return datetime.fromisoformat(str(value))
    except (ValueError, TypeError):
        return None


def _age_days(value: Any, now: datetime) -> float | None:
    dt = _parse_iso(value)
    if dt is None:
        return None
    try:
        return max(0.0, (now - dt).total_seconds() / 86400.0)
    except TypeError:
        return None


def summary(cfg: dict[str, Any], now: datetime, recal_days: int = 60, tubing_days: int = 365) -> dict[str, Any]:
    """Derived, panel-facing AWC metrics. ``recal_days``/``tubing_days`` set the
    maintenance-nag thresholds (research: recalibrate ~every 2 months; replace tubing
    ~yearly under AWC duty)."""
    cfg = cfg or {}
    reservoirs = cfg.get("reservoirs", {}) if isinstance(cfg.get("reservoirs"), dict) else {}
    fresh = reservoirs.get("fresh", {}) if isinstance(reservoirs.get("fresh"), dict) else {}
    waste = reservoirs.get("waste", {}) if isinstance(reservoirs.get("waste"), dict) else {}
    fresh_cap = _f(fresh.get("capacityLitres"))
    fresh_rem = _f(fresh.get("remainingMl")) / 1000.0
    waste_cap = _f(waste.get("capacityLitres"))
    waste_fill = _f(waste.get("filledMl")) / 1000.0

    sched = cfg.get("schedule", {}) if isinstance(cfg.get("schedule"), dict) else {}
    tank = _f(cfg.get("tankVolumeLitres"))
    daily = daily_equivalent_litres(sched, tank) if sched.get("enabled") else 0.0
    weekly = daily * 7.0
    per_change = per_change_litres(sched, tank) if sched.get("enabled") else 0.0

    # Net imbalance from the PERSISTENT ledger when present (survives the capped history —
    # mandatory at micro-change cadence); fall back to summing history for legacy configs.
    threshold = (cfg.get("safety", {}) or {}).get("netImbalanceWarnLitres", DEFAULT_NET_IMBALANCE_L)
    ledger = cfg.get("ledger") if isinstance(cfg.get("ledger"), dict) else None
    if ledger is not None:
        ni = net_imbalance_from_totals(
            ledger.get("cumulativeDrainedL"), ledger.get("cumulativeFilledL"), threshold
        )
        ni["since"] = ledger.get("resetAt") or None
    else:
        ni = net_imbalance_state(cfg.get("history", []), threshold)
    removed_30d = continuous_removed(daily * 30.0, tank) if (tank > 0 and daily > 0) else 0.0

    pumps: dict[str, Any] = {}
    for role in ("drain", "fill"):
        p = cfg.get("pumps", {}).get(role, {}) if isinstance(cfg.get("pumps"), dict) else {}
        cal_age = _age_days(p.get("calibratedAt"), now)
        tub_age = _age_days(p.get("tubingInstalledAt"), now)
        pumps[role] = {
            "mlPerS": _f(p.get("mlPerS")),
            "calibrated": _f(p.get("mlPerS")) > 0,
            "calibrationAgeDays": None if cal_age is None else round(cal_age, 1),
            "recalibrationDue": cal_age is not None and cal_age >= recal_days,
            "tubingAgeDays": None if tub_age is None else round(tub_age, 1),
            "tubingReplaceDue": tub_age is not None and tub_age >= tubing_days,
            # Lifetime wear odometers (persist independently of the capped history):
            # run-hours vs motor/tube life, start-count vs switching wear — the honest
            # duty numbers for high-frequency micro-changes (~8,760 starts/yr at hourly).
            "runHours": round(max(0.0, _f(p.get("runSeconds"))) / 3600.0, 2),
            "startCount": int(max(0.0, _f(p.get("startCount")))),
        }

    return {
        "reservoirs": {
            "fresh": {
                "remainingL": round(fresh_rem, 2),
                "capacityL": round(fresh_cap, 2),
                "percent": round(reservoir_percent(fresh_cap, fresh_rem), 1),
            },
            "waste": {
                "filledL": round(waste_fill, 2),
                "capacityL": round(waste_cap, 2),
                "percent": round(reservoir_percent(waste_cap, waste_fill), 1),
                "remainingCapacityL": round(max(0.0, waste_cap - waste_fill), 2),
            },
        },
        "scheduleText": schedule_text(sched, tank),
        "dailyChangeL": round(daily, 3),
        "weeklyChangeL": round(weekly, 3),
        "weeklyPercentOfTank": round(weekly / tank * 100.0, 2) if tank > 0 else 0.0,
        "daysOfFreshRemaining": days_of_supply(fresh_rem, daily),
        "changesRemaining": changes_remaining(fresh_rem, per_change),
        "netImbalance": ni,
        "projectedRemovalPct30d": round(removed_30d * 100.0, 1),
        "pumps": pumps,
    }


def due_slots(schedule: dict[str, Any], last_run: datetime | None, now: datetime) -> list[datetime]:
    """Every slot that has passed today and is unserved (ascending). The tail is
    what fires; interval mode folds the earlier ones into one coalesced catch-up
    change instead of running each missed micro-change back-to-back."""
    sched = schedule or {}
    if not sched.get("enabled", True):
        return []
    if str(sched.get("method", "")).startswith("continuous"):
        return []
    if now.weekday() not in (
        {_WEEKDAYS.index(d) for d in (sched.get("days") or []) if d in _WEEKDAYS} or set(range(7))
    ):
        return []
    now_min = now.hour * 60 + now.minute
    today_start = now.replace(hour=0, minute=0, second=0, microsecond=0)
    out: list[datetime] = []
    for minute in slot_minutes_for_day(sched):
        if minute > now_min:
            continue
        fire_at = today_start + timedelta(minutes=minute)
        if last_run is None or last_run < fire_at:
            out.append(fire_at)
    return out


def due_slot(schedule: dict[str, Any], last_run: datetime | None, now: datetime) -> datetime | None:
    """The fire time of the latest scheduled slot that has passed and is unserved
    (nothing run since it), or ``None``. Exposing the slot itself (not just a bool)
    lets the orchestrator judge slot freshness and report which slot was blocked."""
    slots = due_slots(schedule, last_run, now)
    return slots[-1] if slots else None


def is_due(schedule: dict[str, Any], last_run: datetime | None, now: datetime) -> bool:
    """True when a batch change should fire now: a scheduled time on an allowed day
    has passed since ``last_run`` (or since the start of today if never run)."""
    return due_slot(schedule, last_run, now) is not None
