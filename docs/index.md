# just-buildit

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

Need a project scaffold? [just-makeit](https://github.com/just-buildit/just-makeit) generates a CMake-based C extension project pre-wired for just-buildit — see the [examples](examples.md#scaffolding-with-just-makeit).

### CLI

```sh
uvx just-buildit inspect   # dry-run: show config and what would be built
uvx just-buildit build     # build wheel into dist/
uvx just-buildit sdist     # build source distribution into dist/

# For a project deriving its version from git tags, the number CI cannot
# read out of a file, because there is no longer a file carrying it:
uvx just-buildit --next-version   # -> 1.1.4  (the tag a release would push)
```

______________________________________________________________________

## Requirements

- Python 3.8+
- A compiler (you already have one)
- `uv` for wheel repair (`uvx auditwheel` / `uvx delocate-wheel` / `uvx delvewheel`)
