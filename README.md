<p align="center">
  <img src="docs/assets/logo-wordmark.svg" alt="just-build" width="480">
</p>

The missing [PEP 517](https://peps.python.org/pep-0517/) build backend for C extensions.

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

## Quickstart

Got a single C extension in `src/mylib/`? No configuration needed:

```toml
[build-system]
requires = ["just-buildit"]
build-backend = "just_build"

[project]
name = "mylib"
version = "0.1.0"
```

Run `pip install .` and just-build finds `src/mylib/`, compiles every `.c`
file it contains, and ships the result.

For anything more complex, point it at your build command:

```toml
[tool.just-build]
command = "make"
```

just-build sets environment variables, calls your command, packages everything
written to `$JUST_BUILD_OUTPUT_DIR`, and ships the result.

---

## Documentation

| | |
|---|---|
| [Environment variables](docs/environment-variables.md) | What just-build sets before calling your command |
| [Examples](docs/examples.md) | Makefile, CMake, Meson, mixed Python + C |
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
