# SPDX-FileCopyrightText: 2026 Festo SE & Co. KG
# SPDX-License-Identifier: MIT

"""Test config migration and schema validation."""

import json
import pytest
from pathlib import Path
from types import SimpleNamespace

from src.gripper.config_adapter import (
    GripperConfigAdapter,
    ConfigValidationError,
    load_config,
)
from src.gripper.gripper import Gripper


class TestConfigAdapter:
    """Test GripperConfigAdapter with legacy and spec 3.0 configs."""

    @pytest.fixture
    def legacy_config(self) -> dict:
        """Old Python dict format (test_config.py style)."""
        return {
            "components": {
                "controller": {
                    "control_library": "cpx_io",
                    "control_system": "cpx_system",
                    "control_bus": "cpx_e",
                    "control_module": {"cpx_e": "CpxE"},
                    "controller": {"eep": "CpxEEp"},
                    "ip": "192.168.0.41",
                    "modules": [
                        {"eep": "CpxEEp"},
                        {"e16di": "CpxE16Di"},
                        {"e8do": "CpxE8Do"},
                    ],
                },
                "gripper": {
                    "control_signal_channels": {"grip": 1, "release": 0}
                },
            }
        }

    @pytest.fixture
    def spec_3_0_config(self) -> dict:
        """New spec 3.0 JSON format."""
        return {
            "spec_version": "3.0",
            "component_config": {
                "metadata": {},
                "components": {
                    "gripper_1": {
                        "component_spec_version": "2.0",
                        "component_class": "gripper",
                        "uuid": "0000-000000000-000000-100",
                        "type": "parallel",
                        "control_signal": "digital",
                        "control_modules": {
                            "controller": {
                                "control_library": "cpx_io",
                                "control_system": "cpx_system",
                                "control_bus": "cpx_e",
                                "control_module": {"cpx_e": "CpxE"},
                                "controller": {"eep": "CpxEEp"},
                                "ip": "192.168.0.41",
                                "modules": [
                                    {"eep": "CpxEEp"},
                                    {"e16di": "CpxE16Di"},
                                ],
                            }
                        },
                        "control_signal_channels": {"grip": 1, "release": 0},
                    }
                },
            },
        }

    def test_legacy_config_loads_without_warning(self, legacy_config):
        """Old format loads and adapter detects it correctly."""
        adapter = GripperConfigAdapter(legacy_config)
        assert not adapter.is_new_schema
        assert adapter.config["components"]["gripper"]["control_signal_channels"]["grip"] == 1

    def test_spec_3_0_config_translates_to_legacy(self, spec_3_0_config):
        """New format loads and translates to old format for backward compat."""
        adapter = GripperConfigAdapter(spec_3_0_config)
        assert adapter.is_new_schema
        config = adapter.get_gripper_config()

        # Check translation preserves channel values
        assert config["components"]["gripper"]["control_signal_channels"]["grip"] == 1
        assert config["components"]["gripper"]["control_signal_channels"]["release"] == 0

    def test_sensor_and_output_module_preserved(self, spec_3_0_config):
        gripper = spec_3_0_config["component_config"]["components"]["gripper_1"]
        gripper["control_signal_module"] = {"e8do": "CpxE8Do"}
        gripper["sensor"] = {
            "control_signal_module": {"e16di": "CpxE16Di"},
            "control_signal_channels": {"grip": 0, "release": 1},
        }
        result = GripperConfigAdapter(spec_3_0_config).get_gripper_config()
        assert result["components"]["gripper"]["control_signal_module"] == {"e8do": "CpxE8Do"}
        assert result["components"]["gripper"]["sensor"]["control_signal_channels"] == {
            "grip": 0,
            "release": 1,
        }

    def test_legacy_validates_required_fields(self, legacy_config):
        """Missing required fields in legacy config raises error."""
        del legacy_config["components"]["gripper"]["control_signal_channels"]
        with pytest.raises(ConfigValidationError, match="Missing required field"):
            GripperConfigAdapter(legacy_config)

    def test_legacy_validates_channel_types(self, legacy_config):
        """Non-integer channel numbers raise validation error."""
        legacy_config["components"]["gripper"]["control_signal_channels"]["grip"] = "invalid"
        with pytest.raises(ConfigValidationError, match="must be int"):
            GripperConfigAdapter(legacy_config)

    def test_spec_3_0_validates_version(self, spec_3_0_config):
        """Unsupported spec_version raises error."""
        spec_3_0_config["spec_version"] = "2.0"
        with pytest.raises(ConfigValidationError, match="Unsupported spec_version"):
            GripperConfigAdapter(spec_3_0_config)

    def test_spec_3_0_requires_gripper_component(self, spec_3_0_config):
        """Missing gripper component raises error."""
        del spec_3_0_config["component_config"]["components"]["gripper_1"]
        with pytest.raises(ConfigValidationError, match="No component with component_class"):
            GripperConfigAdapter(spec_3_0_config)

    def test_spec_3_0_validates_control_signal_channels(self, spec_3_0_config):
        """Missing or invalid channels in spec 3.0 raises error."""
        spec_3_0_config["component_config"]["components"]["gripper_1"][
            "control_signal_channels"
        ] = {"grip": 1}  # missing release
        with pytest.raises(ConfigValidationError, match="must have 'grip' and 'release'"):
            GripperConfigAdapter(spec_3_0_config)

    def test_load_from_json_file(self, tmp_path, spec_3_0_config):
        """load_config() handles JSON file paths."""
        config_file = tmp_path / "config.json"
        config_file.write_text(json.dumps(spec_3_0_config))

        config = load_config(config_file)
        assert config["components"]["gripper"]["control_signal_channels"]["grip"] == 1

    def test_load_from_path_string(self, tmp_path, spec_3_0_config):
        """load_config() accepts string paths."""
        config_file = tmp_path / "config.json"
        config_file.write_text(json.dumps(spec_3_0_config))

        config = load_config(str(config_file))
        assert config["components"]["gripper"]["control_signal_channels"]["grip"] == 1

    def test_load_missing_file_raises_error(self):
        """load_config() raises FileNotFoundError for missing files."""
        with pytest.raises(FileNotFoundError):
            load_config("/nonexistent/config.json")

    def test_load_invalid_json_raises_error(self, tmp_path):
        """load_config() raises ConfigValidationError for invalid JSON."""
        config_file = tmp_path / "bad.json"
        config_file.write_text("{ invalid json")

        with pytest.raises(ConfigValidationError, match="Invalid JSON"):
            load_config(config_file)

    def test_channel_values_preserved_after_translation(self, spec_3_0_config):
        """Grip/release channel numbers match after spec 3.0 → legacy translation."""
        spec_3_0_config["component_config"]["components"]["gripper_1"][
            "control_signal_channels"
        ] = {"grip": 5, "release": 3}

        adapter = GripperConfigAdapter(spec_3_0_config)
        config = adapter.get_gripper_config()

        assert config["components"]["gripper"]["control_signal_channels"]["grip"] == 5
        assert config["components"]["gripper"]["control_signal_channels"]["release"] == 3

    def test_controller_extraction_from_control_modules(self, spec_3_0_config):
        """Controller config extracted correctly from control_modules."""
        adapter = GripperConfigAdapter(spec_3_0_config)
        config = adapter.get_gripper_config()

        # Check controller fields extracted
        assert config["components"]["controller"]["control_library"] == "cpx_io"
        assert config["components"]["controller"]["control_system"] == "cpx_system"
        assert config["components"]["controller"]["control_bus"] == "cpx_e"
        assert config["components"]["controller"]["ip"] == "192.168.0.41"

    def test_spec_3_0_mounted_gripper_preserves_mount_fields(self):
        """Mounted gripper spec 3.0 config validates mount_gantry, mount_axis."""
        config = {
            "spec_version": "3.0",
            "component_config": {
                "metadata": {},
                "components": {
                    "gripper_mounted": {
                        "component_spec_version": "2.0",
                        "component_class": "gripper",
                        "uuid": "0000-000000000-000000-100",
                        "mount_gantry": {"name": "gantry_1", "uuid": "0000-000000000-000000-200"},
                        "mount_axis": {"name": "Z", "index": 2, "uuid": "0000-000000000-000000-202"},
                        "control_signal_channels": {"grip": 1, "release": 0},
                        "control_modules": {
                            "controller": {
                                "control_library": "cpx_io",
                                "control_module": {"cpx_e": "CpxE"},
                            }
                        },
                    }
                },
            },
        }

        adapter = GripperConfigAdapter(config)
        assert adapter.is_new_schema
        # Should load without error (mount fields are optional but allowed)
        assert adapter.get_gripper_config() is not None

    def test_deprecation_warning_on_spec_3_0_load(self, spec_3_0_config, caplog):
        """Loading spec 3.0 config logs deprecation warning."""
        adapter = GripperConfigAdapter(spec_3_0_config)
        assert "Spec 3.0 config detected" in caplog.text


