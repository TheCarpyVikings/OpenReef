"""Vision — pure Frigate-event mathematics for tank intelligence.

Like spawning.py and awc.py, this module is deliberately a **pure,
dependency-free, side-effect-free** computation layer (stdlib only — no Home
Assistant, no MQTT client, no network). Orchestration (the MQTT subscription,
tick scheduler, notifications, config persistence) lives in __init__.py per the
repo convention. Everything here is dict-in/dict-out so tests/test_vision.py
runs in the dependency-free CI.

What it does
------------
An external Frigate NVR watches the tank, detects fish, classifies species
(sub_labels) and tags polygon zones (corals, anemone, feeding area, surface).
Frigate publishes a JSON lifecycle per tracked object on `<prefix>/events`
(`type`: new/update/end, several messages per second per fish). This engine
folds that firehose into small, bounded aggregates:

  * per-species last-seen timestamps        → missing-fish detection
  * per-zone visit counts                   → "who visits which coral"
  * per-object surface loitering            → distress alerting
  * feed-session response latency per fish  → feeding report card

Semantics that are easy to get wrong (and are covered by tests):

  * `entered_zones` is CUMULATIVE over a tracked object's lifetime and repeated
    in every update message. Visits are counted once per (object id, zone) via
    a seen-set that is evicted when the object's `end` message arrives.
  * Aggregates must survive HA restarts: `rehydrate()` re-seeds last-seen from
    the last persisted summary, and `visionOnlineAt` makes "never seen since
    vision came online" reportable rather than silently unknowable.
  * Surface loitering is tracked PER OBJECT — another fish swimming elsewhere
    must not clear a distressed fish's surface timer.
  * Notifications get per-key cooldowns so a 5-minute tick cannot page a phone
    every 5 minutes about the same missing fish.
"""

from __future__ import annotations

import json
from typing import Any

# Evict oldest object-id bookkeeping beyond this many concurrent tracked
# objects. Frigate sends an `end` per object; this cap only matters if ends are
# lost (Frigate restart mid-track), and prevents unbounded growth either way.
MAX_TRACKED_OBJECTS = 200


# rehydrate() only restores the observation clock (onlineAt) when the persisted
# summary is at most this fresh. A short gap is an HA restart, where carrying the
# clock over keeps "never seen since online" honest; a long gap means vision was
# OFF, and counting that as observation time produces false missing-fish alarms.
REHYDRATE_MAX_GAP_S = 2 * 3600


def new_runtime(
    species: list[str], zones: list[str], now: float, surface_zone: str = "surface"
) -> dict[str, Any]:
    """Fresh in-memory aggregate state. Persisted only via summary()/rehydrate()."""
    return {
        "onlineAt": now,                            # epoch s vision came online
        "lastFlushAt": now,                         # epoch s summary last persisted
        "surfaceZone": surface_zone,                # Frigate zone that means "at the surface"
        "lastSeen": {s: None for s in species},     # species -> epoch s | None
        "zoneVisits": {z: 0 for z in zones},        # zone -> distinct-object visits
        "eventZones": {},                           # object id -> [zones already counted]
        "surfaceAt": {},                            # object id -> epoch s entered surface
        "anemoneState": None,                       # latest state-classifier strings
        "tankState": None,
        "fishCount": None,                          # latest <prefix>/<camera>/all payload
        "lastEventAt": None,                        # epoch s of last accepted event
        "feedSession": None,                        # {"startedAt": s, "firstSeen": {species: latency_s}}
        "notifiedAt": {},                           # alert key -> epoch s last notified
    }


def rehydrate(runtime: dict[str, Any], summary: Any, now: float) -> None:
    """Re-seed a fresh runtime from the last persisted summary (restart survival).

    Restores last-seen timestamps unconditionally (else a fish missing for days
    can never alert after a reboot) and notification cooldowns (else a restart
    re-pages about the same missing fish). The online clock is restored only
    when the summary is recent (REHYDRATE_MAX_GAP_S): after a long-off period
    or a re-enable, observation starts NOW — time vision was off must never
    count toward a "never seen for N hours" alarm. Zone counters restart per
    session by design — they feed daily deltas.
    """
    if not isinstance(summary, dict):
        return
    last_seen = summary.get("lastSeen")
    if isinstance(last_seen, dict):
        for species, ts in last_seen.items():
            if species in runtime["lastSeen"] and isinstance(ts, (int, float)):
                runtime["lastSeen"][species] = float(ts)
    notified = summary.get("notifiedAt")
    if isinstance(notified, dict):
        for key, ts in notified.items():
            if isinstance(key, str) and isinstance(ts, (int, float)):
                runtime["notifiedAt"][key] = float(ts)
    as_of = summary.get("asOf")
    online = summary.get("onlineAt")
    if (
        isinstance(as_of, (int, float))
        and isinstance(online, (int, float))
        and online > 0
        and now - float(as_of) <= REHYDRATE_MAX_GAP_S
    ):
        runtime["onlineAt"] = min(runtime["onlineAt"], float(online))


