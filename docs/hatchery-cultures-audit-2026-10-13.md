# Hatchery and cultures audit — 13 October 2026

The stock-availability fixes were published in **v0.7.214**. This follow-up, **v0.7.215**, reviews the hatchery and culture calculations, recommendations, stock movements and dashboard inputs. It corrects further defects and proposes a clearer layout. It does not establish the biological condition of the live cultures from screenshots or timers.

## Scope and method

Reviewed the hatchery and cultures engines, their Home Assistant action handlers, linked food-pump freshness, food-shelf sources, split/refill/seed/restart/enrichment flows, growth learning and dashboard displays. Checked worked examples independently, reproduced boundary failures in the fake Home Assistant harness, reviewed changes across the shared handlers, and added regression tests. Existing mixing, salinity, migration, reminders and dashboard suites provide adjacent coverage.

No live Home Assistant settings, pumps or aquarium devices were operated. Historical stock and observation records were not rewritten. Unrelated workspace changes were excluded.

## Confirmed findings and corrections

| Area | Finding | Correction |
| --- | --- | --- |
| Hatchery supply | Food still soaking, future-dated loads and invalid clocks could count towards the hatch forecast. | Forecast only uses feedable stock; a usable fridge bottle can still provide supply during a container soak. |
| Harvest actions | Repeating a harvest against a named idle vessel could create food; harvesting into a full container could finish a running batch without adding stock. | Reject these actions before changing the batch or ledger. The older unnamed manual-load API remains supported. |
| Enrichment | A second dose could debit food after the soaking batch was emptied/replaced, or after its planned completion. | Validate batch identity, remaining volume and soak clock before debiting. |
| Freshness | Linked pump and manual paths could disagree over custom shelf duration; future food dates were treated as fresh. | Share the batch-age check and respect configured plain shelf duration. Perishable food with future or unverifiable dates is unavailable. Shelf-stable products retain their existing expiry setting. |
| Summary clocks | Timezone-free rack or enrichment stamps could crash the page summary. | Handle unusable timestamps without crashing the rest of the summary. |
| Culture food | Expired phyto could appear as a source. Seeding and restarting could debit unavailable feed; tracked f/2 shortages were not preflighted. | Validate the source and requested quantity before recording stock use, including combined nutrient demand when seeding a backup. |
| Top-ups | Phyto drip top-ups restarted the age of old food; an unknown-age fridge bottle could become fresh. | Keep the oldest valid age. An unknown-age remainder stays unverified. |
| Seed and undo ledgers | Standalone sibling seeding did not deduct the donor volume. Undo could miss the original bottle after the configured feed changed. | Deduct the actual starter, retain donor seed, and credit the original recorded bottle. Rejected backup creation leaves no new jar behind. |
| Volume conservation | An automatic drip share could duplicate phyto already assigned elsewhere. Bottle overflow disappeared from the destination accounting. Oversized starters/refill portions were accepted. | Resolve shares before checking totals, record accepted bottle volume and excess waste, and reject impossible recipe volumes. Expose bottle capacity before a split. |
| Growth fits | Small nonzero fitted slopes rounded to zero before division, crashing Secchi/index forecasts. Small draws reset learning as if they were full splits. | Calculate with the full slope precision and preserve the current growth cycle across small draws. |
| Daily draw suggestion | The calculated draw was forced up to a 20% minimum even for slow recovery. | Use the calculated percentage, rounded down; withhold a daily-mode suggestion below the supported setting range. |
| Advice | Flat pH claimed harvest readiness; sizing text promised the bottle would absorb surplus for three weeks. Disabled drip schedules still counted as demand. | Require observations beyond pH, describe storage/capacity constraints, and exclude disabled demand. |
| Dashboard | Dense text obscured which hatchery a summary described. Nutrient/refill text could disagree with edited fields or a plain-water source selection. Generic “no backup” and “all quiet” labels hid their scope. | Identify the selected batch and its clock; update recipe previews from the current inputs and show the applicable source and capacity limits. Name the species needing backup, and say “No care actions due” independently of food availability. |

## Independent checks against the screenshots

| Example | Calculation | Assessment |
| --- | --- | --- |
| Hatchery progress | `6.8 / 36 = 18.9%`; `33.7 / 36 = 93.6%` | The displayed 19% and 94% are correct clock progress, not measured hatch percentage. |
| Brine container | `250 / 750 = 33.3%` | The displayed 33% is correct volume remaining. |
| Projected gap | Incoming loads at about 2.3 h and 29.2 h are 26.9 h apart; `26.9 - 24 = 2.9 h`. | Arithmetic is correct under the assumed 24 h supply window, adequate volume and fresh receiving container. Top-ups preserve older expiry, so the forecast now states its fresh-container assumption. |
| Backup phyto split | `3,500 × 0.60 = 2,100 ml`; `2.1 × 1.5 = 3.15 ml f/2`. | 2,100 ml out and rounded 3.2 ml nutrient are correct for the configured fresh-water recipe. |
| Main phyto split | `5,000 × 0.50 = 2,500 ml`; `2.5 × 1.5 = 3.75 ml f/2`. | 2,500 ml out and rounded 3.8 ml nutrient are correct for that recipe. |
| Changed working volume | Backup: `4,000 - (3,500 - 2,100) = 2,600 ml` fresh; nutrient `2.6 × 1.5 = 3.9 ml`. | Editing “After” to 4 L must change the displayed nutrient amount from 3.2 to 3.9 ml. |
| Projected phyto production | `2,100 / 8 = 262.5 ml/day`; `2,500 / 8 = 312.5 ml/day`. | These are conditional water-volume averages. They do not establish current readiness, cell density or storage capacity. A 1,000 ml bottle cannot receive the entire default split. |
| Rotifer harvest plus purge | `999.9 + 50 ≈ 1,050 ml`; at 27 ppt from 35 ppt stock: `1,050 × 27 / 35 = 810 ml` stock plus 240 ml RODI. | The screenshot's plain refill is correct within rounding. |
| Rotifer refill using phyto | 300 ml phyto at 35 ppt + 510 ml stock at 35 ppt + 240 ml RODI gives 1,050 ml at approximately 27 ppt. | Correct only when that phyto source and amount are selected and available. |
| Daily equivalent of an eight-day, 60% split | `100 × (1 - 0.4 ** (1/8)) ≈ 10.8155%`. | Suggesting 20% overstated this model. The revised result is 10.8%; it remains a growth-model estimate. |

