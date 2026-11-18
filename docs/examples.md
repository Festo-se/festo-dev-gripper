# Examples

## Basic CPX-E gripper

`examples/gripper_demo.py` loads controller and module classes from Spec 3.0 configuration. It does not hard-code `CpxE`, `CpxE16Di`, `CpxE8Do`, or `CpxEEp` imports.

Run only with safe hardware connected:

```bash
GRIPPER_CPX_IP=192.168.0.2 python examples/gripper_demo.py
```

Core pattern using the canonical, managed configurator bootstrap:

```python
from pathlib import Path

from configurator import Configurator, Registry
from gripper.bootstrap import gripper_registration

with Configurator.bootstrap(
    Path("src/gripper/data/gripper-config.json"),
    "gripper_standalone",
    Registry.compose(gripper_registration()),
    options={"legacy_component_types": {"gripper_standalone": "gripper"}},
) as result:
    gripper = result.instance
    gripper.release()
    print(gripper.get_status().get_position())
    gripper.grip()
    print(gripper.get_status().get_position())
```

`Gripper.from_config` and `load_config` remain compatibility delegates for one
release cycle. New config-driven consumers should call `Configurator.bootstrap`
with an explicit gripper registration as shown above.

Configuration selects output and sensor modules:

```json
"control_signal_module": {"e8do": "CpxE8Do"},
"control_signal_channels": {"grip": 1, "release": 0},
"sensor": {
  "control_signal_module": {"e16di": "CpxE16Di"},
  "control_signal_channels": {"grip": 0, "release": 1}
}
```

`CpxE8Do` drives outputs. `CpxE16Di` reads closed/gripping input on channel `0` and open/released input on channel `1`.
