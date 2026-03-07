#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT_DIR"

OUT="${1:-calibration_readings.json}"

echo "Step 1/3: Prepare ice-water bath (0C), keep probe submerged and stable."
read -r -p "Press Enter to start 0C capture (30s)..."
python scripts/calibrate_capture.py --reference-c 0 --duration-sec 30 --interval-sec 0.5 --output "$OUT"

echo ""
echo "Step 2/3: Prepare boiling water bath (100C at sea level), keep probe submerged and stable."
read -r -p "Press Enter to start 100C capture (30s)..."
python scripts/calibrate_capture.py --reference-c 100 --duration-sec 30 --interval-sec 0.5 --output "$OUT"

echo ""
echo "Step 3/3: Applying calibration into config.json"
python scripts/calibrate_apply.py --input "$OUT" --config config.json

echo ""
echo "Calibration complete. Restart server to use new calibration."