Salinity mixing uses the project's volume approximation and rounded millilitres. Actual prepared water still needs a salinity measurement. Calendar-based yield and colour-based density estimates cannot prove food concentration or nutrient uptake.

Automatic vessel-source suggestions require dark observations. Existing explicit, measured feeds from a healthy green culture remain recordable; they do not acquire the default dark-culture density assumption. Sibling starter recipes require matching salinity.

## Biological advice and source limits

The selected Reefphyto nutrient product currently specifies **3 ml per 2 litres**, matching the configured 1.5 ml/L conversion. That concentration is product-specific; other f/2 preparations can differ. Its first-harvest timing is conditional on conditions and growth. The app's calculation applies the configured dose to fresh replacement water; it cannot measure residual nutrients. [Reefphyto modified f/2 directions](https://reefphyto.co.uk/products/phytoplankton-nutrient-modified-f-2-medium).

Reefphyto's rotifer guide describes establishment and harvesting according to visible density, with partial harvests around 25–30%. A calendar reminder is an inspection prompt, not a population measurement. [Reefphyto culture guide](https://reefphyto.co.uk/pages/rotifer-culture-guide).

FAO distinguishes newly hatched instar-I Artemia, which cannot feed, from later feeding stages. Warm animals consume energy after hatch; cold storage slows that loss. This supports keeping biological age separate from the load timestamp. It does not validate OpenReef's temperature formula or a universal storage limit. [FAO Artemia manual](https://www.fao.org/4/w3732e/w3732e0o.htm).

Supplier enrichment instructions and general stage descriptions can disagree. Retain product-specific protocols and actual observations. The app's warm/cold shelf windows, temperature factors, molt delays and drop-volume conversion are explicitly planning assumptions, not nutrient assays, measured hatch success or guarantees of viability. [Reefphyto enrichment directions](https://reefphyto.co.uk/products/rotifer-artemia-enrichment).

## Layout recommendation

The screenshot has many explanatory paragraphs above the routine culture buttons, in narrow columns. Hatchery forecast, nutrition, temperature and actions compete in one text block.

The [interactive layout proposal](feeding-layout-proposal.html) uses illustrative data and makes no changes to OpenReef:

1. Put available food, the next action and exceptions at the top.
2. Use wider cards for active cultures, with labelled measurements and observation controls visible immediately.
3. Group details into **Split/refill recipe**, **Light/growth/supply**, and **Measurements/history** sections that expand on demand.
4. Give hatchery forecast and spacing their own section; keep batch identity and remaining time beside each vessel.
5. Move inactive cultures and the large rig illustration below everyday controls, while keeping them accessible.
6. Keep shortages and blocking problems visible even when background explanations are collapsed.

This larger layout is a proposal, separate from the dashboard accuracy fixes. The desktop and narrow-screen preview were rendered in Chrome for visual inspection.

## Verification and remaining limits

The full run discovered **57 standalone suites**. After completing the dashboard changes and rerunning its affected suites, **55 passed**. Two failures already existed before this audit: `test_report.py::test_due_kinds_catch_up_and_the_tick_stores_and_pushes` and the hand-logged-parameter trend modal assertion in `test_panel_live.mjs` (38/39 cases passed). They are outside the hatchery/cultures changes and are reported separately rather than represented as passing.

Focused passing coverage: NPS 194, cultures 107, culture audit 31, new culture integrity 19, hatchery audit 27, new hatchery pump-clock audit 2, dosing 55, feeding availability 10, phyto feeding 11, culture dashboard 59, and NPS dashboard 76. This includes **35 new regression cases** across the new suites and expanded audit/dashboard suites. Python compilation, panel JavaScript syntax and `git diff --check` pass. Full-run logs are in `/tmp/openreef-full-culture-audit`; tests use fake Home Assistant and the repository's dashboard harness.

Files: `custom_components/openreef/{__init__,cultures,dosing,nps}.py`, `frontend/openreef-panel.js`, related Python/dashboard tests, version metadata, and this audit/proposal. No new production dependencies.

After updating the integration and refreshing the dashboard, compare one real, measured harvest/refill and one food transfer with the displayed quantities and timestamps. No hardware, water-quality, density or live Home Assistant validation was performed here.
