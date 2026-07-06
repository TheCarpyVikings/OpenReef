"""Vision engine — Frigate event folding, zone dedupe, restart survival, alerts.

The vision engine (custom_components/openreef/vision.py) is pure stdlib, so it
unit-tests cleanly. These tests pin the semantics that are easy to get wrong
against real Frigate 0.17 behavior:

  * `entered_zones` is cumulative and repeated in every update message — a
    new -> update x N -> end lifecycle must count ONE visit per zone.
  * Aggregates must survive HA restarts (rehydrate + never-seen-since-online).
  * Surface loitering is per tracked object — other fish must not clear it.
  * Notification cooldowns gate the 5-minute tick.
  * Feeding reports are never fabricated when no session was open.

Run standalone:  python3 tests/test_vision.py
"""

from __future__ import annotations

import json
import os
import sys

_HERE = os.path.dirname(os.path.abspath(__file__))
_ROOT = os.path.dirname(_HERE)

sys.path.insert(0, _HERE)
import _ha_stubs  # noqa: E402

_ha_stubs.install()

sys.path.insert(0, os.path.join(_ROOT, "custom_components"))
from openreef import vision  # noqa: E402

SPECIES = ["clownfish", "six_line_wrasse", "chalk_goby"]
ZONES = ["anemone", "torch_coral", "feeding_zone"]


def _event(object_id, etype="update", species="clownfish", zones=None, entered=None, camera="reef_tank"):
    return json.dumps(
        {
            "type": etype,
            "after": {
                "id": object_id,
                "camera": camera,
                "label": "ClownFish",
                "sub_label": species,
                "current_zones": zones or [],
                "entered_zones": entered or [],
            },
        }
    )


def test_parse_normalises_and_never_raises():
    parsed = vision.parse_frigate_event(_event("1-a", species="clownfish"))
    assert parsed["id"] == "1-a" and parsed["species"] == "clownfish"
    # sub_label as [name, score] (Frigate sometimes ships the pair)
    raw = json.loads(_event("1-b"))
    raw["after"]["sub_label"] = ["chalk_goby", 0.91]
    assert vision.parse_frigate_event(json.dumps(raw))["species"] == "chalk_goby"
    # garbage payloads -> None, no exception
    for garbage in ("", "not json", "[]", '{"after": 3}', b"\xff\xfe", None):
        assert vision.parse_frigate_event(garbage) is None


def test_zone_visits_deduped_across_update_spam():
    rt = vision.new_runtime(SPECIES, ZONES, now=1000.0)
    # new -> 30 updates -> end, entered_zones cumulative + repeated every message
    vision.apply_event(rt, vision.parse_frigate_event(_event("obj1", "new")), 1000.0)
    for i in range(30):
        vision.apply_event(
            rt,
            vision.parse_frigate_event(
                _event("obj1", "update", zones=["torch_coral"], entered=["torch_coral"])
            ),
            1001.0 + i,
        )
    vision.apply_event(
        rt,
        vision.parse_frigate_event(_event("obj1", "end", entered=["torch_coral"])),
        1040.0,
    )
    assert rt["zoneVisits"]["torch_coral"] == 1
    assert "obj1" not in rt["eventZones"]  # evicted on end
    # a NEW object visiting the same coral counts again
    vision.apply_event(
        rt,
        vision.parse_frigate_event(_event("obj2", "update", entered=["torch_coral"])),
        1100.0,
    )
    assert rt["zoneVisits"]["torch_coral"] == 2
    # unknown zones are ignored
    vision.apply_event(
        rt,
        vision.parse_frigate_event(_event("obj3", "update", entered=["sump"])),
        1101.0,
    )
    assert "sump" not in rt["zoneVisits"]


