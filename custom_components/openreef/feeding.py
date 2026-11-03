"""Whole-tank feeding summaries, independent of Home Assistant and storage.

Amounts are logged portions, not nutritional equivalents. Liquid percentages
describe liquid added over the selected period, including carrier water; they
are not a biomass estimate, water-change percentage, or a feeding target.
"""

from __future__ import annotations

from datetime import date, datetime, timedelta
import math
import re
from typing import Any

from .cultures import species_ids, species_preset
from .nps import ENRICHMENT_CATEGORY, HOME_PHYTO_PREFIX, PRODUCT_LIBRARY

UNITS = ("ml", "pinch", "scoop", "g", "cube", "drop", "piece")
MAX_DAYS = 365
ROTATION_PHASES = ("marine", "platinum")
ROTATION_DAYS = {"marine": 28, "platinum": 14}
_UNIT_ALIASES = {"pinches": "pinch", "scoops": "scoop", "grams": "g",
                 "cubes": "cube", "drops": "drop", "pieces": "piece", "mL": "ml"}


def _number(value: Any) -> float | None:
    if value is None or isinstance(value, bool):
        return None
    try:
        value = float(value)
    except (TypeError, ValueError, OverflowError):
        return None
    return value if math.isfinite(value) and value >= 0 else None


def _stamp(value: Any) -> datetime | None:
    if not isinstance(value, str) or not value:
        return None
    try:
        result = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except (ValueError, TypeError):
        return None
    return result if result.utcoffset() is not None else None


def _unit(value: Any, default: str = "ml") -> str:
    value = str(value or default).strip()
    return _UNIT_ALIASES.get(value, value)


def _items(value: Any) -> dict[str, dict[str, Any]]:
    if isinstance(value, dict):
        return {str(k): v for k, v in value.items() if isinstance(v, dict)}
    if isinstance(value, list):
        return {str(v["id"]): v for v in value if isinstance(v, dict) and v.get("id")}
    return {}


def normalise_foods(raw: Any) -> dict[str, dict[str, Any]]:
    """Validate manually configured foods without inventing brands or history."""
    foods = {}
    for fid, item in list(_items(raw).items())[:128]:
        name = str(item.get("name") or "").strip()[:120]
        unit = _unit(item.get("unit"), "pinch")
        if not name or unit not in UNITS or not fid or len(fid) > 120:
            continue
        portion = _number(item.get("portion"))
        foods[fid] = {
            "name": name, "unit": unit,
            "portion": min(50000.0, portion) if portion and portion > 0 else 1.0,
            "live": item.get("live") is True or item.get("liveFood") is True,
            "enabled": item.get("enabled") is not False,
        }
    return foods


def _calendar_date(value: Any) -> date | None:
    """Only a local calendar date, never a timestamp or an elapsed duration."""
    if not isinstance(value, str) or not re.fullmatch(r"\d{4}-\d{2}-\d{2}", value):
        return None
    try:
        return date.fromisoformat(value)
    except ValueError:
        return None


def normalise_rotation(raw: Any) -> dict[str, Any]:
    """Bound the optional shared calendar; a missing/invalid anchor stays off."""
    raw = raw if isinstance(raw, dict) else {}
    start = _calendar_date(raw.get("startDate"))
    groups = {}
    for key in ("marineFoodIds", "platinumFoodIds"):
        values = raw.get(key) if isinstance(raw.get(key), list) else []
        groups[key] = list(dict.fromkeys(v for v in values if isinstance(v, str) and 0 < len(v) <= 140))[:128]
    marker = _calendar_date(raw.get("observedPhaseStartDate"))
    return {"enabled": raw.get("enabled") is True and start is not None,
            "startDate": start.isoformat() if start else "",
            "startPhase": raw.get("startPhase") if raw.get("startPhase") in ROTATION_PHASES else "marine",
            **groups, "notify": raw.get("notify") is True,
            "observedPhaseStartDate": marker.isoformat() if marker else ""}


def rotation_food_ids(catalog: Any) -> set[str]:
    """Eligible linked foods; empty stock affects logging, not the calendar."""
    return {fid for fid, food in _items(catalog).items()
            if food.get("enabled", True) and food.get("tankFeed", True) and food.get("loggable", True)
            and any(isinstance(source, dict) and source.get("loggable", True)
                    and source.get("tankFeed", True) for source in food.get("sources", []))}


