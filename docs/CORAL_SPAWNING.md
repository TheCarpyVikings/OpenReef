# Coral Spawning — Reef Location Simulator

> The headline feature. OpenReef turns "pick a reef" into a finished Apex spawning
> program — eliminating the most miserable part of home coral spawning: hand-authoring
> a year of seasonal/lunar data tables.

## Why this exists

Advanced reefers already spawn *Acropora* at home on a Neptune Apex by replaying a
reef's seasonal **photoperiod**, seasonal **temperature**, and **lunar cycle** — the
method pioneered by Jamie Craggs / Project Coral and documented for hobbyists by
Rich Ross. What they complain about isn't biology or motivation; it's **programming
the data tables**: scraping a year of sunrise/sunset/new-moon data off
timeanddate.com, digging up seasonal SST, and hand-writing the Apex code, then
maintaining it. OpenReef computes all of it from a curated reef preset and hands them
the finished artifacts.

The value lands on **day one** (a program generated in seconds vs. weeks of Fusion
grind). The spawn itself is the bonus the reefer was already chasing ~9–12 months out.

### Product framing
- **Reef Location Simulation** — any reefer can run a reef's authentic seasonal/lunar
  rhythm. Broad, day-one value.
- **Spawning Program** — the advanced goal-state on the same engine, dialled to the
  full Craggs protocol (cold-winter conditioning, strict dark nights).

## The science (cue stack)

| Cue | Drives | Notes |
|---|---|---|
| Seasonal photoperiod (day length) | gametogenesis onset — the *month* | latitude-driven; equatorial reefs barely move |
| Seasonal temperature | egg development (cold winter) → maturation/trigger (warming) | Craggs held ±0.1 °C; GBR needs ≥26 °C ~a month |
| Lunar cycle | the *night* | spawning N nights after the spawning-month full moon; **dark nights matter** — light pollution desynchronises spawning |
| Sunset (diel) | the *hour* | the proximate release trigger |

Hierarchy: **photoperiod + temperature set the month, lunar sets the night, sunset
sets the hour.**

