# Dosing node — Node 1 of the multi-node topology (ESP32-S3 Zero)

**This document is the pin and contract authority for Node 1** — the 4-channel
dosing station: 3× Kamoer KPHM100 brushed heads (AWC drain, AWC fill, live food)
on D4184 MOSFET trigger modules, plus the KPHM100-STB10 kalk stepper on a BTT
TMC2209 V1.3. The flashable firmware is `dosingnode-s3zero-reference.yaml`, in
this directory. If copper and this document ever disagree, fix one of them the
same day — never let them drift.

Topology context (`MULTINODE_PIVOT_BRIEF.md`, locked 2026-08-03): each equipment
group gets its own ESP32. **Node 1 is pumps only — no physical sensors of any
kind.** Tank telemetry and tank-side safety (pH probe, leak, display-high, tank
floats) belong to future nodes and reach this one's guards through Home
Assistant. The previous single-node design (`reefnode-s3-design.md`) remains a
valid alternative topology; it is no longer the default build.

## 1. Node 1 pin budget — ESP32-S3 Zero

Header pins available on the Zero: GP1–GP13 and GP43/44. GP3 is a strapping pin
(skip it). GP14–GP18 exist only as bottom pads and are unused in this build;
GPIO33–37 are not broken out at all.

| Signal | GPIO | Dir | Notes |
|---|---|---|---|
| `drain_pump` gate | **1** | out | D4184 TRIG |
| `fresh_pump` (fill) gate | **2** | out | D4184 TRIG |
| `livefood_pump` gate | **4** | out | D4184 TRIG (GP3 skipped — strapping) |
| TMC2209 ENN | **5** | out | low = driver enabled |
| TMC2209 INDEX | **6** | in | |
| TMC2209 UART TX | **43** | out | 500 kBd — the Zero's "TX" silk = UART0 default |
| TMC2209 UART RX | **44** | in | the Zero's "RX" silk |
| spares | 3 (avoid), 7–13 | — | GP21 (or GP48 on some clones): onboard WS2812 |

Power: one fused 12 V motor rail; 12 V→5 V buck feeds the Zero; the Zero's 3V3
pin feeds TMC2209 VIO. TMC2209 at UART address 0x00, R_SENSE 0.11 Ω.

**Hard consequence of GP43/44:** UART0's default pins drive the stepper, so the
logger must run on native USB — `logger: hardware_uart: USB_CDC` (arduino
framework; `USB_SERIAL_JTAG` under esp-idf). Without that line the boot log
corrupts the TMC2209.

## 2. Bench gates — pass these before wiring is called done

1. **D4184 floating-TRIG check (fail-OFF gate).** With 12 V applied and the TRIG
   wire disconnected, the pump must NOT run. Most D4184 modules carry their own
   gate pull-down; verify this one does — if the pump twitches or runs with TRIG
   floating, **add a 10 kΩ resistor from TRIG to GND** on that module. This is
   what preserves pumps-stay-off through an ESP crash, reboot or brownout; the
   discrete-MOSFET spec provided it with the mandatory 10 kΩ gate pull-down, and
   a module build must not silently lose it.
2. **ROM boot output on GP43 — known and harmless, never chase it.** The S3's
   boot ROM prints its own output on GP43 at every reset, before any firmware
   runs, regardless of logger configuration. The TMC2209's UART protocol is
   CRC-guarded, so it ignores the noise. If you sniff the UART lines during
   bring-up you WILL see it; it is not a fault.
3. **Flyback diodes.** 1N5819 leaded Schottky soldered directly across each
   brushed motor's tabs (functional equivalent of the spec'd SS34), banded end
   to +12 V.

## 3. Entity contracts — pointers, not copies

One authority per table; this document deliberately does not duplicate them:

- **Kalk channel (25 entities, contract rev 3):** `kalk-doser-esphome-design.md`
  §6, plus `Kalk Min Gap (min)` from Stage E. Auto-bind expects **25 of 25**.
- **Live-food channel (22 entities, brushed):** `reefnode-s3-design.md` §3 —
  frozen at Stage D and unchanged by the pivot. Auto-bind expects **22 of 22**.
