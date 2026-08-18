# SPDX-FileCopyrightText: 2026 Festo SE & Co. KG
# SPDX-License-Identifier: MIT

"""Hardware tests for connected CPX-E gripper.

Run explicitly with ``python -m pytest tests/system_tests/ -m hardware -v``.
Set ``GRIPPER_CPX_IP`` and channel variables for bench-specific wiring.
"""

import pytest


pytestmark = pytest.mark.hardware


def test_grip_and_release(gripper):
    """Execute one release and grip cycle on connected hardware."""
    gripper.release()
    released = gripper.get_status()

    gripper.grip()
    gripped = gripper.get_status()

    assert released.get_position() in {"open", None}
    assert gripped.get_position() in {"closed", None}


def test_sensor_status_is_readable(gripper):
    """Read current CPX-E16DI sensor status without commanding motion."""
    status = gripper.get_status()

    assert status.get_gripping_state() in {"gripping", "released", "unknown", "fault"}