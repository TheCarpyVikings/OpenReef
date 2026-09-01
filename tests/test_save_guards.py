"""Server-owned runtime survives a stale whole-config save (0.7.109).

The 2026-09-01 incident: a wall client frozen in Pulse mode posted an
hours-old config blob and erased a completed 35 L salt & mix — the mixing
vessel reverted to "50 L RODI on hand". save_config now carries every
server-owned ledger forward from the stored config: the mixing station's
vessels/batch/odometers, the AWC engine's state/reservoirs/ledger/wear,
the NPS feed-exchange/truce/hatchery runtime, consumables bottle levels
(newer-history rule) and the activity feed (union merge). Settings fields
stay the client's — a stale client can still revert a settings edit, but
never the water.

Run standalone:  python3 tests/test_save_guards.py
Or with pytest:  pytest tests/
"""

from __future__ import annotations

import copy
import os
import sys
from datetime import datetime, timedelta, timezone

_HERE = os.path.dirname(os.path.abspath(__file__))
_ROOT = os.path.dirname(_HERE)

sys.path.insert(0, _HERE)
import _ha_stubs  # noqa: E402

_ha_stubs.install()

sys.path.insert(0, os.path.join(_ROOT, "custom_components"))
import openreef as integration  # noqa: E402

from _fake_ha import FakeConnection, FakeEntry, FakeHass, run  # noqa: E402

CONF_SETTINGS = integration.CONF_SETTINGS
NOW = datetime(2026, 9, 1, 12, 0, 0, tzinfo=timezone.utc)
EARLIER = NOW - timedelta(hours=6)


def _iso(dt):
    return dt.isoformat()


# ------------------------------------------------------------- mixing station

def _mixing_stored():
    """The state the incident lost: 35 L vessel salted and ready."""
    return {
        "enabled": True,
        "layout": "single",
        "vessels": {
            "mix": {"volumeLitres": 35.0, "estimatedLitres": 35.0, "contents": "salt",
                    "levelSensorEntity": ""},
        },
        "rodi": {
            "rateLph": 9.21, "calibratedAt": _iso(EARLIER),
            "litresProcessed": 190.0, "meteredSince": _iso(EARLIER - timedelta(days=30)),
            "filters": [{"id": "f1", "label": "Sediment", "type": "sediment",
                         "ratedLitres": 2000.0, "litresProcessed": 190.0,
                         "changedAt": _iso(EARLIER)}],
        },
        "batch": {"state": "ready", "startedAt": _iso(EARLIER), "stageAt": _iso(EARLIER),
                  "litres": 35.0, "loggedPpt": 35.1, "testedAt": _iso(EARLIER)},
    }


def _mixing_stale():
    """What the frozen wall was holding: the pre-session snapshot."""
    return {
        "enabled": True,
        "layout": "single",
        "vessels": {
            "mix": {"volumeLitres": 50.0, "estimatedLitres": 50.0, "contents": "rodi",
                    "levelSensorEntity": ""},
        },
        "rodi": {
            "rateLph": 9.21, "calibratedAt": _iso(EARLIER),
            "litresProcessed": 150.0, "meteredSince": _iso(EARLIER - timedelta(days=30)),
            "filters": [{"id": "f1", "label": "Sediment", "type": "sediment",
                         "ratedLitres": 2000.0, "litresProcessed": 150.0,
                         "changedAt": _iso(EARLIER - timedelta(days=10))}],
        },
        "batch": {"state": "idle", "startedAt": "", "stageAt": "",
                  "litres": 0.0, "loggedPpt": 0.0, "testedAt": ""},
    }


def test_mixing_ledger_survives_a_stale_save():
    stored = {"mixingStation": _mixing_stored()}
    incoming = {"mixingStation": _mixing_stale()}
    incoming["mixingStation"]["salt"] = {"brand": "redsea_coralpro"}  # the client's edit
    integration._mixing_preserve_runtime(stored, incoming)
    mix = incoming["mixingStation"]
    assert mix["vessels"]["mix"]["estimatedLitres"] == 35.0
    assert mix["vessels"]["mix"]["contents"] == "salt"
    assert mix["batch"]["state"] == "ready" and mix["batch"]["litres"] == 35.0
    assert mix["rodi"]["litresProcessed"] == 190.0
    # Settings stay the client's: the volume revert and the brand edit both stand.
    assert mix["vessels"]["mix"]["volumeLitres"] == 50.0
    assert mix["salt"]["brand"] == "redsea_coralpro"