def validate_rotation(raw: dict[str, Any], catalog: Any) -> dict[str, Any]:
    """Validate explicit choices, without guessing Vitalis products by name."""
    # Turning guidance off must never require repairing a deleted food or an
    # old malformed anchor first. Bounded selections remain available to edit.
    if raw.get("enabled") is False:
        return normalise_rotation(raw)
    if raw.get("startPhase") not in ROTATION_PHASES:
        raise ValueError("Choose Marine or Platinum as the starting phase.")
    if (raw.get("enabled") or raw.get("startDate")) and _calendar_date(raw.get("startDate")) is None:
        raise ValueError("Choose a valid phase start date (YYYY-MM-DD).")
    for key in ("marineFoodIds", "platinumFoodIds"):
        values = raw.get(key)
        if (not isinstance(values, list) or len(values) > 128
                or any(not isinstance(v, str) or not 0 < len(v) <= 140 for v in values)):
            raise ValueError("Choose foods from your current tank-feeding catalogue.")
    rotation = normalise_rotation(raw)
    marine, platinum = set(rotation["marineFoodIds"]), set(rotation["platinumFoodIds"])
    if marine & platinum:
        raise ValueError("A food can belong to only one rotation phase.")
    if (marine | platinum) - rotation_food_ids(catalog):
        raise ValueError("Choose existing tank foods; culture supplies and harvest-only sources cannot join this rotation.")
    if rotation["enabled"] and (not marine or not platinum):
        raise ValueError("Choose at least one Marine food and one Platinum food before enabling the rotation.")
    return rotation


def rotation_summary(now_local: datetime, raw: Any, catalog: Any) -> dict[str, Any]:
    """Marine 28 calendar days then Platinum 14, in the caller's local zone.

    startDate is day one of startPhase, so choosing a past date resumes an
    existing routine. This is guidance only and never consumes feeding rows.
    """
    rotation = normalise_rotation(raw)
    summary = {k: v for k, v in rotation.items() if k != "observedPhaseStartDate"}
    summary.update(status="disabled", phase=None, phaseLabel="", cycleDay=None, cycleWeek=None,
                   phaseDay=None, phaseStartDate=None, nextPhase=None, nextSwitchDate=None,
                   daysUntilSwitch=None, suggestedFoodIds=[], invalidFoodIds=[])
    if not rotation["enabled"]:
        return summary
    start, today = _calendar_date(rotation["startDate"]), now_local.date()
    eligible = rotation_food_ids(catalog)
    groups = rotation["marineFoodIds"] + rotation["platinumFoodIds"]
    invalid = sorted(set(groups) - eligible)
    overlap = set(rotation["marineFoodIds"]) & set(rotation["platinumFoodIds"])
    summary["invalidFoodIds"] = sorted(set(invalid) | overlap)
    missing = bool(invalid or overlap or not rotation["marineFoodIds"] or not rotation["platinumFoodIds"])
    if today < start:
        summary.update(status="needs_foods" if missing else "upcoming", nextPhase=rotation["startPhase"],
                       phaseStartDate=rotation["startDate"], nextSwitchDate=rotation["startDate"],
                       daysUntilSwitch=(start - today).days)
        return summary
    cycle_day = ((today - start).days + (28 if rotation["startPhase"] == "platinum" else 0)) % 42
    phase = "marine" if cycle_day < 28 else "platinum"
    phase_day = cycle_day + 1 if phase == "marine" else cycle_day - 27
    remaining = ROTATION_DAYS[phase] - phase_day + 1
    phase_start = today - timedelta(days=phase_day - 1)
    try:
        next_switch = (today + timedelta(days=remaining)).isoformat()
    except OverflowError:
        next_switch = None
    summary.update(status="needs_foods" if missing else "active", phase=phase, phaseLabel=phase.title(),
                   cycleDay=cycle_day + 1, cycleWeek=cycle_day // 7 + 1, phaseDay=phase_day,
                   phaseStartDate=phase_start.isoformat(), nextPhase="platinum" if phase == "marine" else "marine",
                   nextSwitchDate=next_switch, daysUntilSwitch=remaining,
                   suggestedFoodIds=[fid for fid in rotation[phase + "FoodIds"] if fid in eligible and fid not in overlap])
    return summary


