#!/bin/bash
set -euo pipefail
cd "$(dirname "$0")/.."
mkdir -p build/module-cache
SDK="${SDKROOT:-$(xcrun --sdk macosx --show-sdk-path)}"
swiftc -swift-version 5 -sdk "$SDK" -target "$(uname -m)-apple-macosx14.0" -module-cache-path "$PWD/build/module-cache" \
  Sources/BrandGeometry.swift Sources/DesignSystem.swift Sources/Models.swift Sources/PetAnimation.swift \
  Sources/Pets.swift Sources/AppModel.swift Sources/MainView.swift Sources/ConnectionViews.swift Sources/SummaryViews.swift Sources/UpdateViews.swift \
  tests/task-filtering/main.swift -o build/task-filtering-tests
build/task-filtering-tests --demo
