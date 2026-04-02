# just-build

Minimum viable [PEP 517](https://peps.python.org/pep-0517/) build backend for C extensions.

You know how to build your project. just-build knows how to package it.
That's the whole deal.

---

## The problem

Every existing Python build backend either wants to own your build system,
assumes you're using setuptools extensions, or drags in a dependency tree
bigger than your project. There's no option that just says:

> "Here are your C files. Build them however you want. I'll ship the result."

just-build is that option.

---

## How it works

Add just-build to your `pyproject.toml` and tell it your build command:

```toml
[build-system]
requires = ["just-build"]
build-backend = "just_build"

[project]
name = "mylib"
version = "0.1.0"

[tool.just-build]
command = "make"
```

Run `pip install .` (or `uv pip install .`) and just-build will:

1. Set four environment variables your command can read
2. Call your command
3. Pick up the compiled extension
4. Assemble a correct, shippable wheel
5. Run `auditwheel` / `delocate` / `delvewheel` to make it portable

---

## Environment variables

just-build sets these before calling your command:

| Variable | Example value |
|---|---|
| `JUST_BUILD_NAME` | `mylib` |
| `JUST_BUILD_INCLUDE_DIR` | `/usr/include/python3.12` |
| `JUST_BUILD_OUTPUT_DIR` | `/tmp/just-build-xyz/output` |
| `JUST_BUILD_EXT_SUFFIX` | `.cpython-312-x86_64-linux-gnu.so` |

Your command must write the compiled extension to:

```
$JUST_BUILD_OUTPUT_DIR/$JUST_BUILD_NAME$JUST_BUILD_EXT_SUFFIX
```

That's the entire contract.

---

## Makefile example

```makefile
TARGET := $(JUST_BUILD_OUTPUT_DIR)/$(JUST_BUILD_NAME)$(JUST_BUILD_EXT_SUFFIX)

all: $(TARGET)

$(TARGET):
	$(CC) -shared -fPIC \
		-I$(JUST_BUILD_INCLUDE_DIR) \
		src/mylib/mylib.c \
		-o $(TARGET)
```

---

## Wheel repair

just-build automatically runs the right repair tool for your platform:

| Platform | Tool |
|---|---|
| Linux | `uvx auditwheel repair` |
| macOS | `uvx delocate-wheel` |
| Windows / MinGW | `uvx delvewheel repair` |

Override or disable repair in your config:

```toml
[tool.just-build]
command = "make"
repair = "uvx auditwheel repair --plat manylinux_2_28_x86_64"  # custom
# repair = false  # skip entirely
```

---

## Full configuration reference

```toml
[tool.just-build]
command = "make"       # required — your build command
repair  = "uvx ..."   # optional — auto-detected by platform, or false to skip
```

That's all of it.

---

## Requirements

- Python 3.11+
- A compiler (you already have one)
- `uv` for wheel repair (`uvx auditwheel` / `uvx delocate-wheel` / `uvx delvewheel`)

---

## Running the tests

```sh
python -m unittest tests.test_build -v
```

No dependencies required. The test suite builds a real C extension, verifies
the wheel structure, imports the extension, and confirms it produces correct
results.

---

## License

MIT
