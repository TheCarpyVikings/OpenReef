"""Fault injection against Node 1's actual YAML C++ lambdas and ENN wrapper.

Standalone: python3 tests/test_dosingnode_safety.py
Requires the development tools PyYAML and a C++17 compiler; no hardware is used.
This checks decisions/action ordering, not physical pump flow or MCU scheduling.
"""

from pathlib import Path
import re
import shutil
import subprocess
import tempfile
import unittest

import yaml


ROOT = Path(__file__).resolve().parents[1]
YAML_PATH = ROOT / "docs/manual/dosingnode-s3zero-reference.yaml"
WRAPPER = ROOT / "docs/manual/esphome_components/openreef_tmc2209/safe_tmc2209.h"


class Loader(yaml.SafeLoader):
    pass


Loader.add_constructor("!lambda", lambda loader, node: loader.construct_scalar(node))
Loader.add_constructor("!secret", lambda loader, node: loader.construct_scalar(node))
CONFIG = yaml.load(YAML_PATH.read_text(), Loader=Loader)
SCRIPTS = {row["id"]: row for row in CONFIG["script"]}


def cpp_lambda(script):
    code = next(row["lambda"] for row in SCRIPTS[script]["then"] if "lambda" in row)
    return host_code(code)


def host_code(code):
    code = re.sub(r"id\((\w+)\)", r"c.\1", code)
    # Persistent ESPHome globals have a separate component pointer in generated
    # C++. The host records writes while executing the original arithmetic.
    return re.sub(r"(\w+)->update\(\)", r'c.writes.push_back("\1")', code)


PRELUDE = r"""
#include <cassert>
#include <cmath>
#include <cstdint>
#include <limits>
#include <string>
#include <vector>
#define ESP_LOGW(...) ((void)0)
uint32_t tick = 1000;
uint32_t millis() { return tick; }
namespace api {
struct Server { bool connected=true; bool is_connected() { return connected; } } server;
Server *global_api_server=&server;
}
struct Preferences { bool okay=true; bool sync() { return okay; } } preferences;
Preferences *global_preferences=&preferences;
struct Entity {
  float state=0;
  int calls=0;
  bool running=false, failed=false;
  int current_position=0;
  std::string text;
  bool is_running() { return running; }
  bool is_failed() { return failed; }
  void execute() { ++calls; }
  void turn_off() { state=0; ++calls; }
  void publish_state(const std::string &s) { text=s; }
};
struct Clock {
  bool valid=true;
  int year=2026, month=10, day_of_month=25, hour=12, minute=0;
  long timestamp=1792929600;
  bool is_valid() { return valid; }
  Clock now() { return *this; }
};
struct Context {
  bool awc_locked=false, node_ready=true, guard_pass=false, lf_guard_pass=false;
  bool ph_latched_high=false, kalk_in_progress=false, lf_in_progress=false;
  uint32_t kalk_enable_heartbeat=0, lf_enable_heartbeat=0, ph_last_update=0;
  uint32_t stepper_progress_at=0;
  int stepper_last_position=0;
  int dose_day=20261025;
  long group_ca_last_ts=0;
  float steps_per_ml=1000, dosed_today_ml=0, lf_dosed_today_ml=0;
  float completed_today_ml=0, lf_completed_today_ml=0;
  Clock reef_time;
  Entity kalk_driver, run_stepper, kalk_enabled, kalk_ha_suspend, kalk_reservoir_low;
  Entity kalk_window_start_min, kalk_window_end_min, kalk_ph_guard, tank_ph;
  Entity kalk_max_daily_ml, kalk_min_gap_min, kalk_last_skip, kalk_speed;
  Entity lf_run_dose, lf_service_run, livefood_pump, livefood_enabled;
  Entity livefood_ha_suspend, livefood_reservoir_low, livefood_flow_ml_s;
  Entity livefood_window_start_min, livefood_window_end_min, livefood_max_daily_ml;
  Entity livefood_spin_up_ml, livefood_last_skip, trip_lock;
  std::vector<std::string> writes;
  Context() {
    kalk_enabled.state=livefood_enabled.state=1;
    kalk_max_daily_ml.state=livefood_max_daily_ml.state=100;
    livefood_flow_ml_s.state=1; kalk_speed.state=400;
  }
};
"""


class FirmwareSafetyTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.compiler = shutil.which("g++")
        if not cls.compiler:
            raise RuntimeError("Install g++ to run firmware fault-injection tests")

    def run_cpp(self, code, files=None):
        with tempfile.TemporaryDirectory(prefix="openreef-firmware-test-") as directory:
            root = Path(directory)
            for name, content in (files or {}).items():
                path = root / name
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_text(content)
            source = root / "test.cpp"
            source.write_text(code)
            executable = root / "test"
            result = subprocess.run(
                [self.compiler, "-std=c++17", "-Wall", "-Werror", "-I", directory,
                 str(source), "-o", str(executable)], capture_output=True, text=True,
            )
            self.assertEqual(result.returncode, 0, result.stderr)
            result = subprocess.run([str(executable)], capture_output=True, text=True)
            self.assertEqual(result.returncode, 0, result.stderr)

    def test_real_guards_refuse_offline_untrusted_clock_bad_calibration_and_caps(self):
        code = PRELUDE
        code += "void kalk(Context &c,float dose_ml) {" + cpp_lambda("check_guards") + "}\n"
        code += "void food(Context &c,float dose_ml) {" + cpp_lambda("lf_check_guards") + "}\n"
        code += r"""
int main() {
  Context c;
  kalk(c,5); food(c,5); assert(c.guard_pass && c.lf_guard_pass);
  api::server.connected=false;
  kalk(c,5); food(c,5); assert(!c.guard_pass && !c.lf_guard_pass);
  api::server.connected=true;
  tick=180000; kalk(c,5); food(c,5); assert(!c.guard_pass && !c.lf_guard_pass);
  // millis() rollover must not accidentally renew an old lease.
  tick=30; c.kalk_enable_heartbeat=c.lf_enable_heartbeat=UINT32_MAX-10;
  kalk(c,5); food(c,5); assert(c.guard_pass && c.lf_guard_pass);
  c=Context(); tick=1000;
  c.reef_time.valid=false;
  kalk(c,5); food(c,5); assert(!c.guard_pass && !c.lf_guard_pass);
  c.reef_time.valid=true; c.reef_time.day_of_month=24;
  kalk(c,5); food(c,5); assert(!c.guard_pass && !c.lf_guard_pass);
  c=Context(); c.dosed_today_ml=c.lf_dosed_today_ml=96;
  kalk(c,5); food(c,5); assert(!c.guard_pass && !c.lf_guard_pass);
  c.dosed_today_ml=c.lf_dosed_today_ml=95;
  kalk(c,5); food(c,5); assert(c.guard_pass && c.lf_guard_pass);
  for (float bad : {0.0f, -1.0f, 11.0f, NAN, INFINITY}) {
    c=Context(); kalk(c,bad); food(c,bad); assert(!c.guard_pass && !c.lf_guard_pass);
  }
  c=Context(); c.steps_per_ml=NAN; c.livefood_flow_ml_s.state=NAN;
  kalk(c,5); food(c,5); assert(!c.guard_pass && !c.lf_guard_pass);
  c=Context(); c.kalk_max_daily_ml.state=NAN; c.livefood_max_daily_ml.state=NAN;
  kalk(c,5); food(c,5); assert(!c.guard_pass && !c.lf_guard_pass);
  c=Context(); c.dosed_today_ml=c.lf_dosed_today_ml=-100;
  kalk(c,5); food(c,5); assert(!c.guard_pass && !c.lf_guard_pass);
  c=Context(); c.kalk_ph_guard.state=1; c.tank_ph.state=-INFINITY;
  kalk(c,5); assert(!c.guard_pass);
  c=Context(); c.kalk_driver.failed=true;
  kalk(c,5); assert(!c.guard_pass && c.kalk_last_skip.text=="driver_unavailable");
  c=Context(); c.run_stepper.running=true; c.lf_service_run.running=true;
  kalk(c,5); food(c,5); assert(!c.guard_pass && !c.lf_guard_pass);
  c=Context(); c.livefood_flow_ml_s.state=0.05f;
  food(c,5); assert(!c.lf_guard_pass && c.livefood_last_skip.text=="runtime_limit");
  c=Context(); c.livefood_spin_up_ml.state=5;
  food(c,5); assert(!c.lf_guard_pass);
  c=Context(); c.awc_locked=true;
  kalk(c,5); food(c,5); assert(!c.guard_pass && !c.lf_guard_pass);
  c=Context(); c.kalk_ha_suspend.state=c.livefood_ha_suspend.state=1;
  kalk(c,5); food(c,5); assert(!c.guard_pass && !c.lf_guard_pass);
}
"""
        self.run_cpp(code)

    def test_actual_daily_rollover_handles_missed_midnight_and_backward_time(self):
        code = PRELUDE + "void roll(Context &c) {" + cpp_lambda("update_daily_total") + "}\n"
        code += r"""
int main() {
  Context c; c.dosed_today_ml=90; c.lf_dosed_today_ml=50;
  roll(c); assert(c.dosed_today_ml==90 && c.writes.empty());
  c.reef_time.day_of_month=26; roll(c);
  assert(c.dose_day==20261026 && c.dosed_today_ml==0 && c.lf_dosed_today_ml==0);
  c.dosed_today_ml=80; c.reef_time.day_of_month=25; roll(c);
  assert(c.dose_day==20261026 && c.dosed_today_ml==80);
  c.reef_time.day_of_month=27; c.kalk_in_progress=true; roll(c);
  assert(c.dosed_today_ml==80); // Do not discard a running dose's reservation.
  c.kalk_in_progress=false; c.reef_time.valid=false; roll(c);
  assert(c.dosed_today_ml==80);
  c=Context(); c.dose_day=0; c.dosed_today_ml=70; roll(c);
  assert(c.dose_day==20261025 && c.dosed_today_ml==70); // Firmware migration.
  c.reef_time.day_of_month=26; preferences.okay=false; roll(c);
  assert(c.trip_lock.calls==1); // Refuse motion after persistence failure.
}
"""
        self.run_cpp(code)

    def test_actual_lease_monitor_switches_both_channels_off(self):
        monitor = next(row for row in CONFIG["interval"] if row["interval"] == "1s")
        code = PRELUDE + "void monitor(Context &c) {" + host_code(monitor["then"][0]["lambda"]) + "}\n"
        code += r"""
int main() {
  Context c; monitor(c); assert(c.kalk_enabled.state && c.livefood_enabled.state);
  tick=180000; monitor(c);
  assert(!c.kalk_enabled.state && !c.livefood_enabled.state);
  c=Context(); tick=1000; api::server.connected=false; monitor(c);
  assert(!c.kalk_enabled.state && !c.livefood_enabled.state);
  c=Context(); c.kalk_enabled.state=c.livefood_enabled.state=0;
  c.lf_service_run.running=true; monitor(c); assert(c.trip_lock.calls==1);
  c.lf_service_run.running=false; c.run_stepper.running=true;
  c.trip_lock.calls=0; monitor(c); assert(c.trip_lock.calls==1);
  c=Context(); api::server.connected=true; c.run_stepper.running=true; tick=2000;
  monitor(c); assert(c.trip_lock.calls==1); // INDEX disconnected, motor cutoff.
  c=Context(); c.run_stepper.running=true; c.kalk_driver.current_position=5;
  monitor(c); assert(c.trip_lock.calls==0 && c.stepper_progress_at==2000);
  c.kalk_in_progress=true; c.kalk_ph_guard.state=1; c.tank_ph.state=NAN;
  monitor(c); assert(c.trip_lock.calls==1);
}
"""
        self.run_cpp(code)

    def test_motion_is_reserved_and_persisted_before_motor_start(self):
        stepper = SCRIPTS["run_dose"]["then"][0]["lambda"]
        self.assertLess(stepper.index("dosed_today_ml->update()"), stepper.index("global_preferences->sync()"))
        self.assertLess(stepper.index("global_preferences->sync()"), stepper.index("id(run_stepper).execute"))
        food = SCRIPTS["lf_run_dose"]["then"]
        self.assertIn("lf_dosed_today_ml->update()", food[0]["lambda"])
        self.assertIn("global_preferences->sync()", food[0]["lambda"])
        self.assertEqual(food[1], {"switch.turn_on": "livefood_pump"})
        globals_ = {row["id"]: row for row in CONFIG["globals"]}
        for name in ("awc_locked", "dose_day", "kalk_in_progress", "lf_in_progress",
                     "dosed_today_ml", "lf_dosed_today_ml", "completed_today_ml", "lf_completed_today_ml"):
            self.assertTrue(globals_[name]["restore_value"], name)
        sensors = {row.get("id"): row for row in CONFIG["sensor"]}
        self.assertEqual(sensors["kalk_dosed_today"]["lambda"], "return id(completed_today_ml);")
        self.assertEqual(sensors["livefood_dosed_today"]["lambda"], "return id(lf_completed_today_ml);")
        self.assertNotIn("completed_today_ml", stepper)
        self.assertNotIn("lf_completed_today_ml", food[0]["lambda"])
        self.assertIn("completed_today_ml", SCRIPTS["run_dose"]["then"][2]["lambda"])
        self.assertEqual(food[4], {"switch.turn_off": "livefood_pump"})
        self.assertIn("lf_completed_today_ml", food[5]["lambda"])

    def test_trip_abort_watchdogs_and_no_shared_chaser(self):
        kill = repr(SCRIPTS["kill_all_pumps"])
        for actuator in ("drain_pump", "fresh_pump", "stop_livefood", "stop_stepper"):
            self.assertIn(actuator, kill)
        for name, stop in (("kalk_enabled", "stop_stepper"), ("livefood_enabled", "stop_livefood")):
            switch = next(row for row in CONFIG["switch"] if row.get("id") == name)
            self.assertEqual(switch["restore_mode"], "ALWAYS_OFF")
            self.assertIn("heartbeat", repr(switch["turn_on_action"]))
            self.assertIn(stop, repr(switch["on_turn_off"]))
        self.assertNotIn("fresh_pump", repr(SCRIPTS["lf_run_dose"]))
        self.assertEqual(CONFIG["substitutions"]["drain_max_runtime"], "180s")
        self.assertEqual(CONFIG["substitutions"]["fill_max_runtime"], "180s")
        self.assertIn("stepper_watchdog", repr(SCRIPTS["run_stepper"]))

    def test_locked_pump_commands_never_energise_the_physical_gpio(self):
        switches = {row.get("id"): row for row in CONFIG["switch"]}
        for prefix in ("drain", "fresh", "livefood"):
            motor = switches[f"{prefix}_motor"]
            self.assertEqual(motor["platform"], "gpio")
            self.assertTrue(motor["internal"])
            control = switches[f"{prefix}_pump"]
            branch = control["turn_on_action"][0]["if"]
            self.assertEqual(branch["then"], [{"switch.turn_on": f"{prefix}_motor"}])
            self.assertEqual(branch["else"], [{"switch.turn_off": f"{prefix}_motor"}])
            guard = host_code(branch["condition"]["lambda"])
            code = PRELUDE + "bool allow(Context &c) {" + guard + "}\n"
            code += "int main() { Context c; assert(allow(c)); c.awc_locked=true; assert(!allow(c)); c.awc_locked=false; c.node_ready=false; assert(!allow(c)); }"
            self.run_cpp(code)

    def test_actual_driver_wrapper_stays_off_during_failed_setup_and_uart_stop(self):
        stub = r"""
#pragma once
#include <cstdint>
#include <stdexcept>
#include <vector>
#define ESP_LOGE(...) ((void)0)
namespace esphome::tmc2209 {
inline bool setup_fails=false, stop_fails=false;
inline std::vector<int> events;
struct Pin { void setup() { events.push_back(3); } void digital_write(bool high) { events.push_back(high?0:1); } };
class TMC2209Component {
 public:
  virtual void setup() {} virtual void enable(bool enabled) { enn_pin_->digital_write(!enabled); is_enabled_=enabled; }
  bool is_failed() { return failed_; }
 protected:
  Pin pin_; Pin *enn_pin_=&pin_; bool is_enabled_=false, failed_=false;
};
enum ControlMethod { CONTROL_UNSET, SERIAL_CONTROL };
class Stepper { public: void set_target(int32_t) {} };
class TMC2209Stepper : public TMC2209Component, public Stepper {
 public:
  void setup() override { failed_=setup_fails; enable(true); }
  virtual void stop() { events.push_back(2); if(stop_fails) throw std::runtime_error("UART lost"); }
  virtual void set_target(int32_t);
  virtual void on_shutdown() { stop(); }
 protected:
  ControlMethod control_method_=SERIAL_CONTROL;
};
}
"""
        code = '#include <algorithm>\n#include <cassert>\n#include "safe_tmc2209.h"\n'
        motion_source = WRAPPER.with_name("tmc2209_stepper.cpp").read_text()
        # Exercise the real delegated target method too: an overly broad
        # boot-OFF fix must not accidentally prevent every commanded dose.
        target_method = re.search(
            r"void TMC2209Stepper::set_target\(int32_t steps\) \{.*?\n\}",
            motion_source, re.S,
        ).group(0)
        code += "namespace esphome::tmc2209 {\n" + target_method + "\n}\n"
        code += r"""
int main() {
  using namespace esphome::tmc2209;
  esphome::openreef_tmc2209::SafeTMC2209Stepper healthy;
  healthy.setup(); assert(std::find(events.begin(),events.end(),1)==events.end());
  assert(events[0]==0 && events[1]==3); // Latch HIGH before output mode.
  healthy.set_target(3200); assert(events.back()==1);
  events.clear(); stop_fails=true;
  try { healthy.enable(false); } catch (const std::runtime_error &) {}
  assert(events.size()==2 && events[0]==0 && events[1]==2);
  stop_fails=false; setup_fails=true; events.clear();
  esphome::openreef_tmc2209::SafeTMC2209Stepper broken;
  broken.setup(); broken.set_target(3200);
  assert(std::find(events.begin(),events.end(),1)==events.end());
  setup_fails=false; events.clear(); healthy.on_shutdown();
  assert(events[0]==0 && events[1]==2);
}
"""
        self.run_cpp(code, {"tmc2209_stepper.h": stub, "safe_tmc2209.h": WRAPPER.read_text()})


if __name__ == "__main__":
    unittest.main()