def shelf_feeding_use(product: Any) -> str:
    """Preserve a known supply role even when its display name is changed."""
    if not isinstance(product, dict):
        return ""
    role = product.get("feedingUse")
    if role in ("culture_feed", "culture_nutrient"):
        return role
    name = str(product.get("name") or "")
    if re.search(r"\bf\s*/\s*2\b", name, re.I):
        return "culture_nutrient"
    key = (name.casefold(), str(product.get("brand") or "").casefold())
    return next((p["feedingUse"] for p in PRODUCT_LIBRARY if p.get("feedingUse")
                 and (p["name"].casefold(), p["brand"].casefold()) == key), "")


def tank_feed_rules(products: Any, cultures: Any = None, hatchery: Any = None) -> dict[str, dict[str, Any]]:
    """Current shelf use controls new tank feeds, never historical destinations.

    Culture-feed links default to culture use; a keeper may opt into dual use.
    Nutrient and enrichment supplies use their existing specialist controls.
    Home phyto bottles remain tank foods when shared with an animal culture.
    """
    cultures = cultures if isinstance(cultures, dict) else {}
    hatchery = hatchery if isinstance(hatchery, dict) else {}
    jars = _items(cultures.get("jars"))
    def linked(value: Any) -> str:
        return str(value.get("productId") or "") if isinstance(value, dict) else ""
    nutrients = {linked(jar.get("nutrient")) for jar in jars.values()} - {""}
    culture_feeds = {linked(jar.get("feed")) for jar in jars.values()} - {""}
    enrichment = {linked(cultures.get("enrichment")), linked(hatchery.get("enrichment"))} - {""}
    home_bottles = {str(jar.get("bottleProductId") or HOME_PHYTO_PREFIX + jid)
                    for jid, jar in jars.items() if jar.get("species") in species_ids()
                    and species_preset(jar["species"]).get("kind") == "phyto"}
    rules = {}
    for pid, product in _items(products).items():
        role = shelf_feeding_use(product)
        nutrient = pid in nutrients or role == "culture_nutrient"
        if nutrient:
            allowed, locked, reason = False, True, "Culture nutrient — record its use in Cultures."
        elif product.get("category") == ENRICHMENT_CATEGORY or pid in enrichment:
            allowed, locked, reason = False, True, "Enrichment supply — use the hatchery or culture enrichment controls."
        elif (pid in culture_feeds or role == "culture_feed") and not (
                pid in home_bottles or pid.startswith(HOME_PHYTO_PREFIX)):
            allowed, locked, reason = False, False, "Culture feed — enable tank feeding only if you also feed this product to the tank."
        else:
            allowed, locked, reason = True, False, ""
        rules[pid] = {"tankFeed": allowed, "tankFeedLocked": locked, "tankFeedReason": reason}
    return rules


