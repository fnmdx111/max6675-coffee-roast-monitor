#!/usr/bin/env python3
import argparse
import json
import time
from datetime import datetime, timezone
from pathlib import Path

from max6675 import MAX6675, build_max6675_env


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Capture MAX6675 readings for calibration at a known reference temperature.")
    parser.add_argument("--reference-c", type=float, required=True, help="Known reference temperature (e.g. 0 or 100).")
    parser.add_argument("--duration-sec", type=float, default=30.0, help="Sampling duration in seconds (default: 30).")
    parser.add_argument("--interval-sec", type=float, default=0.5, help="Sampling interval in seconds (default: 0.5).")
    parser.add_argument("--output", default="calibration_readings.json", help="Output JSON path for captured readings.")
    return parser.parse_args()


def load_or_init(path: Path) -> dict:
    if path.exists():
        with path.open("r", encoding="utf-8") as f:
            data = json.load(f)
            if isinstance(data, dict):
                data.setdefault("points", {})
                return data
    return {"points": {}}


def avg(values: list[float]) -> float:
    return sum(values) / len(values)


def main() -> None:
    args = parse_args()
    out_path = Path(args.output)
    total_samples = max(1, int(args.duration_sec / args.interval_sec))

    print(f"Capturing {total_samples} samples at {args.reference_c:.1f}C reference...")
    print("Keep the thermocouple submerged and stable during capture.")

    readings: list[float] = []
    with MAX6675(*build_max6675_env()) as sensor:
        for i in range(total_samples):
            value = float(sensor.temperature)
            readings.append(value)
            print(f"[{i + 1:>3}/{total_samples}] {value:6.2f} C")
            if i < total_samples - 1:
                time.sleep(args.interval_sec)

    point_payload = {
        "reference_c": args.reference_c,
        "samples": len(readings),
        "duration_sec": args.duration_sec,
        "interval_sec": args.interval_sec,
        "measured_avg_c": round(avg(readings), 6),
        "measured_min_c": round(min(readings), 6),
        "measured_max_c": round(max(readings), 6),
        "captured_at": datetime.now(timezone.utc).isoformat(),
        "readings_c": [round(v, 6) for v in readings],
    }

    doc = load_or_init(out_path)
    doc["sensor"] = "MAX6675"
    doc["updated_at"] = datetime.now(timezone.utc).isoformat()
    key = str(int(args.reference_c)) if args.reference_c.is_integer() else str(args.reference_c)
    doc["points"][key] = point_payload

    with out_path.open("w", encoding="utf-8") as f:
        json.dump(doc, f, indent=2)

    print("")
    print(f"Saved capture for {args.reference_c:.1f}C to {out_path}")
    print(f"Average measured reading: {point_payload['measured_avg_c']:.3f}C")


if __name__ == "__main__":
    main()
