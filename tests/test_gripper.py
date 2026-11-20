# SPDX-FileCopyrightText: 2026 Festo SE & Co. KG
# SPDX-License-Identifier: MIT

"""Unit tests for dependency-injected gripper control."""

import json
from types import SimpleNamespace
from unittest.mock import Mock
from pathlib import Path

import pytest

from configurator import SourceError
from gripper.gripper import Gripper, GripperSensor, GripperStatus
from gripper.config_adapter import ConfigValidationError, GripperConfigAdapter


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


def test_close_does_not_close_injected_control(control, config):
    gripper = Gripper(control, config)

    gripper.close()

    control.shutdown.assert_not_called()


def test_injected_control_accepts_normalized_component_config(control, config):
    """Direct injection normalizes the configurator's component_config wrapper."""
    wrapped = {"component_config": config}

    gripper = Gripper(control, json.dumps(wrapped))

    assert gripper.grip_channel == 1
    assert gripper.release_channel == 0


def test_injected_control_loads_config_from_path(control, config, tmp_path):
    """Direct injection uses configurator loading for JSON file sources."""
    source = tmp_path / "gripper.json"
    source.write_text(json.dumps(config), encoding="utf-8")

    gripper = Gripper(control, source)

    assert gripper.grip_channel == 1
    assert gripper.release_channel == 0


def test_injected_control_selects_requested_component(control, config):
    """Direct injection uses the explicit component name, not a fallback entry."""
    config["components"]["secondary"] = {
        "control_signal_channels": {"grip": 3, "release": 2},
    }

    gripper = Gripper(control, config, component_name="secondary")

    assert gripper.grip_channel == 3
    assert gripper.release_channel == 2


def test_injected_control_rejects_malformed_components_before_key_access(control):
    """Malformed component entries fail during configurator-source validation."""
    source = {"components": {"gripper": None}}

    with pytest.raises(SourceError, match="Each component must have"):
        Gripper(control, source)


def test_injected_control_rejects_malformed_sensor_before_nested_access(control, config):
    """Malformed nested sensor data is validated before sensor construction."""
    config["components"]["gripper"]["sensor"] = ["not", "a", "mapping"]

    with pytest.raises(ConfigValidationError, match="sensor must be a mapping"):
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
    construction_order = []
    import_paths = []

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
            self.ip_address = kwargs["ip_address"]

    class Eep:
        def __init__(self):
            construction_order.append("eep")
            self.name = "eep"

    class E4Iol:
        def __init__(self):
            construction_order.append("e4iol")
            self.name = "e4iol"

    output = Output()

    def fake_import(name):
        import_paths.append(name)
        module = Mock()
        if name.endswith(".cpx_e"):
            module.CpxE = Controller
        elif name.endswith(".e16di"):
            module.CpxE16Di = lambda: construction_order.append("e16di") or input_module
        elif name.endswith(".e8do"):
            module.CpxE8Do = lambda: construction_order.append("e8do") or output
        elif name.endswith(".eep"):
            module.CpxEEp = Eep
        elif name.endswith(".e4iol"):
            module.CpxE4Iol = E4Iol
        return module

    monkeypatch.setattr("configurator.kernel.import_module", fake_import)
    config_path = tmp_path / "gripper.json"
    config_path.write_text(json.dumps(config))

    gripper = Gripper.from_config(config_path, component_name="gripper_standalone")
    controller = gripper._owned_control
    status = gripper.get_status()

    assert status.get_position() == "open"
    assert gripper.sensor.module is input_module
    assert construction_order == ["eep", "e16di", "e8do", "e4iol"]
    assert [module.name for module in controller.modules] == ["eep", "e16di", "e8do", "e4iol"]
    assert controller.ip_address == "192.168.0.2"
    assert all(path.startswith("cpx_io.") for path in import_paths)
    with gripper:
        pass
    gripper.close()
    controller.shutdown.assert_called_once()


