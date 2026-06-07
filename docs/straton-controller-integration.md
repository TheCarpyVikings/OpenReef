# OpenReef Straton Controller Integration

Date: 2026-06-07

For a simple tester checklist, see [OpenReef Straton Beta Test Guide](straton-beta-test-guide.md). For the narrow commit/update workflow, see [OpenReef Straton Push Checklist](straton-push-checklist.md).

## What Changed

OpenReef Core now has a native `Lights` tab in the Home Assistant panel. The first lighting surface is focused on ATI Straton planning:

- Straton fixture targets with IP/host, group, firmware, connection path, setup state, and selected target state.
- Research-backed template library for mixed reef, SPS, Saxby-inspired, soft/LPS, and photo/maintenance use.
- Quick modes for auto, blue phase, photo white, and feeding hold.
- Daily schedule preview for start time, photoperiod, ramp, peak, cloud dimming, and moonlight.
- Lunar, cloud, acclimation, peak, and photoperiod controls.
- Pain-point coverage matrix showing which researched ATI app complaints are fixed locally, still candidate evidence, or blocked by missing hardware proof.
- Fixture sync matrix showing target state, group coverage, firmware readiness, read-only live bridge matching, and hardware-write lock.
- Local program receipts so users can see what was saved inside OpenReef.
- Copy/import Straton program packages for local backup, restore, and sharing.
- Redacted Straton support note for beta feedback, fixture readiness, live bridge status, and remaining adapter evidence.
- Returned tester support-note intake for summarizing the beta verdict, assessing returned setup-bypass evidence, comparing returned schema fingerprints, rehearsing strong AP, LAN-only, AP route blocker, reachability-only, and Reef Pilot Bluetooth example notes, and promoting safe candidate read paths from real returned notes only.
- Read-only Home Assistant `light.*` bridge for live state, brightness, effect, and colour status.
- Adapter evidence collector for before/after ATI export diffs and redacted endpoint notes.
- Read-only pasted fixture-state analyzer for comparing likely current fixture fields against the OpenReef plan.
- Redacted schema fingerprint for comparing fixture JSON shapes across testers without sharing raw settings.
- Read-only endpoint probe that asks the Home Assistant backend to run a local `GET` against a selected fixture host and typed path, then feeds any JSON response into the same planned-vs-observed comparison. Browser `GET` remains a fallback for older OpenReef builds.
- Setup rescue panel for AP fallback, AP route readiness, controller reachability, one-click safe read-only path scanning, optional extra relative GET paths, and plain outcome guidance before asking users to touch scheduling.
- Copyable beta update message for the after-push handoff, before the tester opens the new `Lights` tab.
- Copyable beta tester steps for the Straton connection test, so hardware evidence requests are consistent and read-only.
- Beta hardware evidence checklist showing fixture target, adapter generation, first-setup route, controller/AP route, returned tester note, setup-bypass evidence, readback candidate, schema fingerprint, and write safety in one tester-facing view.
- Copyable adapter evidence request for controlled one-change ATI export/network capture runs.
- Adapter evidence coverage matrix for schedule, spectrum, grouping, firmware/model, read endpoint, and save/apply mapping buckets.
- Candidate read-endpoint catalog for promoted safe paths such as reachability, current state, program, firmware/model, and groups, while write/apply paths remain locked.
- Hardware write unlock checklist with a compact proof summary that keeps writes locked until setup-bypass proof, fixture read proof, AP route proof, current-state read, program readback, firmware/group reads, save/apply evidence, and rollback evidence are accounted for.
- Controller bridge status for OpenReef lighting equipment, future Home Assistant light entities, Apex/MXM, Hydros, Reef Pilot Bluetooth, and direct fixture adapters.

## Why This Shape

ATI Straton user complaints are mostly about app confidence, not light quality: discovery failures, manual IP fallbacks, firmware uncertainty, multi-light grouping, weak save feedback, and awkward schedule editing.

Competitive reef light app research adds the features users consistently like:

- Mobius-style proven templates and user templates.
- myAI-style shared/imported community schedules.
- ReefBeat/Orphek/Kessil lunar cycle, weather, clouds, sunrise/sunset, and acclimation.
- Apex/Hydros-style controller visibility, alerts, and simple one-screen status.
- Fixture-level sync confidence before any write action.
- Quick manual viewing modes that do not destroy the main program.

## Current Safety Boundary

This is not yet a hardware write adapter. The `Save local plan` button saves an OpenReef receipt and config only. It does not call Home Assistant services, push to Straton hardware, or update firmware.

That boundary is deliberate: guessing ATI endpoint contracts would repeat the reliability problems this feature is designed to solve.

The current bridge can read a mapped Home Assistant light entity from OpenReef lighting equipment. It is useful for confidence checks and support summaries, but it still does not modify schedules, channels, effects, firmware, or fixture state.

