"""Shared pytest fixtures for the festo-dev-gripper test suite.

Fixtures
--------
gripper
    A ``Gripper`` connected to the CPX-E module at the configured IP
    address.  The IP is read from the ``GRIPPER_CPX_IP`` environment
    variable, falling back to the default found in the reference
    configuration.  Mark any test that uses this fixture with
    ``@pytest.mark.hardware``.

Run all hardware tests with::

    uv run pytest -m hardware

Skip hardware tests (CI default)::

    uv run pytest -m "not hardware"

Override connection details at runtime::

    GRIPPER_CPX_IP=10.0.0.41 uv run pytest -m hardware
"""

import socket
from os import getenv

import pytest

from gripper.gripper import Gripper

# ---------------------------------------------------------------------------
# Defaults taken from festo-dev-gripper/src/gripper/test_config.py
# ---------------------------------------------------------------------------
_DEFAULT_CPX_IP = "192.168.0.41"
_DEFAULT_GRIP_CHANNEL = 1
_DEFAULT_RELEASE_CHANNEL = 0
_CPX_PORT = 502


def _build_gripper_config(ip: str, grip_ch: int, release_ch: int) -> dict:
    return {
        "components": {
            "gripper": {
                "control_signal_channels": {
                    "grip": grip_ch,
                    "release": release_ch,
                },
                "sensor": {
                    "control_signal_module": {"e16di": "CpxE16Di"},
                    "control_signal_channels": {"grip": 0, "release": 1},
                },
            }
        }
    }


# ---------------------------------------------------------------------------
# Hardware fixtures — require a connected CPX-E module
# ---------------------------------------------------------------------------


@pytest.fixture(scope="module")
def gripper_control():
    """Return a CPX-E control object connected to the configured hardware."""
    ip = getenv("GRIPPER_CPX_IP", _DEFAULT_CPX_IP)
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as probe:
        probe.settimeout(2.0)
        if probe.connect_ex((ip, _CPX_PORT)) != 0:
            pytest.skip(f"CPX-E hardware not reachable at {ip}:{_CPX_PORT}")

    from cpx_io.cpx_system.cpx_e.cpx_e import CpxE
    from cpx_io.cpx_system.cpx_e.e16di import CpxE16Di
    from cpx_io.cpx_system.cpx_e.e8do import CpxE8Do
    from cpx_io.cpx_system.cpx_e.eep import CpxEEp

    return CpxE(ip_address=ip, modules=[CpxEEp(), CpxE16Di(), CpxE8Do()])


@pytest.fixture(scope="module")
def gripper(gripper_control):
    """Return a Gripper connected to the hardware CPX-E control object."""
    grip_ch = int(getenv("GRIPPER_GRIP_CHANNEL", str(_DEFAULT_GRIP_CHANNEL)))
    release_ch = int(getenv("GRIPPER_RELEASE_CHANNEL", str(_DEFAULT_RELEASE_CHANNEL)))
    config = _build_gripper_config(
        ip=getenv("GRIPPER_CPX_IP", _DEFAULT_CPX_IP),
        grip_ch=grip_ch,
        release_ch=release_ch,
    )
    return Gripper(gripper_control, config)
