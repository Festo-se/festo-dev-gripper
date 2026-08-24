# SPDX-FileCopyrightText: 2026 Festo SE & Co. KG
# SPDX-License-Identifier: MIT

"""Unit tests for dependency-injected gripper control."""

from types import SimpleNamespace
from unittest.mock import Mock
from pathlib import Path

import pytest

from gripper.gripper import Gripper, GripperSensor, GripperStatus
from gripper.config_adapter import GripperConfigAdapter


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


def test_sensorless_status_is_unknown(control, config):
    """Sensorless gripper reports unknown state without hardware reads."""
    status = Gripper(control, config).get_status()

    assert (status.code, status.get_gripping_state(), status.get_movement_state(), status.get_position()) == (
        0,
        "unknown",
        "unknown",
        None,
    )


@pytest.mark.parametrize(
    ("values", "expected"),
    [
        ([True, False], (0, "gripping", "stopped", "closed")),
        ([False, True], (0, "released", "stopped", "open")),
        ([False, False], (1, "unknown", "moving", None)),
        ([True, True], (2, "fault", "unknown", "contradictory")),
    ],
)
def test_sensor_status_classifies_all_input_states(values, expected, config):
    """Sensor status classification covers valid, moving, and fault inputs."""
    sensor_module = Mock(name="e16di")
    sensor_module.name = "e16di"
    sensor_module.read_channel.side_effect = values
    config["components"]["gripper"]["sensor"] = {
        "control_signal_module": {"e16di": "CpxE16Di"},
        "control_signal_channels": {"grip": 0, "release": 1},
    }

    status = Gripper(SimpleNamespace(modules=[sensor_module]), config).get_status()

    assert (status.code, status.get_gripping_state(), status.get_movement_state(), status.get_position()) == expected


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


def test_status_accessors_return_constructor_values():
    """Status accessors expose values supplied during construction."""
    status = GripperStatus(7, "custom-grip", "custom-motion", "custom-position")

    assert status.get_gripping_state() == "custom-grip"
    assert status.get_movement_state() == "custom-motion"
    assert status.get_position() == "custom-position"


def test_multiple_sensor_modules_are_rejected(control, config):
    """Sensor config must select exactly one module mapping."""
    config["components"]["gripper"]["sensor"] = {
        "control_signal_module": {"e16di": "CpxE16Di", "other": "Other"},
        "control_signal_channels": {"grip": 0, "release": 1},
    }

    with pytest.raises(ValueError, match="exactly one module"):
        Gripper(control, config)


# def test_status_accessors_return_constructor_values():
#     """Status accessors expose values supplied during construction."""
#     status = GripperStatus(7, "custom-grip", "custom-motion", "custom-position")
# 
#     assert status.get_gripping_state() == "custom-grip"
#     assert status.get_movement_state() == "custom-motion"
#     assert status.get_position() == "custom-position"


def test_current_spec_config_selects_standalone_gripper(monkeypatch):
    """Current Spec 3.0 fixture translates into runnable gripper config."""
    monkeypatch.setattr("gripper.gripper.time.sleep", Mock())
    path = Path(__file__).parents[1] / "src/gripper/data/gripper-config.json"
    config = GripperConfigAdapter(path, component_name="gripper_standalone").get_gripper_config()
    control = Mock()
    control.modules = []

    gripper = Gripper(control, config)

    assert gripper.grip_channel == 1
    assert gripper.release_channel == 0


def test_factory_routes_sensor_reads_to_configured_input_module(monkeypatch, tmp_path):
    """Factory-created gripper reads status from configured E16DI module."""
    import json

    source = Path(__file__).parents[1] / "src/gripper/data/gripper-config.json"
    config = json.loads(source.read_text())
    input_module = Mock()
    input_module.name = "e16di"
    input_module.read_channel.side_effect = [False, True]

    class Output:
        name = "e8do"

        def write_channel(self, channel, value):
            pass

        def reset_channel(self, channel):
            pass

    class Controller:
        def __init__(self, **kwargs):
            self.modules = kwargs["modules"]
            self.shutdown = Mock()

    class Module:
        def __init__(self):
            self.name = "module"

    output = Output()

    def fake_import(name):
        module = Mock()
        if name.endswith(".cpx_e"):
            module.CpxE = Controller
        elif name.endswith(".e16di"):
            module.CpxE16Di = lambda: input_module
        elif name.endswith(".e8do"):
            module.CpxE8Do = lambda: output
        elif name.endswith(".eep"):
            module.CpxEEp = Module
        elif name.endswith(".e4iol"):
            module.CpxE4Iol = Module
        return module

    monkeypatch.setattr("gripper.gripper.import_module", fake_import)
    config_path = tmp_path / "gripper.json"
    config_path.write_text(json.dumps(config))

    gripper = Gripper.from_config(config_path, component_name="gripper_standalone")
    controller = gripper._owned_control
    status = gripper.get_status()

    assert status.get_position() == "open"
    assert gripper.sensor.module is input_module
    gripper.close()
    controller.shutdown.assert_called_once()


def test_duplicate_output_channels_are_rejected(control, config):
    """Reject unsafe configuration that aliases grip and release outputs."""
    config["components"]["gripper"]["control_signal_channels"] = {"grip": 1, "release": 1}

    with pytest.raises(ValueError, match="must be distinct"):
        Gripper(control, config)
