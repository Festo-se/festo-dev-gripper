# SPDX-FileCopyrightText: 2026 Festo SE & Co. KG
# SPDX-License-Identifier: MIT

"""Dependency-injected digital I/O control and status models for grippers."""

import logging
import os
from importlib import import_module
import time

from gripper.config_adapter import ConfigValidationError, GripperConfigAdapter

logger = logging.getLogger(__name__)


class GripperFactoryError(RuntimeError):
    """Raised when configured gripper construction fails."""


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
        logger.debug("GripperSensor initialization started")
        self.module = module
        self.grip_channel = channels["grip"]
        self.release_channel = channels["release"]
        logger.debug(
            "GripperSensor initialized: grip_channel=%s release_channel=%s",
            self.grip_channel,
            self.release_channel,
        )

    def read(self) -> dict[str, bool]:
        """Read both configured inputs and map them to semantic states.

        Returns:
            Dictionary with ``grip`` and ``release`` boolean readings.

        Raises:
            Exception: Propagates hardware read failures unchanged.
        """
        logger.debug("GripperSensor read started")
        try:
            readings = {
                "grip": bool(self.module.read_channel(self.grip_channel)),
                "release": bool(self.module.read_channel(self.release_channel)),
            }
        except Exception:
            logger.exception("GripperSensor read failed")
            raise
        logger.debug("Gripper sensor readings: %s", readings)
        return readings


#
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
        logger.debug(
            "GripperStatus created: code=%s gripping_state=%s movement_state=%s position=%s",
            code,
            gripping_state,
            movement_state,
            position,
        )
        self.code = code
        self.gripping_state = gripping_state
        self.movement_state = movement_state
        self.position = position

    def get_gripping_state(self):
        """Return semantic gripping state."""
        logger.debug("GripperStatus gripping state requested: state=%s", self.gripping_state)
        return self.gripping_state

    def get_movement_state(self):
        """Return semantic movement state."""
        logger.debug("GripperStatus movement state requested: state=%s", self.movement_state)
        return self.movement_state

    def get_position(self):
        """Return semantic position, or ``None`` when unavailable."""
        logger.debug("GripperStatus position requested: position=%s", self.position)
        return self.position


# class Gripper(ABC):
#     pass
#
#


# class DiscreteParallelGripper(Gripper):


