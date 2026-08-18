# SPDX-FileCopyrightText: 2026 Festo SE & Co. KG
# SPDX-License-Identifier: MIT

"""Basic CPX-E gripper demo.

Run only with a safe, connected gripper::

    GRIPPER_CPX_IP=192.168.0.41 python examples/gripper_demo.py

Output channels use ``grip=1`` and ``release=0``. Sensor inputs use
``grip=0`` and ``release=1`` on ``CpxE16Di``.
"""

import os
from importlib import import_module
from pathlib import Path

from gripper.config_adapter import load_config
from gripper.gripper import Gripper


CONFIG_PATH = Path(__file__).parents[1] / "src/gripper/data/gripper-config.json"


def main() -> None:
    """Load controller classes from config, then run one grip/release cycle."""
    ip_address = os.getenv("GRIPPER_CPX_IP", "192.168.0.41")
    config = load_config(CONFIG_PATH)
    controller = config["components"]["controller"]
    package = ".".join(
        (
            controller["control_library"],
            controller["control_system"],
            controller["control_bus"],
        )
    )

    controller_module_name, controller_class_name = next(iter(controller["control_module"].items()))
    controller_class = getattr(import_module(f"{package}.{controller_module_name}"), controller_class_name)
    modules = []
    for module_spec in controller["modules"]:
        module_name, module_class_name = next(iter(module_spec.items()))
        module_class = getattr(import_module(f"{package}.{module_name}"), module_class_name)
        modules.append(module_class())

    control = controller_class(ip_address=ip_address, modules=modules)
    gripper = Gripper(control, config)

    try:
        gripper.release()
        print(f"released: {gripper.get_status().get_position()}")
        gripper.grip()
        print(f"gripped: {gripper.get_status().get_position()}")
    finally:
        control.shutdown()


if __name__ == "__main__":
    main()
