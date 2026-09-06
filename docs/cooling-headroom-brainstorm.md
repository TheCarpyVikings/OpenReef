# Cooling headroom — humidity-aware fan cooling + smart dehumidifier · research & brainstorm (2026-09-03)

Reece's observation: the fans are far less effective on a humid day than on a hot dry one,
even when the room is cooler. The dehumidifier currently runs off a dumb humidistat. Wanted:
a **"fan cooling will be affected" warning** and a **dehumidifier trigger that only fires when
it will actually help**, projecting 24 h ahead from room temp, room humidity and the weather.

Research + brainstorm 2026-09-03 on 0.7.118; **Layers 1, 2 and 3 built as 0.7.119 / 0.7.120 / 0.7.121 the same day** (§9–§11). Decisions locked in §7; the window fan in §8.

---

## 1. The physics — what actually limits a fan over a reef tank

A tank fan is **not** an evaporative cooler in the HVAC sense (no wet pad, no air being cooled
for people). It is a fan blowing room air across a **warm water surface**. Three things happen:

1. **Latent cooling (the one we want).** Water evaporates off the surface, taking ~2,430 kJ per
   litre with it. Rate is proportional to the **vapour-pressure deficit (VPD)** between the
   water surface and the air, times airspeed (Engineering Toolbox: `E = (25 + 19·v) · A · (xs − x)`).
   - `xs` / `Psat(T_water)` = saturation vapour pressure **at the water temperature** (fixed, ~26 °C)
   - `x` / `P_air = RH × Psat(T_room)` = what the room air already carries
   - **VPD = Psat(T_water) − RH·Psat(T_room)**
2. **Sensible exchange (usually against us in summer).** The fan also convects heat between the
   air and the water. When room air is *warmer* than the water, this **heats** the tank. Net fan
   effect = latent − sensible.
3. **Condensation (the failure mode).** When the room's **dew point ≥ water temperature**, VPD is
   negative: nothing evaporates, moisture condenses onto the tank and the fan is purely a heater.

So the correct single number for "will the fans work" is **not room RH** and **not room
wet-bulb** (that is the floor for cooling *air*, which is the HVAC case). It is the
**dew-point margin: `T_water − T_dew(room)`**, or equivalently the VPD. This is why Reece's
cool-but-humid day loses to the hot-but-dry one — a 22 °C / 80 % room has a dew point of
18.4 °C (margin 7.6 °C on a 26 °C tank) while 28 °C / 40 % has a dew point of 13.1 °C
(margin 12.9 °C).

### 1.1 The figures (water at 26 °C)

