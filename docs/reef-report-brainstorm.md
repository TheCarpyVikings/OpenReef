# The Reef Report — weekly and monthly (design brief, 2026-09-16)

> Reece's ask: "generate a weekly/monthly report with a breakdown of all
> maintenance tasks done, tests, hatches, cultures, feeds, important actions,
> plus anything valuable in a reef report. Provide a plan for the coming
> week/month with recommendations. Show trends, possibly reef score, so it
> helps the user track if they need to make more effort. Weekly and monthly
> should focus on different recommendations — small vs big."

Status: **brief only, nothing built.** Stage A's foundation (the maintenance
log, 0.7.196) shipped the same day this was written.

## 1. Why this is the next headline

OpenReef's identity is "the intelligence layer for reefing". Every engine so
far answers a question *now* (is the hatch ready, is alk drifting, is the
room too humid). The report answers the question a keeper asks on a Sunday:
**how did the week go, and what should I change?** Nothing on the market
writes that sentence.

What the field does today (research 2026-09-16):

- Loggers (Aquarimate, Reef Trak, AquaticLog, ReefBay, Reefability) record
  parameters, tasks, dosing, livestock and photos, and draw trend graphs. The
  keeper still reads the graphs and draws the conclusions.
- NextUpReef scores the tank twice: a *Reef Score* (closeness of parameters to
  ideal, logging consistency, water changes, equipment completeness) and a
  *Stability Score* (how steady parameters stay between logs, maintenance
  reliability). That split — condition vs consistency — is worth borrowing.
- Reef Analysis pulls live controller data and overlays *events* on trend
  charts so a keeper can tie a parameter move to an action. Cause next to
  effect is the single most useful thing a report can show.
- Apex Fusion: graphs and a data log. No narrative, no plan.
- Keeper guides agree on cadence: alk/Ca/Mg weekly (alk is the volatile one),
  salinity/NO3/PO4 weekly, mechanical media weekly, pumps and heads monthly,
  and "stability over chasing numbers".

The gap: **a written, opinionated, evidence-backed report that combines what
the keeper did with what the system did** (auto water changes, hatches on
their clocks, feeds on their windows, cultures on their journals) and ends in
a plan. OpenReef already holds every ledger needed. The report is a reader
over them.

## 2. Principles (locked unless Reece says otherwise)

1. **Only what was logged.** The report never guesses a water change happened.
   Untested parameters say "not tested this week", and that itself becomes a
   recommendation. Honesty is the product.
2. **Explainable, like Reef Health.** Every score shows its parts; every
   recommendation shows the evidence line it came from. No black box.
3. **Read the ledgers, not the activity log.** Activity is capped at 200 lines
   and is a stream, not a store. The report compiles from maintenance
   completions, manual tests, ICP results, dosing history, AWC history, the
   mixing ledger, the NPS feed log, hatchery history, culture journals, the
   coral diary and capture events. Anything the report needs that is not
   stored today gets a bounded ledger (§4 lists two).
4. **Backend compiles, panel renders.** `report.py` is a pure engine (config +
   now → report dict), the same shape as `nps.py`, `cultures.py`,
   `livestock.py`. The panel never re-derives a number. LOCKSTEP by reading.
5. **Compiled reports are stored, compactly.** A report is a snapshot; the
   ledgers it read will roll over. `reports.items` keeps 26 weekly + 12
   monthly. Server-owned, so it **joins the stale-save merge guard**.
6. **Small vs big.** Weekly recommendations change *behaviour this week* (test
   alk, feed the pods, start the hatch Tuesday night). Monthly recommendations
   change *the setup* (add a hatchery, raise the water-change target, switch
   dosing method, recalibrate, order salt). Both are capped so the report
   never nags.
7. **Tone.** The comic voice is allowed on the calm parts (a good week is
   allowed a line); never on anything that reads as a warning. Safety alerts
   are listed as facts.

## 3. Report anatomy

### 3.1 Weekly (Monday morning, covering Mon–Sun)

