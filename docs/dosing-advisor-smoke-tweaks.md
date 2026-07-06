# Dosing Advisor Smoke-Test Tweaks

Running list of tweaks found while smoke-testing the Dosing & Consumption Advisor in Home Assistant.

Use this as the quick working list while screenshots come in. Items can move into the main roadmap or
eval todo once they become larger feature work.

## Smoke-Test Order

- [x] Kalkwasser safety: `docs/eval-data/kalkwasser/demand-outgrowing-kalk.csv`
- [x] Reef Fusion exact advice: `docs/eval-data/reef-fusion/alkalinity-demand.csv`
- [x] DIY / custom verified strength: `docs/eval-data/custom-diy-three-part/alkalinity-demand.csv`
- [ ] All-For-Reef guided behaviour: `docs/eval-data/all-for-reef/demand-increasing.csv`
- [ ] Above-target safety: `docs/eval-data/reef-fusion/above-target.csv`
- [ ] Mission Control Dosing Advisor display persistence
- [ ] Support summary dosing output

## Open Tweaks

- [x] **Bug - high priority:** Dosing settings cannot persist "No secondary supplement". After saving
      Reef Fusion with secondary supplement set to none, OpenReef reloads with
      `Kalkwasser / calcium hydroxide` selected again and shows kalk delivery/safety fields. This
      blocks clean smoke testing for Reef Fusion and other primary-only systems.
      Fixed in `0.4.78`: explicit blank primary/secondary system choices now override old
      per-parameter product-preset inference.
- [ ] Kalkwasser: remove duplicated "Do not use kalkwasser as a one-off correction bolus" wording.
- [ ] Kalkwasser: explain evaporation headroom in plainer language, e.g. "based on your configured
      evaporation ceiling".
- [ ] Reef Fusion magnesium card: remove irrelevant two-part dose/max-dose safety text from
      magnesium, because Reef Fusion does not cover magnesium.
- [ ] Reef Fusion magnesium card: change product assumption wording from "Seachem Reef Fusion 1/2"
      to clearer "No magnesium product configured" or "Reef Fusion does not cover magnesium".
- [ ] Reef Fusion calcium card: make correction wording clearly optional when calcium movement is
      below useful signal, so it does not look like OpenReef is pushing calcium changes during an
      alkalinity-only demand scenario.
- [x] **Safety guardrail - high priority:** Custom verified-strength products can show absurd exact
      mL/day advice when the entered/calculated strength is implausibly weak. In the DIY alkalinity
      smoke test, OpenReef showed a `544.5 mL/day` holding dose and roughly `5300.0 mL/day`
      correction dose from a calculated `0.0001 dKH/mL` potency. This should switch to
      `Review`/`Locked`, suppress exact mL advice, and tell the user to verify the "1 mL raises X in
      Y litres" strength fields before changing a doser.
- [x] Custom verified-strength products need a conservative sanity limit for daily dose changes and
      correction splits, or a user-configured maximum safe daily dose before exact advice can be
      shown.
      Fixed in `0.4.79`: implausibly weak custom strengths and very large custom-product advice now
      switch to review/warning language and suppress exact mL lines until the strength is verified.

## Watch List

- [ ] Confirm dosing cards stay readable on laptop-width and mobile-width screens.
- [ ] Confirm warning colours match severity: locked/safety issues amber, genuine unsafe states red,
      informational safety reminders neutral.
- [ ] Confirm "Guided", "Review", "Learning", "Locked", and "Not covered" labels feel consistent
      across products.
- [ ] Confirm product assumptions are obvious enough that a beta tester knows which bottle/system the
      advice is using.

## Passed Notes

### Kalkwasser Safety - Demand Outgrowing Kalk

Status: passed.

What looked right:

- Says kalk may not keep up for alkalinity/calcium.
- Does not suggest a kalkwasser correction bolus.
- Mentions pH and evaporation limits.
- Confirms pH guard is OK.
- Magnesium correctly says kalkwasser does not maintain/fix magnesium.
- Keeps the whole advisor in advisory-only language.

Polish found:

- Duplicate anti-bolus wording.
- Evaporation headroom number is useful but needs a clearer source/explanation.

### Reef Fusion Exact Advice - Alkalinity Demand

Status: passed with polish/follow-up tweaks.

What looked right:

- Primary system can be set to `Seachem Reef Fusion 1/2`.
- Secondary supplement now persists as `None`.
- Safety state is acknowledged with `200 L` net volume.
- Alkalinity shows exact advisory maintenance and correction guidance.
- Calcium is recognised as covered by Reef Fusion and stays steady.
- Magnesium is marked `Not covered`.
- No automatic dosing language appears.

Polish found:

- Magnesium card still includes irrelevant Reef Fusion daily dose/max-dose safety wording even though
  magnesium is not covered.
- Magnesium card product assumption is technically showing the selected primary system, but this reads
  confusingly when the card itself is `Not covered`.
- Calcium correction text appears even though calcium trend is below useful signal. This is safe
  because it is phrased as "if correcting", but it should be visually/verbally less prominent than
  the alkalinity demand.

### DIY / Custom Verified Strength - Alkalinity Demand

Status: passed after `0.4.79` guardrail fix.

What looked right:

- Primary system can be set to `Custom verified-strength product`.
- Secondary supplement persists as `None`.
- Safety state is acknowledged with `200 L` net volume.
- Alkalinity demand is detected.
- With verified strength settings, alkalinity gives a small holding-dose review
  (`32.0 mL/day` to `32.5 mL/day`) and a capped correction split.
- Calcium and magnesium remain steady and are not forced into dosing changes.
- No automatic dosing language appears.

Safety issue found:

- Alkalinity advice showed very large exact mL values as normal `Ready` advice:
  `544.5 mL/day` estimated holding dose and roughly `5300.0 mL/day` correction dose.
- The root cause is an extremely weak calculated custom potency: `0.0001 dKH/mL` in this tank.
- This is likely a strength-entry or recipe-unit problem, so OpenReef should not present it as an
  actionable dose.

Fix added:

- If custom product strength creates unusually large advice, the card now switches to
  review/warning language.
- Exact maintenance and correction mL lines are suppressed for implausibly weak custom strengths.
- Large custom correction advice is locked separately from sensible maintenance advice, so normal
  DIY maintenance estimates can still appear.
- The eval now includes an `implausibly-weak-alkalinity-strength` scenario to stop this regressing.

Retest result:

- The DIY alkalinity smoke test no longer shows `544.5 mL/day` holding advice or
  `5300.0 mL/day` correction advice.
- The same scenario works correctly when realistic verified-strength fields are entered.

Polish found:

- Magnesium is technically `2 ppm` above target, so it shows a safe "do not dose downward" note.
  This is correct, but the wording could be made calmer for tiny above-target differences.