def test_mixing_flow_rate_follows_the_newer_calibration():
    stored = {"mixingStation": _mixing_stored()}
    stored["mixingStation"]["rodi"]["rateLph"] = 10.5
    stored["mixingStation"]["rodi"]["calibratedAt"] = _iso(NOW)   # fresh ceremony
    incoming = {"mixingStation": _mixing_stale()}
    integration._mixing_preserve_runtime(stored, incoming)
    assert incoming["mixingStation"]["rodi"]["rateLph"] == 10.5
    assert incoming["mixingStation"]["rodi"]["calibratedAt"] == _iso(NOW)


def test_mixing_manual_rate_edit_wins_on_equal_stamps():
    stored = {"mixingStation": _mixing_stored()}
    incoming = {"mixingStation": _mixing_stale()}
    incoming["mixingStation"]["rodi"]["rateLph"] = 8.0   # hand edit, stamp unchanged
    integration._mixing_preserve_runtime(stored, incoming)
    assert incoming["mixingStation"]["rodi"]["rateLph"] == 8.0


def test_mixing_filter_odometers_survive_but_stage_edits_stand():
    stored = {"mixingStation": _mixing_stored()}
    incoming = {"mixingStation": _mixing_stale()}
    incoming["mixingStation"]["rodi"]["filters"] = [
        {"id": "f1", "label": "Renamed", "type": "carbon", "ratedLitres": 3000.0,
         "litresProcessed": 150.0, "changedAt": _iso(EARLIER - timedelta(days=10))},
        {"id": "f9", "label": "New stage", "type": "di", "ratedLitres": 0.0,
         "litresProcessed": 0.0, "changedAt": ""},
    ]
    integration._mixing_preserve_runtime(stored, incoming)
    stages = incoming["mixingStation"]["rodi"]["filters"]
    assert stages[0]["litresProcessed"] == 190.0          # backend odometer
    assert stages[0]["changedAt"] == _iso(EARLIER)        # backend Changed stamp
    assert stages[0]["label"] == "Renamed" and stages[0]["ratedLitres"] == 3000.0
    assert stages[1]["label"] == "New stage"              # client addition untouched


def test_mixing_guard_replaces_a_client_that_predates_the_station():
    stored = {"mixingStation": _mixing_stored()}
    incoming = {"tank": {}}
    integration._mixing_preserve_runtime(stored, incoming)
    assert incoming["mixingStation"]["batch"]["state"] == "ready"
    integration._mixing_preserve_runtime(None, {})        # never raises
    integration._mixing_preserve_runtime({}, {"mixingStation": {}})


def test_incident_replay_through_the_real_save_handler():
    """The whole point end-to-end: the stale wall blob posts via save_config
    and the ready batch, contents and odometers all survive."""
    stored = integration._normalise_core_config({
        "mixingStation": _mixing_stored(),
        "activity": [{"timestamp": _iso(EARLIER), "message": "Mixing station: salt & mix done",
                      "type": "control"}],
    })
    entry = FakeEntry(options={CONF_SETTINGS: stored})
    hass = FakeHass(entries=[entry])
    stale = integration._normalise_core_config({
        "mixingStation": _mixing_stale(),
        "activity": [],
    })
    run(integration.websocket_save_config(hass, FakeConnection(), {"id": 1, "config": stale}))
    saved = entry.options[CONF_SETTINGS]["mixingStation"]
    assert saved["vessels"]["mix"]["estimatedLitres"] == 35.0
    assert saved["vessels"]["mix"]["contents"] == "salt"
    assert saved["batch"]["state"] == "ready" and saved["batch"]["litres"] == 35.0
    assert saved["rodi"]["litresProcessed"] == 190.0


# ----------------------------------------------------------------------- AWC

