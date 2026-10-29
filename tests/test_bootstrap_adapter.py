"""Focused tests for the configurator-owned gripper bootstrap boundary."""

import json
from pathlib import Path
from types import SimpleNamespace

import pytest

from configurator import ComponentView, Configurator, SelectionError
from gripper.bootstrap import bootstrap_gripper, validate_gripper_view
from gripper.config_adapter import ConfigValidationError, GripperConfigAdapter


def _view(data, root=None, name="gripper"):
    root = root or {"components": {name: data, "controller": _controller()}}
    return ComponentView(
        name, data.get("component_class", "gripper"), data, root, f"components.{name}", root["components"]
    )


def _controller():
    return {
        "control_library": "cpx_io",
        "control_system": "cpx_system",
        "control_bus": "cpx_e",
        "control_module": {"cpx_e": "CpxE"},
        "modules": [{"e8do": "CpxE8Do"}],
    }


def _factory_source(ip=None):
    controller = _controller()
    if ip is not None:
        controller["ip"] = ip
    return {
        "components": {
            "controller": controller,
            "gripper": {
                "control_signal_module": {"e8do": "CpxE8Do"},
                "control_signal_channels": {"grip": 1, "release": 0},
            },
        }
    }


def _component(**overrides):
    value = {
        "component_class": "gripper",
        "control_signal_module": {"e8do": "CpxE8Do"},
        "control_modules": {"controller": _controller()},
        "control_signal_channels": {"grip": 1, "release": 0},
    }
    value.update(overrides)
    return value


def test_selected_legacy_view_is_validated_without_file_adapter():
    validate_gripper_view(
        _view(
            {
                "control_signal_module": {"e8do": "CpxE8Do"},
                "control_signal_channels": {"grip": 1, "release": 0},
            }
        )
    )


def test_selected_spec_view_is_validated():
    view = _view(
        _component(component_spec_version="2.0"),
        {"spec_version": "3.0", "components": {"gripper": _component(component_spec_version="2.0")}},
    )
    validate_gripper_view(view)


def test_mapping_controller_modules_are_validated_in_insertion_order():
    modules = {"eep": "CpxEEp", "e16di": "CpxE16Di", "e8do": "CpxE8Do"}
    data = _component()
    data["control_modules"]["controller"]["modules"] = modules

    validate_gripper_view(_view(data))


@pytest.mark.parametrize(
    "change",
    [
        {"control_signal_channels": {"grip": 1, "release": 1}},
        {"control_signal_module": {"e8do": "CpxE8Do", "other": "CpxE8Do"}},
        {"sensor": {"control_signal_module": {}, "control_signal_channels": {"grip": 0, "release": 1}}},
    ],
)
def test_selected_view_rejects_unsafe_mappings_and_channels(change):
    data = _component()
    data.update(change)
    with pytest.raises(ConfigValidationError):
        validate_gripper_view(_view(data))


def test_ambiguous_gripper_selection_raises_without_building():
    source = {
        "spec_version": "3.0",
        "component_config": {
            "components": {
                "first": _component(component_spec_version="2.0"),
                "second": _component(component_spec_version="2.0"),
            }
        },
    }
    with pytest.raises(SelectionError, match="select one explicitly"):
        bootstrap_gripper(source)


def test_missing_or_unknown_gripper_selection_keeps_compatibility_errors():
    with pytest.raises(ConfigValidationError, match="No component with component_class='gripper' found"):
        bootstrap_gripper({"components": {"pump": {"component_type": "pump"}}})

    with pytest.raises(ConfigValidationError, match="Unknown gripper component: missing"):
        bootstrap_gripper({"components": {}}, component_name="missing")


@pytest.mark.parametrize(
    ("explicit", "environment", "configured", "expected"),
    [
        ("192.168.0.10", "192.168.0.11", "192.168.0.41", "192.168.0.10"),
        (None, "192.168.0.11", "192.168.0.41", "192.168.0.11"),
        (None, None, "192.168.0.41", "192.168.0.41"),
        (None, None, None, "192.168.0.2"),
    ],
)
def test_ip_precedence(monkeypatch, explicit, environment, configured, expected):
    class Output:
        name = "e8do"

        def write_channel(self, channel, value):
            pass

        def reset_channel(self, channel):
            pass

    class Controller:
        def __init__(self, **kwargs):
            self.ip_address = kwargs["ip_address"]
            self.modules = kwargs["modules"]
            self.shutdown_called = 0

        def shutdown(self):
            self.shutdown_called += 1

    def fake_import(path):
        if path.endswith(".cpx_e"):
            return SimpleNamespace(CpxE=Controller)
        return SimpleNamespace(CpxE8Do=Output)

    monkeypatch.setattr("configurator.kernel.import_module", fake_import)
    if environment is None:
        monkeypatch.delenv("GRIPPER_CPX_IP", raising=False)
    else:
        monkeypatch.setenv("GRIPPER_CPX_IP", environment)

    gripper = bootstrap_gripper(_factory_source(configured), ip_address=explicit)

    assert gripper._owned_control is not None
    assert gripper._owned_control.ip_address == expected
    gripper.close()