The adapter lab is also read-only. It compares pasted ATI exports or network notes in the browser session and shows changed keys, endpoint method/path hints, and likely focus areas such as schedule, spectrum, grouping, and firmware. It can also ask the Home Assistant backend to run a `GET` against a configured fixture host and typed path so testers can check controller-to-fixture reachability, status, content type, and JSON shape without browser CORS or mixed-content blocking the result. Raw pasted evidence and raw probe responses are not saved into OpenReef config; copied summaries are redacted.

Program packages are meant for local backup and reef-to-reef sharing of planned settings. They include fixture host/IP fields so a user can restore their own setup, so use the support summary or adapter evidence summary when a redacted diagnostic note is needed.

The schedule preview is also local planner state. It helps users understand the planned day before saving, but it does not program ATI schedules until a verified adapter exists.

The sync matrix is a confidence view, not a fixture acknowledgement. It marks the OpenReef target list, group membership, firmware readiness, and conservative Home Assistant `light.*` matches. It cannot prove an ATI fixture accepted a schedule until a read-only fixture endpoint is mapped.

The copied support note is also redacted and advisory. It includes fixture targets, redacted host/IP values, connection path, setup state, firmware readiness, live bridge state, planned program settings, and adapter evidence status, but it does not include raw ATI exports or prove a hardware push.

The pain-point coverage matrix is the quick honesty check. It maps the common complaints directly to OpenReef state: setup bypass, discovery/reachability, current fixture reads, schedule editing, multi-light grouping, save confidence, controller visibility, backup/support handoff, and hardware save/apply. Rows marked fixed are local OpenReef behaviours or proven read evidence. Rows marked candidate need stronger fixture evidence. Rows marked blocked must not be treated as solved.

The setup rescue panel is the first bypass test for ATI's awkward setup path. It lets a tester stage the direct AP fallback address, record whether the fixture is using LAN or AP fallback, record whether the light is already on LAN, brand new/reset, or stuck in setup, test basic root reachability, run a one-click safe scan across built-in read-only candidate paths, optionally add extra relative GET paths from redacted evidence, and see a plain outcome such as "read path found", "reachable, no JSON", or "not reachable" before touching schedule controls. It also shows `AP route` separately, so a tester can tell whether the Home Assistant/controller network can actually reach `192.168.100.1` before treating ATI setup as bypassed. Successful read candidates are promoted into a small endpoint catalog for reachability and current-state reads. If the returned JSON includes likely schedule, spectrum, firmware/model, or grouping fields, OpenReef also marks that path as a candidate for program, firmware, or group read roles. The current fixture sample analyzer then parses a pasted JSON fixture response, a probe response, or an export, identifies likely schedule, spectrum, grouping, model, and firmware fields, creates a schema fingerprint from redacted field paths and primitive value types, then compares obvious candidate values such as peak, start time, photoperiod, ramp, moonlight, and firmware against the OpenReef plan. It is still candidate matching only; a successful probe proves that one controller `GET` returned data, not that the final ATI endpoint contract is mapped.

The in-app bypass verdict is deliberately blunt: `read-only bypass proven`, `reachability bypass only`, `bypass not proven`, or `bypass untested`. That keeps beta feedback focused on whether OpenReef can help before ATI's app setup, instead of accidentally presenting the planner as a finished hardware adapter.

OpenReef also separates the reachability verdict from the setup-replacement claim. A LAN read is useful adapter evidence, but it is labelled `LAN confidence only` when the fixture was already configured. A real setup-bypass candidate requires AP fallback, a brand-new/reset or stuck setup state, a controller/AP route that can reach the direct fixture address, and a useful read path. This prevents OpenReef from claiming it fixed ATI onboarding when it only read an already configured fixture or when the controller simply cannot route to the Straton AP.

The tester support-note intake closes the evidence loop after a remote beta test. It accepts the copied redacted support note, extracts the bypass verdict, safe scan counts, best/current-state paths, AP route readiness, schema fingerprint, hardware generation, Bluetooth evidence, and next action, then computes a returned setup-evidence verdict such as `Strong pre-setup evidence`, `LAN read evidence only`, `Route blocker`, `Reef Pilot Bluetooth evidence`, `Reachable but no setup proof`, or `Setup evidence incomplete`. It also shows a `Beta return review` that separates return type, setup-bypass support, read mapping, endpoint-catalog updates, and write safety before the detailed rows. It compares the returned fingerprint with the current local fixture sample where available, then promotes only safe read-path candidates from real ReefTECH Wi-Fi returned notes into the endpoint catalog. `Load example note` can fill the intake with synthetic rehearsal notes for strong AP, LAN-only, AP route blocker, reachability-only, and Reef Pilot Bluetooth outcomes so the parser can be tested without hardware; example notes do not promote endpoint candidates or make proof gates ready. The raw returned note is transient browser state and is not saved into OpenReef config.

