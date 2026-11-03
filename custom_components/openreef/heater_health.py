"""Passive heater condition learning. No HA imports and no actuator commands.

Power is electrical input, not efficiency or remaining life. Shared supplies need
an observed controller action or a one-tap load identification; watts alone cannot
prove that a load is a heater. References are retained until an explicit reset.
"""
from __future__ import annotations

import math
from copy import deepcopy
from statistics import median
from typing import Any

MODES = ("off", "heater", "shared_fan", "shared_chiller")
MIN_CYCLES = 12
MIN_SPAN = 7 * 86400
MAX_GAP = 180
MAX_REFERENCES = 160
MAX_LOADS = 8
IDLE_MAX_W = 5.0  # Lower loads remain unassigned on shared supplies without telemetry.


def number(value: Any) -> float | None:
    if isinstance(value, bool):
        return None
    try:
        result = float(value)
        return result if math.isfinite(result) else None
    except (ValueError, TypeError, OverflowError):
        return None


def normalise_settings(raw: Any) -> dict:
    raw = raw if isinstance(raw, dict) else {}
    mode = raw.get("mode")
    climate = raw.get("climateEntity")
    return {"mode": mode if mode in MODES else "off",
            "climateEntity": climate if isinstance(climate, str) and
            climate.startswith("climate.") and climate.count(".") == 1 and
            climate.replace(".", "_").replace("_", "").isalnum() else ""}


def new_state(now: float, binding: list | None = None) -> dict:
    return {"version": 1, "started": now, "binding": binding, "loads": [],
            "reference": [], "recent": [], "hours": [], "last": None,
            "segment": None, "issue": None, "notified": None}


def restart(state: dict, now: float, settings_only: bool = False) -> dict:
    fresh = new_state(now, state.get("binding"))
    fresh["previous"] = {"at": now, "reference": deepcopy(state.get("reference", [])),
                         "loads": deepcopy(state.get("loads", []))}
    fresh["loads"] = deepcopy(state.get("loads", []))
    if not settings_only:
        fresh["loads"] = [load for load in fresh["loads"] if load.get("role") != "heating"]
    return fresh


def identify(state: dict, load_id: str, role: str) -> None:
    if role not in ("heating", "cooling", "idle"):
        raise ValueError("Choose heater, cooling equipment or standby")
    load = next((x for x in state["loads"] if x["id"] == load_id), None)
    if load is None:
        raise ValueError("That power pattern is no longer available; refresh first")
    if load.get("ambiguous"):
        raise ValueError("Heating and cooling overlap at this wattage. Restore controller telemetry or meter the outputs separately.")
    load.update(role=role, source="confirmed")
    # Do not retrospectively learn temperature response from uncertain periods.
    state["segment"] = None
    state["last"] = None
    state["notified"] = None


def _load(state: dict, watts: float, now: float) -> dict | None:
    matches = [x for x in state["loads"] if abs(watts - x["watts"]) <= max(1.0, x["watts"] * .06)]
    if matches:
        return min(matches, key=lambda x: abs(watts - x["watts"]))
    if len(state["loads"]) >= MAX_LOADS:
        transient = next((x for x in state["loads"] if not x.get("role") and x["seconds"] < 120), None)
        if transient:
            state["loads"].remove(transient)
        else:
            return None
    # IDs stay unique when a heater reset retains cooling patterns.
    serial = max([int(x["id"][1:]) for x in state["loads"]] or [0]) + 1
    load = {"id": f"p{serial}", "watts": round(watts, 2), "role": None,
            "source": "observed", "seconds": 0.0, "visits": 0, "first": now}
    state["loads"].append(load)
    return load


def _role(state: dict, sample: dict, mode: str, load: dict | None) -> tuple[str, str]:
    action = sample.get("action")
    watts = sample["watts"]
    if action in ("heating", "cooling"):
        # A controller requesting heat does not prove the element is drawing power.
        if watts <= IDLE_MAX_W:
            return "idle", "power"
        return action, "controller"
    if action in ("idle", "off") and watts <= IDLE_MAX_W:
        return "idle", "controller"
    if load and load.get("ambiguous"):
        return "uncertain", "overlapping"
    if load and load.get("role"):
        return load["role"], load["source"]
    if mode == "heater":
        return ("heating", "power") if watts > IDLE_MAX_W else ("idle", "power")
    # On a shared plug even a small fan could overlap controller standby. Do not
    # silently assign the lowest/highest observed power to standby/heating.
    assigned = [x for x in state["loads"] if x.get("role") in ("heating", "cooling")
                and abs(watts - x["watts"]) <= max(2.0, x["watts"] * .35)]
    roles = {x["role"] for x in assigned}
    if len(roles) == 1:
        return roles.pop(), "inferred"
    return "uncertain", "unassigned"