def test_named_selection_is_forwarded_to_bootstrap(monkeypatch):
    source = {"components": {"first": _component(), "second": _component()}}
    selected = type("Result", (), {"instance": type("Instance", (), {})()})()
    captured = {}

    def fake_bootstrap(cls, *args, **kwargs):
        captured.update(kwargs)
        return selected

    monkeypatch.setattr(Configurator, "bootstrap", classmethod(fake_bootstrap))

    assert bootstrap_gripper(source, component_name="first") is selected.instance
    assert captured["selector"] == {"type": "gripper", "require_single": True, "name": "first"}


def test_bootstrap_path_does_not_use_legacy_file_loading(monkeypatch, tmp_path):
    class Output:
        name = "e8do"

        def write_channel(self, channel, value):
            pass

        def reset_channel(self, channel):
            pass

    class Controller:
        def __init__(self, **kwargs):
            self.modules = kwargs["modules"]
            self.shutdown_called = 0

        def shutdown(self):
            self.shutdown_called += 1

    def fake_import(path):
        return SimpleNamespace(CpxE=Controller, CpxE8Do=Output)

    monkeypatch.setattr("configurator.kernel.import_module", fake_import)
    monkeypatch.setattr(GripperConfigAdapter, "_load_json_file", lambda _: pytest.fail("legacy loader used"))
    source = {
        "components": {
            "controller": {
                "control_library": "cpx_io",
                "control_system": "cpx_system",
                "control_bus": "cpx_e",
                "control_module": {"cpx_e": "CpxE"},
                "modules": [{"e8do": "CpxE8Do"}],
                "ip": "192.168.0.2",
            },
            "gripper": {
                "control_signal_channels": {"grip": 1, "release": 0},
                "control_signal_module": {"e8do": "CpxE8Do"},
            },
        }
    }
    path = Path(tmp_path) / "gripper.json"
    path.write_text(json.dumps(source))

    gripper = bootstrap_gripper(path)
    assert gripper.grip_channel == 1
    gripper.close()


def test_cpx_ap_library_declaration_resolves_under_cpx_io(monkeypatch):
    imported = []

    class Output:
        name = "io"

        def write_channel(self, channel, value):
            pass

        def reset_channel(self, channel):
            pass

    class Controller:
        def __init__(self, **kwargs):
            self.modules = kwargs["modules"]
            self.ip_address = kwargs["ip_address"]
            self.shutdown_called = 0

        def shutdown(self):
            self.shutdown_called += 1

    def fake_import(path):
        imported.append(path)
        if path.endswith(".io"):
            return SimpleNamespace(CpxApAOutput=Output)
        if path.endswith(".ap_a"):
            return SimpleNamespace(CpxApAController=Controller)
        pytest.fail(f"Unexpected import path: {path}")

    monkeypatch.setattr("configurator.kernel.import_module", fake_import)
    source = {
        "spec_version": "3.0",
        "component_config": {
            "components": {
                "gripper_cpx_ap_a": {
                    "component_spec_version": "2.0",
                    "component_class": "gripper",
                    "control_signal_module": {"io": "CpxApAOutput"},
                    "control_signal_channels": {"grip": 1, "release": 0},
                    "control_modules": {
                        "controller": {
                            "control_library": "cpx_ap",
                            "control_system": "cpx_system",
                            "control_bus": "cpx_ap_a",
                            "control_module": {"ap_a": "CpxApAController"},
                            "modules": [{"io": "CpxApAOutput"}],
                            "ip": "192.168.0.41",
                        }
                    },
                }
            }
        },
    }

    gripper = bootstrap_gripper(source)

    assert gripper._owned_control is not None
    assert imported == [
        "cpx_io.cpx_system.cpx_ap_a.io",
        "cpx_io.cpx_system.cpx_ap_a.ap_a",
    ]
    control = gripper._owned_control
    assert control.ip_address == "192.168.0.41"
    assert gripper.control is gripper._owned_control.modules[0]
    gripper.close()
    assert gripper._owned_control is None
    assert control.shutdown_called == 1


def test_new_part_resolves_dynamically_without_per_class_allow_list(monkeypatch):
    """A part absent from a curated class list resolves under the approved package root."""
    from configurator import NamespaceResolver

    class CpxApA:
        pass

    captured = {}

    def fake_import(path):
        captured["path"] = path
        return SimpleNamespace(CpxApA=CpxApA)

    monkeypatch.setattr("configurator.kernel.import_module", fake_import)
    resolver = NamespaceResolver({"cpx_io"})

    assert resolver.resolve(("cpx_io", "cpx_system", "cpx_ap_a", "ap_a"), "CpxApA") is CpxApA
    assert captured["path"] == "cpx_io.cpx_system.cpx_ap_a.ap_a"


def test_resolver_refuses_unapproved_root():
    """The only hard gate is the top-level package root."""
    from configurator import NamespaceResolver, ResolutionError

    resolver = NamespaceResolver({"cpx_io"})
    with pytest.raises(ResolutionError, match="not an approved package"):
        resolver.resolve(("os", "path"), "sep")
