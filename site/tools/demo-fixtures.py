#!/usr/bin/env python3
"""Generate demo-tank fixtures for the marketing site's live demo (/demo/).

Runs the REAL backend WS handlers (websocket_get_config & friends) inside the
tests/ fake-HA harness against a seeded showroom tank, and dumps their exact
response payloads as JSON for the browser-side hass shim to replay. No Home
Assistant install needed, and no hand-authored payload shapes — whatever the
backend serialises today is what the demo serves.

Timestamps are emitted relative to generation time; the browser shim rebases
every ISO timestamp by (viewer now − generatedAt) so "yesterday's water change"
stays yesterday forever.

Regenerate after integration changes:
    python3 site/tools/demo-fixtures.py
Output: site/public/demo/fixtures.json
"""

from __future__ import annotations

import asyncio
import json
import os
import random
import shutil
import sys
from datetime import datetime, timedelta, timezone

_HERE = os.path.dirname(os.path.abspath(__file__))
_ROOT = os.path.dirname(os.path.dirname(_HERE))

sys.path.insert(0, os.path.join(_ROOT, "tests"))
import _ha_stubs  # noqa: E402

_ha_stubs.install()

sys.path.insert(0, os.path.join(_ROOT, "custom_components"))
import openreef as integration  # noqa: E402

from _fake_ha import FakeConnection, FakeEntry, FakeHass, FakeState, run  # noqa: E402

CONF_SETTINGS = integration.CONF_SETTINGS
NOW = datetime.now(timezone.utc).replace(microsecond=0)
rng = random.Random(52)  # deterministic fixtures → reviewable diffs


def iso(dt: datetime) -> str:
    return dt.isoformat().replace("+00:00", "Z")


def days_ago(days: float, hour: int | None = None) -> datetime:
    dt = NOW - timedelta(days=days)
    if hour is not None:
        dt = dt.replace(hour=hour, minute=rng.randrange(0, 55), second=0)
    return dt


_WEEKDAYS = ("Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun")


def _next_weekday_at(days: tuple[str, ...], hour: int) -> datetime:
    """The next upcoming occurrence of any of ``days`` at ``hour`` local-UTC."""
    for ahead in range(0, 8):
        candidate = (NOW + timedelta(days=ahead)).replace(hour=hour, minute=0, second=0)
        if _WEEKDAYS[candidate.weekday()] in days and candidate > NOW:
            return candidate
    return NOW + timedelta(days=1)


# --------------------------------------------------------------------------- #
# Seed: a believable, story-rich 250 L mixed reef.
# Story beats the demo leans on: alk consumption creeping up (the advisor has
# something to say), nitrate drifting high (one amber sensor), a skimmer clean
# slightly overdue, a heater-stuck alert RESOLVED three nights ago (the
# scripted "2 AM save" opener replays it), yesterday's water change logged.
# --------------------------------------------------------------------------- #

def _readings(param: str, days: int, start: float, end: float, jitter: float,
              unit: str, every_days: float = 1.0) -> list[dict]:
    rows = []
    n = int(days / every_days)
    for i in range(n):
        t = days - i * every_days
        frac = 1 - t / days
        value = start + (end - start) * frac + rng.uniform(-jitter, jitter)
        rows.append({
            "id": f"demo:{param}:{i}",
            "timestamp": iso(days_ago(t, hour=19)),
            "value": round(value, 2),
            "unit": unit,
            "source": "manual",
            "notes": "",
        })
    return rows


