# Multi-node pivot — change plan

> **Status:** PROPOSED — nothing lands until Reece approves.
> **Against:** repo v0.6.6, `MULTINODE_PIVOT_BRIEF.md` (2026-08-03).
> **Shape:** two phases. Phase A is docs + the new node YAML + CI coverage (no integration
> code, no release). Phase B is one small integration feature the exploration says we
> genuinely need (release 0.6.7) — separable, recommended, your call.

---

## 0. Verdicts on the §7 open questions (with evidence)

### Q1 — Can the AWC run with no leak / display-high / float entities bound? **Yes, silently. I recommend an acknowledgement gate (Phase B).**

Evidence: `_awc_binary_on(hass, None)` returns False (`__init__.py:5702`), and the
fail-closed "configured-but-unavailable" check explicitly excludes unset entities —
*"Unset entity ⇒ nothing to distrust ⇒ False"* (`__init__.py:5714`). So with nothing
bound, `start_guard_reasons` raises no hazard guard at all: the AWC enables, schedules
and runs with zero hardware failsafes, and nothing in the panel says so.

The repo already has the exact pattern for this: the kalk channel refuses to dose when
no pH entity is bound until the user acknowledges (`dosing.py:346` guard
`ph_unacknowledged`; panel action `doser-ack-no-ph`; WS `openreef/dosing_acknowledge`;
event `ack_no_ph`). Node 1 ships with no leak sensor **by design**, so the honest
posture is the same one-click informed consent, not silence.

