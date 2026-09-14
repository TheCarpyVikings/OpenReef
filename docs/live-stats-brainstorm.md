# Live Stats — redesign + direction arrows · brainstorm (2026-09-13)

Reece's ask: the Live Stats page was built with a weaker model and looks it. Make it a lot more
visually appealing, and add **trend direction** — "I've just opened a window: is the room
temperature going up or down, and how fast?"

Mockup (example data, hover the sparklines): https://claude.ai/code/artifact/0722b031-87c1-4f4c-9d86-e324ddd5ed67

Decisions locked in §8 (2026-09-13). **v1 built the same day as 0.7.171** (§9), **v2 as 0.7.172** (§10), **the trend modal as 0.7.173** (§11), **the three parked ideas as 0.7.181** (§12). Nothing is parked now except per-sensor speed thresholds.

---

## 1. What is there today (0.7.163)

`_liveStats()` in the panel: three summary tiles (Sensors / In range / Attention), then sensor
cards bucketed by group (`tank`, `sump`, `chemistry`, `water`, `flow`, `lighting`, `safety`,
`room`). A Numbers / Graphs / Gauges picker (`_liveStatsMode`, localStorage) swaps the middle of
every card. Graphs mode fetches a 24 h sparkline per sensor (`_loadLiveSparklines`, sequential,
cached 4 min) via `_pulseSparkSvg`, which is a bare polyline with no scale, no range, no
endpoint. Gauges mode is a min→max semicircle. Status comes from `_sensorStatus` (min/max +
`warningBuffer` % + hysteresis, light-gated low suppression) and the friendly label from
`_liveStatBadge`. Clicking a card opens the existing Trend view (`show-trend`).

There is **no notion of direction or rate anywhere on the page**. The only slope maths in the
panel is the least-squares fit in the health/dosing advisor (`_leastSquares`, units/day) — the
right tool, the wrong timescale.

## 2. Why it looks weak (the honest critique)

- **Three cards say the same thing.** Sensors 5/5, In range 4, Attention 1 is one fact spread
  over three boxes, each as big as a sensor card. The eye lands on the tiles, not the readings.
- **Every card shouts equally.** Left accent stripe + coloured border + coloured pill + tinted
  background on all five cards. Green everywhere means red can't stand out; the humidity card
  only wins by being reddest.
- **The three modes are three half-pages.** Numbers has nothing to look at; Graphs loses the
  big number; Gauges is a min/max bar bent into a semicircle and shows the same information as
  the pill. None of them answers "what's happening".
- **The sparkline is unanchored.** No safe band, no endpoint, no "now", auto-scaled to its own
  min/max so a 0.05 °C wobble looks like a 2 °C swing.
- **Empty space.** Three-column grid with two Tank sensors leaves a third of the row blank;
  the page is over in one screen with nothing to read.
- **No time.** Nothing says when a reading last arrived. A sensor that died an hour ago looks
  exactly like a live one.

## 3. The proposal — one card that answers four questions

Kill the modes. Every card carries, top to bottom:

1. **What** — label + one status pill (in range / near limit / high / low / **stale**).
2. **How much** — the big cyan number. Unchanged; it's the panel's signature.
3. **Which way, how fast, and where that ends** — the **direction line**. This is the new
   thing and the answer to the window question:
   `↘  −0.7 °C/h · back toward the middle` or `↗  +0.06 °C/h · hits 26.0 ≈ 17:50 at this pace`
   or `→  steady last 20 min`.
4. **The last day, with the safe range drawn on it** — an always-on sparkline: 24 h in a
   dimmed slate line, the **last hour in bright cyan**, the safe band as a faint green fill
   with dashed edges and min/max labels, an endpoint dot for "now", and a dashed tick for any
   marked moment. Hover for time + value. Y-scale = union of safe range and the day's data, so
   a calm sensor draws a calm line.
5. **Footer** — `24 h 24.8–25.7 · avg 25.3`, `Δ since 14:02`, `Trend ›`.

Status stays where it belongs: the pill, a 2 px top edge, and (critical only) a faint red wash.
The left stripe goes on this page; the OK cards go quiet so the one that isn't stands out.
Sparkline colour is **never** status colour — it's the panel cyan, so a red line doesn't fight
a red pill and a green line doesn't lie when the reading is heading the wrong way.

