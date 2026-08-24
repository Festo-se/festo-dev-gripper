# SPDX-FileCopyrightText: 2026 Festo SE & Co. KG
# SPDX-License-Identifier: MIT

"""Basic CPX-E gripper demo.

Run only with a safe, connected gripper::

    GRIPPER_CPX_IP=192.168.0.2 python examples/gripper_demo.py

Output channels use ``grip=1`` and ``release=0``.
"""
# Sensor inputs use ``grip=0`` and ``release=1`` on ``CpxE16Di``.

import os
from pathlib import Path
from pprint import pprint
import logging

from gripper.gripper import Gripper

log_level = os.getenv("LOG_LEVEL", "DEBUG").upper()
logging.basicConfig(level=log_level)

logging.info("This will now print!")
logging.debug("This will only print if LOG_LEVEL=DEBUG")

CONFIG_PATH = Path(__file__).parents[1] / "src/gripper/data/gripper-config.json"
pprint(CONFIG_PATH)


def main() -> None:
    """Run safe release, grip, final-release cycle on configured hardware."""

    def report(label: str, gripper: Gripper) -> None:
        status = gripper.get_status()
        if status.code == 2:
            raise RuntimeError(f"Contradictory sensor status after {label}")
        print(f"{label}: {status.get_position()}")

    with Gripper.from_config(CONFIG_PATH, component_name="gripper_standalone") as gripper:
        gripper.release()
        report("released", gripper)
        gripper.grip()
        report("gripped", gripper)
        gripper.release()
        report("released", gripper)
        gripper.grip()
        report("gripped", gripper)
        gripper.release()
        report("released", gripper)
        gripper.grip()
        report("gripped", gripper)
        gripper.release()
        report("released", gripper)
        gripper.grip()
        report("gripped", gripper)
        gripper.release()
        report("released", gripper)
        gripper.grip()
        report("gripped", gripper)
        gripper.release()
        report("released", gripper)
        gripper.grip()
        report("gripped", gripper)
        gripper.release()
        report("released", gripper)


if __name__ == "__main__":
    main()
