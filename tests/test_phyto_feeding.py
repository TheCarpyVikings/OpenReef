"""Home-phyto stock, shared tank doses and culture-readiness regressions.

Run: python3 tests/test_phyto_feeding.py
Uses fake HA only; no live configuration or hardware is accessed.
"""
from __future__ import annotations

import copy
import traceback
from datetime import datetime, timedelta, timezone

import test_cultures as t

nps = t.nps_engine
integration = t.integration
NOW = t.REAL


def _config():
    jars = {
        "backup": {**t._phyto_jar(started_ago_days=21, now=NOW, lastTint="green",
                                 lastHarvestAt=t._iso(NOW - timedelta(days=7))), "name": "Nanno Backup"},
        "main": {**t._phyto_jar(started_ago_days=6.9, now=NOW, lastTint="green"), "name": "Nanno Main"},
    }
    cfg = t._config(t._phyto_entry(jars=jars, products={}, tank_l=52))
    integration._cultures_ensure_home_bottles(cfg)
    cfg["maintenance"]["enabled"] = True
    return cfg


def _stock(cfg, jar="main", ml=500):
    product = cfg["consumables"]["products"][f"home_phyto_{jar}"]
    product.update(remainingMl=ml, openedAt=t._iso(NOW - timedelta(hours=1)))
    return product


def _events(cfg, now=NOW):
    return [e for e in nps.feed_timeline(now, products=cfg["consumables"]["products"], channels={},
                                        cultures=cfg["nps"]["cultures"], tank_l=52)["events"]
            if e["source"].startswith("shelf:home_phyto_")]


def _pending(cfg, now=NOW):
    return [e for e in _events(cfg, now) if e["status"] in ("due", "late", "missed", "planned")]


def test_empty_greening_cultures_have_no_feed_or_maintenance_doses_due():
    cfg = _config()
    backup = cfg["consumables"]["products"]["home_phyto_backup"]
    backup.update(lastDosedAt=t._iso(NOW - timedelta(days=2)), history=[
        {"at": t._iso(NOW - timedelta(days=2)), "ml": 35, "kind": "dose", "to": "tank"}])
    before = copy.deepcopy(cfg)
    shelf = nps.shelf_summary(cfg["consumables"]["products"], NOW, 52)
    integration._cultures_shelf_nudges(cfg, shelf["products"], NOW)
    assert shelf["doseDueCount"] == 0 and not _events(cfg)
    for state in shelf["products"].values():
        assert state["empty"] and not state["handDose"]["clock"]["due"]
        assert "No harvested phyto available" in state["handDose"]["pauseReason"]
        assert "still greening" in state["splitNudge"] and "early split" not in state["splitNudge"]
    assert integration._maintenance_due_items(cfg, NOW) == []
    assert integration._maintenance_upcoming(cfg, NOW) == []
    assert cfg == before, "derived availability must never overwrite stock, schedules or history"


def test_stocked_bottle_can_feed_while_its_culture_regrows():
    cfg = _config()
    _stock(cfg)
    events = _pending(cfg)
    assert [(e["source"], e["ml"]) for e in events] == [("shelf:home_phyto_main", 35)]
    assert len(integration._maintenance_due_items(cfg, NOW)) == 1
    for jar in cfg["nps"]["cultures"]["jars"].values():
        assert t.cultures.density_advice("green", t.cultures.culture_state(jar, NOW))["action"] == "wait"


def test_two_stocked_default_bottles_offer_one_tank_dose_and_share_a_skip():
    cfg = _config()
    _stock(cfg, "main")
    _stock(cfg, "backup")
    assert len(_pending(cfg)) == 1
    products = cfg["consumables"]["products"]
    assert nps.shelf_summary(products, NOW, 52)["doseDueCount"] == 1
    products["home_phyto_main"]["doseSkippedAt"] = t._iso(NOW)
    assert not _pending(cfg)
    assert not integration._maintenance_due_items(cfg, NOW)
    assert len(_pending(cfg, NOW + timedelta(hours=25))) == 1
    assert not any(p["history"] for p in products.values()), "skips never invent consumption"


def test_default_dose_emptying_one_bottle_does_not_request_another_from_backup():
    cfg = _config()
    _stock(cfg, "backup", 35)
    _stock(cfg, "main")
    entry = t._phyto_entry()
    entry.options[t.CONF_SETTINGS] = cfg
    hass, conn = t.FakeHass(entries=[entry]), t.FakeConnection()
    t.run(integration.websocket_consumable_log_dose(hass, conn, {"id": 1, "product_id": "home_phyto_backup"}))
    assert not conn.errors, conn.errors
    saved = t._config(entry)
    now = datetime.now(timezone.utc)
    assert saved["consumables"]["products"]["home_phyto_backup"]["remainingMl"] == 0
    assert saved["consumables"]["products"]["home_phyto_main"]["remainingMl"] == 500
    assert not _pending(saved, now)
    assert len([e for e in _events(saved, now) if e["status"] == "done"]) == 1
    assert not integration._maintenance_due_items(saved, now)
    assert len(_pending(saved, now + timedelta(hours=25))) == 1
    # Taking back that dose restores stock and the single shared reminder.
    t.run(integration.websocket_consumable_undo_dose(hass, conn, {"id": 2, "product_id": "home_phyto_backup"}))
    assert not conn.errors, conn.errors
    assert len(_pending(t._config(entry), now)) == 1