**Proposed rule (Phase B):** when `awc.safety.leakEntity` is unset and
`awc.safety.floodMissingAcknowledged` is not true, `start_guard_reasons` adds a
`"block"` (never fault) guard — manual runs included, since this is a safety posture,
not a convenience. Panel: an amber banner in AWC settings mirroring the kalk copy
("No flood failsafe. Reservoir sizing and dose lines ending in air are the only
protection…") with an Acknowledge button. Once acked, behaviour is exactly today's.
If you'd rather Node 1 bring-up isn't gated on a new feature, Phase A can land first —
the ack only ever *adds* a guard.

### Q2 — Board / framework / logger / LED for the S3 Zero clone

The reefnode reference uses `board: esp32-s3-devkitc-1` + **arduino**
(`reefnode-s3-reference.yaml:93-96`). Keep both for the dosing node — same board def
works for the Zero, and arduino is the framework the slimcdk TMC2209 component is
already expected to compile against (build brief §7).

- `esp32: flash_size: 4MB` stated explicitly (S3FH4R2 = 4 MB; clones commonly match —
  verify with esptool's flash_id line on first flash).
- **Logger:** `logger: hardware_uart: USB_CDC` (arduino). This is the hard constraint
  from giving UART0's pins to the TMC2209; comment in the YAML that esp-idf would use
  `USB_SERIAL_JTAG` instead. Note that USB-CDC logs only appear after USB enumerates —
  early boot is invisible, that's normal.
- **First flash:** hold BOOT while connecting USB-C (native USB, no bridge). Goes in
  the design doc and the YAML header.
- **LED:** substitution `status_led_pin: GPIO21` with a commented optional
  `esp32_rmt_led_strip` block and a "verify at first flash — this clone may be GPIO48;
  edit the substitution, nothing else" note. One YAML serves both.
- Bench check worth writing down: confirm the D4184's TRIG sits low when floating
  (modules usually carry their own pull-down — if this one doesn't, add 10 k). That's
  the fail-OFF property the discrete 10 k gate pull-down spec was providing.

### Q3 — fresh2: **drop it from Node 1.** 

AWC pumps are explicit-bind (`reefnode-s3-reference.yaml` header; panel
`_awcEntitySelect`), and the engine derives available roles from configured pumps
(`awc_engine.fill_roles`), so absence breaks nothing. A phantom `fresh2_pump` switch
would be a control for hardware that doesn't exist — worse than no entity. A future
pump node can host source 2 under its own prefix and be explicitly bound then. The
`fill2_max_runtime` substitution goes with it.

### Q4 — Multi-node assumptions in auto-bind: **one real constraint, no blockers.**

Auto-bind matches by suffix with `keys.find(...)` — **first match wins**
(`openreef-panel.js:9485`). Two nodes exposing the same doser-suffix family would bind
nondeterministically. Not a problem today (Node 1 is the only doser node), and stored
config keeps explicit ids with per-role overrides, so even then it's recoverable by
hand. Constraint to document in the design doc: *one auto-bindable channel per suffix
family per HA instance; additional nodes of the same type bind via the per-role
overrides.* Prefix-scoped scanning is backlog, not now.

Everything else checks out: AWC pumps/sensors are explicit-bind; the pH mirror is the
fixed **HA-side** id `sensor.openreef_kalk_ph_mirror` published by the integration, so
it's node-prefix-independent and already multi-node-shaped; backend sync uses stored
entity ids. Auto-bind also accepts bare prefix-less ids, so any `friendly_name` works.

### Q5 — Naming convention

Files: `<function>node-<board>-…` → `docs/manual/dosingnode-s3zero-design.md` +
`dosingnode-s3zero-reference.yaml`. Node hostname `openreef-dosing`; `friendly_name:
OpenReef Dosing` → entity prefix `openreef_dosing_` (suffix contract unaffected).
Reserved future names: `sensornode` (`openreef-sense`), and whatever hosts tank-side
plumbing later. The reefnode keeps its name as the single-node alternative.

---

## 1. Phase A — files touched

| # | File | Action |
|---|---|---|
| 1 | `docs/manual/dosingnode-s3zero-reference.yaml` | **NEW** — the Node 1 flashable node, derived per the checklist below |
| 2 | `docs/manual/dosingnode-s3zero-design.md` | **NEW** — pin/contract authority for Node 1, mirroring the reefnode design doc's structure (pin table, safety model *without* relay + honest residual-risk section, brushed table pointer, bring-up order, Q4 constraint) |
| 3 | `docs/manual/reefnode-s3-design.md` | Header relabel: "alternative single-node topology", pointer to the dosingnode docs as the current build. No pin/entity changes. |
| 4 | `docs/manual/reefnode-s3-reference.yaml` | Same relabel in the header comment block only. |
| 5 | `docs/HARDWARE_BUILD_BRIEF.md` | §3/§4 rewritten: multi-node topology, real bench state (the "nothing physical exists" line goes), D4184 modules (own gate circuitry — the 150 Ω/10 kΩ spec stays for discrete builds, noted as such), 1N5819 ≈ SS34, S3 Zero. §4 becomes a pointer to the two per-node authorities. |
| 6 | `docs/OPENREEF_DOSING_SMOKE_TEST.md` | New §11b "Dosing node (S3 Zero) variant": no relay/coil-float/leak checks; stubbed floats verified present and reading clear; auto-bind still **25/25 + 22/22**; watchdogs still latch (software lock + Clear Lock). §12 precondition reworded: the relay precondition applies to topologies that fit one; on Node 1 the soak's flood exposure is bounded by reservoir sizing, dose lines ending in air, and the fuse — size reservoirs so a total discharge is absorbable, and take the Phase-B acknowledgement if it has landed. |
| 7 | `docs/manual/HARDWARE_HANDOVER_BRIEF.md` | **Regenerated** against the new authority (D4184/1N5819/S3-Zero facts, USB logger + BOOT-hold, stub-float note replacing the float-polarity gotcha, same "superseded pin tables" warnings now including the reefnode map for Node-1 purposes). |
| 8 | `tests/test_entity_contract.py` | Extended: `_DOSINGNODE_YAML` joins the parse list; the three reefnode assertions (friendly_name kept, every frozen kalk entity present, every brushed entity present) run against it too. Float stubs keep contract names, so this passes — and CI now holds the new node to the same contract forever. |

### YAML derivation checklist (item 1, from `reefnode-s3-reference.yaml`)

**Keep byte-identical:** the kalk channel (guard chain, pH-mirror subscription, all 25
rev-3 entities), the live-food channel (all 22, chaser included — its borrowed fresh
pump exists here on GP2), AWC drain/fill switch names, watchdog durations (180 s /
180 s / 60 s), `Kalk HA Suspend` boots `ALWAYS_OFF`, skip-reason vocabulary, SNTP
midnight reset, slimcdk pin-the-ref comment.

**Change:**
- Pins per brief §3: drain GP1, fill GP2, livefood GP4, TMC ENN GP5 / INDEX GP6 /
  TX GP43 / RX GP44. Header pin-budget comment rewritten for the Zero (GP3 skipped —
  strapping; GP7–GP13 spare; GP14–18 bottom pads unused; 33–37 not broken out).
- `logger: hardware_uart: USB_CDC` + `flash_size: 4MB` + LED substitution per Q2.
- `kalk_reservoir_low` + `live_food_reservoir_low` → **template binary_sensor stubs**,
  names and device_class untouched, `lambda: return false;`, commented honestly ("no
  float on this node — the software reservoir ledger is the empty-guard").
- **Removed:** fresh2 switch + its watchdog + `fill2_max_runtime`; leak (15);
  display_high (16); fresh_empty (17); fresh2_empty (18); waste_full (21);
  `master_enable` + the on_boot energise (replaced by a boot log line).
- **Latch reworked as software-only:** `awc_locked`, `kill_all_pumps`, Clear Lock and
  the watchdog trip path stay; comments state plainly that a shorted MOSFET/TMC on this
  node runs until 12 V is pulled, and the mitigations are the fuse, lines-in-air, and
  reservoir sizing.
- `substitutions:` → `node_name: openreef-dosing`, `friendly_name: OpenReef Dosing`.

**One naming decision I've taken (veto if wrong):** the two node-branded entities.
`Master Enable` is gone with the relay; **`Reefnode Clear Lock` becomes `Dosing Clear
Lock`** on this node. It's explicit-bind and not in any suffix table, so nothing
breaks — and "Reefnode Clear Lock" on a node that isn't the reefnode would be a
permanent confusion. The design doc records both names.

## 2. Phase B — the flood-failsafe acknowledgement (recommended, separable)

Scope: `awc.safety.floodMissingAcknowledged` (normaliser + default false), one guard in
`awc_engine.start_guard_reasons` (block, incl. manual, when leakEntity unset and not
acked), a WS ack path reusing the existing `openreef/awc_*` shape, panel banner + button
in AWC settings mirroring the kalk no-pH copy, activity log entry on ack. Tests: engine
guard both ways, WS ack round-trip, normaliser default — into `test_awc_safety.py` +
`test_awc.py`, plus the §11b smoke line. CORE_SCHEMA_VERSION 49→50, release **0.6.7**.

## 3. Sequencing, validation, and what I can't verify here

1. Phase A lands as one commit (docs + YAML + contract test). CI: full suite must stay
   green — the contract test extension is the real gate.
2. Handover brief regenerates in the same commit (item 7), so Claude Chat writes the
   manual against docs that already agree with the copper.
3. Phase B (if approved) is its own commit + release, after Phase A.
4. **I cannot compile ESPHome here.** The YAML will be contract-tested and eyeballed,
   but first compile happens at your bench — the design doc gets a "first compile
   checklist" (pin the slimcdk ref, confirm `USB_CDC` accepted, confirm LED pin, run
   `esphome config` before `run`).

**Untouched, per brief §6:** every entity name in the suffix tables, guard chains,
skip-reason vocabulary, calibration ceremonies, pH-mirror pathway, write-then-verify
sync, the panel, all engines. The bench-starter YAML stays out of the repo.

## 4. Decisions taken in this plan (each vetoable)

1. fresh2 **dropped** from Node 1 (Q3).
2. Flood-failsafe **ack recommended**, trigger = leakEntity unset (Q1) — Phase B.
3. `Reefnode Clear Lock` → **`Dosing Clear Lock`** on the new node (§1 checklist).
4. §12 soak wording for relay-less topologies: allowed with sized reservoirs +
   lines-in-air + ack, rather than forbidden (item 6).
5. Naming convention as in Q5.

## 5. Definition of done (brief §8)

Plan approved → Phase A commit (docs + YAML + CI) → handover brief regenerated →
Claude Chat writes the hardware manual → optional Phase B release 0.6.7. Bench work
is never blocked by any of it.