### 3.1 The page around the cards

- **Truth strip** replaces the three tiles: one sentence plus four small counts.
  *"4 of 5 in range. Humidity is high but falling 1.7 %/h since the window opened — back in
  range ≈ 16:41. pH has not reported for 38 min."* Calm-state copy can carry the personality
  voice per the existing rule; the sentence with a warning in it stays plain.
- **Needs a look** group pinned at the top, holding any card that isn't OK. It's *moved*, not
  duplicated, so the group counts still add up (question in §7).
- **Since:** row — the marker chips (§4).
- **Cards / List** density switch instead of Numbers / Graphs / Gauges. List = one row per
  sensor with a mini-sparkline, direction line and pill: the phone view and the wall view.
- The legend under the grid explains the four line treatments once.

## 4. Direction, rate and "since I opened the window" — the maths

### 4.1 Where the readings come from

Two candidates, and the answer is **both**:

- **HA history** (`_fetchHistoryTrendPoints`, already used for the 24 h sparkline). One fetch
  per sensor gives the sparkline *and* the recent window for the slope. Costs one recorder
  call per sensor per 4 min — the existing cap. Downside: the recorder thins values that
  didn't change, and a 5-minute-old sample is the freshest it can be on first paint.
- **Live state deltas.** Every `hass` push already reaches the panel; keep a small ring
  buffer per sensor (`{t, v}`, last 2 h, capped ~120 entries) in memory. Zero fetch cost, the
  direction line updates on every reading, and it survives a recorder gap. Lost on reload,
  which is fine because history refills it.

Rule: the slope is computed from the ring buffer when it holds ≥ 3 points in the window,
else from history. The sparkline is always history.

### 4.2 The numbers

- **Rate** = least-squares slope over the last **20 min**, in units/h (reuse `_leastSquares`
  with x in hours). A second slope over 60 min is kept for the tooltip ("last hour −0.4 °C/h")
  and for the acceleration hint below.
- **Speed class** is relative to the sensor's own safe band, so one rule fits °C, pH and ppm:
  `pct = |rate| / (max − min) × 100` per hour. `< 1.5 %/h` → **steady** `→`; `< 8 %/h` →
  **moving** `↗ ↘`; else **fast** `↑ ↓`. (Tank temp 24–26: steady below 0.03 °C/h, fast above
  0.16 °C/h. pH 7.8–8.4: fast above 0.05/h.) Thresholds are a per-sensor override later, not
  now.
- **Toward or away**: `toward` when the sign of the rate points at the nearer limit
  (`rate > 0 && value > mid`, or the mirror). Arrow chip is amber for toward, green for away,
  neutral for steady. This is what makes "window opened, room cooling" read as *good* even
  while the room is still warm.
- **Projection**: `hours = (limit − value) / rate`. Show `hits <limit> ≈ HH:MM at this pace`
  only when `0 < hours < 3`; beyond that the extrapolation is noise. When already out of
  range and heading back: `back in range ≈ HH:MM` (allow up to 6 h). Otherwise, if out of
  range and still moving away: `still moving away`.
- **Acceleration hint** (later): if `|rate20| > 1.5 × |rate60|` the change is speeding up →
  add "and picking up"; if `< 0.5 ×` → "and easing". Cheap, and it's literally the
  "how quickly is the window working" answer.
- **Stale**: if the freshest point is older than `max(3 × sensor cadence, 10 min)` → pill
  reads `stale 38 min`, endpoint dot goes hollow, direction line is suppressed (a slope on
  dead data is a lie). `last_changed` is already read in `_state`.
- **Lockstep**: the direction line is panel-only for v1. If the backend ever wants rate (for an
  alert like "rising fast toward max"), the slope helper moves to `__init__.py` and the panel
  reads it — never two slope implementations with different windows.

### 4.3 Markers — "since I…"

A **marker** is `{ at, label, source }`. Every card shows `Δ since <time>` = now − value at the
marker (nearest history point). The sparkline draws a dashed tick at it.

- **Manual**: `+ Mark this moment` → prompt for a label ("Opened window", "Turned fan on",
  "Fed"). One active manual marker at a time; clearing it clears the Δ column. Stored in the
  config under `liveStats.marker` so it survives reload and shows on the iPad too (it is a
  server-written field → it MUST join the stale-save guard).
