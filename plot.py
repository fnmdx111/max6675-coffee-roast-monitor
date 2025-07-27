import json
import datetime
import time
import matplotlib.pyplot as plt
from collections import deque
from max6675 import MAX6675, build_max6675_env
import sys

import logging
logger = logging.getLogger(__name__)


timestamp = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")

start_time = time.time()
def get_t_min():
    now = time.time()
    return now, (now - start_time) / 60


def shutdown(crack_marks, fig):
    logger.info(json.dumps({"event": "shutdown", "t": get_t_min()[1]}))
    plt.ioff()

    for x in crack_marks:
        color = "green"
        ax1.axvline(x=x, color=color, linestyle="--")
        ax1.text(x, ax1.get_ylim()[1] - 5, "crack recorded", rotation=90, color=color, ha="right", va="top")

    fig.tight_layout()
    plt.savefig(f"{timestamp}.png", dpi=300)

    sys.exit(0)


def main(fig, ax1, crack_marks):
    ax1.set_xlabel("Time (min)")
    ax1.set_ylabel("Temperature (C)", color="tab:red")
    ax1.set_ylim(0, 230)
    ax1.set_xlim(0, 12)
    temp_line, = ax1.plot([], [], color="tab:red", label="Temp")

    ax2 = ax1.twinx()
    ax2.set_ylabel("Rate of Rise (C/min)", color="tab:blue")
    ax2.set_ylim(0, 30)
    ror_line, = ax2.plot([], [], color="tab:blue", linestyle="--", label="RoR")

    x_data = []
    temp_data = []
    ror_data = []

    ror_window = 30
    recent_temps = deque()

    with MAX6675(*build_max6675_env()) as sensor:
        while True:
            now, t_min = get_t_min()

            try:
                temp = sensor.temperature
            except Exception as e:
                logger.error(json.dumps({"event": "error", "error": str(e), "t": t_min}))
                time.sleep(1)
                continue

            logger.info(json.dumps({"event": "temp", "temp": f"{temp:.2f}", "t": t_min}))

            x_data.append(t_min)
            temp_data.append(temp)
            recent_temps.append((now, temp))

            while recent_temps and now - recent_temps[0][0] > ror_window:
                recent_temps.popleft()

            if len(recent_temps) >= 2:
                t0, temp0 = recent_temps[0]
                ror = (temp - temp0) / (now - t0) * 60
            else:
                ror = 0

            ror_data.append(ror)

            temp_line.set_data(x_data, temp_data)
            ror_line.set_data(x_data, ror_data)

            ax1.set_xlim(0, t_min + 0.5)
            ax1.figure.canvas.draw()
            ax1.figure.canvas.flush_events()

            time.sleep(1)


def on_click_handler(fig, ax1, crack_marks):
    def handler(event):
        _, x = get_t_min()
        if event.button == 1:
            crack_marks.append(x)
            ax1.axvline(x=x, color="green", linestyle="--")
            ax1.text(x, ax1.get_ylim()[1] - 5, "crack recorded", rotation=90, color="green", ha="right", va="top")
            logger.info(json.dumps({"event": "crack", "t": x}))

    return handler


if __name__ == "__main__":
    logging.basicConfig(filename=f"{timestamp}.log", level=logging.INFO)

    crack_marks = []

    plt.ion()
    fig, ax1 = plt.subplots()
    fig.suptitle("Temp and RoR")

    fig.canvas.mpl_connect("button_press_event", on_click_handler(fig, ax1, crack_marks))
    fig.canvas.mpl_connect("close_event", lambda e: shutdown(crack_marks, fig))

    try:
        main(fig, ax1, crack_marks)
    except KeyboardInterrupt:
        shutdown(crack_marks, fig)