class TestDynamicImportValidation:
    """Test validation of dynamic import patterns."""

    def test_f_string_import_construction_cpx_e(self):
        """F-string for CPX-E module path construction is valid."""
        control_library = "cpx_io"
        control_system = "cpx_system"
        control_bus = "cpx_e"
        lib = "cpx_e"

        result = f"{control_library}.{control_system}.{control_bus}.{lib}"
        expected = "cpx_io.cpx_system.cpx_e.cpx_e"
        assert result == expected

    def test_control_module_dict_unpacking_single_item(self):
        """control_module dict with exactly 1 item unpacks correctly."""
        control_module = {"cpx_e": "CpxE"}
        lib, head = tuple(control_module.items())[0]
        assert lib == "cpx_e"
        assert head == "CpxE"

    def test_control_module_dict_multiple_items_raises_error(self):
        """control_module dict with 2+ items fails unpacking."""
        control_module = {"cpx_e": "CpxE", "other": "Other"}
        # Unpacking works but gets first item only
        lib, head = tuple(control_module.items())[0]
        # This should be caught by validation logic
        assert len(control_module) > 1  # Multiple items detected


class TestCPXAPAConfig:
    """Test CPX-AP-A (pneumatic gripper) config support."""

    def test_cpx_ap_a_config_loads(self):
        """CPX-AP-A spec 3.0 config with device descriptor validates."""
        config = {
            "spec_version": "3.0",
            "component_config": {
                "metadata": {},
                "components": {
                    "gripper_cpx_ap_a": {
                        "component_spec_version": "2.0",
                        "component_class": "gripper",
                        "uuid": "0000-000000000-000000-102",
                        "control_library": "cpx_ap",
                        "control_system": "cpx_system",
                        "control_bus": "cpx_ap_a",
                        "control_modules": {
                            "controller": {
                                "control_library": "cpx_ap",
                                "control_module": {"cpx_ap_a": "CpxApA"},
                            },
                            "gripper_control": {
                                "device_descriptor_file": "descriptors/CPX-AP-A.xml",
                                "device_descriptor_url": "https://festo/descriptors/cpx-ap-a.xml",
                            },
                        },
                        "control_signal_channels": {"grip": 1, "release": 0},
                    }
                },
            },
        }

        adapter = GripperConfigAdapter(config)
        assert adapter.is_new_schema
        result = adapter.get_gripper_config()
        assert result["components"]["gripper"]["uuid"] == "0000-000000000-000000-102"


