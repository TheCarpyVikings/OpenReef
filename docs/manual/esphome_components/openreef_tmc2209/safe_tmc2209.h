#pragma once

#include "tmc2209_stepper.h"

namespace esphome::openreef_tmc2209 {

// The pinned upstream component enables its driver during setup, including
// after a failed UART probe. Keep its tested motion implementation, but require
// successful setup AND an explicit target before ENN may become active.
class SafeTMC2209Stepper : public tmc2209::TMC2209Stepper {
 public:
  void setup() override {
    // Preload the output latch before changing the pin to output, matching
    // ESPHome's GPIO switch setup order and avoiding an active-low pulse.
    this->enn_pin_->digital_write(true);
    this->enn_pin_->setup();
    this->enn_pin_->digital_write(true);
    this->is_enabled_ = false;
    tmc2209::TMC2209Stepper::setup();
    this->setup_complete_ = !this->is_failed();
    this->enable(false);
  }

  void enable(bool enabled) override {
    const bool allow = enabled && this->setup_complete_ && !this->is_failed();
    if (!allow) {
      // ENN first: loss of UART must not delay the physical stop.
      tmc2209::TMC2209Component::enable(false);
      tmc2209::TMC2209Stepper::stop();
      return;
    }
    tmc2209::TMC2209Component::enable(true);
  }

  void set_target(int32_t steps) override {
    if (!this->setup_complete_ || this->is_failed()) {
      this->enable(false);
      return;
    }
    tmc2209::TMC2209Stepper::set_target(steps);
  }

  void on_shutdown() override { this->enable(false); }

 protected:
  bool setup_complete_{false};
};

}  // namespace esphome::openreef_tmc2209
