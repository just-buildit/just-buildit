# Configuration

## Full reference

```toml
[tool.just-buildit]
command       = "make"        # optional — omit for zero-config src/{package}/ build
pure          = true          # optional — pure-Python: copy src/{package}/ verbatim, compile nothing
package       = "my_package"  # optional — package dir; defaults to normalized project name
editable_path = "src"         # optional — src root for .pth editable installs; auto-detected as src/ if present
repair        = "uvx ..."     # optional — auto-detected by platform, or false to skip
repair-args   = ["--plat", "manylinux_2_28_x86_64"]  # optional — extra args appended to the repair command
version-from  = "vcs"         # optional — derive [project] version; requires dynamic = ["version"]
exclude = [                   # optional — glob patterns relative to $JUST_BUILDIT_OUTPUT_DIR
    "mypkg/tests/**",
    "mypkg/bench/**",
]
```

`__pycache__/`, `*.pyc`, and `*.pyo` are always excluded.

!!! note "Package directory name"

    If `package` is omitted, the directory name is derived from
    `[project] name` by replacing runs of non-alphanumeric characters with
    underscores and lower-casing — the same rule Python uses for import
    names. A project named `my-lib` will look for `src/my_lib/`.

!!! info "`.c` and `.h` files in the wheel"

    In a normal (non-`pure`) build, `.c` and `.h` files are **excluded from
    the wheel** — they compile into the extension and have no place in the
    distribution.

    Set `pure = true` to keep them as package data (useful when shipping C
    source templates or scaffolding examples alongside Python code).

______________________________________________________________________

## Deriving the version

`[project] version` may be **derived at build time** instead of written as a
literal. List it in PEP 621's `dynamic` and name a source:

```toml
[project]
name = "my_package"
dynamic = ["version"]

[tool.just-buildit]
version-from = "vcs"
```

The point is to remove the version as a *tracked file*. A package index refuses
a duplicate filename, so a re-used version is a rejected upload — with a
literal, every PR has to bump it, and any two open PRs conflict on every file
that carries a copy, whatever they actually changed.

### Where the value comes from

`version-from = "vcs"` is currently the only source. It resolves in two steps:

1. **A sibling `PKG-INFO`.** Its presence means the tree is an unpacked sdist,
    and the version recorded in it is that artifact's identity.
1. **`git describe`** against the nearest `v*` tag.

| git state                   | version                     |
| --------------------------- | --------------------------- |
| exactly on tag `v1.1.3`     | `1.1.3`                     |
| 5 commits past it           | `1.1.4.dev5`                |
| 5 commits past `v1.1.3-rc1` | `1.1.3rc2.dev5`             |
| unpacked sdist, no `.git`   | whatever `PKG-INFO` records |

Commits past a tag name the release they are working **toward**, never the one
already made. Each derived version therefore sorts strictly after the tag it
followed and strictly before the release it anticipates, which is what makes a
stream of dev builds usable on an index.

`PKG-INFO` is checked **first**, and that ordering is what closes the loop: an
sdist built from a checkout carries a concrete number, so the wheel built from
that sdist agrees with it without needing a repository that is no longer there.
It also stops an sdist unpacked inside an unrelated checkout from picking up
that checkout's tags.

### Asking for the next version

Deriving the version removes it from every tracked file, which is the point —
and the reason CI then has nothing to read it out of. There is no
`[project] version` to grep and no file for a version check to probe, so a
release job needs a way to ask:

```bash
just-buildit --next-version      # -> 1.1.4
```

It prints the version the **next release** would carry, and nothing else, so
it can be captured directly:

```bash
VERSION=$(just-buildit --next-version)
git tag "v$VERSION" && git push origin "v$VERSION"
```

This invents no policy. A build five commits past `v1.1.3` is already called
`1.1.4.dev5`, and `.devN` means "on the way to" — so that build already names
1.1.4 as the next release. The query reports the same number with the `.devN`
removed, from the same parse of the same tag.

