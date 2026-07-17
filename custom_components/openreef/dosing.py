"""Dosing-channel engine — pure maths for OpenReef's multi-pump dosing feature.

Design stance (mirrors awc.py): everything in this module is a pure function of
its inputs — no Home Assistant imports, no I/O, no clocks. The orchestration
(timers, entity reads/writes, WS handlers) lives in __init__.py.

Division of responsibility (locked in the feature plan):
  * The ESPHome firmware EXECUTES the schedule and the full per-dose guard chain
    (enabled → !ha_suspend → reservoir → calibrated → in-window → pH → daily cap)
    so dosing fails safe and keeps running when HA is offline.
  * HA (this engine) COMPILES the user's daily-total-first schedule into the
    firmware's number entities, MIRRORS the guard chain for display, and owns the
    ledgers the firmware can't: missed-dose trajectory, reservoir bookkeeping,
    calibration history, tube wear, dose-integrity trust, advisory ramp.

Research provenance (2026-07 UX sweep, see docs): "daily total + window,
auto-split" is the most-loved scheduling interaction (Apex/ReefDose); missed-dose
silence is the #1 trust breaker; reservoir days-until-empty is the #2 demand and
must never disable dosing; manual actions are always bounded; kalk pH is a
failsafe (pause-above / resume-below hysteresis), never the driver; kalk missed
volume defaults to SKIP, never an automatic catch-up bolus (the Red Sea lesson).
"""

from __future__ import annotations

import math
from datetime import datetime
from typing import Any

from .awc import _f, _age_days, _parse_iso, parse_hhmm, within_window, window_minutes

# --------------------------------------------------------------------------- #
# Engine defaults (config clamps live in const.py; these keep the engine
# callable in isolation / in tests).
# --------------------------------------------------------------------------- #
FIRMWARE_DOSE_ML_MIN = 0.1        # firmware dose-volume number bounds
FIRMWARE_DOSE_ML_MAX = 10.0
FIRMWARE_INTERVAL_MIN = 1         # firmware interval number bounds (minutes)
FIRMWARE_INTERVAL_MAX = 240
TARGET_INTERVAL_MIN = 10          # preferred cadence when the volume allows it
CAL_STEPS_PER_100REV = 320000.0   # 200 steps x 16 microsteps x 100 revolutions
RECAL_NAG_DAYS = 60               # matches the AWC recalibration nag
MISSED_TOLERANCE_PCT = 10.0
CAL_DRIFT_WARN_PCT = 10.0         # successive stepsPerMl values differing beyond this
AUTO_DAILY_CAP_MULT = 1.25        # maxDailyMl 0 = auto ⇒ mlPerDay x this
NIGHT_PERCENT_MAX = 90.0          # keep a residual day rate so the day interval stays finite

_CHEMICAL_LABELS = {
    "alk": "Alkalinity", "ca": "Calcium", "mg": "Magnesium",
    "kalk": "Kalkwasser", "trace": "Trace", "other": "Other",
}


def _fmt_hhmm(minutes: float) -> str:
    m = int(minutes) % 1440
    return f"{m // 60:02d}:{m % 60:02d}"


def _overlap_minutes(s1: int, e1: int, s2: int, e2: int) -> int:
    """Minutes of a day inside BOTH [s1,e1) and [s2,e2), wrap-aware (exact by
    construction: windows are minute-granular and a day is only 1440 minutes)."""
    return sum(
        1 for m in range(1440)
        if within_window(m, s1, e1) and within_window(m, s2, e2)
    )


def _cfg(channel: dict[str, Any], key: str) -> dict[str, Any]:
    block = channel.get(key)
    return block if isinstance(block, dict) else {}