def fingerprint(cfg: Any) -> str:
    """Stable identity of the vision wiring. Orchestration re-arms the MQTT
    subscription ONLY when this changes — config saves that do not touch vision
    must never destroy runtime state (feed sessions, last-seen, counters)."""
    if not isinstance(cfg, dict):
        return "disabled"
    if not cfg.get("enabled"):
        return "disabled"
    return json.dumps(
        {
            "prefix": cfg.get("topicPrefix", ""),
            "camera": cfg.get("cameraName", ""),
            "species": sorted(cfg.get("species") or []),
            "zones": sorted(cfg.get("zones") or []),
            "surfaceZone": cfg.get("surfaceZone", "surface"),
        },
        sort_keys=True,
    )


def _sub_label(after: dict[str, Any]) -> str:
    """Frigate sub_label may be a string or [name, score]. Never raises."""
    raw = after.get("sub_label")
    if isinstance(raw, str):
        return raw
    if isinstance(raw, (list, tuple)) and raw and isinstance(raw[0], str):
        return raw[0]
    return ""


def parse_frigate_event(payload: Any) -> dict[str, Any] | None:
    """`<prefix>/events` JSON -> minimal normalised record, else None. Never raises."""
    try:
        data = json.loads(payload)
    except (ValueError, TypeError):
        return None
    if not isinstance(data, dict):
        return None
    after = data.get("after")
    if not isinstance(after, dict):
        return None
    object_id = after.get("id")
    return {
        "id": str(object_id) if object_id is not None else "",
        "type": str(data.get("type") or ""),        # new | update | end
        "camera": str(after.get("camera") or ""),
        "label": str(after.get("label") or ""),
        "species": _sub_label(after),
        "zones": [z for z in (after.get("current_zones") or []) if isinstance(z, str)],
        "entered": [z for z in (after.get("entered_zones") or []) if isinstance(z, str)],
    }


def apply_event(runtime: dict[str, Any], event: dict[str, Any], now: float) -> bool:
    """Fold one parsed event into the aggregates. Returns True if state changed."""
    changed = False
    object_id = event["id"]
    runtime["lastEventAt"] = now

    # Species last-seen + feed-session response latency.
    species = event["species"]
    if species in runtime["lastSeen"]:
        runtime["lastSeen"][species] = now
        changed = True
        feed = runtime.get("feedSession")
        if isinstance(feed, dict) and species not in feed["firstSeen"]:
            feed["firstSeen"][species] = round(now - feed["startedAt"], 1)

    # Zone visits: entered_zones is cumulative + repeated per message, so count
    # each zone once per object id (dedupe set evicted on the end message).
    if object_id:
        # LRU discipline: re-insert on every event so eviction (which only
        # matters when Frigate loses `end` messages) removes the object with
        # the STALEST activity, never a fish that is still being tracked —
        # evicting a live object would re-count its zones and reset its
        # surface-distress timer.
        if object_id in runtime["eventZones"]:
            counted = runtime["eventZones"].pop(object_id)
            runtime["eventZones"][object_id] = counted
        else:
            counted = runtime["eventZones"][object_id] = []
        if len(runtime["eventZones"]) > MAX_TRACKED_OBJECTS:
            oldest = next(iter(runtime["eventZones"]))
            runtime["eventZones"].pop(oldest, None)
            runtime["surfaceAt"].pop(oldest, None)
        for zone in event["entered"]:
            if zone in runtime["zoneVisits"] and zone not in counted:
                runtime["zoneVisits"][zone] += 1
                counted.append(zone)
                changed = True

        # Surface loitering is per object: set when THIS object is in the
        # surface zone, cleared when THIS object leaves or ends.
        if runtime.get("surfaceZone", "surface") in event["zones"]:
            runtime["surfaceAt"].setdefault(object_id, now)
        else:
            runtime["surfaceAt"].pop(object_id, None)

        if event["type"] == "end":
            runtime["eventZones"].pop(object_id, None)
            runtime["surfaceAt"].pop(object_id, None)

    return changed


