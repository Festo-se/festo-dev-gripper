# Festo Gripper

`festo-dev-gripper` is a Python library providing a reference implementation of controls for a digital-IO-based Festo parallel gripper using the `festo-cpx-io` library.

## Installation

### From Codebase

Navigate to the directory where the code is stored and, using uv, type in the following command:

```
uv pip install -e .
```

This will package the library locally and can be used as regular imports.

### Official Packaged Releases

The latest released version of this package can be found on the package registry of this project.
Install using uv:

```
uv add festo-dev-gripper
```

### From Git Repository

```
uv pip install git+https://github.com/Festo-se/festo-dev-gripper.git
```

Or as an editable dependency with a local copy of the source code:

1. Clone the repository

```
git clone https://github.com/Festo-se/festo-dev-gripper.git <destination-directory>
```

2. Navigate to the clone destination directory

```
cd <destination>
```

3. Install with uv

```
uv pip install -e .
```

## Dependencies

`festo-dev-gripper` depends on `festo-cpx-io` for communicating with the Festo CPX I/O system.

## Examples

See [Examples](examples.md) for basic gripper operation and configuration-driven dynamic controller loading.
