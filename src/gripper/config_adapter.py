# SPDX-FileCopyrightText: 2026 Festo SE & Co. KG
# SPDX-License-Identifier: MIT

"""Config adapter for backward compatibility and schema validation."""

import json
import logging
from pathlib import Path
from typing import Any, Dict, Union

logger = logging.getLogger(__name__)


class ConfigValidationError(Exception):
    """Raised when config schema validation fails."""

    pass


class GripperConfigAdapter:
    """
    Translate between old Python dict format and new spec 3.0 JSON schema.

    Handles both formats transparently:
    - Old format: Python dict (legacy test_config.py)
    - New format: Spec 3.0 JSON with component_spec_version 2.0

    Adapter detects format at load time and translates new → old field names
    internally, so old code sees identical dict structure. Deprecation warnings
    guide users to new schema.
    """

    OLD_FORMAT_VERSION = "1.0"
    NEW_FORMAT_VERSION = "3.0"
    COMPONENT_SPEC_VERSION = "2.0"

    def __init__(self, config: Union[Dict[str, Any], str, Path]) -> None:
        """
        Load config from dict, JSON file, or path string.

        Args:
            config: Config dict, file path (str/Path), or JSON content string

        Raises:
            ConfigValidationError: Schema validation fails
        """
        logger.debug("GripperConfigAdapter initialization started: config_type=%s", type(config).__name__)
        if isinstance(config, (str, Path)):
            logger.debug("Loading gripper config file: path=%s", config)
            config = self._load_json_file(config)

        self.raw_config = config
        self.is_new_schema = self._detect_schema_version()
        logger.debug("Detected gripper config schema: new=%s", self.is_new_schema)

        if self.is_new_schema:
            self._validate_spec_3_0()
            self.config = self._translate_spec_3_0_to_legacy()
            logger.info("Translated spec 3.0 gripper config to legacy format")
            logger.warning(
                "Spec 3.0 config detected. Migration path available: See docs/MIGRATION.md for upgrade guide."
            )
        else:
            self._validate_legacy()
            self.config = config
            logger.debug("Legacy config loaded (old Python dict format)")
        logger.debug("GripperConfigAdapter initialization completed: new_schema=%s", self.is_new_schema)

    def get_gripper_config(self) -> Dict[str, Any]:
        """Return normalized config dict compatible with Gripper."""
        logger.debug("Normalized gripper config requested")
        return self.config

    @staticmethod
    def _load_json_file(path: Union[str, Path]) -> Dict[str, Any]:
        """Load and parse JSON file."""
        logger.debug("JSON gripper config load started: path=%s", path)
        path = Path(path)
        if not path.exists():
            logger.error("Gripper config file not found: path=%s", path)
            raise FileNotFoundError(f"Config file not found: {path}")
        try:
            with open(path, "r") as f:
                config = json.load(f)
                logger.debug("Gripper config file loaded: path=%s", path)
                return config
        except json.JSONDecodeError as e:
            logger.error("Invalid gripper config JSON: path=%s", path)
            raise ConfigValidationError(f"Invalid JSON in {path}: {e}") from e

    def _detect_schema_version(self) -> bool:
        """Detect if config is new spec 3.0 (True) or old format (False)."""
        # New schema has spec_version key at top level
        detected = "spec_version" in self.raw_config
        logger.debug("Gripper config schema detection completed: new_schema=%s", detected)
        return detected

    def _validate_legacy(self) -> None:
        """Validate old Python dict format."""
        logger.debug("Legacy gripper config validation started")
        required_paths = [
            ("components",),
            ("components", "gripper"),
            ("components", "gripper", "control_signal_channels"),
            ("components", "gripper", "control_signal_channels", "grip"),
            ("components", "gripper", "control_signal_channels", "release"),
        ]

        for path in required_paths:
            try:
                self._get_nested(self.raw_config, path)
            except KeyError:
                logger.error("Legacy gripper config missing field: path=%s", ".".join(path))
                raise ConfigValidationError(f"Missing required field in legacy config: {'.'.join(path)}") from None

        # Validate channel types
        grip = self._get_nested(self.raw_config, ("components", "gripper", "control_signal_channels", "grip"))
        release = self._get_nested(self.raw_config, ("components", "gripper", "control_signal_channels", "release"))

        if not isinstance(grip, int):
            logger.error("Legacy gripper grip channel has invalid type: type=%s", type(grip).__name__)
            raise ConfigValidationError(f"grip channel must be int, got {type(grip).__name__}")
        if not isinstance(release, int):
            logger.error("Legacy gripper release channel has invalid type: type=%s", type(release).__name__)
            raise ConfigValidationError(f"release channel must be int, got {type(release).__name__}")
        logger.debug("Legacy gripper config validation completed")

    def _validate_spec_3_0(self) -> None:
        """Validate spec 3.0 schema structure."""
        logger.debug("Spec 3.0 gripper config validation started")
        required_top_level = ("spec_version", "component_config")
        for field in required_top_level:
            if field not in self.raw_config:
                logger.error("Spec 3.0 gripper config missing top-level field: field=%s", field)
                raise ConfigValidationError(f"Missing required top-level field: {field}")

        if self.raw_config["spec_version"] != self.NEW_FORMAT_VERSION:
            logger.error("Unsupported gripper config schema: version=%s", self.raw_config["spec_version"])
            raise ConfigValidationError(
                f"Unsupported spec_version: {self.raw_config['spec_version']}. Expected {self.NEW_FORMAT_VERSION}"
            )

        # Validate component structure
        components = self._get_nested(self.raw_config, ("component_config", "components"))
        if not isinstance(components, dict):
            logger.error("Spec 3.0 gripper components are not a dict")
            raise ConfigValidationError("component_config.components must be a dict")

        # Find first gripper component and validate it
        gripper_config = None
        for _, comp_spec in components.items():
            if comp_spec.get("component_class") == "gripper":
                gripper_config = comp_spec
                break

        if not gripper_config:
            logger.error("Spec 3.0 gripper component not found")
            raise ConfigValidationError("No component with component_class='gripper' found")

        # Validate required gripper fields
        required_gripper_fields = (
            "component_spec_version",
            "control_signal_channels",
        )
        for field in required_gripper_fields:
            if field not in gripper_config:
                logger.error("Spec 3.0 gripper component missing field: field=%s", field)
                raise ConfigValidationError(f"Gripper component missing required field: {field}")

        # Validate signal channels
        channels = gripper_config["control_signal_channels"]
        self._validate_signal_channels(channels)
        logger.debug("Spec 3.0 gripper config validation completed")

    def _validate_signal_channels(self, channels: Any) -> None:
        logger.debug("Gripper control signal channel validation started")
        if not isinstance(channels, dict):
            logger.error("Gripper control signal channels are not a dict")
            raise ConfigValidationError("control_signal_channels must be a dict")
        if "grip" not in channels or "release" not in channels:
            logger.error("Gripper control signal channels missing grip or release")
            raise ConfigValidationError("control_signal_channels must have 'grip' and 'release' keys")
        if not isinstance(channels["grip"], int) or not isinstance(channels["release"], int):
            logger.error("Gripper control signal channels have invalid types")
            raise ConfigValidationError("grip/release channels must be integers")
        logger.debug("Gripper control signal channel validation completed")

    def _translate_spec_3_0_to_legacy(self) -> Dict[str, Any]:
        """Translate spec 3.0 config to old Python dict format."""
        logger.debug("Spec 3.0 gripper config translation started")
        # Extract gripper component
        components = self._get_nested(self.raw_config, ("component_config", "components"))
        gripper_config = None

        for _, comp_spec in components.items():
            if comp_spec.get("component_class") == "gripper":
                gripper_config = comp_spec
                break

        if not gripper_config:
            logger.error("Spec 3.0 gripper component missing during translation")
            raise ConfigValidationError("No gripper component found in spec 3.0 config")

        # Build legacy format
        translated = {
            "components": {
                "gripper": {
                    "control_signal_channels": gripper_config["control_signal_channels"],
                    "control_signal_module": gripper_config.get("control_signal_module", {}),
                    "sensor": gripper_config.get("sensor"),
                    # Preserve other fields if present
                    "uuid": gripper_config.get("uuid", "0000-000000000-000000-000"),
                    "type": gripper_config.get("type", "parallel"),
                    "control_signal": gripper_config.get("control_signal", "digital"),
                },
                # Include controller if present (from control_modules)
                "controller": self._extract_controller_config(gripper_config),
            }
        }
        logger.debug("Spec 3.0 gripper config translation completed")
        return translated

    @staticmethod
    def _extract_controller_config(gripper_config: Dict[str, Any]) -> Dict[str, Any]:
        """Extract controller config from gripper's control_modules."""
        logger.debug("Controller config extraction started")
        control_modules = gripper_config.get("control_modules", {})
        controller = control_modules.get("controller", {})
        control_system = controller.get("control_system", "cpx_system")
        control_bus = controller.get("control_bus")
        if control_bus is None and "." in control_system:
            control_system, control_bus = control_system.split(".", 1)

        # Return controller with defaults if not present
        controller_config = {
            "control_library": controller.get("control_library", "cpx_io"),
            "control_system": control_system,
            "control_bus": control_bus or "cpx_e",
            "control_module": controller.get("control_module", {"cpx_e": "CpxE"}),
            "controller": controller.get("controller", {"eep": "CpxEEp"}),
            "ip": controller.get("ip", "192.168.0.41"),
            "modules": controller.get("modules", []),
        }
        logger.debug("Controller config extraction completed: module_count=%s", len(controller_config["modules"]))
        return controller_config

    @staticmethod
    def _get_nested(d: Dict[str, Any], path: tuple) -> Any:
        """Get nested dict value by path tuple."""
        logger.debug("Nested gripper config value requested: path=%s", ".".join(path))
        result = d
        for key in path:
            result = result[key]
        logger.debug("Nested gripper config value found: path=%s", ".".join(path))
        return result


def load_config(config_path: Union[str, Path]) -> Dict[str, Any]:
    """
    Load config file (spec 3.0 or legacy) and return normalized dict.

    Handles migration transparently. Logs deprecation warning if legacy format.

    Args:
        config_path: Path to JSON or Python dict config

    Returns:
        Config dict in legacy format (compatible with existing code)

    Raises:
        ConfigValidationError: Schema validation fails
        FileNotFoundError: Config file not found
    """
    logger.info("Gripper config load requested: path=%s", config_path)
    adapter = GripperConfigAdapter(config_path)
    config = adapter.get_gripper_config()
    logger.info("Gripper config load completed: new_schema=%s", adapter.is_new_schema)
    return config
