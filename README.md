# MAX6675 Coffee Roast Monitor

A Raspberry Pi 4 coffee-roasting helper using a MAX6675 thermocouple sensor.

It includes:
- A Python HTTP server for live temperature readings (`server.py`)
- Calibration support (0C and 100C reference points)
- A touch-friendly web UI with:
  - Real-time temperature and RoR (Rate of Rise)
  - Roast timer and post-1st-crack timer
  - 1st crack marker
  - Profile-based RoR guidance
  - Finish/reset flow with PNG + CSV export

## Project Layout

- `server.py`: HTTP server + sensor integration + RoR computation
- `max6675.py`: MAX6675 hardware driver wrapper
- `config.json`: runtime config (sensor mode, calibration, RoR window)
- `profiles/`: roast profiles loaded from JSON files
- `static/`: web UI (`index.html`, `styles.css`, `app.js`)
- `run_roast_helper.sh`: start server and open browser
- `stop_roast_helper.sh`: stop server started by launcher
- `scripts/calibrate_*.py`: calibration capture/apply helpers
- `tests/`: basic unit tests

## Requirements

Python 3.10+ recommended.

Install dependencies:

```bash
pip install -r requirements.txt
```

`requirements.txt` includes Raspberry Pi sensor runtime packages:
- `adafruit-blinka`
- `RPi.GPIO`

## Setup

1. Clone/copy this repo to your Pi.
2. Install dependencies.
3. Edit `config.json`:
   - For real sensor mode: set `"sensor": { "mode": "max6675", ... }`
   - For mock mode: set `"sensor": { "mode": "mock", ... }`
4. (Optional) Tune RoR settings in `config.json`:
   - `ror.window_sec`
   - `ror.min_span_sec`
   - `ror.ema_alpha` (0 disables EMA smoothing; typical range 0.15-0.35)
5. (Optional) Tune chart temperature guides:
   - `temp_guides.charge_c` (preheat/bean-charge guide)
   - `temp_guides.first_crack_c`
   - `temp_guides.drop_c`

## Start / Stop

### Quick start (recommended)

```bash
./run_roast_helper.sh
```

This will:
- start `server.py` in background (if not running)
- wait for readiness
- open the UI in your default browser (`xdg-open`)

Stop it:

```bash
./stop_roast_helper.sh
```

### Optional virtualenv for launcher

If you want launcher to activate a virtualenv first:

```bash
ROAST_HELPER_VENV=/path/to/venv ./run_roast_helper.sh
```

## Calibration (0C / 100C)

Recommended workflow:

```bash
./scripts/calibrate_workflow.sh
```

Manual steps:

```bash
python scripts/calibrate_capture.py --reference-c 0 --duration-sec 30 --interval-sec 0.5
python scripts/calibrate_capture.py --reference-c 100 --duration-sec 30 --interval-sec 0.5
python scripts/calibrate_apply.py
```

This updates `config.json` calibration fields:
- `calibration.measured_at_0c`
- `calibration.measured_at_100c`

Restart server after applying calibration.

## Using the UI

1. Open the app page (launcher opens it automatically).
2. Select a roast profile.
3. Press `Start` to begin recording.
4. Press `1st Crack` when first crack starts.
5. Monitor temp, RoR, stage guidance, and timers.
6. Press `Finish` to stop recording and auto-export plot/data.
7. Press `Reset` to clear state for next roast.

## Tests

Run basic tests:

```bash
python -m unittest discover -s tests -p 'test_*.py'
```

## Notes

- `plot.py` is legacy and not required for the web UI workflow.
- In mock mode, no GPIO hardware is required.
- Session JSON files are saved under `sessions/` when finishing a roast.
