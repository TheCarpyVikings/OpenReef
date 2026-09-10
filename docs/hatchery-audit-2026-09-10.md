# Hatchery code audit — 10 September 2026

The audit found substantive scheduling, storage and state-transition errors, plus husbandry claims that were stronger than their evidence. The confirmed defects below are corrected in the workspace. This is a code and source review, not a validation of the live aquarium or the physical harvest rig.

## Scope

Reviewed the pure hatchery calculations in `nps.py`; normalisation, harvest/enrichment/feed actions, reminders, bottle transfers and summary assembly in `__init__.py`; the dosing guard connection in `dosing.py`; dashboard advice, settings and the rig instructions in `openreef-panel.js`; the public hatchery page; and the existing hatchery tests. Existing unrelated workspace changes were left alone. No live settings, pumps or notifications were operated and nothing was deployed.

## Confirmed defects and corrections

| Priority | Finding | Corrected behaviour |
| --- | --- | --- |
| High | The next-start recommendation selected the cone that freed first, even when another cone could finish the next batch sooner. | Compare free time plus each cone's own next-cycle duration. Respect the selected cone's availability. |
| High | Refrigerated expiry moved forward after the budget was exhausted. The action guard used `>` while the dashboard used `>=`, allowing expired stock through at the boundary. | Calculate a fixed deadline from fridge entry; use an inclusive stale boundary. Cold storage cannot revive spent stock. |
| High | Harvesting into a partly full container renewed the older brine's clock. | Plain top-ups preserve the existing load timestamp and cold credit. Plain harvests cannot dilute a recorded enriched batch while keeping an enrichment claim. |
| High | Soak completion could award enrichment before any dose or before the duration elapsed; acknowledging it late renewed the boost. | Require the same nonempty batch, a logged first dose and the configured duration. Start the boost window at the scheduled soak end. |
| High | Harvests and bottle returns could change a batch during a soak; discarding left its soak running. | Reject those transfers during a soak. Discard clears the soak and boost stamps. A spent batch cannot start enrichment to renew its clock. |
| High | Container and bottle volumes were added under the later expiry, including stock that could not be consumed before its own expiry. | Model first-expiring-first use at the planned rate. Only usable volume contributes to runway; expired stock contributes none. |
| High | Bottle mixing chose the oldest load rather than the batch with the least remaining life. Returns could silently erase overflow. | Compare expiry after the destination temperature change. Reject enriched/plain mixing and transfers that exceed capacity. |
| High | The linked pump's freshness checks ignored hatchery enrichment and cold credit, and could dispense during a soak. | Share the batch calculation with pump guards, enable-state sync and the periodic check. A running soak blocks dispensing. |
| Medium | A current batch's banked refrigeration hours extended forecasts for future batches. | Future loads use the plain warm window; credit stays with the batch that earned it. |
| Medium | Incoming loads were assumed to cover a full shelf window regardless of feed rate and load volume. Earlier gaps could disappear behind the final incoming load. | Cap incoming coverage by expected volume/rate, report the first earlier gap, and show lateness even when starting immediately cannot meet the deadline. |
| Medium | `chainLoadsAt` omitted handling time. Vessel count charged that handling time on every cycle while the rack simulation overlapped it with restarting. | Include the one-hour buffer in load arrival. The ideal steady-state count uses cycle length divided by the usable supply window. |
| Medium | Harvested durations from different vessels were pooled and presented as measured hatch times. | Scope learning to vessel and cyst type. Label it start-to-harvest history, including any delay before harvesting. |
| Medium | Temperature readings were treated as Celsius regardless of units; the cool-room preset could receive a second cold adjustment. | Convert Fahrenheit/Kelvin, reject invalid readings, and avoid stretching the already cool-room preset. Label the model as a heuristic. |
| Medium | A feed could log more volume than remained, including a feed from an empty container. | Record at most the available amount and reject empty feeds. |
| Medium | Harvest reminders replanned from a new timestamp instead of the completed load's actual ledger. | Use the existing batch clock, usable bottle stock and planned depletion after the load. |

## Rechecking the supplied screenshot

The displayed percentages are consistent with the rounded values: `25.7 / 36 ≈ 71%`, `10.3 / 24 ≈ 43%`, and `250 / 750 ≈ 33%`. A rounded soak countdown and an integer percentage can also differ slightly without an arithmetic error.

The next-start choice was wrong for the displayed configuration:

- Hatchery 1 frees in approximately **10.3 h**. Its next 36 h batch, plus the 1 h handling allowance, loads in **47.3 h**.
- Hatchery 2 frees in approximately **13.7 h**. Its next 24 h batch, plus handling, loads in **38.7 h**.
- Selecting Hatchery 2 advances that next load by **8.6 h**. Under the model's 24 h supply window, this removes the claimed unavoidable gap after the last committed load.

This calculation uses the configured clocks. It does not establish the true hatch duration, available food during the current soak, or the actual number of nauplii produced. Earlier supply gaps are reported separately.

## Recommendations checked against sources