| Section | Content | Reads |
|---|---|---|
| **Headline** | Reef Week Score with delta vs last week, one-sentence verdict, the week's photo | score log, captures |
| **What you did** | Counts by domain (tasks, tests, feeds, hatches, harvests, check-ins); on-schedule % and streaks; water changed (L and %) hand vs auto | maintenance completions, AWC history, feed log, hatchery history, culture journals, coral diary |
| **Water** | Table per parameter: latest, 4-week sparkline, stability band (steady / drifting / swinging), days since tested; Alk/Ca/Mg consumption per day and its change; ICP flags if a result landed | manualTests, sensors (recorder), consumption advisor maths, ICP |
| **Living reef** | Hatches (n, learned hours vs clock, lateness), cultures (harvests, tint/clearing signs, any sign of a crash), feeds (windows hit vs missed, truce lane), corals (check-ins done, score moves, colonies overdue a look) | hatchery, cultures, NPS feed log, livestock |
| **What happened** | Alerts and escalations, mode changes, equipment interlocks, cooling headroom events, spawning runs, salt/consumable low events | alerts, activity (for the week only), cooling, spawning, shelf |
| **Cause next to effect** | Two or three annotated moments: a parameter move with the action beside it ("alk fell 0.6 dKH the day the doser ran dry") | manualTests + dosing + AWC timelines |
| **Next week** | Due tasks by day (the Coming up buckets), hatch starts on the plan, culture harvests, tests to run, water on hand vs planned changes | maintenance evaluator, next-hatch plan, culture clocks, mixing ledger |
| **Recommendations (small)** | At most three, each with evidence, effort, expected effect | §5 |

### 3.2 Monthly (1st of the month, covering the calendar month)

Everything weekly at month scale, plus:

| Section | Content |
|---|---|
| **Score trend** | 3-month score line with sub-scores; month-over-month deltas |
| **Cadence drift** | Which tasks you are consistently late on (the trends cards, ranked); which streaks held |
| **Consumption trend** | Alk/Ca/Mg demand per month — rising demand = growth, falling = check the doser or the corals |
| **Water change ledger** | Total vs target, hand vs auto, salt used vs stock, RODI drawn |
| **Testing discipline** | Tests per parameter vs the cadence the keeper set; gaps |
| **ICP** | Compare to the previous result; trace-element movers |
| **Livestock** | New colonies, scores over the month, photo pairs (first vs last) |
| **Equipment ageing** | Carbon / socks / calibrations by age; heater and pump hours if metered |
| **Recommendations (big)** | At most three structural changes, each with the month of evidence behind it |
| **Goals** | What last month's report recommended and whether it happened |

### 3.3 Score — "Reef Week Score" (0–100, explainable)

Five sub-scores, weighted, each with a "why" line and a "what would raise it":

| Sub-score | Weight | Built from |
|---|---|---|
| Chemistry stability | 30 | Reef Health's chemistry parts + week-over-week variance per parameter (steady beats perfect) |
| Care consistency | 25 | on-schedule % across tracked tasks, tests done vs cadence, water-change target met |
| Nutrition | 15 | feed windows hit, hatches on time, cultures healthy, dose plans followed |
| Livestock wellbeing | 15 | coral diary scores and check-in coverage, confidence clocks |
| System reliability | 15 | alerts, interlocks, equipment faults, sensor health, AWC/doser refusals |

Rules: a sub-score with no data scores neutral and says so (never a hidden
zero); the headline delta compares like with like. The score borrows the
NextUpReef split — condition (Chemistry, Livestock) vs consistency (Care,
Nutrition, Reliability) — and shows both totals so a keeper can see "the
tank is fine, you are slipping" as its own sentence.

## 4. Data inventory

| Domain | Store today | Report reads | Gap |
|---|---|---|---|
| Maintenance | `maintenance.completions[task]` (cap 200 per task), the Log view (0.7.196) | done/skipped/volume/newWater/source per entry | none |
| Manual tests | `manualTests` results | value per parameter per date | none |
| ICP | ICP importer results | flags, movers | none |
| Reef Health | computed live in the panel and backend | current score only | **score log**: a daily `{date, total, parts}` row, cap 400 days, backend-stamped |
| Dosing | channel history, consumption advisor | ml per day, refusals, reservoir events | consumption maths lives in panel JS — port the projection to Python for the compile |
| AWC | `awc.history` | drained/filled/method/partial per run | none |
| Mixing station | contents ledger, activity | batches mixed, salt used, RODI drawn | none |
| NPS feeds | `nps.feed_log` sweep, feeding windows | windows hit/missed, doses, truce | none |
| Hatchery | `hatchery.history`, per-vessel state | hatches, learned hours, lateness | none |
| Cultures | per-jar journals (`_chronological`) | feeds, looks, harvests, signs, purges | none |
| Corals | livestock registry + check-ins + photos | scores, check-ins, photo pairs | none |
| Alerts / modes / interlocks | `activity` (cap 200) + alert state | events for the week | **event ledger**: a bounded `events` list (cap 500, `{at, kind, summary, severity}`) written by the same choke points that write activity — activity keeps its cap, events keep the month |
| Cooling / spawning | own state + activity | runs, triggers | reads the event ledger |
| Camera | captures, timelapse | photo of the week (pick: the feed-watch or the capture with the highest score, else the latest) | none |

