"""Whole-tank feeding totals, identity and volume estimates.

Run standalone with ``python3 tests/test_feeding.py``.
"""

from __future__ import annotations

from copy import deepcopy
from datetime import datetime, timedelta, timezone
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import _ha_stubs  # noqa: E402

_ha_stubs.install()
sys.path.insert(0, os.path.join(os.path.dirname(HERE), "custom_components"))
from openreef import feeding  # noqa: E402

NOW = datetime(2026, 11, 1, 18, 30, tzinfo=timezone.utc)


def catalog():
    return feeding.build_catalog(
        {
            "home_phyto_a": {"name": "Nanno bottle A", "category": "phyto", "doseMl": 100},
            "home_phyto_b": {"name": "Nanno bottle B", "category": "phyto", "doseMl": 50},
            "preserved": {"name": "Preserved phyto", "category": "phyto", "liveFood": False},
            "blend": {"name": "Commercial phyto blend", "category": "phyto", "liveFood": True},
            "unknown_phyto": {"name": "Unclassified phyto", "category": "phyto"},
        },
        {"jars": {"a": {"name": "Nanno A", "species": "nanno"},
                  "b": {"name": "Nanno B", "species": "nanno"},
                  "r": {"name": "Rotifer cone", "species": "rotifer_L"}}},
        {"flake": {"name": "Flake", "unit": "pinch", "portion": 1},
         "scoop": {"name": "Powder", "unit": "scoop", "portion": .5}},
    )


def row(id, source="brine", ml=250, *, days_ago=0, **values):
    return {"id": id, "source": source, "name": "Legacy row name", "ml": ml,
            "at": (NOW - timedelta(days=days_ago, hours=1)).isoformat(), **values}


def total(summary, fid, unit="ml"):
    return next(f for f in summary["totals"] if f["foodId"] == fid and f["unit"] == unit)


def test_native_foods_combine_sources_but_not_different_products():
    cat = catalog()
    rows = [row("b1", **{"from": "container"}), row("b2", **{"from": "bottle"}),
            row("n1", "shelf:home_phyto_a", 100), row("n2", "shelf:home_phyto_b", 200),
            row("n3", "culture:a", 300), row("r1", "cultures-bottle", 50),
            row("r2", "culture:r", 100), row("blend", "shelf:blend", 20)]
    result = feeding.summarize(NOW, rows, cat, tank_litres=500)
    assert total(result, "brine")["amount"] == 500
    assert {s["id"] for s in total(result, "brine")["sources"]} == {"brine:container", "brine:bottle"}
    assert total(result, "phyto:nanno")["amount"] == 600
    assert len(total(result, "phyto:nanno")["sources"]) == 3
    assert total(result, "rotifers")["amount"] == 150
    assert total(result, "product:blend")["amount"] == 20
    assert result["liveLiquidMl"] == 1270


def test_volume_percent_is_period_liquid_over_configured_water_volume():
    rows = [row("b", ml=5000), row("n", "culture:a", 8000)]
    five_hundred = feeding.summarize(NOW, rows, catalog(), tank_litres=500)
    assert total(five_hundred, "brine")["tankVolumePct"] == 1
    fifty_two = feeding.summarize(NOW, rows, catalog(), tank_litres=52)
    assert total(fifty_two, "brine")["tankVolumePct"] == 9.615
    two_hundred = feeding.summarize(NOW, rows, catalog(), tank_litres=200)
    assert two_hundred["liveVolumePct"] == 6.5
    assert "carrier water" in two_hundred["volumeNote"]
    for invalid in (None, "", 0, -10, "bad", float("nan"), float("inf"), True):
        result = feeding.summarize(NOW, rows, catalog(), tank_litres=invalid)
        assert result["tankLitres"] is None
        assert result["liveVolumePct"] is None
        assert total(result, "brine")["tankVolumePct"] is None


def test_dry_and_prepared_foods_do_not_enter_live_liquid_estimate():
    rows = [row("live", ml=100), row("preserved", "shelf:preserved", 400),
            row("uncertain", "shelf:unknown_phyto", 500),
            row("dry", "manual:flake", None, amount=3, foodId="manual:flake", unit="pinch"),
            row("live_count", "manual:live_count", None, foodId="manual:live_count", name="Live prey",
                amount=2, unit="scoop", live=True),
            row("unknown", "brine", None)]
    result = feeding.summarize(NOW, rows, catalog(), tank_litres=100)
    assert total(result, "manual:flake", "pinch")["amount"] == 3
    assert total(result, "manual:flake", "pinch")["tankVolumePct"] is None
    assert result["liveLiquidMl"] == 100
    assert result["liveVolumePct"] == .1
    assert result["unknownLiveFeeds"] == 2
    assert result["unclassifiedLiquidMl"] == 500
    assert total(result, "brine")["unknownAmount"] == 1


