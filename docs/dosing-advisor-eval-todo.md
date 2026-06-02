# OpenReef Dosing Advisor Eval Todo

This tracker is for validating OpenReef dosing advice with simulated reef data before
the advice is trusted by beta testers. Every product/system gets its own eval so we can
review the recommendation text, safety gates, and failure modes one at a time.

## Harness

- [x] Build dosing eval harness foundation.
- [x] Build shared 90-day simulation utilities.
- [x] Build shared expected-output/assertion helpers.
- [x] Kalkwasser / calcium hydroxide dosing-pump eval.
- [x] Review kalkwasser eval output and tune the advisor.
- [ ] Add UI smoke coverage for Dosing Advisor cards after the pure evals are stable.

## Product/System Evals

- [x] Tropic Marin All-For-Reef eval.
- [ ] Seachem Reef Fusion 1/2 eval.
- [ ] Aquaforest Component 1+2+3+ eval.
- [ ] ATI Essentials / Essentials Pro eval.
- [ ] Red Sea Complete Reef Care 4-part eval.
- [ ] TRITON Core7 Flex eval.
- [ ] Fauna Marin Balling Light eval.
- [ ] BRS Pharma 2-Part / DIY recipe eval.
- [ ] ESV B-Ionic eval.
- [ ] Custom verified-strength product eval.
- [ ] Hybrid dosing eval: kalkwasser plus two-part/AFR.
- [ ] Apex/Trident read-only chemistry eval.

## Future Candidate Reviews

- [ ] Brightwell Reef Code.
- [ ] Brightwell Kalk+2.
- [ ] Red Sea 7-part.
- [ ] Tropic Marin Original Balling.
- [ ] Calcium reactor advisor.

## Eval Template

Each product eval should record:

- Source links checked.
- Product class.
- Simulated tank assumptions.
- Expected advisor behaviour.
- Unsafe advice that must never appear.
- Current OpenReef result.
- Tweaks needed.

## Source Anchors

- Tropic Marin All-For-Reef: https://www.tropic-marin-smartinfo.com/all-for-reef
- Seachem Reef Fusion: https://www.seachem.com/reef-fusion.php
- TRITON Core7 Flex: https://www.triton.de/en/products/core7-flex/
- BRS Pharma Kalkwasser: https://www.bulkreefsupply.com/brs-pharma-kalkwasser-bulk-reef-supply.html
- Aquaforest Component 1+2+3+: https://aquaforest.eu/en/product/component-123/
- Red Sea Complete Reef Care: https://redseafish.com/reef-care-program/supplements/complete-4-part/
- Local deep research: `/home/reece/Desktop/Reef Aquarium Dosing Systems Research for OpenReef.md`

## Kalkwasser / Calcium Hydroxide Dosing-Pump Eval

Status: complete for the first beta pass. Harness output and manual CSV import checks have been
reviewed against the OpenReef UI.

Assumptions:

- 200 L mixed reef.
- Kalkwasser delivered by dosing pump, not ATO.
- Balanced mixed-reef targets: alkalinity 8.3 dKH, calcium 430 ppm,
  magnesium 1350 ppm, pH normal 7.9-8.35.
- Three months of realistic noisy manual alkalinity/calcium/magnesium data.
- Three months of simulated live pH, temperature, and salinity context.
- Manual tests drive dosing advice for this eval.

Scenarios:

- [x] Stable support.
- [x] Demand outgrowing kalk.
- [x] High pH risk.
- [x] No pH guard.
- [x] Stale manual tests.
- [x] Magnesium drift.
- [x] Above-target chemistry.

Expected safety rules:

- Kalkwasser must never be suggested as a one-off correction bolus.
- Kalkwasser must never produce automated dosing pump control advice.
- High pH or missing pH guard must be visible in the advisor.
- Magnesium drift must not be attributed to kalkwasser.
- If demand outgrows kalk, OpenReef should suggest review/escalation rather than fake precision.

