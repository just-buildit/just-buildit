# Environment variables

## Variables set by just-buildit

just-buildit sets these before calling your build command:

| Variable                   | Example value                      | Purpose                                                           |
| -------------------------- | ---------------------------------- | ----------------------------------------------------------------- |
| `JUST_BUILDIT_NAME`        | `mylib`                            | Normalized package name — use as the base of your output filename |
| `JUST_BUILDIT_PYTHON`      | `/usr/bin/python3.12`              | Absolute path to the Python interpreter running the build         |
| `JUST_BUILDIT_INCLUDE_DIR` | `/usr/include/python3.12`          | Python header directory — pass as `-I$JUST_BUILDIT_INCLUDE_DIR`   |
| `JUST_BUILDIT_OUTPUT_DIR`  | `/tmp/just-buildit-xyz/output`     | **Wheel content root** — write all output here                    |
| `JUST_BUILDIT_EXT_SUFFIX`  | `.cpython-312-x86_64-linux-gnu.so` | Full platform extension suffix for `.so` / `.pyd` naming          |

!!! info "Output directory"

    `$JUST_BUILDIT_OUTPUT_DIR` is packaged verbatim into the wheel.
    Write every file your package needs there — extensions, pure-Python
    sources, data files — and preserve the directory structure you want
    users to import.

______________________________________________________________________

### Platform-specific link flags

| Variable               |      Linux      |                  macOS                  |             Windows (clang-cl)             |
| :--------------------- | :-------------: | :-------------------------------------: | :----------------------------------------: |
| `JUST_BUILDIT_LDFLAGS` | `-shared -fPIC` | `-dynamiclib -undefined dynamic_lookup` |                   `/LD`                    |
| `JUST_BUILDIT_LIBS`    |    *(empty)*    |                *(empty)*                | `C:/Python314/libs/python314.lib` (a path) |

`JUST_BUILDIT_LIBS` is only non-empty when a custom `command` is configured
**and** the platform is Windows — where Python's import library
(`python3X.lib`, from the native CPython install) must be linked explicitly.
On Linux and macOS it is always empty; `JUST_BUILDIT_LDFLAGS` is sufficient.

Windows builds use **clang-cl** against native CPython (the MSVC ABI), so the
flags are MSVC's (`/LD`, `/Fe:`, `/Fo`), not gcc's. just-buildit removes the
`.lib` and `.exp` files `/LD` leaves beside the extension, and any `.obj`,
before packaging. MinGW / MSYS2 Python is no longer supported.

!!! warning "Link order on Linux and macOS"

    Always place `$JUST_BUILDIT_LIBS` **after** the output file (`-o`) in
    your linker invocation:

    ```makefile
    # CORRECT — library after the object file
    $(CC) $(JUST_BUILDIT_LDFLAGS) -I$(JUST_BUILDIT_INCLUDE_DIR) \
        src/mylib.c -o $(TARGET) $(JUST_BUILDIT_LIBS)

    # WRONG — library before the object file (ld drops it silently)
    $(CC) $(JUST_BUILDIT_LDFLAGS) $(JUST_BUILDIT_LIBS) \
        -I$(JUST_BUILDIT_INCLUDE_DIR) src/mylib.c -o $(TARGET)
    ```

    GNU `ld` uses `--as-needed` by default on Debian/Ubuntu; any library
    that appears before the object files that reference it is silently
    dropped. This is a no-op on Linux/macOS (where `JUST_BUILDIT_LIBS` is
    empty anyway), but the ordering habit matters on Windows.

______________________________________________________________________

## Variables read by just-buildit

These are **not** set by just-buildit — they are read from the environment
if already present.

| Variable            |           Default            | Effect                                                      |
| :------------------ | :--------------------------: | ----------------------------------------------------------- |
| `CC`                |             `cc`             | C compiler for zero-config builds (no `command` set)        |
| `SOURCE_DATE_EPOCH` | `315532800` (1980-01-01 UTC) | Unix timestamp clamped into wheel and sdist archive entries |

!!! tip "Selecting the C compiler"

    Override `CC` to use a specific compiler without changing any config:

    ```sh
    CC=gcc pip install .
    CC=clang pip install .
    ```

    This only affects **zero-config** builds (no `command` in
    `[tool.just-buildit]`). Custom-command builds receive no `CC` injection —
    your Makefile or CMake handles compiler selection directly.

!!! info "Reproducible builds"

    Wheel and sdist archive entries already default to a fixed timestamp
    (1980-01-01 UTC, the zip/tar format minimum), so builds are
    byte-for-byte reproducible without any configuration. Set
    `SOURCE_DATE_EPOCH` to pin a different fixed timestamp instead — for
    example, your project's last-commit time:

    ```sh
    SOURCE_DATE_EPOCH=1700000000 pip wheel .
    ```

    This follows the [Reproducible Builds](https://reproducible-builds.org/docs/source-date-epoch/)
    standard and is respected by most build backends and archive tools.
    Both `pip wheel` and `python -m build` propagate it automatically when
    they detect it in the environment.