def test_totals_and_counts_include_all_rows_beyond_display_cap():
    rows = [row(str(i), ml=10) for i in range(500)]
    result = feeding.summarize(NOW, rows, catalog(), limit=3)
    assert len(result["rows"]) == 3 and result["truncated"]
    assert result["rowCount"] == 500 and result["counts"]["feeds"] == 500
    assert total(result, "brine")["amount"] == 5000
    assert total(result, "brine")["feeds"] == 500
    assert result["perDay"][-1]["feeds"] == 500


def test_same_timestamp_separate_feeds_count_and_same_id_upserts():
    rows = [row("first", ml=100), row("second", ml=100), row("first", ml=150)]
    result = feeding.summarize(NOW, rows, catalog())
    assert result["counts"]["feeds"] == 2
    assert total(result, "brine")["amount"] == 250
    # Mutable pump day rows update one id instead of adding another day total.
    drip = [row("channel:drip@midnight", "channel:drip", 100, productId="home_phyto_a", drip=True),
            row("channel:drip@midnight", "channel:drip", 250, productId="home_phyto_a", drip=True)]
    result = feeding.summarize(NOW, drip, catalog())
    assert total(result, "phyto:nanno")["amount"] == 250


def test_undo_plans_transfers_and_stalls_are_not_actual_food():
    rows = [row("real", ml=100), row("undo", ml=500, undoneAt=NOW.isoformat()),
            row("planned", ml=1000, status="planned"), row("jar", ml=1000, to="jar"),
            row("soak", ml=1000, to="soak"), row("transfer", ml=1000, kind="transfer"),
            row("refill", ml=1000, kind="refill"),
            row("stall", "channel:phyto:stall", None, drip=True),
            row("future", ml=1000, at=(NOW+timedelta(minutes=1)).isoformat())]
    result = feeding.summarize(NOW, rows, catalog())
    assert total(result, "brine")["amount"] == 100
    assert result["counts"] == {"feeds": 1, "undone": 1}
    assert len(result["rows"]) == 2
    assert result["unknownLiveFeeds"] == 0


def test_graph_gaps_are_per_food_unknown_not_zero():
    rows = [row("b", ml=100, days_ago=2), row("n", "culture:a", 200, days_ago=1),
            row("zero", ml=0)]
    result = feeding.summarize(NOW, rows, catalog(), days=4)
    assert [day["hasRecords"] for day in result["perDay"]] == [False, True, True, True]
    b = [next(f for f in d["foods"] if f["foodId"] == "brine")["amount"] for d in result["perDay"]]
    assert b == [None, 100, None, 0]
    n = [next(f for f in d["foods"] if f["foodId"] == "phyto:nanno")["amount"] for d in result["perDay"]]
    assert n == [None, None, 200, None]
    assert result["coverage"]["daysWithRecords"] == 3
    assert not result["coverage"]["complete"]


def test_empty_and_unknown_quantity_history_remain_honest():
    empty = feeding.summarize(NOW, [], catalog(), days=7)
    assert empty["rows"] == empty["totals"] == []
    assert all(not day["hasRecords"] for day in empty["perDay"])
    unknown = feeding.summarize(NOW, [row("u", ml=None)], catalog(), tank_litres=100)
    assert total(unknown, "brine")["amount"] is None
    assert total(unknown, "brine")["unknownAmount"] == 1
    assert total(unknown, "brine")["tankVolumePct"] is None
    assert unknown["unknownLiveFeeds"] == 1


def test_local_actual_time_decides_day_and_window_not_planned_slot():
    local = datetime(2026, 11, 2, 1, 0, tzinfo=timezone(timedelta(hours=2)))
    rows = [row("late", at="2026-11-01T22:30:00+00:00", slot="16:00", ml=100),
            row("prior", at="2026-11-01T21:30:00+00:00", ml=250)]
    result = feeding.summarize(local, rows, catalog(), days=1)
    assert result["date"] == "2026-11-02"
    assert total(result, "brine")["amount"] == 100
    assert result["rows"][0]["time"] == "00:30"
    assert result["rows"][0]["slot"] == "16:00"
    # Ambiguous naive timestamps cannot silently inherit the server timezone.
    assert not feeding.summarize(NOW, [row("bad", at="2026-11-01T12:00")], catalog())["rows"]


def test_historical_units_and_live_classification_are_snapshots():
    raw = [row("old", "manual:flake", None, foodId="manual:flake", unit="g", amount=2, live=False),
           row("new", "manual:flake", None, foodId="manual:flake", unit="pinch", amount=3, live=False),
           row("prior", "shelf:blend", 100, foodId="product:blend", unit="ml", amount=100, live=False)]
    result = feeding.summarize(NOW, raw, catalog(), tank_litres=100)
    assert total(result, "manual:flake", "g")["amount"] == 2
    assert total(result, "manual:flake", "pinch")["amount"] == 3
    assert not total(result, "product:blend")["live"]
    assert result["liveLiquidMl"] == 0