The beta hardware evidence checklist is the simple tester-facing layer: it shows whether the target, adapter generation, first-setup route, controller/AP route, returned note, setup-bypass evidence, readback candidate, schema fingerprint, and write safety are ready, candidate, or blocked. For Reef Pilot Bluetooth it explicitly treats AP route as non-proof and asks for separate Bluetooth/Straton X evidence. The hardware write unlock checklist is the final adapter gate before any future write work. It deliberately treats read paths as candidates, not permission to write. It now separates fixture read proof from setup-bypass proof, shows AP route proof separately, and includes a compact proof summary so a LAN read cannot be mistaken for first-time ATI setup replacement. Save/apply remains blocked until OpenReef has verified current-state readback, current-program readback, firmware/group context, save/apply endpoint evidence, and a rollback package path on real hardware.

The copyable adapter evidence request is for the next tier of hardware mapping. It asks a capable ReefTECH Wi-Fi tester to collect one tiny ATI app change at a time, before/after exports where available, and redacted method/path notes for load, save, and apply flows. For Straton X / Reef Pilot Bluetooth it instead asks for pairing/control observations, Live PAR/Energy behavior, template/group behavior, and schedule-save confirmation. This keeps write mapping grounded in observed Straton behavior instead of guessed endpoint contracts.

The adapter evidence coverage matrix summarizes each pasted before/after run into practical mapping buckets: schedule, spectrum, grouping, firmware/model, read endpoint hints, and save/apply hints. It is a coverage tracker, not a write unlock. Save/apply hints remain candidate evidence until verified readback exists on real hardware.

## Hardware Evidence Needed

1. ATI settings export before and after one schedule edit.
2. ATI settings export before and after one spectrum/channel edit.
3. ATI settings export before and after grouping two fixtures.
4. Firmware/model strings from Straton, Straton Pro, Flex, and X where available.
5. Browser network capture for ReefTECH Wi-Fi load/save/apply flows.
6. CORS, mixed-content, and same-origin behavior for direct fixture access from a Home Assistant panel.
7. Verified read-only endpoint paths for current fixture state, current program, model/firmware, and group membership. Candidate role promotion from one JSON response is useful evidence, but verification still requires real hardware readback.
8. Matching schema fingerprints across repeated reads of the same endpoint/firmware, without exposing raw settings. Mismatches should be treated as useful warnings, not failures, until fixture generation, firmware, and endpoint path are confirmed.
9. Separate Straton X / Reef Pilot Bluetooth evidence for Live PAR, Live Energy, group control, templates, and schedule behavior. Do not assume that Reef Pilot Bluetooth shares the ReefTECH Wi-Fi endpoint contract.

## Evidence Collection Workflow

Use the `Lights` tab adapter lab for one small change at a time:

1. Export ATI settings before the change.
2. Change only one thing in the ATI app, such as peak intensity, one channel, one schedule time, or grouping.
3. Export ATI settings again.
4. Paste both exports into the adapter lab and analyze.
5. If possible, paste browser network method/path notes from the same flow.
6. Copy the redacted summary for adapter implementation notes.
7. Copy the Straton support note when reporting beta feedback or fixture readiness.
8. Paste any current fixture JSON response/export into the read-only sample analyzer and review planned-vs-observed candidates.
9. If a likely read path is known, enter it in the read-only endpoint probe, run `GET`, and include the redacted probe result in the support note.
10. If several likely relative GET paths are known, paste them into `Extra safe GET paths`, then run `Scan safe paths`.
11. If the user is stuck before ATI setup, use `Copy tester steps`, `Use AP fallback`, then `Scan safe paths`, before asking them to open ATI's app.
12. Check `AP route`; if it is not reachable, solve controller/AP routing before treating this as a Straton or ATI-app failure.
13. Paste the returned support note into `Tester support-note intake` and click `Analyze note` to summarize the beta verdict, assess setup-bypass evidence, and compare any returned schema fingerprint with the current local fixture sample.
14. Review `Hardware evidence checklist` for the tester-facing proof state, then review `Hardware write unlock checklist`; do not enable writes while any row is blocked.
15. Use `Copy evidence request` only for testers comfortable collecting ATI exports, browser network method/path notes, or Reef Pilot Bluetooth app-control observations.
16. Review `Adapter evidence coverage` after each pasted before/after run and collect only the missing buckets.

Keeping each run to one change makes it much easier to map Straton fields safely.

## Next Build Step

Extend the read-only adapter before writing:

- verify the backend read-only probe against real ATI fixture endpoints in AP mode and LAN mode
- promote confirmed read paths from the candidate catalog into verified fixture state, program, firmware, and group reads
- compare verified fixture reads to the OpenReef planned program
- upgrade the existing sync matrix from OpenReef/read-only bridge confidence to real fixture acknowledgement

Only after read-only mapping is verified should OpenReef add write support.