def seed_config() -> dict:
    sensors = {
        "temp": "sensor.showroom_tank_temp",
        "ph": "sensor.showroom_ph",
        "salinity": "sensor.showroom_salinity",
        "orp": "sensor.showroom_orp",
        "sump_temp": "sensor.showroom_sump_temp",
        "leak": "binary_sensor.showroom_leak",
    }
    config = {
        "tank": {
            "name": "The Showroom Reef",
            "owner": "OpenReef",
            "volumeLitres": 250,
        },
        "display": {"setupComplete": True},
        "watchdog": {"enabled": True, "lastHeartbeat": iso(NOW - timedelta(hours=2))},
        "sensors": {
            sid: {"entity_id": eid, "enabled": True} for sid, eid in sensors.items()
        },
        "equipment": {
            "return_pump": {"type": "return_pump", "label": "Return pump",
                            "armed": True, "switch_entity_id": "switch.showroom_return"},
            "heater": {"type": "heater", "label": "Heater",
                       "armed": True, "switch_entity_id": "switch.showroom_heater"},
            "skimmer": {"type": "skimmer", "label": "Skimmer",
                        "armed": True, "switch_entity_id": "switch.showroom_skimmer"},
            "ato": {"type": "ato", "label": "ATO",
                    "armed": True, "switch_entity_id": "switch.showroom_ato"},
            "wavemaker": {"type": "display_wavemaker", "label": "Wavemaker left",
                          "armed": True, "switch_entity_id": "switch.showroom_wave"},
            "wavemaker2": {"type": "display_wavemaker", "label": "Wavemaker right",
                           "armed": True, "switch_entity_id": "switch.showroom_wave2"},
            "frag_light": {"type": "light", "label": "Frag light",
                           "armed": False, "switch_entity_id": "switch.showroom_frag"},
        },
        # The living tank diagram + Reef Layer. Slot placement is deliberately
        # left to the panel's zone-honouring auto-layout (SPS on the crest,
        # LPS mid-rock, softies low, gorgonian at the back, colours spaced) —
        # the demo shows the product's own placement logic, not a hand-set one.
        "diagram": {
            "systemType": "sump",
            "scape": "twinpeaks",
            "allowControls": True,
            "showAlerts": True,
            "showReadings": True,
            "layout": {},
        },
        "livestock": {
            "corals": {
                "staghorn1": {"name": "Ragnar's staghorn", "species": "staghorn", "colour": "purple",
                              "addedAt": iso(days_ago(410)), "notes": "First SPS in the tank — from a 2 cm frag."},
                "birdsnest1": {"name": "Pink birdsnest", "species": "birdsnest", "colour": "pink",
                               "addedAt": iso(days_ago(300)), "notes": ""},
                "digitata1": {"name": "Forest fire digitata", "species": "digitata", "colour": "orange",
                              "addedAt": iso(days_ago(240)), "notes": ""},
                "table1": {"name": "Green table acro", "species": "table", "colour": "green",
                           "addedAt": iso(days_ago(180)), "notes": ""},
                "torch1": {"name": "Dragon soul torch", "species": "torch", "colour": "gold",
                           "addedAt": iso(days_ago(260)), "notes": "The expensive one."},
                "hammer1": {"name": "Hammer garden", "species": "hammer", "colour": "green",
                            "addedAt": iso(days_ago(330)), "notes": ""},
                "duncan1": {"name": "Duncan colony", "species": "duncan", "colour": "teal",
                            "addedAt": iso(days_ago(150)), "notes": ""},
                "brain1": {"name": "Warpaint scoly", "species": "scoly", "colour": "red",
                           "addedAt": iso(days_ago(120)), "notes": ""},
                "zoa1": {"name": "Utter chaos zoas", "species": "zoa", "colour": "orange",
                         "addedAt": iso(days_ago(370)), "notes": "Started as five polyps."},
                "mushroom1": {"name": "Bounce mushroom", "species": "mushroom", "colour": "red",
                              "addedAt": iso(days_ago(90)), "notes": ""},
                "xenia1": {"name": "Pulsing xenia", "species": "xenia", "colour": "pink",
                           "addedAt": iso(days_ago(430)), "notes": "It was free. It is everywhere."},
                "gorgonian1": {"name": "Purple sea fan", "species": "gorgonian", "colour": "purple",
                               "addedAt": iso(days_ago(200)), "notes": ""},
            },
        },
        # The advisor needs a chosen product before it advises; All-For-Reef is
        # the classic single-solution choice for a demo tank.
        "dosing": {
            "enabled": True,
            "system": {
                "primaryProduct": "tropic_marin_all_for_reef",
                "sharedDailyDoseMl": 45,
                "safetyAcknowledged": True,
            },
            # Dosing Pumps v2: two HA-timed peristaltics on smart plugs (the
            # showroom has no OpenReef firmware node, so no kalk stepper —
            # honest). All-For-Reef carries the chemistry; the phyto pump is
            # the NPS bridge, debiting the shelf bottle it draws from.
            "channels": {
                "afr": {
                    "name": "All-For-Reef", "chemical": "alk", "enabled": True,
                    "driver": {"type": "ha_switch_timed",
                               "entities": {"powerSwitch": "switch.showroom_dose_afr"}},
                    "schedule": {"enabled": True, "mlPerDay": 45, "mode": "doses", "dosesPerDay": 12,
                                 "windowStart": "00:00", "windowEnd": "00:00",
                                 "night": {"enabled": False}},
                    "guards": {"maxPerDoseMl": 10, "suspendDuringAwc": True},
                    "calibration": {"mlPerS": 1.2, "spinUpMl": 0.1, "calibratedAt": iso(days_ago(12))},
                    "reservoir": {"volumeMl": 2000, "remainingMl": 1350, "lowThresholdMl": 200,
                                  "shelfLifeDays": 0},
                    "state": {}, "wear": {},
                },
                "phyto": {
                    "name": "Phyto pump", "chemical": "food", "enabled": True,
                    "productId": "phyto",
                    "driver": {"type": "ha_switch_timed",
                               "entities": {"powerSwitch": "switch.showroom_dose_phyto"}},
                    "schedule": {"enabled": True, "mlPerDay": 30, "mode": "doses", "dosesPerDay": 3,
                                 "windowStart": "09:00", "windowEnd": "21:00",
                                 "night": {"enabled": False}},
                    "guards": {"maxPerDoseMl": 15},
                    "calibration": {"mlPerS": 1.0, "spinUpMl": 0.0, "calibratedAt": iso(days_ago(9))},
                    "reservoir": {"volumeMl": 1000, "remainingMl": 620, "lowThresholdMl": 100,
                                  "shelfLifeDays": 28, "productId": "phyto"},
                    "state": {}, "wear": {},
                },
            },
        },
        # The NPS system: the food shelf, the brine hatchery (its clock is
        # started through the REAL handler in main() and then backdated so a
        # visitor lands mid-hatch), and the live cultures rig.
        "consumables": {
            "products": {
                "phyto": {
                    "name": "Live phytoplankton", "brand": "Reef Phyto", "category": "phyto",
                    "bottleMl": 1000.0, "remainingMl": 620.0, "lowThresholdMl": 150.0,
                    "openedAt": iso(days_ago(6)), "shelfLifeDaysOpened": 28.0,
                    "refrigerated": True, "stirDaily": True,
                    "particleUmMin": 2.0, "particleUmMax": 12.0,
                    "notes": "Feeds the phyto pump and the rotifer jar.", "createdAt": iso(days_ago(6)),
                    "history": [],
                },
                "powder": {
                    "name": "Coral powder blend", "brand": "", "category": "blend",
                    "bottleMl": 120.0, "remainingMl": 74.0, "lowThresholdMl": 20.0,
                    "openedAt": iso(days_ago(40)), "shelfLifeDaysOpened": 180.0,
                    "refrigerated": False, "stirDaily": False,
                    "particleUmMin": 50.0, "particleUmMax": 400.0,
                    "doseMl": 2.0, "doseEveryDays": 1, "lastDosedAt": iso(days_ago(1, hour=20)),
                    "notes": "Hand-fed after lights out — the sun corals open for it.",
                    "createdAt": iso(days_ago(40)), "history": [],
                },
                "amino": {
                    "name": "Amino acids", "brand": "", "category": "amino",
                    "bottleMl": 250.0, "remainingMl": 45.0, "lowThresholdMl": 50.0,
                    "openedAt": iso(days_ago(70)), "shelfLifeDaysOpened": 365.0,
                    "refrigerated": False, "stirDaily": False,
                    "particleUmMin": 0.0, "particleUmMax": 0.0,
                    "doseMl": 5.0, "doseEveryDays": 2, "lastDosedAt": iso(days_ago(2, hour=21)),
                    "notes": "", "createdAt": iso(days_ago(70)), "history": [],
                },
            },
        },
        "nps": {
            "enabled": True,
            "hatchery": {
                "enabled": True,
                "eggType": "premium",
                "hatchHours": 24,
                "tempEntity": "sensor.showroom_room_temp",
                "cysts": {"openedAt": iso(days_ago(10))},
                # The live-brine container the hatch drains into, and the
                # fridge bottle mixed this morning (brine keeps ~24 h in the
                # fridge, so "yesterday" would already read as spent).
                "reservoir": {"volumeMl": 500, "remainingMl": 0},
                "fridgeBottle": {"volumeMl": 250, "remainingMl": 180, "mixedAt": iso(NOW - timedelta(hours=6))},
                "handFeed": {"feedsPerDay": 2, "defaultDoseMl": 30, "windowStart": "11:00", "windowEnd": "21:00"},
                "handFeeds": [
                    {"at": iso(days_ago(1, hour=18)), "from": "bottle", "ml": 20},
                    {"at": iso(days_ago(2, hour=18)), "from": "bottle", "ml": 20},
                ],
            },
            "cultures": {
                "enabled": True,
                "tempEntity": "sensor.showroom_room_temp",
                "jars": {
                    "a": {"name": "Rotifers A", "species": "rotifer_L", "volumeL": 4.0, "salinityPpt": 27,
                          "feed": {"productId": "phyto", "doseMl": 20}, "cadence": {},
                          "state": {"startedAt": iso(days_ago(6, hour=19)),
                                    "lastRestartAt": iso(days_ago(6, hour=19)),
                                    "lastFedAt": iso(days_ago(0.4)),
                                    "lastHarvestAt": iso(days_ago(1, hour=8)),
                                    "lastSign": "cloudy", "lastSignAt": iso(days_ago(0.4)),
                                    "lastTint": "tan"},
                          "history": []},
                    "b": {"name": "Tigriopus B", "species": "tigriopus", "volumeL": 4.0, "salinityPpt": 35,
                          "feed": {"productId": "phyto", "doseMl": 10}, "cadence": {},
                          "state": {"startedAt": iso(days_ago(20, hour=19)),
                                    "lastRestartAt": iso(days_ago(20, hour=19)),
                                    "lastFedAt": iso(days_ago(2, hour=19)),
                                    "lastHarvestAt": iso(days_ago(5, hour=9))},
                          "history": []},
                },
                "bottle": {"volumeMl": 1000, "remainingMl": 600, "filledAt": iso(days_ago(1, hour=8)), "doseMl": 20},
            },
        },
        # The saltwater mixing station: two 50 L vessels, NYOS at 35 ppt, a
        # tested batch sitting in storage (so the AWC sees a ready batch), and
        # a salt bucket that is getting low enough to mention.
        "mixingStation": {
            "enabled": True,
            "layout": "dual",
            "vessels": {
                "rodi": {"volumeLitres": 50, "estimatedLitres": 38, "levelSensorEntity": ""},
                "mix": {"volumeLitres": 50, "estimatedLitres": 45, "contents": "salt", "levelSensorEntity": ""},
            },
            "salt": {"brand": "nyos_pure", "targetPpt": 35.0, "mixHours": 0, "customGPerL": 0},
            "heat": {"enabled": True, "targetC": 25.0, "tempSensorEntity": ""},
            "storage": {"circulateEveryH": 6, "circulateForMin": 10, "retestAfterDays": 7},
            "switches": {
                "rodiBooster": {"switchEntity": "switch.showroom_mix_booster"},
                "mixPumpA": {"switchEntity": "switch.showroom_mix_pump_a"},
                "mixPumpB": {"switchEntity": "switch.showroom_mix_pump_b"},
                "heater": {"switchEntity": "switch.showroom_mix_heater"},
            },
            "rodi": {
                "rateLph": 6, "fillCapMin": 240,
                # Filter stages each earn their own litres clock; the DI is
                # the one getting close, as it always is.
                "filters": [
                    {"id": "sed", "label": "Sediment 5 µm", "type": "sediment", "ratedLitres": 6000,
                     "litresProcessed": 2100, "changedAt": iso(days_ago(95))},
                    {"id": "carbon", "label": "Carbon block", "type": "carbon", "ratedLitres": 6000,
                     "litresProcessed": 2100, "changedAt": iso(days_ago(95))},
                    {"id": "membrane", "label": "RO membrane 75 GPD", "type": "membrane", "ratedLitres": 30000,
                     "litresProcessed": 9400, "changedAt": iso(days_ago(400))},
                    {"id": "di", "label": "DI resin", "type": "di", "ratedLitres": 2000,
                     "litresProcessed": 1750, "changedAt": iso(days_ago(80))},
                ],
            },
            "saltStock": {"kg": 3.1, "bucketKg": 10, "updatedAt": iso(days_ago(3)), "history": []},
            "batch": {"state": "storing", "type": "salt",
                      "startedAt": iso(days_ago(3, hour=10)), "stageAt": iso(days_ago(2, hour=12)),
                      "litres": 45, "loggedPpt": 35.1, "testedAt": iso(days_ago(2, hour=12)),
                      "usedLitres": 0},
        },
        # Cooling headroom: room sensors, a weather entity with an hourly
        # forecast (served by the fake HA in main()), the dehumidifier on a
        # plug in auto, and the intake fan in front of the window.
        "coolingHeadroom": {
            "enabled": True,
            "roomTempEntity": "sensor.showroom_room_temp",
            "humidityEntity": "sensor.showroom_room_rh",
            "waterTempEntity": "",
            "targetTempC": 25.5,
            "weatherEntity": "weather.showroom",
            "lookaheadHours": 24,
            "dehumidifier": {"mode": "auto", "armed": True, "switchEntity": "switch.showroom_dehum",
                             "leadHours": 3, "minOnMinutes": 20, "minOffMinutes": 10, "maxRunHours": 8},
            "vent": {"mode": "auto", "armed": True, "switchEntity": "switch.showroom_intake_fan",
                     "windowEntity": "binary_sensor.showroom_window"},
        },
        "manualReadings": {
            # Alk consumption creeping up — decline steepens over the month.
            "alkalinity": _readings("alk", 30, 8.6, 8.0, 0.06, "dKH"),
            "calcium": _readings("ca", 30, 428, 415, 3, "ppm", every_days=2),
            "magnesium": _readings("mg", 30, 1360, 1335, 8, "ppm", every_days=3),
            "nitrate": _readings("no3", 28, 4.0, 12.0, 0.8, "ppm", every_days=3.5),
            "phosphate": _readings("po4", 28, 0.03, 0.08, 0.008, "ppm", every_days=3.5),
        },
        # The "2 AM save" the scripted opener replays: heater stuck three
        # nights ago, caught, outlet cut, resolved 26 minutes later.
        "alerts": {
            "history": [
                {"timestamp": iso(days_ago(0.6)), "sensor_id": "ph", "label": "pH Level",
                 "state": "ok", "title": "pH back in range",
                 "message": "pH recovered to 8.12 after the evening CO2 dip."},
                {"timestamp": iso(days_ago(0.7)), "sensor_id": "ph", "label": "pH Level",
                 "state": "warning", "title": "pH low warning",
                 "message": "pH read 7.94, inside the warning buffer below minimum 7.8."},
                {"timestamp": iso(days_ago(3.1)), "sensor_id": "temp", "label": "Display Tank Temperature",
                 "state": "ok", "title": "Temperature back in range",
                 "message": "Tank temperature recovered to 26.4 °C after the heater outlet was switched off."},
                {"timestamp": iso(days_ago(3.12)), "sensor_id": "temp", "label": "Display Tank Temperature",
                 "state": "critical", "title": "Temperature critical",
                 "message": "Tank temperature read 27.9 °C (max 27.5 °C) with the heater still ON. Critical alert pushed to phone."},
            ],
        },
        "activity": [
            {"timestamp": iso(NOW - timedelta(minutes=41)), "message": "Reef health recalculated — alkalinity trending down over 30 days", "type": "info"},
            {"timestamp": iso(days_ago(1, hour=9)), "message": "Automatic water change completed: 25.0 L drained, 25.0 L filled (batch sequential)", "type": "success"},
            {"timestamp": iso(days_ago(1, hour=9)), "message": "ATO suspended for 15 min after water change (stabilisation holdoff)", "type": "info"},
            {"timestamp": iso(days_ago(2, hour=18)), "message": "Feed mode: skimmer paused 10 min, wavemaker to 30 %", "type": "info"},
            {"timestamp": iso(days_ago(6, hour=20)), "message": "Reef Layer: Bounce mushroom registered — placed low on the rock", "type": "info"},
            {"timestamp": iso(days_ago(3.1)), "message": "Heater outlet switched off from phone (armed switch): temperature exceeded 27.5 °C with heater ON", "type": "warning"},
            {"timestamp": iso(days_ago(5, hour=11)), "message": "ICP report imported (Triton) — drift check passed on Ca/Mg, alk kit reads 0.3 dKH high", "type": "info"},
        ],
        "maintenance": {
            "seeded": True,
            "enabled": True,
            "tasks": {
                "water_change": {"label": "Water change", "cadenceDays": 7, "enabled": True},
                "filter_sock": {"label": "Swap filter socks", "cadenceDays": 5, "enabled": True},
                "skimmer_clean": {"label": "Clean skimmer cup", "cadenceDays": 14, "enabled": True},
                "glass_clean": {"label": "Clean glass", "cadenceDays": 3, "enabled": True},
            },
            "completions": {
                "water_change": [
                    {"id": "demo:wc:1", "timestamp": iso(days_ago(1, hour=9)), "notes": "",
                     "volume": 25.0, "volumeUnit": "L", "source": "awc"},
                    {"id": "demo:wc:2", "timestamp": iso(days_ago(8, hour=9)), "notes": "",
                     "volume": 25.0, "volumeUnit": "L", "source": "awc"},
                    {"id": "demo:wc:3", "timestamp": iso(days_ago(15, hour=10)), "notes": "manual bucket day",
                     "volume": 30.0, "volumeUnit": "L"},
                ],
                "filter_sock": [
                    {"id": "demo:fs:1", "timestamp": iso(days_ago(3, hour=19)), "notes": ""},
                ],
                # Skimmer clean last done 15 days ago on a 14-day cadence —
                # one day overdue, so Mission Control has something to nag about.
                "skimmer_clean": [
                    {"id": "demo:sk:1", "timestamp": iso(days_ago(15, hour=19)), "notes": ""},
                ],
                "glass_clean": [
                    {"id": "demo:gc:1", "timestamp": iso(days_ago(2, hour=19)), "notes": ""},
                ],
            },
        },
        "automaticWaterChange": {
            "enabled": True,
            "pumps": {
                "drain": {"switchEntity": "switch.showroom_awc_drain", "mlPerS": 55.0},
                "fill": {"switchEntity": "switch.showroom_awc_fill", "mlPerS": 52.5},
            },
            "reservoirs": {
                "fresh": {"capacityLitres": 60, "remainingMl": 34000,
                          "emptyEntity": "binary_sensor.showroom_fresh_empty"},
                "waste": {"capacityLitres": 60, "filledMl": 25500,
                          "fullEntity": "binary_sensor.showroom_waste_full"},
            },
            "safety": {
                "highLevelEntity": "binary_sensor.showroom_high",
                "leakEntity": "binary_sensor.showroom_leak",
                "maxSingleChangePercent": 25,
            },
            "guards": {"quietHoursEnabled": True, "quietStart": "22:00", "quietEnd": "08:00",
                       "blockDuringFeed": True, "blockOnReturnPumpIssue": True},
            "ato": {"suspendDuringChange": True, "stabilizationHoldoffMinutes": 15},
            # 50 L/week over Mon+Thu = 25 L per change (10 % of the tank each run).
            "schedule": {"method": "batch_sequential", "enabled": True,
                         "days": ["Mon", "Thu"], "times": ["09:00"],
                         "amount": 50, "amountUnit": "litres", "period": "week"},
            "state": {"status": "idle",
                      "lastRun": iso(days_ago(1, hour=9)),
                      "nextRun": iso(_next_weekday_at(("Mon", "Thu"), 9))},
            "history": [
                {"completedAt": iso(days_ago(1, hour=9)), "drainedL": 25.0, "filledL": 24.9,
                 "method": "batch_sequential", "partial": False, "notes": "", "source": "sched"},
                {"completedAt": iso(days_ago(4, hour=9)), "drainedL": 25.0, "filledL": 25.1,
                 "method": "batch_sequential", "partial": False, "notes": "", "source": "sched"},
                {"completedAt": iso(days_ago(8, hour=9)), "drainedL": 25.0, "filledL": 24.8,
                 "method": "batch_sequential", "partial": False, "notes": "", "source": "sched"},
            ],
        },
    }
    return config