Two new bounded ledgers, both server-written, both joining the stale-save
guard: **score log** and **event ledger**. Everything else is a reader.

## 5. Recommendation engine

Rule-based, explainable, capped. Each rule yields
`{id, size: "small"|"big", title, evidence, effort, effect, actions[]}`;
actions are panel deep-links (open the task, open dosing, snooze this rec for
a month). Rules are pure functions of the compiled report so they are
unit-testable from fixtures.

Small (weekly) examples:
- Alk not tested for 9 days → "Test alkalinity today" (evidence: last test
  date, consumption trend suggests ±0.4 dKH drift since).
- Two culture feeds skipped → "Feed the rotifers on the window; tint still
  clearing" (evidence: journal).
- Hatch started late twice → "Start Tuesday's hatch at 22:00 — the plan's
  time, not the morning" (evidence: next-hatch plan vs completions).
- Water change short of target → "One extra 10 % change this week; 32 L is
  standing in the vessel" (evidence: ledger).
- Coral overdue a look → "Look at the Acropora frag — 12 days since the last".
- Nothing wrong → a calm line, and one small habit suggestion at most.

Big (monthly) examples:
- Consistently late on hatch starts across the month → "Add a third hatchery
  or lengthen the cadence" (evidence: cadence drift card + vessels-needed maths).
- Alk consumption up 40 % over 3 months → "Raise the doser's daily plan; the
  corals are growing" (evidence: consumption trend).
- Water-change total under target three months running → "Raise the AWC
  daily volume or lower the target — pick one".
- Calibration older than 60 days on a probe whose readings drifted vs tests →
  "Recalibrate pH; the probe and the kit disagree by 0.2".
- Salt stock below two months of use → "Order salt".
- Tests done sporadically → "Set a test day; Sunday fits your completions".

Caps: three small, three big. A snoozed recommendation stays out until its
month is up. A recommendation that repeats three months running is promoted
to the headline.

## 6. Architecture

```
custom_components/openreef/report.py        pure engine: compile(config, ledgers, now, period) -> report dict
                                            score(report) -> {total, parts[]}; recommend(report) -> [rec]
__init__.py                                 ws openreef/report_compile {period, anchor?}   (on demand, not stored)
                                            ws openreef/report_list / report_get {id}      (stored snapshots)
                                            ws openreef/report_snooze_rec {rec_id}
                                            scheduler: Monday 07:00 weekly, 1st 07:00 monthly (local), + async_setup re-arm
                                            score log + event ledger writers at the existing choke points
                                            push: one digest line with the headline + "open the report"
frontend                                    Reports view (Home tab hero card + a Reports screen off it):
                                            timeline of past reports, the viewer, share (PNG via the overlay/share
                                            pattern, Markdown copy, Telegram), print stylesheet
tests                                       test_report.py (fixtures: one busy week, one empty week, one bad week),
                                            test_panel_report.mjs (render, share, deep-links)
docs                                        this brief, kept as-built
```

Compile inputs stay config-shaped so the fake-HA harness can drive them; the
only recorder read is sensor history for the Water sparklines, behind the
same helper Live Stats uses, and it degrades to manual tests when the
recorder is absent.

## 7. Stages

| Stage | Scope | Release |
|---|---|---|
| **A. Ledgers** | Score log (daily stamp) + event ledger at the activity choke points; both in the merge guard; tests | small, first |
| **B. Compile** | `report.py`: weekly compile of "What you did", "Water", "Living reef", "What happened", "Next week"; WS on-demand; fixtures; no UI beyond a JSON dump behind a dev flag | medium |
| **C. Viewer** | Reports screen: on-demand weekly report rendered; sections collapsible; deep-links; the photo of the week | medium |
| **D. Score + small recs** | Reef Week Score with parts; small recommendation rules; headline + delta | medium |
| **E. Schedule + store + push** | Monday compile, stored snapshots, timeline, digest push line; Telegram share | small |
| **F. Monthly** | Month compile, trends, cadence drift, consumption trend, big recs, goals check | medium |
| **G. Share + polish** | PNG export, Markdown copy, print stylesheet, Pulse card "Last week: 78 ↑" | small |

