# Cooling headroom — humidity-aware fan cooling + smart dehumidifier · research & brainstorm (2026-09-03)

Reece's observation: the fans are far less effective on a humid day than on a hot dry one,
even when the room is cooler. The dehumidifier currently runs off a dumb humidistat. Wanted:
a **"fan cooling will be affected" warning** and a **dehumidifier trigger that only fires when
it will actually help**, projecting 24 h ahead from room temp, room humidity and the weather.

Research + brainstorm 2026-09-03 on 0.7.118; **Layer 1 built as 0.7.119 the same day** (§9). Decisions locked in §7; the window fan in §8.

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