def _awc_stored():
    return {
        "enabled": True,
        "tankVolumeLitres": 200.0,
        "pumps": {"drain": {"switchEntity": "switch.drain", "mlPerS": 20.0,
                            "calibratedAt": _iso(EARLIER), "runSeconds": 5000.0,
                            "startCount": 40, "tubingInstalledAt": _iso(EARLIER)},
                  "fill": {"switchEntity": "switch.fill", "mlPerS": 19.0,
                           "calibratedAt": _iso(EARLIER), "runSeconds": 5100.0,
                           "startCount": 41, "tubingInstalledAt": _iso(EARLIER)}},
        "reservoirs": {"fresh": {"capacityLitres": 25.0, "remainingMl": 12000.0},
                       "waste": {"capacityLitres": 25.0, "filledMl": 9000.0}},
        "state": {"status": "paused", "pausedReason": "leak sensor wet",
                  "startedAt": _iso(EARLIER)},
        "history": [{"completedAt": _iso(EARLIER), "drainedL": 5.0, "filledL": 5.0}],
        "ledger": {"cumulativeDrainedL": 120.0, "cumulativeFilledL": 119.5},
        "todayLitres": 5.0, "weekLitres": 20.0, "monthLitres": 60.0,
    }


def test_awc_runtime_survives_a_stale_save():
    stored = {"automaticWaterChange": _awc_stored()}
    incoming = {"automaticWaterChange": copy.deepcopy(_awc_stored())}
    inc = incoming["automaticWaterChange"]
    inc["state"] = {"status": "idle"}                     # the stale revert
    inc["reservoirs"]["fresh"]["remainingMl"] = 25000.0
    inc["reservoirs"]["waste"]["filledMl"] = 0.0
    inc["history"] = []
    inc["ledger"] = {"cumulativeDrainedL": 0.0, "cumulativeFilledL": 0.0}
    inc["pumps"]["drain"]["runSeconds"] = 100.0
    inc["reservoirs"]["fresh"]["capacityLitres"] = 30.0   # the client's real edit
    integration._awc_preserve_runtime(stored, incoming)
    assert inc["state"]["status"] == "paused"             # a fault must not un-pause
    assert inc["reservoirs"]["fresh"]["remainingMl"] == 12000.0
    assert inc["reservoirs"]["waste"]["filledMl"] == 9000.0
    assert inc["history"] and inc["ledger"]["cumulativeDrainedL"] == 120.0
    assert inc["pumps"]["drain"]["runSeconds"] == 5000.0
    assert inc["reservoirs"]["fresh"]["capacityLitres"] == 30.0


def test_awc_pump_calibration_newer_in_stored_wins():
    stored = {"automaticWaterChange": _awc_stored()}
    stored["automaticWaterChange"]["pumps"]["fill"]["mlPerS"] = 21.5
    stored["automaticWaterChange"]["pumps"]["fill"]["calibratedAt"] = _iso(NOW)
    incoming = {"automaticWaterChange": copy.deepcopy(_awc_stored())}
    incoming["automaticWaterChange"]["pumps"]["drain"]["mlPerS"] = 18.0  # hand edit
    integration._awc_preserve_runtime(stored, incoming)
    pumps = incoming["automaticWaterChange"]["pumps"]
    assert pumps["fill"]["mlPerS"] == 21.5                # newer calibration wins
    assert pumps["drain"]["mlPerS"] == 18.0               # equal stamps: edit stands


# ----------------------------------------------------------------------- NPS

def _nps_stored():
    return {
        "nps": {
            "enabled": True,
            "feedExchange": {"enabled": True, "channelId": "brine",
                             "state": {"owedMl": 400.0, "drainStartedAt": _iso(EARLIER)}},
            "truce": {"enabled": True,
                      "state": {"skimmer": {"restoreAt": _iso(NOW),
                                            "turnedOff": ["switch.skimmer"]}}},
            "hatchery": {
                "enabled": True, "eggType": "standard", "hatchHours": 24,
                "vessels": {"v1": {"name": "Hatchery 1", "volumeL": 1.0,
                                   "state": {"hatchStartedAt": _iso(EARLIER),
                                             "eggType": "standard", "hatchHours": 24,
                                             "readyNotifiedAt": ""}}},
                "reservoir": {"volumeMl": 500.0, "remainingMl": 120.0,
                              "mixedAt": _iso(EARLIER), "lastLoadEnriched": True,
                              "enrichedAt": _iso(EARLIER),
                              "refrigeratedAt": _iso(EARLIER), "fridgeSavedH": 3.5},
                "enrichment": {"hours": 12, "state": {"startedAt": _iso(EARLIER)}},
                "history": [{"vesselId": "v1", "startedAt": _iso(EARLIER - timedelta(days=1)),
                             "harvestedAt": _iso(EARLIER)}],
            },
        },
        "consumables": {"products": {
            "selcon": {"name": "Selcon", "bottleMl": 250.0, "remainingMl": 180.0,
                       "history": [{"at": _iso(EARLIER), "ml": 2.0, "kind": "dose"}]},
        }},
    }


