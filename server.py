#!/usr/bin/env python3
import argparse
import json
import random
import threading
import time
from collections import deque
from dataclasses import dataclass
from datetime import datetime, timezone
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any
from urllib.parse import urlparse


BASE_DIR = Path(__file__).resolve().parent
STATIC_DIR = BASE_DIR / "static"
SESSIONS_DIR = BASE_DIR / "sessions"
CONFIG_PATH = BASE_DIR / "config.json"
DEFAULT_CONFIG = {
    "host": "0.0.0.0",
    "port": 8000,
    "poll_interval_sec": 0.5,
    "ror": {
        "window_sec": 30.0,
        "min_span_sec": 5.0,
        "ema_alpha": 0.24,
    },
    "temp_guides": {
        "charge_c": 205.0,
        "first_crack_c": 208.0,
        "drop_c": 212.0,
    },
    "charge_ready": {
        "enabled": True,
        "min_temp_c": 205.0,
        "stable_window_sec": 20.0,
        "max_abs_ror_c_per_min": 2.5,
        "max_temp_span_c": 3.0,
    },
    "sensor": {
        "mode": "mock",
        "mock": {
            "noise_c": 0.25,
            "response": 0.24,
            "cycle_sec": 900,
            "curve": [
                {"time_sec": 0, "temp_c": 205},
                {"time_sec": 95, "temp_c": 92},
                {"time_sec": 270, "temp_c": 152},
                {"time_sec": 500, "temp_c": 196},
                {"time_sec": 620, "temp_c": 209},
                {"time_sec": 760, "temp_c": 80},
                {"time_sec": 900, "temp_c": 34}
            ]
        },
    },
    "calibration": {
        "measured_at_0c": 0.0,
        "measured_at_100c": 100.0,
    },
    "auto_finish": {
        "enabled": True,
        "drop_c": 18.0,
        "window_sec": 25.0,
        "min_temp_c": 140.0,
    },
}


def ensure_json_file(path: Path, payload: Any) -> None:
    if path.exists():
        return
    path.write_text(json.dumps(payload, indent=2), encoding="utf-8")


def load_json(path: Path, default_payload: Any) -> Any:
    ensure_json_file(path, default_payload)
    with path.open("r", encoding="utf-8") as f:
        return json.load(f)


def load_profiles(path: Path) -> list[dict[str, Any]]:
    if not path.exists():
        print(f"Profiles path not found: {path}. Returning empty profile list.")
        return []

    if path.is_file():
        with path.open("r", encoding="utf-8") as f:
            payload = json.load(f)
        if isinstance(payload, list):
            return payload
        if isinstance(payload, dict):
            return [payload]
        raise ValueError("Profile file must contain an object or list of objects")

    if path.is_dir():
        profiles: list[dict[str, Any]] = []
        for file in sorted(path.glob("*.json")):
            with file.open("r", encoding="utf-8") as f:
                payload = json.load(f)
            if isinstance(payload, list):
                profiles.extend(payload)
            elif isinstance(payload, dict):
                profiles.append(payload)
            else:
                raise ValueError(f"Invalid profile payload in {file}")
        return profiles

    raise ValueError(f"Unsupported profiles path: {path}")


@dataclass
class Calibration:
    measured_at_0c: float
    measured_at_100c: float

    def apply(self, raw_c: float) -> float:
        lo = self.measured_at_0c
        hi = self.measured_at_100c
        if hi == lo:
            return raw_c
        return (raw_c - lo) * 100.0 / (hi - lo)


class SensorError(RuntimeError):
    pass


class SensorBase:
    def read_c(self) -> float:
        raise NotImplementedError

    def close(self) -> None:
        return


class MockSensor(SensorBase):
    def __init__(self, cfg: dict[str, Any]):
        self._noise = float(cfg.get("noise_c", 0.25))
        self._response = float(cfg.get("response", 0.24))
        self._cycle_sec = float(cfg.get("cycle_sec", 900.0))
        raw_curve = cfg.get("curve")
        if isinstance(raw_curve, list) and raw_curve:
            self._curve = sorted(
                [
                    (float(p["time_sec"]), float(p["temp_c"]))
                    for p in raw_curve
                    if isinstance(p, dict) and "time_sec" in p and "temp_c" in p
                ],
                key=lambda p: p[0],
            )
        else:
            self._curve = [
                (0.0, 205.0),   # charge / preheat probe temp
                (95.0, 92.0),   # turning point dip
                (270.0, 152.0), # drying complete (yellow)
                (500.0, 196.0), # around 1st crack
                (620.0, 209.0), # drop
                (760.0, 80.0),  # cooling
                (900.0, 34.0),  # end of cycle
            ]
        if len(self._curve) < 2:
            self._curve = [(0.0, 205.0), (900.0, 34.0)]

        self._cycle_sec = max(self._cycle_sec, self._curve[-1][0], 10.0)
        self._start = time.time()
        self._value = self._curve[0][1]

    def _target_for_elapsed(self, elapsed: float) -> float:
        t = elapsed % self._cycle_sec
        prev_t, prev_temp = self._curve[0]
        for next_t, next_temp in self._curve[1:]:
            if t <= next_t:
                span = max(next_t - prev_t, 1e-6)
                ratio = (t - prev_t) / span
                return prev_temp + (next_temp - prev_temp) * ratio
            prev_t, prev_temp = next_t, next_temp
        return self._curve[-1][1]

    def read_c(self) -> float:
        elapsed = time.time() - self._start
        target = self._target_for_elapsed(elapsed)
        self._value += (target - self._value) * self._response
        self._value += random.uniform(-self._noise, self._noise)
        return max(-20.0, self._value)