def seed_states() -> dict:
    def st(state, attrs):
        return {"state": state, "attributes": attrs,
                "last_changed": iso(NOW - timedelta(minutes=2)),
                "last_updated": iso(NOW - timedelta(minutes=2))}

    return {
        "sensor.showroom_tank_temp": st("25.9", {"unit_of_measurement": "°C", "friendly_name": "Tank temp", "device_class": "temperature"}),
        "sensor.showroom_ph": st("8.16", {"unit_of_measurement": "", "friendly_name": "pH"}),
        "sensor.showroom_salinity": st("35.1", {"unit_of_measurement": "ppt", "friendly_name": "Salinity"}),
        "sensor.showroom_orp": st("382", {"unit_of_measurement": "mV", "friendly_name": "ORP"}),
        "sensor.showroom_sump_temp": st("25.7", {"unit_of_measurement": "°C", "friendly_name": "Sump temp", "device_class": "temperature"}),
        "binary_sensor.showroom_leak": st("off", {"friendly_name": "Leak sensor", "device_class": "moisture"}),
        "switch.showroom_return": st("on", {"friendly_name": "Return pump"}),
        "switch.showroom_heater": st("on", {"friendly_name": "Heater"}),
        "switch.showroom_skimmer": st("on", {"friendly_name": "Skimmer"}),
        "switch.showroom_ato": st("on", {"friendly_name": "ATO"}),
        "switch.showroom_wave": st("on", {"friendly_name": "Wavemaker left"}),
        "switch.showroom_wave2": st("on", {"friendly_name": "Wavemaker right"}),
        "switch.showroom_frag": st("off", {"friendly_name": "Frag light"}),
        "switch.showroom_awc_drain": st("off", {"friendly_name": "AWC drain pump"}),
        "switch.showroom_awc_fill": st("off", {"friendly_name": "AWC fill pump"}),
        "binary_sensor.showroom_fresh_empty": st("off", {"friendly_name": "Fresh reservoir empty", "device_class": "problem"}),
        "binary_sensor.showroom_waste_full": st("off", {"friendly_name": "Waste reservoir full", "device_class": "problem"}),
        "binary_sensor.showroom_high": st("off", {"friendly_name": "Display high level", "device_class": "problem"}),
        # Room + weather for cooling headroom, the hatchery and the cultures.
        "sensor.showroom_room_temp": st("27.6", {"unit_of_measurement": "°C", "friendly_name": "Tank room temp", "device_class": "temperature"}),
        "sensor.showroom_room_rh": st("64", {"unit_of_measurement": "%", "friendly_name": "Tank room humidity", "device_class": "humidity"}),
        "weather.showroom": {"state": "cloudy", "attributes": {"temperature": 22.0, "humidity": 70, "temperature_unit": "°C", "friendly_name": "Showroom weather"},
                             "last_changed": iso(NOW - timedelta(minutes=2)), "last_updated": iso(NOW - timedelta(minutes=2))},
        "switch.showroom_dehum": st("off", {"friendly_name": "Dehumidifier"}),
        "switch.showroom_intake_fan": st("on", {"friendly_name": "Intake fan"}),
        "binary_sensor.showroom_window": st("on", {"friendly_name": "Fish-room window", "device_class": "opening"}),
        # Dosing pumps and the mixing station's plugs.
        "switch.showroom_dose_afr": st("off", {"friendly_name": "AFR dosing pump"}),
        "switch.showroom_dose_phyto": st("off", {"friendly_name": "Phyto dosing pump"}),
        "switch.showroom_mix_booster": st("off", {"friendly_name": "RODI booster pump"}),
        "switch.showroom_mix_pump_a": st("off", {"friendly_name": "Mix pump A"}),
        "switch.showroom_mix_pump_b": st("off", {"friendly_name": "Mix pump B"}),
        "switch.showroom_mix_heater": st("off", {"friendly_name": "Mix vessel heater"}),
    }


