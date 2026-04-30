# Changelog

## [0.3.0] — 2026-04-30

### Added

- Bazel example (`examples/bazel/`) — `genrule`-based build with a `build_ext.py` bridge script forwarding just-buildit env vars via `--action_env`
- Nested package example (`examples/nested/`) — recursive package tree with multiple extensions across subdirectories
- CLI integration tests (`tests/test_cli.py`) — 15 tests covering `inspect`, `build`, `sdist`, `help`, and error handling via subprocess
- CI: dedicated `test-bazel` job running the Bazel example across all Python versions

### Docs

- Env variable table split into platform-neutral and platform-specific sections
- Examples page updated with Bazel and recursive package tree sections
- Quickstart updated to call out flat, nested, multi-extension, and mixed layouts
- PyPI doc links updated to point to GitHub Pages

---

## [0.2.1] — 2026-04-15

### Breaking

- Renamed config section from `[tool.just-build]` to `[tool.just-buildit]`

---

## [0.2.0] — 2026-04-15

### Breaking

- Renamed Python module from `just_build` to `just_buildit`. Update your `pyproject.toml`:
  ```toml
  [build-system]
  requires = ["just-buildit"]
  build-backend = "just_buildit"   # was: just_build
  ```
- Renamed all environment variables from `JUST_BUILD_*` to `JUST_BUILDIT_*`. Update your Makefiles and build scripts:
  - `JUST_BUILD_NAME` → `JUST_BUILDIT_NAME`
  - `JUST_BUILD_PYTHON` → `JUST_BUILDIT_PYTHON`
  - `JUST_BUILD_INCLUDE_DIR` → `JUST_BUILDIT_INCLUDE_DIR`
  - `JUST_BUILD_OUTPUT_DIR` → `JUST_BUILDIT_OUTPUT_DIR`
  - `JUST_BUILD_EXT_SUFFIX` → `JUST_BUILDIT_EXT_SUFFIX`
  - `JUST_BUILD_LDFLAGS` → `JUST_BUILDIT_LDFLAGS`
  - `JUST_BUILD_LIBS` → `JUST_BUILDIT_LIBS`

### Added

- CLI entry point: `just-buildit inspect`, `just-buildit build [DIR]`, `just-buildit sdist [DIR]`
  - `inspect` shows parsed config, build mode, env vars, and predicted wheel filename without running anything
  - `build` builds a wheel into the given directory (default: `dist/`)
  - `sdist` builds a source distribution into the given directory (default: `dist/`)
- `build_sdist()` / `get_requires_for_build_sdist()` — PEP 517 sdist support

---

## [0.1.5] — 2026-04-03

### Fixed

- Don't delete the original wheel when the repair tool writes an output file with the same filename

---

## [0.1.4] — 2026-04-03

### Fixed

- Repair into a temp subdirectory to avoid a `PermissionError` on Windows when pip holds the source wheel open

---

## [0.1.3] — 2026-04-02

### Fixed

- MSYS2 Python 3.14: search `lib/` and check `.dll.a` suffix for link flags
- Windows native CPython link flags via `libs/python3X.lib`
- CI: release gate, example Makefile fixes

---

## [0.1.2] — 2026-04-02

### Added

- `editable_path` config option: `build_editable()` writes a `.pth` file instead of rebuilding, enabling instant `uv sync` for projects with C extensions compiled in place

---

## [0.1.1] — 2026-04-02

### Added

- Initial release on PyPI
- Zero-config `src/{package}/*.c` auto-discovery and compilation
- PEP 517 `build_wheel()` and `build_editable()`
- Platform auto-repair: auditwheel (Linux), delocate (macOS), delvewheel (Windows)
- Pure Python detection: no `*{ext_suffix}` in output → `py3-none-any` tags
