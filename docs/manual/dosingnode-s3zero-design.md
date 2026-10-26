# Dosing node — Node 1 of the multi-node topology (ESP32-S3 Zero)

**This document is the pin and contract authority for Node 1** — the 4-channel
dosing station: 3× Kamoer KPHM100 brushed heads (AWC drain, AWC fill, live food)
on D4184 MOSFET trigger modules, plus the KPHM100-STB10 stepper on a BTT
TMC2209 V1.3. The flashable firmware is `dosingnode-s3zero-reference.yaml`, in
this directory. If copper and this document ever disagree, fix one of them the
same day — never let them drift.

**NPS use:** the later phyto-drip decision repurposes the stepper for phyto;
choose **Food** in OpenReef while keeping the firmware's **Kalk** entity names.
The brushed food head uses **Live food**. Those are separate channels.

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
hold and the firmware guard chains keep their `reservoir_low` step. OpenReef estimates the
remaining stock and warns; this is not a physical empty interlock.

**Node identity / multi-node prefix convention:** each node sets
`friendly_name: OpenReef <Function>` ("OpenReef Dosing" here → entity prefix
`openreef_dosing_`). The suffix contract is prefix-agnostic, so any prefix
binds; distinct prefixes are what keep entity ids from colliding across nodes.
Auto-bind refuses ambiguous suffixes when multiple nodes match a role; choose
those entities explicitly in the per-role overrides. Existing bindings are kept
for ambiguous roles. The kalk pH guard
subscribes to the fixed HA-side id `sensor.openreef_kalk_ph_mirror`, published
by the integration — node-agnostic by design; the probe will live on a future
sensor node and nothing here changes when it does.

## 4. Safety model on this node — thinner than the reefnode's, stated plainly

1. Dosing enable switches boot OFF and need a verified OpenReef sync before
   schedules run. The enable lease expires after 180 seconds without renewal;
   losing the API connection stops food dosing. The D4184 floating-TRIG gate (§2.1) checks the
   hardware stays off while GPIOs are floating.
2. Per-pump max-runtime watchdogs (drain/fill 180 s, live food 60 s, stepper
   expected motion time × 1.5 + 5 s, capped at 2 h) FAIL-LOCK the node — a **software** latch (`Clear Lock` re-arms; displays as
   "OpenReef Dosing Clear Lock"). The trip latch survives reboot; an interrupted
   food dose also locks the node. There is no master relay on this node.
3. The reservoir ledger is an estimate, not an automatic physical empty cutoff
   (floats stubbed, §3). HA checks food expiry and renews the firmware enable
   lease only after verifying settings. Expired phyto also stops the standing drip.
4. Flood-hazard sensing (leak, display-high) arrives with a future sensor node
   and acts through HA's AWC guards once bound.

**Residual risk:** a shorted MOSFET or shorted TMC2209 on this node runs until
12 V is pulled — no GPIO and no software latch can stop it. Mitigations: the
fused motor rail, dose lines ending **in air above the waterline** (no siphon
path), and reservoir sizing — never plumb more water than the tank can absorb.
The single-node topology's master fail-OFF relay + hardware coil float remain
available by building the reefnode instead; Node 1 trades them for simplicity
knowingly.

## 5. Checked build and commissioning — 2026-10-25

The reference was **validated and compiled with ESPHome 2026.10.0**, Arduino
on ESP-IDF 5.5.6, for a 4 MB ESP32-S3. No physical board was flashed during the
review. The compile used a temporary copy with dummy Wi-Fi values.

The slimcdk component is pinned at
`b5f0e44ae8732f68b9bbeaed9e962ca052d04cdb`. Driver setup belongs under
`esphome.on_boot`; the old driver-level `on_boot` did not validate. The direct
`enable(false)` method avoids that component's incompatible disable-action
code generation on ESPHome 2026.10.0. The local `esphome_components/openreef_tmc2209`
wrapper holds ENN off during setup and cuts it before UART stop calls. Copy
that directory alongside the YAML; the YAML alone is no longer sufficient.
Current external-component warnings do
not prevent compilation; retest before upgrading ESPHome or that dependency.

