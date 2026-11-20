# SPDX-FileCopyrightText: 2026 Festo SE & Co. KG
# SPDX-License-Identifier: MIT

"""Configurator registration and bootstrap adapter for digital grippers."""

import logging
import os
from collections.abc import Mapping
from typing import Any

from configurator import (
    ComponentView,
    Configurator,
    NamespaceResolver,
    Registration,
    Registry,
    RuntimeRegistry,
    SelectionError,
)

from gripper.config_adapter import ConfigValidationError
from gripper.gripper import Gripper, GripperFactoryError

logger = logging.getLogger(__name__)

_DEFAULT_IP = "192.168.0.2"

# The only safety gate on dynamic import is the top-level package root, not a
# curated class list: any module/class under an approved root may be named in
# configuration without code changes, so new parts (e.g. CPX-AP-A) need no
# library blessing. Roots are overridable so an application can widen them.
_ALLOWED_ROOTS = frozenset({"cpx_io"})
# TODO: This seems silly if we're to have fully flexible module support, consider dynamic discovery instead


def _single_mapping(value: Any, field: str) -> tuple[str, Any]:
    if not isinstance(value, Mapping) or len(value) != 1:
        raise ConfigValidationError(f"{field} must contain exactly one item")
    name, selected = next(iter(value.items()))
    if not isinstance(name, str) or not name:
        raise ConfigValidationError(f"{field} must use a non-empty string name")
    if not isinstance(selected, str) or not selected:
        raise ConfigValidationError(f"{field} must map to a non-empty class name")
    return name, selected


def _validate_channels(channels: Any, field: str = "control_signal_channels") -> None:
    if not isinstance(channels, Mapping):
        raise ConfigValidationError(f"{field} must be a dict")
    if "grip" not in channels or "release" not in channels:
        raise ConfigValidationError(f"{field} must have 'grip' and 'release' keys")
    grip, release = channels["grip"], channels["release"]
    if type(grip) is not int or type(release) is not int:
        raise ConfigValidationError("grip/release channels must be integers")
    if grip == release:
        raise ConfigValidationError("grip and release channels must be distinct")


def _validate_mappings(component: Mapping[str, Any]) -> None:
    output = component.get("control_signal_module")
    if output is not None:
        _single_mapping(output, "control_signal_module")

    _validate_sensor_mapping(component.get("sensor"))
    _validate_controller_mapping(component.get("control_modules"))


def _validate_sensor_mapping(sensor: Any) -> None:
    if sensor is None:
        return
    if not isinstance(sensor, Mapping):
        raise ConfigValidationError("sensor must be a mapping")
    _single_mapping(sensor.get("control_signal_module"), "sensor control_signal_module")
    _validate_channels(sensor.get("control_signal_channels"), "sensor control_signal_channels")


def _validate_controller_mapping(control_modules: Any) -> None:
    if control_modules is None:
        return
    if not isinstance(control_modules, Mapping) or not isinstance(control_modules.get("controller"), Mapping):
        raise ConfigValidationError("Gripper control_modules.controller must be a mapping")
    controller = control_modules["controller"]

    for field in ("control_library", "control_system", "control_bus"):
        if field in controller and not isinstance(controller[field], str):
            raise ConfigValidationError(f"controller.{field} must be a string")
    _validate_controller_ip(controller)
    for field in ("control_module", "controller"):
        if field in controller:
            _single_mapping(controller[field], f"controller.{field}")
    for module in _controller_module_specs(controller.get("modules", [])):
        _single_mapping(module, "controller.modules item")


def _controller_module_specs(value: Any) -> list[Mapping[str, Any]]:
    """Normalize legacy ordered module mappings and list declarations."""
    if isinstance(value, Mapping):
        return [{name: selected} for name, selected in value.items()]
    if isinstance(value, list):
        return value
    raise ConfigValidationError("controller.modules must be a list or mapping")


def _validate_controller_ip(controller: Mapping[str, Any]) -> None:
    if "ip" not in controller:
        return
    address = controller["ip"]
    if not isinstance(address, str):
        raise ConfigValidationError("controller.ip must be a string")
    if not address.strip():
        raise ConfigValidationError("controller.ip must be a non-empty string")


def validate_gripper_view(view: ComponentView, **_: Any) -> None:
    """Validate legacy or Spec 3.0 data after configurator selection."""
    data = view.data
    version = data.get("component_spec_version", view.root.get("spec_version"))
    if view.root.get("spec_version") == "3.0" and version != "2.0":
        raise ConfigValidationError(f"Unsupported component_spec_version: {version}. Expected 2.0")
    _validate_channels(data.get("control_signal_channels"))
    _validate_mappings(data)
    _single_mapping(data.get("control_signal_module"), "control_signal_module")
    controller = _controller_data(view)
    _validate_controller_mapping({"controller": controller})
    _controller_base(controller)
    _single_mapping(controller.get("control_module"), "control_module")