class Max6675Sensor(SensorBase):
    def __init__(self):
        try:
            from max6675 import MAX6675, build_max6675_env  # pylint: disable=import-error
        except Exception as exc:  # pragma: no cover
            raise SensorError(f"Failed to import MAX6675 dependencies: {exc}") from exc

        self._driver = MAX6675(*build_max6675_env())
        self._driver.__enter__()

    def read_c(self) -> float:
        try:
            return float(self._driver.temperature)
        except Exception as exc:
            raise SensorError(str(exc)) from exc

    def close(self) -> None:
        self._driver.__exit__(None, None, None)


class AppState:
    def __init__(self, config: dict[str, Any]):
        sensor_cfg = config.get("sensor", {})
        mode = sensor_cfg.get("mode", "mock").strip().lower()

        if mode == "max6675":
            self.sensor = Max6675Sensor()
        else:
            self.sensor = MockSensor(sensor_cfg.get("mock", {}))
            mode = "mock"

        calibration_cfg = config.get("calibration", {})
        self.calibration = Calibration(
            measured_at_0c=float(calibration_cfg.get("measured_at_0c", 0.0)),
            measured_at_100c=float(calibration_cfg.get("measured_at_100c", 100.0)),
        )
        self.mode = mode
        self.lock = threading.Lock()
        ror_cfg = config.get("ror", {})
        self.ror_window_sec = float(ror_cfg.get("window_sec", config.get("ror_window_sec", 30.0)))
        self.ror_min_span_sec = float(ror_cfg.get("min_span_sec", 5.0))
        self.ror_ema_alpha = max(0.0, min(1.0, float(ror_cfg.get("ema_alpha", 0.24))))
        self._recent_adjusted: deque[tuple[float, float]] = deque()
        self._last_ror_raw_c_per_min = 0.0
        self._last_ror_c_per_min = 0.0
        self._has_ror = False

    def read_temperature(self) -> dict[str, Any]:
        now_epoch = time.time()
        with self.lock:
            raw_c = self.sensor.read_c()
            adjusted_c = self.calibration.apply(raw_c)
            self._recent_adjusted.append((now_epoch, adjusted_c))

            cutoff = now_epoch - self.ror_window_sec
            while self._recent_adjusted and self._recent_adjusted[0][0] < cutoff:
                self._recent_adjusted.popleft()

            raw_ror_c_per_min = self._last_ror_raw_c_per_min
            if len(self._recent_adjusted) >= 2:
                t0, temp0 = self._recent_adjusted[0]
                for ts, temp in self._recent_adjusted:
                    if now_epoch - ts >= self.ror_min_span_sec:
                        t0, temp0 = ts, temp
                        break

                dt = now_epoch - t0
                if dt >= 0.5:
                    raw_ror_c_per_min = (adjusted_c - temp0) / dt * 60.0
            self._last_ror_raw_c_per_min = raw_ror_c_per_min

            if not self._has_ror:
                ror_c_per_min = raw_ror_c_per_min
                self._has_ror = True
            elif self.ror_ema_alpha <= 0.0:
                ror_c_per_min = raw_ror_c_per_min
            else:
                ror_c_per_min = (
                    self.ror_ema_alpha * raw_ror_c_per_min
                    + (1.0 - self.ror_ema_alpha) * self._last_ror_c_per_min
                )
            self._last_ror_c_per_min = ror_c_per_min

        return {
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "raw_c": round(raw_c, 3),
            "adjusted_c": round(adjusted_c, 3),
            "ror_c_per_min": round(ror_c_per_min, 3),
            "ror_raw_c_per_min": round(raw_ror_c_per_min, 3),
            "ror_ema_alpha": round(self.ror_ema_alpha, 3),
            "ror_window_sec": round(self.ror_window_sec, 3),
            "sensor_mode": self.mode,
        }

    def close(self) -> None:
        with self.lock:
            self.sensor.close()


