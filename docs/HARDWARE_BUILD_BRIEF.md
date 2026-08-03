# OpenReef Hardware Build Brief — for the AI assistant helping with the physical build

> **Audience:** Claude (in Claude Chat) assisting Reece step-by-step with building the OpenReef pump hardware. This doc is your project alignment: what the software already does, what the firmware contract demands, which decisions are locked, and where every reference file lives. The repo is public: **github.com/TheCarpyVikings/OpenReef** — you can be given raw file links from it.
>
> Written 2026-07-12 at software version **v0.5.1**.

## 1. What OpenReef is, in one paragraph

OpenReef is a Home Assistant custom integration ("the intelligence layer for reefing") positioned to beat Neptune Apex Fusion and raw HA on usability. Backend: `custom_components/openreef/` (one large orchestration module + pure-math engines `awc.py`/`dosing.py`). Frontend: a single ~19k-line vanilla web-component panel. Hardware side: ESP32 nodes running ESPHome. **Design law: guards live in firmware.** HA edits schedules and verifies every write by read-back; the device executes autonomously and must keep working (or keep refusing to work) when Wi-Fi/HA is down.

## 2. What's already built (software — all shipped and released)

- **Automatic Water Change (AWC):** calibrated volume-primary changes (sequential + simultaneous methods), two-tier safety (benign limits pause/auto-resume; real faults latch), ATO suspend + stabilisation hold-off, persistent drain/fill ledger, pump wear odometers, multi-point calibration with spin-up/prime split.
- **Dosing channels:** multi-pump dosing dashboard + settings; first driver type is the **kalk stepper**. Daily-total-first schedules compiled into firmware numbers with write-then-verify sync; missed-dose detection (ask-first, kalk defaults to skip); reservoir ledger with days-until-empty; calibration with drift history; tube-life tracking; pH failsafe (pause-above/resume-below hysteresis); panic lockout with a firmware dead-man; advisor→pump one-tap apply; night weighting.
- **v0.5.1 (today)** was a hardening release: 24 verified bug fixes. Relevant to you: the **entity contract is now rev 2 and machine-checked in CI** (see §5 — this constrains what you may name things).

**Bench state (2026-08-03): Node 1 is physically under construction.** Pump pigtails + waterproof connectors soldered (drain + fill), flyback diodes fitted, D4184 modules headered, the S3 Zero being headered. No wire is pin-committed yet — the dosingnode pin map is what gets plugged.

## 3. Locked hardware decisions (grilled and decided — do not re-litigate)

**Topology (pivoted 2026-08-03, `MULTINODE_PIVOT_BRIEF.md` — LOCKED): distributed multi-node.** Each equipment group gets its own ESP32, syncing through HA. **Node 1 = a self-contained 4-channel dosing station, PUMPS ONLY — no physical sensors of any kind on it.** Tank telemetry and tank-side safety sensors (pH, temp, leak, display-high, tank floats) live on future nodes. The single-node reefnode remains a valid alternative topology, not the default.

| Decision | Value |
|---|---|
| Tank | 52 L display, ~35 ppt; all water sources salt-matched |
| Topology | **Multi-node**; Node 1 = dosing station (AWC drain + fill, kalk, live food), board **ESP32-S3 Zero (clone)** |
| AWC pumps | Kamoer **KPHM100 brushed 12 V** — drain + fill (source 2 dropped from Node 1; a future node can host it), driven by **D4184 dual-MOSFET trigger modules**. ⚠️ The KPHM100 is a *platform*: the **brushed** variant is the MOSFET drop-in. Brushless = 5-wire ESC, stepper = needs a driver — neither works as a MOSFET load. |
| Kalk doser | **Kamoer KPHM100-STB10 (stepper)** + BigTreeTech **TMC2209 V1.3** over UART (address 0x00, R_SENSE 0.11 Ω, StealthChop + interpolation), ~0.27 ml/rev nominal (calibration is authoritative) — unchanged by the pivot |
| Live food | Its own small **brushed** pump on Node 1 (phyto/pods/baby brine only — adult Artemia clog/chop the head); ml-doses, never litre-scale fills; reservoir freshness lockout |
| Cadence | Hourly ~40 ml micro-changes (simultaneous method), 20 L reservoirs |
| Electrical, Node 1 | **D4184 modules** carry their own gate circuitry (bench gate: TRIG must sit LOW when floating — add 10 kΩ to GND if not, `dosingnode-s3zero-design.md` §2); **1N5819** leaded Schottky flybacks across each brushed motor's tabs (functional equivalent of the spec'd SS34); one fused 12 V motor rail; 12 V→5 V buck feeds the Zero; Zero 3V3 → TMC VIO. **No master relay, no leak float, no tank floats on this node** — residual risk stated plainly in the design doc. |
| Electrical, discrete/single-node builds | The original spec stands: master **fail-OFF relay** (energize-to-run) with a **hardware leak-float wired into the coil circuit**; per-channel AO3400A/IRLB8721 MOSFETs; SS34 flybacks; 150 Ω gate / 10 kΩ pull-down per gate; fused 12 V rail; 3.3 V logic |
| Kalk chemistry safety | Dose above waterline with a siphon break; pH guard is the primary chemical safety; never dose cloudy slurry (draw from the clear zone, intake an inch off the bottom) |

