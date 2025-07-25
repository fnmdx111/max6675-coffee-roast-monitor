import time
import matplotlib.pyplot as plt
from collections import deque
from max6675 import MAX6675, build_max6675_env


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

    start_time = time.time()
    ror_window = 30
    recent_temps = deque()

    with MAX6675(*build_max6675_env()) as sensor:
        while True:
            now = time.time()
            t_min = (now - start_time) / 60

            try:
                temp = sensor.temperature
            except Exception as e:
                print(f"Read error: {e}")
                time.sleep(1)
                continue

            print(f"{t_min:5.2f} min | Temp: {temp:.2f} C")

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

            ax1.set_xlim(max(0, t_min - 2), t_min + 0.5)
            ax1.figure.canvas.draw()
            ax1.figure.canvas.flush_events()

            time.sleep(1)


if __name__ == "__main__":
    crack_marks = []

    plt.ion()
    fig, ax1 = plt.subplots()
    fig.suptitle("Temp and RoR")

    try:
        main(fig, ax1, crack_marks)
    except KeyboardInterrupt:
        plt.ioff()

        for label, x in crack_marks:
            color = "purple"
            ax1.axvline(x=x, color=color, linestyle="--")
            ax1.text(x, ax1.get_ylim()[1] - 5, label, rotation=90, color=color, ha="right", va="top")

        fig.tight_layout()
        plt.savefig(f"curve.png", dpi=300)
        plt.show()
