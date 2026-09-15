"""Coral diary engine — pure maths for the colony registry (0.7.192).

Design stance (mirrors cultures.py / nps.py): every function here is a pure
function of its inputs — no Home Assistant imports, no I/O, no wall clock.
Orchestration (WS handlers, ledgers, the digest) lives in __init__.py; the
panel carries a LOCKSTEP mirror of the score and the due maths
(``_coralState``), pinned by the same fixtures in tests/test_livestock.py and
tests/test_panel_corals.mjs.

The honesty rule (docs/coral-diary-brainstorm.md §3.3): a coral cannot be
probed, so its score is an observation ledger with a confidence clock. A
colony nobody has looked at cannot grade A; the water is CONTEXT for the
card and never moves the number — the check-in already recorded what the
coral thought of the week.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any

from .awc import _f, _parse_iso
from . import nps as nps_engine

CORAL_STATUSES: tuple[str, ...] = ("active", "fragged", "rehomed", "lost")
CORALS_MAX = 60            # registered (the diary)
CORALS_DRAWN_MAX = 16      # drawn on the rockwork (the art budget, unchanged)
CHECKINS_MAX = 52          # per coral — a year of weekly looks
FEEDS_MAX = 100            # per coral
PHOTOS_MAX_DEFAULT = 24    # per coral; the keeper's cap lives in livestock.settings
PHOTOS_MAX_CEILING = 96
UNDO_HOURS = 24            # a check-in or a feed can be taken back for a day
LATE_HOURS = 24            # ...and logged up to a day late

# The check-in's tap rows. Order matters: the index IS the stored value for
# extension (0–3); the words are stored for the rest.
EXTENSION: tuple[str, ...] = ("retracted", "partial", "normal", "full")
TISSUE: tuple[str, ...] = ("intact", "stalled", "receding", "stn", "rtn")
FLUOR: tuple[str, ...] = ("same", "up", "fading")
FEEDING: tuple[str, ...] = ("", "took", "ignored")
PESTS: tuple[str, ...] = ("none", "suspected", "confirmed")
NEIGHBOURS: tuple[str, ...] = ("stung", "shaded", "nipped")
COLOUR_MIN, COLOUR_MAX = 1, 6          # CoralWatch Coral Health Chart brightness
COLOUR_BASELINE_DEFAULT = 4

TISSUE_WORDS = {"intact": "tissue intact", "stalled": "recession stopped (algae-dusted edge)",
                "receding": "active recession (white edge)", "stn": "slow tissue necrosis",
                "rtn": "rapid tissue necrosis"}
EXTENSION_WORDS = {0: "polyps retracted", 1: "partial extension", 2: "normal extension", 3: "full extension"}

# The score's vocabulary — one table, mirrored verbatim in the panel.
SCORE_LOSS = {
    "extension": {1: 10, 0: 25},
    "tissue": {"stalled": 8, "receding": 20, "stn": 30, "rtn": 40},
    "colour": {1: 6, 2: 15},              # steps under the colony's baseline (2 = two or more)
    "fluor": {"fading": 8},
    "feeding": {"ignored": 8},
    "pests": {"suspected": 12, "confirmed": 20},
    "neighbour": 8,                       # per neighbour trouble, at most two counted
}
SCORE_CAP = {
    "receding": 40, "stn": 20, "rtn": 10,
    "pests_confirmed": 60,
    "bleaching": 50,                      # colour ≤ 2 on the chart
    "unchecked": 70,                      # past twice the cadence with no look
}
GRADES: tuple[tuple[int, str], ...] = ((90, "A"), (75, "B"), (60, "C"), (40, "D"), (0, "E"))
STATUS_WATCH_BELOW = 75
STATUS_NEEDS_BELOW = 60
TREND_STEADY_PTS = 3

# --------------------------------------------------------------------------- #
# Groups: the classification every entry is guaranteed to have (the Reef
# Layer's art species), carrying the recommended cadences and the mouth. NPS
# animals defer to the NPS library — one animal, one record, one clock.
# --------------------------------------------------------------------------- #
GROUPS: dict[str, dict[str, Any]] = {
    "sps": {"label": "SPS", "checkDays": 7, "feedDays": 0,
            "foods": ("zooPrepared", "amino"), "particleUmMin": 5, "particleUmMax": 300,
            "feedNote": "Broadcast only — fine zooplankton and aminos for the whole tank. No per-colony feed."},
    "euphyllia": {"label": "Euphyllia & friends", "checkDays": 7, "feedDays": 7,
                  "foods": ("zooPrepared", "blend"), "particleUmMin": 300, "particleUmMax": 3000,
                  "feedNote": "Light target feeding, small particles, about weekly. Never force large items; sweepers reach 10–15 cm."},
    "lps_feeder": {"label": "LPS (regular feeder)", "checkDays": 7, "feedDays": 3,
                   "foods": ("zooPrepared", "blend"), "particleUmMin": 500, "particleUmMax": 5000,
                   "feedNote": "Target feed two or three times a week in the evening when the polyps are open — mysis, pellets, a blend."},
    "lps_meaty": {"label": "LPS (meaty, weekly)", "checkDays": 7, "feedDays": 5,
                  "foods": ("zooPrepared",), "particleUmMin": 1000, "particleUmMax": 20000,
                  "feedNote": "One or two modest meaty feeds a week — mysis, chopped seafood. Too much rots unswallowed."},
    "soft": {"label": "Soft corals & polyps", "checkDays": 14, "feedDays": 0,
             "foods": (), "particleUmMin": 0, "particleUmMax": 0,
             "feedNote": "No target feeding needed — they take what the tank offers."},
    "anemone": {"label": "Anemone", "checkDays": 7, "feedDays": 5,
                "foods": ("zooPrepared",), "particleUmMin": 2000, "particleUmMax": 20000,
                "feedNote": "A meaty chunk once or twice a week — mysis, a piece of silverside — never bigger than the mouth."},
    "clam": {"label": "Clam", "checkDays": 14, "feedDays": 0,
             "foods": ("phyto",), "particleUmMin": 1, "particleUmMax": 20,
             "feedNote": "Light does the feeding; live phyto helps a small clam. No target feed reminder."},
    "nps": {"label": "NPS (non-photosynthetic)", "checkDays": 7, "feedDays": 0,
            "foods": (), "particleUmMin": 0, "particleUmMax": 0,
            "feedNote": "The NPS feed plan owns this animal's feeds — the shelf, the pumps and the feeding log already count them."},
}
SPECIES_GROUP: dict[str, str] = {
    # 0.7.193: one row per catalogue id — mirrored by the panel's _coralCatalogue().
    **{s: "sps" for s in ("staghorn", "millepora", "tenuis", "table", "birdsnest", "pocillopora", "digitata", "setosa", "plate", "leptoseris", "stylophora", "hydnophora", "pavona", "psammocora", "porites", "cyphastrea")},
    **{s: "euphyllia" for s in ("torch", "hammer", "frogspawn", "octospawn", "bubble", "physogyra", "foxcoral", "elegance")},
    **{s: "lps_feeder" for s in ("acan", "blasto", "favia", "leptastrea", "brain", "platygyra", "chalice", "pectinia", "duncan", "candycane", "goniopora", "alveopora", "galaxea", "turbinaria", "symphyllia")},
    **{s: "lps_meaty" for s in ("scoly", "trachy", "cynarina", "acanthophyllia", "lobo", "fungia", "tongue")},
    **{s: "soft" for s in ("zoa", "palythoa", "mushroom", "rhodactis", "ricordea", "yuma", "xenia", "anthelia", "cespitularia", "gsp", "clove", "pipeorgan", "kenyatree", "sinularia", "nephthea", "toadstool", "lobophytum", "cabbage", "gorgonian_photo")},
    **{s: "anemone" for s in ("anemone", "rfa", "carpet", "lta", "magnifica")},
    **{s: "clam" for s in ("clam", "crocea", "derasa", "squamosa")},
    **{s: "nps" for s in ("tubastraea", "tubastraea_black", "dendrophyllia", "rhizotrochus", "chili", "dendronephthya", "chironephthya", "studeriotes", "seapen", "lacecoral", "gorgonian_easy", "gorgonian_hard", "gorgonian_atlantic", "gorgonian_purple", "gorgonian_whip", "gorgonian_fan", "blueberry", "crinoid", "basketstar", "cerianthus", "featherduster", "tubeworm", "seaapple", "filterfeeders")},
    "suncoral": "nps", "gorgonian": "nps",
}
# An NPS library id drawn on the rock (the migration's art pick, by family) —
# kept for a config whose species id predates the catalogue (0.7.193 stores
# the library id itself as the species).
NPS_ART_SPECIES = {"stony": "suncoral", "gorgonian": "gorgonian", "soft": "kenyatree", "filter": "clam"}

DEFAULT_SETTINGS: dict[str, Any] = {
    "remind": True,            # check-in reminders ride the daily digest
    "feedRemind": True,        # ...and the target-feed reminders
    "arrivalDays": 30,         # the new-arrival window
    "arrivalCadenceDays": 3,   # ...and its check-in cadence
    "photoCap": PHOTOS_MAX_DEFAULT,
}


def _days_between(later: datetime, earlier: datetime) -> float:
    return (later - earlier).total_seconds() / 86400.0


def _stamp(value: Any) -> datetime | None:
    """ISO stamp → aware datetime; a bare YYYY-MM-DD counts as midnight UTC."""
    parsed = _parse_iso(value)
    if parsed is None and isinstance(value, str) and len(value) == 10:
        parsed = _parse_iso(value + "T00:00:00+00:00")
    if parsed is not None and parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed


def group_id(coral: dict[str, Any]) -> str:
    if coral.get("npsId"):
        return "nps"
    return SPECIES_GROUP.get(str(coral.get("species") or ""), "soft")


def group_of(coral: dict[str, Any]) -> dict[str, Any]:
    return {"id": group_id(coral), **GROUPS[group_id(coral)]}


def settings_view(raw: Any) -> dict[str, Any]:
    """The diary's knobs, clamped — the normaliser's shape, re-applied so
    every reader (backend digest, panel mirror) sees one clamp."""
    raw = raw if isinstance(raw, dict) else {}
    out = dict(DEFAULT_SETTINGS)
    out["remind"] = bool(raw.get("remind", True))
    out["feedRemind"] = bool(raw.get("feedRemind", True))
    out["arrivalDays"] = int(max(0, min(90, _f(raw.get("arrivalDays", 30)))))
    out["arrivalCadenceDays"] = int(max(1, min(14, _f(raw.get("arrivalCadenceDays", 3)) or 3)))
    out["photoCap"] = int(max(1, min(PHOTOS_MAX_CEILING, _f(raw.get("photoCap", PHOTOS_MAX_DEFAULT)) or PHOTOS_MAX_DEFAULT)))
    return out


def in_arrival_window(coral: dict[str, Any], settings: dict[str, Any], now: datetime) -> bool:
    arrived = _stamp(coral.get("addedAt"))
    days = int(settings.get("arrivalDays") or 0)
    return arrived is not None and days > 0 and 0 <= _days_between(now, arrived) < days


def check_cadence(coral: dict[str, Any], settings: dict[str, Any], now: datetime) -> dict[str, Any]:
    """Days between looks, and why: the keeper's own number wins; a new
    arrival is looked at every few days for its first month; otherwise the
    group's recommendation."""
    own = _f(coral.get("checkCadenceDays"))
    if own > 0:
        return {"days": int(max(1, min(365, own))), "reason": "own"}
    if in_arrival_window(coral, settings, now):
        return {"days": int(settings["arrivalCadenceDays"]), "reason": "arrival"}
    return {"days": int(GROUPS[group_id(coral)]["checkDays"]), "reason": "group"}


