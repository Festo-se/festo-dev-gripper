# SPDX-FileCopyrightText: 2026 Festo SE & Co. KG
# SPDX-License-Identifier: MIT

"""Unit tests for dependency-injected gripper control."""

from types import SimpleNamespace
from unittest.mock import Mock

import pytest

from gripper.gripper import Gripper, GripperSensor, GripperStatus


@pytest.fixture
def config():
    """Return minimal output-channel configuration."""
    return {
        "components": {
            "gripper": {
                "control_signal_channels": {"grip": 1, "release": 0},
            }
        }
    }


@pytest.fixture
def control():
    """Return fake control assembly recording output operations."""
    fake = Mock()
    fake.modules = []
    return fake


def test_grip_pulses_outputs_and_resets(monkeypatch, control, config):
    """Grip energizes grip output, leaves release low, then resets both."""
    monkeypatch.setattr("gripper.gripper.time.sleep", Mock())
    gripper = Gripper(control, config)

    gripper.grip()

    assert control.write_channel.call_args_list == [
        ((0, False),),
        ((1, True),),
    ]
    assert control.reset_channel.call_args_list == [
        ((0,),),
        ((1,),),
    ]


def test_release_pulses_outputs_and_resets(monkeypatch, control, config):
    """Release energizes release output, leaves grip low, then resets both."""
    monkeypatch.setattr("gripper.gripper.time.sleep", Mock())
    gripper = Gripper(control, config)

    gripper.release()

    assert control.write_channel.call_args_list == [
        ((0, True),),
        ((1, False),),
    ]
    assert control.reset_channel.call_args_list == [
        ((0,),),
        ((1,),),
    ]


def test_command_resets_outputs_when_write_fails(monkeypatch, control, config):
    """Output cleanup runs when hardware write raises."""
    monkeypatch.setattr("gripper.gripper.time.sleep", Mock())
    control.write_channel.side_effect = RuntimeError("write failed")
    gripper = Gripper(control, config)

    with pytest.raises(RuntimeError, match="write failed"):
        gripper.grip()

    assert control.reset_channel.call_args_list == [
        ((0,),),
        ((1,),),
    ]


def test_sensor_reads_configured_channels():
    """Sensor maps configured CPX-E16DI channels to semantic readings."""
    module = Mock()
    module.read_channel.side_effect = [True, False]
    sensor = GripperSensor(module, {"grip": 0, "release": 1})

    assert sensor.read() == {"grip": True, "release": False}
    assert module.read_channel.call_args_list == [((0,),), ((1,),)]


def test_sensorless_status_is_unknown(control, config):
    """Sensorless gripper reports unknown state without hardware reads."""
    status = Gripper(control, config).get_status()

    assert status.code == 0
    assert status.get_gripping_state() == "unknown"
    assert status.get_movement_state() == "unknown"
    assert status.get_position() is None


@pytest.mark.parametrize(
    ("values", "code", "gripping_state", "movement_state", "position"),
    [
        ([True, False], 0, "gripping", "stopped", "closed"),
        ([False, True], 0, "released", "stopped", "open"),
        ([False, False], 1, "unknown", "moving", None),
        ([True, True], 2, "fault", "unknown", "contradictory"),
    ],
)
def test_sensor_status_classifies_all_input_states(
    values, code, gripping_state, movement_state, position, config
):
    """Sensor status classification covers valid, moving, and fault inputs."""
    sensor_module = Mock()
    sensor_module.name = "e16di"
    sensor_module.read_channel.side_effect = values
    control = SimpleNamespace(modules=[sensor_module])
    config["components"]["gripper"]["sensor"] = {
        "control_signal_module": {"e16di": "CpxE16Di"},
        "control_signal_channels": {"grip": 0, "release": 1},
    }

    status = Gripper(control, config).get_status()

    assert (status.code, status.get_gripping_state(), status.get_movement_state(), status.get_position()) == (
        code,
        gripping_state,
        movement_state,
        position,
    )


def test_sensor_module_can_be_injected_directly(config):
    """Configured sensor_module takes precedence over module discovery."""
    sensor_module = Mock()
    sensor_module.read_channel.side_effect = [False, True]
    control = SimpleNamespace(sensor_module=sensor_module, modules=[])
    config["components"]["gripper"]["sensor"] = {
        "control_signal_module": {"e16di": "CpxE16Di"},
        "control_signal_channels": {"grip": 0, "release": 1},
    }

    status = Gripper(control, config).get_status()

    assert status.get_position() == "open"


def test_multiple_sensor_modules_are_rejected(control, config):
    """Sensor config must select exactly one module mapping."""
    config["components"]["gripper"]["sensor"] = {
        "control_signal_module": {"e16di": "CpxE16Di", "other": "Other"},
        "control_signal_channels": {"grip": 0, "release": 1},
    }

    with pytest.raises(ValueError, match="exactly one module"):
        Gripper(control, config)


def test_status_accessors_return_constructor_values():
    """Status accessors expose values supplied during construction."""
    status = GripperStatus(7, "custom-grip", "custom-motion", "custom-position")

    assert status.get_gripping_state() == "custom-grip"
    assert status.get_movement_state() == "custom-motion"
    assert status.get_position() == "custom-position"
