# Contributing

## Running the tests

```sh
python -m unittest tests.test_build tests.test_examples tests.test_cli -v
```

No dependencies required. `tests.test_build` builds real C extensions, verifies
wheel structure, and confirms correct results. `tests.test_examples` builds each
example in `examples/` end-to-end; CMake, Meson, and Bazel tests skip gracefully
if those tools are not installed. `tests.test_cli` exercises the CLI via
subprocess.

---

## Platform support

| Platform | Tested on |
|---|---|
| Linux | x86-64, aarch64 |
| macOS | arm64, x86-64 |
| Windows | MinGW-w64 / UCRT64 (MSYS2) |

CI runs on all three platforms on every push.

---

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

---

## Releasing

- [ ] All CI checks green on `main`
- [ ] `CHANGELOG.md` updated with release date and notes
- [ ] Version bumped in `pyproject.toml`
- [ ] Commit: `chore: bump version to X.Y.Z`
- [ ] Tag: `git tag vX.Y.Z && git push origin vX.Y.Z`
- [ ] Confirm the release workflow passes and the wheel lands on PyPI
