# Coral Spawning — smart-plug execution — design brainstorm

Date: 2026-08-24 · Status: **ARC COMPLETE — A+B shipped 0.7.73, C+D shipped 0.7.74 (2026-08-24)** · Mapped against v0.7.72

> **C+D shipped (0.7.74)**: **Stage C** — `sensor.openreef_spawning_target_temp` publishes whenever spawning is on (bare state-machine write, dosing-mirror pattern; reef/sunrise/sunset/moon/window attributes), and guarded seasonal heat/cool: symmetric bang-bang at RT ± 0.2 (exact Apex snippet mirror; plug state is the hysteresis latch, software stateless), normalize-enforced opt-in (`temp.enabled` only sticks with `acknowledged` + sensor + an actuator), every sensor doubt (unavailable/non-numeric/stale ≥15 min/implausible outside 15–32 °C) fails BOTH plugs OFF + alert, hard clamps `maxC`/`minC` beat the curve, °F sensors auto-convert, drift alert at ±1.0 °C, temp channels never honor hold-overrides (safety channel). The tick now also runs **publish-only** (feature on, execution apex/disarmed): sensor + captures, zero actuation. **Stage D** — one capture per predicted spawn-window night at first tick after sunset (evening-side dedupe), opt-in `capture.triggers.spawnWindowNight` ("OpenReef films your spawn"); Pulse moon tile gains the live-execution line + "keep nights dark" when the window is open. Tests: 8 more (spawning = 58); full backend + panel harness green.

