#!/usr/bin/env bash
#
# build.sh -- Cosmya's official local release build script.
#
# Builds the Rust native extension, installs Cosmya and its Python
# dependencies into a self-contained virtual environment, and packages
# the result as a Debian package at dist/cosmya_<version>_amd64.deb.
#
# The end user installing the resulting .deb needs NONE of: Rust, Cargo,
# uv, maturin, or Python build tools -- only python3 >= 3.11 (declared as
# a package dependency) and the .deb itself.

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$SCRIPT_DIR"

ARCH="amd64"
PKG_NAME="cosmya"

log() { printf '\033[1;36m==>\033[0m %s\n' "$1"; }
fail() { printf '\033[1;31mERROR:\033[0m %s\n' "$1" >&2; exit 1; }

# --------------------------------------------------------------------------
# 1. Check required build dependencies
# --------------------------------------------------------------------------
log "Checking build dependencies..."

command -v uv >/dev/null 2>&1 || fail "uv is required. Install it: https://docs.astral.sh/uv/"
command -v cargo >/dev/null 2>&1 || fail "Rust/Cargo is required. Install it: https://rustup.rs/"
command -v rustc >/dev/null 2>&1 || fail "rustc is required. Install it: https://rustup.rs/"
command -v dpkg-deb >/dev/null 2>&1 || fail "dpkg-deb is required (apt install dpkg-dev)."

log "All build dependencies found (uv, cargo, rustc, dpkg-deb)."

# Cosmya targets Python >= 3.11 for its runtime, but the Rust build itself
# must link against a Python version PyO3 actually supports. Rather than
# trusting whatever `python3` happens to resolve to on PATH (which caused a
# real build failure when a system's default was newer than PyO3
# supported), we pin an explicit interpreter for the whole build via uv and
# point PyO3 at it with PYO3_PYTHON. Bump PIN_PYTHON_VERSION here once a
# newer PyO3 release supports a newer CPython and you want to build against it.
PIN_PYTHON_VERSION="3.12"

