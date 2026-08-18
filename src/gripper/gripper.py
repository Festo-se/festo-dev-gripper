# SPDX-FileCopyrightText: 2026 Festo SE & Co. KG
# SPDX-License-Identifier: MIT

"""Dependency-injected digital I/O control and status models for grippers."""

import time


class GripperSensor:
    """Read open and closed gripper switches from a digital-input module.

    ``channels["grip"]`` identifies closed/gripping input. ``channels["release"]``
    identifies open/released input. Sensor values are normalized to ``bool``;
    hardware-specific input classes stay behind ``module``.
    """

    def __init__(self, module, channels: dict):
        """Create sensor reader.

        Args:
            module: Digital-input module exposing ``read_channel(channel)``.
            channels: Mapping containing integer ``grip`` and ``release`` channels.
        """
        self.module = module
        self.grip_channel = channels["grip"]
        self.release_channel = channels["release"]

    def read(self) -> dict[str, bool]:
        """Read both configured inputs and map them to semantic states.

        Returns:
            Dictionary with ``grip`` and ``release`` boolean readings.

        Raises:
            Exception: Propagates hardware read failures unchanged.
        """
        return {
            "grip": bool(self.module.read_channel(self.grip_channel)),
            "release": bool(self.module.read_channel(self.release_channel)),
        }


class GripperStatus:
    """Snapshot of gripper position, motion, and fault state.

    ``code`` uses ``0`` for a valid state, ``1`` for indeterminate inputs,
    and ``2`` for contradictory sensor inputs. State strings remain available
    through accessors for callers that do not want to interpret numeric codes.
    """

    def __init__(self, code, gripping_state="unknown", movement_state="unknown", position=None):
        """Create status snapshot.

        Args:
            code: Numeric status code: 0 valid, 1 unknown, 2 fault.
            gripping_state: Semantic gripping state.
            movement_state: Semantic movement state.
            position: ``"gripped"``, ``"released"``, ``"contradictory"``, or ``None``.
        """
        self.code = code
        self.gripping_state = gripping_state
        self.movement_state = movement_state
        self.position = position

    def get_gripping_state(self):
        """Return semantic gripping state."""
        return self.gripping_state

    def get_movement_state(self):
        """Return semantic movement state."""
        return self.movement_state

    def get_position(self):
        """Return semantic position, or ``None`` when unavailable."""
        return self.position


class Gripper:
    """Gripper control class for CPX-based gripping modules.

    ``control`` is dependency-injected. It must expose ``write_channel`` and
    ``reset_channel``. Sensor-enabled controls must also expose either
    ``sensor_module`` or a ``modules`` iterable containing configured
    ``sensors via digital input``. Constructor does not create or close hardware resources.
    """

    """
    TODO: Add a config-only factory that dynamically imports the configured
    controller and module classes, constructs the control assembly, and then
    delegates to this constructor. Keep dependency injection available for
    tests and applications that own hardware lifecycle.
    """

    def __init__(self, control, config: dict):
        """Initialize gripper from normalized legacy-compatible config.

        Args:
            control: Injected CPX control assembly.
            config: Mapping with ``components.gripper`` and
                ``control_signal_channels``. Optional ``sensor`` config maps
                CPX-E16DI channels 0 and 1 to gripping and release states.

        Raises:
            KeyError: Required configuration field is absent.
            ValueError: Configured sensor module cannot be found.
        """
        self.control = control
        self.config = config["components"]["gripper"]
        self.channels_config = self.config["control_signal_channels"]
        self.grip_channel = self.channels_config["grip"]
        self.release_channel = self.channels_config["release"]
        self.sensor = self._build_sensor(control)

        # TODO: Support ``Gripper.from_config(config_path)`` using
        # ``control_library``, ``control_system``, ``control_bus``,
        # ``control_module``, and ``modules``. Do not hard-code CPX-E classes.

        # TODO: Resolve controller configuration before construction, including
        # configured IP address and environment-variable override policy.

        # TODO: Define ownership and cleanup for controls created by the factory;
        # injected controls must remain caller-owned.

    def _wait(self, timeout: int):
        """Wait ``timeout`` polling cycles.

        Each cycle sleeps for 10 ms. Existing synchronous timing behavior is
        preserved; argument is cycle count, not elapsed milliseconds.
        """
        for _ in range(timeout):
            # self.control.read_channel(self.channel_numbers[0]) # why?
            time.sleep(0.01)

    def _set_gripper(self, to_open: bool):
        """Pulse mutually exclusive outputs to open or close gripper.

        Args:
            to_open: ``True`` energizes release output; ``False`` energizes grip.

        Both outputs are reset in ``finally`` after command starts, including
        hardware write, wait, or reset failures.
        """
        self._wait(15)
        try:
            self.control.write_channel(self.release_channel, to_open)
            self.control.write_channel(self.grip_channel, not to_open)
            self._wait(100)
        finally:
            self.control.reset_channel(self.release_channel)
            self.control.reset_channel(self.grip_channel)

    def _build_sensor(self, control):
        """Resolve configured digital-input module and create sensor reader.

        Args:
            control: Injected control assembly containing module instances.

        Returns:
            ``GripperSensor`` when sensor config exists; otherwise ``None``.

        Raises:
            ValueError: Sensor module mapping is empty or module is unavailable.
        """
        sensor_config = self.config.get("sensor")
        if not sensor_config:
            return None

        module = getattr(control, "sensor_module", None)
        module_spec = sensor_config["control_signal_module"]
        if len(module_spec) != 1:
            raise ValueError("Sensor control_signal_module must contain exactly one module")
        module_name, module_class = next(iter(module_spec.items()))
        for candidate in getattr(control, "modules", []):
            if type(candidate).__name__ == module_class or getattr(candidate, "name", None) == module_name:
                module = candidate
                break
        if module is None:
            raise ValueError(f"Configured sensor module not found: {module_class}")
        return GripperSensor(module, sensor_config["control_signal_channels"])

    def check_sensor_status(self) -> GripperStatus:
        """Read position inputs and classify current gripper state.

        Returns:
            Status with ``gripping``/``released`` when one input is active,
            ``moving`` when neither input is active, or ``fault`` when both
            inputs are active. Sensorless grippers return unknown status.
        """
        if self.sensor is None:
            return GripperStatus(0)

        readings = self.sensor.read()
        if readings["grip"] and readings["release"]:
            return GripperStatus(2, "fault", "unknown", "contradictory")
        if readings["grip"]:
            return GripperStatus(0, "gripping", "stopped", "closed")
        if readings["release"]:
            return GripperStatus(0, "released", "stopped", "open")
        return GripperStatus(1, "unknown", "moving", None)

    def grip(self):
        """Command gripper to enter grip state using configured grip output pulse."""
        self._set_gripper(to_open=False)
        self._wait(1)

    def release(self):
        """Release gripper from "grip" state using configured release output pulse."""
        self._set_gripper(to_open=True)
        self._wait(1)

    def get_status(self) -> GripperStatus:
        """Return current status from configured position sensors."""
        return self.check_sensor_status()
