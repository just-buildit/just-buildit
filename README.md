<p align="center">
  <img src="docs/assets/logo-wordmark.svg" alt="just-buildit" width="540">
</p>

[![CI](https://github.com/just-buildit/just-buildit/actions/workflows/ci.yml/badge.svg)](https://github.com/just-buildit/just-buildit/actions/workflows/ci.yml)
[![Docs](https://github.com/just-buildit/just-buildit/actions/workflows/docs.yml/badge.svg)](https://github.com/just-buildit/just-buildit/actions/workflows/docs.yml)

The missing [PEP 517](https://peps.python.org/pep-0517/) build backend for C extensions.

You know how to build your project. just-buildit knows how to package it.
That's the whole deal.

---

## The problem

Every existing Python build backend either wants to own your build system,
assumes you're using setuptools extensions, or drags in a dependency tree
bigger than your project. There's no option that just says:

> "Here are your C files. Build them however you want. I'll ship the result."

just-buildit is that option.

---

## Quickstart

Flat layouts, nested packages, multiple extensions across subdirectories, mixed pure Python and C — whatever your build produces.

**Zero config** — a single C extension in `src/mylib/`:

```toml
[build-system]
requires = ["just-buildit"]
build-backend = "just_buildit"

[project]
name = "mylib"
version = "0.1.0"
```

Run `pip install .` and just-buildit finds `src/mylib/`, compiles every `.c`
file it contains, and ships the result.

**Custom build command** — Make, CMake, Meson, Bazel, or anything else:

```toml
[tool.just-buildit]
command = "make"
```

just-buildit sets environment variables, calls your command, and packages
everything written to `$JUST_BUILDIT_OUTPUT_DIR`.

### CLI

```sh
uvx just-buildit inspect   # dry-run: show config and what would be built
uvx just-buildit build     # build wheel into dist/
uvx just-buildit sdist     # build source distribution into dist/
```

---

## Documentation

| | |
|---|---|
| [Environment variables](docs/environment-variables.md) | What just-buildit sets before calling your command |
| [Examples](docs/examples.md) | Make, CMake, Meson, Bazel, mixed Python + C, nested packages |
| [Configuration](docs/configuration.md) | Full config reference, wheel repair, editable installs |
| [Contributing](docs/contributing.md) | Running tests, platform support, bootstrapping |

---

## Requirements

- Python 3.11+
- A compiler (you already have one)
- `uv` for wheel repair (`uvx auditwheel` / `uvx delocate-wheel` / `uvx delvewheel`)

---

## License

MIT
