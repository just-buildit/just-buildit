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