## 4. Pin maps — one authority per node

**Node 1 (the dosing station being built): `docs/manual/dosingnode-s3zero-design.md` + `dosingnode-s3zero-reference.yaml` are the build authority.** If the build ever deviates, update the design doc the same day — copper and docs never disagree.

| Signal | GPIO | Dir | Notes |
|---|---|---|---|
| `drain_pump` gate | 1 | out | D4184 TRIG |
| `fresh_pump` (fill) gate | 2 | out | D4184 TRIG |
| `livefood_pump` gate | 4 | out | D4184 TRIG (GP3 skipped — strapping) |
| TMC2209 ENN | 5 | out | low = enabled |
| TMC2209 INDEX | 6 | in | |
| TMC2209 UART TX | 43 | out | 500 kBd — UART0 default pin |
| TMC2209 UART RX | 44 | in | |
| spares | 3 (avoid), 7–13 | — | GP21 (or 48 on some clones): onboard WS2812 |

Two consequences to never rediscover: (1) UART0's pins drive the TMC2209, so the **logger runs on native USB** (`hardware_uart: USB_CDC` under arduino) — first flash needs BOOT held while connecting USB-C; (2) the **S3 ROM prints boot output on GP43 at every reset** regardless of logger config — harmless to the CRC-guarded TMC2209 UART, documented so it is never chased as a fault.

**Single-node alternative (the reefnode): `docs/manual/reefnode-s3-design.md` §1 is its pin authority** (pumps 4/5/6, relay 7, livefood 8, TMC 11–14, floats 9/10, sensors 15–18/21 — avoids strapping 0/3/45/46, USB-JTAG 19/20, flash 26–32, octal-PSRAM 33–37, UART0 43/44). Its recorded hardware call stands: the kalk stepper's **motor** rail runs through the master power-cut relay; TMC2209 logic stays on the always-on rail. The kalk doc's classic-ESP32 map (TX 22/RX 21/EN 23) remains only for the old two-node path.

## 5. The entity contract — the one thing you must NOT improvise

The OpenReef panel auto-binds a doser by scanning HA for **frozen entity-id suffixes**. The contract (revision 2) lives in `docs/manual/kalk-doser-esphome-design.md` §6 and is enforced by CI (`tests/test_entity_contract.py`). Rules for any YAML you help write:

1. **Never rename entities** from the reference YAML — names → HA entity-id suffixes → auto-bind. A rename is a breaking API change.
2. **`friendly_name` is part of the contract** (rev 2): the node must set it (reference uses `friendly_name: OpenReef`), giving ids like `number.openreef_kalk_dose_volume_ml`. Prefix may vary; suffix may not. (Prefix-less nodes also work — the panel accepts exact bare ids — but keep friendly_name set.)
3. ESPHome `text_sensor` entities register in HA under **`sensor.`** (there is no text_sensor HA domain) — the skip-reason sensor binds as `sensor.<p>_kalk_last_skip_reason`.
4. The kalk pH guard subscribes to the **fixed HA-side id `sensor.openreef_kalk_ph_mirror`** — OpenReef publishes it; the user picks the real probe in the panel. Don't invent a different pathway.
5. Frozen skip-reason vocabulary: `disabled · ha_suspend · reservoir_low · not_calibrated · out_of_window · ph_guard · daily_cap · ok HH:MM`.

## 6. Reference files (repo paths)