# --------------------------------------------------------------------------- #
# Schedule compilation — daily-total-first → firmware number writes
# --------------------------------------------------------------------------- #
def compile_schedule(
    channel: dict[str, Any],
    lighting_window: tuple[int, int] | None = None,
    now: datetime | None = None,
) -> dict[str, Any]:
    """Compile ``mlPerDay + window + mode (+ night weighting)`` into the firmware
    entity writes, an explicit plan, and plain-language output.

    Returns ``{"writes": {bindingRole: value}, "plan": {...}, "warnings": [...]}``.
    ``plan.summaryText`` is the mandatory always-visible sentence — schedule math
    must never be opaque ("funky math" is a research-verified trust killer).

    ``lighting_window`` is the tank's lights-OFF window as ``(start_min, end_min)``
    when the profile provides one and the channel opted into inheriting it.

    A same-day respread (see :func:`respread_plan`) stored in
    ``channel.state.respread`` overrides the compiled intervals for today only, so
    the drift verifier doesn't immediately "repair" an accepted catch-up.
    """
    schedule = _cfg(channel, "schedule")
    guards = _cfg(channel, "guards")
    warnings: list[dict[str, str]] = []

    ml_per_day = max(0.0, _f(schedule.get("mlPerDay")))
    mode = schedule.get("mode") if schedule.get("mode") in ("continuous", "doses") else "continuous"
    win_start = parse_hhmm(schedule.get("windowStart"), 0)
    win_end = parse_hhmm(schedule.get("windowEnd"), 0)
    win_len = window_minutes(win_start, win_end)

    if ml_per_day <= 0:
        warnings.append({"code": "no_volume", "message": "Daily volume is 0 ml — nothing will dose."})

    # --- night weighting (continuous mode only) --------------------------------
    night = schedule.get("night") if isinstance(schedule.get("night"), dict) else {}
    night_enabled = bool(night.get("enabled")) and mode == "continuous"
    if night.get("useLightingSchedule") and lighting_window is not None:
        night_start, night_end = int(lighting_window[0]) % 1440, int(lighting_window[1]) % 1440
    else:
        night_start = parse_hhmm(night.get("windowStart"), 1320)
        night_end = parse_hhmm(night.get("windowEnd"), 480)
    night_pct = min(NIGHT_PERCENT_MAX, max(0.0, _f(night.get("percent"), 50.0))) if night_enabled else 0.0

    night_min = _overlap_minutes(win_start, win_end, night_start, night_end) if night_enabled else 0
    if night_enabled and night_min == 0:
        warnings.append({
            "code": "night_outside_window",
            "message": "The night window has no overlap with the dosing window — night weighting is inactive.",
        })
        night_pct = 0.0
    day_min = max(0, win_len - night_min)

    night_ml = ml_per_day * night_pct / 100.0
    day_ml = ml_per_day - night_ml
    if day_min == 0 and day_ml > 0:
        # dosing window entirely inside the night window: everything is "night"
        night_ml, day_ml = ml_per_day, 0.0

    # --- derive per-dose volume + intervals ------------------------------------
    per_dose = 0.0
    day_interval = FIRMWARE_INTERVAL_MAX
    night_interval = FIRMWARE_INTERVAL_MAX
    if ml_per_day > 0:
        if mode == "doses":
            doses = max(1, int(_f(schedule.get("dosesPerDay"), 1)))
            per_dose = ml_per_day / doses
            # ceil, not floor: floor lets the firmware's elapsed counter squeeze in an
            # extra dose in a tiny window (win 8 min / 3 doses → interval 2 → 4 doses).
            day_interval = max(FIRMWARE_INTERVAL_MIN, math.ceil(win_len / doses))
            if day_interval > FIRMWARE_INTERVAL_MAX:
                day_interval = FIRMWARE_INTERVAL_MAX
                warnings.append({
                    "code": "interval_capped",
                    "message": "Doses can't be spread that thinly — the firmware interval is capped at 240 min.",
                })
            night_interval = day_interval
        else:
            day_rate = day_ml / day_min if day_min else 0.0        # ml per in-window minute
            night_rate = night_ml / night_min if night_min else 0.0
            fastest = max(day_rate, night_rate)
            if fastest <= 0:
                fastest = ml_per_day / win_len
            per_dose = fastest * TARGET_INTERVAL_MIN
            per_dose = min(FIRMWARE_DOSE_ML_MAX, max(FIRMWARE_DOSE_ML_MIN, per_dose))
            max_per_dose = _f(guards.get("maxPerDoseMl"), FIRMWARE_DOSE_ML_MAX)
            if max_per_dose > 0:
                per_dose = min(per_dose, max_per_dose)
            day_interval = (
                int(min(FIRMWARE_INTERVAL_MAX, max(FIRMWARE_INTERVAL_MIN, round(per_dose / day_rate))))
                if day_rate > 0 else FIRMWARE_INTERVAL_MAX
            )
            night_interval = (
                int(min(FIRMWARE_INTERVAL_MAX, max(FIRMWARE_INTERVAL_MIN, round(per_dose / night_rate))))
                if night_rate > 0 else day_interval
            )
        per_dose = round(per_dose, 2)
        if per_dose <= 0:
            per_dose = FIRMWARE_DOSE_ML_MIN
            warnings.append({
                "code": "dose_floor",
                "message": "The computed per-dose volume sits at the firmware floor of 0.1 ml.",
            })

    # --- same-day respread override (accepted catch-up must survive drift repair) --
    # The respread records the plan it was computed AGAINST (base*): if the user
    # edits the schedule afterwards (e.g. halves mlPerDay after a high test), the
    # base no longer matches and the override is ignored + flagged stale — a
    # safety edit must never keep dosing at the old catch-up cadence.
    respread_stale = False
    respread = _cfg(channel, "state").get("respread")
    if isinstance(respread, dict) and respread and now is not None and respread.get("date") == now.date().isoformat():
        base_matches = (
            abs(_f(respread.get("basePerDoseMl"), per_dose) - per_dose) <= 0.011
            and int(_f(respread.get("baseDayIntervalMin"), day_interval)) == day_interval
            and int(_f(respread.get("baseNightIntervalMin"), night_interval)) == night_interval
        )
        if base_matches:
            day_interval = int(_f(respread.get("dayIntervalMin"), day_interval)) or day_interval
            night_interval = int(_f(respread.get("nightIntervalMin"), night_interval)) or night_interval
        else:
            respread_stale = True

    # --- realised totals (dose-count truth, not the requested figure) ----------
    doses_day = (day_min // day_interval) if day_interval else 0
    doses_night = (night_min // night_interval) if night_interval else 0
    if mode == "doses" and night_min == 0:
        doses_day = min(doses_day, max(1, int(_f(schedule.get("dosesPerDay"), 1)))) if per_dose else 0
    realised = per_dose * (doses_day + doses_night)
    if ml_per_day > 0 and realised > 0 and abs(realised - ml_per_day) / ml_per_day > 0.10:
        warnings.append({
            "code": "realised_drift",
            "message": (
                f"Firmware granularity lands at {realised:.1f} ml/day against the requested "
                f"{ml_per_day:.1f} ml/day — adjust volume or window if that matters."
            ),
        })

    # --- daily cap ---------------------------------------------------------------
    max_daily = _f(guards.get("maxDailyMl"))
    if max_daily <= 0:
        max_daily = math.ceil(ml_per_day * AUTO_DAILY_CAP_MULT / 5.0) * 5.0 if ml_per_day > 0 else 0.0
    elif ml_per_day > 0 and max_daily < ml_per_day:
        warnings.append({
            "code": "cap_below_daily",
            "message": (
                f"Max-daily cap ({max_daily:.0f} ml) is below the daily target ({ml_per_day:.0f} ml) — "
                "the schedule can never complete."
            ),
        })

    # --- kalk-specific: evaporation / salinity budget ---------------------------
    if channel.get("chemical") == "kalk":
        evap_limit = _f(_cfg(channel, "guards").get("evaporationLimitMlPerDay"))
        if evap_limit > 0 and ml_per_day > evap_limit:
            warnings.append({
                "code": "kalk_exceeds_evaporation",
                "message": (
                    f"Kalk at {ml_per_day:.0f} ml/day exceeds the evaporation budget "
                    f"({evap_limit:.0f} ml/day) — the excess raises water level and drops salinity."
                ),
            })

    # --- plain-language summary --------------------------------------------------
    window_text = "all day" if win_start == win_end else f"{_fmt_hhmm(win_start)}–{_fmt_hhmm(win_end)}"
    if ml_per_day <= 0:
        summary_text = "No daily volume set."
    elif mode == "doses":
        summary_text = (
            f"{ml_per_day:g} ml/day in {doses_day or 1} doses of {per_dose:g} ml, "
            f"every {day_interval} min {window_text}"
        )
    elif night_pct > 0:
        summary_text = (
            f"{ml_per_day:g} ml/day continuous, {per_dose:g} ml every {day_interval} min by day / "
            f"{night_interval} min at night — {night_pct:g}% overnight "
            f"{_fmt_hhmm(night_start)}–{_fmt_hhmm(night_end)}"
        )
    else:
        summary_text = (
            f"{ml_per_day:g} ml/day continuous, {per_dose:g} ml every {day_interval} min {window_text}"
        )

    writes: dict[str, float] = {}
    if ml_per_day <= 0:
        # A zeroed schedule is a SAFETY edit: write the zero so the firmware
        # stops sizing doses from its old volume, and so drift detection guards
        # the zero like any other value (previously writes={} left the pump
        # dosing its stale schedule while the panel said "nothing will dose").
        writes = {"doseVolumeNumber": 0.0}
    else:
        writes = {
            "doseVolumeNumber": per_dose,
            "doseIntervalNumber": float(day_interval),
            "nightIntervalNumber": float(night_interval),
            "maxDailyNumber": max_daily,
            "windowStartNumber": float(win_start),
            "windowEndNumber": float(win_end),
            "nightStartNumber": float(night_start if night_pct > 0 else win_start),
            "nightEndNumber": float(night_end if night_pct > 0 else win_start),
        }
        ph_pause = _f(guards.get("phPauseAbove"))
        ph_resume = _f(guards.get("phResumeBelow"))
        if ph_pause > 0:
            writes["phStopNumber"] = ph_pause
            writes["phResumeNumber"] = ph_resume if 0 < ph_resume < ph_pause else round(ph_pause - 0.1, 2)

    plan = {
        "mlPerDay": ml_per_day,
        "mode": mode,
        "perDoseMl": per_dose,
        "dayIntervalMin": day_interval,
        "nightIntervalMin": night_interval,
        "dosesDay": doses_day,
        "dosesNight": doses_night,
        "realisedMlPerDay": round(realised, 2),
        "dayMl": round(day_ml, 2),
        "nightMl": round(night_ml, 2),
        "dayMinutes": day_min,
        "nightMinutes": night_min,
        "windowStart": win_start,
        "windowEnd": win_end,
        "nightStart": night_start,
        "nightEnd": night_end,
        "nightPercent": night_pct,
        "maxDailyMl": max_daily,
        "summaryText": summary_text,
        "respreadStale": respread_stale,
    }
    return {"writes": writes, "plan": plan, "warnings": warnings}


# --------------------------------------------------------------------------- #
# Guard mirror — HA-side view of why a channel is (or would be) blocked
# --------------------------------------------------------------------------- #
def guard_reasons(
    channel: dict[str, Any],
    live: dict[str, Any] | None,
    now_minutes: int,
    manual: bool = False,
    now: datetime | None = None,
) -> list[dict[str, str]]:
    """Mirror of the firmware guard chain plus the HA-only guards, for display and
    for gating HA-initiated actions. Shape matches awc.start_guard_reasons:
    ``{code, severity: block|warn, message}``. The firmware remains the enforcement
    layer — an empty list here never *causes* a dose."""
    live = live or {}
    reasons: list[dict[str, str]] = []
    guards = _cfg(channel, "guards")
    state = _cfg(channel, "state")

    def block(code: str, message: str) -> None:
        reasons.append({"code": code, "severity": "block", "message": message})

    def warn(code: str, message: str) -> None:
        reasons.append({"code": code, "severity": "warn", "message": message})

    if not channel.get("enabled"):
        block("disabled", "Channel is disabled.")
    if live.get("enabledSwitch") is False:
        block("firmware_disabled", "The doser's enable switch is off.")
    if _f(_cfg(channel, "calibration").get("stepsPerMl")) <= 0:
        block("not_calibrated", "Not calibrated yet — scheduled dosing is blocked until calibration is stored.")
    if live.get("deviceOnline") is False:
        block("device_offline", "Doser entities are unavailable — device appears offline.")
    sync_state = _cfg(channel, "sync").get("state")
    if sync_state == "failed":
        block("not_synced", "The last settings write to the device could not be verified.")
    if live.get("reservoirLow") is True:
        block("reservoir_low", "Reservoir float reports low — doses are being skipped.")

    ph_entity = str(guards.get("phEntity") or "")
    if channel.get("chemical") == "kalk" and not ph_entity and not guards.get("phMissingAcknowledged"):
        block(
            "ph_unacknowledged",
            "No pH failsafe is configured — acknowledge that schedule and volume caps are the only protection.",
        )
    if ph_entity:
        if live.get("phUnavailable"):
            block("ph_unavailable", "pH sensor is unavailable — dosing paused (fail-safe).")
        else:
            ph = live.get("phValue")
            pause_above = _f(guards.get("phPauseAbove"))
            # Same fallback as the firmware write path: a resume of 0 (or ≥ pause)
            # would otherwise latch the mirror forever.
            resume_below = _f(guards.get("phResumeBelow"))
            if not 0 < resume_below < pause_above:
                resume_below = round(pause_above - 0.1, 2)
            latched = bool(state.get("phLatchedHigh"))
            if ph is not None and pause_above > 0:
                ph = _f(ph)
                if ph >= pause_above or (latched and ph >= resume_below):
                    block(
                        "ph_blocked",
                        f"pH {ph:.2f} — paused at ≥ {pause_above:.2f}, resumes below {resume_below:.2f}.",
                    )

    if guards.get("suspendDuringAwc", True) and live.get("awcActive"):
        block("awc_active", "Suspended — an automatic water change is active.")

    suspended_until = _parse_iso(state.get("suspendedUntil"))
    now_dt = live.get("now")
    if suspended_until is not None and isinstance(now_dt, datetime) and now_dt < suspended_until:
        block("suspended", f"Dosing lockout active until {suspended_until.strftime('%H:%M')}.")

    if not manual and guards.get("quietHoursEnabled"):
        qs = parse_hhmm(guards.get("quietStart"), 60)
        qe = parse_hhmm(guards.get("quietEnd"), 300)
        if within_window(now_minutes, qs, qe):
            block("quiet_hours", "Inside quiet hours.")

    max_daily = _f(guards.get("maxDailyMl"))
    if max_daily <= 0:
        # Mirror the auto cap the firmware is actually enforcing (compile_schedule
        # writes mlPerDay x 1.25 rounded to 5 when the guard is 0 = auto).
        ml_per_day = _f(_cfg(channel, "schedule").get("mlPerDay"))
        max_daily = math.ceil(ml_per_day * AUTO_DAILY_CAP_MULT / 5.0) * 5.0 if ml_per_day > 0 else 0.0
    dosed = _f(live.get("dosedTodayMl"))
    if max_daily > 0 and dosed >= max_daily:
        block("daily_cap_reached", f"Daily cap reached ({dosed:.1f} of {max_daily:.0f} ml).")

    if channel.get("chemical") == "livefood" and now is not None:
        fresh = freshness_state(_cfg(channel, "reservoir"), now)
        if fresh["status"] == "stale":
            block("stale_food",
                  "The live-food culture is past its shelf life — refresh the "
                  "reservoir and tap 'Refreshed', or nothing doses.")
        elif fresh["status"] == "aging":
            warn("food_aging",
                 f"Live food is nearing its shelf life (~{fresh['hoursLeft']:.0f} h left).")

    if live.get("reservoirLow") is None and str(_cfg(channel, "driver").get("entities", {}).get("reservoirLowSensor") or "") == "":
        # advisory only: ledger-empty without a float is never a hard stop
        remaining = _f(_cfg(channel, "reservoir").get("remainingMl"))
        if _f(_cfg(channel, "reservoir").get("volumeMl")) > 0 and remaining <= 0:
            warn("reservoir_ledger_empty", "The reservoir ledger reads empty — refill and log it (no float fitted).")

    return reasons


# --------------------------------------------------------------------------- #
# Missed-dose trajectory
# --------------------------------------------------------------------------- #
def expected_dosed_ml(plan: dict[str, Any], now_minutes: int) -> float:
    """What the firmware's Dosed Today sensor *should* read at ``now_minutes``,
    walking the day minute-by-minute with the same static-elapsed-counter logic
    the firmware interval executor uses."""
    per_dose = _f(plan.get("perDoseMl"))
    if per_dose <= 0:
        return 0.0
    total = 0.0
    for _, ml in _simulate_day(plan, until_minute=max(0, min(1440, int(now_minutes)))):
        total += ml
    return round(total, 2)


def missed_state(
    expected_ml: float,
    actual_ml: float,
    per_dose_ml: float,
    tolerance_pct: float = MISSED_TOLERANCE_PCT,
) -> dict[str, Any]:
    """Classify the expected-vs-delivered shortfall. ``missed`` needs to clear both
    an absolute floor (2 doses — one skip is noise) and a relative one."""
    shortfall = max(0.0, _f(expected_ml) - _f(actual_ml))
    per_dose = max(0.0, _f(per_dose_ml))
    threshold = max(2 * per_dose, _f(expected_ml) * max(0.0, tolerance_pct) / 100.0)
    if shortfall <= max(per_dose, 0.01):
        status = "ok"
    elif shortfall <= threshold:
        status = "behind"
    else:
        status = "missed"
    return {"missedMl": round(shortfall, 2), "status": status}


def respread_plan(
    channel: dict[str, Any],
    plan: dict[str, Any],
    missed_ml: float,
    now_minutes: int,
    dosed_today_ml: float,
) -> dict[str, Any]:
    """The one-tap catch-up: re-spread ``missed_ml`` across the rest of today's
    window by tightening the interval, never by raising the per-dose volume, and
    never past the daily cap. Kalk always recommends skip — a kalk catch-up bolus
    is the classic overdose story."""
    if channel.get("chemical") == "kalk":
        return {"recommendation": "skip", "reason": "Kalk shortfalls are skipped by design — never re-dosed."}
    missed = max(0.0, _f(missed_ml))
    per_dose = _f(plan.get("perDoseMl"))
    if missed <= 0 or per_dose <= 0:
        return {"recommendation": "skip", "reason": "Nothing to re-spread."}

    minutes_left = _remaining_window_minutes(plan, now_minutes)
    if minutes_left < FIRMWARE_INTERVAL_MIN * 2:
        return {"recommendation": "skip", "reason": "Not enough dosing window left today."}

    max_daily = _f(plan.get("maxDailyMl"))
    planned_rest = max(0.0, _f(plan.get("realisedMlPerDay")) - _f(dosed_today_ml) - missed)
    if max_daily > 0 and _f(dosed_today_ml) + planned_rest + missed > max_daily:
        return {
            "recommendation": "skip",
            "reason": f"Re-spreading would break the {max_daily:.0f} ml daily cap.",
        }

    target_ml = planned_rest + missed
    interval = int(max(FIRMWARE_INTERVAL_MIN, min(FIRMWARE_INTERVAL_MAX, minutes_left // max(1, math.ceil(target_ml / per_dose)))))
    return {
        "recommendation": "respread",
        "dayIntervalMin": interval,
        "nightIntervalMin": interval,
        "writes": {"doseIntervalNumber": float(interval), "nightIntervalNumber": float(interval)},
        "note": (
            f"Re-spreads {missed:.1f} ml across the remaining {minutes_left} min "
            f"({per_dose:g} ml every {interval} min until midnight)."
        ),
    }


def _remaining_window_minutes(plan: dict[str, Any], now_minutes: int) -> int:
    start = int(_f(plan.get("windowStart")))
    end = int(_f(plan.get("windowEnd")))
    return sum(1 for m in range(max(0, min(1440, int(now_minutes))), 1440) if within_window(m, start, end))


# --------------------------------------------------------------------------- #
# Reservoir ledger
# --------------------------------------------------------------------------- #
def reservoir_state(reservoir: dict[str, Any], ml_per_day: float, now: datetime) -> dict[str, Any]:
    volume = max(0.0, _f(reservoir.get("volumeMl")))
    remaining = min(volume, max(0.0, _f(reservoir.get("remainingMl")))) if volume else 0.0
    low_threshold = max(0.0, _f(reservoir.get("lowThresholdMl")))
    daily = max(0.0, _f(ml_per_day))
    days = round(remaining / daily, 1) if daily > 0 and volume > 0 else None
    refilled = _parse_iso(reservoir.get("refilledAt"))
    primed = _parse_iso(reservoir.get("primedAt"))
    refill_without_reprime = refilled is not None and (primed is None or primed < refilled)
    return {
        "volumeMl": volume,
        "remainingMl": round(remaining, 1),
        "percent": round(remaining / volume * 100.0, 1) if volume > 0 else None,
        "daysUntilEmpty": days,
        "low": bool(volume > 0 and remaining <= low_threshold),
        "refillWithoutReprime": refill_without_reprime,
    }


# --------------------------------------------------------------------------- #
# Calibration, wear, integrity
# --------------------------------------------------------------------------- #
# --------------------------------------------------------------------------- #
# 2-part chemical spacing (Stage E) — alkalinity and calcium must never dose
# into the same water volume minutes apart (localized precipitation). Groups:
# kalk IS alkalinity chemistry, so it shares the alk group.
# --------------------------------------------------------------------------- #
_SPACING_GROUPS = {"alk": "alk", "kalk": "alk", "ca": "ca", "mg": "mg"}


def spacing_group(chemical: str) -> str:
    """The spacing group a chemical belongs to ('' = ungrouped: trace, live food
    and 'other' never participate in spacing)."""
    return _SPACING_GROUPS.get(str(chemical or ""), "")


def spacing_pair_key(group_a: str, group_b: str) -> str:
    """Canonical matrix key — alphabetical, so 'ca|alk' and 'alk|ca' are one row."""
    return "|".join(sorted((group_a, group_b)))


def spacing_gap_minutes(spacing: dict[str, Any] | None, group_a: str, group_b: str) -> float:
    """Required minutes between doses of two groups (0 = no constraint)."""
    spacing = spacing or {}
    if not spacing.get("enabled") or not group_a or not group_b or group_a == group_b:
        return 0.0
    matrix = spacing.get("matrix") if isinstance(spacing.get("matrix"), dict) else {}
    return max(0.0, _f(matrix.get(spacing_pair_key(group_a, group_b))))


def channel_min_gap_minutes(spacing: dict[str, Any] | None, chemical: str) -> float:
    """The FIRMWARE number for a channel: the largest gap its group owes any other
    group. The firmware guard is per-node ('minutes since any OTHER group dosed on
    this node'), so the max is the safe single value to hold there."""
    group = spacing_group(chemical)
    spacing = spacing or {}
    if not group or not spacing.get("enabled"):
        return 0.0
    matrix = spacing.get("matrix") if isinstance(spacing.get("matrix"), dict) else {}
    gaps = [max(0.0, _f(v)) for k, v in matrix.items()
            if group in str(k).split("|") and len(str(k).split("|")) == 2
            and str(k).split("|")[0] != str(k).split("|")[1]]
    return max(gaps, default=0.0)


def spacing_verdict(
    spacing: dict[str, Any] | None, chemical: str,
    group_last_dose: dict[str, datetime | None] | None, now: datetime,
) -> dict[str, Any]:
    """HA-side manual-dose gate: may this channel dose NOW given when each group
    last dosed? Returns {ok, waitMinutes, conflict}. Unknown last-dose times pass
    (advisory HA layer — the per-node firmware guard is the enforcement)."""
    group = spacing_group(chemical)
    if not group or not (spacing or {}).get("enabled"):
        return {"ok": True, "waitMinutes": 0.0, "conflict": ""}
    worst_wait = 0.0
    conflict = ""
    for other, last in (group_last_dose or {}).items():
        if other == group or last is None:
            continue
        gap = spacing_gap_minutes(spacing, group, other)
        if gap <= 0:
            continue
        try:
            elapsed = (now - last).total_seconds() / 60.0
        except TypeError:
            continue
        wait = gap - elapsed
        if wait > worst_wait:
            worst_wait = wait
            conflict = other
    return {"ok": worst_wait <= 0, "waitMinutes": round(max(0.0, worst_wait), 1),
            "conflict": conflict}


def phase_offsets(spacing: dict[str, Any] | None, groups_present: Iterable[str]) -> dict[str, float]:
    """Compile-time stagger so scheduled doses naturally interleave (alk :00 /
    ca :30 for a 30-min gap): groups in alphabetical order, each offset by the
    cumulative gap owed to its predecessor. The firmware guard remains the
    enforcement; this just keeps it from ever needing to trip."""
    spacing = spacing or {}
    ordered = sorted({g for g in groups_present if g})
    offsets: dict[str, float] = {}
    cursor = 0.0
    previous = ""
    for group in ordered:
        if previous:
            cursor += spacing_gap_minutes(spacing, previous, group)
        offsets[group] = cursor
        previous = group
    return offsets


def brushed_calibration_from_run(measured_ml: float, run_seconds: float = 30.0) -> float:
    """Brushed-head calibration: the firmware runs the pump for a FIXED timed burst
    (default 30 s — rhymes with the stepper's exact 100 revolutions), the keeper
    measures the output, and the flow rate is the quotient. Returns ml/s
    (0 = invalid measurement; callers treat 0 as not-calibrated)."""
    secs = _f(run_seconds)
    ml = _f(measured_ml)
    if secs <= 0 or ml <= 0:
        return 0.0
    return round(ml / secs, 3)


def freshness_state(reservoir: dict[str, Any] | None, now: datetime) -> dict[str, Any]:
    """Live-food freshness: cultures are perishable, so ``mixedAt`` + ``shelfLifeDays``
    grade the reservoir fresh / aging (final 25% of shelf life) / stale. FAIL-CLOSED:
    no mixedAt stamp means STALE — never dose food of unknown age. shelfLifeDays <= 0
    disables expiry (a non-perishable brushed additive)."""
    res = reservoir or {}
    shelf_days = _f(res.get("shelfLifeDays"), 1.0)
    if shelf_days <= 0:
        return {"status": "fresh", "hoursLeft": None, "ageHours": None}
    mixed = _parse_iso(res.get("mixedAt"))
    if mixed is None:
        return {"status": "stale", "hoursLeft": 0.0, "ageHours": None}
    try:
        age_h = max(0.0, (now - mixed).total_seconds() / 3600.0)
    except TypeError:
        return {"status": "stale", "hoursLeft": 0.0, "ageHours": None}
    left_h = shelf_days * 24.0 - age_h
    if left_h <= 0:
        status = "stale"
    elif left_h <= shelf_days * 24.0 * 0.25:
        status = "aging"
    else:
        status = "fresh"
    return {"status": status, "hoursLeft": round(max(0.0, left_h), 1),
            "ageHours": round(age_h, 1)}


def is_brushed(channel: dict[str, Any]) -> bool:
    """Driver-awareness helper: brushed DC heads have no stepper motion and no pH
    guard hardware — guards and calibration flows branch on this."""
    driver = channel.get("driver") if isinstance(channel.get("driver"), dict) else {}
    return str(driver.get("type") or "") == "openreef_esphome_brushed"


def calibration_from_measured(
    measured_ml: float, steps_per_100rev: float = CAL_STEPS_PER_100REV
) -> dict[str, float] | None:
    """100-revolution volumetric calibration: ``stepsPerMl = steps / measured``.
    None on an implausible measurement (Kamoer KPHM ~0.27 ml/rev ⇒ ~27 ml/100 rev;
    we accept 1–1000 ml to cover other heads without accepting junk)."""
    measured = _f(measured_ml)
    if not 1.0 <= measured <= 1000.0:
        return None
    return {
        "stepsPerMl": round(steps_per_100rev / measured, 1),
        "mlPerRev": round(measured / 100.0, 4),
        "measuredMl": round(measured, 2),
    }


def tube_wear_increment(delta_ml: float, steps_per_ml: float, steps_per_s: float) -> float:
    """Pump-run seconds represented by ``delta_ml`` of delivered volume. Dose
    execution is firmware-side, so HA derives runtime from what it *can* see:
    the dosed-today delta, the stored calibration, and the synced motor speed.
    Speed-aware, so the estimate stays honest when the user retunes the motor."""
    delta = _f(delta_ml)
    spm = _f(steps_per_ml)
    sps = _f(steps_per_s)
    if delta <= 0 or spm <= 0 or sps <= 0:
        return 0.0
    return delta * spm / sps


def integrity(channel: dict[str, Any], now: datetime, recal_days: int = RECAL_NAG_DAYS) -> dict[str, Any]:
    """Per-channel dose-integrity trust status — "is this head lying to you?".
    Combines calibration age, refill-without-reprime, sync trouble, and drift
    between successive calibrations. Feeds the panel pill and the maintenance
    nags; it never gates dosing by itself."""
    reasons: list[str] = []
    cal = _cfg(channel, "calibration")
    steps_per_ml = _f(cal.get("stepsPerMl"))
    if steps_per_ml <= 0:
        return {"status": "untrusted", "reasons": ["Not calibrated."]}

    age = _age_days(cal.get("calibratedAt"), now)
    if age is not None and age >= recal_days:
        reasons.append(f"Calibration is {age:.0f} days old — recalibrate.")
    history = cal.get("history") if isinstance(cal.get("history"), list) else []
    if len(history) >= 2:
        last = _f((history[0] or {}).get("stepsPerMl"))
        prev = _f((history[1] or {}).get("stepsPerMl"))
        if last > 0 and prev > 0 and abs(last - prev) / prev * 100.0 > CAL_DRIFT_WARN_PCT:
            reasons.append("Successive calibrations differ by more than 10% — check the tube and rollers.")
    res = reservoir_state(_cfg(channel, "reservoir"), 0.0, now)
    if res["refillWithoutReprime"]:
        reasons.append("Refilled without re-priming — the next doses may run air.")
    sync_state = _cfg(channel, "sync").get("state")
    if sync_state in ("failed", "drift"):
        reasons.append("Device settings diverged from OpenReef — see sync state.")
    if _cfg(channel, "state").get("rolloverAnomaly"):
        reasons.append("The dosed-today counter reset away from midnight — possible device reboot/data loss.")

    return {"status": "attention" if reasons else "ok", "reasons": reasons}


def tube_state(wear: dict[str, Any], now: datetime) -> dict[str, Any]:
    run_hours = max(0.0, _f(wear.get("runSeconds"))) / 3600.0
    life = _f(wear.get("tubeLifeHours"), 1000.0) or 1000.0
    return {
        "runHours": round(run_hours, 1),
        "doseCount": int(_f(wear.get("doseCount"))),
        "tubeLifeHours": life,
        "tubePercentUsed": round(min(100.0, run_hours / life * 100.0), 1),
        "tubeReplaceDue": run_hours >= life,
        "tubeReplaceSoon": run_hours >= life * 0.9,
        "installedDays": _age_days(wear.get("tubeInstalledAt"), now),
    }


# --------------------------------------------------------------------------- #
# Ramp (advisory only — feeds the suggested-dose display, never writes)
# --------------------------------------------------------------------------- #
def ramp_target(ramp: dict[str, Any], base_ml_per_day: float) -> dict[str, Any] | None:
    """New-tank ramp: start at ``startPercent`` of the computed dose and step up
    ``stepPercent`` per confirmed test checkpoint, capped at 100%. Purely
    advisory — the user applies the suggestion themselves (locked decision)."""
    if not isinstance(ramp, dict) or not ramp.get("enabled"):
        return None
    base = max(0.0, _f(base_ml_per_day))
    checkpoints = ramp.get("checkpoints") if isinstance(ramp.get("checkpoints"), list) else []
    start = min(100.0, max(10.0, _f(ramp.get("startPercent"), 60.0)))
    step = min(50.0, max(1.0, _f(ramp.get("stepPercent"), 10.0)))
    percent = min(100.0, start + step * len(checkpoints))
    return {
        "percent": percent,
        "targetMlPerDay": round(base * percent / 100.0, 1),
        "checkpointsDone": len(checkpoints),
        "complete": percent >= 100.0,
        "maxDkhPerDay": _f(ramp.get("maxDkhPerDay"), 1.0),
        "hint": (
            "Ramp complete — dosing at the full computed rate."
            if percent >= 100.0
            else f"Dosing at {percent:g}% of the computed rate — test, then log a checkpoint to step up {step:g}%."
        ),
    }


# --------------------------------------------------------------------------- #
# Rollover + dry-run
# --------------------------------------------------------------------------- #
def detect_rollover(prev_ml: float, new_ml: float) -> bool:
    """The firmware resets Dosed Today at device-local midnight; HA detects that
    by the value dropping — clock-immune (the Kamoer/Jebao timezone lesson)."""
    prev = _f(prev_ml)
    new = _f(new_ml)
    return prev > 0.005 and new < prev - 0.005


def _simulate_day(plan: dict[str, Any], until_minute: int = 1440):
    """Yield ``(minute, ml)`` for each dose the firmware's static-elapsed-counter
    executor would fire before ``until_minute``. Mirrors the firmware exactly:
    the counter only advances inside the dosing window, and the night interval
    applies while inside the night window."""
    per_dose = _f(plan.get("perDoseMl"))
    day_int = int(_f(plan.get("dayIntervalMin"))) or FIRMWARE_INTERVAL_MAX
    night_int = int(_f(plan.get("nightIntervalMin"))) or day_int
    ws = int(_f(plan.get("windowStart")))
    we = int(_f(plan.get("windowEnd")))
    ns = int(_f(plan.get("nightStart")))
    ne = int(_f(plan.get("nightEnd")))
    night_active = _f(plan.get("nightPercent")) > 0
    if per_dose <= 0:
        return
    elapsed = 0
    for minute in range(max(0, min(1440, until_minute))):
        if not within_window(minute, ws, we):
            continue
        elapsed += 1
        interval = night_int if (night_active and within_window(minute, ns, ne)) else day_int
        if elapsed >= interval:
            elapsed = 0
            yield minute, per_dose


def dry_run_preview(plan: dict[str, Any], max_entries: int = 300) -> dict[str, Any]:
    """Tomorrow's plan, computed — no motor. The cheap slice of the loved DIY
    simulation mode: exact dose times, sizes, and the daily total the firmware
    granularity will actually deliver."""
    doses = [
        {"minute": minute, "time": _fmt_hhmm(minute), "ml": _f(plan.get("perDoseMl"))}
        for minute, _ in _simulate_day(plan)
    ]
    truncated = len(doses) > max_entries
    total = round(sum(d["ml"] for d in doses), 2)
    return {
        "doses": doses[:max_entries],
        "count": len(doses),
        "totalMl": total,
        "truncated": truncated,
        "summaryText": plan.get("summaryText", ""),
    }


def next_dose_eta(plan: dict[str, Any], now_minutes: int) -> dict[str, Any] | None:
    """Minutes until the next scheduled dose (today only; None when no more fire)."""
    now_minutes = max(0, min(1440, int(now_minutes)))
    consumed = sum(1 for _ in _simulate_day(plan, until_minute=now_minutes))
    for index, (minute, ml) in enumerate(_simulate_day(plan)):
        if index >= consumed and minute >= now_minutes:
            return {"minute": minute, "time": _fmt_hhmm(minute), "inMinutes": minute - now_minutes, "ml": ml}
    return None


# --------------------------------------------------------------------------- #
# Panel-facing summary
# --------------------------------------------------------------------------- #
def summary(
    channels: dict[str, Any],
    live_map: dict[str, dict[str, Any]],
    now: datetime,
    lighting_window: tuple[int, int] | None = None,
) -> dict[str, Any]:
    """Everything the Dosing tab needs, per channel. ``live_map`` carries the
    orchestrator's entity snapshot per channel id (see guard_reasons for keys)."""
    now_minutes = now.hour * 60 + now.minute
    out: dict[str, Any] = {}
    for channel_id, channel in (channels or {}).items():
        if not isinstance(channel, dict):
            continue
        live = live_map.get(channel_id, {}) if isinstance(live_map, dict) else {}
        compiled = compile_schedule(channel, lighting_window, now)
        plan = compiled["plan"]
        dosed = _f(live.get("dosedTodayMl"))
        state_blk = _cfg(channel, "state")
        # Missed-dose display: the ORCHESTRATOR owns the "missed" verdict — it is
        # debounced, gated on sensor availability, and baselined against mid-day plan
        # changes. The live computation here is display-colour only and never
        # escalates past "behind": an unbound/offline sensor is "unknown", never a
        # giant false "missed" (the #1 trust breaker this feature exists to avoid).
        active = bool(channel.get("enabled")) and bool(_cfg(channel, "schedule").get("enabled"))
        trusted = bool(live.get("dosedSensorTrusted"))
        expected = expected_dosed_ml(plan, now_minutes) if (active and trusted) else None
        if state_blk.get("missedSince"):
            missed = {"missedMl": _f(state_blk.get("missedMl")), "status": "missed", "pendingDecision": True}
        elif not active:
            missed = {"missedMl": 0.0, "status": "idle"}
        elif not trusted:
            missed = {"missedMl": 0.0, "status": "unknown"}
        else:
            missed = missed_state(expected, dosed, plan["perDoseMl"])
            if missed["status"] == "missed":
                missed["status"] = "behind"
        cal = _cfg(channel, "calibration")
        out[channel_id] = {
            "name": channel.get("name") or channel_id,
            "chemical": channel.get("chemical") or "other",
            "chemicalLabel": _CHEMICAL_LABELS.get(channel.get("chemical"), "Other"),
            "enabled": bool(channel.get("enabled")),
            "plan": plan,
            "warnings": compiled["warnings"],
            "writes": compiled["writes"],
            "guards": guard_reasons(channel, {**live, "now": now}, now_minutes),
            "dosedTodayMl": round(dosed, 2),
            "expectedTodayMl": expected,
            "missed": missed,
            "reservoir": reservoir_state(_cfg(channel, "reservoir"), plan["mlPerDay"], now),
            "integrity": integrity(channel, now),
            "tube": tube_state(_cfg(channel, "wear"), now),
            "calibration": {
                "stepsPerMl": _f(cal.get("stepsPerMl")),
                "mlPerRev": round(_f(cal.get("measuredMl")) / 100.0, 4) if _f(cal.get("measuredMl")) > 0 else None,
                "calibratedAt": cal.get("calibratedAt") or "",
                "ageDays": _age_days(cal.get("calibratedAt"), now),
                "recalDue": (_age_days(cal.get("calibratedAt"), now) or 0) >= RECAL_NAG_DAYS
                if cal.get("calibratedAt") else False,
                "history": (cal.get("history") or [])[:3],
            },
            "sync": {
                "state": _cfg(channel, "sync").get("state", "unsynced"),
                "lastSyncedAt": _cfg(channel, "sync").get("lastSyncedAt", ""),
                "lastError": _cfg(channel, "sync").get("lastError", ""),
            },
            "ramp": ramp_target(_cfg(channel, "ramp"), plan["mlPerDay"]),
            "nextDose": next_dose_eta(plan, now_minutes) if channel.get("enabled") else None,
        }
    return out