| git state                  | build version   | `--next-version` |
| -------------------------- | --------------- | ---------------- |
| exactly on tag `v1.1.3`    | `1.1.3`         | `1.1.4`          |
| 1 commit past it           | `1.1.4.dev1`    | `1.1.4`          |
| 5 commits past it          | `1.1.4.dev5`    | `1.1.4`          |
| exactly on `v1.1.3rc1`     | `1.1.3rc1`      | `1.1.3rc2`       |
| 3 commits past `v1.1.3rc1` | `1.1.3rc2.dev3` | `1.1.3rc2`       |

The answer does not change as commits land — only how far along the dev
builds are — so it is stable to read at any point in a release branch's life.

It **refuses** rather than guesses in the two cases where there is no answer:

- **A literal `[project] version`.** There is no derivation scheme to report,
    and which digit the next release bumps is a judgement, not a fact about
    the repository — the same judgement `version-from` never makes for you.
- **No tag yet.** There is no next release to name until there is a first
    one. Unlike the build's own version, this deliberately does *not* fall
    back to a sibling `PKG-INFO`: "what comes next" is a question about a
    repository's history, and an sdist has neither tags nor a future.

Every diagnostic goes to stderr with a non-zero exit, so a failed query can
never be captured and pushed as a tag.

### Reaching an alpha, beta or release candidate

You **tag** it. The scheme derives; it never invents a pre-release phase,
because deciding "this is now an alpha" is a judgement no tool should make for
you. The tag is where that judgement is recorded, and everything after it
follows automatically:

```bash
git tag v1.1.3a1        # you decide this is the first alpha
```

| git state                 | version         |
| ------------------------- | --------------- |
| after `v1.1.2`, 5 commits | `1.1.3.dev5`    |
| on `v1.1.3a1`             | `1.1.3a1`       |
| 3 commits past it         | `1.1.3a2.dev3`  |
| on `v1.1.3rc1`            | `1.1.3rc1`      |
| 3 commits past it         | `1.1.3rc2.dev3` |
| on `v1.1.3`               | `1.1.3`         |

Those are strictly increasing under PEP 440, in that order. `b1`, `.post1` and
an epoch (`v1!2.3`) all behave the same way, and the number is bumped
numerically, so `a9` becomes `a10` rather than a lexical successor.

### Tag spelling does not matter

A tag is parsed with PEP 440's grammar, so every spelling the specification
makes equivalent gives the same version, and what just-buildit emits is always
the **canonical** form — it becomes a wheel filename and a requirement string,
so it must match what every other tool writes.

| tag                                      | version at +3 commits |
| ---------------------------------------- | --------------------- |
| `v1.1.3-rc1`, `v1.1.3_rc1`, `v1.1.3.rc1` | `1.1.3rc2.dev3`       |
| `v1.1.3alpha2`, `v1.1.3ALPHA2`           | `1.1.3a3.dev3`        |
| `v1.1.3c1`, `v1.1.3preview1`             | `1.1.3rc2.dev3`       |
| `v1.1.3.rev1`, `v1.1.3-1`                | `1.1.3.post2.dev3`    |
| `v1.1.3a` (numeral omitted, so `a0`)     | `1.1.3a1.dev3`        |
| `v1!2.3`                                 | `1!2.4.dev3`          |

A tag that is not a PEP 440 version at all is refused by name rather than
guessed at.

### Tags that cannot be a base

Two tag shapes are refused rather than derived from, because appending a commit
distance to them does not produce a usable version:

- **one already carrying `.dev`** — `v1.1.3.dev5` would give
    `1.1.3.dev6.dev2`, which is not a valid PEP 440 version at all.
- **one carrying a local `+` segment** — `v1.1.3+local` would give
    `1.1.4+local.dev3`, which *is* well-formed and is worse for it: the
    distance lands inside the local part, so every build past the tag compares
    equal on its public version, and PyPI refuses local versions outright.

