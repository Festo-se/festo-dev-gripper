# Festo Dev Gripper

[![CI tests](https://github.com/Festo-se/festo-dev-gripper/actions/workflows/ci.yml/badge.svg?branch=main)](https://github.com/Festo-se/festo-dev-gripper/actions/workflows/ci.yml)
[![Coverage](https://codecov.io/gh/Festo-se/festo-dev-gripper/branch/main/graph/badge.svg)](https://app.codecov.io/gh/Festo-se/festo-dev-gripper)
[![Release](https://img.shields.io/github/v/release/Festo-se/festo-dev-gripper?display_name=tag)](https://github.com/Festo-se/festo-dev-gripper/releases)
[![License](https://img.shields.io/github/license/Festo-se/festo-dev-gripper)](LICENSE)

Python controls for digital-I/O Festo parallel grippers. The library drives
grip and release outputs through `festo-cpx-io`, reads optional open/closed
switches, and accepts both legacy Python dictionaries and Spec 3.0 JSON
configuration.

> **Badge hooks:** The CI badge expects `.github/workflows/ci.yml`; the coverage
> badge expects a Codecov upload for this repository. They become live when
> those integrations are configured.

## Features

- Open or close a parallel gripper with mapped digital-output channels.
- Read optional digital-input sensors for open, closed, moving, and
	contradictory states.
- Load and validate legacy configuration dictionaries.
- Load Spec 3.0 JSON configuration and translate it for existing controls.
- Configure CPX-E and CPX-AP-A controller metadata.
- Model standalone or gantry-mounted grippers.

## Requirements

- Python 3.10 or later
- A compatible `festo-cpx-io` control object
- `uv` recommended for installation and development

## Install

Install released package:

```bash
uv add festo-dev-gripper
```

Install repository checkout for development:

```bash
uv sync
```

## Quick start

Create controller through `festo-cpx-io`, load a gripper configuration, then
call `grip()` or `release()`.

```python
from gripper.config_adapter import load_config
from gripper.gripper import Gripper

# Construct this with the CPX-E modules and network settings for your system.
control = create_festo_cpx_io_control()

config = load_config("src/gripper/data/gripper-config.json")
gripper = Gripper(control, config)

gripper.grip()
status = gripper.get_status()
print(status.get_gripping_state())  # "gripping" when closed sensor is active

gripper.release()
```

Runnable hardware example: `examples/gripper_demo.py`.

`create_festo_cpx_io_control()` is application-specific. Its control object
must support `write_channel()` and `reset_channel()`. For sensor feedback, it
must expose configured input modules through `control.modules`.

## Status feedback

When a `sensor` block is configured, `get_status()` returns these states:

| Sensor inputs | Gripping state | Movement state | Position | Code |
| --- | --- | --- | --- | --- |
| Grip active | `gripping` | `stopped` | `closed` | `0` |
| Release active | `released` | `stopped` | `open` | `0` |
| Neither active | `unknown` | `moving` | `None` | `1` |
| Both active | `fault` | `unknown` | `contradictory` | `2` |

Without a sensor configuration, status code is `0` with unknown state fields.

## Configuration

Spec 3.0 is recommended. It must contain `spec_version: "3.0"`, a gripper
component with `component_class: "gripper"`, and integer `grip` and `release`
output channels.

```json
{
	"spec_version": "3.0",
	"component_config": {
		"components": {
			"gripper_1": {
				"component_spec_version": "2.0",
				"component_class": "gripper",
				"control_signal_channels": {
					"grip": 1,
					"release": 0
				},
				"sensor": {
					"control_signal_module": {"e16di": "CpxE16Di"},
					"control_signal_channels": {"grip": 0, "release": 1}
				}
			}
		}
	}
}
```

Reference configurations:

- `src/gripper/data/gripper-config.json`: CPX-E standalone and mounted grippers.
- `src/gripper/data/gripper-config-cpx-ap-a.json`: CPX-AP-A pneumatic gripper.
- `MIGRATION-GUIDE.md`: legacy-to-Spec-3.0 migration details.

## Development

Run tests:

```bash
uv run pytest
```

Run tests with coverage:

```bash
uv run pytest --cov=gripper --cov-report=term-missing
```

Hardware-dependent tests should be explicitly marked `hardware`; skip them in
local CI-style runs with:

```bash
uv run pytest -m "not hardware"
```

## Safety

Validate channel mappings and test hardware behavior in a safe state before
operating a connected gripper. Incorrect I/O mapping can cause unexpected
motion.

## License

Distributed under the [MIT License](LICENSE).
