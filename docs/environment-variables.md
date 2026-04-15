# Environment variables

just-buildit sets these before calling your command:

| Variable | Example value |
|---|---|
| `JUST_BUILDIT_NAME` | `mylib` |
| `JUST_BUILDIT_PYTHON` | `/usr/bin/python3.12` |
| `JUST_BUILDIT_INCLUDE_DIR` | `/usr/include/python3.12` |
| `JUST_BUILDIT_OUTPUT_DIR` | `/tmp/just-build-xyz/output` |
| `JUST_BUILDIT_EXT_SUFFIX` | `.cpython-312-x86_64-linux-gnu.so` |
| `JUST_BUILDIT_LDFLAGS` | `-shared -fPIC` (Linux) / `-dynamiclib -undefined dynamic_lookup` (macOS) |
| `JUST_BUILDIT_LIBS` | `` (Linux/macOS) / `-L/ucrt64/lib -lpython3.14` (Windows/MinGW) |

`$JUST_BUILDIT_OUTPUT_DIR` is the wheel content root. Write everything your
wheel needs there — extensions, Python sources, data files. just-buildit
packages the entire directory verbatim, preserving structure.
