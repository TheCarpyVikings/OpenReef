# Cultures code audit — 10 September 2026

The audit found calculation, state-transition and recommendation defects. The confirmed defects below are corrected in the workspace, with regression coverage. The code can calculate volumes and elapsed time; it cannot establish culture density, water quality, nutritional adequacy or animal viability from those numbers alone.

## Scope

Reviewed the rotifer and Tigriopus engine in `cultures.py`; configuration normalisation, sensor readings, summaries, stock ledgers, harvest destinations, enrichment, bottle actions, seeding, splitting, restarts and reminders in `__init__.py`; culture contributions to the NPS feed timeline in `nps.py`; culture settings, instructions, calculations and reminders in `openreef-panel.js`; and the public live-cultures page. Existing tests were checked for expectations that encoded the defects, then corrected alongside new regressions.

No live Home Assistant settings, aquarium devices or notifications were operated. Nothing was deployed. Other work changed the checkout during this audit. For release 0.7.164, the audit changes were reapplied in an isolated checkout on top of 0.7.163, preserving direct-to-tank harvesting, species coverage and the tidied culture tiles from 0.7.161–0.7.163. Unrelated edits in the original workspace were left alone. The release commit contains the audit changes and its version bump.

## Confirmed defects and corrections

| Priority | Finding | Corrected behaviour |
| --- | --- | --- |
| High | A cone's refill replaced the crop but omitted water discarded in the preceding purge. | Replace crop **plus purge**, debit the stock-water share of that total, and show both volumes. Warn when combined withdrawal exceeds 30% of the working volume; refuse withdrawals exceeding the whole vessel. |
| High | A target above the mixing stock's salinity produced a plausible-looking dilution recipe by changing the target. | Preserve the requested target and mark dilution unavailable. Related actions refuse before changing their ledgers. |
| High | Mixing instructions labelled stock water with the culture's lower target salinity. The rig could also display another cone's recipe. | Label stock and target separately, and use the due cone's named recipe. |
| High | Starter acclimation assumed the target culture salinity was a measurement of the incoming pouch. Fill instructions could underfill the jar after a sieve transfer. | Require an actual starter-salinity measurement for numerical acclimation. Use the entered starter volume and mass-balance additions; sieve/rinse into the full prepared jar volume and discard shipping water. |
| High | Bottle top-ups could renew old or unknown freshness and enrichment claims. Overflow was recorded as if all water had entered the bottle. | Preserve the oldest or unknown load age; preserve the oldest enrichment timestamp only when all mixed stock qualifies. Plain additions clear the enrichment claim. Record only the volume accepted. |
| High | Enrichment could be acknowledged before completion, or gain a new boost window when acknowledged late. | Refuse an enrichment claim before the configured soak completes. Keep the original harvest age and use the scheduled soak end for the boost timestamp. An unverified overdue warm portion cannot acquire a fresh bottle age. |
| High | Feeding from an empty bottle could log a phantom dose; consuming its last dose prevented a useful undo. | Refuse empty/stale stock and invalid amounts, cap a feed at the available volume, and preserve the batch identity so the last dose can be undone. |
| High | A combined feed/sign/harvest tap could write some records before failing the harvest. | Validate establishment, volumes, available salinity and soak capacity before writing feed, sign, inventory or history changes. |
| High | Split and sibling-seed actions could use incompatible or unsuitable sources; split water charged the whole fill to stock rather than its diluted share. | Require a different jar of the same species and an appropriate healthy source. Splitting requires maturity and suitable observations. Charge only the stock share and validate before creating the destination. |
| Medium | Generic reminders could bypass the first-harvest establishment wait or round a half-day culture cadence into whole days. Long cadences could be clamped to generic maintenance limits. | Backend, dashboard and NPS reminders use the actual culture chore clock. Preserve fractional-day schedules and the culture-specific 90-day upper limit. Idle/crashed jars do not acquire harvest reminders. |
| Medium | A complete restart left old harvest/water-change debt and old slow-clearing evidence active. Disabling calendar restarts could hide warning signs. | Reset the relevant exchange clocks, limit slow-clearing evidence to the current run, and retain sign-driven inspection/restart prompts even without a calendar interval. |
| Medium | Bottle demand could recommend harvesting before the jar had recovered. Multiple jars were selected by order rather than earliest eligible harvest. | Respect the jar's recovery clock even when the bottle is empty, and compare eligible harvest times. |
| Medium | Routine preventive restarts were treated as failures, progressively shortening the learned restart interval. Harvests were treated as feeds even when no feeding was recorded. | Only repeated recorded crashes can suggest a shorter restart interval. Clearing samples require actual feeding, including an explicitly recorded feed combined with a harvest. |
| Medium | Usage/yield averages could count three daily events over two elapsed intervals. Undo, future rows and zero-use days distorted estimates. | Average over observed calendar days, including today and zero-use days; ignore undone/future events in these volume estimates. Label harvested water volume separately from biological output. |
| Medium | Short history retention discarded records needed for learning and frequent bottle feeding. | Retain up to 600 jar and bottle records. Existing discarded history cannot be recovered. |
| Medium | The NPS timeline treated discarded culture water as the volume dosed into the tank. | Use a separately reported rinse/feed volume (`tankMl`) for direct tank harvests. Leave dose volume unknown when it was not measured. Preserve the recorded harvest destination. |
| Medium | Temperature inputs were assumed to be Celsius, and a missing primary sensor blocked a valid fallback. An unsorted forecast could select a later heat crossing. | Convert Fahrenheit/Kelvin, reject invalid readings, fall back to the configured alternate sensor, and sort forecast timestamps before selecting the first crossing. |
| Medium | Invalid numeric overrides and ambiguous timestamps could leak into calculations. | Share finite, bounded cadence validation between the engine and normaliser; reject timezone-free culture timestamps and treat unknown/future bottle ages as unverified. |
| Medium | A zero egg observation was lost as “missing”; new rotifer jars could use 35 ppt despite the 27 ppt preset. Initial seed feeding did not debit food. | Preserve explicit zero observations, initialise species salinity consistently, and debit the feed already recorded during seeding. |
| Medium | Recommendations inferred ammonia, crash timing, superior purge volumes, heat immunity or nutritional completeness without measurements. Copepod advice inherited rotifer harvest-debt logic. | Use species-specific inspection advice, observational comparisons and explicitly conditional presets. Remove the unsupported certainty from the dashboard, engine notes and public page. |

