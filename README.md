<p align="center">
  <img src="https://raw.githubusercontent.com/just-buildit/just-buildit/main/docs/assets/logo-wordmark.png" alt="just-buildit" width="540">
</p>

[![CI](https://github.com/just-buildit/just-buildit/actions/workflows/ci.yml/badge.svg)](https://github.com/just-buildit/just-buildit/actions/workflows/ci.yml)
[![Docs](https://github.com/just-buildit/just-buildit/actions/workflows/docs.yml/badge.svg)](https://github.com/just-buildit/just-buildit/actions/workflows/docs.yml)

The missing [PEP 517](https://peps.python.org/pep-0517/) build backend for C extensions.

You know how to build your project. just-buildit knows how to package it.
That's the whole deal.

______________________________________________________________________

## The problem

Every existing Python build backend either wants to own your build system,
assumes you're using setuptools extensions, or drags in a dependency tree
bigger than your project. There's no option that just says:

> "Here are your C files. Build them however you want. I'll ship the result."

just-buildit is that option.

______________________________________________________________________

## Installation

```sh
pip install just-buildit
```

______________________________________________________________________

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

Need a project scaffold? [just-makeit](https://github.com/just-buildit/just-makeit) generates a CMake-based C extension project pre-wired for just-buildit — see the [examples](https://just-buildit.github.io/just-buildit/examples/#scaffolding-with-just-makeit).

### CLI

```sh
uvx just-buildit inspect   # dry-run: show config and what would be built
uvx just-buildit build     # build wheel into dist/
uvx just-buildit sdist     # build source distribution into dist/

# The version numbers CI cannot read out of a file once the version is
# derived, because there is no longer a file carrying one:
uvx just-buildit --current-version # -> 1.1.4.dev5  (what this tree builds as)
uvx just-buildit --next-version    # -> 1.1.4       (what a release would tag)
```

______________________________________________________________________

## Documentation

|                                                                                             |                                                              |
| ------------------------------------------------------------------------------------------- | ------------------------------------------------------------ |
| [Environment variables](https://just-buildit.github.io/just-buildit/environment-variables/) | What just-buildit sets before calling your command           |
| [Examples](https://just-buildit.github.io/just-buildit/examples/)                           | Make, CMake, Meson, Bazel, mixed Python + C, nested packages |
| [Configuration](https://just-buildit.github.io/just-buildit/configuration/)                 | Full config reference, wheel repair, editable installs       |
| [Contributing](https://just-buildit.github.io/just-buildit/contributing/)                   | Running tests, platform support, bootstrapping               |

______________________________________________________________________

## Requirements

- Python 3.8+
- A compiler (you already have one)
- `uv` for wheel repair (`uvx auditwheel` / `uvx delocate-wheel` / `uvx delvewheel`)

______________________________________________________________________

## Authors

Matthew T. Hunter, Ph.D. and [Claude Code](https://claude.ai/code)

______________________________________________________________________

## License

MIT
