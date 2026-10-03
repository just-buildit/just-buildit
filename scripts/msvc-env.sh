#!/usr/bin/env bash
# msvc-env.sh -- put the MSVC developer environment into a GitHub Actions job.
#
#   - name: MSVC developer environment (x64)
#     run: scripts/msvc-env.sh x64          # a Windows job, `shell: bash`
#
# Every later step then finds cl.exe, link.exe and the SDK, and clang-cl finds
# the INCLUDE / LIB it drives the MSVC toolchain with: what "open a Developer
# Command Prompt" does, for a runner.
#
# Why this exists: every adopter used `ilammy/msvc-dev-cmd` for it, with
# `arch: x64` and nothing else (just-makeit 2 sites, doppler 5). That action
# has had no commit since 2024-04 and still declares `node20`, which GitHub
# now forces onto Node 24 with a deprecation notice and will stop running.
# The whole job is ~30 lines of shell, so it lives here, vendored, rather
# than as a third-party pin in seven places.
#
# How: `vswhere` finds the newest Visual Studio with the C++ x64/x86 tools,
# `vcvarsall.bat <arch>` sets the environment inside cmd.exe, and every
# variable it added or changed -- compared with the same cmd.exe's `set`
# before the call -- is appended to $GITHUB_ENV, which the runner applies to
# every later step. Path included: it is exported whole, as the action did.
#
# The argument is vcvarsall's (x64, x86, arm64, x86_amd64, ...). It is
# checked by reading back VSCMD_ARG_TGT_ARCH rather than trusted, because
# vcvarsall reports a bad one on stdout and can still exit 0.
set -euo pipefail

die() { echo "msvc-env: $*" >&2; exit 1; }

arch=${1:-x64}
[ -n "${GITHUB_ENV:-}" ] \
    || die "GITHUB_ENV is not set -- this runs inside a GitHub Actions step"
command -v cmd.exe >/dev/null || die "no cmd.exe -- this runs on Windows"

pf86=$(printenv 'ProgramFiles(x86)' || true)
vswhere="$pf86/Microsoft Visual Studio/Installer/vswhere.exe"
[ -f "$vswhere" ] || die "no vswhere at $vswhere"
vs=$("$vswhere" -latest -products '*' \
         -requires Microsoft.VisualStudio.Component.VC.Tools.x86.x64 \
         -property installationPath | tr -d '\r')
[ -n "$vs" ] || die "no Visual Studio with the C++ tools"
vcvars="$vs\\VC\\Auxiliary\\Build\\vcvarsall.bat"

tmp=$(mktemp -d)
trap 'rm -rf "$tmp"' EXIT

# Batch files, not a `cmd /c "..."` one-liner: the quoted path would pass
# through bash's quoting, MSYS's argument conversion and cmd's own, and a
# space in "Program Files" has to survive all three.
printf '@set\r\n' >"$tmp/before.bat"
printf '@call "%s" %s >nul || exit /b 1\r\n@set\r\n' "$vcvars" "$arch" \
    >"$tmp/after.bat"
run() { cmd.exe //d //c "$(cygpath -w "$1")" | tr -d '\r'; }
run "$tmp/before.bat" | sort >"$tmp/before"
run "$tmp/after.bat" | sort >"$tmp/after" \
    || die "vcvarsall.bat $arch failed"

got=$(sed -n 's/^VSCMD_ARG_TGT_ARCH=//p' "$tmp/after")
[ "$got" = "${arch##*_}" ] \
    || die "vcvarsall.bat $arch set target arch '${got:-nothing}'"

# Lines present after and not before: every variable vcvarsall added or
# changed. `set` prints NAME=VALUE one per line, and none of these values
# can hold a newline, so a line is a variable.
comm -13 "$tmp/before" "$tmp/after" >"$tmp/changed"
[ -s "$tmp/changed" ] || die "vcvarsall.bat $arch changed nothing"
cat "$tmp/changed" >>"$GITHUB_ENV"

echo "msvc-env: $arch from $vs"
echo "  exported: $(cut -d= -f1 "$tmp/changed" | tr '\n' ' ')"