def feed_cadence(coral: dict[str, Any]) -> dict[str, Any]:
    """Days between target feeds; 0 = no reminder. ``feedCadenceDays`` null
    means the group's number, 0 means the keeper switched it off."""
    raw = coral.get("feedCadenceDays")
    if raw is not None and raw != "":
        days = _f(raw)
        return {"days": int(max(0, min(365, days))), "reason": "own"}
    return {"days": int(GROUPS[group_id(coral)]["feedDays"]), "reason": "group"}


def _grade(score: float | None) -> str:
    if score is None:
        return "—"
    for floor, letter in GRADES:
        if score >= floor:
            return letter
    return "E"


def score_checkin(row: dict[str, Any], baseline: dict[str, Any] | None, group: str) -> dict[str, Any]:
    """One look, scored: losses and caps in Reef Health's grammar, each
    naming the signal that caused it. Returns {score, losses, caps, insights}."""
    baseline = baseline if isinstance(baseline, dict) else {}
    losses: list[dict[str, Any]] = []
    caps: list[dict[str, Any]] = []

    def loss(pts: int, label: str, status: str = "warning") -> None:
        losses.append({"points": int(pts), "label": label, "status": status})

    def cap(limit: int, label: str) -> None:
        caps.append({"limit": int(limit), "label": label, "status": "critical"})

    ext = row.get("extension")
    if isinstance(ext, int) and ext in SCORE_LOSS["extension"]:
        loss(SCORE_LOSS["extension"][ext], EXTENSION_WORDS[ext].capitalize(), "critical" if ext == 0 else "warning")
    tissue = str(row.get("tissue") or "intact")
    if tissue in SCORE_LOSS["tissue"]:
        loss(SCORE_LOSS["tissue"][tissue], TISSUE_WORDS[tissue].capitalize(), "critical" if tissue != "stalled" else "warning")
    if tissue in ("receding", "stn", "rtn"):
        cap(SCORE_CAP[tissue], f"{TISSUE_WORDS[tissue].capitalize()} — the score cannot read above {SCORE_CAP[tissue]} until the edge stops")
    colour = row.get("colour")
    if isinstance(colour, int) and COLOUR_MIN <= colour <= COLOUR_MAX:
        base = baseline.get("colour")
        base = int(base) if isinstance(base, int) and COLOUR_MIN <= base <= COLOUR_MAX else COLOUR_BASELINE_DEFAULT
        steps = base - colour
        if steps >= 2:
            loss(SCORE_LOSS["colour"][2], f"Colour {steps} steps paler than usual (chart {colour} vs {base})")
        elif steps == 1:
            loss(SCORE_LOSS["colour"][1], f"A step paler than usual (chart {colour} vs {base})")
        if colour <= 2:
            cap(SCORE_CAP["bleaching"], f"Chart colour {colour} — bleaching territory")
    if str(row.get("fluor") or "") == "fading":
        loss(SCORE_LOSS["fluor"]["fading"], "Fluorescence fading under the blues")
    if str(row.get("feeding") or "") == "ignored" and GROUPS[group]["feedDays"] > 0 or (group == "nps" and str(row.get("feeding") or "") == "ignored"):
        loss(SCORE_LOSS["feeding"]["ignored"], "Ignored food")
    pests = str(row.get("pests") or "none")
    if pests in SCORE_LOSS["pests"]:
        loss(SCORE_LOSS["pests"][pests], "Pests confirmed" if pests == "confirmed" else "Pests suspected",
             "critical" if pests == "confirmed" else "warning")
    if pests == "confirmed":
        cap(SCORE_CAP["pests_confirmed"], "Confirmed pests — the score cannot read above 60 until they are gone")
    neighbours = [n for n in (row.get("neighbours") or []) if n in NEIGHBOURS]
    words = {"stung": "stung by a neighbour", "shaded": "shaded by a neighbour", "nipped": "nipped by a fish"}
    for n in neighbours[:2]:
        loss(SCORE_LOSS["neighbour"], words[n].capitalize())

    score = 100 - sum(item["points"] for item in losses)
    for item in caps:
        score = min(score, item["limit"])
    score = max(0, min(100, score))
    return {"score": score, "losses": losses, "caps": caps}