def test_customised_plans_are_not_silently_merged():
    for change in ({"doseMl": 20}, {"doseEveryDays": 2}, {"doseFirstAt": "20:00"},
                   {"doseEveryHours": 12}, {"doseTimesPerDay": 2}, {"doseNote": "My own plan"}):
        cfg = _config()
        _stock(cfg, "backup")
        _stock(cfg, "main").update(change)
        plans = nps.hand_dose_plans(cfg["consumables"]["products"], NOW, 52)
        assert all(not plan.get("shared") and not plan["pauseReason"] for plan in plans.values()), change


def test_auto_estimates_from_different_tank_sizes_still_share_one_feed():
    cfg = _config()
    _stock(cfg, "backup")
    _stock(cfg, "main").update(doseMl=40, doseNote=nps.home_phyto_dose_note(40))
    assert len(_pending(cfg)) == 1, "adding a bottle after changing tank volume must not double the plan"


def test_shared_clock_ignores_invalid_stamps_and_preserves_overdue_severity():
    cfg = _config()
    main = _stock(cfg, "main")
    backup = _stock(cfg, "backup")
    main["lastDosedAt"] = t._iso(NOW - timedelta(days=4))
    for invalid in ("junk", "2026-01-01T12:00:00", t._iso(NOW + timedelta(days=1))):
        backup["lastDosedAt"] = invalid
        due = integration._maintenance_due_items(cfg, NOW)
        assert len(due) == 1 and due[0]["severity"] == "critical"


def test_insufficient_or_expired_supply_pauses_but_keeps_actual_feeds():
    for overrides in ({"remainingMl": 0}, {"remainingMl": 20}, {"openedAt": ""},
                      {"openedAt": t._iso(NOW - timedelta(days=22))}):
        cfg = _config()
        p = _stock(cfg)
        p.update(overrides)
        p["history"] = [{"at": t._iso(NOW), "ml": 35, "kind": "dose", "to": "tank"}]
        assert not _pending(cfg)
        assert len([e for e in _events(cfg) if e["status"] == "done"]) == 1
        assert not integration._maintenance_due_items(cfg, NOW)
    # Generic shelf bottles also stop asking for stock that does not exist.
    p = {"bottleMl": 100, "remainingMl": 0, "doseMl": 5, "doseEveryDays": 1}
    assert not nps.hand_dose_state(p, NOW)["clock"]["due"]
    p["remainingMl"] = 5
    assert nps.hand_dose_state(p, NOW)["clock"]["due"]


def test_unavailable_quick_dose_is_refused_without_changing_the_ledger():
    cfg = _config()
    entry = t._phyto_entry()
    entry.options[t.CONF_SETTINGS] = cfg
    hass, conn = t.FakeHass(entries=[entry]), t.FakeConnection()
    before = copy.deepcopy(entry.options)
    t.run(integration.websocket_consumable_log_dose(hass, conn, {"id": 1, "product_id": "home_phyto_main"}))
    assert conn.error_codes == ["dose_unavailable"]
    assert entry.options == before


def test_nudge_requires_observed_readiness_even_after_calendar_deadline():
    empty = {"empty": True, "remainingMl": 0, "daysUntilEmpty": 0}
    st = {"status": "producing", "splitEligible": True, "lastTint": "green", "harvest": {"due": True}}
    assert "still greening" in nps.home_bottle_nudge(empty, st, "Main")
    st["lastTint"] = "dark"
    assert "reads dark: split" in nps.home_bottle_nudge(empty, st, "Main")
    st["harvestBlocked"] = True
    assert "nothing goes into the bottle" in nps.home_bottle_nudge(empty, st, "Main")


def test_ws_shelf_timeline_and_culture_cards_agree_on_empty_supply():
    entry = t._phyto_entry()
    entry.options[t.CONF_SETTINGS] = _config()
    hass, conn = t.FakeHass(entries=[entry]), t.FakeConnection()
    t.run(integration.websocket_nps_summary(hass, conn, {"id": 1}))
    summary = conn.results[-1].payload
    assert summary["shelf"]["doseDueCount"] == 0
    assert not [e for e in summary["timeline"]["events"] if e["source"].startswith("shelf:home_phyto_")]
    t.run(integration.websocket_cultures_summary(hass, conn, {"id": 2}))
    for jar in conn.results[-1].payload["jars"]:
        assert jar["densityAdvice"]["action"] == "wait"
        assert jar["homeBottle"]["handDose"]["pauseReason"]
        assert not jar["homeBottle"]["handDose"]["clock"]["due"]


if __name__ == "__main__":
    tests = [(name, fn) for name, fn in sorted(globals().items()) if name.startswith("test_") and callable(fn)]
    failures = 0
    for name, fn in tests:
        try:
            fn()
            print(f"PASS {name}")
        except Exception:
            failures += 1
            print(f"FAIL {name}")
            traceback.print_exc()
    print(f"{len(tests) - failures}/{len(tests)} passed")
    raise SystemExit(bool(failures))
