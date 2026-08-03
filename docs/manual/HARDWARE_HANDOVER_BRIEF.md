# Hardware manual handover brief

Attach this file **plus the four sources listed below** when asking another assistant to
write or rewrite the hardware half of the DIY manual. It exists because this repo carries
several older pin tables that are still useful prose but wrong copper — the single most
likely way to end up with a confidently-written manual that miswires a build.

Regenerated 2026-08-03 after the **multi-node pivot** (`MULTINODE_PIVOT_BRIEF.md`,
repo v0.6.6). If the dosingnode design doc and this file ever disagree, the design doc
wins and this file is stale.

---

## 1. Attach these — they are the build authority

| File | Why |
|---|---|
| `docs/manual/dosingnode-s3zero-design.md` | **THE pin/contract authority for Node 1** — the dosing station actually being built. Every GPIO number comes from here. |
| `docs/manual/dosingnode-s3zero-reference.yaml` | **THE flashable node.** The entity `name:` values in it are an API, not labels. |
| `docs/HARDWARE_BUILD_BRIEF.md` | Topology + bench state, electrical decisions (D4184 modules, 1N5819 flybacks), ESPHome gotchas, entity-contract rules. |
| `docs/OPENREEF_DOSING_SMOKE_TEST.md` | §7–§10 bring-up, **§11b is Node 1's variant**, §12 soak with its per-topology posture. |

Optional, for prose and diagrams only — **their pin tables are superseded for Node 1**:

| File | Take this | Ignore this |
|---|---|---|
| `docs/manual/reefnode-s3-design.md` | the single-node ALTERNATIVE topology (fuller safety model: master relay + coil float); §3 is the frozen live-food contract table both topologies point at | its pin map, for Node 1 purposes |
| `docs/manual/awc-esphome-3pump-design.md` | §4 master-relay + coil-float wiring diagram (single-node builds), MOSFET wiring, plumbing reasoning | its pin table |
| `docs/manual/kalk-doser-esphome-design.md` | guard chain, §6 frozen entity table (rev 3 with Min Gap), tuning, residual risks | the classic-ESP32 map (TX 22 / RX 21 / EN 23) |
| `docs/manual/awc-hardware-and-safety.md` | plumbing and safety prose | — |

**Do not use as a build target at all:** `docs/manual/awc-esphome-reference.yaml`
(2-pump classic ESP32, pattern reference) and `docs/manual/kalk-doser-feature-spec.md`
Appendix A (historical).

---

## 2. The topology, in two sentences

OpenReef hardware is **multi-node**: each equipment group gets its own ESP32, syncing
through Home Assistant. **Node 1 — the build in progress — is a 4-channel dosing
station, pumps only, no physical sensors**; tank telemetry and tank-side safety (pH,
leak, display-high, floats) arrive on future nodes, and the old single-ESP32 "reefnode"
remains a documented alternative for anyone who wants one node with the fuller
relay-backed safety model.

## 3. The definitive Node 1 pin map (ESP32-S3 Zero)

| Signal | GPIO | Dir | Notes |
|---|---|---|---|
| `drain_pump` gate | 1 | out | D4184 TRIG |
| `fresh_pump` (fill) gate | 2 | out | D4184 TRIG |
| `livefood_pump` gate | 4 | out | D4184 TRIG (GP3 skipped — strapping) |
| TMC2209 ENN | 5 | out | low = enabled |
| TMC2209 INDEX | 6 | in | |
| TMC2209 UART TX | 43 | out | 500 kBd — UART0 default pin |
| TMC2209 UART RX | 44 | in | |
| spares | 3 (avoid), 7–13 | — | GP21 (or GP48 on some clones): onboard WS2812 |

Board facts: header pins GP1–GP13 + GP43/44 only; GP14–18 are bottom pads (unused);
33–37 not broken out. One fused 12 V motor rail; 12 V→5 V buck feeds the Zero; Zero
3V3 → TMC VIO. TMC2209 V1.3, UART address 0x00, R_SENSE 0.11 Ω.

## 4. Facts the manual must state (Node 1)

- **Logger runs on native USB** — `logger: hardware_uart: USB_CDC` (arduino). UART0's
  pins drive the stepper; without this line the boot log corrupts the TMC2209. First
  flash: hold BOOT while connecting USB-C; USB-CDC logs appear only after enumeration.
