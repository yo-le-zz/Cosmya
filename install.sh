#!/usr/bin/env bash
#
# install.sh -- installs the latest Cosmya .deb release for Linux x86_64.
#
# This script does NOT compile anything and does NOT require Rust, Python
# dev tools, uv, or maturin. It only downloads the pre-built .deb published
# on GitHub Releases, verifies its checksum, and installs it with apt/dpkg.
#
# Usage:
#   curl -fsSL https://raw.githubusercontent.com/yo-le-zz/Cosmya/main/install.sh | bash

set -euo pipefail

REPO="yo-le-zz/Cosmya"
GITHUB_API="https://api.github.com/repos/${REPO}/releases/latest"

log() { printf '\033[1;36m==>\033[0m %s\n' "$1"; }
fail() { printf '\033[1;31mERROR:\033[0m %s\n' "$1" >&2; exit 1; }

# --------------------------------------------------------------------------
# 1. Detect OS
# --------------------------------------------------------------------------
OS_NAME="$(uname -s)"
if [ "$OS_NAME" != "Linux" ]; then
    fail "Cosmya only supports Linux. Detected: $OS_NAME"
fi

# --------------------------------------------------------------------------
# 2. Detect and verify architecture
# --------------------------------------------------------------------------
ARCH="$(uname -m)"
case "$ARCH" in
    x86_64|amd64)
        DEB_ARCH="amd64"
        ;;
    *)
        fail "Unsupported architecture: $ARCH. Cosmya currently only ships Linux x86_64 (amd64) packages."
        ;;
esac

# --------------------------------------------------------------------------
# 3. Check required tools
# --------------------------------------------------------------------------
command -v curl >/dev/null 2>&1 || fail "curl is required."
command -v dpkg >/dev/null 2>&1 || fail "dpkg is required (this installer only supports Debian/Ubuntu-based systems)."
command -v sha256sum >/dev/null 2>&1 || fail "sha256sum is required."

SUDO=""
if [ "$(id -u)" -ne 0 ]; then
    command -v sudo >/dev/null 2>&1 || fail "This installer needs root privileges (sudo not found)."
    SUDO="sudo"
fi

# --------------------------------------------------------------------------
# 4. Resolve the latest release and its .deb asset
# --------------------------------------------------------------------------
log "Looking up the latest Cosmya release..."
RELEASE_JSON="$(curl -fsSL "$GITHUB_API")" || fail "Could not reach GitHub Releases API."

DEB_URL="$(printf '%s' "$RELEASE_JSON" \
    | grep -o "\"browser_download_url\": *\"[^\"]*cosmya_[^\"]*_${DEB_ARCH}\.deb\"" \
    | head -n1 \
    | sed -E 's/.*"(https[^"]+)"/\1/')"
[ -n "$DEB_URL" ] || fail "No .deb release asset found for architecture $DEB_ARCH."

CHECKSUM_URL="${DEB_URL}.sha256"

DEB_FILENAME="$(basename "$DEB_URL")"
WORKDIR="$(mktemp -d)"
trap 'rm -rf "$WORKDIR"' EXIT

# --------------------------------------------------------------------------
# 5. Download the .deb
# --------------------------------------------------------------------------
log "Downloading $DEB_FILENAME..."
curl -fsSL -o "$WORKDIR/$DEB_FILENAME" "$DEB_URL" \
    || fail "Failed to download $DEB_URL"

# --------------------------------------------------------------------------
# 6. Verify checksum (if a .sha256 asset was published for this release)
# --------------------------------------------------------------------------
if curl -fsSL -o "$WORKDIR/${DEB_FILENAME}.sha256" "$CHECKSUM_URL" 2>/dev/null; then
    log "Verifying checksum..."
    EXPECTED="$(awk '{print $1}' "$WORKDIR/${DEB_FILENAME}.sha256")"
    ACTUAL="$(sha256sum "$WORKDIR/$DEB_FILENAME" | awk '{print $1}')"
    if [ "$EXPECTED" != "$ACTUAL" ]; then
        fail "Checksum verification FAILED for $DEB_FILENAME. Refusing to install a package that does not match its published checksum."
    fi
    log "Checksum verified."
else
    log "No checksum asset published for this release; proceeding without checksum verification."
fi

# --------------------------------------------------------------------------
# 7. Install
# --------------------------------------------------------------------------
log "Installing $DEB_FILENAME (requires root)..."
# --reinstall matters here: Cosmya may publish a new .deb under an
# unchanged version string during pre-1.0 development (e.g. a same-version
# bugfix rebuild). Without --reinstall, apt sees a matching version already
# installed, silently no-ops ("already the newest version"), and the freshly
# downloaded fix never actually gets installed.
$SUDO apt-get install --reinstall -y "$WORKDIR/$DEB_FILENAME" \
    || $SUDO dpkg -i "$WORKDIR/$DEB_FILENAME" \
    || fail "Installation failed."

# --------------------------------------------------------------------------
# 8. Report success
# --------------------------------------------------------------------------
if command -v cosmya >/dev/null 2>&1; then
    log "Cosmya installed successfully."
    cosmya --version || true
    log "Run 'cosmya config' to get started."
else
    fail "Installation completed but the 'cosmya' command was not found on PATH."
fi