- **Automatic** (v2): OpenReef already writes the activity ledger for feeds, AWC runs, mixing
  draws, lights, cooling actions. Draw the last few as small ticks on the relevant cards (AWC
  → tank temp/salinity; feed → pH/CO₂; cooling fan/vent → room temp/humidity/tank temp). The
  card then *explains* its own bumps. Nobody else's dashboard does this; it's the
  intelligence-layer pitch on one screen.

## 5. New suggestions, ranked

| # | Idea | Value | Cost | Notes |
|---|------|-------|------|-------|
| 1 | Direction line (arrow · rate · projection) | ★★★★★ | S | The ask. §4.2 |
| 2 | Always-on sparkline with safe band, last-hour highlight, endpoint | ★★★★★ | S | Replaces the three modes; reuses the 24 h fetch |
| 3 | Truth strip + Needs-a-look group | ★★★★ | S | Copy + ordering, no data |
| 4 | Stale pill + hollow endpoint | ★★★★ | S | `last_changed` is already there; this is a safety feature dressed as a design one |
| 5 | Manual marker ("since I opened the window") | ★★★★ | M | §4.3; needs a config field + guard |
| 6 | 24 h min / max / avg footer | ★★★ | S | From the same points |
| 7 | List density (phone + wall) | ★★★ | M | Same maths, second renderer |
| 8 | Automatic event ticks from the activity ledger | ★★★★ | M | §4.3 v2; per-sensor relevance map |
| 9 | Acceleration hint ("and picking up") | ★★★ | S | Two slopes, one comparison |
| 10 | Typical-day ghost line (7-day per-hour mean behind today) | ★★★ | M | Needs statistics fetch; answers "is today weird?" |
| 11 | Room ↔ tank coupling ("tank lags room by ~2 h") | ★★ | L | Cross-correlation; later, and only if the cooling arc wants it |
| 12 | Tap the direction line → 6 h trend at that sensor | ★★ | S | Just a range param on `_loadTrend` |

Suggested v1 = 1–6. v2 = 7–9. Later = 10–12.

## 6. Visual rules for the build

- Keep the panel's tokens: `#0b1220` ground, `#111d2d` surface, `#67e8f9` numerals, green/amber/
  red reserved for status. No new identity — a better use of the one we have.
- Numerals and rates in tabular figures (`font-variant-numeric: tabular-nums`); rate and 24 h
  stats in the mono face if the panel gets one, else the same sans.
- One card = one grid with `gap`, no per-element margins. The sparkline box is
  `aspect-ratio: 320 / 84`, never a fixed height (the first mockup pass got this wrong: a fixed
  height fitted the SVG to the box and left two-thirds of the card empty).
- `repeat(auto-fill, minmax(320px, 1fr))` so two Tank sensors sit two-up instead of leaving a
  hole; a lone attention card is allowed to sit alone — that's the point.
- Hover crosshair + `HH:MM  25.3 °C` tooltip on every sparkline. Pointer events only; the card
  stays a `<button>` so keyboard users still reach Trend.
- Every status pill carries a word, never colour alone.

## 7. The grill — questions for Reece before anything is built

1. **Kill Numbers / Graphs / Gauges outright**, or keep Gauges as a third density for the wall?
   (My vote: kill. The gauge encodes what the pill and the band already say.)
2. **Needs-a-look: move or duplicate?** Moving keeps the counts honest; duplicating keeps every
   group complete. Mockup moves.
3. **Rate windows**: 20 min "now" + 60 min context — or 10 / 30 for a room that changes fast?
   Tank temp barely moves in 20 min; room temp and humidity do. Could be per-group.
4. **Projection horizon**: 3 h for "hits the limit", 6 h for "back in range". Longer?
5. **Manual marker**: one global marker (mockup) or one per card? Global is the window case;
   per-card is "I dosed alk" — but that's already an event in the ledger.
6. **Which automatic events earn a tick, and on which cards?** First cut in §4.3.
7. **Stale threshold**: `3 × cadence, min 10 min` — or a flat 15 min everywhere?
8. **Personality**: the truth strip's calm state ("Everything in range. Nothing to see; go and
   look at the corals.") — yes, under the Cheeky toggle?

## 8. Decisions — LOCKED 2026-09-13 (Reece's answers to §7)