**Hatching and density.** FAO describes a common 25–28 °C hatching range, strain-dependent performance, and densities above 2 g/L in suitable small vessels. Therefore 2 g/L remains a conservative starting guide, not a universal optimum or proof that any higher density worsens hatch-out. Premium yield does not establish a faster hatch time. The standard, premium and hatchable decapsulated presets now use a clearly labelled 24 h starting estimate; existing saved clocks remain intact. Follow the actual product's instructions. [FAO: use of cysts](https://www.fao.org/4/w3732e/w3732e0n.htm).

**Harvest, nutrition and mesh.** FAO recommends prompt use of newly hatched nauplii and a submerged screen below 150 µm, followed by rinsing. The 120 µm screen fits that size guidance, but it also retains larger debris. The instructions no longer promise perfect separation or prescribe a fixed 700 ml/35 ppt refill for every configuration. Energy use begins at hatch, so a post-load timer cannot establish biological age. Cold retention of energy in unfed animals must not be presented as equivalent DHA retention after enrichment. [FAO: use of nauplii and meta-nauplii](https://www.fao.org/4/w3732e/w3732e0o.htm).

**Refrigeration.** A primary study found high survival after 48 h at 2–4 °C for most tested strains under its experimental conditions. That supports a useful planning allowance, not guaranteed survival or a universally measured 24:48 linear ageing law. [Léger, Vanhaecke and Sorgeloos, 1983](https://doi.org/10.1016/0144-8609(83)90006-7).

**Selcon.** American Marine's current FAQ allows 1–12 h with aeration. The app's 12 h soak is now described as a configurable protocol; settings allow one hour. A second dose at +10 h is explicitly another full configured dose and requires a product-appropriate protocol. It is not presented as a universal Selcon instruction. [American Marine: Selcon FAQ](https://americanmarineusa.com/pages/faqs-about-selcon).

The 3–4 week cyst-pouch reminder now asks for a storage/yield check rather than asserting that the cysts expire then. Temperature and instar advice no longer claim that a timer has observed hatch-out or feeding readiness. The public hatchery page has been corrected accordingly, including its erroneous claim that harvesting debits a cyst inventory.

## Practical limits that remain

- The 8% per-degree temperature formula is an **uncalibrated heuristic**. It is bounded and labelled accordingly. Hatch-water measurements and observations for the actual cyst product should determine the configured clock.
- The 24 h warm / 48 h cold plain windows and 12 h warm / 48 h cold enriched windows are **handling budgets**, not nutrient assays, water-quality checks or guarantees of viability. Product-specific dose concentration and nauplii density are not measured. The illustrative yield calculation assumes 225,000 nauplii/g.
- History records the keeper's harvest action, not the first or last hatch. Loading can occur later, and refrigeration delays development. Neither timestamp alone confirms instar II. Existing historical age errors cannot be reconstructed automatically.
- The rack projection assumes prompt restarts, evenly applied cycle settings, usable forecast load volume, and replacement or use of preceding batches. Its bounded, half-hour-grid search is not a proof of an optimal permanent schedule. It does not allocate time or holding capacity for the physical cleaning/rinsing/enrichment workflow. Stock in an active soak is not immediately ready to feed even when its ordinary storage budget has time left.
- A linked pump relies on Home Assistant's guard/sync path; physical firmware behaviour and the existing periodic-check latency were not tested on hardware. The hand-feed actions record reported feeding rather than certifying food quality.
- The prototype valve/mesh arrangement was reviewed as instructions, not tested hydraulically. Inspect bleed water before discarding it, maintain oxygenation, and verify the actual catch and refill volume.

## Verification and files

All **46 standalone suites** passed: 27 Python suites and 19 dashboard suites. This included 169 existing NPS cases, 17 new hatchery regression tests and 58 NPS dashboard cases. The broader checks cover dosing, reminders, migrations, save guards, mixing and neighbouring panels. Python compilation, JavaScript syntax and whitespace checks also passed. The site TypeScript/Vite production build passed, with Vite's non-blocking warning about a large scene bundle. Tests use the repository's fake Home Assistant harness; no live device validation was performed.

Changed files:

- `custom_components/openreef/nps.py` — scheduling, expiry, presets and scoped history.
- `custom_components/openreef/__init__.py` — state transitions, transfers, planning, sensor units, reminders and pump integration.
- `custom_components/openreef/dosing.py` — shared food status and soak guard.
- `custom_components/openreef/frontend/openreef-panel.js` — advice, settings and action states.
- `site/src/pages/brine-hatchery.tsx` — matching public explanations.
- `tests/test_nps.py`, `tests/test_panel_nps.mjs` — corrected expectations and dashboard regression coverage.
- `tests/test_hatchery_audit.py` — new calculation and lifecycle regressions.
- This audit report, plus a pointer in the historical brainstorm document.

Next: review the changes, then reload the updated integration and dashboard in a controlled session. Compare one observed hatch, one full soak, a fridge round trip and a logged feed against the displayed timestamps and volumes before relying on the revised estimates for the live feeding routine.
