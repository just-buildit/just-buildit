# Configuration

## Full reference

```toml
[tool.just-build]
command       = "make"        # optional — omit for zero-config src/{package}/ build
package       = "my_package"  # optional — package dir name when it differs from project name
editable_path = "src"         # optional — src root for fast .pth-file editable installs
repair        = "uvx ..."     # optional — auto-detected by platform, or false to skip
exclude = [                   # optional — glob patterns relative to $JUST_BUILD_OUTPUT_DIR
    "mypkg/tests/**",
    "mypkg/bench/**",
]
```

`__pycache__/`, `*.pyc`, and `*.pyo` are always excluded.

---

## Wheel repair

just-build automatically runs the right repair tool for your platform:

| Platform | Tool |
|---|---|
| Linux | `uvx auditwheel repair` |
| macOS | `uvx --from delocate delocate-wheel` |
| Windows / MinGW | `uvx delvewheel repair` |

Override or disable repair in your config:

```toml
[tool.just-build]
command = "make"
repair = "uvx auditwheel repair --plat manylinux_2_28_x86_64"  # custom
# repair = false  # skip entirely
```

---

## Editable installs

Set `editable_path` to the directory that should be added to `sys.path`:

```toml
[tool.just-build]
command       = "make"
editable_path = "src"
```

`pip install -e .` then installs a single `.pth` file pointing at `src/` —
no build command is run. Python finds your source directly. The C extension
must be compiled in place once (e.g. `make`) before importing.

Without `editable_path`, `pip install -e .` falls back to a full wheel build.
