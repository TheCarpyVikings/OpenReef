# Dosing node — Node 1 of the multi-node topology (ESP32-S3 Zero)

**Start here:** [interactive NPS build guide](nps-build-guide.html) — short steps,
saved progress and separate wiring, flashing and bench-test checkpoints. This
document supplies its pin map and detailed commissioning reference.

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
framework; `USB_SERIAL_JTAG` under esp-idf). This keeps application logs off
the driver UART. ROM boot output is separate; see the physical check below.

## 2. Bench gates — pass these before wiring is called done

1. **D4184 floating-TRIG check (fail-OFF gate).** With 12 V applied and the TRIG
   wire disconnected, the pump must NOT run. Most D4184 modules carry their own
   gate pull-down; verify this one does — if the pump twitches or runs with TRIG
   floating, **add a 10 kΩ resistor from TRIG to GND** on that module and
   repeat the check. This supplies a floating-input pull-down; the actual
   crash, reset and power-interruption checks still need to pass.
2. **ROM boot output on GP43 is expected; prove no motion at boot.** The S3's
   boot ROM can transmit on GP43 before application firmware runs, independently
   of the logger setting. CRC checking is not a physical fail-OFF guarantee.
   Verify ENN keeps the driver disabled and that cold boot, reset and power
   interruption cause no uncommanded movement, with outlets in catch containers.
3. **Flyback diodes.** Fit suitable diodes directly across each brushed motor's
   tabs, banded end to motor positive. A 1N5819 is rated 1 A; an SS34 is rated
   3 A, so they are not interchangeable by assumption. Check the actual motor
   current, switching transients and diode thermal ratings before accepting
   the installed part.

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
fused motor rail, dose outlets ending **in air above the tank waterline**, and
limited source and waste volumes. An outlet air gap prevents tank back-siphoning
but does not stop an elevated source siphoning forward. Test every line with
power off at its actual heights; do not rely on pump tubing as a guaranteed
siphon stop. Limit both possible addition and removal to what the tank can tolerate.
The single-node topology's master fail-OFF relay + hardware coil float remain
available by building the reefnode instead; Node 1 trades them for simplicity
knowingly.

<a id="5-checked-build-and-commissioning--2026-10-25"></a>

## 5. Checked build and commissioning — rechecked 2026-10-31

The **current workspace source**, including its API/OTA encryption changes,
was validated and compiled with **ESPHome 2026.10.0**, Arduino on ESP-IDF
5.5.6, for a 4 MB ESP32-S3: configuration hash `0x40a91e4a`, RAM 32.4%,
flash 49.6%. This is a source snapshot, not a claim that v0.7.228 contains
these later changes. No physical board was flashed. The build used dummy
credentials in a temporary copy; compile your own configuration. Confirm the
actual board/clone flash size and motor rating before using these defaults.

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
  UART + INDEX design. On the documented BTT V1.3 board, factory PDN_UART
  routing uses J1 pin 4; its solder option can reroute it to pin 5. Identify
  the actual PDN_UART connection and solder state on your board, using its
  manufacturer diagram; do not assume every clone has the same routing.
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
   the entity names, GPIOs and pinned external-component ref. In your local
   ESPHome secrets, provide `wifi_ssid`, `wifi_password` and a unique
   `openreef_dosing_encryption_key` (32 random bytes, base64 encoded). The
   current YAML requires that API key and its OTA encryption inherits it.
   Keep these values local; do not paste them into the guide, logs or repository.
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
2. Keep individual channel enables and schedules **off** during setup and
   calibration. In OpenReef, **Settings → Dosing → Show the Dosing tab** is
   also the dosing master control; it must be on for the later dose tests.
3. In **Settings → Dosing channels**, use **+ Live food doser** for the
   brushed food head. This preset selects **Live food** and the brushed
   driver; rename the channel for rotifers if needed. Auto-bind **22/22**,
   then **Save**. **+ Live brine pump** in NPS settings is the same preset.
4. In **Settings → Automated NPS system**, use **+ Phyto pump**. This selects
   **Food** and the stepper driver. Configure it in **Settings → Dosing
   channels**, auto-bind **25/25**, then Save. Its device entities still say
   **Kalk**; do not rename them. There is no separate driver-type selector.
   If multiple devices match, select the correct entity overrides. Counts
   alone do not prove readiness: check availability, successful sync and
   actual pump identity during the cup tests.
5. Pick **AWC Drain Pump** and **AWC Fill Pump** explicitly in Water Change
   setup. Calibrate those from that page later; they do not use the food
   channel's calibration button.
6. **Automatic rinse is disabled** in both the integration and this firmware.
   It shares the AWC saltwater fill pump and cannot safely run independently.
   Flush the food line manually. Old saved chaser values are not actuated.

### 4. Prove one food pump at a time with water into a jug

1. Place both ends away from the aquarium. Leave the real food-shelf bottle
   unlinked while testing with water, so test doses do not debit actual food
   stock. Power the assembled node and pass the floating-trigger/boot checks
   in §2. All motor outputs must be stopped.
2. Use **Prime once (~5 s)** until the outlet is bubble-free. Confirm flow
   direction and the actual delivered water; the UI alone cannot confirm flow.