def _triton_report() -> dict:
    """A client-parsed Triton-style report, fed through the REAL import handler
    so normalisation, flags and core fan-out are authentic."""
    sample = days_ago(12, hour=10)
    return {
        "id": "demo:icp:triton:1",
        "lab": "Triton",
        "adapter": "triton_csv",
        "method": "ICP-OES",
        "sampleType": "tank",
        "sampleDate": iso(sample),
        "testId": "TR-260722",
        "source": {"fileName": "showroom-triton.csv"},
        "elements": [
            {"symbol": "Ca", "rawValue": 419, "rawUnit": "mg/L"},
            {"symbol": "Mg", "rawValue": 1342, "rawUnit": "mg/L"},
            {"symbol": "KH", "rawValue": 8.1, "rawUnit": "dKH"},
            {"symbol": "NO3", "rawValue": 9.8, "rawUnit": "mg/L"},
            {"symbol": "PO4", "rawValue": 0.06, "rawUnit": "mg/L"},
            {"symbol": "K", "rawValue": 402, "rawUnit": "mg/L"},
            {"symbol": "Sr", "rawValue": 7.9, "rawUnit": "mg/L"},
            {"symbol": "B", "rawValue": 4.6, "rawUnit": "mg/L"},
            {"symbol": "I", "rawValue": 0.041, "rawUnit": "mg/L"},
            {"symbol": "Si", "rawValue": 0.09, "rawUnit": "mg/L"},
            {"symbol": "Cu", "rawValue": "<0.5", "rawUnit": "µg/L"},
            {"symbol": "Zn", "rawValue": 2.1, "rawUnit": "µg/L"},
            {"symbol": "Sal", "rawValue": 35.0, "rawUnit": "ppt"},
        ],
    }