def _live_rows(rows: Any) -> list[dict[str, Any]]:
    """Newest first, tombstones dropped, unparseable stamps dropped."""
    out = []
    for row in rows if isinstance(rows, list) else []:
        if not isinstance(row, dict) or row.get("undoneAt"):
            continue
        at = _stamp(row.get("at"))
        if at is None:
            continue
        out.append((at, row))
    out.sort(key=lambda pair: pair[0], reverse=True)
    return [row for _, row in out]


def coral_state(coral: dict[str, Any], checkins: Any, feeds: Any, now: datetime,
                settings: dict[str, Any] | None = None) -> dict[str, Any]:
    """Everything the card, the diagram glyph and the digest need for one
    colony: the score with its trend and grade, the status word, the
    confidence clock, the check-in and feed clocks, the insights."""
    settings = settings_view(settings)
    gid = group_id(coral)
    status = str(coral.get("status") or "active")
    live = _live_rows(checkins)
    latest = live[0] if live else None
    previous = live[1] if len(live) > 1 else None
    baseline = coral.get("baseline") if isinstance(coral.get("baseline"), dict) else {}
    cadence = check_cadence(coral, settings, now)
    insights: list[dict[str, Any]] = []

    scored = score_checkin(latest, baseline, gid) if latest else None
    score: int | None = scored["score"] if scored else None
    prev_score = score_checkin(previous, baseline, gid)["score"] if previous else None
    caps = list(scored["caps"]) if scored else []
    losses = list(scored["losses"]) if scored else []

    last_at = _stamp(latest.get("at")) if latest else None
    anchor = last_at or _stamp(coral.get("addedAt"))
    days_since = _days_between(now, last_at) if last_at else None
    next_check = (anchor + timedelta(days=cadence["days"])) if anchor else None
    check_due = bool(anchor is None or (next_check is not None and now >= next_check))
    check_overdue = bool(anchor is None or (anchor is not None and now >= anchor + timedelta(days=cadence["days"] * 2)))
    stale = bool(last_at is not None and days_since is not None and days_since >= cadence["days"] * 2)
    if stale and score is not None:
        cap_limit = SCORE_CAP["unchecked"]
        if score > cap_limit:
            caps.append({"limit": cap_limit, "label": f"Not looked at for {int(days_since)} days", "status": "warning"})
            score = cap_limit
        insights.append({"status": "warning", "label": f"Not looked at for {int(days_since)} days",
                         "detail": "The score cannot read above 70 until you check in — a colony nobody looks at cannot grade A."})
    if latest is None:
        insights.append({"status": "context", "label": "No check-in yet",
                         "detail": "Log a first look and the diary has a baseline to judge the next one against."})

    if score is None:
        word = "unchecked"
    elif score < STATUS_NEEDS_BELOW or any(c["limit"] <= 40 for c in caps):
        word = "needs"
    elif score < STATUS_WATCH_BELOW:
        word = "watch"
    else:
        word = "fine"

    trend = None
    if score is not None and prev_score is not None and not stale:
        delta = score - prev_score
        trend = {"delta": delta, "word": "up" if delta > TREND_STEADY_PTS else "down" if delta < -TREND_STEADY_PTS else "steady"}

    fcad = feed_cadence(coral)
    feed_rows = _live_rows(feeds)
    last_feed = _stamp(feed_rows[0].get("at")) if feed_rows else None
    feed_anchor = last_feed or _stamp(coral.get("addedAt"))
    feed_on = fcad["days"] > 0 and status == "active" and gid != "nps"
    next_feed = (feed_anchor + timedelta(days=fcad["days"])) if (feed_on and feed_anchor) else None
    feed_due = bool(feed_on and (feed_anchor is None or (next_feed is not None and now >= next_feed)))

    for item in losses:
        insights.append({"status": item["status"], "label": item["label"], "detail": f"−{item['points']} points at the last check-in."})
    for item in caps:
        if item["label"] not in [i["label"] for i in insights]:
            insights.append({"status": item["status"], "label": item["label"], "detail": f"Capped at {item['limit']}."})

    return {
        "group": gid,
        "groupLabel": GROUPS[gid]["label"],
        "status": status,
        "score": score,
        "grade": _grade(score),
        "word": word,
        "stale": stale,
        "trend": trend,
        "lastCheckAt": latest.get("at") if latest else None,
        "daysSinceCheck": round(days_since, 1) if days_since is not None else None,
        "checkins": len(live),
        "cadenceDays": cadence["days"],
        "cadenceReason": cadence["reason"],
        "nextCheckAt": next_check.isoformat() if next_check else None,
        "checkDue": check_due and status == "active",
        "checkOverdue": check_overdue and status == "active",
        "feedDays": fcad["days"] if feed_on else 0,
        "feedReason": fcad["reason"],
        "lastFeedAt": feed_rows[0].get("at") if feed_rows else None,
        "nextFeedAt": next_feed.isoformat() if next_feed else None,
        "feedDue": feed_due,
        "caps": caps,
        "losses": losses,
        "insights": insights,
    }


