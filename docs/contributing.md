# Contributing

## Running the tests

```sh
python -m unittest tests.test_build tests.test_examples tests.test_cli tests.test_metadata -v
```

No dependencies required. `tests.test_build` builds real C extensions, verifies
wheel structure, and confirms correct results. `tests.test_examples` builds each
example in `examples/` end-to-end; CMake, Meson, and Bazel tests skip gracefully
if those tools are not installed. `tests.test_cli` exercises the CLI via
subprocess. `tests.test_metadata` verifies every PEP 621 field is mapped
correctly into the wheel/sdist METADATA file.

______________________________________________________________________

## Platform support

| Platform | Tested on                         |
| -------- | --------------------------------- |
| Linux    | x86-64, aarch64                   |
| macOS    | arm64                             |
| Windows  | clang-cl + native CPython, x86-64 |

CI runs on all three platforms on every push.

______________________________________________________________________

## Bootstrapping (offline or pre-release)

just-buildit is a pure Python package with no dependencies. If you need it
before it can be fetched from PyPI — air-gapped environment, initial release
bootstrap, or simply testing a local change — add the source directly to your
path:

```sh
git clone https://github.com/just-buildit/just-buildit.git
export PYTHONPATH=/path/to/just-buildit/src:$PYTHONPATH
```

Then use your build frontend with `--no-isolation` so it picks up the local
copy:

```sh
pip install --no-build-isolation .
# or
python -m build --wheel --no-isolation
# or
uv build --no-build-isolation
```

No build step, no compiler, no install required. `src/just_buildit/` is
importable as-is.

______________________________________________________________________

## Releasing

The release workflow (`release.yml`) triggers on any `v*` tag: it runs the
test matrix, builds the wheel, and publishes to PyPI. The golden rule is
**tag only a commit that is already on `origin/main`** — never a local-only
commit. `main` is protected, so the version bump goes through a PR like any
other change.

### 1. Pick the version

Pre-1.0, the patch digit absorbs both features and fixes; bump the minor digit
only for a breaking change. Lowering the supported-Python floor or any other
additive change is a patch bump.

### 2. Bump version + changelog on a branch

- [ ] `version = "X.Y.Z"` in `pyproject.toml` (single source of truth)
- [ ] New `## [X.Y.Z] — YYYY-MM-DD` section at the top of `CHANGELOG.md`

```sh
git checkout -b chore/bump-X.Y.Z
uv lock
git add pyproject.toml CHANGELOG.md uv.lock
git commit -m "chore: bump version to X.Y.Z"
git push -u origin chore/bump-X.Y.Z
gh pr create --fill
```

### 3. Merge the bump PR — then tag

- [ ] CI green on the PR, then merge it. **Do not tag before it is merged.**
- [ ] Tag the merged commit on `origin/main`, not your local branch:

```sh
git fetch origin
git tag vX.Y.Z origin/main
git push origin vX.Y.Z
```

> If the merge rewrote the commit (squash/rebase merge changes the SHA),
> tagging `origin/main` guarantees the tag is reachable from `main`. Verify
> with `git diff vX.Y.Z origin/main` — it must be empty.

### 4. Verify

- [ ] `release.yml` passes and the wheel lands on PyPI
- [ ] Post-release smoke test: `python -m unittest tests.test_pypi -v`
- [ ] (optional) build on the floor: `uvx --python 3.8 just-buildit@X.Y.Z`
    against a C-extension fixture

> **Never delete and re-push a tag after a successful publish** — that
> re-triggers `release.yml` and the PyPI upload fails on a duplicate version.
> Re-tagging is only safe if no publish has happened yet (e.g. you tagged
> before CI was green). To fix a bad release, bump to the next patch version
> instead.