def build_catalog(products: Any, cultures: Any = None, foods: Any = None) -> list[dict[str, Any]]:
    """Map physical feed sources to food identity without merging by name.

    Native brine containers share one food; native culture jars and their
    linked bottles share their species. Independent shop products retain their
    own identity. A preserved phyto product is not live merely because its
    category is ``phyto``. Such products need an explicit ``liveFood`` flag.
    """
    catalog: dict[str, dict[str, Any]] = {}
    source_food: dict[str, str] = {}

    def add(fid: str, name: str, unit: str, live: bool, portion: Any,
            source: dict[str, Any], *, live_known: bool = True, enabled: bool = True) -> None:
        food = catalog.setdefault(fid, {"id": fid, "name": name, "unit": unit,
                                       "portion": _number(portion) or 1.0,
                                       "live": live, "liveKnown": live_known,
                                       "enabled": enabled, "sources": []})
        sid = source["id"]
        if sid in source_food:
            return
        food["sources"].append(source)
        source_food[sid] = fid

    add("brine", "Live brine", "ml", True, 250,
        {"id": "brine:container", "label": "Brine container", "kind": "brine", "from": "container"})
    add("brine", "Live brine", "ml", True, 250,
        {"id": "brine:bottle", "label": "Brine fridge bottle", "kind": "brine", "from": "bottle"})
    add("rotifers", "Live rotifers", "ml", True, 100,
        {"id": "cultures-bottle", "label": "Rotifer fridge bottle", "kind": "bottle"})

    products = _items(products)
    cultures = cultures if isinstance(cultures, dict) else {}
    known_species = set(species_ids())
    for jid, jar in _items(cultures.get("jars")).items():
        species = str(jar.get("species") or "")
        preset = species_preset(species) if species in known_species else {}
        kind = preset.get("kind")
        jar_name = str(jar.get("name") or jid)
        if kind == "phyto":
            fid = f"phyto:{species}"
            name = "Live phyto · " + ("Nanno" if species == "nanno" else str(preset.get("name") or species))
        elif kind == "rotifer":
            fid, name = "rotifers", "Live rotifers"
        elif species in known_species:
            fid, name = f"culture-species:{species}", "Live " + str(preset.get("name") or species)
        else:
            # Unknown species never inherit species_preset's rotifer fallback.
            fid, name = f"culture:{jid}", jar_name
        add(fid, name, "ml", True, 100, {"id": f"culture:{jid}", "label": jar_name,
                                          "kind": "culture", "jarId": jid})
        if kind == "phyto":
            pid = str(jar.get("bottleProductId") or f"home_phyto_{jid}")
            product = products.get(pid)
            if product:
                add(fid, name, "ml", True, product.get("doseMl") or 100,
                    {"id": f"shelf:{pid}", "label": str(product.get("name") or jar_name + " bottle"),
                     "kind": "shelf", "productId": pid})

    for pid, product in products.items():
        sid = f"shelf:{pid}"
        if sid in source_food:
            continue
        meta = product.get("live") if isinstance(product.get("live"), dict) else {}
        name = str(product.get("name") or pid)
        if pid in ("live_brine_container", "live_brine_bottle") or meta.get("kind") == "brine":
            fid, food_name = "brine", "Live brine"
        elif pid == "live_rotifer_bottle" or pid.startswith("live_rotifer_cone_") or meta.get("kind") == "rotifers":
            fid, food_name = "rotifers", "Live rotifers"
        else:
            fid, food_name = f"product:{pid}", name
        explicit = product.get("liveFood") if isinstance(product.get("liveFood"), bool) else product.get("live")
        live = bool(explicit is True or meta or product.get("category") == "zooLive"
                    or pid.startswith("home_phyto_"))
        if explicit is False:
            live = False
        live_known = isinstance(explicit, bool) or live or product.get("category") not in (None, "", "phyto", "blend", "other")
        unit = _unit(product.get("feedingUnit"), "ml")
        add(fid, food_name, unit, live, product.get("doseMl") or (100 if live else 1),
            {"id": sid, "label": name, "kind": "shelf", "productId": pid}, live_known=live_known)

    for fid, food in normalise_foods(foods).items():
        source = f"manual:{fid}"
        add(source, food["name"], food["unit"], food["live"], food["portion"],
            {"id": source, "label": "By hand", "kind": "manual", "foodId": fid},
            enabled=food["enabled"])
    return list(catalog.values())


def annotate_rows(rows: Any, catalog: Any) -> list[dict[str, Any]]:
    """Attach stable food identity and source labels to the old feeding rows.

    ``source`` and the original ``id`` remain untouched so existing undo
    commands still address the original ledger. Archived canonical metadata
    wins over current catalog settings, preserving historic unit/live flags.
    """
    foods = _items(catalog)
    by_source = {str(source.get("id")): (food, source)
                 for food in foods.values()
                 for source in food.get("sources", []) if isinstance(source, dict) and source.get("id")}
    result = []
    for raw in rows if isinstance(rows, list) else []:
        if not isinstance(raw, dict):
            continue
        row = dict(raw)
        source = str(row.get("sourceId") or row.get("source") or "")
        if source == "brine":
            source = "brine:" + ("bottle" if row.get("from") == "bottle" else "container")
        matching = by_source.get(source)
        if matching is None and row.get("productId"):
            matching = by_source.get("shelf:" + str(row["productId"]))
        food = foods.get(str(row.get("foodId") or ""))
        if food is None and matching:
            food = matching[0]
        food = food or {}
        canonical = bool(row.get("foodId"))
        fid = str(row.get("foodId") or food.get("id") or source or row.get("id") or "unknown")
        live = row.get("live") if canonical and isinstance(row.get("live"), bool) else food.get("live", False)
        row.update({
            "foodId": fid,
            "name": str(row.get("name") if canonical and row.get("name") else food.get("name") or row.get("name") or fid),
            "unit": _unit(row.get("unit") if canonical else food.get("unit"), "ml"),
            "amount": _number(row.get("amount") if "amount" in row else row.get("ml")),
            "live": live is True,
            "liveKnown": bool(row.get("liveKnown", True) if canonical and "live" in row else food.get("liveKnown", False)),
            "sourceId": source,
            "sourceLabel": str(row.get("sourceLabel") or (matching[1].get("label") if matching else None)
                               or row.get("from") or row.get("via") or row.get("source") or "By hand"),
        })
        result.append(row)
    return result


