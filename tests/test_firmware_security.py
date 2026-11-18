"""Security defaults and real heater predicates; no firmware upload or hardware.

Run: python3 tests/test_firmware_security.py (PyYAML and g++ required).
"""

from pathlib import Path
import subprocess
import tempfile
import unittest

import yaml


ROOT = Path(__file__).resolve().parents[1]


class SecretReference(str):
    pass


class Loader(yaml.SafeLoader):
    pass


Loader.add_constructor("!secret", lambda loader, node: SecretReference(loader.construct_scalar(node)))
Loader.add_constructor("!lambda", lambda loader, node: loader.construct_scalar(node))


def config(path):
    return yaml.load((ROOT / path).read_text(), Loader=Loader)


class FirmwareSecurityTests(unittest.TestCase):
    def test_every_reference_requires_authenticated_api_and_ota(self):
        paths = sorted((ROOT / "docs/manual").glob("*reference.yaml"))
        paths.append(ROOT / "esphome/openreef_edge_failsafes.example.yaml")
        keys = []
        for path in paths:
            with self.subTest(profile=path.name):
                cfg = config(path)
                key = cfg["api"]["encryption"]["key"]
                self.assertIsInstance(key, SecretReference, "never embed a real key in a template")
                keys.append(key)
                self.assertGreaterEqual(str(cfg["esphome"]["min_version"]), "2026.10.0")
                for ota in cfg["ota"]:
                    self.assertEqual(ota["platform"], "esphome")
                    self.assertIn("encryption", ota, "OTA must authenticate even on the LAN")
                    self.assertFalse((ota["encryption"] or {}).get("allow_plaintext_upload", False))
                    self.assertNotIn("password", ota)
        self.assertEqual(len(keys), len(set(keys)), "profiles must request separate device keys")

    def test_repeated_ato_commands_do_not_extend_the_running_timer(self):
        cfg = config("esphome/openreef_edge_failsafes.example.yaml")
        script = next(item for item in cfg["script"] if item["id"] == "ato_timed_run")
        self.assertEqual(script["mode"], "single", "restart/queued mode permits extension of a run")
        self.assertEqual(script["then"][-1], {"switch.turn_off": "ato_pump_relay"})

    def test_real_heater_guards_fail_closed_for_leak_unknown_sensor_and_bad_temperature(self):
        cfg = config("esphome/openreef_edge_failsafes.example.yaml")
        switch = next(item for item in cfg["switch"] if item["id"] == "heater_guarded")
        enable = switch["turn_on_action"][0]["if"]["condition"]["lambda"]
        cutoff = cfg["interval"][0]["then"][0]["if"]["condition"]["lambda"]
        for key, value in cfg["substitutions"].items():
            enable = enable.replace("${" + key + "}", str(value))
            cutoff = cutoff.replace("${" + key + "}", str(value))
        source = """
#include <cassert>
#include <cmath>
#include <limits>
struct Binary { bool known=true, state=false; bool has_state() { return known; } } leak_sensor;
struct Temp { float state=25; } tank_temp;
#define id(name) name
bool enable() { ENABLE }
bool cutoff() { CUTOFF }
int main() {
  assert(enable()); assert(!cutoff());
  leak_sensor.state=true; assert(!enable()); assert(cutoff());
  leak_sensor.state=false; leak_sensor.known=false; assert(!enable()); assert(cutoff());
  leak_sensor.known=true;
  for (float value : {std::numeric_limits<float>::quiet_NaN(),
                      std::numeric_limits<float>::infinity(),
                      -std::numeric_limits<float>::infinity(), 27.0f}) {
    tank_temp.state=value; assert(!enable()); assert(cutoff());
  }
}
""".replace("#include <limits>", "#include <limits>\n#include <initializer_list>")
        source = source.replace("ENABLE", enable).replace("CUTOFF", cutoff)
        with tempfile.TemporaryDirectory(prefix="openreef-heater-security-") as directory:
            root = Path(directory)
            (root / "guard.cpp").write_text(source)
            subprocess.run(["g++", "-std=c++17", "-Wall", "-Werror", str(root / "guard.cpp"),
                            "-o", str(root / "guard")], check=True, capture_output=True)
            subprocess.run([str(root / "guard")], check=True, capture_output=True)


if __name__ == "__main__":
    unittest.main()