def test_config_backed_constructor_uses_runtime_and_closes_owned_control(monkeypatch):
    class Output:
        name = "e8do"

        def write_channel(self, channel, value):
            pass

        def reset_channel(self, channel):
            pass

    class Controller:
        def __init__(self, **kwargs):
            self.modules = kwargs["modules"]
            self.ip_address = kwargs["ip_address"]
            self.shutdown = Mock()

    def fake_import(path):
        return SimpleNamespace(CpxE=Controller, CpxE8Do=Output)

    monkeypatch.setattr("configurator.kernel.import_module", fake_import)
    source = {
        "components": {
            "controller": {
                "control_library": "cpx_io",
                "control_system": "cpx_system",
                "control_bus": "cpx_e",
                "control_module": {"cpx_e": "CpxE"},
                "modules": [{"e8do": "CpxE8Do"}],
            },
            "gripper": {
                "control_signal_module": {"e8do": "CpxE8Do"},
                "control_signal_channels": {"grip": 1, "release": 0},
            },
        }
    }

    gripper = Gripper(config=source, component_name="gripper", ip_address="192.168.0.10")

    assert gripper.registry is not None
    assert gripper._registry_owner is True
    assert gripper._owned_control.ip_address == "192.168.0.10"
    control = gripper._owned_control
    gripper.close()
    assert gripper.registry.closed is True
    control.shutdown.assert_called_once_with()


def test_factory_partial_failure_closes_control_once(monkeypatch, tmp_path):
    from configurator import BuilderError
    from gripper.gripper import GripperFactoryError

    controls = []

    class Controller:
        def __init__(self, **kwargs):
            self.modules = kwargs["modules"]
            self.shutdown = Mock()
            controls.append(self)

    class Input:
        name = "e16di"

    monkeypatch.setattr(
        "configurator.kernel.import_module",
        lambda _: SimpleNamespace(CpxE=Controller, CpxE16Di=Input),
    )
    source = {
        "components": {
            "controller": {
                "control_library": "cpx_io",
                "control_system": "cpx_system",
                "control_bus": "cpx_e",
                "control_module": {"cpx_e": "CpxE"},
                "modules": [{"e16di": "CpxE16Di"}],
            },
            "gripper": {
                "control_signal_channels": {"grip": 1, "release": 0},
                "control_signal_module": {"missing": "MissingOutput"},
            },
        }
    }
    config_path = tmp_path / "partial.json"
    config_path.write_text(json.dumps(source))

    with pytest.raises(GripperFactoryError) as error:
        Gripper.from_config(config_path)

    assert isinstance(error.value.__cause__, BuilderError)
    assert "Configured output module not found" in str(error.value.__cause__.cause)
    assert len(controls) == 1
    controls[0].shutdown.assert_called_once()


def test_from_config_warns_with_migration_target(monkeypatch):
    from gripper.gripper import Gripper

    runtime = Mock()
    instance = object()
    runtime.resolve.return_value = instance
    monkeypatch.setattr("gripper.gripper.RuntimeRegistry", lambda source, options=None: runtime)

    with pytest.warns(DeprecationWarning, match=r"0\.7\.0.*Configurator\.bootstrap"):
        assert Gripper.from_config({"components": {}}, component_name="gripper") is instance


def test_load_config_warns_with_migration_target(tmp_path):
    from gripper.config_adapter import load_config

    config_path = tmp_path / "legacy-config.json"
    config_path.write_text(
        json.dumps(
            {
                "components": {
                    "controller": {
                        "control_library": "cpx_io",
                        "control_system": "cpx_system",
                        "control_bus": "cpx_e",
                        "control_module": {"cpx_e": "CpxE"},
                        "modules": [{"e8do": "CpxE8Do"}],
                    },
                    "gripper": {"control_signal_channels": {"grip": 1, "release": 0}},
                }
            }
        ),
        encoding="utf-8",
    )

    with pytest.warns(DeprecationWarning, match=r"0\.7\.0.*GripperConfigAdapter"):
        load_config(config_path)


def test_duplicate_output_channels_are_rejected(control, config):
    """Reject unsafe configuration that aliases grip and release outputs."""
    config["components"]["gripper"]["control_signal_channels"] = {"grip": 1, "release": 1}

    with pytest.raises(ValueError, match="must be distinct"):
        Gripper(control, config)
