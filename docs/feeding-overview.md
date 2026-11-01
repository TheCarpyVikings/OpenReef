# Whole-tank Feeding overview

Added in OpenReef 0.7.230. The Feeding hub and NPS page show what was recorded
today, what is still planned, and food totals over 7 or 30 days. From 0.7.231,
the NPS, Brine hatchery, Cultures and Spawning cards sit at the top of Feeding,
above the overview, matching the Water and Watch hubs. The detailed feeding
timeline remains available below the log.

## Everyday use

- **Add food** saves a usual portion for flakes, pellets or other hand-fed foods.
  Units include ml, pinch, scoop, g, cube, drop and piece. Each food retains its
  own unit; portions are not converted into nutritional equivalents.
- **Your usual portions** provides quick logging. Where a source or planned slot
  needs choosing, the editor asks for it. Choose an open slot or **Extra feed**.
  An extra never silently completes a scheduled feed.
- Enter the actual amount fed. A smaller amount can complete a planned slot;
  the record preserves both actual and planned amounts.
- **Edit** and **Undo** correct records. Stock-linked records can be corrected
  within 24 hours while their native source record remains available. Custom
  hand-fed foods can be corrected throughout retained history. Corrections do
  not return an old batch's feed to a newly refilled batch.
- **Keep it simple** reduces the detailed timeline and log. It leaves totals,
  quick portions, planned feeds and the Manual Tests link available.
- **Manage portions** adjusts usual amounts and whether a food is live.
  Changing its live classification also updates that food's retained records.
- **Used for tank feeding** controls which foods appear in quick portions and
  the new-feed picker (0.7.232). Culture-linked feeds and culture-feed presets
  start excluded; enable this option if you also feed that product to the tank.
  Shared home phyto bottles remain available. Culture nutrients such as f/2
  and enrichment supplies use their existing specialist controls and cannot
  be enabled here. Custom foods can also be excluded from tank feeding.

Changing tank use affects new feeds, not historical destinations or totals.
Existing entries remain editable and undoable within their usual limits. If a
test tap was logged as a tank feed by mistake, use **Undo**; this removes it
from totals and restores stock when it still belongs to the current batch.

Logging records a feed already performed. It does not run a pump. Existing
source inventory and expiry checks still apply. Custom foods are records only;
they do not manage a physical bottle's stock. Culture harvests continue through
the Cultures controls and contribute their recorded tank share to the overview.

## Optional Vitalis rotation

The rotation follows [Vitalis's feeding guide](https://www.vitalisaquatic.uk/feeding-guides):
28 days using the selected Marine foods, followed by 14 days using the selected
Platinum Marine foods, repeating every 42 days.

Choose the foods you use for each phase, the starting phase, and the date that
phase begins. The overview shows the current phase and next change date;
badges identify the foods selected for that phase. Keep logging the food and
amount actually fed using its usual portion. Other foods remain available.

The calendar advances by local date, including days with no feeding recorded.
It does not create feed entries or change totals. You can optionally enable a
Home Assistant persistent notification when the phase changes; this appears
in Home Assistant's notifications. Setup and date adjustments start quietly;
missed switch-day reminders are not queued. Turn off the rotation or its
notification option at any time without changing your feeding history.

## Estimated percentage of tank water volume

For each live liquid food and the combined live liquid total:

```text
percentage = recorded ml in selected period / (configured litres × 1,000) × 100
```

For example, 5,000 ml is 1% of 500 L or approximately 9.6% of 52 L. The total is
cumulative liquid added over the selected period, including carrier water.
It is not biomass, nutrient content, water replaced, a feeding target, or the
amount currently in the aquarium. It can exceed 100% over a long period.

The denominator uses OpenReef's existing effective water volume: the Water
Change volume override when configured, otherwise the tank Profile volume.
The panel displays the denominator. Missing or zero volume hides percentages.
Dry portions, unquantified feeds and liquids of unknown live classification
are excluded from the live-liquid percentage. Unknown classification is shown
so it can be corrected under Manage portions; a product name alone does not
establish that it is live.

## History and interpretation

- Brine from the container and fridge bottle contributes to one brine total.
  Linked home phyto sources group by species; independent commercial products
  remain separate. Source details are retained.
- Totals include all available retained records in the selected period, even
  when the visible log is limited to its newest 300 entries.
- The archive retains up to 365 local calendar days and 50,000 entries. Existing
  retained native history is imported; records already evicted by older source
  ledgers cannot be recovered. New source records are captured during saves.
- Missing days are unknown, not zero. Graphs show gaps, and today is incomplete.
  Totals describe recorded feeding and do not claim every feed was logged.
- Planned, undone, transfer-only and non-tank records do not inflate totals.
  Running daily pump totals update their existing record instead of adding a
  new record each time the view refreshes.
- The Manual Tests card reads existing nitrate and phosphate records and links
  to that form. Nutrient overlays and correlation analysis are not part of this
  first version.

## Implementation and verification

`feeding.py` holds catalogue and summary calculations. The integration exposes
admin WebSocket commands `feeding_summary`, `feeding_food_save`, `feeding_log`,
`feeding_edit` and `feeding_undo` under the `openreef/` namespace. The existing
panel consumes those commands. No production dependency was added.

Focused regression suites:

```sh
python3 tests/test_feeding.py
python3 tests/test_feeding_slots.py
python3 tests/test_feeding_integration.py
node tests/test_panel_feeding.mjs
```

Additional NPS, culture, dosing, save-guard and water-change regressions cover
the shared persistence paths. Browser checks use the actual panel rendering
with a mocked API, including 320, 736 and 1024 px widths. These checks do not
replace testing against a running Home Assistant installation.

After installing the changed integration, restart Home Assistant and refresh
the panel to load the updated version. Confirm the displayed tank volume, add a
usual dry-food portion, and use real feeds to check totals and source stock.