1. **Modes die.** Numbers / Graphs / Gauges and `_liveStatsMode` go; the card is the card.
   Cards / List is the only switch (List lands in v2, so v1 ships with no switch at all).
2. **Needs a look MOVES the card** out of its group. Group counts read "2 sensors · 1 needs a
   look" so nothing looks missing.
3. **Rate windows are per group.** Water changes slowly, air changes fast:
   - *slow* — `tank`, `sump`, `chemistry`, `water`: now = **30 min**, context = **2 h**
   - *fast* — `room`, `flow`, `lighting`: now = **15 min**, context = **60 min**
   - `safety` and any binary sensor: no direction line.
   One table in the panel (`_liveRateWindows`), never inline numbers.
4. **Projection horizons: 3 h** for "hits the limit", **6 h** for "back in range". Beyond that
   the line says only toward / away.
5. **One global marker.** `liveStats.marker = { at, label }` in config; it joins the stale-save
   guard. Clearing it clears every Δ.
6. **Automatic event ticks are user-configurable** (v2): a default relevance map (AWC → tank
   temp / salinity; feed → pH / CO₂; cooling fan / vent / dehumidifier → room temp / humidity /
   tank temp; lights → pH / tank temp) and a Settings list where each event kind can be turned
   off. No per-card matrix — that's a spreadsheet, not a setting.
7. **Stale = 3 × the sensor's observed cadence, floor 10 min, cap 60 min.** Cadence is the
   median gap in the ring buffer; unknown cadence (fresh reload) falls back to 15 min. Stale
   suppresses the direction line and hollows the endpoint; it does not alert — that stays the
   backend's job.
8. **Personality on the calm truth strip only**, under the Cheeky toggle, per the standing
   rule: never when anything is warning, critical or stale.

### 8.1 Build order

- **v1 (one release):** direction line + always-on sparkline (band, last-hour highlight,
  endpoint, hover) + truth strip + Needs-a-look + stale pill + 24 h footer + global marker.
  Modes removed. Ring buffer for slopes with history fallback.
- **v2:** List density, automatic event ticks with the Settings list, acceleration hint.
- **Later:** typical-day ghost line, room ↔ tank coupling, direction-line tap → 6 h trend.

## 9. v1 — shipped as 0.7.171 (2026-09-13)

Panel-only. No backend change: the mark is written by the panel into `display.liveMarker`, which
`_deep_merge` carries through normalisation untouched, and nothing server-side writes it.

- **Modes gone.** `_liveStatsMode`, its localStorage key, the picker and the gauge are deleted.
  `_loadLiveSparklines` runs whenever the Live tab is open (same 4-minute cap, sequential), and
  patches each card in place as its history lands (`_liveRefreshCard`), then the truth strip.
- **Two sources, one series.** `_recordLiveReadings` runs on every hass push and keeps a 2 h
  ring per numeric sensor (`_liveReadings`, cap 240, deduped by `last_reported` stamp — a flat
  sensor that keeps reporting still counts as alive). `_liveSeries` = recorder history + ring
  points newer than it; the sparkline, hover, Δ and 24 h stats all read that.
- **Direction** (`_liveDirection`): slope from `_linearFit` over the group's "now" window
  (`_liveRateWindows`: 30 min water / 15 min air), ring first, history as fallback, ≥ 3 points
  or nothing is said. Speed vs the safe band: < 1.5 %/h steady `→`, < 8 %/h `↗ ↘`, else `↑ ↓`.
  Toward/away from the nearer limit colours the arrow amber/green. Projection: `hits <limit> ≈
  HH:MM at this pace` within 3 h; out of range → `back in range ≈ HH:MM` within 6 h or `still
  moving away`. The context-window slope is computed and carried (`rateContext`) but not yet
  shown — that is v2's acceleration hint.
- **Stale** (`_liveStale`): age from `last_reported`; threshold `_liveStaleAfterMinutes` = 3 × the
  ring's median gap, floor 10, cap 60, flat 15 until the ring holds four readings. Stale wins the
  pill (`stale 38 min`), hollows the endpoint, and replaces the direction line with "no fresh
  readings". It never alerts.
- **The mark**: one global `{ at, label }`. `+ Mark this moment` opens an inline box (Enter or
  *Mark now* saves via `_persistConfigSilently`, ×  clears). Every card shows `Δ since HH:MM`
  from the reading nearest the mark (30 min tolerance, "—" when the history does not reach it);
  the sparkline draws a dashed tick. Automatic ticks from the ledger are v2.
