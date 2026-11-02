#!/bin/bash
set -euo pipefail
cd "$(dirname "$0")/.."
DESTINATION="$PWD/dist/coindex.app"
mkdir -p build dist
STAGE="$(mktemp -d "$PWD/build/coindex-stage.XXXXXX")"
trap 'rm -rf "$STAGE"' EXIT
APP="$STAGE/coindex.app"
RELEASE_VERSION="$(python3 scripts/release.py version)"
RELEASE_BUILD="$(python3 scripts/release.py build-number)"
mkdir -p build/module-cache "$APP/Contents/MacOS" "$APP/Contents/Resources/backend"
SDK="$(xcrun --sdk macosx --show-sdk-path)"
ARCHS="${COINDEX_ARCHS:-$(uname -m)}"
BINARIES=()
for ARCH in $ARCHS; do
  case "$ARCH" in arm64|x86_64) ;; *) printf 'Unsupported architecture: %s\n' "$ARCH" >&2; exit 1 ;; esac
  swiftc -swift-version 5 -O -sdk "$SDK" -target "$ARCH-apple-macosx14.0" \
    -module-cache-path "$PWD/build/module-cache" \
    Sources/BrandGeometry.swift Sources/DesignSystem.swift Sources/Models.swift Sources/PetAnimation.swift Sources/Pets.swift Sources/AppModel.swift Sources/MainView.swift Sources/ConnectionViews.swift Sources/SummaryViews.swift Sources/TaskMapViews.swift Sources/UpdateViews.swift Sources/CodexTodoApp.swift \
    -o "$PWD/build/coindex-$ARCH"
  BINARIES+=("$PWD/build/coindex-$ARCH")
done
if [ "${#BINARIES[@]}" -eq 1 ]; then
  cp "${BINARIES[0]}" "$APP/Contents/MacOS/coindex"
else
  lipo -create "${BINARIES[@]}" -output "$APP/Contents/MacOS/coindex"
fi
cp backend/*.py "$APP/Contents/Resources/backend/"
cp LICENSE "$APP/Contents/Resources/LICENSE"
python3 scripts/release.py metadata macos "$APP/Contents/Resources/release.json"
# Installed Codex artwork is a local import, excluded from shareable builds.
rm -rf "$APP/Contents/Resources/Pets"
if [ "${COINDEX_INCLUDE_LOCAL_PETS:-0}" = 1 ] && [ -d Resources/Pets ]; then
  cp -R Resources/Pets "$APP/Contents/Resources/"
fi
rm -rf "$APP/Contents/Resources/CustomPets"
mkdir -p "$APP/Contents/Resources/CustomPets/coindex-cat"
cp Resources/CustomPets/coindex-cat/pet.json Resources/CustomPets/coindex-cat/spritesheet.png "$APP/Contents/Resources/CustomPets/coindex-cat/"
python3 scripts/create-demo.py "$APP/Contents/Resources/demo.json"
swiftc -swift-version 5 -sdk "$SDK" -module-cache-path "$PWD/build/module-cache" Sources/BrandGeometry.swift scripts/create-icon.swift -o build/create-icon
build/create-icon "$PWD/build/AppIcon.iconset"
python3 scripts/strip-png-metadata.py build/AppIcon.iconset build/MenuIcon.png
cp build/MenuIcon.png "$APP/Contents/Resources/"
mkdir -p Resources/Brand
cp build/AppIcon.iconset/icon_512x512@2x.png Resources/Brand/AppIcon.png
iconutil -c icns "$PWD/build/AppIcon.iconset" -o "$APP/Contents/Resources/AppIcon.icns"
cat > "$APP/Contents/Info.plist" <<PLIST
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0"><dict>
<key>CFBundleExecutable</key><string>coindex</string>
<key>CFBundleIdentifier</key><string>org.coindex.desktop</string>
<key>CFBundleName</key><string>coindex</string>
<key>CFBundleDisplayName</key><string>coindex</string>
<key>CFBundlePackageType</key><string>APPL</string>
<key>CFBundleShortVersionString</key><string>$RELEASE_VERSION</string>
<key>CFBundleVersion</key><string>$RELEASE_BUILD</string>
<key>CFBundleIconFile</key><string>AppIcon</string>
<key>LSMinimumSystemVersion</key><string>14.0</string>
<key>NSHighResolutionCapable</key><true/>
</dict></plist>
PLIST
codesign --force --deep --sign - "$APP"
python3 scripts/release.py install-build macos "$APP" "$DESTINATION"
printf 'Built %s\n' "$DESTINATION"