def _controller_base(controller: Mapping[str, Any]) -> tuple[str, str]:
    library = controller.get("control_library")
    system = controller.get("control_system")
    bus = controller.get("control_bus")
    if not isinstance(library, str) or not library:
        raise ConfigValidationError("controller.control_library must be a non-empty string")
    if not isinstance(system, str) or not system:
        raise ConfigValidationError("controller.control_system must be a non-empty string")
    if not isinstance(bus, str) or not bus:
        raise ConfigValidationError("controller.control_bus must be a non-empty string")
    return system, bus


def _controller_data(view: ComponentView) -> dict[str, Any]:
    control_modules = view.get("control_modules")
    if isinstance(control_modules, Mapping):
        controller = control_modules.get("controller")
        if isinstance(controller, Mapping):
            return dict(controller)
    components = view.root.get("components")
    if isinstance(components, Mapping) and isinstance(components.get("controller"), Mapping):
        return dict(components["controller"])
    raise ConfigValidationError("Gripper controller configuration is missing")


def _resolve_ip_address(controller: Mapping[str, Any], options: Mapping[str, Any]) -> str:
    """Apply explicit argument, environment, config, then canonical default precedence."""
    explicit = options.get("ip_address")
    if explicit is not None:
        if not isinstance(explicit, str) or not explicit.strip():
            raise ConfigValidationError("ip_address must be a non-empty string")
        return explicit

    environment = os.getenv("GRIPPER_CPX_IP")
    if environment and environment.strip():
        return environment

    configured = controller.get("ip")
    if configured is not None:
        if not isinstance(configured, str) or not configured.strip():
            raise ConfigValidationError("controller.ip must be a non-empty string")
        return configured

    return _DEFAULT_IP


def _selected_component_config(view: ComponentView) -> dict[str, Any]:
    return {"components": {view.name: dict(view.data)}}


def _select_output(control: Any, component: Mapping[str, Any]):
    output_name, output_class = _single_mapping(component.get("control_signal_module", {}), "control_signal_module")
    output = next(
        (
            module
            for module in getattr(control, "modules", [])
            if type(module).__name__ == output_class or getattr(module, "name", None) == output_name
        ),
        None,
    )
    if output is None:
        raise GripperFactoryError(f"Configured output module not found: {output_class}")
    return output


def build_gripper_view(
    view: ComponentView,
    *,
    options: Mapping[str, Any] | None = None,
    runtime: RuntimeRegistry | None = None,
    **_: Any,
) -> Gripper:
    """Build a gripper from a selected, validated configurator view."""
    options = dict(options or {})
    controller = _controller_data(view)
    base = _controller_base(controller)
    address = _resolve_ip_address(controller, options)
    module_resolver = NamespaceResolver(_ALLOWED_ROOTS)
    control = None
    try:
        modules = []
        for module_spec in _controller_module_specs(controller.get("modules", [])):
            submodule, class_name = _single_mapping(module_spec, "controller.modules item")
            modules.append(module_resolver.resolve(("cpx_io", *base, submodule), class_name)())
        controller_submodule, controller_class = _single_mapping(controller.get("control_module"), "control_module")
        controller_type = module_resolver.resolve(("cpx_io", *base, controller_submodule), controller_class)
        control = controller_type(ip_address=address, modules=modules)
        output = _select_output(control, view.data)
        result = Gripper(output, _selected_component_config(view), component_name=view.name, sensor_control=control)
        result._owned_control = control
        if runtime is not None:
            result.registry = runtime
            result._runtime_registry = runtime
        return result
    except Exception:
        if control is not None and hasattr(control, "shutdown"):
            try:
                control.shutdown()
            except Exception:
                logger.debug("Partial gripper cleanup failed", exc_info=True)
        raise


def _cleanup_gripper(instance: Gripper) -> None:
    instance._close_owned_control()


def gripper_registration() -> Registration:
    """Return the explicit consumer-owned gripper registration."""
    return Registration(
        name="gripper",
        component_type="gripper",
        # The kernel's version field is optional in legacy configurations; the
        # domain validator handles both legacy and Spec 3.0 compatibility.
        schema_versions=None,
        validator=validate_gripper_view,
        builder=build_gripper_view,
        cleanup=_cleanup_gripper,
    )


def bootstrap_gripper(source, component_name: str | None = None, ip_address: str | None = None) -> Gripper:
    """Load, normalize, select, validate, and build one gripper through the kernel."""
    selector = {"type": "gripper", "require_single": True}
    if component_name is not None:
        selector["name"] = component_name
    try:
        result = Configurator.bootstrap(
            source,
            selector=selector,
            registry=Registry.compose(gripper_registration()),
            options={"ip_address": ip_address, "legacy_component_types": {"gripper": "gripper"}},
        )
    except SelectionError as exc:
        if exc.code not in {"UNKNOWN_COMPONENT", "NO_COMPONENT_MATCH"}:
            raise
        if component_name is None:
            raise ConfigValidationError("No component with component_class='gripper' found") from exc
        raise ConfigValidationError(f"Unknown gripper component: {component_name}") from exc
    instance = result.instance
    instance._bootstrap_result = result
    return instance


__all__ = [
    "bootstrap_gripper",
    "build_gripper_view",
    "gripper_registration",
    "validate_gripper_view",
]
