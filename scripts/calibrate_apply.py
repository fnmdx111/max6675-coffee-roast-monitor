#!/usr/bin/env python3
import argparse
import json
from datetime import datetime, timezone
from pathlib import Path


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Apply 0C/100C calibration averages into config.json.")
    parser.add_argument("--input", default="calibration_readings.json", help="Calibration readings JSON path.")
    parser.add_argument("--config", default="config.json", help="Server config JSON path.")
    parser.add_argument("--cold-ref-c", type=float, default=0.0, help="Cold reference temperature key to use (default: 0).")
    parser.add_argument("--hot-ref-c", type=float, default=100.0, help="Hot reference temperature key to use (default: 100).")
    parser.add_argument("--dry-run", action="store_true", help="Print computed values without writing config.")
    return parser.parse_args()


def key_for(v: float) -> str:
    return str(int(v)) if v.is_integer() else str(v)


def main() -> None:
    args = parse_args()
    input_path = Path(args.input)
    config_path = Path(args.config)

    if not input_path.exists():
        raise SystemExit(f"Missing input file: {input_path}")
    if not config_path.exists():
        raise SystemExit(f"Missing config file: {config_path}")

    data = json.loads(input_path.read_text(encoding="utf-8"))
    points = data.get("points", {})

    cold_key = key_for(args.cold_ref_c)
    hot_key = key_for(args.hot_ref_c)

    if cold_key not in points:
        raise SystemExit(f"Missing cold reference point {cold_key} in {input_path}")
    if hot_key not in points:
        raise SystemExit(f"Missing hot reference point {hot_key} in {input_path}")

    cold_avg = float(points[cold_key]["measured_avg_c"])
    hot_avg = float(points[hot_key]["measured_avg_c"])
    if abs(hot_avg - cold_avg) < 1e-6:
        raise SystemExit("Invalid calibration points: hot and cold measured averages are identical.")

    cfg = json.loads(config_path.read_text(encoding="utf-8"))
    cfg.setdefault("calibration", {})
    cfg["calibration"]["measured_at_0c"] = round(cold_avg, 6)
    cfg["calibration"]["measured_at_100c"] = round(hot_avg, 6)
    cfg["calibration"]["updated_at"] = datetime.now(timezone.utc).isoformat()

    slope = 100.0 / (hot_avg - cold_avg)

    print("Computed calibration:")
    print(f"  measured_at_0c   = {cold_avg:.6f}")
    print(f"  measured_at_100c = {hot_avg:.6f}")
    print(f"  linear scale     = {slope:.6f} C_true/C_measured")

    if args.dry_run:
        print("Dry run only; config not modified.")
        return

    config_path.write_text(json.dumps(cfg, indent=2), encoding="utf-8")
    print(f"Updated {config_path}")


if __name__ == "__main__":
    main()
