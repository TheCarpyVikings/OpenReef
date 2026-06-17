# Automatic Water Change — hardware, calibration & safety

OpenReef's Automatic Water Change (AWC) does calibrated, **volume-accurate** water
changes: it knows how many litres it moved and how many are left in the reservoir —
something sensor-only controllers (HYDROS, GHL) structurally can't tell you. v1 runs
sequential drain-then-fill changes only, on a flexible schedule (litres **or** %, per
day **or** week), or on demand ("change N litres now").

## What you need (v1)

- **ESP32 + two peristaltic pumps** (standard DC is fine for the v1 sequential prototype;
  steppers can wait until the safety stack is proven) exposed to
  Home Assistant as `switch` entities — one **drain** (sump → waste), one **fill**
  (premixed saltwater → sump). See [`awc-esphome-reference.yaml`](awc-esphome-reference.yaml).
- **Premixed, heated, aged saltwater** in the fresh reservoir — v1 is a pure swap; it
  does not mix or temperature-match for you.
- **Float/optical sensors** (binary): fresh-empty + waste-full.
- **A display/sump high-level cutoff** (independent overfill backstop).
- **A leak sensor** (e.g. Aqara Zigbee or wired) under the system — the last-resort
  flood catch.

Map all of these in **OpenReef → Water Change → Setup & calibration**.

## Calibration

Per pump: run it for a measured number of seconds, measure the dispensed volume,
and enter both in Setup → *Calibrate*. OpenReef derives ml/s and from then on drives
every change by **time = volume ÷ ml/s**. Re-calibrate roughly **every 2 months** —
peristaltic tubing fatigues and the panel will nag you when calibration is stale. The
optional **exchange factor** lets you trim the fill pump so OUT and IN move matched
volumes despite different tube lengths/heads.

## Safety model (layered, enabled by default)

| Layer | Behaviour |
|---|---|
| Leak | **Master kill** — all AWC pumps + the return pump cut, latched. |
| Display high-level cutoff | Aborts the change (overfill), latched. |
| Reservoir floats | Empty fresh ⇒ **pause** fill; full waste ⇒ **pause** drain (auto-resume when cleared). |
| Reservoir model | Blocks start if OpenReef's own fresh/waste counters say the change will not fit. |
| Per-pump max-runtime / volume cap | Fail-locks the change if a leg runs far past its calibrated time. |
| Net-imbalance tracking | Logs cumulative drain-vs-fill; warns before salinity drifts. |
| Calibration-drift nag | Flags stale calibration / tubing age. |
| ATO coordination | Suspends auto-top-off for the whole change + a post-change hold-off (prevents the GHL-style salinity crash). |
| Max single-change cap | Refuses any one change larger than a configurable % of tank volume. |

**Two-tier trip policy:** benign limits (reservoir empty/full) **pause and
auto-resume**; genuine faults (leak, overfill, runtime/volume anomaly) **latch** and
require a manual *Acknowledge & clear* — never a silent auto-retry.

**Local-first:** the hard cutoffs also live in the ESP32 firmware, so a Wi-Fi or Home
Assistant outage can never strand a running pump. OpenReef mirrors them and owns the
orchestration, litre accounting, scheduling, and resume-to-balance after a restart.

**Not yet exposed in v1:** simultaneous and continuous/trickle exchange are kept out
of live control until OpenReef has independent per-pump timers. DIY pump rates drift,
so one shared timer can silently over-drain or over-fill the tank.

## ⚠️ Documented residual risk (v1)

A **welded relay or shorted pump driver** defeats *every* software and firmware
cutoff above — turning a GPIO off cannot stop a physically stuck actuator. v1 ships
software/firmware caps only. Mitigate by:

1. Keeping the **fresh reservoir small** enough that a total dump can't crash
   salinity (treat reservoir size as a safety parameter).
2. Planning the **v2 hardware backstop**: an independent series / master power-cut
   relay on the AWC power rail, and/or a mechanical float valve on the fill line.

Until then, don't run unattended changes larger than you'd be comfortable losing to a
stuck pump.
