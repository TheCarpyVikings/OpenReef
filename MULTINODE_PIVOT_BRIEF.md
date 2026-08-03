# OpenReef Multi-Node Pivot Brief — sync the repo to the physical build

> **Audience:** Claude Fable, working inside the OpenReef repository.
> **From:** the hardware side (Reece + Claude Chat, at the bench).
> **Date:** 2026-08-03, written against repo state v0.6.6 / `HARDWARE_HANDOVER_BRIEF.md`.
> **Requested deliverable:** a change plan first — not immediate rewrites. Explore the repo, propose the plan (docs + firmware touched, decisions taken on the open questions in §7), and wait for Reece's approval before landing it.

---

## 1. Why this brief exists

The repo's hardware documents assume the **single-node reefnode** ("one ESP32-S3 hosts everything") and state that *"Nothing physical exists yet. No pumps built, no boards flashed."* Both assumptions are stale.

Reece pivoted the architecture to **distributed multi-node** — each equipment group gets its own ESP32 — and has been physically building the first node for several bench sessions. That decision was made in the hardware-side chat and never reached the repo; the software arc (through v0.6.6, Stage D–F) completed against the old topology in good faith. Nothing shipped is wasted: the panel, engines, and entity contracts are topology-agnostic. Only the **hardware documents, pin maps, and the reference node YAML** describe a build that no longer matches the copper.

This brief is the missing hand-off. `reefnode-s3-design.md` / `reefnode-s3-reference.yaml` remain valid as *one* topology option (keep them, relabelled as the single-node path); they are no longer **the** build authority for what Reece is building.

## 2. The locked decisions (do not re-litigate)

1. **Topology: multi-node.** Node 1 is a self-contained **4-channel dosing station** — a product a user could build or buy as "dosing pumps," not a full AWC system. Tank telemetry and tank-side safety sensors (pH, temp, SCD30, leak, display-high, tank floats) will live on **other nodes, later**, syncing through HA.
2. **Node 1 is PUMPS ONLY.** No physical sensors of any kind on this node. This was stated repeatedly and is final.
3. **Node 1 hardware (much of it already soldered):**
   - 3× Kamoer KPHM100 brushed 12 V — reference roles: **drain (GP1), fill (GP2), live-food (GP4)** — driven by **D4184 dual-MOSFET trigger modules** (not discrete AO3400A/IRLB8721; the modules carry their own gate circuitry — update the electrical spec prose accordingly)
   - 1× Kamoer KPHM100-STB10 stepper (kalk) on a genuine **BTT TMC2209 V1.3**, UART addr 0x00, R_SENSE 0.11 Ω — unchanged from the existing kalk design
   - **1N5819** leaded Schottky flybacks soldered directly across each brushed motor's tabs (functional equivalent of the spec'd SS34)
   - Board: **ESP32-S3 Zero (clone)** — castellated, header pins GP1–GP13 + GP43/44 only; GPIO33–37 not broken out; GPIO14–18 exist only as bottom pads (unused in this build); onboard WS2812 on GP21 (genuine Waveshare) **or possibly GP48 on this clone — treat the LED pin as a substitution to verify at first flash**
   - One fused 12 V motor rail; 12 V→5 V buck feeds the Zero; Zero 3V3 → TMC VIO
   - No master relay, no leak float, no tank floats on this node
4. **Bench state:** pump pigtails + waterproof connectors soldered (drain + fill), diodes fitted, modules headered, Zero being headered. **No wire is pin-committed yet** — the pin map below is what will be plugged.

## 3. The Node 1 pin map — new build authority for the dosing station

| Signal | GPIO | Notes |
|---|---|---|
| drain_pump MOSFET gate | **GP1** | D4184 TRIG input |
| fresh_pump (fill) MOSFET gate | **GP2** | D4184 TRIG input |
| livefood_pump MOSFET gate | **GP4** | GP3 skipped (strapping) |
| TMC2209 ENN | **GP5** | low = enabled |
| TMC2209 INDEX | **GP6** | |
| TMC2209 UART TX | **GP43** | the Zero's "TX" silk = UART0 default |
| TMC2209 UART RX | **GP44** | the Zero's "RX" silk |
| spares | GP3, GP7–GP13 | GP21 (or 48): onboard LED |