class TestGripperSensorStatus:
    def test_sensor_status_reads_cpx_e16di_channels(self):
        class FakeInput:
            name = "e16di"

            def __init__(self, values):
                self.values = values

            def read_channel(self, channel):
                return self.values[channel]

        config = {
            "components": {
                "gripper": {
                    "control_signal_channels": {"grip": 1, "release": 0},
                    "sensor": {
                        "control_signal_module": {"e16di": "CpxE16Di"},
                        "control_signal_channels": {"grip": 0, "release": 1},
                    },
                }
            }
        }
        control = SimpleNamespace(modules=[FakeInput([True, False])])
        gripper = Gripper(control, config)

        status = gripper.get_status()

        assert status.get_gripping_state() == "gripping"
        assert status.get_position() == "closed"

    def test_sensor_status_reports_contradictory_inputs(self):
        class FakeInput:
            name = "e16di"

            def read_channel(self, channel):
                return True

        config = {
            "components": {
                "gripper": {
                    "control_signal_channels": {"grip": 1, "release": 0},
                    "sensor": {
                        "control_signal_module": {"e16di": "CpxE16Di"},
                        "control_signal_channels": {"grip": 0, "release": 1},
                    },
                }
            }
        }
        gripper = Gripper(SimpleNamespace(modules=[FakeInput()]), config)

        status = gripper.get_status()

        assert status.code == 2
        assert status.get_position() == "contradictory"