def apply_state_topic(runtime: dict[str, Any], kind: str, payload: Any) -> None:
    """Fold a state-classifier or count topic payload. Never raises."""
    try:
        text = payload.decode() if isinstance(payload, (bytes, bytearray)) else str(payload)
    except Exception:  # noqa: BLE001 - defensive: arbitrary broker payloads
        return
    text = text.strip()[:64]
    if kind == "anemone":
        runtime["anemoneState"] = text or None
    elif kind == "tank":
        runtime["tankState"] = text or None
    elif kind == "count":
        try:
            runtime["fishCount"] = int(float(text))
        except ValueError:
            pass


def missing_species(runtime: dict[str, Any], now: float, threshold_hours: float) -> list[str]:
    """Species not positively identified within the threshold. A species never
    seen counts as missing once vision itself has been online past the
    threshold — otherwise a restart makes a genuinely missing fish unreportable."""
    if threshold_hours <= 0:
        return []
    cutoff = now - threshold_hours * 3600
    online_long_enough = runtime["onlineAt"] < cutoff
    missing = []
    for species, ts in runtime["lastSeen"].items():
        if ts is None:
            if online_long_enough:
                missing.append(species)
        elif ts < cutoff:
            missing.append(species)
    return missing


def surface_loiterers(runtime: dict[str, Any], now: float, min_seconds: float) -> list[dict[str, Any]]:
    """Object ids that have been continuously at the surface past min_seconds."""
    return [
        {"id": object_id, "seconds": round(now - since, 1)}
        for object_id, since in runtime["surfaceAt"].items()
        if now - since >= min_seconds
    ]


def should_notify(runtime: dict[str, Any], key: str, now: float, cooldown_s: float) -> bool:
    """Per-alert-key cooldown gate. Records the notification time when True."""
    last = runtime["notifiedAt"].get(key)
    if last is not None and now - last < cooldown_s:
        return False
    runtime["notifiedAt"][key] = now
    return True


def clear_notify(runtime: dict[str, Any], key: str) -> None:
    """Reset a cooldown when its condition recovers, so the next occurrence alerts."""
    runtime["notifiedAt"].pop(key, None)


def start_feed_session(runtime: dict[str, Any], now: float) -> None:
    runtime["feedSession"] = {"startedAt": now, "firstSeen": {}}


def close_feed_session(
    runtime: dict[str, Any], species: list[str], window_s: int, now: float
) -> dict[str, Any] | None:
    """Close the feed window -> bounded report-card record, or None when no
    session was open (never fabricate a record from a zeroed fallback)."""
    feed = runtime.get("feedSession")
    runtime["feedSession"] = None
    if not isinstance(feed, dict) or not feed.get("startedAt"):
        return None
    rows = [
        {
            "species": s,
            "latency": feed["firstSeen"].get(s),
            "responded": feed["firstSeen"].get(s) is not None
            and feed["firstSeen"][s] <= window_s,
        }
        for s in species
    ]
    return {
        "startedAt": feed["startedAt"],
        "endedAt": now,
        "rows": rows,
        "respondedCount": sum(1 for r in rows if r["responded"]),
    }


def summary(runtime: dict[str, Any], now: float) -> dict[str, Any]:
    """Small bounded snapshot: persisted for restart rehydration and served to
    the panel over websocket. Must stay tiny — it rides in the config entry."""
    return {
        "onlineAt": runtime["onlineAt"],
        "asOf": now,
        "lastSeen": dict(runtime["lastSeen"]),
        "notifiedAt": dict(runtime["notifiedAt"]),
        "zoneVisits": dict(runtime["zoneVisits"]),
        "anemoneState": runtime["anemoneState"],
        "tankState": runtime["tankState"],
        "fishCount": runtime["fishCount"],
        "lastEventAt": runtime["lastEventAt"],
        "feeding": runtime.get("feedSession") is not None,
    }