**Hard constraint this creates:** UART0's default pins are being given to the TMC2209, so the **logger must move to native USB** — `logger: hardware_uart: USB_SERIAL_JTAG` (esp-idf) or `USB_CDC` (arduino); verify which compiles against the chosen framework. Without this line the boot log corrupts the stepper driver. Also doc-worthy: first flash requires holding BOOT while connecting USB-C (native USB, no bridge chip).

## 4. Firmware ask: a dosing-node reference YAML

Derive `dosingnode-s3zero-reference.yaml` (naming per repo convention) from `reefnode-s3-reference.yaml`:

**Keep verbatim (frozen contracts):**
- The entire kalk channel — guard chain, pH mirror subscription (`sensor.openreef_kalk_ph_mirror` — this HA-side pathway is *exactly* multi-node-friendly and needs zero change; the probe will simply live on a future sensor node), all 25 contract-rev-3 entities. The reservoir-low sensor survives as a stub (below), so the 25/25 auto-bind count holds.
- The entire live-food channel — all 22 entities, including the chaser (the AWC fresh pump it borrows exists on this node at GP2).
- AWC drain/fill switches with reference names (explicit-bind), max-runtime watchdogs (drain/fill 180 s, live-food 60 s — keep; they're free safety).

**Change:**
- Pins per §3.
- `kalk_reservoir_low` and `live_food_reservoir_low` become **template stubs reading permanently clear** (`lambda: return false;`), names untouched. Accepted trade, decided: the software reservoir ledger is the empty-guard; physical floats are not fitted on this node.
- **Remove:** fresh2 channel (no physical pump — recommended; explicit-bind means no contract breakage), leak (GPIO15), display_high (16), fresh_empty (17), fresh2_empty (18), waste_full (21), and the master_enable relay GPIO.
- **Rework the latch:** keep `awc_locked`, `kill_all_pumps`, `Clear Lock` and the watchdog trip path as a software latch; there is no relay to drop on this node. Be honest in comments: on this node a shorted MOSFET/TMC runs until 12 V is pulled; mitigations are the fuse, dose lines ending in air above the waterline, and reservoir sizing.
- Node identity: set a per-node `friendly_name` and **document the multi-node prefix convention** (contract rev 2 already allows any prefix; multiple nodes need distinct prefixes to avoid entity-id collisions — propose the convention).

## 5. Docs ask

- New `dosingnode` design doc = pin/contract authority for Node 1 (mirror the structure of `reefnode-s3-design.md`).
- `reefnode-s3-design.md` + its YAML: relabel as the alternative single-node topology, not the default path.
- `HARDWARE_BUILD_BRIEF.md`: update §3/§4 (topology, bench state, D4184 modules, 1N5819, S3 Zero) — the "nothing physical exists" line goes.
- `OPENREEF_DOSING_SMOKE_TEST.md`: add a Node-1 variant of §11 (no relay/leak checks; stubbed floats read clear; auto-bind expectations unchanged at 25/25 + 22/22; §12 soak's relay precondition applies only to topologies that fit one).
- Regenerate `HARDWARE_HANDOVER_BRIEF.md` to point at the new authority — after that lands, Claude Chat writes the DIY manual hardware chapters against it.

## 6. What does NOT change

Entity names (never rename anything), the guard chains and skip-reason vocabulary, calibration ceremonies (100 rev / 30 s), the pH-mirror pathway, write-then-verify sync, the panel — all untouched. The bench continues meanwhile on a throwaway bench-starter YAML (copper-proving only; its "Bench …" entity names are deliberately non-contract and will be replaced by the production node).

## 7. Open questions for the plan

1. Does the AWC panel currently permit arming with **no** leak/display-high/float entities bound (Node 1 ships without them), or does it need an acknowledgement path like the kalk "No pH failsafe" ack?
2. Correct ESPHome board definition for the S3 Zero clone + framework choice, and therefore the logger line and the LED pin (21 vs 48) — propose substitutions so one YAML serves both.
3. fresh2: confirm dropping it from Node 1 (a future node can host source 2), or keep dormant entities — your call with rationale.
4. Any panel assumptions about a *single* node prefix in auto-bind or diagnostics that multi-node would trip — verify and note.
5. File/node naming convention for the multi-node era (dosingnode / sensornode / …).

## 8. Definition of done

Plan proposed → Reece approves → changes land → handover brief regenerated → hardware manual gets written against docs that finally agree with the copper. Until then, nothing on the bench is blocked: Node 1's wiring, bench firmware, and calibration proceed exactly as planned.