- **The S3 ROM prints boot output on GP43 at every reset**, before firmware, regardless
  of logger config. Harmless — the TMC2209 UART is CRC-guarded. Document it so nobody
  ever chases it as a fault.
- **Bench gate: D4184 TRIG must sit LOW when floating** (pump must not run with TRIG
  disconnected). If it does, add 10 kΩ from TRIG to GND on that module. This preserves
  pumps-stay-off through crashes and brownouts — it replaces the discrete build's
  mandatory 10 kΩ gate pull-down.
- **1N5819** leaded Schottky flybacks directly across each brushed motor's tabs
  (functional equivalent of the spec'd SS34), banded end to +12 V.
- **No master relay, no leak float, no tank floats on this node.** The reservoir-low
  entities exist but are template stubs reading permanently clear — OpenReef's software
  ledger is the empty-guard. Honest residual risk: a shorted MOSFET or TMC2209 runs
  until 12 V is pulled; mitigations are the fuse, dose lines ending **in air above the
  waterline**, and reservoir sizing (never plumb more water than the tank can absorb).
- The AWC panel permits running with no safety sensors bound; from 0.6.7 it asks for a
  one-click **flood-failsafe acknowledgement** first. The manual should present that as
  informed consent, not a nag.
- Kalk chemistry safety is unchanged: dose above the waterline with a siphon break; pH
  guard (via a future sensor node) is the primary chemical safety; never dose cloudy
  slurry.

## 5. The entity-name contract — do not paraphrase this away

The panel auto-binds a doser by **slugified entity-id suffix**, and
`tests/test_entity_contract.py` enforces it in CI — for BOTH reference YAMLs.

1. Never rename entities from the reference YAML. A rename is a breaking API change.
2. `friendly_name` is part of the contract. Multi-node convention: **"OpenReef
   <Function>"** per node — Node 1 uses `friendly_name: OpenReef Dosing`, giving ids
   like `number.openreef_dosing_kalk_dose_volume_ml`. Prefix may vary; suffix may not.
3. ESPHome `text_sensor` registers under HA's `sensor.` domain — the skip-reason binds
   as `sensor.<prefix>_kalk_last_skip_reason`.
4. The kalk pH guard subscribes to the fixed HA-side id
   `sensor.openreef_kalk_ph_mirror` — published by the integration, node-agnostic; the
   probe simply lives on a future sensor node.
5. Frozen skip-reason vocabulary: `disabled · ha_suspend · reservoir_low ·
   not_calibrated · out_of_window · ph_guard · daily_cap · spacing · ok HH:MM`.
6. Auto-bind expects **kalk 25/25** (rev 3) and **live-food 22/22**; the stubbed floats
   keep both counts whole. One auto-bindable channel family per HA instance — extra
   nodes bind via the per-role overrides.

## 6. Known gaps, as of the pivot

- **No calcium-group channel exists.** The Stage E 2-part spacing guard reads
  `group_ca_last_ts`, but nothing writes it — spacing is one-sided until a Ca head
  ships on some node. A manual must not promise two-part spacing as a working feature.
- **fresh2 (source 2) is not on Node 1.** The panel's second-source features apply only
  once a future node hosts it.

## 7. Prompt to use

> Rewrite the hardware chapters of the OpenReef DIY manual for a competent beginner who
> can solder but has never built a doser. The build is **Node 1, the multi-node dosing
> station** — use ONLY the attached files for anything electrical.
> `dosingnode-s3zero-design.md` and `dosingnode-s3zero-reference.yaml` are the build
> authority: every GPIO number must come from them, and you must not reuse any pin
> table found in the other files — those are superseded for this build and are attached
> for prose, diagrams and safety reasoning only (the reefnode files describe a
> different, optional topology; present it as such or not at all). Do not invent part
> numbers, pin assignments or entity names. Where the attached sources are silent, say
> so plainly rather than filling the gap. Keep the entity-name contract verbatim.
> Include the bench gates (D4184 floating-TRIG check; GP43 ROM boot chatter is
> harmless) and the honest residual-risk paragraph. End with the bring-up order:
> smoke test §7–§10, then §11b, then §12 under its Node 1 posture.