| File | What it is |
|---|---|
| `docs/manual/kalk-doser-esphome-design.md` | **The kalk channel firmware design** — full amended ESPHome YAML (guard chain, hysteresis pH latch, SNTP windows/night cadence, bounded manual dose, HA-suspend dead-man with 4 h auto-expiry), §6 frozen entity table, tuning notes, honest residual risks. The classic-ESP32 pin section is superseded by §4 above, everything else stands. |
| `docs/manual/awc-esphome-reference.yaml` | 2-pump classic-ESP32 AWC node (watchdogs, latched lock, `AWC Clear Lock` switch). Basis for pump-channel patterns even though the build targets S3. |
| `docs/manual/awc-esphome-3pump-design.md` | The 3-pump ESP32-S3 AWC design (MOSFET wiring, master relay, plumbing) — closest to what's being built; its pin table gets superseded by §4. |
| `docs/manual/awc-hardware-and-safety.md` | Deeper hardware/safety prose for the AWC. |
| `docs/awc-multisource-livefood-brainstorm.md` | The multi-source + live-food research/audit (why live food is ml-dosed, salinity ledger math, micro-change numbers). |
| `docs/OPENREEF_DOSING_SMOKE_TEST.md` | **Sections 7–10 are the hardware bring-up checklist**: auto-bind (expect 24/24), calibration-blocks-until-done, every guard demonstrably blocking with the firmware skip sensor agreeing, ledgers/reboot behaviour. Build to pass these. |
| `docs/manual/kalk-doser-feature-spec.md` | The original brief (historical; Appendix A superseded by the design doc). |

## 7. ESPHome gotchas already discovered (don't rediscover them)

- Pin the slimcdk `tmc2209` external component to a known-good ref; the `stepper`/`tmc2209.configure`/`tmc2209.currents`/`write_run_current(x)` API is kept verbatim from the original brief and must be verified at first compile.
- Template **numbers** persist with `restore_value: true`; template **switches** use `restore_mode` (not restore_value). The **Kalk HA Suspend** switch must boot OFF (`ALWAYS_OFF`) — it's a dead-man, never restored.
- `api::global_api_server->is_connected()` may need to be unqualified `global_api_server` depending on ESPHome version.
- Script `parameters:` need ESPHome ≥ 2023.x. `update_interval: never` on the template text sensor.
- Firmware guard-chain order is documented and fixed: `enabled → !ha_suspend → reservoir not low → calibrated (steps_per_ml > 0) → in window → pH ok (if guard on) → daily cap`. `steps_per_ml` boots **0 = not calibrated** and every dose path refuses while ≤ 0.

## 8. How the software will treat the freshly flashed node

1. User adds a channel in the panel → **Auto-bind entities** → expect **24 of 24** by suffix. Misses appear by role.
2. On Save, HA **writes the schedule into the firmware numbers and verifies each write by read-back** (~8 s); the card shows "synced HH:MM". Expect `number.set_value` traffic on every settings save and a re-assert of the suspend switch every 60 s while a hold is active — that's by design, not a bug.
3. Calibration: prime (bounded 10 s runs) → **Run 100 revolutions** (exactly 320,000 microsteps) → measure (~27 ml for the KPHM100) → panel derives steps/ml and writes it → verify with a 10 ml dose into a measuring cylinder (±5%).
4. **Dose into a measuring vessel, never the tank, until smoke-test §9 (guard checks) passes.**
5. AWC pumps are explicit-bind (picked manually in the panel), not suffix-frozen — but keep the reference names anyway.

## 9. Residual risks the software can't fix (hardware's job)

- A **welded relay / shorted MOSFET / shorted TMC2209** defeats every software and firmware cutoff — that's what the master fail-OFF relay + hardware leak-float in its coil are for. Per-dose step counts and daily caps bound the damage; reservoir sizing bounds the catastrophe (never plumb more water than the tank can absorb).
- Kalk crusts: expect head wear (tube life ~1000 h, tracked), vinegar-flush the line periodically, recalibrate after any tube change (the panel nags at 60 days).
- Floats are cross-checks, not primaries: the software ledger dead-reckons volume; floats arbitrate.

## 10. What's coming next in software (so you don't design against a moving target)

**The software arc is COMPLETE (0.6.0)** — nothing left to design against.
Shipped train: hardening (0.5.1–0.5.2) → interval schedules + micro-change ATO
skip + drift (0.5.3) → N-source alternation (0.5.5, numbering shifted +1
mid-arc) → brushed driver + live food (0.5.6) → the merged single-S3 reference
node you'll flash (0.5.7) → 2-part spacing (0.5.8) → stabilization + legacy-alias
removal (0.6.0). Flash `reefnode-s3-reference.yaml`, wire to its §1 pin budget,
follow `reefnode-s3-design.md` §5 for bring-up (expect kalk auto-bind 25/25,
contract rev 3, and live-food 22/22) — then run the acceptance soak:
**`OPENREEF_DOSING_SMOKE_TEST.md` §12** (48 h, everything on, hourly
micro-changes; its ledger-honesty and ATO-availability checks are the arc's
exit criteria).