class Gripper:
    """Gripper control class for CPX-based gripping modules.

    ``control`` is dependency-injected. It must expose ``write_channel`` and
    ``reset_channel``. Sensor-enabled controls must also expose either
    ``sensor_module`` or a ``modules`` iterable containing configured
    ``sensors via digital input``. Constructor does not create or close hardware resources.
    """

    def __init__(self, control, config: dict, component_name: str | None = None, sensor_control=None):
        """Initialize gripper from normalized legacy-compatible config.

        Args:
            control: Injected CPX control assembly.
            config: Mapping with ``components.gripper`` and
                ``control_signal_channels``. Optional ``sensor`` config maps
                CPX-E16DI channels 0 and 1 to gripping and release states.
            component_name: Name of gripper component in config, used when multiple grippers are present.
            sensor_control: Optional controller assembly used for sensor module lookup.

        Raises:
            KeyError: Required configuration field is absent.
            ValueError: Configured sensor module cannot be found.
        """
        logger.debug("Gripper initialization started")
        self.control = control
        components = config["components"]
        self.config = components.get("gripper", components.get(component_name))
        if self.config is None and control is None:
            raise KeyError("No instantiated control or valid config given.")
        self.channels_config = self.config["control_signal_channels"]
        self.grip_channel = self.channels_config["grip"]
        self.release_channel = self.channels_config["release"]
        if self.grip_channel == self.release_channel:
            raise ValueError("grip and release channels must be distinct")
        self._owned_control = None
        self._sensor_control = sensor_control
        self.sensor = self._build_sensor(self._sensor_control)
        logger.info(
            "Gripper initialized: grip_channel=%s release_channel=%s sensor=%s",
            self.grip_channel,
            self.release_channel,
            self.sensor is not None,
        )

    @classmethod
    def from_config(cls, source, component_name: str | None = None, ip_address: str | None = None):
        """Construct gripper and CPX modules from Spec 3.0 configuration."""
        ## TODO: AP module has autorecognition, so explicit IOs are not clear except from some kind of info or other config. Need this to bootstrap and understand system topology of actuators, sensors, etc.
        # TODO: COnfig options: AP still positional in terms of IO modules, this is how the config shuold be structured, avoid hardcoding indices for controls
        # TODO: Map :  cpx.module[index].set_channel(other index) -> human understandable methods/verbs

        adapter = GripperConfigAdapter(source, component_name=component_name)
        config = adapter.get_gripper_config()
        controller = config["components"]["controller"]
        package = ".".join((controller["control_library"], controller["control_system"], controller["control_bus"]))
        selected = config["components"]["gripper"]
        try:
            module_specs = controller["modules"]
            modules = [cls._instantiate_module(package, spec) for spec in module_specs]
            controller_spec = controller["control_module"]
            controller_module, controller_class = cls._single_mapping(controller_spec, "control_module")
            controller_type = getattr(import_module(f"{package}.{controller_module}"), controller_class)
            address = ip_address or os.getenv("GRIPPER_CPX_IP") or controller.get("ip", "192.168.0.2")
            base = controller_type(ip_address=address, modules=modules)
            output_name, output_class = cls._single_mapping(
                selected.get("control_signal_module", {}), "control_signal_module"
            )
            output = next(
                (
                    module
                    for module in base.modules
                    if type(module).__name__ == output_class or getattr(module, "name", None) == output_name
                ),
                None,
            )
            if output is None:
                raise GripperFactoryError(f"Configured output module not found: {output_class}")
            result = cls(output, config, component_name=component_name, sensor_control=base)
            result._owned_control = base
            return result
        except Exception as exc:
            if "base" in locals() and hasattr(base, "shutdown"):
                base.shutdown()
            if isinstance(exc, (ConfigValidationError, GripperFactoryError, ValueError, KeyError)):
                raise
            raise GripperFactoryError(f"Unable to construct configured gripper: {exc}") from exc

    @staticmethod
    def _single_mapping(value, field):
        if not isinstance(value, dict) or len(value) != 1:
            raise ValueError(f"{field} must contain exactly one item")
        return next(iter(value.items()))

    @classmethod
    def _instantiate_module(cls, package, spec):
        name, class_name = cls._single_mapping(spec, "module")
        module_type = getattr(import_module(f"{package}.{name}"), class_name)
        return module_type()

    def close(self):
        """Shut down CPX control when factory created it."""
        if self._owned_control is not None:
            control, self._owned_control = self._owned_control, None
            control.shutdown()

    def __enter__(self):
        """Return factory-owned gripper for context management."""
        return self

    def __exit__(self, exc_type, exc_value, traceback):
        """Close factory-owned CPX control after context exit."""
        self.close()

    def _wait(self, timeout: int):
        """Wait ``timeout`` polling cycles.

        Each cycle sleeps for 10 ms. Existing synchronous timing behavior is
        preserved; argument is cycle count, not elapsed milliseconds.
        """
        logger.debug("Gripper wait started: cycles=%s interval_seconds=0.01", timeout)
        for _ in range(timeout):
            # self.control.read_channel(self.channel_numbers[0]) # why?
            time.sleep(0.01)
        logger.debug("Gripper wait completed: cycles=%s", timeout)

    def _set_gripper(self, to_open: bool):
        """Pulse mutually exclusive outputs to open or close gripper.

        Args:
            to_open: ``True`` energizes release output; ``False`` energizes grip.

        Both outputs are reset in ``finally`` after command starts, including
        hardware write, wait, or reset failures.
        """
        logger.info("Gripper output command started: to_open=%s", to_open)
        self._wait(15)
        try:
            self.control.write_channel(self.release_channel, to_open)
            self.control.write_channel(self.grip_channel, not to_open)
            logger.debug(
                "Gripper outputs written: release_channel=%s release_value=%s grip_channel=%s grip_value=%s",
                self.release_channel,
                to_open,
                self.grip_channel,
                not to_open,
            )
            self._wait(100)
            logger.info("Gripper output command completed: to_open=%s", to_open)
        except Exception:
            logger.exception("Gripper output command failed: to_open=%s", to_open)
            raise
        finally:
            try:
                self.control.reset_channel(self.release_channel)
                self.control.reset_channel(self.grip_channel)
            except Exception:
                logger.exception("Gripper output reset failed")
                raise
            logger.debug("Gripper outputs reset")

    def _build_sensor(self, control):
        """Resolve configured digital-input module and create sensor reader."""
        logger.debug("Gripper sensor construction started")
        sensor_config = self.config.get("sensor")
        if not sensor_config:
            return None
        module_spec = sensor_config.get("control_signal_module")
        if not isinstance(module_spec, dict) or len(module_spec) != 1:
            raise ValueError("Sensor control_signal_module must contain exactly one module")
        module_name, module_class = next(iter(module_spec.items()))
        module = getattr(control, "sensor_module", None)
        for candidate in getattr(control, "modules", []):
            if type(candidate).__name__ == module_class or getattr(candidate, "name", None) == module_name:
                module = candidate
                break
        if module is None:
            raise ValueError(f"Configured sensor module not found: {module_class}")
        return GripperSensor(module, sensor_config["control_signal_channels"])

    def check_sensor_status(self) -> GripperStatus:
        """Read configured inputs and classify gripper state."""
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

    def get_status(self) -> GripperStatus:
        """Return current status from configured position sensors."""
        return self.check_sensor_status()

    def grip(self):
        """Command gripper to enter grip state using configured grip output pulse."""
        logger.info("Gripper grip requested")
        self._set_gripper(to_open=False)
        self._wait(1)
        logger.info("Gripper grip completed")

    def release(self):
        """Release gripper from "grip" state using configured release output pulse."""
        logger.info("Gripper release requested")
        self._set_gripper(to_open=True)
        self._wait(1)
        logger.info("Gripper release completed")

    # def get_status(self) -> GripperStatus:
    #     """Return current status from configured position sensors."""
    #     logger.debug("Gripper status requested")
    #     status = self.check_sensor_status()
    #     logger.debug("Gripper status returned: code=%s position=%s", status.code, status.position)
    #     return status