- AWC drain/fill switches are **explicit-bind** but keep the reference names
  (`AWC Drain Pump`, `AWC Fill Pump`).

Both reference YAMLs are held to these tables by CI
(`tests/test_entity_contract.py`) — a rename fails the build.

**Stubbed floats (accepted trade, locked):** `Kalk Reservoir Low` and
`Live Food Reservoir Low` exist as template sensors reading permanently clear —
no floats are fitted on this node. Names are untouched, so the auto-bind counts
hold and the firmware guard chains keep their `reservoir_low` step. The software
reservoir ledger in OpenReef is the empty-guard here.

**Node identity / multi-node prefix convention:** each node sets
`friendly_name: OpenReef <Function>` ("OpenReef Dosing" here → entity prefix
`openreef_dosing_`). The suffix contract is prefix-agnostic, so any prefix
binds; distinct prefixes are what keep entity ids from colliding across nodes.
Constraint to know: the panel's auto-bind is first-match-wins per suffix, so run
**one auto-bindable channel family per HA instance** — a second dosing node
would bind via the per-role overrides, not auto-bind. The kalk pH guard
subscribes to the fixed HA-side id `sensor.openreef_kalk_ph_mirror`, published
by the integration — node-agnostic by design; the probe will live on a future
sensor node and nothing here changes when it does.

## 4. Safety model on this node — thinner than the reefnode's, stated plainly

1. Everything boots OFF (`ALWAYS_OFF`); the D4184 floating-TRIG gate (§2.1)
   extends that through crashes and brownouts.
2. Per-pump max-runtime watchdogs (drain/fill 180 s, live food 60 s) FAIL-LOCK
   the node — a **software** latch (`Clear Lock` re-arms; displays as
   "OpenReef Dosing Clear Lock"). There is no master relay on this node.
3. Reservoir empty-guards are OpenReef's software ledgers (floats stubbed, §3).
4. Flood-hazard sensing (leak, display-high) arrives with a future sensor node
   and acts through HA's AWC guards once bound.

**Residual risk:** a shorted MOSFET or shorted TMC2209 on this node runs until
12 V is pulled — no GPIO and no software latch can stop it. Mitigations: the
fused motor rail, dose lines ending **in air above the waterline** (no siphon
path), and reservoir sizing — never plumb more water than the tank can absorb.
The single-node topology's master fail-OFF relay + hardware coil float remain
available by building the reefnode instead; Node 1 trades them for simplicity
knowingly.

## 5. First compile + bring-up flow

First compile happens at the bench, not in CI (the repo cannot compile ESPHome):

1. Pin the slimcdk `tmc2209` external component to a known-good ref and verify
   the `stepper`/`tmc2209.configure`/`tmc2209.currents` API at first compile
   (`HARDWARE_BUILD_BRIEF.md` §7 gotchas apply unchanged).
2. `esphome config dosingnode-s3zero-reference.yaml` before any `run` — confirm
   `hardware_uart: USB_CDC` is accepted by the installed ESPHome/framework pair.
3. First flash: hold BOOT while connecting USB-C (native USB, no bridge chip).
   USB-CDC logs appear only after USB enumerates — early boot is invisible.
4. LED check: enable the commented `light:` block; if the WS2812 stays dark,
   change `status_led_pin` to GPIO48 (clone variant) and nothing else.
5. Bench gates §2, then power-path checks: buck output, 3V3→VIO, fused rail.
6. Auto-bind: kalk **25/25**, live-food **22/22**; explicit-bind drain + fill.
   Calibrations, one ceremony per channel type: kalk = the 100-rev ceremony;
   live food = its `Calibrate 30s` button (burst into a jug, panel derives
   ml/s); AWC drain/fill = the Water Change panel's own timed calibration run
   (`awc_calibration_run`) — they do NOT use the 30 s dosing button.
7. Watchdog proof: force a >180 s drain command with the tube in a bucket — the
   node must trip, latch, and refuse pumps until Clear Lock.
8. Then `OPENREEF_DOSING_SMOKE_TEST.md` §11b (the Node 1 variant), and §12 with
   its relay-less posture: sized reservoirs, lines in air, flood-failsafe
   acknowledgement taken.