Neither is a release tag, and the error names the offending tag rather than
reporting a missing one.

### When it cannot be determined

PEP 621 requires a back-end to raise an error if a field is listed in `dynamic`
and cannot be computed, so an untagged repository, a missing `git`, and a tree
that is neither a checkout nor an sdist are all build failures naming the two
ways out. There is deliberately no `0.0.0` placeholder: that would upload a
wrong version rather than fail.

Three further rules, also PEP 621's:

- `name` may never appear in `dynamic`.
- Giving `version` both statically **and** in `dynamic` is an error — pick one.
- A project that says nothing about `dynamic` behaves exactly as before, so a
    literal version is still perfectly good.

______________________________________________________________________

## Pure-Python packages

A zero-config build compiles every `.c` file it finds under
`src/{package}/`. That is wrong for a pure-Python package that *ships* `.c`
files as data (sample sources, test fixtures, scaffolding templates) — they
must land in the wheel untouched, not be handed to a compiler.

Set `pure = true` to tell just-buildit the package is pure Python:

```toml
[tool.just-buildit]
pure = true
```

With `pure = true`, just-buildit:

- compiles nothing — the `.c` scan is skipped entirely
- copies the whole `src/{package}/` tree verbatim into the wheel, **keeping**
    any `.c`/`.h` files as package data
- tags the wheel `py3-none-any` (`Root-Is-Purelib: true`)
- skips the wheel-repair step — a pure wheel has no native binary to repair

!!! failure "Cannot combine `pure` and `command`"

    Setting both is a configuration error:

    ```
    [tool.just-buildit] sets both 'pure' and 'command'.
    'pure' means compile nothing — drop 'command', or drop 'pure'.
    ```

    `pure` means "compile nothing and copy the source tree verbatim."
    A build `command` is only needed when there is something to compile.

______________________________________________________________________

## Wheel repair

just-buildit automatically runs the right repair tool for your platform:

| Platform            | Auto-detected command                |
| :------------------ | :----------------------------------- |
| **Linux**           | `uvx auditwheel repair`              |
| **macOS**           | `uvx --from delocate delocate-wheel` |
| **Windows / MinGW** | `uvx delvewheel repair`              |

Override or disable repair in your config:

```toml
[tool.just-buildit]
command = "make"
repair  = "uvx auditwheel repair"   # override the auto-detected command
# repair = false                    # skip repair entirely
```

Pass extra arguments without replacing the whole command using `repair-args`.
The args are appended after the wheel path:

```toml
[tool.just-buildit]
command     = "make"
repair-args = ["--plat", "manylinux_2_28_x86_64"]
```

Accepts either a list of strings or a single space-separated string:

```toml
repair-args = "--plat manylinux_2_28_x86_64 --strip"
```

______________________________________________________________________

## Editable installs

`pip install -e .` installs a single `.pth` file pointing at your source
tree — no build command is run. Python finds your source directly. The C
extension must be compiled in place once (e.g. `make`) before importing.

!!! tip "Standard src-layout: zero config needed"

    If `editable_path` is not set and a `src/` directory exists at the
    project root, just-buildit uses it automatically:

    ```toml
    [tool.just-buildit]
    command = "make"
    # editable_path = "src"  ← omit; auto-detected when src/ exists
    ```

Set `editable_path` explicitly only when your source root differs from `src/`:

```toml
[tool.just-buildit]
command       = "make"
editable_path = "lib"     # non-standard layout
```

!!! warning "No editable source root found"

    If neither `editable_path` is set nor a `src/` directory exists,
    `build_editable` raises an error instead of guessing:

    ```
    build_editable requires an editable source root but none was found.

    Either put your sources in a src/ directory (auto-detected), or set:

      [tool.just-buildit]
      editable_path = "src"
    ```