def _forecast() -> list[dict]:
    """24 hourly entries from now: a warm, humid afternoon ahead (peaks ~+8 h),
    cooling into a damp night — enough for the cooling projection to have an
    opinion about the dehumidifier and the intake fan."""
    import math
    items = []
    for i in range(24):
        at = NOW + timedelta(hours=i)
        peak = math.exp(-((i - 8) / 4.5) ** 2)
        temp = round(19.5 + 9.5 * peak, 1)
        rh = round(82 - 30 * peak, 0)
        items.append({"datetime": at.isoformat(), "temperature": temp, "humidity": rh})
    return items


def _backdate(node, key: str, value: str) -> int:
    """Set every ``key`` that already carries a value, anywhere in a nested
    config, to ``value``. Used to shift real-handler stamps into the past."""
    hits = 0
    if isinstance(node, dict):
        for k, v in node.items():
            if k == key and v:
                node[k] = value
                hits += 1
            else:
                hits += _backdate(v, key, value)
    elif isinstance(node, list):
        for v in node:
            hits += _backdate(v, key, value)
    return hits


# --------------------------------------------------------------------------- #
# Run the real handlers, capture their send_result payloads.
# --------------------------------------------------------------------------- #

def main() -> int:
    config = seed_config()
    states = seed_states()
    entry = FakeEntry(options={CONF_SETTINGS: config}, entry_id="demo_entry")
    hass = FakeHass(entries=[entry])
    for eid, s in states.items():
        # Fresh last_changed, or the trust check flags every sensor as stale.
        hass.states.set(eid, FakeState(s["state"], s["attributes"], last_changed=NOW))

    # Feed one ICP report through the REAL import handler so icpReports,
    # flags and the manualReadings fan-out are exactly what production writes.
    icp_conn = FakeConnection()
    run(integration.websocket_import_icp_report(
        hass, icp_conn, {"id": 1, "type": "openreef/import_icp_report", "report": _triton_report()}))
    if icp_conn.error_codes:
        print(f"WARNING: ICP seed import failed: {icp_conn.error_codes}")

    # Cooling headroom Layer 2 reads the weather entity's hourly forecast via
    # weather.get_forecasts — the fake HA answers with a warm, humid day
    # ahead so the projection, dehumidifier plan and vent advice all render.
    hass.services.responses[("weather", "get_forecasts")] = {
        "weather.showroom": {"forecast": _forecast()}
    }

    # Start a brine hatch through the REAL handler so the vessel state is
    # exactly what production writes, then backdate the clock 14 h so the
    # visitor lands mid-hatch (~10 h to go) instead of at zero.
    hatch_conn = FakeConnection()
    try:
        result = integration.websocket_nps_hatch_start(
            hass, hatch_conn, {"id": 2, "type": "openreef/nps_hatch_start"})
        if asyncio.iscoroutine(result):
            run(result)
        if hatch_conn.error_codes:
            print(f"WARNING: hatch start refused: {hatch_conn.error_codes}")
        else:
            _backdate(entry.options[CONF_SETTINGS], "hatchStartedAt", iso(NOW - timedelta(hours=14)))
            # The handler also logged "hatch started" (and the litre it drew
            # from the mix vessel) at NOW — shift those entries back with
            # the clock so the ticker and the countdown tell one story.
            for item in entry.options[CONF_SETTINGS].get("activity") or []:
                text = str(item.get("message", "")).lower()
                if "hatch" in text and item.get("timestamp", "") >= iso(NOW - timedelta(minutes=5)):
                    item["timestamp"] = iso(NOW - timedelta(hours=14))
    except Exception as err:  # noqa: BLE001
        print(f"WARNING: hatch start failed: {type(err).__name__}: {err}")

    # Cooling headroom's projection (forecast parse, dehumidifier plan, vent
    # advice) is built by the 5-minute tick, not by the status read — run one
    # tick the way tests/test_cooling.py does so cooling_status has a plan.
    try:
        run(integration._async_cooling_tick(hass, entry, NOW))
    except Exception as err:  # noqa: BLE001
        print(f"WARNING: cooling tick failed: {type(err).__name__}: {err}")

    handlers = {
        "openreef/get_config": integration.websocket_get_config,
        "openreef/awc_summary": getattr(integration, "websocket_awc_summary", None),
        "openreef/dosing_summary": getattr(integration, "websocket_dosing_summary", None),
        "openreef/icp_dashboard": getattr(integration, "websocket_icp_dashboard", None),
        "openreef/lighting_window": getattr(integration, "websocket_lighting_window", None),
        "openreef/list_reef_presets": getattr(integration, "websocket_list_reef_presets", None),
        "openreef/guardian_status": getattr(integration, "websocket_guardian_status", None),
        "openreef/vision_summary": getattr(integration, "websocket_vision_summary", None),
        # The Helm-era pages: NPS shelf/hatchery, cultures, mixing station,
        # cooling headroom, and the spawning executor.
        "openreef/nps_summary": getattr(integration, "websocket_nps_summary", None),
        "openreef/cultures_summary": getattr(integration, "websocket_cultures_summary", None),
        "openreef/mixing_summary": getattr(integration, "websocket_mixing_summary", None),
        "openreef/cooling_status": getattr(integration, "websocket_cooling_status", None),
        "openreef/spawning_execution_status": getattr(integration, "websocket_spawning_execution_status", None),
    }

    ws: dict[str, object] = {}
    skipped: list[str] = []
    for cmd, handler in handlers.items():
        if handler is None:
            skipped.append(f"{cmd} (no handler)")
            continue
        conn = FakeConnection()
        try:
            result = handler(hass, conn, {"id": 1, "type": cmd})
            if asyncio.iscoroutine(result):  # decorated sync handlers send inline
                run(result)
            if conn.results:
                ws[cmd] = conn.results[-1].payload
            else:
                skipped.append(f"{cmd} (no result: {conn.error_codes or 'nothing sent'})")
        except Exception as err:  # noqa: BLE001 — fixture gen, report and move on
            skipped.append(f"{cmd} ({type(err).__name__}: {err})")

    # Spawning: pre-compile the GBR programme so the demo's "generate" button
    # returns a real compiled window (the shim replays this for any params).
    spawn_conn = FakeConnection()
    try:
        integration.websocket_generate_spawning_program(
            hass, spawn_conn,
            {"id": 1, "type": "openreef/generate_spawning_program",
             "reefPreset": "gbr_central", "year": NOW.year},
        )
        if spawn_conn.results:
            ws["openreef/generate_spawning_program"] = spawn_conn.results[-1].payload
    except Exception as err:  # noqa: BLE001
        skipped.append(f"openreef/generate_spawning_program ({type(err).__name__}: {err})")

    out = {
        "generatedAt": iso(NOW),
        "source": "seeded",  # becomes "recorded" when demo-record runs against a real tank
        "ws": ws,
        "states": states,
    }
    dest = os.path.join(_ROOT, "site", "public", "demo", "fixtures.json")
    os.makedirs(os.path.dirname(dest), exist_ok=True)
    with open(dest, "w", encoding="utf-8") as fh:
        json.dump(out, fh, indent=1, default=str)
    size = os.path.getsize(dest)
    print(f"wrote {dest} ({size/1024:.0f} KB)")
    print(f"captured: {', '.join(ws) or 'NOTHING'}")
    for line in skipped:
        print(f"skipped: {line}")

    # Pin the panel + its avatar art alongside the fixtures, so the demo always
    # runs the exact frontend this fixture set was generated against.
    frontend = os.path.join(_ROOT, "custom_components", "openreef", "frontend")
    panel_dest = os.path.join(_ROOT, "site", "public", "demo", "openreef-panel.js")
    shutil.copyfile(os.path.join(frontend, "openreef-panel.js"), panel_dest)
    print(f"copied panel → {panel_dest} ({os.path.getsize(panel_dest)/1024:.0f} KB)")
    avatar_dest = os.path.join(_ROOT, "site", "public", "openreef_static", "avatar")
    os.makedirs(avatar_dest, exist_ok=True)
    copied = 0
    for name in os.listdir(os.path.join(frontend, "avatar")):
        if name.endswith(".png"):
            shutil.copyfile(os.path.join(frontend, "avatar", name), os.path.join(avatar_dest, name))
            copied += 1
    print(f"copied {copied} avatar PNGs → {avatar_dest}")
    return 0 if "openreef/get_config" in ws else 1


if __name__ == "__main__":
    sys.exit(main())
