# Examples

## Basic CPX-E gripper

`examples/gripper_demo.py` loads controller and module classes from Spec 3.0 configuration. It does not hard-code `CpxE`, `CpxE16Di`, `CpxE8Do`, or `CpxEEp` imports.

Run only with safe hardware connected:

```bash
GRIPPER_CPX_IP=192.168.0.41 python examples/gripper_demo.py
```

Core pattern:

```python
import os
from importlib import import_module
from pathlib import Path

from gripper.config_adapter import load_config
from gripper.gripper import Gripper

config = load_config(Path("src/gripper/data/gripper-config.json"))
controller = config["components"]["controller"]
package = ".".join(
    (
        controller["control_library"],
        controller["control_system"],
        controller["control_bus"],
    )
)

module_name, class_name = next(iter(controller["control_module"].items()))
controller_class = getattr(import_module(f"{package}.{module_name}"), class_name)
modules = []
for module_spec in controller["modules"]:
    module_name, class_name = next(iter(module_spec.items()))
    module_class = getattr(import_module(f"{package}.{module_name}"), class_name)
    modules.append(module_class())

control_class = controller_class
control = control_class(
    ip_address=os.getenv("GRIPPER_CPX_IP", controller["ip"]),
    modules=modules,
)
gripper = Gripper(control, config)

try:
    gripper.release()
    print(gripper.get_status().get_position())
    gripper.grip()
    print(gripper.get_status().get_position())
finally:
    control.shutdown()
```

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
