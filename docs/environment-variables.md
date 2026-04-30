# Environment variables

just-buildit sets these before calling your command:

| Variable | Example value |
|---|---|
| `JUST_BUILDIT_NAME` | `mylib` |
| `JUST_BUILDIT_PYTHON` | `/usr/bin/python3.12` |
| `JUST_BUILDIT_INCLUDE_DIR` | `/usr/include/python3.12` |
| `JUST_BUILDIT_OUTPUT_DIR` | `/tmp/just-buildit-xyz/output` |
| `JUST_BUILDIT_EXT_SUFFIX` | `.cpython-312-x86_64-linux-gnu.so` |

| Variable | Linux | macOS | Windows (MinGW) |
|---|---|---|---|
| `JUST_BUILDIT_LDFLAGS` | `-shared -fPIC` | `-dynamiclib -undefined dynamic_lookup` | `-shared -fPIC` |
| `JUST_BUILDIT_LIBS` | — | — | `-L/ucrt64/lib -lpython3.14` |

`$JUST_BUILDIT_OUTPUT_DIR` is the wheel content root. Write everything your
wheel needs there — extensions, Python sources, data files. just-buildit
packages the entire directory verbatim, preserving structure.
