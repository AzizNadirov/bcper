#!/bin/bash
set -e

VERSION="0.1.0"
ARCH="all"
PKG="bcper"
BUILD_DIR="build-deb"

# Clean previous build
rm -rf "$BUILD_DIR"
mkdir -p "$BUILD_DIR/DEBIAN"
mkdir -p "$BUILD_DIR/usr/lib/python3/dist-packages"
mkdir -p "$BUILD_DIR/usr/bin"
mkdir -p "$BUILD_DIR/usr/share/applications"
mkdir -p "$BUILD_DIR/usr/share/pixmaps"

# Install Python packages
cp -r bcper "$BUILD_DIR/usr/lib/python3/dist-packages/"
cp -r bcper_core "$BUILD_DIR/usr/lib/python3/dist-packages/"
cp -r bcperd "$BUILD_DIR/usr/lib/python3/dist-packages/"

# Remove build artifacts
find "$BUILD_DIR/usr/lib/python3/dist-packages" -type d -name __pycache__ -exec rm -rf {} + 2>/dev/null || true
find "$BUILD_DIR/usr/lib/python3/dist-packages" -name "*.pyc" -delete 2>/dev/null || true

# Create wrapper scripts
cat > "$BUILD_DIR/usr/bin/bcper" << 'EOF'
#!/usr/bin/python3
import sys
from bcper.__main__ import main
if __name__ == '__main__':
    sys.exit(main())
EOF

cat > "$BUILD_DIR/usr/bin/bcperd" << 'EOF'
#!/usr/bin/python3
import sys
from bcperd.__main__ import main
if __name__ == '__main__':
    sys.exit(main())
EOF

cat > "$BUILD_DIR/usr/bin/bcper-cli" << 'EOF'
#!/usr/bin/python3
import sys
from bcper.cli import main
if __name__ == '__main__':
    sys.exit(main())
EOF

chmod 755 "$BUILD_DIR/usr/bin/bcper"
chmod 755 "$BUILD_DIR/usr/bin/bcperd"
chmod 755 "$BUILD_DIR/usr/bin/bcper-cli"

# Copy assets if they exist
if [ -d "bcper/gui/assets" ]; then
    cp -r bcper/gui/assets "$BUILD_DIR/usr/lib/python3/dist-packages/bcper/gui/"
fi

# Desktop entry
cat > "$BUILD_DIR/usr/share/applications/bcper.desktop" << EOF
[Desktop Entry]
Name=BCPER
Comment=Backup Manager
Exec=bcper
Type=Application
Terminal=false
Categories=System;Utility;
EOF

# Control file
cat > "$BUILD_DIR/DEBIAN/control" << EOF
Package: bcper
Version: $VERSION
Section: utils
Priority: optional
Architecture: $ARCH
Depends: python3, python3-cryptography, python3-tk
Recommends: rclone
Maintainer: BCPER Team <bcper@localhost>
Description: Lightweight desktop backup manager
 BCPER is a backup manager with a Tkinter GUI
 and a background daemon worker.
 Supports local and remote (rclone) storage,
 scheduled jobs, and AES-256-GCM encryption.
EOF

# Build package
fakeroot dpkg-deb --build "$BUILD_DIR" "${PKG}_${VERSION}_${ARCH}.deb"

echo "Built: ${PKG}_${VERSION}_${ARCH}.deb"
