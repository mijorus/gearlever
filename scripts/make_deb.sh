#!/usr/bin/env bash
set -euo pipefail

# Minimal .deb builder that uses Meson/Ninja install into a DESTDIR
# Requirements: meson, ninja, ninja-build, dpkg-deb

ROOT_DIR=$(cd "$(dirname "$0")/.." && pwd)
BUILD_DIR="$ROOT_DIR/build"
PKGDIR="$ROOT_DIR/pkgroot"
PACKAGE_NAME="gearlever"

VERSION=$(sed -n "s/.*version:\s*'\([0-9.][0-9.]*\)'.*/\1/p" "$ROOT_DIR/meson.build" | head -n1 || true)
if [ -z "$VERSION" ]; then
  VERSION="0.0.0"
fi
ARCH=$(dpkg --print-architecture || echo "all")

echo "Building $PACKAGE_NAME version $VERSION for $ARCH"

if [ ! -d "$BUILD_DIR" ]; then
  meson setup "$BUILD_DIR" --prefix=/usr
else
  meson setup --reconfigure "$BUILD_DIR" --prefix=/usr || true
fi

# Build
ninja -C "$BUILD_DIR"

# Clean previous package root
rm -rf "$PKGDIR"
mkdir -p "$PKGDIR"

# Install into package root
DESTDIR="$PKGDIR" ninja -C "$BUILD_DIR" install

# Install Python dependencies
echo "Installing Python dependencies..."
pip3 install --target="$PKGDIR/usr/share/gearlever" --no-deps -r "$ROOT_DIR/requirements.txt"

# Ensure helper scripts from build-aux get packaged (used at runtime by the app)
if [ -f "$ROOT_DIR/build-aux/get_appimage_offset.sh" ]; then
  mkdir -p "$PKGDIR/usr/bin"
  cp "$ROOT_DIR/build-aux/get_appimage_offset.sh" "$PKGDIR/usr/bin/get_appimage_offset"
  chmod 755 "$PKGDIR/usr/bin/get_appimage_offset"
fi

# Create minimal DEBIAN control file
mkdir -p "$PKGDIR/DEBIAN"
cat > "$PKGDIR/DEBIAN/control" <<EOF
Package: $PACKAGE_NAME
Version: $VERSION
Section: utils
Priority: optional
Architecture: $ARCH
Depends: python3, gir1.2-gtk-4.0, gir1.2-adw-1
Maintainer: Your Name <you@example.com>
Description: Gear Lever - manage AppImages and updates (packaged locally)
EOF

# Ensure permissions
chmod -R a+r "$PKGDIR"
if [ -f "$PKGDIR/usr/bin/$PACKAGE_NAME" ]; then
  chmod 755 "$PKGDIR/usr/bin/$PACKAGE_NAME"
fi

OUTPUT="$ROOT_DIR/${PACKAGE_NAME}_${VERSION}_${ARCH}.deb"
dpkg-deb --build --root-owner-group "$PKGDIR" "$OUTPUT"

echo "Created $OUTPUT"