def test_nps_runtime_survives_a_stale_save():
    stored = _nps_stored()
    incoming = copy.deepcopy(stored)
    nps = incoming["nps"]
    nps["feedExchange"]["state"] = {"owedMl": 0.0}
    nps["truce"]["state"] = {}
    nps["hatchery"]["vessels"]["v1"]["state"] = {"hatchStartedAt": ""}
    nps["hatchery"]["vessels"]["v1"]["name"] = "Left rack"   # the client's edit
    nps["hatchery"]["reservoir"]["remainingMl"] = 500.0
    nps["hatchery"]["reservoir"]["volumeMl"] = 700.0         # the client's edit
    nps["hatchery"]["reservoir"]["refrigeratedAt"] = ""      # stale snapshot: fridged since
    nps["hatchery"]["reservoir"]["fridgeSavedH"] = 0
    nps["hatchery"]["enrichment"]["state"] = {"startedAt": ""}
    nps["hatchery"]["history"] = []
    integration._nps_preserve_runtime(stored, incoming)
    assert nps["feedExchange"]["state"]["owedMl"] == 400.0
    assert nps["truce"]["state"]["skimmer"]["turnedOff"] == ["switch.skimmer"]
    assert nps["hatchery"]["vessels"]["v1"]["state"]["hatchStartedAt"] == _iso(EARLIER)
    assert nps["hatchery"]["vessels"]["v1"]["name"] == "Left rack"
    assert nps["hatchery"]["reservoir"]["remainingMl"] == 120.0
    assert nps["hatchery"]["reservoir"]["volumeMl"] == 700.0
    assert nps["hatchery"]["reservoir"]["refrigeratedAt"] == _iso(EARLIER), \
        "the per-batch fridge stamp is server-owned runtime (0.7.115)"
    assert nps["hatchery"]["reservoir"]["fridgeSavedH"] == 3.5
    assert nps["hatchery"]["enrichment"]["state"]["startedAt"] == _iso(EARLIER)
    assert nps["hatchery"]["history"]


def test_consumable_bottle_follows_the_newer_history():
    stored = _nps_stored()
    stored["consumables"]["products"]["selcon"]["remainingMl"] = 150.0
    stored["consumables"]["products"]["selcon"]["history"].insert(
        0, {"at": _iso(NOW), "ml": 2.0, "kind": "dose"})   # dosed after the snapshot
    incoming = copy.deepcopy(_nps_stored())
    integration._nps_preserve_runtime(stored, incoming)
    product = incoming["consumables"]["products"]["selcon"]
    assert product["remainingMl"] == 150.0 and len(product["history"]) == 2

    # No newer server entry -> the client's refill/correction stands.
    stored2 = _nps_stored()
    incoming2 = copy.deepcopy(stored2)
    incoming2["consumables"]["products"]["selcon"]["remainingMl"] = 250.0
    integration._nps_preserve_runtime(stored2, incoming2)
    assert incoming2["consumables"]["products"]["selcon"]["remainingMl"] == 250.0


# ------------------------------------------------------------------- activity

def test_activity_union_restores_missed_entries():
    stored = {"activity": [
        {"timestamp": _iso(NOW), "message": "AWC finished", "type": "control"},
        {"timestamp": _iso(EARLIER), "message": "Heartbeat OK", "type": "info"},
    ]}
    incoming = {"activity": [
        {"timestamp": _iso(NOW + timedelta(minutes=1)), "message": "Panel action", "type": "control"},
        {"timestamp": _iso(EARLIER), "message": "Heartbeat OK", "type": "info"},
    ]}
    integration._merge_activity(stored, incoming)
    messages = [item["message"] for item in incoming["activity"]]
    assert messages == ["Panel action", "AWC finished", "Heartbeat OK"]


def test_activity_clear_is_respected():
    stored = {"activity": [{"timestamp": _iso(NOW), "message": "old", "type": "info"}]}
    incoming = {"activity": []}
    integration._merge_activity(stored, incoming)
    assert incoming["activity"] == []


if __name__ == "__main__":
    failures = 0
    for name, fn in sorted(globals().items()):
        if name.startswith("test_") and callable(fn):
            try:
                fn()
                print(f"  ok  {name}")
            except AssertionError as err:
                failures += 1
                print(f"FAIL  {name}: {err}")
    raise SystemExit(1 if failures else 0)
