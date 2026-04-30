# Examples

## Makefile

```toml
[tool.just-buildit]
command = "make"
```

```makefile
TARGET := $(JUST_BUILDIT_OUTPUT_DIR)/$(JUST_BUILDIT_NAME)$(JUST_BUILDIT_EXT_SUFFIX)

all: $(TARGET)

$(TARGET):
	$(CC) $(JUST_BUILDIT_LDFLAGS) \
		-I$(JUST_BUILDIT_INCLUDE_DIR) \
		src/mylib/mylib.c \
		-o $(TARGET) \
		$(JUST_BUILDIT_LIBS)
```

---

## CMake

```toml
[tool.just-buildit]
command = "make pyext"
```

```makefile
pyext:
	cmake -B _build -DPython3_EXECUTABLE=$(JUST_BUILDIT_PYTHON)
	cmake --build _build --target mylib
	find _build -maxdepth 3 -name "$(JUST_BUILDIT_NAME)$(JUST_BUILDIT_EXT_SUFFIX)" \
		-exec cp {} $(JUST_BUILDIT_OUTPUT_DIR)/ \;

.PHONY: pyext
```

```cmake
# CMakeLists.txt
cmake_minimum_required(VERSION 3.15)
project(mylib C)
find_package(Python3 COMPONENTS Development.Module REQUIRED)
Python3_add_library(mylib MODULE src/mylib.c)
set_target_properties(mylib PROPERTIES
    OUTPUT_NAME "$ENV{JUST_BUILDIT_NAME}"
    SUFFIX      "$ENV{JUST_BUILDIT_EXT_SUFFIX}"
    PREFIX      "")
```

---

## Meson

```toml
[tool.just-buildit]
command = "make pyext"
```

```makefile
pyext:
	meson setup _build --reconfigure -Dbuildtype=release
	meson compile -C _build
	find _build -name "*$(JUST_BUILDIT_EXT_SUFFIX)" \
		-exec cp {} $(JUST_BUILDIT_OUTPUT_DIR)/ \;
```

```python
# meson.build
project('mylib', 'c')
py = import('python').find_installation()
py.extension_module('mylib', 'src/mylib.c', install: false)
```

---

## Mixed pure Python + C extension

A package with a Python API wrapping a C core:

```
src/mylib/
    __init__.py      # pure Python
    utils.py         # pure Python
    _core.c          # C extension
```

```toml
[tool.just-buildit]
command = "make"
```

```makefile
EXT := $(JUST_BUILDIT_OUTPUT_DIR)/mylib/_core$(JUST_BUILDIT_EXT_SUFFIX)

all: $(EXT)
	cp src/mylib/*.py $(JUST_BUILDIT_OUTPUT_DIR)/mylib/

$(EXT):
	mkdir -p $(JUST_BUILDIT_OUTPUT_DIR)/mylib
	$(CC) $(JUST_BUILDIT_LDFLAGS) \
		-I$(JUST_BUILDIT_INCLUDE_DIR) \
		src/mylib/_core.c \
		-o $(EXT) \
		$(JUST_BUILDIT_LIBS)
```

`import mylib` loads the Python package; `mylib._core` is the compiled
extension — both land in the wheel from a single `$JUST_BUILDIT_OUTPUT_DIR`.

---

## Bazel

A `build_ext.py` script bridges just-buildit and Bazel, forwarding the
just-buildit environment variables into the build via `--action_env`:

```toml
[tool.just-buildit]
command = "python build_ext.py"
```

```python
# build_ext.py
import os, shutil, subprocess
from pathlib import Path

out = Path(os.environ["JUST_BUILDIT_OUTPUT_DIR"])
name = os.environ["JUST_BUILDIT_NAME"]
ext_suffix = os.environ["JUST_BUILDIT_EXT_SUFFIX"]
cc = shutil.which("cc") or shutil.which("gcc") or shutil.which("clang") or "cc"

subprocess.run(
    [
        "bazel", "build", "//:mylib_so",
        f"--action_env=CC={cc}",
        f"--action_env=JUST_BUILDIT_INCLUDE_DIR={os.environ['JUST_BUILDIT_INCLUDE_DIR']}",
        f"--action_env=JUST_BUILDIT_LDFLAGS={os.environ['JUST_BUILDIT_LDFLAGS']}",
        f"--action_env=JUST_BUILDIT_LIBS={os.environ.get('JUST_BUILDIT_LIBS', '')}",
    ],
    check=True,
)

shutil.copy2("bazel-bin/mylib.so", out / (name + ext_suffix))
```

```python
# BUILD.bazel
genrule(
    name = "mylib_so",
    srcs = ["src/mylib.c"],
    outs = ["mylib.so"],
    cmd = """
        $$CC $$JUST_BUILDIT_LDFLAGS \
            -I$$JUST_BUILDIT_INCLUDE_DIR \
            $(location src/mylib.c) \
            -o $@ \
            $$JUST_BUILDIT_LIBS
    """,
)
```

For pre-built `.so` files produced by a Bazel C++ rule (e.g. nanobind), the
same pattern applies: `build_ext.py` runs the Bazel target and copies the
output into `$JUST_BUILDIT_OUTPUT_DIR`, renaming with `$JUST_BUILDIT_EXT_SUFFIX`.

---

## Recursive package tree with multiple extensions

A larger package with extensions nested at multiple levels:

```
src/mylib/
    __init__.py
    filters/
        __init__.py
        _blur.c
        _sharpen.c
    codec/
        __init__.py
        _encode.c
```

```toml
[tool.just-buildit]
command = "make"
```

```makefile
OUT := $(JUST_BUILDIT_OUTPUT_DIR)
EXT := $(JUST_BUILDIT_EXT_SUFFIX)
CC_EXT = $(CC) $(JUST_BUILDIT_LDFLAGS) -I$(JUST_BUILDIT_INCLUDE_DIR) $< -o $@ $(JUST_BUILDIT_LIBS)

EXTS := \
    $(OUT)/mylib/filters/_blur$(EXT) \
    $(OUT)/mylib/filters/_sharpen$(EXT) \
    $(OUT)/mylib/codec/_encode$(EXT)

all: $(EXTS)
	find src/mylib -name "*.py" | while read f; do \
	    dest=$(OUT)/$${f#src/}; \
	    mkdir -p $$(dirname $$dest); \
	    cp $$f $$dest; \
	done

$(OUT)/mylib/filters/_blur$(EXT): src/mylib/filters/_blur.c | $(OUT)/mylib/filters
	$(CC_EXT)

$(OUT)/mylib/filters/_sharpen$(EXT): src/mylib/filters/_sharpen.c | $(OUT)/mylib/filters
	$(CC_EXT)

$(OUT)/mylib/codec/_encode$(EXT): src/mylib/codec/_encode.c | $(OUT)/mylib/codec
	$(CC_EXT)

$(OUT)/mylib/filters $(OUT)/mylib/codec:
	mkdir -p $@
```

The key: mirror your source tree under `$JUST_BUILDIT_OUTPUT_DIR`. just-buildit packages the directory verbatim, so any layout that works at runtime works in the wheel.