- **Page**: truth strip (`_liveTruthMarkup`: one sentence + four counts; attention sentences
  carry the direction — *"Humidity is high but falling 1.60 %/h — back in range ≈ 16:42"*; the
  calm line is cheeky/professional via `_tone()`), *Needs a look* group at the top holding every
  warning/critical card (moved; its home group reads "2 sensors · 1 needs a look"), groups in the
  old order, legend under the grid. Cards are `auto-fill, minmax(300px, 1fr)`.
- **Sparkline** (`_liveSparkSvg`): 320×84 viewBox in an `aspect-ratio` box, 24 h x-domain ending
  now, y = union of band and readings ± 12 %, dimmed history + bright last hour sharing a boundary
  point, band fill + dashed edges + min/max labels, endpoint dot with a surface ring, hover
  crosshair + `HH:MM  value unit` tip (delegated `pointermove` on the shadow root).
- **Tests**: `tests/test_panel_live.mjs` (18) — windows, every direction branch, the history
  fallback, stale threshold table, ring dedupe/trim, series merge, mark Δ and "—", the move to
  Needs a look, the truth strip in both voices, the sparkline's parts.
- **Not done in v1**: List density, automatic event ticks + the Settings list, the acceleration
  hint (§8.1 v2); per-sensor speed thresholds; the typical-day ghost line.

## 10. v2 — shipped as 0.7.172 (2026-09-13)

Still panel-only. The three §8.1 v2 rows, plus one correction v2 forced.

- **The series is one line now.** v1's `_liveSeries` appended only ring readings newer than the
  history, and `_liveSlope` read the ring *first* — so the 60-minute context window, when the
  ring held three readings, was just the last quarter-hour again and no pace could ever show.
  Now `_liveSeries` = history up to where the ring begins, then the ring (finer, authoritative
  where it exists), and every slope reads that one series.
- **Pace** (`direction.pace`): `|rate_now| > 1.5 × |rate_context|` → *picking up*; `< 0.5 ×` →
  *easing*; a sign change against a context that was itself moving (≥ 1.5 %/h of the band) →
  *just turned*. Steady never has a pace. Shown as `· picking up` after the rate on the card,
  and in the truth strip as *"but falling 1.60 %/h and picking up"* / *"but now falling …"*.