def _name(coral: dict[str, Any], cid: str) -> str:
    return str(coral.get("name") or coral.get("taxon") or cid)


def summary(livestock: dict[str, Any], now: datetime, settings: dict[str, Any] | None = None) -> dict[str, Any]:
    """The diary as one payload: every colony's state, the strip counts, and
    the due lists the digest and the Corals tab both read."""
    livestock = livestock if isinstance(livestock, dict) else {}
    corals = livestock.get("corals") if isinstance(livestock.get("corals"), dict) else {}
    checkins = livestock.get("checkins") if isinstance(livestock.get("checkins"), dict) else {}
    feeds = livestock.get("feeds") if isinstance(livestock.get("feeds"), dict) else {}
    settings = settings_view(settings if settings is not None else livestock.get("settings"))
    states: dict[str, dict[str, Any]] = {}
    counts = {"active": 0, "fine": 0, "watch": 0, "needs": 0, "unchecked": 0, "lost": 0, "gone": 0}
    due_checks: list[dict[str, Any]] = []
    due_feeds: list[dict[str, Any]] = []
    for cid, coral in corals.items():
        if not isinstance(coral, dict):
            continue
        state = coral_state(coral, checkins.get(cid), feeds.get(cid), now, settings)
        states[cid] = state
        if state["status"] != "active":
            counts["lost" if state["status"] == "lost" else "gone"] += 1
            continue
        counts["active"] += 1
        counts[state["word"]] += 1
        if state["checkDue"]:
            due_checks.append({"id": cid, "name": _name(coral, cid), "overdue": state["checkOverdue"],
                               "days": state["daysSinceCheck"]})
        if state["feedDue"]:
            due_feeds.append({"id": cid, "name": _name(coral, cid), "days": state["feedDays"]})
    due_checks.sort(key=lambda d: (not d["overdue"], -(d["days"] or 9999)))
    return {"corals": states, "counts": counts, "dueChecks": due_checks, "dueFeeds": due_feeds,
            "settings": settings}