## Calculation checks

The dilution model uses zero-salinity RODI and a volume-based approximation:

```text
crop ml        = working litres × 1,000 × harvest percentage / 100
replacement ml = crop ml + separately discarded purge ml
stock ml       = replacement ml × target ppt / stock ppt
RODI ml        = replacement ml − stock ml
```

For **2.5 L at 27 ppt**, a **25% harvest plus 50 ml purge** removes **675 ml**: 625 ml crop and 50 ml purge. From 35 ppt stock, the displayed refill is **521 ml stock + 154 ml RODI**. Integer-millilitre rounding conserves replacement volume and gives approximately 27.015 ppt. A complete 2.5 L fill uses **1,929 ml stock + 571 ml RODI**. A 40 ppt target cannot be made by diluting 35 ppt stock.

The regression matrix covers **225 combinations** of vessel volume, withdrawal percentage, target salinity and stock salinity. For valid dilution, stock and RODI sum to the replacement volume and rounding contributes no more than half a millilitre of stock error. Actual salinity is mass-based and depends on measurement conditions: verify the prepared water with a calibrated instrument rather than treating this hobby mixing approximation as laboratory accuracy.

Acclimation additions use `(old salinity × old volume + incoming salinity × added volume) / new volume`. Tests check the volume and salinity after each addition. The maximum-step limit reports an incomplete plan instead of claiming the target was reached. Extra water used for acclimation and rinsing is separate from the jar's fill/refill debit and must be logged separately in stock use.

Three 625 ml harvests on three consecutive calendar days now give **625 ml/day**, rather than dividing by the two intervals between observations. This remains a recent water-throughput estimate, not a count of rotifers or copepods. Including the current partial day can temporarily lower the average before today's actions are logged.

## Recommendations checked against primary sources

**Rotifer culture.** Reefphyto's guide supports density-dependent first harvesting around days 5–7 and partial harvests around 25–30%; its kit page gives a longer initial establishment allowance. The 6-day first-harvest clock is therefore an earliest inspection prompt, not proof of readiness. The 27 ppt target is a starting preset; the supplier gives a brackish SG range and FAO describes salinity-dependent reproduction. Neither source establishes that a fixed salinity or a fortnightly restart guarantees survival. [Reefphyto culture guide](https://reefphyto.co.uk/pages/rotifer-culture-guide), [culture kit instructions](https://reefphyto.co.uk/products/rotifer-culture-kit), [FAO rotifer production](https://www.fao.org/4/w3732e/w3732e0h.htm).

**Copepod culture.** The supplier supports daily observation, a longer establishment period, conservative harvesting and water-quality checks. The retained 28-day first inspection, 10-day harvest spacing and 25% volume preset are configurable starting points. Tigriopus is bottom-dwelling: removing 25% of water does not establish that 25% of the population was removed. The supplier's dedicated guide and blog differ on routine water-change practice; the app does not present one calendar as universally optimal. Test water quality weekly, respond to ammonia/nitrite, replace harvested water with matched saltwater, and replace evaporation with RODI. The last distinction follows salt balance even where supplier wording is inconsistent. [Reefphyto copepod guide](https://reefphyto.co.uk/pages/copepod-culture-guide), [supplier culture article](https://reefphyto.co.uk/a/blog/how-to-successfully-culture-copepods).