class RoastHandler(BaseHTTPRequestHandler):
    state: AppState | None = None
    config: dict[str, Any] = {}
    profiles: list[dict[str, Any]] = []

    def log_message(self, fmt: str, *args: Any) -> None:  # keep stdout clean
        return

    def _json(self, status: int, payload: dict[str, Any]) -> None:
        data = json.dumps(payload).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def _read_json_body(self) -> dict[str, Any]:
        raw_len = int(self.headers.get("Content-Length", "0"))
        if raw_len == 0:
            return {}
        raw = self.rfile.read(raw_len)
        return json.loads(raw.decode("utf-8"))

    def _serve_static(self, rel_path: str) -> None:
        target = (STATIC_DIR / rel_path).resolve()
        try:
            target.relative_to(STATIC_DIR.resolve())
        except ValueError:
            self.send_error(HTTPStatus.NOT_FOUND)
            return
        if not target.exists() or not target.is_file():
            self.send_error(HTTPStatus.NOT_FOUND)
            return

        mime = "text/plain"
        suffix = target.suffix.lower()
        if suffix == ".html":
            mime = "text/html"
        elif suffix == ".css":
            mime = "text/css"
        elif suffix == ".js":
            mime = "application/javascript"
        elif suffix == ".json":
            mime = "application/json"

        data = target.read_bytes()
        self.send_response(HTTPStatus.OK)
        self.send_header("Content-Type", mime)
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def do_GET(self) -> None:  # pylint: disable=invalid-name
        parsed = urlparse(self.path)
        path = parsed.path

        if path == "/api/temperature":
            assert self.state is not None
            try:
                payload = self.state.read_temperature()
            except SensorError as exc:
                self._json(HTTPStatus.SERVICE_UNAVAILABLE, {"ok": False, "error": str(exc)})
                return

            payload["ok"] = True
            self._json(HTTPStatus.OK, payload)
            return

        if path == "/api/config":
            ror_payload = dict(self.config.get("ror", {}))
            ror_payload.setdefault("window_sec", self.state.ror_window_sec if self.state else 30.0)
            ror_payload.setdefault("min_span_sec", self.state.ror_min_span_sec if self.state else 5.0)
            ror_payload.setdefault("ema_alpha", self.state.ror_ema_alpha if self.state else 0.24)
            payload = {
                "ok": True,
                "poll_interval_sec": float(self.config.get("poll_interval_sec", 0.5)),
                "ror": ror_payload,
                "temp_guides": self.config.get(
                    "temp_guides",
                    {"charge_c": 205.0, "first_crack_c": 208.0, "drop_c": 212.0},
                ),
                "charge_ready": self.config.get(
                    "charge_ready",
                    {
                        "enabled": True,
                        "min_temp_c": 205.0,
                        "stable_window_sec": 20.0,
                        "max_abs_ror_c_per_min": 2.5,
                        "max_temp_span_c": 3.0,
                    },
                ),
                "auto_finish": self.config.get("auto_finish", {}),
                "sensor_mode": self.state.mode if self.state else "unknown",
            }
            self._json(HTTPStatus.OK, payload)
            return

        if path == "/api/profiles":
            self._json(HTTPStatus.OK, {"ok": True, "profiles": self.profiles})
            return

        if path in ("/", "/index.html"):
            self._serve_static("index.html")
            return

        if path.startswith("/static/"):
            self._serve_static(path.split("/static/", 1)[1])
            return

        self.send_error(HTTPStatus.NOT_FOUND)

    def do_POST(self) -> None:  # pylint: disable=invalid-name
        parsed = urlparse(self.path)
        if parsed.path != "/api/sessions":
            self.send_error(HTTPStatus.NOT_FOUND)
            return

        try:
            payload = self._read_json_body()
        except json.JSONDecodeError as exc:
            self._json(HTTPStatus.BAD_REQUEST, {"ok": False, "error": f"invalid json: {exc}"})
            return

        SESSIONS_DIR.mkdir(parents=True, exist_ok=True)
        stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        session_id = f"roast_{stamp}"
        session_file = SESSIONS_DIR / f"{session_id}.json"

        payload.setdefault("saved_at", datetime.now(timezone.utc).isoformat())
        session_file.write_text(json.dumps(payload, indent=2), encoding="utf-8")

        self._json(HTTPStatus.CREATED, {"ok": True, "session_id": session_id, "file": str(session_file.name)})


def build_server_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Coffee roast helper server")
    parser.add_argument("--config", default=str(CONFIG_PATH), help="Path to config JSON")
    parser.add_argument("--profiles", default=str(BASE_DIR / "profiles"), help="Path to roast profile JSON file or directory")
    parser.add_argument("--mock", action="store_true", help="Force mock sensor mode")
    return parser.parse_args()


def main() -> None:
    args = build_server_args()

    config_path = Path(args.config)
    profiles_path = Path(args.profiles)

    config = load_json(config_path, DEFAULT_CONFIG)
    profiles = load_profiles(profiles_path)

    if args.mock:
        config.setdefault("sensor", {})["mode"] = "mock"

    state = AppState(config)

    RoastHandler.state = state
    RoastHandler.config = config
    RoastHandler.profiles = profiles

    host = config.get("host", "0.0.0.0")
    port = int(config.get("port", 8000))

    server = ThreadingHTTPServer((host, port), RoastHandler)
    print(f"Roast helper server running on http://{host}:{port}")

    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        state.close()
        server.server_close()


if __name__ == "__main__":
    main()