def summarize(now_local: datetime, rows: Any, catalog: Any, *, days: Any = 7,
              tank_litres: Any = None, history_started_at: Any = None,
              unrecorded: Any = None, limit: int = 300) -> dict[str, Any]:
    """Sum every available actual feed before limiting the display rows.

    Absent food/day records have ``amount: None``. An explicit known zero
    (for example a daily pump total) stays zero. No window is labelled complete:
    a durable archive cannot prove that every manual feed was recorded.
    """
    if now_local.utcoffset() is None:
        raise ValueError("now_local must have an explicit timezone")
    count = _number(days)
    days = max(1, min(MAX_DAYS, int(count or 7)))
    today = now_local.date()
    since = today - timedelta(days=days - 1)
    tank = _number(tank_litres)
    tank = tank if tank and tank > 0 else None
    by_id: dict[str, dict[str, Any]] = {}
    anonymous: list[dict[str, Any]] = []
    for row in annotate_rows(rows, catalog):
        if row.get("id"):
            by_id[str(row["id"])] = row
        else:
            anonymous.append(row)
    selected = []
    for row in [*by_id.values(), *anonymous]:
        stamp = _stamp(row.get("at"))
        if stamp is None or stamp > now_local:
            continue
        local = stamp.astimezone(now_local.tzinfo)
        if local.date() < since or local.date() > today:
            continue
        if row.get("status") in ("planned", "due", "late", "missed", "skipped", "expected", "blocked"):
            continue
        if row.get("to") in ("jar", "soak", "bottle", "waste"):
            continue
        if row.get("kind") in ("transfer", "refill", "request", "requested"):
            continue
        if str(row.get("source") or "").endswith(":stall"):
            continue
        row.update({"date": local.date().isoformat(), "time": local.strftime("%H:%M"),
                    "undone": bool(row.get("undone") or row.get("undoneAt"))})
        selected.append((stamp, row))
    selected.sort(key=lambda pair: (pair[0], str(pair[1].get("id") or "")), reverse=True)
    all_rows = [row for _, row in selected]
    totals: dict[tuple[str, str], dict[str, Any]] = {}
    daily: dict[str, dict[tuple[str, str], dict[str, Any]]] = {}
    live_ml = 0.0
    unknown_live = 0
    unclassified_ml = 0.0
    active = 0
    for row in all_rows:
        if row["undone"]:
            continue
        active += 1
        key = (row["foodId"], row["unit"])
        bucket = totals.setdefault(key, {
            "foodId": row["foodId"], "name": row["name"], "unit": row["unit"],
            "amount": None, "feeds": 0, "unknownAmount": 0, "live": row["live"],
            "liveLiquidMl": 0.0, "tankVolumePct": None, "sources": {},
        })
        bucket["feeds"] += 1
        # Old and new classification stamps may coexist; the volume numerator
        # includes each row only when that row explicitly recorded live food.
        bucket["live"] = bucket["live"] or row["live"]
        source = bucket["sources"].setdefault(row["sourceId"], {
            "id": row["sourceId"], "label": row["sourceLabel"], "unit": row["unit"],
            "amount": None, "feeds": 0, "unknownAmount": 0,
        })
        source["feeds"] += 1
        day_food = daily.setdefault(row["date"], {}).setdefault(key, {
            "foodId": row["foodId"], "unit": row["unit"], "amount": None,
            "feeds": 0, "unknownAmount": 0, "liveLiquidMl": 0.0,
        })
        day_food["feeds"] += 1
        amount = row["amount"]
        for target in (bucket, source, day_food):
            if amount is None:
                target["unknownAmount"] += 1
            else:
                target["amount"] = (target["amount"] or 0.0) + amount
        if row["live"]:
            if row["unit"] == "ml" and amount is not None:
                live_ml += amount
                bucket["liveLiquidMl"] += amount
                day_food["liveLiquidMl"] += amount
            else:
                unknown_live += 1
        elif not row.get("liveKnown") and row["unit"] == "ml" and amount is not None:
            unclassified_ml += amount

    def rounded(value: float | None) -> float | None:
        return round(value, 3) if value is not None else None

    def percentage(ml: float) -> float | None:
        return round(ml / (tank * 1000.0) * 100.0, 3) if tank is not None else None

    ordered = sorted(totals.values(), key=lambda food: (food["name"].casefold(), food["unit"]))
    for food in ordered:
        food["amount"] = rounded(food["amount"])
        food["liveLiquidMl"] = rounded(food["liveLiquidMl"])
        food["tankVolumePct"] = (percentage(food["liveLiquidMl"])
                                 if food["live"] and food["unit"] == "ml" and food["amount"] is not None
                                 else None)
        food["sources"] = sorted(food["sources"].values(), key=lambda source: source["label"].casefold())
        for source in food["sources"]:
            source["amount"] = rounded(source["amount"])
    per_day = []
    for offset in range(days):
        date = (since + timedelta(days=offset)).isoformat()
        by_food = daily.get(date, {})
        entries = []
        for food in ordered:
            key = (food["foodId"], food["unit"])
            item = by_food.get(key, {"foodId": key[0], "unit": key[1], "amount": None,
                                     "feeds": 0, "unknownAmount": 0, "liveLiquidMl": None})
            entries.append({**item, "amount": rounded(item["amount"]),
                            "liveLiquidMl": rounded(item["liveLiquidMl"])})
        per_day.append({"date": date, "foods": entries, "hasRecords": bool(by_food),
                        "feeds": sum(item["feeds"] for item in by_food.values()),
                        "inProgress": date == today.isoformat()})
    started = _stamp(history_started_at)
    known_dates = sorted(daily)
    missing = [day["date"] for day in per_day if not day["hasRecords"]]
    notes = ["Logged amounts only. Missing records are unknown, not zero feeding."]
    if started and since < started.astimezone(now_local.tzinfo).date():
        notes.append("This range includes history from before the feeding archive started; older records may be incomplete.")
    unknown = sum(food["unknownAmount"] for food in ordered)
    if unknown:
        notes.append(f"{unknown} feed{'s have' if unknown != 1 else ' has'} no recorded quantity.")
    if unknown_live:
        notes.append("Live feeds without a recorded ml amount are excluded from the liquid-volume estimate.")
    if unclassified_ml:
        notes.append("Some liquid foods have no live/prepared classification and are excluded from the live-volume estimate.")
    unrecorded = [str(name) for name in unrecorded or [] if isinstance(name, str)]
    if unrecorded:
        notes.append("Some pump deliveries are not individually recorded: " + ", ".join(unrecorded) + ".")
    try:
        limit = max(1, int(limit))
    except (ValueError, TypeError, OverflowError):
        limit = 300
    return {
        "date": today.isoformat(), "since": since.isoformat(), "days": days,
        "foods": list(_items(catalog).values()), "rows": all_rows[:limit],
        # Today's timeline must not silently lose feeds at the log's display
        # cap. These are the same canonical rows, not a second feeding ledger.
        "timelineRows": [row for row in all_rows if row["date"] == today.isoformat()
                         and not row["undone"]] if days == 1 else [],
        "totals": ordered, "perDay": per_day,
        "counts": {"feeds": active, "undone": sum(row["undone"] for row in all_rows)},
        "truncated": len(all_rows) > limit, "rowCount": len(all_rows),
        "tankLitres": tank, "liveLiquidMl": rounded(live_ml), "liveVolumePct": percentage(live_ml),
        "unknownLiveFeeds": unknown_live, "unclassifiedLiquidMl": rounded(unclassified_ml),
        "volumeNote": "Logged live-feed liquid added, including carrier water, over this period; not biomass or water replaced.",
        "coverage": {"daysWithRecords": len(known_dates), "missingDates": missing,
                     "firstRecordedDate": known_dates[0] if known_dates else None,
                     "historyStartedAt": started.isoformat() if started else None,
                     "complete": False, "notes": notes},
    }