**Feed and enrichment.** Food dose depends on concentration and population density. Reefphyto's enrichment product gives 1–5 drops and a 6–12 h soak; that supports a configurable 6 h default for that product, not a universal dose for every brand or volume. The inventory assumes 0.05 ml/drop, an estimate that should be calibrated for the dispenser. FAO describes food-dependent nutritional value; completing a timer cannot prove DHA content or a complete diet. [Reefphyto enrichment directions](https://reefphyto.co.uk/products/rotifer-artemia-enrichment), [feed concentrate](https://reefphyto.co.uk/products/rotifer-feed-concentrate), [FAO nutritional value](https://www.fao.org/4/w3732e/w3732e0i.htm).

**Storage.** The supplier describes refrigerated storage up to five days for its supplied rotifers. The app's five-day bottle limit remains a handling estimate, not validation of every home-harvest density or refrigerator. The 8 h warm / 24 h cold boost windows are planning assumptions, not verified universal nutrient-retention limits. Top-ups and late button presses now preserve age correctly within those assumptions. [Reefphyto rotifer FAQs](https://reefphyto.co.uk/pages/live-rotifers-faqs).

**Temperature and acclimation.** FAO describes salinity differences greater than about 5 ppt as needing acclimation; it does not validate the app's 15-minute wait as sufficient for every starter. Temperature tolerance also varies with population and conditions. The heat tiers are precautionary prompts to inspect and protect the culture, not measured lethal limits; room/forecast temperature is not necessarily culture-water temperature. [FAO production guidance](https://www.fao.org/4/w3732e/w3732e0h.htm), [Willett, 2010: variation in Tigriopus thermal-stress survival](https://onlinelibrary.wiley.com/doi/full/10.1111/j.1558-5646.2010.01008.x).

## Verification

Before release, all **47 discovered standalone suites passed** on the merged 0.7.164 checkout: 28 Python suites and 19 dashboard suites. Culture and adjacent checks included:

- Python: `test_cultures.py` (62), `test_cultures_audit.py` (26), `test_nps.py` (175), `test_config_migration.py` (62), `test_mixing.py` (111), `test_salinity_sg.py` (12), `test_maintenance.py` (45), `test_save_guards.py` (12), and `test_hatchery_audit.py` (17).
- Dashboard: cultures (34), maintenance (17), mixing (45), NPS (61), and Pulse (57).
- Python compilation, dashboard JavaScript syntax, and `git diff --check` passed.
- The site's TypeScript/Vite production build passed, with the existing non-blocking large-bundle warning.

That is **122 culture-focused checks**, plus adjacent regression coverage. The new audit cases exercise volume conservation, timestamps, input validation, species boundaries, oldest-stock handling, undo, rejected-action atomicity, fractional reminders, observations used in learning, enrichment timing and dose-volume attribution. Tests use fake Home Assistant and a dashboard rendering harness. No live device, pump, culture-water or physical rig test was performed.

## Files changed for this audit

- `custom_components/openreef/cultures.py` — calculations, clocks, learning and advice.
- `custom_components/openreef/__init__.py` — validation, ledgers, lifecycle actions, sensor units and reminders.
- `custom_components/openreef/nps.py` — culture reminder timing and actual tank-dose attribution.
- `custom_components/openreef/const.py`, `custom_components/openreef/manifest.json` — release version 0.7.164.
- `custom_components/openreef/frontend/openreef-panel.js` — displayed calculations, settings, observations and advice.
- `site/src/pages/live-cultures.tsx` — matching public claims.
- `tests/test_cultures.py`, `tests/test_nps.py`, `tests/test_panel_cultures.mjs` — corrected expectations and integration/UI coverage.
- `tests/test_cultures_audit.py` — new regression suite.
- This report.

## Remaining limits and next step

Calendar ages, tint, feed volumes and egg observations cannot confirm organism density, oxygen, ammonia or viability. Learned suggestions remain sensitive to reporting frequency, changed doses and environmental conditions. Historical records missing feed flags, actual tank volume, salinity or age cannot be reconstructed. The heat forecast's ±5 °C offset cap is a chosen model bound, not a physical limit. The rig is an illustration, not hydraulic verification.

After reviewing the changes, load them in a controlled Home Assistant session and compare one measured fill, one harvest plus purge, one enrichment cycle and one bottle feed/undo with the displayed volumes and timestamps. Check the saved species, working volumes, actual stock salinity, feed product and refrigerator conditions before relying on the revised estimates. Deployment remains a separate step.
