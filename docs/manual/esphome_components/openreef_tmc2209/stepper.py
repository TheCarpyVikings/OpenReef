"""Keep the TMC2209 physically disabled until a valid motion command."""

import esphome.codegen as cg
import esphome.config_validation as cv
from esphome import pins
from esphome.components import stepper
from esphome.components.tmc2209 import (
    CONF_ENN_PIN,
    CONF_INDEX_PIN,
    TMC2209_BASE_CONFIG_SCHEMA,
    register_tmc2209_base,
    validate_tmc2209_base,
)
from esphome.components.tmc2209.stepper import ControlMethod, TMC2209Stepper
from esphome.const import CONF_ID

AUTO_LOAD = ["tmc2209", "tmc2209_hub"]
DEPENDENCIES = ["uart"]

safe_ns = cg.esphome_ns.namespace("openreef_tmc2209")
SafeTMC2209Stepper = safe_ns.class_("SafeTMC2209Stepper", TMC2209Stepper)

# This Node 1 wrapper supports serial motion with INDEX feedback only. ENN is
# mandatory: a UART command cannot be an independent emergency motor cutoff.
CONFIG_SCHEMA = cv.All(
    TMC2209_BASE_CONFIG_SCHEMA.extend(stepper.STEPPER_SCHEMA).extend(
        {
            cv.GenerateID(): cv.declare_id(SafeTMC2209Stepper),
            cv.Required(CONF_ENN_PIN): pins.internal_gpio_output_pin_schema,
            cv.Required(CONF_INDEX_PIN): pins.internal_gpio_input_pin_schema,
        }
    ),
    validate_tmc2209_base,
)


async def to_code(config):
    var = cg.new_Pvariable(config[CONF_ID])
    await register_tmc2209_base(var, config)
    await stepper.register_stepper(var, config)
    cg.add(var.set_control_method(ControlMethod.SERIAL_CONTROL))