def mouth(coral: dict[str, Any]) -> dict[str, Any]:
    """The colony's mouth in the keeper's own foods — the NPS library's rule
    (right type AND overlapping particle window), so a shelf bottle that
    'fits' here would count for this mouth there too. An NPS animal answers
    from its library entry."""
    if coral.get("npsId"):
        sp = nps_engine._SPECIES_BY_ID.get(str(coral.get("npsId")))
        if sp:
            return nps_engine.mouth_note(sp)
    g = GROUPS[group_id(coral)]
    if not g["foods"]:
        return {"fits": [], "tooBig": [], "tooFine": [], "note": ""}
    return nps_engine.mouth_note({"particleUmMin": g["particleUmMin"], "particleUmMax": g["particleUmMax"],
                                  "foods": g["foods"]})


def foods_on_shelf(coral: dict[str, Any], products: dict[str, Any]) -> list[dict[str, Any]]:
    """The shelf filtered to this mouth: right category and an overlapping
    particle window (the NPS matcher's rule). A bottle with no window set is
    judged on category alone — the honest default for a jar of pellets."""
    if coral.get("npsId"):
        sp = nps_engine._SPECIES_BY_ID.get(str(coral.get("npsId"))) or {}
        foods, lo, hi = tuple(sp.get("foods") or ()), _f(sp.get("particleUmMin")), _f(sp.get("particleUmMax"))
    else:
        g = GROUPS[group_id(coral)]
        foods, lo, hi = g["foods"], g["particleUmMin"], g["particleUmMax"]
    out = []
    for pid, product in (products or {}).items():
        if not isinstance(product, dict):
            continue
        category = str(product.get("category") or "")
        if category not in foods:
            continue
        p_lo, p_hi = _f(product.get("particleUmMin")), _f(product.get("particleUmMax"))
        fits = True
        if p_lo or p_hi:
            fits = nps_engine._ranges_overlap(p_lo, p_hi or p_lo, lo, hi or 1e9)
        out.append({"id": str(pid), "name": str(product.get("name") or pid), "category": category, "fits": fits})
    out.sort(key=lambda p: (not p["fits"], p["name"].lower()))
    return out