def test_last_seen_and_missing_semantics_survive_restart():
    rt = vision.new_runtime(SPECIES, ZONES, now=1000.0)
    vision.apply_event(rt, vision.parse_frigate_event(_event("o1", species="clownfish")), 2000.0)
    flushed = vision.summary(rt, 2000.0)

    # QUICK restart (gap within REHYDRATE_MAX_GAP_S): online clock carries over
    rt_quick = vision.new_runtime(SPECIES, ZONES, now=3000.0)
    vision.rehydrate(rt_quick, flushed, now=3000.0)
    assert rt_quick["lastSeen"]["clownfish"] == 2000.0
    assert rt_quick["onlineAt"] == 1000.0
    # never-seen goby IS reportable once observation exceeds the threshold
    missing = vision.missing_species(rt_quick, now=5000.0, threshold_hours=0.5)
    assert "chalk_goby" in missing

    # LONG gap (vision was off for days): online clock must restart NOW —
    # time-off is not observation time, so never-seen species do NOT false-alarm
    rt_cold = vision.new_runtime(SPECIES, ZONES, now=500000.0)
    vision.rehydrate(rt_cold, flushed, now=500000.0)
    assert rt_cold["lastSeen"]["clownfish"] == 2000.0  # last-seen always survives
    assert rt_cold["onlineAt"] == 500000.0             # clock NOT dragged back
    missing = vision.missing_species(rt_cold, now=500000.0, threshold_hours=12)
    assert "clownfish" in missing        # genuinely stale sighting still alerts
    assert "chalk_goby" not in missing   # never-seen needs fresh observation time
    # threshold 0 = alert disabled
    assert vision.missing_species(rt_cold, 500000.0, 0) == []
    # a fresh install online for five minutes reports nothing
    rt3 = vision.new_runtime(SPECIES, ZONES, now=500000.0)
    assert vision.missing_species(rt3, 500300.0, 12) == []
    # rehydrate never raises on garbage
    vision.rehydrate(rt3, "corrupt", now=500000.0)
    vision.rehydrate(rt3, {"lastSeen": "nope", "onlineAt": [], "notifiedAt": 7}, now=1.0)


def test_notify_cooldowns_survive_restart():
    rt = vision.new_runtime(SPECIES, ZONES, now=0.0)
    assert vision.should_notify(rt, "missing:chalk_goby", 1000.0, cooldown_s=21600)
    flushed = vision.summary(rt, 1000.0)
    # restart: without rehydrated cooldowns the same missing fish would re-page
    rt2 = vision.new_runtime(SPECIES, ZONES, now=1500.0)
    vision.rehydrate(rt2, flushed, now=1500.0)
    assert not vision.should_notify(rt2, "missing:chalk_goby", 2000.0, 21600)
    assert vision.should_notify(rt2, "missing:chalk_goby", 30000.0, 21600)


def test_surface_loitering_is_per_object():
    rt = vision.new_runtime(SPECIES, ZONES, now=0.0)
    vision.apply_event(
        rt, vision.parse_frigate_event(_event("sick", zones=["surface"])), 100.0
    )
    # another fish swimming elsewhere must NOT clear the sick fish's timer
    vision.apply_event(
        rt, vision.parse_frigate_event(_event("healthy", zones=["torch_coral"])), 200.0
    )
    loiterers = vision.surface_loiterers(rt, now=500.0, min_seconds=300)
    assert [l["id"] for l in loiterers] == ["sick"]
    # the sick fish leaving the surface clears it
    vision.apply_event(rt, vision.parse_frigate_event(_event("sick", zones=[])), 600.0)
    assert vision.surface_loiterers(rt, 900.0, 300) == []
    # the distress zone name is configurable (Frigate zones are user-named)
    rt2 = vision.new_runtime(SPECIES, ZONES, now=0.0, surface_zone="water_surface")
    vision.apply_event(
        rt2, vision.parse_frigate_event(_event("f1", zones=["water_surface"])), 50.0
    )
    assert [l["id"] for l in vision.surface_loiterers(rt2, 500.0, 300)] == ["f1"]


def test_eviction_is_lru_not_insertion_order():
    rt = vision.new_runtime(SPECIES, ZONES, now=0.0)
    # 'keeper' is the FIRST-inserted object but stays active (worst case for
    # naive insertion-order eviction: a long-tracked fish under id churn)
    vision.apply_event(
        rt, vision.parse_frigate_event(_event("keeper", entered=["anemone"], zones=["surface"])), 1.0
    )
    for i in range(vision.MAX_TRACKED_OBJECTS + 40):
        vision.apply_event(
            rt, vision.parse_frigate_event(_event(f"churn-{i}")), 10.0 + i
        )
        if i % 10 == 0:  # keeper keeps producing events -> stays recent
            vision.apply_event(
                rt,
                vision.parse_frigate_event(
                    _event("keeper", entered=["anemone"], zones=["surface"])
                ),
                10.5 + i,
            )
    assert "keeper" in rt["eventZones"]           # survived: LRU, not FIFO
    assert rt["zoneVisits"]["anemone"] == 1       # never re-counted
    assert "keeper" in rt["surfaceAt"]            # distress clock never reset
    assert len(rt["eventZones"]) <= vision.MAX_TRACKED_OBJECTS + 1