Sources: Craggs et al. 2017 (Ecology & Evolution, [PMC5743687](https://pmc.ncbi.nlm.nih.gov/articles/PMC5743687/));
Craggs et al. 2025 out-of-season offset profiles (Proc. R. Soc. B,
[rspb.2025.1558](https://royalsocietypublishing.org/doi/10.1098/rspb.2025.1558));
Rich Ross, "Coral Spawning Resources" ([packedhead.net](https://packedhead.net/coral-spawning-resources/));
ALAN disruption (Nat. Comms 2023, [s41467-023-38070-y](https://www.nature.com/articles/s41467-023-38070-y)).

## Architecture

**Brain — `custom_components/openreef/spawning.py`** (pure stdlib, no deps, fully unit-tested).
Given a reef preset + year it computes:
- solar day length → anchored sunrise/sunset (NOAA/Spencer declination; photoperiod
  centered on a user "solar-noon" so the tank runs on a convenient clock)
- accurate new/full-moon instants (Meeus *Astronomical Algorithms* ch. 49) + a smooth
  illumination curve
- seasonal temperature from the preset's monthly SST climatology
- a spawn-window prediction (full moon of the spawning month + the documented
  "N nights after full moon")
- an optional whole-month **offset** that maps the reef's season onto the user's
  calendar (Craggs' out-of-season method)

**Compiler** (in the same module) emits the exact artifacts a reefer pastes into the
Apex, following Rich Ross's documented Apex-Local workflow verbatim:
- the 12-row **Season Table** (sunrise/sunset/RT per month)
- lighting **Profiles** (Sunup/Midday/Sunset/Moonlight for MXM Radions)
- **code** snippets — temperature (`If <probe> < RT-0.2 Then ON`), daylight
  (`If Sun 000/-360 Then Sunup` …), lunar (`If Moon 000/000 Then ON`), Radion
  moonlight (`If Output vMoon = ON Then Moonlight`)
- the year's **new-moon dates** (+ the Jan-1 reset reminder)
- a guided Apex-Local walkthrough

**Hands** — for v0, OpenReef *generates*; the **Apex executes** (with its own failsafes
intact). HA-native direct drive is a later phase.

### Backend wiring
- `const.py`: `REEF_PRESETS`, `SPAWNING_*` constants, `spawningProgram` in
  `DEFAULT_CORE_CONFIG`, `CORE_SCHEMA_VERSION` bumped to 42.
- `__init__.py`: `spawningProgram` normalisation; WS commands
  `openreef/list_reef_presets` and `openreef/generate_spawning_program`
  (read-only `@callback` computes — fall back to the saved selection).
- Frontend (`openreef-panel.js`): a **Spawning** tab — reef picker + options →
  Generate → renders prediction, Season Table, Profiles, code (copy buttons),
  new-moon dates, and the walkthrough. Selection persists via the normal save path.

### Reef presets (curated; dynamic SST is a later phase)
GBR (Central), Singapore (Kusu), Red Sea (Gulf of Aqaba), Hawaiʻi (Oʻahu),
Caribbean/Florida. Monthly SST is approximate climatology; **GBR & Singapore are
validated against Craggs' published profiles**. The GBR spawn window uses Rich Ross's
documented "12–15 nights after the full moon" template.

## Tests
`tests/test_spawning.py` (23 tests, in CI): astronomy validated against known anchors
(2000-01-06 new moon, 2000-01-21 full moon, equinox/solstice day lengths), the
compiler emitting Rich Ross's exact code, offset mapping, preset integrity, config
normalisation, and the WS handlers end-to-end.

## Roadmap
- **v0 (shipped):** the compiler — preset → Season Table + Profiles + code + walkthrough.
- **v1:** "Reef Location Simulation" framing for all users; maintenance-reminder
  hooks (Jan-1 new-moon reset nag, "nights until window" countdown); gravid-coral
  readiness checklist.
- **v2 (premium):** HA-native direct drive for MXM-Radions — night-by-night lunar
  intensity grading + dark-window enforcement (the Apex can't do this natively) +
  camera-based night-lux light-pollution coaching.
- **v3:** dynamic SST data (NOAA Coral Reef Watch / AIMS); larval-rearing guidance.

## Related: lighting-schedule alert gating

The same solar engine powers a separate feature — **light-dependent alert gating**
(`lightingSchedule` config + `spawning.is_lights_on()`). Light sensors (PAR) read ~0
when the lights are off, which would trip a false "below minimum" alert; the lighting
schedule (off / simple on-off times / reef-mimic-with-offset) gates the **low side** of
`lightGated` sensor alerts to the lights-on window, with a ramp-grace buffer. High alerts
always fire; mode `off` (default) keeps legacy behaviour. See `_sensor_low_suppressed` and
`_sensor_alert_items` in `__init__.py`.

**Known limitations:**
- **DST drift.** The window is evaluated in Home Assistant's local (DST-aware) time, but a
  reef/simple schedule is a fixed clock offset. When local time crosses a DST boundary the
  window shifts ±1h until the user re-tunes the offset (the ramp grace, default 30 min, only
  partly absorbs this). Reefers mimicking a no-DST locale on a no-DST HA box (e.g. Cairns /
  Queensland) are unaffected. A future enhancement could auto-correct using the HA tzinfo.
- **History churn (mitigated).** A genuinely-low daytime reading is now *held* across the
  lights-off window rather than flapping resolved→alert each dusk/dawn (`_sync_alert_state`
  carries the last state forward while suppressed); recovery is still detected during lit hours.

## Open questions to validate with spawning reefers
- Exact Season-Table granularity the Apex accepts (12 monthly rows vs. fewer anchors).
- Per-preset spawn-timing conventions beyond GBR (we use the field-literature
  "2–6 nights after full moon" default where no hobbyist template exists).