Manual import notes:

- The seven manual-test CSVs are usable for testing advisor wording in a real OpenReef instance.
- Stable support should read calm: alkalinity/calcium steady, magnesium not covered by kalkwasser.
- Demand outgrowing kalk should warn that kalk may not keep up without offering a correction bolus.
- High pH risk requires a real mapped pH value above the configured kalk max pH, or a temporary lower
  max-pH setting, because manual Alk/Ca/Mg CSV rows cannot simulate live pH state on their own.
- No pH guard requires the pH sensor to be unmapped/disabled in OpenReef settings.
- Stale manual tests require old result dates relative to the current Home Assistant clock.
- Above-target chemistry should avoid any downward chemical correction advice.

Model inputs now tracked:

- Daily kalk volume.
- Kalk concentration.
- Evaporation ceiling.
- Max pH.
- Max pH rise per dosing window.

Remaining tuning questions:

- Whether OpenReef should estimate a rough saturation/capacity range for kalkwasser or keep this as
  safety-context-only guidance.
- Whether hybrid kalk + two-part/AFR should get a separate eval before exact two-part calculators are
  trusted.
- Whether the real UI needs an eval-data import helper for live-context sensor states, not just manual
  chemistry rows.

## Tropic Marin All-For-Reef Eval

Status: complete for the first beta pass. Harness output and manual CSV import files are ready for
UI review.

Source links checked:

- Tropic Marin All-For-Reef: https://www.tropic-marin-smartinfo.com/all-for-reef
- Local dosing research doc on balanced all-in-one systems and maintenance-only products.

Product class:

- `single_solution_balanced`
- Primary dosing system.
- Maintenance guidance only; no one-off correction bolus.

Assumptions:

- 200 L mixed reef.
- Targets: alkalinity 8.3 dKH, calcium 430 ppm, magnesium 1350 ppm.
- Manual alkalinity/calcium/magnesium tests drive advice.
- Current daily All-For-Reef dose is scenario-specific.
- Official dose model used by OpenReef for guidance:
  - start near 5 mL per 100 L per day,
  - review upward by no more than 2.5 mL per 100 L per week,
  - do not exceed 25 mL per 100 L per day.

Scenarios:

- [x] Stable maintenance.
- [x] Demand increasing within headroom.
- [x] Near max dose / demand outgrowing All-For-Reef.
- [x] Calcium-led adjustment.
- [x] Imbalanced parameters.
- [x] Stale manual tests.
- [x] Above-target chemistry.

Expected safety rules:

- All-For-Reef must never produce an exact one-off correction bolus.
- OpenReef must never imply automated dosing-pump control.
- Falling Alk/Ca should produce a slow weekly maintenance review step, then retest.
- Near-max dosing should warn before suggesting any increase.
- Calcium-led wording should be visible because Tropic Marin recommends calcium as the regular
  regulator once All-For-Reef is established.
- If Alk/Ca/Mg are moving in different directions, OpenReef should tell the user to correct the
  imbalance separately before relying on All-For-Reef maintenance.
- Stale manual tests should lock actionable advice until fresh tests are logged.
- Above-target chemistry should never suggest chemical correction downward.

Manual import notes:

- CSV files are in `docs/eval-data/all-for-reef/`.
- Start UI review with `demand-increasing.csv`, then `near-max-dose.csv`.
- `stale-manual-tests.csv` only behaves as stale relative to the current Home Assistant clock; adjust
  dates if needed when retesting later.
- The live pH/temp/salinity context exists in the pure eval harness, but the CSV files only contain
  manual chemistry rows.

Completed UI tweaks:

- The Dosing Advisor now shows one shared daily All-For-Reef dose control instead of one dose field
  per parameter.

Tweaks to consider after UI review:

- Whether OpenReef should highlight calcium as the primary regulator more prominently in the UI.