A–E is the weekly report end to end; F–G make it the monthly one and make it
shareable (the livestream and Discord audience will want the PNG).

## 8. Decisions (Reece, 2026-09-16)

1. **Week boundary**: user-configurable, default Monday–Sunday → `reports.weekStart` (0 = Monday).
2. **Where it lives**: off Home (a hero card, a Reports screen behind it).
3. **Score**: the Reef Week Score sits *alongside* Reef Health (the now score); they share the chemistry parts.
4. **Push**: the headline block as its own Monday push (score, delta, verdict, three counts, top recommendation, link); the digest line is the fallback when push is off. The whole report is never pushed — sharing is the share button's job.
5. **Beta tester**: yes — Stage B reads Trident tests from the recorder from day one, falling back to manual tests.

### 8.1 Stage A as built (0.7.197, 2026-09-16)

- `reports` block in `DEFAULT_CORE_CONFIG`: `weekStart`, `scoreLog` (cap 400, one row per local day), `events` (cap 400). `_normalise_reports` coerces both ledgers, newest first, latest stamp per day wins.
- **Score log is panel-stamped.** Reef Health is panel maths over live HA state (sensor alerts, interlocks, validation); porting it is not Stage A work. The panel calls `openreef/report_score_stamp {date, total, parts}` once per local day (refreshed every six hours it is open, never from a demo). A day the panel never opened is an honest gap — Stage D's Week Score computes its chemistry part backend-side from tests + recorder, and reads this log as "Reef Health as seen".
- **Event ledger rides `_append_activity`.** Every non-info activity (`control`, `warning`) and any caller that passes a `kind` is mirrored into `reports.events` at the same choke point; the activity feed keeps its 200 lines, the ledger keeps the month. `openreef/report_events {days}` reads a window.
- Both ledgers are server-owned and join the stale-save guard (`_reports_preserve_runtime`, both save paths); `weekStart` stays the client's.

### 8.2 Stage B as built (0.7.198, 2026-09-16)

- `report.py` — pure engine: `period_bounds` (week on `reports.weekStart`, month; previous or the partial current), `compile_period(ctx)` → headline (score stamps: latest / average / delta vs the period before / gaps), What you did (per task done / skipped / late with on-time % against each task's own cadence, water changed by hand vs AWC, AWC runs, tests, feeds recounted inside the window, hatches, culture feeds, coral looks), Water (per parameter: tests, sensor samples, latest, days since, four-week points, band steady / drifting / swinging / single / untested on kit-precision tolerances, in-range against the sensor's min/max, a median-fall-per-day consumption estimate for Alk/Ca/Mg that needs two falling pairs), Living reef (hatches with actual vs planned hours, culture journals, coral grades and score moves), What happened (event ledger in the window), Next (the plan by local day), notes (the honesty lines), one calm verdict sentence.
- Backend: `_maintenance_next_due_at` / `_maintenance_upcoming` mirror the panel's Coming up clock (interval, hour cadence, fixed days, snooze, culture and hatch clocks); `_report_context` gathers every ledger; `_nps_feed_log_for` reuses the NPS feed-log engine; `_report_recorder_readings` reads sensor history from the recorder when present (decision 5) and the panel may hand its own `readings` in; `openreef/report_compile {period, which, readings}`.
- Not stored, no UI, no push yet — Stage C renders it, Stage E schedules and stores it.

### 8.3 Stage C as built (0.7.199, 2026-09-16)

- **Off Home**: a "Reef Report" mission card (toggle in Settings → mission cards) reads last week's average stamp vs the week before straight from the score log, and opens the viewer.
- **The viewer** is a dialog (`.report-dialog`, its own class for scroll restore): Week / Month and Last / This-so-far chips, Refresh; headline (average score with its delta and a day-by-day sparkline, the verdict, stamped-days honesty, the photo of the week from the capture ledger), What you did (stat tiles + the per-task table), Water (per parameter: latest and its age, a four-week sparkline over the target band, the stability pill, in-range, the consumption estimate or how many falling pairs it still needs), Living reef (hatchery, each culture jar, corals with grade spread and score moves), What happened, Next week by day, Notes, and the readings source.
- **Deep links**: every task in the table and the plan → the Maintenance tab, All tasks, that row open (`report-task`).
- **Readings**: the panel calls `report_compile`; when the backend answers `readingsSource: "tests"` (no recorder) the panel fetches the mapped chemistry sensors' history the way Live Stats does and compiles again with `readings` — the Trident path works on both sides.
- Charts follow the dataviz rules: one series per line (no legend), 2 px lines, recessive band, text in ink tokens, status only on pills, a title per point for hover.