> **A+B shipped (0.7.73)**: `spawning.execution_desired_state()` pure engine (offset-mapped daily photoperiod, real-moon illumination gating, next-transition countdown, spawn-window flag, seasonal target temp for Stage C) + minutely reconcile tick (`_async_spawning_tick`, stamp-and-compare override detection — the repo's first, "hold"/"reassert" policies, cooldown-deduped unavailable alerts, spawn-window dark-night vigilance, plain-prose activity entries) + ⚡ Execution card on the Spawning tab (mode selector, armed toggle, switch/light entity pickers with the R20 no-silent-unbind rule, live today-strip, override banner + Resume now, opt-in PAR-gate button) + `lightingSchedule.mode: "spawning"` resolved through `_effective_lighting_cfg` at all three gate call sites. WS: `spawning_execution_status`, `spawning_execution_resume`; config rides `save_config`. Tests: 18 new in `tests/test_spawning.py` (50 total), full backend suite green.

The idea in one line: **same brain, new hands.** Today the spawning engine compiles homework for a Neptune Apex (Season Table + Profiles + code). This arc makes OpenReef *execute the program itself* — the generated seasonal sunrise/sunset (and optionally moonlight and temperature) drives ordinary Home Assistant smart plugs, live, every day of the year.

---

## 0. Locked decisions (Reece, 2026-08-24)

1. **v1 scope: Stages A+B together** — daylight plug and moonlight/dark-night protection ship as one arc.
2. **Override policy: default "hold"** — a manual toggle is respected until the next natural transition, with an override banner + "Resume now" chip. Strict re-assert remains a config option, not the default.
3. **Heater control: LOCKED (b), Inkbird-inline variant, with symmetric cooling** — Inkbird becomes the fixed dual-direction guard rail (never software-driven); OpenReef does seasonal heat (fail-OFF, AND-gated through the Inkbird heat socket) and seasonal fan cooling (fail-ON, own plug straight to wall). Full design in the §5 Stage C rig addendum. Step 1 RT target sensor ships first; (c) firmware node stays the later upgrade path.
4. **B′ two-plug step ramp: PARKED** — design preserved below, not in the arc.
5. **Entity domains: both** — `switch.` and `light.` entities (driven on/off; dimmable ramps are a separate later stage).
6. **PAR-gating sync: opt-in** — a one-click "gate light alerts from the spawning program", never automatic.

Continuity note: the original spawning grilling (2026-06-12) already locked "direct HA actuation is the premium/later path" — this arc is that path activating.

## 1. Why it's worth doing (positioning)

- The Craggs/Rich Ross method today has a **hardware floor of a ~£600–800 Apex**. This drops it to a **£12 smart plug**. Every HA user with a light on a plug becomes a potential spawning-project reefer — a far wider funnel than Apex owners.
- It completes the intelligence-layer story: OpenReef stops generating homework for *another* controller and **is the controller**. The Apex path stays untouched (the beta tester is an Apex owner) — two execution targets, one brain.
- Small honest superiority: the Apex workflow's "⚠️ re-enter the new-moon table every Jan 1 or your lunar timing silently drifts" footgun **disappears** — the engine computes real moon instants continuously.
- **Fidelity honesty (disclose, don't overclaim):** a plug is hard on/off — no dawn/dusk ramp, and the Sunset ramp is the documented proximate spawn trigger. What survives fully intact are the *primary* cues: seasonal **day-length drift**, seasonal **temperature**, and the **lunar cycle**. Mitigations: the two-plug step ramp (§5, Stage B′) and, later, dimmable `light.` entities. The advisory banner should say this plainly.
- Claim wording needs an NPS-style prior-art sweep before it hits the site, but the likely-defensible line is something like *"run a real reef's seasonal spawning photoperiod on any smart plug — no reef controller required."* Apex/Hydros/GHL all require their own hardware; raw HA requires hand-built template automations with hand-scraped data (the exact misery the engine already eliminates).

## 2. What already exists (mapped 2026-08-24)

The pleasant surprise: **the runtime brain is already written.** The engine is pure and per-date, not per-month:

- `anchored_sun_times(lat, date, solar_noon)` → exact sunrise/sunset for **any date** (the 12-row Season Table is just 12 samples of it) — [spawning.py:149](custom_components/openreef/spawning.py#L149).
- `moon_illumination()` / `moon_age_days()` for any instant; Meeus new/full-moon instants; `predict_spawn_window()` — all pure, all CI-tested.
- `config["spawningProgram"]` already persisted + normalized (`enabled`, `reefPreset`, `offsetMonths`, `solarNoonHour`, `tempUnit`, `tempProbe`, `acknowledgedAdvisory`) — [__init__.py:2822](custom_components/openreef/__init__.py#L2822).
- Actuation idioms ready to copy: minutely `async_track_time_interval` ticks (AWC schedule tick, dosing tick, watchdog), `switch.turn_on/turn_off` service calls with the blocking + log-and-swallow stop-path doctrine, and NPS Stage C's `ha_switch_timed` driver which already proved the "**any HA switch as a best-effort actuator behind a guard chain**" pattern.
- `lighting_window()` / `is_lights_on()` — the PAR-alert gating schedule — already does a mini version of this computation but from a *separate* config (`lighting`, reef mode centered on 12:00 + offsetHours, not `solarNoonHour`). §8 proposes unifying.
- Test harness: fake-HA drives ticks with injected `now`; a pure desired-state function means a whole simulated year runs in milliseconds.

So the arc is genuinely small: **a desired-state function + a reconcile tick + an Execution card on the Spawning tab.**

## 3. Architecture — reconcile, don't schedule

**Recommended: a declarative desired-state evaluator**, not scheduled timers.

1. New pure function in `spawning.py` (no HA imports, unit-tested like the rest):
   `execution_desired_state(cfg, now_local) -> {light: bool, moon: bool, sunrise, sunset, dayLength, moonIlluminationPct, phaseName, ...}`
2. A minutely tick in `__init__.py` (own unsub const, same idiom as `AWC_SCHEDULE_UNSUB`) computes desired state and reconciles the configured entities to it — **service call only on mismatch**, so no spam, and repeated asserts are free.

Why reconcile beats the alternatives:

| Approach | Verdict |
|---|---|
| **Minutely reconcile tick** | Restart-safe (HA reboots mid-day → first tick re-asserts), DST-safe (times are local clock), config edits take effect next tick, self-healing if the plug reboots. Sunrise only drifts ~1–2 min/day, so minute resolution is exact. Matches the maintenance-arc LOCKSTEP doctrine. |
| Point-in-time timers for next sunrise/sunset | Fragile across restarts and config edits; two sources of truth. |
| Generate HA automations/YAML for the user | Daily-varying times are awful in YAML, breaks lockstep with the panel, and "here's some YAML" is exactly the raw-HA experience we position against. |

Every transition logs to the existing event stream with the personality-on-calm-states voice: *"🌅 Sunrise — running GBR November, 12 h 48 m of light today."*

## 4. Manual override semantics (a real decision)

Reefers turn lights off at the wall to frag, photograph, and catch fish. When the tick sees actual ≠ desired **because a human changed it** (state changed outside our own service call):

- **Option "hold" (recommended):** respect it until the *next natural transition* (sunset/sunrise), show an "Override — program resumes at sunset (18:42)" banner with a "Resume now" chip.
- **Option "reassert":** strictly re-assert within a minute (offered as a per-config policy for set-and-forget users).

Either way the **armed** master toggle (AWC-style) always wins: disarmed = OpenReef never touches the plugs.

## 5. Channels, staged

**Stage A — daylight plug (the v1 meat).**
One `switch.` (or `light.` treated as on/off) entity. ON at sunrise, OFF at sunset, per the exact same curve that fills the Apex table. Panel gets an **Execution** section on the Spawning tab: target selector (**Neptune Apex** — today's compile flow, unchanged | **OpenReef smart plug**), entity picker, armed toggle, and a live "today" strip — sunrise/sunset, day length, next transition countdown, moon phase, spawn-window countdown (all already computed by `generate_program`).

**Stage B — moonlight plug + dark-night protection.**
Second plug: ON sunset→sunrise on nights where illumination ≥ threshold (default ~25%), **forced OFF around the new moon** — genuinely dark nights are the thing light pollution ruins, so the *off* behaviour is the headline, not the on. During the predicted spawn window, add vigilance: warn (event + alert fan-out) if the daylight plug is manually ON after sunset. Moonrise drifting ~50 min/night after full is a v2 nicety; the threshold gate carries the biology.

**Stage B′ — two-plug step ramp · PARKED 2026-08-24.**
A second daylight plug emulates the Apex 3-step profile with dumb hardware: blues ON at sunrise → whites ON at sunrise + `SPAWNING_SUNUP_RAMP_MIN` → whites OFF at sunset − ramp → blues OFF at sunset. Maps directly onto the dual-channel (blues/whites) wiring many reefers already have. Softens the hard-sunset fidelity compromise for £12 more.

**Stage C — temperature (careful, two steps).** Temperature is the cue that sets the *month* of gamete readiness — a full smart-plug execution wants it eventually, but the heater is categorically riskier than the light channel:

- **Failure asymmetry.** A light plug stuck ON/OFF gives a wrong photoperiod — bad for the project, harmless to livestock for days. A heater plug stuck ON cooks the tank in hours; stuck OFF in winter chills it over a day or two. Same software, opposite stakes.
- **No hardware fallback on a dumb plug.** Apex outlets have firmware `Fallback OFF` if the head unit dies. A £12 plug has nothing: if HA hangs, the tick dies, or the plug drops WiFi while ON, it simply stays ON. Software cannot mitigate its own absence.
- **Sensor trust.** Bang-bang is only as good as the temp reading. A stale value (sensor offline, HA showing the last state), a probe out of the water, or a cheap miscalibrated stick-on all produce confident wrong heating.

*Step 1 — RT target sensor (**locked 2026-08-24**, zero-risk, ships in this arc or right after):* expose today's RT as `sensor.openreef_spawning_target_temp` + a panel drift readout vs the tank's actual temp sensor. Power users wire their own `generic_thermostat` (HA's own well-tested component) at their own risk; Apex owners keep Apex heater control and see seasonal drift at a glance.

*Step 2 — OpenReef drives the heater (**open decision**), three ways to own it:*

| Option | Shape | Residual risk |
|---|---|---|
| **(a) Sensor-only forever** | Step 1 is the feature; we never switch a heater | Zero for us; least featureful |
| **(b) Guarded plug + dial-as-ceiling** | Bang-bang at RT ± 0.2° with the full guard stack, **and** the ack flow requires the heater's own onboard thermostat set to the curve's seasonal peak (e.g. 27.5 °C GBR). OpenReef then only ever modulates *downward* (cool-season suppression) | Worst software failure = tank parked at spawning-peak temp by the heater's own dial — suboptimal, not lethal. Cold direction covered by drift alerts |
| **(c) ESPHome temp-guard node** | Reefnode doctrine: firmware owns the thermostat + hard cutoff with its own probe; OpenReef just sets the seasonal target. Survives HA death entirely | Best safety story; gates the feature on the hardware track |

The reframing that makes (b) shippable: **the heater's own dial is the physical failsafe**, not our software. Software guards stack on top: stale/implausible sensor (no update N min, or reading outside 15–32 °C) → **fail OFF** + alert; hard command clamps independent of the curve; plug-unavailable alert; drift alert when actual strays beyond RT ± band for N minutes (catches stuck-OFF chill). Cooling ships **with** heating, symmetric — see the rig addendum below; in a warm room the fan is the primary actuator, not an emergency device. Recommended path: Step 1 now → (b) as a later stage behind an explicit `acknowledgedAdvisory`-style checklist → (c) as the eventual premium/kit answer.

*Addendum — Reece's rig (2026-08-24, recommended design, awaiting lock):* Reece runs an **Inkbird heat/cool controller** and the tank temp probe already lives on an **ESP32 multi-sensor node** (pH, room temp, humidity, CO₂) with its temperature entity in HA. That is option (b) in its strongest form — the Inkbird *is* the independent inline thermostat, with a probe independent of the control probe:

```
Wall ── Inkbird ──(heat socket)── smart plug A (OpenReef) ── heater (dial = max/just above Inkbird)
              └──(cool socket)── emergency fan B (fixed hardware backstop, recommended £15 add)
Wall ── smart plug C (OpenReef) ─── primary fan (the seasonal workhorse)
```

- **Cooling is symmetric and first-class, not deferred** (corrected 2026-08-24 after Reece's push-back: his room hits 30 °C and the fan already runs daily to hold 25 — cooling is the *primary* actuator whenever ambient ≥ RT). The engine already agrees: `generate_program` ships heater **and** chiller Apex snippets; the plug executor mirrors both with the same ±0.2 bands (Rich Ross verbatim).
- The primary fan gets its **own plug straight to wall — never through the Inkbird cool socket** (series = AND-gate, and the cool socket only closes above the guard ceiling, which would block all seasonal cooling below it).
- **Failure directions are opposite per channel**: heater fails safe **OFF**; fan fails safe **ON** (a fan stuck on is harmless — the heater band compensates in winter, worst case is evaporation/electricity). Prefer an ESPHome-flashable plug for the fan so its no-HA-heartbeat behavior can be "default ON". Stale/implausible sensor → both actuators OFF + loud alert (neutral drift to ambient; Inkbird alarms backstop both ends).
- Inkbird's role changes from day-to-day thermostat to **guard rail, both directions with its one setpoint**: TS = seasonal RT max + ~0.5 (e.g. 28.0) → heat socket refuses heating above ~TS−HD *and* cool socket forces emergency fan B above ~TS+CD. High/low audible alarms armed (low alarm covers stuck-off heating; high alarm covers HA-dead-in-heatwave if no fan B).
- Smart plug A goes **between the Inkbird heat socket and the heater** (not upstream of the Inkbird), so the Inkbird stays always-powered — display, cool socket, and alarms alive regardless of plug state.
- OpenReef does the seasonal bang-bang at RT ± 0.2 via the ESP32 temp entity → **AND-gate of two independent thermostats with two independent probes** on the heat side. Runaway heat requires both to fail; runaway cool doesn't exist (evaporative floor ≈ wet-bulb).
- *Intelligence-layer nicety (Stage C or Pulse):* the same ESP32 carries **room temp + humidity** — evaporative cooling weakens as humidity rises, so OpenReef can compute **cooling headroom** and warn early: "Room 30.1°, humidity 78 % — fan headroom thin today."
- **Doctrine: never drive the Inkbird's setpoint from software** (even if it's a WiFi model) — a failsafe you can program is a failsafe you can break.
- Upgrade path to true (c) later, near-free: the existing ESP32 sensor node (if ESPHome, with a spare GPIO + relay — or probe moved onto an ESPHome plug/Shelly+Add-On) runs a firmware `thermostat` climate locally; OpenReef writes only the daily target; Inkbird stays as guard. No new design needed when wanted.

**Stage D — spawn-night camera tie-in.**
Auto-arm Camera V2 event capture / feed-watch on predicted spawn-window nights — *"OpenReef films your spawn."* Plus a Pulse insight-rotator card ("Spawn window opens in 12 nights"). Cheap, and it's the demo moment.

## 6. Config & surface sketch

Extend `spawningProgram` (normalize in the existing block at [__init__.py:2822](custom_components/openreef/__init__.py#L2822)):

```jsonc
"execution": {                       // as built (A+B) — lightEntity2 dropped with parked B′;
  "mode": "apex" | "openreef",      // default "apex" — beta tester sees zero change
  "armed": false,                    // temp block arrives with Stage C
  "lightEntity": null,               // switch.* or light.* (driven on/off)
  "moonEntity": null,
  "moonMinIlluminationPct": 25,
  "overridePolicy": "hold" | "reassert"
}
```

Persistence rides the panel's normal `openreef/save_config` flow (normalize sanitizes the block); live state comes from a lightweight `openreef/spawning_execution_status` WS the tab polls while open, and `openreef/spawning_execution_resume` clears a hold-override early. PAR-gating opt-in = `lighting.mode: "spawning"`, which the backend resolves to the executed program's own window (one sun model; unknown-mode fallback stays "never suppress"). Demo/present modes must never actuate. Watchdog covers the tick. Switching mode back to `apex` or disarming releases control and leaves the plug in its last state — never yank the lights mid-day on a config edit.

## 7. Safety & edge-case checklist

- Entity `unavailable`/`unknown` at a transition → keep trying each tick, raise **one** deduped alert (existing alert idioms), clear on recovery.
- HA restart mid-day → first tick reconciles; no missed-transition catch-up logic needed (declarative state has no backlog).
- DST → times are local-clock; the skipped/repeated hour just shifts one evaluation, day length unaffected.
- Heater channel: everything in §5 Stage C step 2 — fail-OFF is the only acceptable failure direction.
- Plug is a shared circuit (someone plugs a skimmer into the "light" plug): docs + the entity picker showing current entity name/state at selection time is the realistic mitigation.

## 8. Unify with the PAR-alert lighting schedule

When execution mode is `openreef` and armed, the PAR-alert gating window should **follow the executed program automatically** — one sun model, one source of truth. Today `lighting_window()` reef mode centers on 12:00 + `offsetHours` while spawning centers on `solarNoonHour`; running both configured slightly differently would gate alerts against a *different* sunset than the one actually switching the lights. Minimum: a one-click "gate light alerts from the spawning program"; better: automatic while armed.

## 9. Staged build plan (indicative)

| Stage | Contents | Size |
|---|---|---|
| **A+B** (locked as the v1 arc) | `execution_desired_state()` + reconcile tick + daylight plug + Execution card + "hold" override + moonlight plug + dark-night forcing + spawn-window vigilance + tests | the meat; B is small once the tick exists |
| **B′** | two-plug step ramp | **PARKED** |
| **C** | RT target sensor (locked) → heater control per the open (a)/(b)/(c) decision | sensor tiny; heater deliberate |
| **D** | camera auto-arm on window nights + Pulse card | small, high demo value |

## 10. Open questions

**None — all six decisions locked (§0, 2026-08-24).** Heater locked as (b) Inkbird-inline with symmetric cooling per the §5 Stage C rig addendum; Stage C builds after A+B.