def _finish(state: dict) -> None:
    segment = state.get("segment")
    if not segment or not segment.get("safe", True) or segment["role"] != "heating" or segment["seconds"] < 300:
        return
    if not segment.get("completeStart"):
        return  # Starting/restarting mid-cycle cannot create a reference cycle.
    seconds = segment["seconds"]
    cycle = {"at": segment["endAt"], "seconds": seconds,
             "watts": segment["wattSeconds"] / seconds,
             "gap": segment["gapSeconds"] / seconds,
             "start": segment["startC"], "end": segment["endC"],
             "rate": (segment["endC"] - segment["startC"]) / (seconds / 60),
             "hour": int(segment["endAt"] // 3600) % 24}
    # Water-change/relocation jumps are caught between samples too; very large
    # whole-cycle excursions and cycles that never warmed are not healthy seeds.
    delta = cycle["end"] - cycle["start"]
    state["recent"] = (state["recent"] + [cycle])[-12:]
    refs = state["reference"]
    matched = comparable(refs, cycle)
    stable_power = not refs or abs(cycle["watts"] / median(x["watts"] for x in refs) - 1) < .12
    stable_control = not refs or abs(cycle["end"] - median(x["end"] for x in refs)) < .35
    if .04 <= delta <= 1.5 and stable_power and stable_control and len(refs) < MAX_REFERENCES:
        # Retain the original reference for familiar conditions. New ambient
        # ranges may be learned, but never erase drift in an existing range.
        if not ready(state) or len(matched) < 5:
            refs.append(cycle)


def comparable(refs: list, cycle: dict) -> list:
    return [x for x in refs if abs(x["gap"] - cycle["gap"]) <= 1.25
            and abs(x["start"] - cycle["start"]) <= .3
            and min(abs(x["hour"] - cycle["hour"]), 24 - abs(x["hour"] - cycle["hour"])) <= 4
            and x["at"] != cycle["at"]]


def ready(state: dict) -> bool:
    refs = state["reference"]
    return len(refs) >= MIN_CYCLES and refs[-1]["at"] - refs[0]["at"] >= MIN_SPAN


def _issue(code: str, title: str, message: str, severity: str = "warning") -> dict:
    return {"code": code, "title": title, "message": message, "severity": severity}


def observe(state: dict, sample: dict, mode: str) -> dict:
    """Consume one time-aligned observation; missing readings never become zero.

    Call on power events as well as periodically. Integrate only contiguous
    intervals, using the preceding state (zero-order hold). Learning uses complete
    heating episodes, independent of how frequently a smart plug reports.
    """
    now = sample["at"]
    state["issue"] = None
    previous = state.get("last")
    error = sample.get("error")
    water = sample.get("waterC")
    lo, hi = sample.get("minC"), sample.get("maxC")
    # Temperature alerts run during learning, missing room data and maintenance.
    if water is not None and ((hi is not None and water > hi) or (lo is not None and water < lo)):
        state["issue"] = _issue("temperature", "Temperature outside the configured range",
            "Check the tank temperature and heating/cooling system now. This does not identify which component failed.", "critical")
    if error or sample.get("paused"):
        state["last"] = None
        state["segment"] = None
        state.pop("noHeatSince", None)
        state.pop("overrunSince", None)
        state["current"] = "unknown"
        state["pauseReason"] = error or "Maintenance or water change — learning resumes automatically"
        if error:
            state.setdefault("missingSince", now)
            if now - state["missingSince"] >= 900 and not state["issue"]:
                state["issue"] = _issue("readings", "Heater monitoring needs attention", error)
        return summary(state, now)
    state.pop("missingSince", None)
    state.pop("pauseReason", None)
    if previous and now <= previous["at"]:
        return summary(state, now)
    dt = now - previous["at"] if previous else 0
    contiguous = previous is not None and 0 < dt <= MAX_GAP
    if contiguous and abs(water - previous["waterC"]) > .35:
        # Unknown water changes / probe moves: do not train through abrupt jumps.
        state["settleUntil"] = now + 1800
    if now < state.get("settleUntil", 0):
        state["last"] = None
        state["segment"] = None
        state.pop("noHeatSince", None)
        state.pop("overrunSince", None)
        state["current"] = "unknown"
        state["pauseReason"] = "Temperature changed abruptly — allowing the tank to settle"
        return summary(state, now)
    load = _load(state, sample["watts"], now)
    role, source = _role(state, sample, mode, load)
    sample = {**sample, "role": role, "source": source, "loadId": load["id"] if load else None}
    state.update(current=role, source=source, watts=sample["watts"], observedAt=now)
    if load and source == "controller" and role != "uncertain":
        # Telemetry can distinguish equal-wattage outputs; power alone cannot.
        if load.get("ambiguous"):
            pass
        elif load["role"] in (None, role):
            load.update(role=role, source="controller")
        else:
            load.update(role=None, source="controller", ambiguous=True)
    elif load and mode == "heater":
        load.update(role=role, source="power")
    if not contiguous:
        state["segment"] = None
        state.pop("noHeatSince", None)
        state.pop("overrunSince", None)
    if contiguous:
        old_load = next((x for x in state["loads"] if x["id"] == previous.get("loadId")), None)
        if old_load:
            old_load["seconds"] += dt
        bucket = int(previous["at"] // 3600)
        hour = next((x for x in state["hours"] if x["hour"] == bucket), None)
        if hour is None:
            hour = {"hour": bucket, "seconds": 0, "heating": 0, "cooling": 0,
                    "heatingWh": 0, "coolingWh": 0, "unassignedWh": 0}
            state["hours"].append(hour)
        hour["seconds"] += dt
        if previous["role"] in ("heating", "cooling"):
            hour[previous["role"]] += dt
            idle = [x["watts"] for x in state["loads"] if x.get("role") == "idle"]
            standby = min(idle) if idle else 0
            hour[previous["role"] + "Wh"] += max(0, previous["watts"] - standby) * dt / 3600
        elif previous["role"] == "uncertain":
            hour["unassignedWh"] += previous["watts"] * dt / 3600
        state["hours"] = [x for x in state["hours"] if x["hour"] > int(now // 3600) - 24]
        seg = state.get("segment")
        if seg:
            seg["safe"] = seg.get("safe", True) and state["issue"] is None
            seg["seconds"] += dt
            seg["wattSeconds"] += previous["watts"] * dt
            seg["gapSeconds"] += (previous["waterC"] - previous["roomC"]) * dt
            seg.update(endC=water, endAt=now)
        if role != previous["role"]:
            _finish(state)
            state["segment"] = None
    if state.get("segment") is None:
        state["segment"] = {"role": role, "seconds": 0, "wattSeconds": 0,
            "gapSeconds": 0, "startC": water, "endC": water, "endAt": now,
            "safe": state["issue"] is None,
            "completeStart": contiguous and previous["role"] == "idle"}
        if load:
            load["visits"] += 1
    # Several independent cycles, rather than polling frequency, establish drift.
    refs = state["reference"]
    recent = [x for x in state["recent"] if x["at"] > now - 3 * 86400][-3:]
    issue = None
    if len(refs) >= 3 and len(recent) == 3:
        base_w = median(x["watts"] for x in refs)
        if all(abs(x["watts"] / base_w - 1) > .15 for x in recent):
            issue = _issue("power_changed", "Heating power has changed",
                "Active wattage differs from the reference across three cycles. Have you replaced the heater? Check supply voltage and the heater before assuming a fault.")
        elif all(abs(x["end"] - median(r["end"] for r in refs)) > .4 for x in recent):
            issue = _issue("settings_changed", "Heating stops at a different temperature",
                "Have you adjusted the thermostat or moved a probe? If nothing changed, check the controller and probes.")
        elif ready(state):
            slow = []
            for cycle in recent:
                matches = comparable(refs, cycle)
                if len(matches) < 3:
                    slow.append(False)
                    continue
                rates = [x["rate"] for x in matches]
                typical = median(rates)
                spread = median(abs(x - typical) for x in rates)
                slow.append(typical > .002 and cycle["rate"] < typical - max(typical * .35, spread * 3, .002))
            if all(slow):
                issue = _issue("response", "Heating is slower than expected",
                    "Three cycles warmed more slowly than the baseline at similar room conditions. Check circulation, heater condition, lids and recent equipment changes.")
    # Explicit demand is stronger than an inferred set point or plug relay state.
    if sample.get("action") == "heating" and role == "idle":
        state.setdefault("noHeatSince", now)
        if now - state["noHeatSince"] >= 900:
            issue = _issue("no_heat", "Heating requested without power draw",
                "The controller has requested heat for 15 minutes without an active load. Check its output, the heater thermostat and the power supply.")
    else:
        state.pop("noHeatSince", None)
    if len(refs) >= 3 and role == "heating" and water > median(x["end"] for x in refs) + .5:
        state.setdefault("overrunSince", now)
        if now - state["overrunSince"] >= 300:
            issue = _issue("overrun", "Heating continues above its usual cut-off",
                "The heater has remained active above its learned stopping temperature for five minutes. Check thermostat settings, the controller and probe placement now.")
    else:
        state.pop("overrunSince", None)
    if not issue:
        candidate = next((x for x in state["loads"] if not x.get("role") and not x.get("ambiguous") and x["seconds"] >= 600), None)
        if source == "overlapping":
            issue = _issue("overlap", "Heating and cooling power overlap",
                "Restore the connected thermostat's state readings or meter its outputs separately. Wattage alone cannot identify which output is running.")
        elif candidate or load is None:
            issue = _issue("identify", "Identify a power pattern",
                "Open Energy → Heater health to identify the heater, cooling equipment or controller standby. Unassigned readings are excluded from the heater baseline.")
    if state["issue"] is None:
        state["issue"] = issue
    state["last"] = sample
    return summary(state, now)


def summary(state: dict, now: float) -> dict:
    issue = state.get("issue")
    refs = state["reference"]
    learned = ready(state)
    paused = state.get("pauseReason")
    old = now - state.get("observedAt", 0) > MAX_GAP
    recent = [x for x in state["recent"] if x["at"] >= now - 3 * 86400]
    active_power = median(x["watts"] for x in recent[-3:]) if recent else None
    base_power = median(x["watts"] for x in refs) if refs else None
    known = not paused and not old
    status = "critical" if issue and issue["severity"] == "critical" else "check" if issue else "paused" if not known else "waiting" if learned and not recent else "monitoring" if learned else "learning"
    hours = [x for x in state["hours"] if x["hour"] > int(now // 3600) - 24]
    seconds = sum(x["seconds"] for x in hours)
    return {"status": status, "current": state.get("current", "unknown") if known else "unknown",
            "source": state.get("source", "unknown"), "issue": deepcopy(issue),
            "reason": paused or ("Waiting for fresh readings" if old else
                "The heater has not completed a cycle recently. Its reference is retained." if learned and not recent else
                "Monitoring against your reference" if learned else "Learning during normal use. No action needed."),
            "cycles": len(refs), "cyclesNeeded": MIN_CYCLES, "minimumDays": MIN_SPAN // 86400,
            "baselineReady": learned, "baselineWatts": round(base_power, 1) if base_power else None,
            "powerPercent": round(100 * active_power / base_power) if known and base_power and active_power else None,
            "lastHeatingAt": recent[-1]["at"] if recent else None,
            "observedAt": state.get("observedAt"), "watts": state.get("watts") if known else None,
            "coverageHours": round(seconds / 3600, 1),
            "heatingLoadPercent": round(100 * sum(x["heating"] for x in hours) / seconds) if seconds else None,
            "heatingWhEstimate": round(sum(x["heatingWh"] for x in hours), 1),
            "coolingWhEstimate": round(sum(x["coolingWh"] for x in hours), 1),
            "unassignedWhEstimate": round(sum(x["unassignedWh"] for x in hours), 1),
            "loads": [{"id": x["id"], "watts": x["watts"], "role": x["role"],
                       "source": x["source"], "ambiguous": bool(x.get("ambiguous"))} for x in state["loads"] if x["seconds"] >= 600],
            "coolingObserved": any(x.get("role") == "cooling" for x in state["loads"])}