3. **Brushed:** run the **30 s burst**, measure its output, enter that volume
   and **Save calibration**. **Stepper:** run **100 revolutions**, collect all
   output, enter it and save. The reference requests **320,000 microsteps**:
   100 revolutions assumes a 200-full-step motor at 16 microsteps. At the
   default 400 steps/s this takes **800 s (13 min 20 s)**. Confirm the motor
   specification and wait for it to stop before measuring.
4. Reboot with schedules off; confirm calibration survives and neither pump
   starts. Check sync is successful and all bound entities are available.
5. With water still going to the jug, give the channel a small test schedule,
   sufficient daily cap and fresh reservoir record. Turn on **Channel enabled**
   and **Scheduled dosing**, set a positive daily amount, Save and verify
   **synced**. Manual **Dose now** still needs the firmware enable, calibration,
   freshness and guards; it is not a bypass. Deliver a measured test dose and compare with the command, then disable/save. Tiny
   phyto pulses belong on the stepper; verify many pulses together because a
   household jug cannot resolve 0.1 ml. Brushed runs must be under 60 s.
6. Check disable/suspend and daily-cap refusal. For a **lost INDEX** test,
   power off, disconnect INDEX, power up and use the ESPHome device's **Kalk Prime / Test (run 5s)** button in HA,
   with the outlet in the jug. It should trip after roughly 2–3 s without INDEX progress and refuse
   another motion.
   Power off, restore INDEX, reboot and clear the lock before retesting.
7. Disconnect Wi-Fi/API during a food test; verify motion stops. Stop Home
   Assistant while keeping the device online; verify the firmware dosing-enable switches turn OFF within 180 s and
   no subsequent scheduled motion occurs. A tiny dose that has already
   finished cannot prove this; keep a separate ESPHome network log viewer
   connected to observe the device while HA is stopped. Check it stays stopped after a tripped-node reboot.
8. In Water Change → **Pumps & calibration**, run drain and fill separately
   into containers using **Run 30 s**, **Run 60 s** and **Save fit**. Prove
   their 180 s watchdog with a bounded water supply/catch container before
   relying on water exchange. OpenReef refuses any normal leg longer than 170 s before starting the drain; choose
   smaller, more frequent changes if the calibrated pumps need longer. Restart HA
   during a water change: both pumps must stop and a fault must require you to
   reconcile levels. It must never automatically fill based on downtime.

### 5. Connect food and start a small schedule

- Select the correct shelf bottle. If pumping directly from that bottle,
  check **The bottle IS the reservoir**. If you decant into a separate jar,
  leave it unchecked and log each refill instead. Set the actual container
  volume and choose **Refrigerated** only when physically chilled.
- For a decanted jar, **Refilled — reset ledger** records its volume and
  transfer; **Refreshed today** records its food age. Standing **Loaded today**
  can combine freshness and the linked transfer. Only record food actually
  added. A refrigerated bottle keeps the shelf's opened date and shelf life;
  a Refreshed tap does not make an old bottle fresh.
- Check freshness explicitly: ordinary **Food** channels default to shelf life
  0 (tracking off). A refrigerated linked bottle uses its shelf clock. For
  the intended room-temperature phyto drip, **Standing density (phyto drip)**
  exposes freshness controls and starts with a day clock. Inspect its preview:
  if measured bottle density is supplied, standing mode can derive ml/day.
  Do not treat an unmeasured density as a dose prescription.
- Prime into a cup and check the outlet above the tank's waterline, then prove
  power-off behaviour with the actual source heights. Set the daily amount
  deliberately; this review does not prescribe a new feeding dose. Use the current measured daily amount as the
  starting point, spread over the day, then verify the preview and daily cap.
- Enable the channel and schedule, save, and check **synced**. Watch the first
  doses and compare measured output with the bottle ledger after its update.
  The ESPHome counters estimate commanded volume; no flow sensor proves food
  reached the tank. Observed counter changes and their matched-drain debt are
  saved together; an interrupted dose must not report its full target as delivered.
- Leave **Matched drain on** off until the AWC bucket checks pass. Link only
  live-food suspension whose **measured salinity matches the tank**: a rinsed
  crop resuspended in tank-strength saltwater, not 27 ppt culture water or
  unmatched phyto. Check total added liquid and salinity during supervised runs.
- Follow the [interactive build checkpoints](nps-build-guide.html) and the
  [current audit's hardware acceptance](../AWC_NPS_SAFETY_AUDIT.md#hardware-acceptance-still-required).
  The older dosing smoke test §11b/§12 is superseded for this Node 1 build;
  its chaser and outage instructions do not match the current firmware.

**Limits of this review:** direction, actual flow, clone GPIO/power details,
thermal behaviour and physical fail-OFF remain bench checks. Automatic rinse
is disabled. This node has no independent relay, leak sensor, measured flow
or real reservoir float. A persisted software lock cannot stop failed power
electronics. No claim of hardware acceptance follows from a successful build.
See [the safety audit](../AWC_NPS_SAFETY_AUDIT.md) for the fault cases and the
remaining commissioning gates before unattended use.