def test_notify_cooldown_gates_and_recovers():
    rt = vision.new_runtime(SPECIES, ZONES, now=0.0)
    assert vision.should_notify(rt, "missing:goby", 1000.0, cooldown_s=3600)
    assert not vision.should_notify(rt, "missing:goby", 1500.0, 3600)  # within cooldown
    assert vision.should_notify(rt, "missing:goby", 5000.0, 3600)  # cooldown expired
    vision.clear_notify(rt, "missing:goby")
    assert vision.should_notify(rt, "missing:goby", 5001.0, 3600)  # recovery resets


def test_feed_report_latency_and_no_fabrication():
    rt = vision.new_runtime(SPECIES, ZONES, now=0.0)
    # closing without a session must return None, never a zeroed record
    assert vision.close_feed_session(rt, SPECIES, 180, 100.0) is None
    vision.start_feed_session(rt, 1000.0)
    vision.apply_event(rt, vision.parse_frigate_event(_event("a", species="clownfish")), 1012.0)
    vision.apply_event(rt, vision.parse_frigate_event(_event("b", species="six_line_wrasse")), 1400.0)
    report = vision.close_feed_session(rt, SPECIES, window_s=180, now=1500.0)
    rows = {r["species"]: r for r in report["rows"]}
    assert rows["clownfish"]["responded"] and rows["clownfish"]["latency"] == 12.0
    assert not rows["six_line_wrasse"]["responded"]  # showed up, but past the window
    assert rows["chalk_goby"]["latency"] is None
    assert report["respondedCount"] == 1
    assert rt["feedSession"] is None  # consumed


def test_state_topics_and_object_cap():
    rt = vision.new_runtime(SPECIES, ZONES, now=0.0)
    vision.apply_state_topic(rt, "anemone", b"clown_hosting")
    vision.apply_state_topic(rt, "tank", "clear_day")
    vision.apply_state_topic(rt, "count", "3.0")
    vision.apply_state_topic(rt, "count", "garbage")  # ignored, keeps last good
    assert rt["anemoneState"] == "clown_hosting"
    assert rt["tankState"] == "clear_day"
    assert rt["fishCount"] == 3
    # object bookkeeping stays bounded even if Frigate never sends `end`
    for i in range(vision.MAX_TRACKED_OBJECTS + 50):
        vision.apply_event(
            rt,
            vision.parse_frigate_event(_event(f"lost-{i}", "update", entered=["anemone"])),
            float(i),
        )
    assert len(rt["eventZones"]) <= vision.MAX_TRACKED_OBJECTS + 1


def test_fingerprint_identity():
    base = {"enabled": True, "topicPrefix": "frigate", "cameraName": "reef_tank",
            "species": ["a", "b"], "zones": ["z1"]}
    same = dict(base, species=["b", "a"])  # order-insensitive
    other_camera = dict(base, cameraName="frag_tank")
    assert vision.fingerprint(base) == vision.fingerprint(same)
    assert vision.fingerprint(base) != vision.fingerprint(other_camera)
    # alert/feedReport tweaks do NOT re-arm (runtime state survives those saves)
    with_alerts = dict(base, alerts={"missingFishHours": 12})
    assert vision.fingerprint(base) == vision.fingerprint(with_alerts)
    # feedReport tweaks must NOT re-arm (an open feed session survives the save)
    with_feed = dict(base, feedReport={"enabled": True})
    assert vision.fingerprint(base) == vision.fingerprint(with_feed)
    # the surface zone IS wiring (the engine matches on it) -> re-arm
    other_surface = dict(base, surfaceZone="water_surface")
    assert vision.fingerprint(base) != vision.fingerprint(other_surface)
    assert vision.fingerprint({"enabled": False}) == "disabled"
    assert vision.fingerprint(None) == "disabled"


# --- tiny standalone runner (so this works without pytest installed) ---

def _main() -> int:
    tests = sorted(
        (name, obj)
        for name, obj in globals().items()
        if name.startswith("test_") and callable(obj)
    )
    passed = 0
    failed = []
    for name, fn in tests:
        try:
            fn()
            passed += 1
            print(f"  PASS  {name}")
        except Exception as exc:  # noqa: BLE001 - report everything
            failed.append(name)
            print(f"  FAIL  {name}: {type(exc).__name__}: {exc}")
    print(f"\n{passed}/{len(tests)} passed", "" if not failed else f"— FAILED: {', '.join(failed)}")
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(_main())
