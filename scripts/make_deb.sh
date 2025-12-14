#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR=$(cd "$(dirname "$0")/.." && pwd)
BUILD_DIR="$ROOT_DIR/build"
PKGDIR="$ROOT_DIR/pkgroot"
PACKAGE_NAME="gearlever"

VERSION=$(sed -n "s/.*version:\s*'\([0-9.][0-9.]*\)'.*/\1/p" "$ROOT_DIR/meson.build" | head -n1 || true)
if [ -z "$VERSION" ]; then
  echo "ERROR: Could not extract version from meson.build"
  exit 1
fi

ARCH=$(dpkg --print-architecture)
if [ -z "$ARCH" ]; then
  echo "ERROR: Could not determine architecture"
  exit 1
fi

echo "Building $PACKAGE_NAME $VERSION for $ARCH"

if [ ! -d "$BUILD_DIR" ]; then
  echo "Setting up Meson build..."
  meson setup "$BUILD_DIR" --prefix=/usr
else
  echo "Reconfiguring Meson build..."
  meson setup --reconfigure "$BUILD_DIR" --prefix=/usr || true
fi

echo "Building with Ninja..."
ninja -C "$BUILD_DIR"

echo "Cleaning previous package root..."
rm -rf "$PKGDIR"
mkdir -p "$PKGDIR"

echo "Installing to staging directory..."
DESTDIR="$PKGDIR" ninja -C "$BUILD_DIR" install

echo "Bundling Python dependencies not in Ubuntu repos..."
VENDOR_DIR="$PKGDIR/usr/share/gearlever/vendor"
mkdir -p "$VENDOR_DIR"

pip3 install --target="$VENDOR_DIR" --no-deps --no-compile \
  ftputil==5.1.0 \
  desktop-entry-lib==5.0

echo "Cleaning bundled packages..."
find "$VENDOR_DIR" -type d -name "__pycache__" -exec rm -rf {} + 2>/dev/null || true
find "$VENDOR_DIR" -type d -name "*.egg-info" -exec rm -rf {} + 2>/dev/null || true
find "$VENDOR_DIR" -type d -name "*.dist-info" -exec rm -rf {} + 2>/dev/null || true
find "$VENDOR_DIR" -type f -name "*.pyc" -delete 2>/dev/null || true
find "$VENDOR_DIR" -type f -name "*.pyo" -delete 2>/dev/null || true

LAUNCHER="$PKGDIR/usr/bin/$PACKAGE_NAME"
if [ -f "$LAUNCHER" ]; then
  echo "Updating launcher to include vendor packages..."
  cp "$LAUNCHER" "$LAUNCHER.orig"
  
  cat > "$LAUNCHER" << 'LAUNCHER_EOF'
#!/usr/bin/python3
import sys
import os

# Add vendored packages to Python path
vendor_dir = '/usr/share/gearlever/vendor'
if os.path.exists(vendor_dir) and vendor_dir not in sys.path:
    sys.path.insert(0, vendor_dir)

LAUNCHER_EOF
  
  tail -n +2 "$LAUNCHER.orig" >> "$LAUNCHER"
  rm "$LAUNCHER.orig"
  chmod 755 "$LAUNCHER"
fi

echo "Creating DEBIAN control files..."
mkdir -p "$PKGDIR/DEBIAN"

cat > "$PKGDIR/DEBIAN/control" <<EOF
Package: $PACKAGE_NAME
Version: $VERSION
Section: utils
Priority: optional
Architecture: $ARCH
Depends: python3 (>= 3.9), python3-gi, python3-dbus, python3-xdg, python3-requests, gir1.2-gtk-4.0, gir1.2-adw-1, libgtk-4-1, libadwaita-1-0
Recommends: appstream
Maintainer: Lorenzo Paderi <https://github.com/mijorus/gearlever>
Homepage: https://github.com/mijorus/gearlever
Description: Manage AppImages with ease
 Gear Lever is a GTK4/libadwaita application designed to manage, organize,
 and integrate AppImage files on your Linux system. It provides a clean
 interface for installing, updating, and removing AppImages.
 .
 Features:
  - Install and organize AppImages
  - Automatic update checking
  - Desktop integration
  - Multiple update sources (GitHub, GitLab, FTP, etc.)
 .
 This package includes ftputil and desktop-entry-lib in a vendor directory
 as they are not available in Ubuntu repositories.
EOF

cat > "$PKGDIR/DEBIAN/postinst" <<'EOF'
#!/bin/sh
set -e

case "$1" in
  configure)
    # Compile GSettings schemas
    if [ -x /usr/bin/glib-compile-schemas ]; then
      glib-compile-schemas /usr/share/glib-2.0/schemas >/dev/null 2>&1 || true
    fi
    
    # Update icon cache
    if [ -x /usr/bin/gtk-update-icon-cache ]; then
      gtk-update-icon-cache -q -t -f /usr/share/icons/hicolor >/dev/null 2>&1 || true
    fi
    
    # Update desktop database
    if [ -x /usr/bin/update-desktop-database ]; then
      update-desktop-database -q /usr/share/applications >/dev/null 2>&1 || true
    fi
    ;;
esac

exit 0
EOF

cat > "$PKGDIR/DEBIAN/postrm" <<'EOF'
#!/bin/sh
set -e

case "$1" in
  remove|purge)
    # Compile GSettings schemas
    if [ -x /usr/bin/glib-compile-schemas ]; then
      glib-compile-schemas /usr/share/glib-2.0/schemas >/dev/null 2>&1 || true
    fi
    
    # Update icon cache
    if [ -x /usr/bin/gtk-update-icon-cache ]; then
      gtk-update-icon-cache -q -t -f /usr/share/icons/hicolor >/dev/null 2>&1 || true
    fi
    
    # Update desktop database
    if [ -x /usr/bin/update-desktop-database ]; then
      update-desktop-database -q /usr/share/applications >/dev/null 2>&1 || true
    fi
    ;;
esac

exit 0
EOF

echo "Setting file permissions..."
find "$PKGDIR" -type f -exec chmod 644 {} +
find "$PKGDIR" -type d -exec chmod 755 {} +
if [ -f "$PKGDIR/usr/bin/$PACKAGE_NAME" ]; then
  chmod 755 "$PKGDIR/usr/bin/$PACKAGE_NAME"
fi
if [ -f "$PKGDIR/usr/bin/get_appimage_offset" ]; then
  chmod 755 "$PKGDIR/usr/bin/get_appimage_offset"
fi
chmod 755 "$PKGDIR/DEBIAN/postinst"
chmod 755 "$PKGDIR/DEBIAN/postrm"

OUTPUT="$ROOT_DIR/${PACKAGE_NAME}_${VERSION}_${ARCH}.deb"
echo "Building .deb package..."
dpkg-deb --build --root-owner-group "$PKGDIR" "$OUTPUT"

echo "Successfully created: $OUTPUT"