### 8.4 Stage D as built (0.7.200, 2026-09-16)

- **Reef Week Score** (`report.week_score`): five parts with the brief's weights. Chemistry = the mean over parameters with a trend of steady 100 / drifting 70 / swinging 35, capped at 50 when out of range. Care = the mean of on-time % (when a tick has a tick before it), parameters tested over parameters tracked, and water changed (100 / 30). Nutrition = feeds logged (≥7 → 100, ≥3 → 70, ≥1 → 40), hatches on the clock (≤2 h late 100, ≤6 h 70, else 40), cultures clean 100 / signs 70 / crashed 30. Livestock = the grade spread (A 100 … F 20) minus 10 a dropped colony. Reliability = 100 − 15 a warning − 30 a critical, floor 20. A part with no data is **neutral**: it drops out of the weighting and the card says so. Two totals besides the headline: condition (chemistry + livestock) and consistency (care + nutrition + reliability).
- **Small recommendations** (`report.recommend`): rules over the compiled report, each with evidence, effort, effect and deep-link actions; ranked by priority (culture crash 8, alk untested 10, out of range 12, swinging 15, coral drop 18, culture signs 20, hatch late 25, other tests 30, no water change 35, late 40, skipped 45, closed panel 50); capped at three. A calm week gets "Keep the rhythm". `reports.snoozedRecs` (id → until; expired dropped by the normaliser; rides the guard) hides a recommendation until its stamp passes — `openreef/report_rec_snooze {rec_id, days}` (0 lifts).
- Viewer: the Week Score card sits beside the Reef Health average with a "Why this score" fold (each part's score, weight, why and how to raise it); a Recommendations section under the headline with the actions and "Snooze a month".

### 8.5 Stage E as built (0.7.201, 2026-09-16)

- **Schedule**: `reports.schedule {enabled, time (07:00), push}` (Settings → Maintenance → Reef Report, with the week-start day). One daily tick at that time (`_async_schedule_report`, re-armed on every save like the maintenance reminder) runs `_async_report_tick`: every period that has ended and is not stored is generated — the weekly one the morning the week turns, the monthly one on the 1st, a missed morning caught up the next, a fresh install's first report the next morning.
- **Stored snapshots**: `report.snapshot(report)` keeps the compact record (headline numbers, counts, one line per parameter, the recommendations by title; under 2.5 KB) in `reports.items`, 26 weekly + 12 monthly, newest first, the same period replaced; server-owned, rides the guard. The viewer's "Past weeks / months" timeline draws the scores across periods and re-reads any stored period from the ledgers (`report_compile {anchor}`); "Store this week" (`report_generate`) stores by hand, never pushes.
- **Push** (decision 4): `report.push_text` — the headline block (score with condition · consistency, Reef Health average and its move, the verdict, the counts, the top recommendation, where to read it) to the reminders' push target, its own message the morning it is written. Push off → `_report_digest_line` puts one line in that day's maintenance digest.
- **Ledger hygiene** (found on Reece's tank the same night): the ATO duty cycle said "skipped unavailable ATO" every tick after a restart — the warning saved the config, the save re-armed the scheduler, re-arming ran the handler at once — 397 of the ledger's 400 rows. Now said once per window and state, persisted only when something changed; and the event ledger counts a repeated line up (`count`, `lastAt`, 6 h window) instead of adding rows, with a one-shot collapse of an existing flood on load.

### 8.5a Honest figures (0.7.202, 2026-09-17)

- Reece's report said "Bring salinity back into range — latest 25.312 ppt" with confidence. The figure was a salinity entity left mapped under Settings → Sensors while the sensor was **disabled**: Reef Health ignores a disabled sensor, the recorder read did not, and the copy never said where the number came from.
- Now: the report reads a sensor only when it is enabled AND mapped (`_report_sensor_on`, the panel's rule mirrored, applied to the recorder read and to readings the panel hands in alike); a salinity probe reporting specific gravity is read in ppt; the band is the **keeper's** min/max from Settings → Sensors (MVP defaults behind it, SG bands converted), not the defaults.
- Every "latest" figure carries its source (`latestSource` test|sensor) and the copy names it ("from your test on 9 Sep"). `latestTest` / `latestSensor` sit beside it; `disagree` = the sensor sample nearest the latest test (within a day) more than twice the steady tolerance away; `farOut` = more than one band-width outside the band.
- Recommendation: a sensor reading that is far out, or that the kit contradicts, yields **"Check the salinity reading"** (probe or unit) instead of "Bring salinity back into range" — a probe is never chased as if it were the tank.

### 8.7 Stage F as built (0.7.203, 2026-09-17)

- **Month compile** = the weekly compile at month scale plus `report["month"]` (`month_sections`): **trend** (the stored monthly snapshots before this one plus this compile — score, condition, consistency, Reef Health average — with month-over-month deltas, and the weeks stored inside the month), **drift** (chores with two ticks ranked by the share of late ticks, mean days past the cadence per task from the new `timed` / `slipDays` rows; streaks held), **consumption** (Alk / Ca / Mg median fall a day per calendar month, this month and the two before, from the week's estimator; rising ≥ +30 %, falling ≤ −30 %), **water ledger** (changed by hand / auto against the AWC schedule's planned litres when it is on, else the keeper's recent 8-week rate; salt used from the stock ledger's debits inside the month, kilos on hand, weeks left), **testing discipline** (tests per parameter against the cadence set in Settings → Manual tests, longest gap, and the weekday the keeper's tests actually land on), **ICP** (the month's report against the one before: elements that moved 15 % or a unit floor or changed status; no ICP in the month → days since the last), **equipment ageing** (the built-in consumable / calibration / service tasks by age against cadence, worst first, never-logged said as such; RODI stages by litres through them), **goals** (last stored month's recommendations judged by this compile: cleared when no rule raises the id now, open when one does).
- Readings behind a month reach back 92 days (`lookback_days`), the recorder read and the panel's own history fetch alike, so the consumption trend has three months.
- **Big recommendations** (`recommend_big`, brief §5): recalibrate a probe the kit contradicts (`disagree`, calibration ≥ 60 d or never), hatchery capacity (≥ 4 harvests, > 6 h late on average), demand up / down per consumed parameter, the AWC plan short by a quarter, a test day on the keeper's own weekday (≥ 2 cadences, < 60 % kept), salt under 8 weeks, a cadence to lengthen (≥ 3 ticks, half late), overdue consumables, a spent RODI stage, an ICP ≥ 120 days old. Capped at three, snoozes honoured, a calm month says so; an id recommended in the two stored months before is **promoted** to the top and says "Third month running". `recommend` / `recommend_big` both return `raised` (every rule that fired, before the cap) — the goals check reads the union.
- Viewer (month): Last month's plan (cleared / still open), Score over months (deltas, the month line, the weeks inside it, the table), Cadence drift, Consumption trend, Water ledger, Testing discipline, ICP, Equipment ageing; the headline shows the first and last capture of the month side by side; the Living reef card names colonies added; the push says the move on last month.

## 8.6 Still open

- Report landing time: Monday 07:00 local assumed (a Settings field alongside weekStart in Stage E).
- Which activity choke points should pass a `kind` (mode applied, AWC run, spawning run, cooling trigger) so the "What happened" section can group them — decided per stage as the compile needs them.

## 9. Sources (research 2026-09-16)

- Reef Trak, "Best Reef Tank Apps in 2026" — https://reeftrak.com/blog/best-reef-tank-apps-2026
- Aquarimate — https://www.aquarimate.com/
- NextUpReef features (Reef Score + Stability Score) — https://nextupreef.com/features
- Reef Analysis (events overlaid on trend charts) — https://www.reefanalysis.com/
- ReefBay, "Best Reef Tracking Apps 2025" — https://reefbay.com/blog/best-reef-tracking-apps-2025
- Reef2Reef threads on logging apps — https://www.reef2reef.com/threads/best-aquarium-log-app-software.602703/
- Saltwater Aquarium Blog, "Simple Reef Aquarium Maintenance Scheduling" — https://www.saltwateraquariumblog.com/simple-maintenance-schedule-reef-aquariums/
- The Reefer, "Reef Tank Maintenance Checklist" — https://thereefer.club/reef-tank-maintenance-checklist-daily-weekly-and-monthly-tasks/
- PetPalHQ, "Reef Tank Maintenance Schedule 2026" — https://petpalhq.com/guides/saltwater-reef-tank-maintenance-schedule-2026
