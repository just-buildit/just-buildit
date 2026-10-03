# Examples

Each example below corresponds to a runnable directory in the repository.
Clone the repo and `pip install` the example directly to try it:

```sh
git clone https://github.com/just-buildit/just-buildit
cd just-buildit
pip install ./examples/make      # zero-config
pip install ./examples/cmake
pip install ./examples/meson
pip install ./examples/mixed
pip install ./examples/nested
pip install ./examples/clang-cl  # Windows only (clang-cl)
pip install ./examples/bazel     # requires Bazel
```

______________________________________________________________________

## Zero config

No build command needed — just-buildit discovers `src/add/add.c` and
compiles it automatically.

**Requires:** C compiler (`cc`, `gcc`, or `clang`) on `$PATH`

[Browse `examples/make/`](https://github.com/just-buildit/just-buildit/tree/main/examples/make)

```sh
pip install ./examples/make
python -c "import add; print(add.add(1, 2))"
```

**`pyproject.toml`**

```toml
[build-system]
requires = ["just-buildit"]
build-backend = "just_buildit"

[project]
name = "add"
version = "0.1.0"
description = "just-buildit zero-config example — no Makefile, no command."
requires-python = ">=3.8"

[tool.just-buildit]
repair = false
# Zero-config means no build command — just-buildit finds src/add/add.c
# and compiles it automatically. Repair is a separate distribution concern.
```

**`src/add/add.c`**

```c
/*
 * add.c — zero-config just-buildit example.
 * No Makefile. No command. Just source.
 *
 * Exports: add.add(a, b) -> int
 */

#define PY_SSIZE_T_CLEAN
#include <Python.h>

static PyObject *
add_add(PyObject *self, PyObject *args)
{
    long a, b;
    if (!PyArg_ParseTuple(args, "ll", &a, &b))
        return NULL;
    return PyLong_FromLong(a + b);
}

static PyMethodDef AddMethods[] = {
    {"add", add_add, METH_VARARGS, "Add two integers."},
    {NULL, NULL, 0, NULL}
};

static struct PyModuleDef addmodule = {
    PyModuleDef_HEAD_INIT, "add", NULL, -1, AddMethods
};

PyMODINIT_FUNC
PyInit_add(void) { return PyModule_Create(&addmodule); }
```

______________________________________________________________________

## CMake

**Requires:** `cmake`, `make`, C compiler

[Browse `examples/cmake/`](https://github.com/just-buildit/just-buildit/tree/main/examples/cmake)

```sh
pip install ./examples/cmake
python -c "import add; print(add.add(3, 4))"
```

**`pyproject.toml`**

```toml
[build-system]
requires = ["just-buildit"]
build-backend = "just_buildit"

[project]
name = "add"
version = "0.1.0"
description = "just-buildit CMake example."
requires-python = ">=3.8"

[tool.just-buildit]
command = "make pyext"
repair = false
```

**`Makefile`**

```makefile
pyext:
	cmake -S . -B _build -DCMAKE_BUILD_TYPE=Release
	cmake --build _build
	find _build -name "*$(JUST_BUILDIT_EXT_SUFFIX)" \
		-exec cp {} $(JUST_BUILDIT_OUTPUT_DIR)/ \;

clean:
	rm -rf _build
```

**`CMakeLists.txt`**

```cmake
cmake_minimum_required(VERSION 3.15)
project(add C)

# Build for the interpreter just-buildit is building FOR, not whatever cmake
# finds first. `Development.Module` searches for HEADERS, so setting
# Python3_EXECUTABLE alone is not enough -- it needs the header hint.
if(DEFINED ENV{JUST_BUILDIT_PYTHON})
    set(Python3_EXECUTABLE "$ENV{JUST_BUILDIT_PYTHON}")
endif()
if(DEFINED ENV{JUST_BUILDIT_INCLUDE_DIR})
    set(Python3_INCLUDE_DIR "$ENV{JUST_BUILDIT_INCLUDE_DIR}")
endif()
find_package(Python3 COMPONENTS Development.Module REQUIRED)
Python3_add_library(add MODULE src/add.c)
set_target_properties(add PROPERTIES
    OUTPUT_NAME "$ENV{JUST_BUILDIT_NAME}"
    SUFFIX      "$ENV{JUST_BUILDIT_EXT_SUFFIX}"
    PREFIX      "")
```

**`src/add.c`**

```c
/*
 * add.c — just-buildit CMake example.
 *
 * Exports: add.add(a, b) -> int
 */

#define PY_SSIZE_T_CLEAN
#include <Python.h>

static PyObject *
add_add(PyObject *self, PyObject *args)
{
    long a, b;
    if (!PyArg_ParseTuple(args, "ll", &a, &b))
        return NULL;
    return PyLong_FromLong(a + b);
}

static PyMethodDef AddMethods[] = {
    {"add", add_add, METH_VARARGS, "Add two integers."},
    {NULL, NULL, 0, NULL}
};

static struct PyModuleDef addmodule = {
    PyModuleDef_HEAD_INIT, "add", NULL, -1, AddMethods
};

PyMODINIT_FUNC
PyInit_add(void) { return PyModule_Create(&addmodule); }
```

______________________________________________________________________

## Meson

**Requires:** `meson`, `ninja`, `make`, C compiler

[Browse `examples/meson/`](https://github.com/just-buildit/just-buildit/tree/main/examples/meson)

```sh
pip install ./examples/meson
python -c "import add; print(add.add(5, 6))"
```

**`pyproject.toml`**

```toml
[build-system]
requires = ["just-buildit"]
build-backend = "just_buildit"

[project]
name = "add"
version = "0.1.0"
description = "just-buildit Meson example."
requires-python = ">=3.8"

[tool.just-buildit]
command = "make pyext"
repair = false
```

**`Makefile`**

```makefile
pyext:
	meson setup _build --wipe -Dbuildtype=release \
	    -Dpython_path="$${JUST_BUILDIT_PYTHON:-python3}"
	meson compile -C _build
	find _build -name "*$(JUST_BUILDIT_EXT_SUFFIX)" \
		-exec cp {} $(JUST_BUILDIT_OUTPUT_DIR)/ \;

clean:
	rm -rf _build
```

**`meson.build`**

```python
project('add', 'c')
# `find_installation()` with no argument takes whatever meson finds, which is
# a different Python whenever the build runs under a venv while another
# python3 leads PATH. meson.build cannot read the environment, so the
# Makefile passes the interpreter through this option.
py = import('python').find_installation(get_option('python_path'))
py.extension_module('add', 'src/add.c', install: false, build_by_default: true)
```

**`meson_options.txt`**

```python
# Set by the Makefile from JUST_BUILDIT_PYTHON; see meson.build.
option('python_path', type: 'string', value: 'python3',
       description: 'Interpreter to build the extension for')
```

**`src/add.c`** — same as the CMake example above.

______________________________________________________________________

## Mixed pure Python + C extension

A package (`calc`) where `__init__.py` is pure Python and `_core` is a C
extension. Both ship in the same wheel from a single `$JUST_BUILDIT_OUTPUT_DIR`.

**Requires:** `make`, C compiler

[Browse `examples/mixed/`](https://github.com/just-buildit/just-buildit/tree/main/examples/mixed)

```sh
pip install ./examples/mixed
python -c "import calc; print(calc.add_and_multiply(3, 4))"
```

**Layout**

```
src/calc/
    __init__.py      # pure Python
    _core.c          # C extension
```

**`pyproject.toml`**

```toml
[build-system]
requires = ["just-buildit"]
build-backend = "just_buildit"

[project]
name = "calc"
version = "0.1.0"
description = "just-buildit mixed pure/platform example."
requires-python = ">=3.8"

[tool.just-buildit]
command = "make"
repair = false
```

**`Makefile`**

```makefile
EXT := $(JUST_BUILDIT_OUTPUT_DIR)/calc/_core$(JUST_BUILDIT_EXT_SUFFIX)

all: $(EXT)
	cp src/calc/__init__.py $(JUST_BUILDIT_OUTPUT_DIR)/calc/

$(EXT):
	mkdir -p $(JUST_BUILDIT_OUTPUT_DIR)/calc
	$(CC) $(JUST_BUILDIT_LDFLAGS) \
		-I$(JUST_BUILDIT_INCLUDE_DIR) \
		src/calc/_core.c \
		-o $(EXT) \
		$(JUST_BUILDIT_LIBS)

clean:
	rm -f src/calc/_core*.so src/calc/_core*.pyd
```

**`src/calc/__init__.py`**

```python
from __future__ import annotations

from calc._core import add, multiply


def add_and_multiply(a: int, b: int) -> tuple[int, int]:
    """Return (a+b, a*b)."""
    return add(a, b), multiply(a, b)
```

**`src/calc/_core.c`**

```c
/*
 * _core.c — just-buildit mixed pure/platform example.
 *
 * Exports: calc._core.add(a, b) -> int
 *          calc._core.multiply(a, b) -> int
 */

#define PY_SSIZE_T_CLEAN
#include <Python.h>

static PyObject *
core_add(PyObject *self, PyObject *args)
{
    long a, b;
    if (!PyArg_ParseTuple(args, "ll", &a, &b))
        return NULL;
    return PyLong_FromLong(a + b);
}

static PyObject *
core_multiply(PyObject *self, PyObject *args)
{
    long a, b;
    if (!PyArg_ParseTuple(args, "ll", &a, &b))
        return NULL;
    return PyLong_FromLong(a * b);
}

static PyMethodDef CoreMethods[] = {
    {"add",      core_add,      METH_VARARGS, "Add two integers."},
    {"multiply", core_multiply, METH_VARARGS, "Multiply two integers."},
    {NULL, NULL, 0, NULL}
};

static struct PyModuleDef coremodule = {
    PyModuleDef_HEAD_INIT, "_core", NULL, -1, CoreMethods
};

PyMODINIT_FUNC
PyInit__core(void) { return PyModule_Create(&coremodule); }
```

______________________________________________________________________

## Nested packages with multiple extensions

A package (`imagelib`) with C extensions nested at multiple directory levels.
The Makefile mirrors the source tree under `$JUST_BUILDIT_OUTPUT_DIR` —
just-buildit packages the directory verbatim.

**Requires:** `make`, C compiler

[Browse `examples/nested/`](https://github.com/just-buildit/just-buildit/tree/main/examples/nested)

```sh
pip install ./examples/nested
python -c "from imagelib import blur, encode; print(blur(100), encode(10))"
```

**Layout**

```
src/imagelib/
    __init__.py
    filters/
        __init__.py
        _blur.c
    codec/
        __init__.py
        _encode.c
```

**`pyproject.toml`**

```toml
[build-system]
requires = ["just-buildit"]
build-backend = "just_buildit"

[project]
name = "imagelib"
version = "0.1.0"
description = "just-buildit nested recursive package example."
requires-python = ">=3.8"

[tool.just-buildit]
command = "make"
repair = false
```

**`Makefile`**

```makefile
OUT := $(JUST_BUILDIT_OUTPUT_DIR)
EXT := $(JUST_BUILDIT_EXT_SUFFIX)
CC_EXT = $(CC) $(JUST_BUILDIT_LDFLAGS) -I$(JUST_BUILDIT_INCLUDE_DIR) $< -o $@ $(JUST_BUILDIT_LIBS)

EXTS := \
	$(OUT)/imagelib/filters/_blur$(EXT) \
	$(OUT)/imagelib/codec/_encode$(EXT)

all: $(EXTS)
	find src/imagelib -name "*.py" | while read f; do \
		dest=$(OUT)/$${f#src/}; \
		mkdir -p $$(dirname $$dest); \
		cp $$f $$dest; \
	done

$(OUT)/imagelib/filters/_blur$(EXT): src/imagelib/filters/_blur.c | $(OUT)/imagelib/filters
	$(CC_EXT)

$(OUT)/imagelib/codec/_encode$(EXT): src/imagelib/codec/_encode.c | $(OUT)/imagelib/codec
	$(CC_EXT)

$(OUT)/imagelib/filters $(OUT)/imagelib/codec:
	mkdir -p $@

clean:
	rm -f src/imagelib/filters/_blur*.so src/imagelib/filters/_blur*.pyd
	rm -f src/imagelib/codec/_encode*.so src/imagelib/codec/_encode*.pyd
```

______________________________________________________________________

## Windows (clang-cl)

An explicit Makefile build with clang-cl against native CPython (the MSVC
ABI). The key difference from Linux: `JUST_BUILDIT_LIBS` is non-empty on
Windows — it is the path to `python3X.lib` — and, being an input file, goes
**after** the sources. `JUST_BUILDIT_LDFLAGS` is `/LD`, MSVC's spelling of
"build a DLL", so the compiler line uses MSVC's `/Fe:` and `/Fo` too. On
Linux and macOS `JUST_BUILDIT_LIBS` is empty and the rule is a no-op either
way.

[Browse `examples/clang-cl/`](https://github.com/just-buildit/just-buildit/tree/main/examples/clang-cl)

**Prerequisites:**

- Visual Studio Build Tools with the C++ workload, and LLVM (`clang-cl`)
- CPython from python.org or `uv python install` (not MSYS2's Python)
- GNU `make` on `PATH`

Run from an environment where clang-cl can find the MSVC toolchain, such as
a Developer Command Prompt.

**Try it:**

```sh
pip install ./examples/clang-cl
python -c "import add; print(add.add(1, 2))"
```

**`pyproject.toml`**

```toml
[build-system]
requires = ["just-buildit"]
build-backend = "just_buildit"

[project]
name = "add"
version = "0.1.0"
description = "just-buildit Windows clang-cl example."
requires-python = ">=3.8"

[tool.just-buildit]
command = "make"
repair = false
```

**`Makefile`**

```makefile
# Windows: clang-cl against native CPython (the MSVC ABI). Run it from an
# environment where clang-cl can find the MSVC toolchain (a Developer
# Command Prompt, or scripts/msvc-env.sh on a CI runner).
#
# make's built-in CC is `cc`, which is not on a Windows PATH; an environment
# CC still wins, so only the built-in default is replaced.
ifeq ($(origin CC),default)
CC := clang-cl
endif

TARGET := $(JUST_BUILDIT_OUTPUT_DIR)/add$(JUST_BUILDIT_EXT_SUFFIX)
OBJDIR := build

all: $(TARGET)

# clang-cl takes MSVC's spellings: /LD builds a DLL (JUST_BUILDIT_LDFLAGS),
# /Fe: names the output and /Fo the object directory. JUST_BUILDIT_LIBS is
# the path to python3X.lib; it is an ordinary input file, so it goes after
# the sources. /LD also writes add*.lib and add*.exp beside the output;
# just-buildit removes those before packaging, so they need no handling here.
$(TARGET):
	mkdir -p $(OBJDIR)
	$(CC) $(JUST_BUILDIT_LDFLAGS) \
		-I$(JUST_BUILDIT_INCLUDE_DIR) \
		src/add/add.c \
		/Fo$(OBJDIR)/ \
		/Fe:$(TARGET) \
		$(JUST_BUILDIT_LIBS)

clean:
	rm -rf $(OBJDIR) src/add/add*.pyd
```

**`src/add/add.c`** — same as the zero-config example above.

**Wheel repair on Windows**

For distribution, set `repair = true` (or omit it) and install `delvewheel`:

```sh
pip install delvewheel
```

just-buildit auto-detects `uvx delvewheel repair` on Windows and bundles
the required DLLs into the wheel.

______________________________________________________________________

## Bazel

A `build_ext.py` script bridges just-buildit and Bazel, forwarding
environment variables into the build via `--action_env`.

**Requires:** [Bazel](https://bazel.build/install), C compiler

[Browse `examples/bazel/`](https://github.com/just-buildit/just-buildit/tree/main/examples/bazel)

```sh
pip install ./examples/bazel
python -c "import greeter; print(greeter.greet('world'))"
```

**`pyproject.toml`**

```toml
[build-system]
requires = ["just-buildit"]
build-backend = "just_buildit"

[project]
name = "greeter"
version = "0.1.0"
description = "just-buildit Bazel example."
requires-python = ">=3.8"

[tool.just-buildit]
command = "python build_ext.py"
repair = false
```

**`build_ext.py`**

```python
import os
import shutil
import subprocess
from pathlib import Path

out = Path(os.environ["JUST_BUILDIT_OUTPUT_DIR"])
name = os.environ["JUST_BUILDIT_NAME"]
ext_suffix = os.environ["JUST_BUILDIT_EXT_SUFFIX"]

cc = shutil.which("cc") or shutil.which("gcc") or shutil.which("clang") or "cc"

subprocess.run(
    [
        "bazel", "build", "//:greeter_so",
        f"--action_env=CC={cc}",
        f"--action_env=JUST_BUILDIT_INCLUDE_DIR={os.environ['JUST_BUILDIT_INCLUDE_DIR']}",
        f"--action_env=JUST_BUILDIT_LDFLAGS={os.environ['JUST_BUILDIT_LDFLAGS']}",
        f"--action_env=JUST_BUILDIT_LIBS={os.environ.get('JUST_BUILDIT_LIBS', '')}",
    ],
    check=True,
)

shutil.copy2("bazel-bin/greeter.so", out / (name + ext_suffix))
```

**`BUILD.bazel`**

```python
genrule(
    name = "greeter_so",
    srcs = ["src/greeter.c"],
    outs = ["greeter.so"],
    cmd = """
        $$CC $$JUST_BUILDIT_LDFLAGS \
            -I$$JUST_BUILDIT_INCLUDE_DIR \
            $(location src/greeter.c) \
            -o $@ \
            $$JUST_BUILDIT_LIBS
    """,
)
```

**`src/greeter.c`**

```c
/*
 * greeter.c — just-buildit Bazel example.
 *
 * Exports: greeter.greet(name) -> str
 */

#define PY_SSIZE_T_CLEAN
#include <Python.h>
#include <stdio.h>

static PyObject *
greeter_greet(PyObject *self, PyObject *args)
{
    const char *name;
    if (!PyArg_ParseTuple(args, "s", &name))
        return NULL;
    char buf[256];
    snprintf(buf, sizeof(buf), "Hello, %s!", name);
    return PyUnicode_FromString(buf);
}

static PyMethodDef GreeterMethods[] = {
    {"greet", greeter_greet, METH_VARARGS, "Greet by name."},
    {NULL, NULL, 0, NULL}
};

static struct PyModuleDef greetermodule = {
    PyModuleDef_HEAD_INIT, "greeter", NULL, -1, GreeterMethods
};

PyMODINIT_FUNC
PyInit_greeter(void) { return PyModule_Create(&greetermodule); }
```

For pre-built `.so` files from a Bazel C++ rule (e.g. nanobind), the same
pattern applies: `build_ext.py` runs the Bazel target and copies the output
into `$JUST_BUILDIT_OUTPUT_DIR`, renaming with `$JUST_BUILDIT_EXT_SUFFIX`.

______________________________________________________________________

## Scaffolding with just-makeit

No build system yet? [just-makeit](https://github.com/just-buildit/just-makeit) generates a complete CMake-based C extension project that wires up just-buildit out of the box — no configuration needed.

**Requires:** `cmake` ≥ 3.16, C99 compiler, NumPy

```sh
pip install just-makeit
just-makeit new my_dsp --object gain --state gain:double:1.0
cd my_dsp
pip install .
```

The generated layout:

```
my_dsp/
  just-makeit.toml            # project config — single source of truth
  CMakeLists.txt
  Makefile
  pyproject.toml              # just-buildit backend, command = "make just-build"
  README.md
  Doxyfile                    # Doxygen config (pre-configured)
  zensical.toml               # docs scaffolding
  compile_commands.json       # clangd / IDE support
  cmake/
    my-dsp.pc.in              # pkg-config template
    my_dsp-config.cmake.in    # CMake find_package support
  docs/
    index.md
    api.md
  native/
    inc/
      clib_common.h           # shared C types
      pyex_common.h           # Python extension helpers
      my_dsp.h                # umbrella header
      gain/
        gain_core.h           # C API (state struct, create/destroy/step/reset)
    src/
      my_dsp_lib.c            # library version stub
      gain/
        gain_core.c           # algorithm  ← implement step() here
        gain_ext.c            # Python binding  ← do not edit
        CMakeLists.txt
    tests/
      test_gain_core.c        # CTest lifecycle test
    benchmarks/
      bench_gain_core.c       # C timing benchmark
      jm_bench.h              # header-only bench stats library
  benchmarks/
    history/                  # dated JSON snapshots (git-ignored locally)
  src/my_dsp/
    __init__.py
    gain.pyi                  # type stub (regenerated on every mutation)
    tests/
      __init__.py
      test_gain.py            # pytest suite
    benchmarks/
      __init__.py
      bench_gain.py           # Python throughput benchmark
```

The generated `pyproject.toml` uses just-buildit with no extra work:

```toml
[build-system]
requires = ["just-buildit", "numpy"]
build-backend = "just_buildit"

[tool.just-buildit]
command = "make just-build"
```

Add a new object at any time with `just-makeit object <name>`. Add state
variables to an existing object with `just-makeit add --state name:type[:default]`. just-buildit remains agnostic to how many objects
exist — it packages whatever `make just-build` writes to
`$JUST_BUILDIT_OUTPUT_DIR`.

Use `just-makeit apply` to materialise a project from a TOML manifest
alone — useful for CI templates and composing projects declaratively. See
the [just-makeit docs](https://just-buildit.github.io/just-makeit/) for
the full reference.
