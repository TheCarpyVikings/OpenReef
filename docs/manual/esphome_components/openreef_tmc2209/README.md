# OpenReef TMC2209 safety wrapper

Copy this entire `openreef_tmc2209` directory into
`esphome_components/` beside `dosingnode-s3zero-reference.yaml` in ESPHome.
The YAML selects `platform: openreef_tmc2209`; do not replace it with the
upstream `tmc2209` platform.

`SafeTMC2209Stepper` holds the active-low ENN line high before UART setup,
refuses enable/target commands until setup succeeds, cuts ENN before issuing a
UART stop, and disables the motor on shutdown. Node 1 requires both an ENN
connection and INDEX feedback. This is a software control of ENN, not an
independent electrical power cutoff.

`tmc2209_stepper.h` and `tmc2209_stepper.cpp` originate from
[slimcdk/esphome-custom-components at b5f0e44](https://github.com/slimcdk/esphome-custom-components/tree/b5f0e44ae8732f68b9bbeaed9e962ca052d04cdb/esphome/components/tmc2209/stepper).
The source copy changes the final setup enable to `false`; the safety wrapper
adds the ENN gate. ESPHome only includes a platform's C++ files when that
platform is selected, so these two files are needed by the wrapper. All UART,
register and generic stepper code continues to come from the same pinned
upstream component. Update this copy and the wrapper together when changing
that pin, and rerun both the firmware fault tests and the full ESP32 compile.

Tests: `python3 tests/test_dosingnode_safety.py` from the repository root.