- **Ledger event ticks** (`_liveEvents`): the activity ledger carries only `{timestamp, message,
  type}`, so kinds are read off the message (`_liveEventKinds`): **water** (`^(Scheduled )?water
  change`), **feed** (hand feeds, brine/rotifer feeds, shelf doses, enrichment), **equipment**
  (` switched (on|off)` — hand switches and the cooling arc's fans/dehumidifier alike). Each
  kind lists the groups it can plausibly move (water → tank/sump/chemistry/water; feed →
  tank/sump/chemistry; equipment → tank/sump/room/flow/lighting). Last 24 h, newest first, cap
  12 per card. Drawn as short amber ticks on the baseline, each with its message as a native
  `<title>` tooltip — quieter than the keeper's mark on purpose. Mode changes and lights are
  not in the ledger, so they get no tick (§8.6's map, trimmed to what exists).
- **Settings → Live Stats**: one toggle per kind (`display.liveEventTicks[kind] = false` to
  switch off; absent = on). Client-written; no guard.
- **List density**: `Cards | List` in the section head (`openreef:liveDensity:v1`, view-only
  localStorage like the other view toggles). One row per sensor — name + group, value, a
  200×28 mini sparkline (band, both segments, ticks, endpoint; no labels), the direction line,
  the pill — Needs a look first, then the group order, the moved row reading "Environment ·
  needs a look". Binary/unmapped rows are plain articles. Phone: the row collapses to name +
  value + pill. `_liveRefreshCard` patches a row or a card by the current density.
- **Hover** reads its geometry off the wrapper (`data-live-geom="W,padL,padR"`) so the mini
  and the full sparkline share one handler.
- **Tests**: `tests/test_panel_live.mjs` 18 → 23 (pace ×2, event kinds, tick relevance +
  Settings, list density).
- **Later** (unchanged): per-sensor speed thresholds; typical-day ghost line; room ↔ tank
  coupling; direction-line tap → 6 h trend.

## 11. The trend modal, and the switch you could not see — shipped as 0.7.173 (2026-09-13)

Reece, first real-HA look (2026-09-13): *"it looks great, much better. can we extend the look to
the individual sensor cards please (when clicked and opened larger) — they still have the old
bland styling. also the 'cards/list' selector is hard to see."*

- **The switch.** `.compact-button` carries size only; the Cards | List buttons had no
  background rule of their own and inherited HA's default white button. `.live-density button`
  now wears the panel's secondary look (`#172536` on `#294055`), accent when active. Same rule
  serves the modal's range switch.
- **The trend modal in the card's language.** `_trendSvg(points, unit, range, digits, opts)`
  draws 640×240: the safe band with dashed edges (labelled where they sit clear of the range's
  own min/max gridlines), the area gradient, the dimmed line (`#4f7799` here — a touch brighter
  than the card's, it is the subject) with the last hour bright, OpenReef's event ticks and the
  keeper's mark wherever the chosen range reaches them, an endpoint dot (hollow when stale),
  and the shared hover — the wrapper carries `data-live-source="trend"`, the x-domain and the
  range, so `_liveSparkHover` reads the modal's points and formats a date beyond a day.
- **The header** is the card's: label + pill, the big reading, the direction line. Ranges are
  the compact switch. The three tiles became a stats row: Latest · Low · High · **Average** ·
  **Since <mark>** (Δ, or "—"). The entity id survives as one small line at the foot.
- **Hand-logged parameters** (`source: "manual"`) get the band from their own min/max and the
  chart, nothing from the ring, the mark or the ledger — "Hand-logged results" where the
  direction line would be.
- **Tests**: 23 → 25 (a live sensor's modal; a hand-logged one).

## 12. The typical day, room ↔ tank, and the six-hour tap — shipped as 0.7.181 (2026-09-14)

Reece asked for the three parked ideas together. Panel-only; no backend change.

- **Typical day** (`_liveGhostHours`): the loader fetches seven days of hourly statistics per
  sensor (`recorder/statistics_during_period`, period hour, refetched hourly — `_liveGhosts`,
  `LIVE_GHOST_TTL_MS`) and folds them onto the clock: the mean of each hour-of-day across the
  days that have it, null until four days do. A card draws it only when four days exist and at
  least twelve hours are covered (`_liveGhost`). `_liveGhostValueAt` interpolates between hour
  centres (:30) and wraps midnight; `_liveGhostPath` samples every 20 min and lifts the pen
  across gaps. Faint dashed slate, behind the area — never a colour. The y-scale includes it.
  Drawn on the card, the list's mini and the modal at 1 h / 6 h / 24 h (never across a week).
  The foot gains `typical now 25.3`; the legend gains "typical day (7-day average)".
- **Room ↔ tank** (`_liveCoupling`): pairs every tank/sump-group temperature with the first
  room-group temperature (`_liveCouplingPairs`, by ° in the unit or "temp" in the label). Both
  merged series are resampled onto a 10-minute grid over the last 24 h (`_liveResample`:
  linear, null before the first reading, past the last, or across a > 3 h gap; the room grid
  starts six hours earlier so every lag has a partner). Pearson r and the regression slope at
  every lag 0…6 h; the best r wins. Reported only when ≥ 12 h overlap, r ≥ 0.6, slope > 0, and
  both actually moved (room variance ≥ 0.01, tank ≥ 0.0004 — a heater-held tank says nothing).
  Card line under the direction: *"↔ follows the room by ~2 h · each 1 °C in the room ≈ 0.30 °C
  in the tank"* (or "tracks the room closely" under 20 min); hover shows r. Cards only — the
  list is too narrow. Recomputed per render: 37 lags × 145 points, nothing.
- **Six-hour tap**: the direction line carries `data-trend-range="6h"`; the `show-trend` click
  reads the nearest `[data-trend-range]` and passes it to `_loadTrend`, so the line opens the
  window the arrow was judged in and the rest of the card still opens the day. Hover tint on
  the line inside the card.
- **Tests**: 25 → 30 (fold + interpolation + midnight wrap + the four-day floor; ghost placement
  on card/mini/modal and its absence; the tap attribute; a synthetic 2 h / 0.3 coupling found
  within 10 min and 0.05; the four refusals; lag labels).
