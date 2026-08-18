"""Legacy configuration fixture for examples and migration tests."""

# SPDX-FileCopyrightText: 2026 Festo SE & Co. KG
# SPDX-License-Identifier: MIT

component_config = {
    "components": {
        "controller": {
            "type": "remote-io",
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
                {"e4iol": "CpxE4Iol"},
            ],
        },
        "gripper": {
            "uuid": "0000-000000000-000000-000",
            "type": "parallel",
            "positioning": ("discrete", {"positions": 2}),
            "control_signal": "digital",
            "control_library": "cpx_io",
            "control_system": "cpx_system",
            "control_bus": "cpx_e",
            "control_module": {"cpx_e": "CpxE"},
            "controller": {"eep": "CpxEEp"},
            "controller_ip": "0.0.0.0",  # noqa: S104
            "control_signal_module": {"e8do": "CpxE8Do"},
        },
        "pipettor": None,
    }
}
