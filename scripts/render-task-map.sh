#!/bin/bash
set -euo pipefail
cd "$(dirname "$0")/.."
mkdir -p build/module-cache build/task-map-evidence
SDK="$(xcrun --sdk macosx --show-sdk-path)"
swiftc -swift-version 5 -sdk "$SDK" -target "$(uname -m)-apple-macosx14.0" -module-cache-path "$PWD/build/module-cache" \
  Sources/BrandGeometry.swift Sources/DesignSystem.swift Sources/Models.swift Sources/PetAnimation.swift \
  Sources/Pets.swift Sources/AppModel.swift Sources/MainView.swift Sources/ConnectionViews.swift Sources/SummaryViews.swift Sources/TaskMapViews.swift Sources/UpdateViews.swift \
  tests/task-map/main.swift -o build/task-map-preview
python3 scripts/create-demo.py build/task-map-demo.json
build/task-map-preview --demo build/task-map-demo.json build/task-map-evidence
