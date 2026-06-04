# Dosing Advisor Smoke-Test Tweaks

Running list of tweaks found while smoke-testing the Dosing & Consumption Advisor in Home Assistant.

Use this as the quick working list while screenshots come in. Items can move into the main roadmap or
eval todo once they become larger feature work.

## Smoke-Test Order

- [x] Kalkwasser safety: `docs/eval-data/kalkwasser/demand-outgrowing-kalk.csv`
- [ ] Reef Fusion exact advice: `docs/eval-data/reef-fusion/alkalinity-demand.csv`
- [ ] DIY / custom verified strength: `docs/eval-data/custom-diy-three-part/alkalinity-demand.csv`
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

Status: blocked before advisor review.

Observed:

- Primary system can be set to `Seachem Reef Fusion 1/2`.
- Secondary supplement can be changed to `No secondary supplement` in the UI.
- After saving, the settings reload with `Kalkwasser / calcium hydroxide` selected again.
- Kalkwasser delivery and safety fields reappear, so the Reef Fusion-only smoke test is contaminated
  by secondary kalk context.