def test_source_ids_and_inputs_are_preserved_for_native_undo():
    rows = [row("brine@stamp", **{"from": "bottle"}, slot="11:00", undoable=True)]
    before = deepcopy(rows)
    annotated = feeding.annotate_rows(rows, catalog())
    assert rows == before
    assert annotated[0]["source"] == "brine"
    assert annotated[0]["sourceId"] == "brine:bottle"
    assert annotated[0]["id"] == "brine@stamp"
    assert annotated[0]["undoable"] is True


def test_archive_age_and_unrecorded_pumps_do_not_claim_complete_coverage():
    result = feeding.summarize(NOW, [row("b", ml=100)], catalog(), days=30,
                              history_started_at=NOW.isoformat(), unrecorded=["Firmware pump"])
    assert not result["coverage"]["complete"]
    assert len(result["coverage"]["missingDates"]) == 29
    assert "older records may be incomplete" in " ".join(result["coverage"]["notes"])
    assert "Firmware pump" in " ".join(result["coverage"]["notes"])


def test_food_configuration_is_bounded_and_no_sample_brands_are_seeded():
    foods = feeding.normalise_foods({"ok": {"name": "My food", "unit": "scoops", "portion": .5},
                                     "bad": {"name": "Mystery", "unit": "bucket"},
                                     "empty": {"name": ""}})
    assert list(foods) == ["ok"]
    assert foods["ok"]["unit"] == "scoop" and foods["ok"]["portion"] == .5
    assert not feeding.normalise_foods(None)
    assert {f["name"] for f in feeding.build_catalog({})} == {"Live brine", "Live rotifers"}


def test_culture_presets_and_nutrients_are_not_tank_quick_feeds():
    from openreef.nps import PRODUCT_LIBRARY
    products = {p["name"]: deepcopy(p) for p in PRODUCT_LIBRARY}
    rules = feeding.tank_feed_rules(products)
    for name in ("Rotifer Feed Concentrate", "Copepod Feed"):
        assert rules[name]["tankFeed"] is False
        assert rules[name]["tankFeedLocked"] is False
    for name in ("Phytoplankton Nutrient (Guillard's f/2)", "Selcon", "Rotifer & Artemia Enrichment"):
        assert rules[name]["tankFeed"] is False
        assert rules[name]["tankFeedLocked"] is True
    for name in ("Reef Juice (live phyto blend)", "Phyto-Feast", "Oyster-Feast"):
        assert rules[name]["tankFeed"] is True


def test_culture_links_restrict_unknown_supplies_without_hiding_home_phyto():
    products = {pid: {"name": pid, "category": "phyto"}
                for pid in ("custom_nutrient", "animal_food", "my_phyto_bottle", "soak", "tank_food")}
    cultures = {"jars": {
        "a": {"species": "nanno", "nutrient": {"productId": "custom_nutrient"}, "bottleProductId": "my_phyto_bottle"},
        "r": {"species": "rotifer_L", "feed": {"productId": "my_phyto_bottle"}},
        "p": {"species": "tigriopus", "feed": {"productId": "animal_food"}},
    }}
    before = deepcopy(products)
    rules = feeding.tank_feed_rules(products, cultures, {"enrichment": {"productId": "soak"}})
    assert rules["custom_nutrient"]["tankFeedLocked"] is True
    assert rules["soak"]["tankFeedLocked"] is True
    assert rules["animal_food"]["tankFeed"] is False
    assert rules["my_phyto_bottle"]["tankFeed"] is True
    assert rules["tank_food"]["tankFeed"] is True
    assert products == before


def test_f2_name_fallback_works_before_a_nutrient_link_is_configured():
    rules = feeding.tank_feed_rules({
        "unlinked": {"name": "Guillard’s F / 2 fertiliser", "brand": "Custom", "category": "other"},
        "food": {"name": "Reef food", "category": "other"},
    })
    assert rules["unlinked"]["tankFeed"] is False and rules["unlinked"]["tankFeedLocked"] is True
    assert rules["food"]["tankFeed"] is True


def test_stored_supply_roles_survive_a_name_change():
    rules = feeding.tank_feed_rules({
        "nutrient": {"name": "Culture bottle A", "feedingUse": "culture_nutrient"},
        "culture_food": {"name": "Culture bottle B", "feedingUse": "culture_feed"},
    })
    assert rules["nutrient"]["tankFeedLocked"] is True
    assert rules["culture_food"]["tankFeed"] is False
    assert feeding.shelf_feeding_use({"name": "Fish food", "feedingUse": "unknown"}) == ""


if __name__ == "__main__":
    failures = 0
    for name, fn in sorted(globals().items()):
        if name.startswith("test_") and callable(fn):
            try:
                fn()
                print(f"  ok  {name}")
            except Exception as error:
                failures += 1
                print(f"FAIL  {name}: {type(error).__name__}: {error}")
    raise SystemExit(1 if failures else 0)
