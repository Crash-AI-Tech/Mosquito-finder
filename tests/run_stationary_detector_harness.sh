#!/bin/zsh
set -euo pipefail

ROOT="${0:A:h:h}"
CACHE="${TMPDIR:-/tmp}/mosquito-stationary-swift-cache"
BINARY="${TMPDIR:-/tmp}/mosquito-stationary-detector-harness"

xcrun swiftc \
  -parse-as-library \
  -module-cache-path "$CACHE" \
  "$ROOT/Mosquito-finder/Models/StationaryDetectionModels.swift" \
  "$ROOT/Mosquito-finder/Vision/StationaryFlightDetector.swift" \
  "$ROOT/tests/StationaryFlightDetectorHarness.swift" \
  -o "$BINARY" \
  -framework CoreVideo \
  -framework CoreGraphics \
  -framework SwiftUI

"$BINARY"