### 1. Finish the wiring, with power disconnected

Use the GPIO table in §1, not the older reefnode pin map.

- Feed the D4184 motor supplies and TMC **VM** from the fused 12 V rail.
  Adjust and measure the buck's output at **5 V before connecting the ESP32**.
  Buck output feeds ESP32 **5V**, not 3V3. Tie controller, buck and drivers to
  common ground. Never connect 12 V to an ESP32 pin.
- D4184 trigger inputs: **GP1 drain, GP2 saltwater fill, GP4 live food**.
  Connect supply/load terminals according to the actual module's markings.
  Check the flyback diode band points to motor positive (§2).
- TMC: **GP5 → ENN**, **GP6 ← INDEX**, **GP43 → 1 kΩ resistor → PDN_UART**,
  **GP44 → the same PDN_UART**, **3V3 → VIO**, common GND. Set UART address
  **0** (MS1/MS2 low). Identify the two motor coil pairs before connecting
  A1/A2 and B1/B2; don't rely on wire colour. Keep STEP/DIR unused in this
  UART + INDEX design. Check the BTT board's UART solder configuration.
- The reference initially requests **0.6 A RMS**. Confirm the motor's current
  rating before energising it; this value and driver temperature need a bench
  check. Fit the driver heatsink without bridging pins. Never unplug its motor
  or driver while powered.