Computed with the Magnus dew-point formula (Alduchov–Eskridge coefficients) and Stull 2011 for
wet-bulb; `Psat(26 °C) = 3.36 kPa`. Index = VPD relative to 1.85 kPa (a 28 °C / 40 % "good fan
day"), so 100 % ≈ full fan effect.

| Room °C | RH % | Dew pt °C | Margin °C | VPD kPa | Fan index |
|---|---|---|---|---|---|
| 22 | 50 | 11.1 | 14.9 | 2.04 | 110 % |
| 22 | 70 | 16.3 | 9.7 | 1.51 | 82 % |
| 22 | 80 | 18.4 | 7.6 | 1.24 | 67 % |
| 22 | 90 | 20.3 | 5.7 | 0.98 | 53 % |
| 24 | 60 | 15.8 | 10.2 | 1.57 | 85 % |
| 24 | 80 | 20.3 | 5.7 | 0.97 | 53 % |
| 26 | 50 | 14.8 | 11.2 | 1.68 | 91 % |
| 26 | 70 | 20.1 | 5.9 | 1.01 | 55 % |
| 26 | 80 | 22.3 | 3.7 | 0.67 | 36 % |
| 26 | 90 | 24.2 | 1.8 | 0.34 | 18 % |
| 28 | 40 | 13.1 | 12.9 | 1.85 | 100 % |
| 28 | 60 | 19.5 | 6.5 | 1.09 | 59 % |
| 28 | 70 | 22.0 | 4.0 | 0.71 | 39 % |
| 28 | 80 | 24.2 | 1.8 | 0.34 | 18 % |
| 28 | 90 | 26.2 | −0.2 | −0.04 | **0 — condensing** |
| 30 | 50 | 18.4 | 7.6 | 1.24 | 67 % |
| 30 | 60 | 21.4 | 4.6 | 0.81 | 44 % |
| 30 | 70 | 23.9 | 2.1 | 0.39 | 21 % |
| 30 | 80 | 26.2 | −0.2 | −0.03 | **0 — condensing, fan heats** |
| 32 | 60 | 23.3 | 2.7 | 0.51 | 27 % |
| 32 | 70 | 25.8 | 0.2 | 0.03 | **≈0** |
| 32 | 80 | 28.1 | −2.1 | −0.44 | **negative** |

**Where it dies — RH at which the room dew point reaches the water temperature:**

| Water °C | Room 26 °C | Room 28 °C | Room 30 °C | Room 32 °C |
|---|---|---|---|---|
| 25 | 94 % | 84 % | 75 % | 67 % |
| 26 | 100 % | 89 % | 79 % | 71 % |
| 27 | — | 94 % | 84 % | 75 % |

Reece's room hits 30 °C. At 30 °C the fans are at **~two-thirds strength by 50 % RH, under half
by 60 %, a fifth at 70 %, and dead at ~79 %.** That is exactly the "hot AND humid day" failure
he is seeing, and it is why a fixed 60 % humidistat is the wrong tool: at 22 °C / 60 % the fans
are still fine (index ~96 %), while at 30 °C / 60 % they are already crippled.

### 1.2 Proposed bands (dew-point margin on the tank's *target* temperature)

| Band | Margin | Index | Copy |
|---|---|---|---|
| Good | ≥ 9 °C | ≥ 70 % | "Fans have full headroom" |
| Thinning | 5–9 °C | 40–70 % | "Fan headroom thinning" |
| Weak | 2–5 °C | 15–40 % | "Fans working at a fraction — dehumidifier territory" |
| Dead | < 2 °C | < 15 % | "Evaporative cooling has stopped — fans are just moving warm air" |
| Reversed | ≤ 0 °C and room > water | ≤ 0 | "Room air is condensing on the tank — fan is heating it" |

Band edges are tunable; these fall out of the table above and match the HVAC rule of thumb
that evaporative cooling is "highly effective under 30 % RH, fine 30–50 %, marginal over 50–60 %,
useless over 70 %" once translated onto a 26 °C water surface.

### 1.3 How much heat is at stake

1 % of volume/day is a normal fan-driven evaporation rate. On a 400 L system that is 4 L/day
≈ 9,700 kJ/day ≈ **112 W of continuous cooling** — the same order as a small heater. Losing
70 % of that on a humid afternoon is losing ~80 W of cooling, which is the whole margin on a
30 °C day.

### 1.4 What the dehumidifier actually does (the honest trade)

A compressor dehumidifier is a heat pump that dumps **everything** into the room: its
electrical draw *plus* the latent heat of every gram it condenses. A 12 L/day unit at ~250 W
matching a 170 g/h tank load puts **~365 W of heat into the room air** while it runs. In a small
fish room that is +1–2 °C on the *air*. It still wins, because it removes latent load from the
**water** (the thing we care about) and only adds sensible load to the **air** (weakly coupled
to the water through glass and the surface film) — but it is not free, and it is a bad idea to
run it when it cannot change the outcome. That is the whole argument for a **projection-based
trigger** rather than a humidistat:

- Run it **ahead** of the heat (morning), when its own heat is harmless and the room is still
  dry-able, so the fans have headroom at the 2–5 pm peak.
- Don't run it at 30 °C / 80 % hoping to rescue the afternoon: pulling that room to 60 % is
  ~3 g/m³ × room volume plus the tank's ongoing load, and the unit's heat lands during the peak.
  That is a **"chiller / AC day"** warning, not a dehumidifier job.
- Don't run it at all when the fans are not needed (cool day, high RH): comfort/mould control
  can keep the dumb humidistat for that; OpenReef's trigger is specifically about **cooling**.

### 1.5 The free alternative — ventilation

If the **outdoor dew point** is lower than the indoor dew point, an extractor fan or an open
window dries the room for nothing and, if outdoor air is also cooler, cools it too. HA's weather
forecasts carry `dew_point` and `humidity` per hour (Met Office hourly does). The projection can
therefore also say *"tonight's outdoor dew point is 12 °C — vent the room instead."* Nobody in
reef-land does this; it is a genuine intelligence-layer line.

---

## 2. What OpenReef already has (the hooks)

| Need | Already exists | Where |
|---|---|---|
| Room temp + humidity sensors | `sensors.room_temp`, `sensors.humidity` (group `room`, context-only, no score impact) | [const.py:775](../custom_components/openreef/const.py#L775), [__init__.py:648](../custom_components/openreef/__init__.py#L648) |
| Tank temp + seasonal target | Stage C `execution.temp.sensorEntity`, `state["targetTempC"]` | [const.py:1553](../custom_components/openreef/const.py#L1553), [__init__.py:17600](../custom_components/openreef/__init__.py#L17600) |
| The fan as an HA switch | `execution.temp.coolEntity` (cooling's safe direction is ON) | same |
| A minutely tick with fail-safe sensor validation (stale / non-numeric / implausible / °F) | `_async_spawning_temp_reconcile` — copy the reading pattern verbatim | [__init__.py:17600](../custom_components/openreef/__init__.py#L17600) |
| Cooldown-deduped notifications | `_async_spawning_notify_once(hass, cfg, key, cooldown_s, title, msg)` | [__init__.py:17512](../custom_components/openreef/__init__.py#L17512) |
| Activity/Log tab | `_append_activity(config, message, type)` (cap 200) | [__init__.py:5859](../custom_components/openreef/__init__.py#L5859) |
| Reef Pulse insight rotator | `_pulseInsightCurrent()` + `push(key, kicker, title, detail, status)` | [openreef-panel.js:16938](../custom_components/openreef/frontend/openreef-panel.js#L16938) |
| Recorder / statistics reads (for learning offsets) | `history/history_during_period`, `recorder/statistics_during_period` (panel side today) | [openreef-panel.js:981](../custom_components/openreef/frontend/openreef-panel.js#L981) |
| Rig knowledge | ESP32 node carries tank temp, room temp, humidity, CO₂; Inkbird is the guard; fan on its own plug | [spawning-smartplug-brainstorm.md §5 addendum](spawning-smartplug-brainstorm.md) |
| The idea itself | "cooling headroom … *Room 30.1°, humidity 78 % — fan headroom thin today*" | same addendum, promised as a Stage C / Pulse nicety |

Weather: **nothing** in OpenReef reads an HA `weather.*` entity yet. HA's API is
`weather.get_forecasts` with `type: hourly`, called from Python as
`hass.services.async_call("weather", "get_forecasts", {"type": "hourly"}, target={"entity_id": …}, blocking=True, return_response=True)`.
Hourly entries carry `datetime`, `temperature`, `humidity`, `dew_point` (fields an integration
does not supply are omitted — must be tolerated).

---

## 3. Feature shape — "Cooling headroom"

Working name **Cooling headroom** (already coined in the spawning addendum). Three layers, each
useful on its own:

### Layer 1 — Live index + warning (no weather needed)

Every tick (piggyback the 60 s spawning tick, or its own 5-min tick):

```
T_water  = tank temp reading (fallback: Stage C targetTempC, fallback: 25.5)
T_room, RH = room sensors (same stale/implausible validation as Stage C, fail → "unknown", never alert)
T_dew    = magnus(T_room, RH)
margin   = T_water − T_dew
vpd      = psat(T_water) − RH/100 · psat(T_room)
index    = clamp(vpd / 1.85 kPa, 0, 1)         # 1.85 = 28 °C / 40 % reference
band     = good | thinning | weak | dead | reversed
netFan   = "cooling" | "marginal" | "heating"    # reversed → heating
```

Surfaces:
- **Overview**: the Humidity context card grows a second line — *"Fan headroom 38 % · dew point
  23.9 °C vs tank 26.0 °C"*. Humidity stays `affectsScore: false`; headroom is a derived chip.
- **Living tank diagram**: a chip on the fan (the wavemaker/AWC chip pattern) — colour by band.
- **Reef Pulse insight**: `push("cooling", "Cooling headroom", "Fan headroom thinning", "Room 30.1° / 78 % — dew point 25.9°, tank 26.0°", "warning")`.
- **Notification** (cooldown 6 h, only when the fan is actually needed — see gate below):
  *"Evaporative cooling is failing — Room 30 °C at 80 %: the room's dew point (26.2 °C) is above
  the tank (26.0 °C). The fans are now warming the water. Dehumidify, vent the room, or plan for a
  chiller."* Plain voice — this is a warning, not a calm state (personality doctrine).

**The gate that makes it not-annoying**: warn only when cooling is *needed* — fan entity ON,
or `T_room ≥ T_target − 1`, or tank above target. High humidity on a cool day is silent.

### Layer 2 — 24 h projection (weather-aware) + dehumidifier trigger

Inputs: HA `weather.*` entity (hourly forecast), refreshed hourly, cached in runtime.

Model, deliberately simple and learnable:

```
offsetT(h)   = mean over last 7 days of (T_room − T_outdoor) at hour-of-day h     # learned from recorder
offsetDew(h) = mean over last 7 days of (T_dew_room − T_dew_outdoor) at hour-of-day h
v1 fallback  = single scalar offsets from the current reading vs the current forecast hour

for each forecast hour h in next 24:
    T_room'(h) = T_out(h) + offsetT(h)
    T_dew'(h)  = T_dewOut(h) + offsetDew(h)      # indoor dew tracks outdoor dew + tank load
    margin'(h) = T_target − T_dew'(h)
    fanNeeded(h) = T_room'(h) ≥ T_target − 1     # matches "fan runs whenever ambient ≥ RT"
    index'(h)  = as Layer 1
worst = min index' over hours where fanNeeded
```

Decision (the trigger):

```
shouldDehumidify =
    any hour h ≤ lookahead with fanNeeded(h) and index'(h) < weakThreshold      # cooling will be affected
    and not (T_room'(h) ≥ T_target + 4 and index'(h) < 0.1)                     # unrescuable → "chiller day" warning instead
    and now ≥ (first such hour − leadHours)                                     # start ahead of it
    and dehumidifier not in short-cycle guard
leadHours = learned pull-down rate (RH %/h while the unit ran, from recorder) → default 3 h
stopWhen  = index (live) ≥ goodThreshold for 30 min, or no fanNeeded hour left in lookahead
```

Two modes, exactly like AWC/spawning went: **Advise** (default — Pulse card + notification:
*"Fan headroom will drop to 20 % from 2 pm. Start the dehumidifier by 11 am."*) and **Auto**
(switch entity, armed flag, hold-style override policy). Advise ships first; auto follows the
locked-decision rhythm.

Dehumidifier guards (it is a compressor):
- `minOnMinutes` 20 / `minOffMinutes` 10 short-cycle guard.
- Optional `bucketFullEntity` (binary_sensor) → don't start, notify once.
- The unit's own humidistat must be set *below* our band (or "continuous"), otherwise it will
  refuse to run when we ask — surfaced in the setup checklist, like the Inkbird ack.
- **Never a safety channel.** The fan / Inkbird stay the backstop; the dehumidifier is
  efficiency. If OpenReef dies, nothing gets worse than today.
- Failure direction: OFF (a dehumidifier stuck on is only a bill and a warmer room; stuck off
  is today's status quo).

### Layer 3 — Ventilation advice + "what kind of day is it"

From the same forecast:
- If `T_dewOut(h) ≤ T_dew_room − 3` for a stretch of hours → *"Vent, don't dehumidify: outdoor
  dew point 12 °C tonight."* If `ventEntity` (extractor) is bound, Auto mode can prefer it.
- Day classification for the Pulse morning card: **Dry-heat day** (fans will cope), **Humid-heat
  day** (dehumidifier from HH:MM), **Chiller day** (neither will hold it — pre-warn so Reece can
  drop room load / open up early), **Quiet day**.

This is the piece nobody else has: Apex/Fusion runs a fan on a temperature threshold and has no
idea what humidity will do to it. "OpenReef knows your fans will fail before they do" is a
defensible line, alongside the NPS/AWC firsts — verify the claim the way NPS was before using it.

---

## 4. Config sketch

```python
"coolingHeadroom": {
    "enabled": False,
    "waterTempEntity": "",        # default: inherit sensors.temp, then Stage C sensorEntity
    "targetTempC": None,          # default: inherit Stage C state targetTempC, else 25.5
    "roomTempEntity": "",         # default: inherit sensors.room_temp
    "humidityEntity": "",         # default: inherit sensors.humidity
    "fanEntity": "",              # default: inherit execution.temp.coolEntity (read-only here)
    "weatherEntity": "",          # weather.* — optional; Layer 2/3 switch off without it
    "referenceVpdKpa": 1.85,
    "bands": {"good": 0.70, "thin": 0.40, "weak": 0.15},
    "lookaheadHours": 24,
    "dehumidifier": {
        "mode": "advise",         # off | advise | auto
        "armed": False,
        "switchEntity": "",
        "bucketFullEntity": "",
        "leadHours": 0,           # 0 = learned, fallback 3
        "minOnMinutes": 20,
        "minOffMinutes": 10,
        "overridePolicy": "hold",
    },
    "ventEntity": "",             # optional extractor (Layer 3)
}
```

Runtime (server-written, so it **must** join the stale-save merge guards):

```python
runtime["coolingHeadroom"] = {
    "at": iso, "waterC": 26.0, "roomC": 30.1, "rh": 78, "dewC": 25.9,
    "marginC": 0.1, "vpdKpa": 0.05, "index": 0.03, "band": "dead", "netFan": "heating",
    "fanNeeded": True,
    "forecast": [{"at": iso, "roomC": .., "dewC": .., "index": .., "fanNeeded": ..}] * 24,
    "worst": {"at": iso, "index": 0.2}, "dayKind": "humid-heat",
    "dehumidifier": {"shouldRun": True, "since": iso, "reason": "…", "until": iso, "state": "on"},
    "vent": {"advised": False, "outdoorDewC": 18.2},
    "learned": {"offsetT": [..24], "offsetDew": [..24], "pullDownRhPerHour": 4.5},
    "issues": {},
}
```

WS: `openreef/cooling/state`, `openreef/cooling/save`, `openreef/cooling/simulate`
(what-if: pick room temp / RH / target and see index + band — same "live what-if row" idea as
the mixing dose guide), `openreef/cooling/dehumidifier` (run now / stop / hold).

Backend owns every number (evaluator LOCKSTEP lesson from maintenance: the panel renders, it
never recomputes the index). Psychrometrics live in a small pure module `cooling.py` so the
tests can hit them with known values (Stull's published examples; the table above).

Tests (fake HA, `tests/test_cooling.py`, runner LAST — count `ok` vs tests):
psychrometric known values · band edges · gate (humid cool day is silent) · projection with a
forecast fixture (hours missing `dew_point`, °F units, unavailable weather → Layer 1 only) ·
short-cycle guard · bucket-full · Advise never switches · Auto disarmed never switches · lead-time
learning with no history → default 3 h · stale-save merge keeps runtime.

---

## 5. Sources

- Stull, R. (2011) *Wet-Bulb Temperature from Relative Humidity and Air Temperature*, J. Appl. Meteor. Climatol. 50(11) — https://journals.ametsoc.org/view/journals/apme/50/11/jamc-d-11-0143.1.xml (formula valid 5–99 % RH, −20–50 °C, MAE < 0.3 °C)
- UGA Poultry Ventilation, *Wet Bulb Temperature and Evaporative Cooling* — https://www.poultryventilation.com/resources/wet-bulb-temperature-and-evaporative-cooling/ (pads reach 70–75 % of wet-bulb depression; RH rises ~2.5 % per °F of cooling)
- PickHVAC evaporative cooler chart (cooled-air temperature vs RH, "N/A" above ~60–70 % at high temps) — https://www.pickhvac.com/portable-air-conditioner/evaporative-cooler/humidity-chart/
- Evapolar, *Evaporative Cooling and Humidity* — https://evapolar.com/blogs/blog/evaporative-cooling-and-humidity-what-you-need-to-know (highly effective < 30 %, effective 30–50 %, refrigerative above 50 %, ineffective > 70 %)
- NSW DPI, *Evaporative cooling in greenhouses* — https://www.dpird.nsw.gov.au/agriculture/horticulture/greenhouse/structures-and-technology/evap-cooling (most effective below 60 % RH; site blocks fetch)
- Engineering Toolbox, *Evaporation from a Water Surface* — https://www.engineeringtoolbox.com/evaporation-water-surface-d_690.html (`E = (25 + 19 v) A (xs − x)`)
- Reef Builders, *How to Control Reef Tank Temperature and Excess Humidity* — https://reefbuilders.com/2023/08/26/how-to-control-reef-tank-temperature-and-excess-humidity/ (hobby rule: dehumidifier at ≥ 60 % RH; fans raise house humidity)
- Reef2Reef, *Does ambient air temperature affect cooling fan efficiency?* — https://www.reef2reef.com/threads/does-ambient-air-temperature-affect-cooling-fan-efficiency.928038/ (airflow + humidity dominate; wet-bulb is the floor)
- Melev's Reef, *Cooling with fans* — https://melevsreef.com/articles/cooling-fans
- Home Assistant, `weather.get_forecasts` — https://www.home-assistant.io/actions/weather.get_forecasts/ and Weather entity dev docs — https://developers.home-assistant.io/docs/core/entity/weather/ (hourly `temperature`, `humidity`, `dew_point`)
- Home Assistant Met Office integration (UK hourly) — https://www.home-assistant.io/integrations/metoffice/
- Dew point: Magnus formula, Alduchov & Eskridge (1996) coefficients (a = 17.625, b = 243.04 °C); table in §1.1 computed from it.

---

## 6. The grill — questions for Reece before anything is built

1. **Dehumidifier control path** — smart plug on a dumb unit, or an HA-integrated unit (Meaco /
   Midea / Tuya) with its own humidistat and a bucket-full sensor? Plug → unit must sit in
   "continuous" or with its humidistat set well below our band.
2. **Where is the humidity sensor?** ESP32 node near the sump/cabinet reads higher than the room
   the fans draw from. Room-level placement (or a second sensor) matters more here than anywhere.
3. **Weather entity** — is Met Office (hourly, with humidity) already in HA? Any `weather.*`
   with hourly forecasts will do; without one, Layer 1 still ships.
4. **Which fan entity is the truth** — the Stage C `coolEntity` plug, or is the workhorse fan
   still on the Inkbird cool socket today?
5. **Ventilation** — is there an extractor or a window that can realistically be used (manual
   advice vs a `ventEntity`)?
6. **Tank target** — inherit the Stage C seasonal target, or a fixed number (25.5?) for now?
7. **First ship** — Layer 1 (index + warning + Pulse card, ~a day) then Layer 2 in Advise mode,
   Auto last. Agree?

---

## 7. Decisions — LOCKED 2026-09-03 (Reece's answers to §6)

| # | Question | Answer | What it changes |
|---|---|---|---|
| 1 | Dehumidifier control | **Smart plug on a dumb unit with its own humidistat** | Layer 2 drives the plug; the unit's humidistat must sit at its lowest / "continuous" so the plug decides, not the dial. Setup checklist item, like the Inkbird ack. No bucket-full sensor unless the unit exposes one. |
| 2 | Humidity sensor placement | **High up, away from the tank** | Room-representative — the right place. Warm air rises, so it reads slightly warmer/drier than the fan's intake; no correction needed for a band-based index. |
| 3 | Weather entity | **Unsure** | Layer 1 needs none. Layer 2's settings picker will list any `weather.*`; the Met Office integration (free key, hourly with humidity) is the UK answer. |
| 4 | Fan entity | **Inkbird cool socket — stays** | No fan state in HA, so "cooling needed" is inferred: room ≥ target − gate, or tank over target (`fanGateC`). |
| 5 | Ventilation | **Manual window (a couple of inches) + a powerful circulating fan in front of it pulling fresh air in; exhaust through another window** | This is the Layer 3 actuator — see §8. |
| 6 | Tank target | **Both, user-configurable** | `targetMode: fixed | spawning` — fixed number, or follow the seasonal spawning target when the program is on. |
| 7 | Ship order | **Layer 1 first** | Shipped 0.7.119. Layer 2 (forecast + dehumidifier, Advise then Auto) next; Layer 3 (vent) rides on the same forecast. |

## 8. The window fan — thoughts and improvements

Reece's intake fan is, physically, the best tool on the bench. Pulling outdoor air through the
room and out of a second window is **free dehumidification whenever the outdoor dew point is
below the indoor one, and free cooling whenever outdoor air is cooler than the room** — and in
a UK summer both are true far more often than not. Typical UK summer outdoor dew points sit at
10–16 °C; a fish room at 30 °C / 70 % has a dew point of 24 °C. That is a 8–14 °C dew-point gap
the intake fan can cash in, which the dehumidifier would need hundreds of watts to match.

What can go wrong, and what to build:

1. **It can make things worse.** On a muggy evening (outdoor dew point 19 °C, thunderstorm air),
   pulling that in *raises* the indoor dew point. The rule is simple and the forecast gives it:
   **vent only while `T_dew(outdoor) ≤ T_dew(indoor) − 2 °C`**; otherwise close up and let the
   dehumidifier work. Layer 2/3 should own this switch, not a schedule.
2. **Put the intake fan on a smart plug** → `ventEntity`. Auto rule: vent when the dew-point
   gap holds *and* outdoor ≤ room + 1 °C; dehumidify when it doesn't; **never both** — running a
   dehumidifier while blowing the dried air out of the window is pure waste. That mutual
   exclusion is the single most valuable line of Layer 3.
3. **A window contact sensor** (Zigbee, ~£8) on the intake window, ideally the exhaust window
   too. Auto can then refuse to run the intake fan against a closed window, and the panel can
   say "vent advised — window closed". Without one, Layer 3 stays Advise-only, which is fine.
4. **Night purge** — the biggest free win. Before a forecast hot day, run the intake fan from
   ~23:00 to ~07:00 while outdoor air is at its coolest and driest. The room's walls, floor and
   water absorb the cool, and the afternoon starts from a lower base. Layer 2's forecast already
   knows tomorrow's peak; scheduling the purge is a small addition.
5. **Exhaust high, intake low.** Hot humid air collects at the ceiling; the exhaust window is
   best the higher one. Reece's humidity sensor being high up is also where the exhaust air is
   — it will read the worst air in the room, which is the honest number to act on.
6. **Hygiene.** Mesh on the intake (insects, pollen in season); rain means close up. Salt creep
   is not an issue for an intake fan (it moves outdoor air), unlike the tank fans.
7. **An outdoor temperature/humidity sensor** (~£10 Zigbee) sat in the shade outside the
   intake window turns the forecast into actuals and calibrates it — cheap and worth it if
   Layer 3 goes Auto.
8. **Winter.** The same fan is a heat loss in winter; the dew-point rule naturally stops
   running it (outdoor cold air is dry, but the room does not need cooling — the gate says no).

Priority order when Layer 2/3 run Auto: **intake fan** (free) → **dehumidifier** (costs ~365 W of
room heat) → **"chiller day" warning** (neither will hold it).

## 9. Layer 1 — shipped as 0.7.119 (2026-09-03)

Built exactly as §3 Layer 1, plus the locked decisions:

- `custom_components/openreef/cooling.py` — pure psychrometrics: Magnus dew point, Stull
  wet-bulb, VPD, index (reference 1.85 kPa), bands, `fan_needed` gate, what-if grid, warning copy.
- `coolingHeadroom` config block (const + normaliser): enabled, entity overrides (blank = the
  mapped room/humidity/tank sensors; no tank probe = the target is the water), `targetMode`
  fixed/spawning, `targetTempC`, `fanGateC`, `referenceVpdKpa`, `bands`, `notify`.
- Five-minute tick: snapshot in `hass.data` only (no server-written config fields → **no
  merge guard needed**); warns once per band per six hours *only while cooling is needed*; a
  worsening band escalates; transitions in and out of trouble land in the Log tab.
- WS `openreef/cooling_status` (the snapshot) and `openreef/cooling_simulate` (what-if).
- Panel: Overview row under Core Sensors, Reef Pulse insight card, Settings → Cooling headroom
  (bindings, target, gate, notify, live readout with issues, and the what-if grid for today's tank).
- Tests: `tests/test_cooling.py` (21) and `tests/test_panel_cooling.mjs` (9).

Not in Layer 1 by design: no actuator is touched, no weather, no dehumidifier, no diagram chip
(the fan is not an HA entity on this rig). Next: Layer 2.

## 10. Layer 2 — shipped as 0.7.120 (2026-09-03)

Reece confirmed Layer 1 live (room 26.8 °C at 57 %, tank 24.9 °C → dew point 17.7 °C, 60 % fan
effect) and that HA has `weather.home` (the built-in Met.no forecast: hourly, with temperature
and humidity). That entity is fine — Met Office would only be marginally more local.

**Projection** (`cooling.parse_forecast` / `project`): `weather.get_forecasts` hourly, read every
30 min and cached in the runtime. Each hour indoors = outdoor + a learned offset (room °C and
dew point °C separately), the offsets being an EMA of the live indoor-minus-outdoor difference
(defaults +2 / +3 until both sides read; clamped −3…+12). Each projected hour runs the same
`evaluate()` as the live reading, plus the fan-needed gate. Out of that: the worst needed hour,
the first/last **affected** hour (needed AND weak/dead/reversed), the **day kind** (quiet /
dry-heat / humid-heat / chiller — chiller when any affected hour is ≥ 4 °C over target with an
index under 10 %), and the **night-purge window** (the coolest outdoor hours) for the intake fan.

**Vent advice** (`vent_advice`, live only): outdoor dew point ≥ 2 °C below indoors and outdoor
no warmer than room + 1 → "vent (intake fan + window) instead of dehumidifying". Advice only in
this release; the `ventEntity` actuator is Layer 3.

**Plan** (`dehumidifier_plan`, stateless): *now* (live needed and losing) · *unrescuable* (live
losing but ≥ 4 °C over target at < 10 % — chiller day, don't start: its heat lands in the peak) ·
*ahead* (inside `leadHours` of the first affected hour, until an hour after the last) ·
*scheduled* (a hit is coming, not yet time) · *none*.

**Dehumidifier modes**: `off` · `advise` (default — a notification when a plan becomes active,
the scheduled one logged only; vent advice appended when it applies; a band warning that lands
in the same tick folds into the one message) · `auto` (armed + a switch entity): the tick holds
the plug to the plan with compressor guards (`minOnMinutes` 20, `minOffMinutes` 10, `maxRunHours`
8 then off + a "check the bucket" nudge), a manual-override hold (hand on the plug → held until
the plan flips; `reassert` policy available), unavailable-plug alert, and **leaving auto fails
OFF** once. Manual Run / Stop / "give it back to the plan" from Settings via
`openreef/cooling_dehumidifier`. Runtime stays in `hass.data`; the tick's own save no longer
re-enters the tick (the scheduler only runs an immediate read on first enable).

**Panel**: the 24 h strip (one cell per hour, coloured by band, greyed when the fans aren't
needed, marked when affected), the day-kind line, vent and plan lines, the dehumidifier row
with state + controls; the Overview row and Pulse card carry the plan ("Humid-heat day —
dehumidifier by 11:00", "Dehumidify now", "Vent the room now", "Chiller day").

Tests: `tests/test_cooling.py` 36, `tests/test_panel_cooling.mjs` 14.

**Setup for Reece**: Settings → Cooling headroom → weather entity `weather.home`; dehumidifier
plug on the smart plug with the unit's humidistat at its lowest / continuous; leave Advise for a
few days and compare the notifications with what the room does, then Auto + armed.

Next (Layer 3): `ventEntity` for the intake fan on a plug with the dew-point rule, mutual
exclusion with the dehumidifier, a window contact sensor, and the night-purge schedule.

## 11. Layer 3 — shipped as 0.7.121 (2026-09-03)

The intake fan (§8) as an actuator, on the same plug-reconcile the dehumidifier uses.

**Vent rule** (`cooling.vent_decision`): only while outdoor air is drier by `dewGapC` (default
2 °C) and no warmer than room + 1, and only for a reason —

| kind | when | copy |
|---|---|---|
| `cool` | the room needs cooling now (fan gate) | "the room needs cooling and outdoor air is drier (…)" |
| `predry` | not needed yet, but a losing hour is in the lookahead | "pre-drying the room with outdoor air — headroom drops to X % from HH:MM" |
| `purge` | `nightPurge` on, the lookahead is not a quiet day, now is inside the coolest-hours window | "night purge — the coolest outdoor air (X °C) until HH:MM, ahead of a … day" |
| `blocked` | any of the above, but a bound window sensor reads closed | "… — but the window is closed" |
| `none` | outdoor air wetter / warmer, or no reason | the vent-advice reason ("keep the windows shut") |

Winter needs no special case: a cool room with nothing coming has no reason.

**Mutual exclusion**: the room counts as *vented* when OpenReef is running the intake fan, or a
bound window sensor reads open while venting is advised (the keeper is venting by hand). A
vented room turns the dehumidifier plan into `vented` — off, "drying air you blow out of the
window is waste". The tick reconciles the fan first, then re-derives the plan, then the
dehumidifier. No window sensor + auto → assumes the window is left ajar (Reece's habit; §7).

**Config** `coolingHeadroom.vent`: `mode` off/advise/auto (default advise), `armed`,
`switchEntity`, `windowEntity` (binary_sensor, on = open), `dewGapC`, `nightPurge`,
`minOnMinutes`/`minOffMinutes` (10/10 — a fan, not a compressor; no max-run cap),
`overridePolicy`. Advise: one notification per kind change ("Vent the room", "Intake fan
running", "Open the window — venting would help"); the Log records every change, including
"close up" when the outdoor air turns wet. WS `openreef/cooling_vent` run/stop/resume; the
dehumidifier and vent share one manual handler and one reconcile (`_COOLING_ROLES`).

**Panel**: Settings → Cooling headroom → *Intake fan (vent)* block (mode, plug, window sensor,
gap, min on/off, override, night purge, armed) with the fan row, window state and controls;
the Overview row and Pulse card put the vent verdict first ("Vent the room now", "Venting the
room", "Night purge running", "Open the window — venting would help"), then the dehumidifier.

Tests: `tests/test_cooling.py` 45, `tests/test_panel_cooling.mjs` 18.

**Setup for Reece**: put the circulating fan on a smart plug and bind it; optional £8 Zigbee
contact on the intake window; leave Advise on with the dehumidifier for a few days, then arm
both. Watch for the muggy-evening "close up" line — that is the case a humidistat gets wrong.

Later candidates: an outdoor temp/humidity sensor to replace the forecast for the live vent
rule; a chip on the diagram once the fans are HA entities. Per-hour learned offsets: §12.

## 12. Learned per-hour offsets — shipped as 0.7.122 (2026-09-03)

The projection's indoor-minus-outdoor offsets were one smoothed pair for the whole day. A tank
room is not that: it lags the street in the morning, overshoots it at 4 pm with the lights on,
and holds its humidity overnight. So the offsets are now learned **per hour of day**.

**Why OpenReef's own readings rather than recorder history.** The outdoor side (the weather
entity's temperature/humidity) is not in long-term statistics, and pulling seven days of raw
state history for three entities through the recorder on every reschedule is heavy for a
marginal gain. Reece's call: collect from now. The tick already sees both sides every five
minutes; that is the ledger.

**Maths** (`cooling.learn_slot`): 24 slots, each a capped-count running mean of (room − outdoor)
and (indoor dew − outdoor dew): a plain mean while the count grows, then an EMA with weight
1/84 — at 12 ticks an hour that is roughly a seven-day memory, so a heatwave week reshapes the
slot without one odd afternoon doing so. A slot is **trusted at 6 samples** (half an hour);
`project()` uses the slot for each forecast hour's local hour of day when trusted and the live
smoothed pair otherwise, and reports how many hours were learned. Deltas are clamped to the
same −3…+12 °C range as the live offsets.

**Persistence**: `<config>/openreef_cooling_learning.json`, loaded once per schedule, written
atomically at most every 30 min while dirty and flushed on unload. Never a config field, so no
stale-save guard. A missing or corrupt file is an empty ledger.

**Panel**: a line under the forecast strip — "Per-hour offsets learned for 14 of 24 hours from
3.1 days of readings since …" — plus **Forget learned offsets** (WS `openreef/cooling_learning`
reset; the sensor moved, the room changed). The strip's hint says on how many of the projected
hours the learned slots were used.

Tests: `tests/test_cooling.py` 50, `tests/test_panel_cooling.mjs` 19.

### 12.1 First live forecast (0.7.123, 2026-09-03)

Reece's first strip: a flat 19–21 °C night, a mild tomorrow, dry-heat day, no plan — all
correct — but the night-purge window read "21:00–18:00": every hour was within 2 °C of the
coolest, and the window took the first and last of them. It is now a contiguous run around the
coolest hour, growing toward the cooler neighbour, capped at 8 h (`PURGE_BAND_C`,
`PURGE_MAX_HOURS`). The strip's header also says "next 24 h" (the configured lookahead) rather
than counting the extra past hour.

### 12.2 Startup (0.7.124, 2026-09-03)

After every update the strip showed "waiting for the first forecast read" for a while: the
first tick ran inside setup while HA was still booting, and a blocking `get_forecasts` there
either stalls OpenReef's setup or comes back empty. The first read now waits for the
`homeassistant_started` event when HA is not yet running (the listener's unsub sits in the tick
slot, so a clear cancels it); the five-minute cadence arms after that first read.

---

## 13. Deadbands and the second reason to vent (spec, 2026-09-06)

### 13.1 What 0.7.143/0.7.144 already fixed

Reece's intake fan was switching on and off all afternoon. His activity log for one half hour,
with the outdoor dew point pinned at 10.8–11.3 °C the whole time:

| 13:00 | 13:07 | 13:15 | 13:20 | 13:25 | 13:30 |
|---|---|---|---|---|---|
| gap 3.0 → vent | under → close up | gap 2.1 → vent | under → close up | gap 2.0 → vent | under → close up |

Six decision flips in thirty minutes. Outdoor never moved; the *indoor* dew point was
straddling the 2.0 °C bar. Two of the six reached the plug; `minOn`/`minOff` absorbed the rest.

Every Layer 3 gate was bang-bang against a live sensor, and each one switches on the thing that
erases its own reason: the fan pulls drier air in → indoor dew falls toward outdoor → the gap
closes → the fan stops → the room re-humidifies → it starts again. The 13:00→13:07 leg is that
loop caught red-handed: a full 1 °C of indoor dew point removed in seven minutes, by the fan,
which then switched itself off for it.

`minOn`/`minOff` are in the *time* domain: they floor the cycle **length**, they cannot stop the
decision flapping. So each gate got a deadband on its **stop side only** — a start is never made
easier (0.7.143):

| gate | start | hold until |
|---|---|---|
| dew gap | `gap ≥ dewGapC` | `gap < dewGapC − 0.5` |
| outdoor temp | `out ≤ room + 1.0` | `out > room + 1.5` |
| room/target | `room ≥ target − fanGateC` | `room < target − fanGateC − 0.3` |

The first two key off **observed** state (the plug reads on, or a bound window reads open),
never off the advice they feed, or it is circular. The third needs memory, so `fan_needed`
latches through `runtime["fanNeededLatch"]`. The latch is the **room arm's alone**: the tank arm
already stands 0.2 °C clear of target and water is far too slow to chatter — widening it parks a
tank sitting *on* target, a well-controlled one, at "needs cooling" forever. `project()` stays
unlatched; each forecast hour is an independent hypothetical.

0.7.144: the panel read "Intake fan: **off** — outdoor air is as wet as indoors" with the plug
pill beside it reading **ON**, and nothing explaining it. That was `minOn` legitimately holding a
run. Worse, the copy for the *other* reason a plug may disagree — "held on by hand since HH:MM"
plus a **Give it back to the plan** button — could never render, because `_cooling_actuator_state`
had never published `override`. A manual **Run now** in auto mode therefore pinned the plug until
the plan happened to flip, invisibly, with the release button hidden behind the missing field.
Both `override` and `hold` (the short-cycle countdown) now ship in the snapshot.

Also: `vent_advice`'s "close up" copy printed the outdoor dew point but **not the gap** — you
could see the number when the fan ran and never when it stopped, which is why this needed a log
to diagnose at all. All three branches now name the gap and the bar they missed.

### 13.2 The gap that is left — venting has two benefits, we model one

Reece's panel, 2026-09-06: outdoor **24.3 °C at 43 %** (dew 10.8 °C), room **4.1 °C hotter**,
dew gap **1.4 °C**. Verdict: *"keep the windows shut."* That is 24 °C air being refused by a
28 °C room. Nobody would agree with it standing in the doorway.

It happens because `vent_advice` gates almost entirely on the dew gap, and treats temperature
only as a *guard* (`out ≤ room + 1`), never as a *reason*. But a reef room loses heat to
ventilation by two independent paths:

1. **Evaporative** — the tank's fans need `e_s(T_water) − e_a(room)`. Lowering indoor dew raises
   it. This is what `dewGapC` buys, and §1 is right about it.
2. **Sensible** — a 24.3 °C room simply conducts less heat into a 26 °C tank than a 28.4 °C room
   does, and below the target it removes heat outright. Nothing about the dew point is involved.

Path 2 is entirely absent from the vent rule. Note it is *not* redundant with path 1: room
temperature does not appear in the index at all. `evaluate` computes
`vpd = e_s(water) − rh/100 · e_s(room)`, and `rh/100 · e_s(room)` **is** `e_a` = `e_s(T_dew)`;
the room term cancels. Room temperature enters only the `reversed`/`dead` split and the `net`
direction. So cooling the room at constant dew point changes the headroom index by nothing —
and yet it is obviously worth doing, because `fan_needed` itself is a *room temperature* test.
The feature already believes room temperature matters. It just never lets that belief reach the
vent decision.

### 13.3 The rule — a new `freecool` kind

Named `freecool`, not `chill`: `chiller` is already a day kind and a real piece of reef kit.

Run the intake fan when **all** of:

- `fan_needed` — cooling is on the table (unchanged; the latch of §13.1 applies)
- `room − out ≥ coolGapC` — outdoor is materially cooler (default **2.0 °C**)
- `gap ≥ 0` — outdoor dew is **no higher** than indoor

The third condition is the whole safety of it. We are not claiming a drying benefit, so we do
not demand `dewGapC`; but we must not *import* moisture to buy temperature, because moisture
costs evaporative headroom directly and that is the expensive currency. Dew-neutral, temperature
positive: unambiguously a win, no trade to adjudicate.

**Why not weigh the trade when outdoor is cooler but wetter?** Converting the two paths to a
common currency needs the room's thermal coupling to the tank — how many watts per °C of room
excess actually reach the water. OpenReef does not know that and cannot learn it from what it
records. So refuse the trade rather than guess at it. If that is ever wanted, it needs a
measured coupling constant first, not a fudge factor.

### 13.4 Deadbands (mandatory, not optional)

`freecool` is self-defeating in exactly the way §13.1 describes — venting cool air cools the
room, which shrinks `room − out`, which stops the vent. Shipping it without deadbands would
reintroduce the bug we just fixed, in a new place:

| gate | start | hold until |
|---|---|---|
| cool gap | `room − out ≥ coolGapC` | `room − out < coolGapC − 0.5` |
| dew neutral | `gap ≥ 0` | `gap < −0.3` |

Same discipline: stop side only, keyed off observed venting state, never off the advice.

The equilibrium is self-limiting and worth stating: the fan runs until the room is within
`coolGapC − 0.5` of outdoor, or until `fan_needed` releases (room below `target − fanGateC −
0.3`). Both are natural stops that already exist. On Reece's numbers — room 4.1 °C over, gap 1.4
— it would start now, run, and stop when the room is 1.5 °C over outdoor or comfortably under
target, whichever comes first.

### 13.5 Priority

`cool` → `freecool` → `predry` → `purge`.

`cool` is the stronger claim (drier **and** needed now) and keeps its copy. `freecool` is the
weaker present-tense claim, so it sits directly behind it and ahead of `predry`, which is about a
*future* losing hour — a present need beats a future preparation. `purge` stays last.

Structurally this means `freecool` cannot live inside `vent_decision`'s existing `if
advice["advised"]:` block, since by definition the dew gap is not met. `vent_advice` grows
`freecool: bool` alongside `advised`, computed with the same deadband treatment, so all
threshold logic stays in one function; `vent_decision` just reads the two verdicts.

### 13.6 Night purge — DECIDED 2026-09-06: fix it in the same release

`purge` is gated on `advised`, i.e. the full dew gap. But the purge's whole point is *thermal* —
pre-cool the room's walls, floor and water ahead of a hot day. On a night where outdoor is 6 °C
cooler but only 1.4 °C drier it will not fire, for the same wrong reason as §13.2.

Auditing it for this decision turned up two things it has never had, both worse than the wrong
gate. `purge` sits in the `elif` chain **after** `fan_needed` is false — it fires precisely when
the room does *not* need cooling — and nothing watches the room while it runs:

- **No thermal test at all.** Its only temperature gate is `advised`'s `out ≤ room + 1`, so it
  will happily purge with outdoor *at* room temperature, banking nothing.
- **No low-temperature stop.** `cool` and `freecool` both end when `fan_needed` releases. `purge`
  has no equivalent: it runs its window out (`PURGE_MAX_HOURS` 8) and stops only if outdoor turns
  warmer than the room. Twelve-degree air for eight unattended hours can take the room well below
  target, with the heater fighting it until dawn.

So purge inherits the whole `freecool` gate set rather than merely dropping to dew-neutral:

1. `gap ≥ 0` (dew-neutral) replaces `gap ≥ dewGapC`
2. `room − out ≥ coolGapC` — the thermal test it never had
3. `out ≥ coolMinOutdoorC` — the §13.7 floor
4. **new** `room > target − purgeFloorC` (default 2.0 °C) — stop banking cold once the room is
   comfortably under target; the thermal-mass equivalent of the `fan_needed` brake

Net: purge fires on more nights (for the right reason), refuses nights where it currently
achieves nothing, and can no longer overcool. It ends up better guarded than it is today, which
is why this ships **with** `freecool` rather than after it — and why shipping `freecool` alone
would leave `purge` as the only path still using a drying test for a thermal job.

Residual risk, accepted: dew point commonly *rises* toward dawn as temperature falls, so a purge
that begins dew-neutral can turn wet. The dew gate is live (only the *window* comes from the
forecast; `in_purge_window` just bounds the hours), it is re-evaluated every five minutes, and
the §13.4 deadband stops it at `gap < −0.3`. Worst case is a few minutes of slightly wet air.

Watch on the first cold nights: `coolMinOutdoorC` 10 °C will block the purge in October, when
cold air is exactly what a purge wants. Shared with `freecool` for now; split into its own floor
only if it actually bites.

### 13.7 Safety — the one new hazard

Every existing vent gate optimises humidity, so none of them ever had to care how *cold* the
incoming air is. `freecool` does, and corals object to rapid swings far more than to being a
degree warm.

The natural brake is already there: `fan_needed` goes false once the room drops below
`target − fanGateC − 0.3`, which ends the run. But that is evaluated on a five-minute tick, and
very cold air moves a small room faster than that.

Add `coolMinOutdoorC` (default **10 °C**, `0` disables) — never `freecool` on air colder than
this. Cheap insurance, and it does not interfere with a UK summer night purge at 15–18 °C. Note
the existing `purge` has no such floor today; if §13.6 is adopted the floor should apply there
too.

Not adding a gate for: cooling the room below its own dew point (condensation). At these numbers
— room 28 → 24, dew 12 — it is unreachable, and `coolGapC` plus the `fan_needed` floor bound it
long before.

### 13.8 Config

`coolingHeadroom.vent` gains:

| key | default | range | meaning |
|---|---|---|---|
| `coolVent` | `true` | bool | enable the `freecool` route |
| `coolGapC` | `2.0` | 0.5–8.0 | how much cooler outdoor must be |
| `coolMinOutdoorC` | `10.0` | 0–20 (0 = off) | never freecool (or purge) on air colder than this |
| `purgeFloorC` | `2.0` | 0–6 | stop the night purge once the room is this far below target |

Default **on**: the route only fires when `fan_needed` is already true — the room at or over its
gate — which is a narrow and correct window, and it is self-limiting per §13.4. A cold fish room
in winter never reaches it. It is still a behaviour change and belongs in the release note.

New constants in `cooling.py`: `VENT_COOL_GAP_C`, `VENT_COOL_GAP_HYST_C = 0.5`,
`VENT_DEW_NEUTRAL_HYST_C = 0.3`, `VENT_COOL_MIN_OUTDOOR_C`.

### 13.9 Copy

| where | text |
|---|---|
| reason | "the room is 4.1 °C hotter than outside (24.3 °C) and no wetter — free cooling" |
| notify | "Vent the room — free cooling" / "Intake fan running: free cooling" |
| refused, too cold | "outdoor air is 6.2 °C cooler but only 8 °C — too cold to blow at the tank" |
| refused, wetter | "outdoor air is cooler but wetter (dew point X °C) — it would cost the fans more than it saves" |

The last one matters: it is the line that explains why OpenReef is *declining* obviously cooler
air, which will otherwise read as the same bug Reece just reported.

### 13.10 What does not change

- **The projection and the 24 h strip.** `freecool` is a conduction benefit; it does not alter
  fan headroom, so "needed and losing" hours are computed exactly as now. No change to
  `project()`.
- **Mutual exclusion.** A freecool-vented room is `vent_active`, so `dehumidifier_plan` yields
  to it as `vented` through machinery that already exists — and should, since running a
  dehumidifier into an open window is the waste §11 already names.
- **`dewGapC` and the `cool` kind.** Untouched. This is strictly an additional route.

### 13.11 Files and tests

`cooling.py` (constants, `vent_advice` verdicts, `vent_decision` kind, `VENT_RUN_KINDS`),
`__init__.py` (normaliser, snapshot wiring, notify keys), `openreef-panel.js` (three settings
inputs, the new kind's copy in `_coolingVentLine`, Overview and Pulse).

Tests to add: the three gates and their deadbands; priority against `cool` and `predry`; the
too-cold refusal; `coolVent: false` disabling the route entirely; the normaliser's clamps; and a
`_l2_hass` fixture reproducing Reece's 2026-09-06 reading (room 28.4, outdoor 24.3 at 43 %) which
must return `freecool` — that reading is the acceptance test for the whole section.

### 13.12 Decisions — LOCKED 2026-09-06 (Reece's answers)

1. **`coolGapC` = 2.0.** The conservative start; revisit if his room sits stubbornly 2–3 °C over.
2. **Night purge: fix it in the same release** — see §13.6, which grew from "relax one gate" into
   four gates once the audit found purge had no thermal test and no low-temperature stop.
3. **`coolMinOutdoorC` = 10.0.** Good start; §13.6 notes the October caveat.
4. **Settings applied 2026-09-06** (before any of this is built): `dewGapC` 3 → **2**, `minOn`
   60 → **20**, `minOff` **10**. Confirmed working the same afternoon — gap 4.0 °C, one clean
   run, "Venting: the room needs cooling and outdoor air is drier (25.3 °C, dew point 9.5 °C)".
   With `room − out` at 1.8 °C, under `coolGapC`, `freecool` would correctly not have fired: the
   two routes separate cleanly on his live numbers.

Status: **spec complete, not built.** Next step is the build — `cooling.py` gates and deadbands
first, then the normaliser, then the panel, with §13.11's acceptance test (his 2026-09-06
reading must return `freecool`) written before the code.