# --------------------------------------------------------------------------
# 2. Read version from package metadata (single source of truth)
# --------------------------------------------------------------------------
VERSION="$(grep -oP '__version__ = "\K[^"]+' src/cosmya/__init__.py || true)"
[ -n "$VERSION" ] || fail "Could not determine Cosmya version from src/cosmya/__init__.py."
log "Building Cosmya version $VERSION for $ARCH"

# --------------------------------------------------------------------------
# 3. Clean previous build artifacts
# --------------------------------------------------------------------------
log "Cleaning previous build artifacts..."
rm -rf build/ dist/
mkdir -p build dist

# --------------------------------------------------------------------------
# 4. Set up a pinned Python environment used for both the Rust build and
#    the Python test suite, then run Rust tests against it
# --------------------------------------------------------------------------
log "Setting up a pinned Python $PIN_PYTHON_VERSION environment for the build..."
TEST_VENV="$SCRIPT_DIR/build/test-venv"
uv venv --python "$PIN_PYTHON_VERSION" "$TEST_VENV" >/dev/null
# shellcheck disable=SC1091
source "$TEST_VENV/bin/activate"
uv pip install -e . --group dev -q

# Pin PyO3's target interpreter explicitly rather than letting
# pyo3-build-config discover whatever `python3` resolves to on PATH -- this
# is what broke when a system's default python3 (3.14) was newer than the
# PyO3 release in use supported.
export PYO3_PYTHON="$TEST_VENV/bin/python"

log "Running Rust test suite (rust/) against Python $PIN_PYTHON_VERSION..."
(cd rust && cargo test --release) || fail "Rust tests failed. Aborting build."

# --------------------------------------------------------------------------
# 5. Run Python tests
# --------------------------------------------------------------------------
log "Running Python test suite (tests/python/)..."
python -m pytest tests/python/ -q || fail "Python tests failed. Aborting build."
deactivate

# --------------------------------------------------------------------------
# 6. Build a self-contained runtime venv (Rust extension + all deps)
# --------------------------------------------------------------------------
STAGE_ROOT="$SCRIPT_DIR/build/pkgroot"
INSTALL_LIB_DIR="$STAGE_ROOT/usr/lib/cosmya"
RUNTIME_VENV="$INSTALL_LIB_DIR/venv"

log "Building the compiled Rust + Python runtime environment..."
mkdir -p "$INSTALL_LIB_DIR"
uv venv --python "$PIN_PYTHON_VERSION" "$RUNTIME_VENV" >/dev/null
# shellcheck disable=SC1091
source "$RUNTIME_VENV/bin/activate"
export PYO3_PYTHON="$RUNTIME_VENV/bin/python"
# `uv pip install .` invokes maturin (configured in pyproject.toml) to
# compile rust/ in release mode and install the resulting extension
# alongside Cosmya's pure-Python package and dependencies.
uv pip install . -q || fail "Failed to build/install Cosmya into the runtime venv."
python -c "import cosmya._native" || fail "Native Rust extension failed to import after build."
python -c "import cosmya; print(cosmya.__version__)" || fail "Cosmya package failed to import after build."
deactivate
log "Runtime environment built and verified."

# --------------------------------------------------------------------------
# 7. Assemble the Debian package filesystem layout
# --------------------------------------------------------------------------
log "Assembling Debian package layout..."

mkdir -p "$STAGE_ROOT/usr/bin"
mkdir -p "$STAGE_ROOT/usr/share/doc/cosmya"
mkdir -p "$STAGE_ROOT/DEBIAN"

cat > "$STAGE_ROOT/usr/bin/cosmya" <<EOF
#!/usr/bin/env bash
exec /usr/lib/cosmya/venv/bin/python -m cosmya "\$@"
EOF
chmod 755 "$STAGE_ROOT/usr/bin/cosmya"

cp README.md "$STAGE_ROOT/usr/share/doc/cosmya/README.md"
cp LICENSE "$STAGE_ROOT/usr/share/doc/cosmya/copyright"

# Remove the venv's own pip cache / bytecode to shrink the package.
find "$RUNTIME_VENV" -name '__pycache__' -type d -prune -exec rm -rf {} +
rm -rf "$RUNTIME_VENV/share/../pip_cache" 2>/dev/null || true

INSTALLED_SIZE_KB="$(du -sk "$STAGE_ROOT" | cut -f1)"

sed \
  -e "s/__VERSION__/${VERSION}/" \
  -e "s/__INSTALLED_SIZE__/${INSTALLED_SIZE_KB}/" \
  packaging/debian/control.template > "$STAGE_ROOT/DEBIAN/control"

# --------------------------------------------------------------------------
# 8. Build the .deb
# --------------------------------------------------------------------------
DEB_NAME="${PKG_NAME}_${VERSION}_${ARCH}.deb"
log "Building $DEB_NAME..."
dpkg-deb --root-owner-group --build "$STAGE_ROOT" "dist/$DEB_NAME" \
  || fail "dpkg-deb failed to build the package."

# --------------------------------------------------------------------------
# 9. Verify package contents
# --------------------------------------------------------------------------
log "Verifying package contents..."
dpkg-deb --info "dist/$DEB_NAME" >/dev/null || fail "Built package is not readable by dpkg-deb --info."
# Captured via command substitution rather than piped into `grep -q`:
# piping a live `dpkg-deb --contents` process into `grep -q` lets grep exit
# (and close its end of the pipe) the instant it finds a match, which sends
# dpkg-deb a SIGPIPE it doesn't swallow -- combined with `set -o pipefail`
# that turns a *successful* match into a reported pipeline failure. Command
# substitution has no such live pipe, so this is a plain string check.
PACKAGE_CONTENTS="$(dpkg-deb --contents "dist/$DEB_NAME")" \
  || fail "Could not list built package contents."
case "$PACKAGE_CONTENTS" in
  *usr/bin/cosmya*) ;;
  *) fail "Built package does not contain usr/bin/cosmya." ;;
esac

log "Build succeeded: dist/$DEB_NAME"
log "Install with: sudo apt install ./dist/$DEB_NAME"
log "Then run:     cosmya --version"