Manufacturer references: [Waveshare S3 Zero](https://docs.waveshare.com/ESP32-S3-Zero),
[BTT TMC2209](https://github.com/bigtreetech/docs/blob/master/docs/TMC2209.md),
[the pinned driver's UART wiring](https://github.com/slimcdk/esphome-custom-components/tree/b5f0e44ae8732f68b9bbeaed9e962ca052d04cdb/esphome/components/tmc2209#configuration-of-uart-bus).
Clone markings, flash size and motor rating still need checking on the actual
parts. When USB flashing, disconnect the external buck/12 V supply first.

### 2. Flash the controller

1. Use ESPHome Device Builder **2026.10.0** and copy
   `dosingnode-s3zero-reference.yaml` into a new device configuration. Also copy
   this directory's `esphome_components` folder next to the YAML. Preserve
   the entity names, GPIOs and pinned external-component ref. Enter Wi-Fi in
   your own ESPHome secrets; the file already references `wifi_ssid` and
   `wifi_password`. Keep any API encryption/OTA credentials local.
2. Validate, then compile. From an ESPHome shell the equivalent commands are:
   `esphome config dosingnode-s3zero-reference.yaml` and
   `esphome compile dosingnode-s3zero-reference.yaml`.
3. With the motor rail and external buck disconnected, hold **BOOT**, plug in
   a USB data cable, release BOOT and use **Install → Plug into this computer**
   in Device Builder (or download the factory image and use ESPHome Web).
   If connection fails, hold BOOT while reconnecting. Do not flash the review's
   dummy-network build; compile your own Wi-Fi configuration.
4. Reboot after flashing. Confirm Wi-Fi and USB logs. A TMC communication error
   is expected while its motor supply is disconnected; after powering the
   wired driver, reboot, verify communication and clear the latched fault.
   Do not calibrate a driver reporting failure.

### 3. Add it to Home Assistant and bind it in OpenReef

1. In **Settings → Devices & services**, add the discovered **ESPHome** device
   `OpenReef Dosing`. If discovery misses it, add ESPHome with the device's IP.
2. Keep channel enables and schedules **off** while commissioning.
3. The brushed channel uses the **ESPHome brushed** driver and **Live food**
   chemical. Auto-bind must show **22/22**, then **Save**.
4. The phyto stepper uses **ESPHome stepper** and **Food**. Auto-bind must show
   **25/25**. Its device entities still say **Kalk**; don't rename them. Save.
5. Pick **AWC Drain Pump** and **AWC Fill Pump** explicitly in Water Change
   setup. Calibrate those from that page later; they do not use the food
   channel's calibration button.
6. **Automatic rinse is disabled** in both the integration and this firmware.
   It shares the AWC saltwater fill pump and cannot safely run independently.
   Flush the food line manually. Old saved chaser values are not actuated.

### 4. Prove one food pump at a time with water into a jug

1. Place both ends away from the aquarium. Power the assembled node and pass
   the floating-trigger/boot checks in §2. All motor outputs must be stopped.
2. Prime using bounded test runs until the outlet is bubble-free. Confirm flow
   direction and the actual delivered water; the UI alone cannot confirm flow.
3. **Brushed:** run the **30 s burst**, measure its output, enter that volume
   and **Save calibration**. **Stepper:** run **100 revolutions**, collect all
   output, enter it and save. At the default 400 steps/s, this takes about
   **13 min 20 s**, not 30 seconds. Wait for the motor to stop.
4. Reboot with schedules off; confirm calibration survives and neither pump
   starts. Check sync is successful and all bound entities are available.
5. With water still going to the jug, give the channel a small test schedule,
   sufficient daily cap and fresh reservoir record; enable/save. Deliver a
   measured test dose and compare with the command, then disable/save. Tiny
   phyto pulses belong on the stepper; verify many pulses together because a
   household jug cannot resolve 0.1 ml. Brushed runs must be under 60 s.
6. Check disable/suspend and daily-cap refusal. For a **lost INDEX** test,
   power off, disconnect INDEX, power up and use the stepper's 5 s test into
   the jug. It should trip after roughly 2–3 s without INDEX progress and refuse
   another motion.
   Power off, restore INDEX, reboot and clear the lock before retesting.
7. Disconnect Wi-Fi/API during a food test; verify motion stops. Stop Home
   Assistant while keeping the device online; verify dosing cannot continue
   beyond its 180 s lease. Check it stays stopped after a tripped-node reboot.
8. Run the AWC drain/fill timed calibration separately into containers and
   prove their 180 s watchdog before relying on water exchange. OpenReef
   refuses any normal leg longer than 170 s before starting the drain; choose
   smaller, more frequent changes if the calibrated pumps need longer. Restart HA
   during a water change: both pumps must stop and a fault must require you to
   reconcile levels. It must never automatically fill based on downtime.

### 5. Connect food and start a small schedule

- Select the correct shelf bottle. If pumping directly from that bottle,
  check **The bottle IS the reservoir**. If you decant into a separate jar,
  leave it unchecked and log each refill instead. Set the actual container
  volume and choose **Refrigerated** only when physically chilled.
- Record a fresh load/refill, prime into a cup and check the outlet above the
  tank's waterline. Set the daily amount deliberately; this review does not
  prescribe a new feeding dose. Use the current measured daily amount as the
  starting point, spread over the day, then verify the preview and daily cap.
- Enable the channel and schedule, save, and check **synced**. Watch the first
  doses and compare measured output with the bottle ledger after its update.
  The ESPHome counters estimate commanded volume; no flow sensor proves food
  reached the tank. Observed counter changes and their matched-drain debt are
  saved together; an interrupted dose must not report its full target as delivered.
- Add feed exchange/AWC only after the drain/fill calibration and checks pass.
  Check salinity and total added liquid when feeding live-food suspension.
  Run the acceptance checks in `../OPENREEF_DOSING_SMOKE_TEST.md` §11b/§12
  before unattended use.

**Limits of this review:** direction, actual flow, clone GPIO/power details,
thermal behaviour and physical fail-OFF remain bench checks. Automatic rinse
is disabled. This node has no independent relay, leak sensor, measured flow
or real reservoir float. A persisted software lock cannot stop failed power
electronics. No claim of hardware acceptance follows from a successful build.
See [the safety audit](../AWC_NPS_SAFETY_AUDIT.md) for the fault cases and the
remaining commissioning gates before unattended use.