#
# class PneumaticGripper(Gripper):
#     """Gripper control class for CPX-based pneumatic gripping modules."""
#
#     def __init__(self, module, config: dict):
#         """Please Stop."""
#         logger.debug("PneumaticGripper initialization started")
#         super().__init__(module, config)
#         self.pressure_control_module = self.config["components"]["gripper"]["pressure_control_module"]
#         self.GRIP_PRESSURE = None  # TODO: get from config
#         self.RELEASE_PRESSURE = None  # TODO: get from config
#         logger.info("PneumaticGripper initialized")
#
#     def _set_gripper(self, to_open: bool):
#         """Pulse mutually exclusive outputs to open or close gripper.
#
#         Args:
#             to_open: ``True`` energizes release output; ``False`` energizes grip.
#
#         Raises:
#             Exception: Propagates hardware write failures unchanged.
#         """
#         logger.debug("Pneumatic gripper output command started: to_open=%s", to_open)
#         pressure_control_channel = self.pressure_control_module["pressure_control_channel"]
#         logger.info(
#             "Pneumatic gripper command started: to_open=%s pressure_channel=%s",
#             to_open,
#             pressure_control_channel,
#         )
#         try:
#             if to_open:
#                 self.pressure_control_module.write_channel(
#                     pressure_control_channel, int.to_bytes(-500, 2, byteorder="big")
#                 )
#             else:
#                 self.pressure_control_module.write_channel(
#                     pressure_control_channel, int.to_bytes(500, 2, byteorder="big")
#                 )
#         except Exception:
#             logger.exception("Pneumatic gripper command failed: to_open=%s", to_open)
#             raise
#         logger.info("Pneumatic gripper command completed: to_open=%s", to_open)
