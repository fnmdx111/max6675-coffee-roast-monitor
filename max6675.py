import time
import struct
import board
import digitalio
import busio
import RPi.GPIO as GPIO


class MAX6675:
    def __init__(self, spi, cs):
        self._spi = spi
        self._cs = cs
        self._cs.direction = digitalio.Direction.OUTPUT
        self._cs.value = True

    def read_raw(self):
        buf = bytearray(2)
        self._cs.value = False
        time.sleep(0.001)
        self._spi.readinto(buf)
        self._cs.value = True
        return (buf[0] << 8) | buf[1]

    @property
    def temperature(self):
        raw = self.read_raw()
        if raw & 0x4:
            raise RuntimeError("No thermocouple connected")
        return ((raw >> 3) & 0x0FFF) * 0.25

    def __enter__(self):
        while not self._spi.try_lock():
            pass
        self._spi.configure(baudrate=500000, phase=0, polarity=0)
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        self._spi.unlock()


def build_max6675_env():
    spi = busio.SPI(clock=board.SCK, MISO=board.MISO, MOSI=None)
    cs = digitalio.DigitalInOut(board.D8)

    return spi, cs


if __name__ == "__main__":
    with MAX6675(*build_max6675_env()) as sensor:
        print(f"test {sensor.temperature:.2f}")
