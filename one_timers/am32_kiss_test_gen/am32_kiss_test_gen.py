#!/usr/bin/env python3
import argparse
import math
import random
import struct
import time


PACKET_INTERVAL_S = 0.030
CRC8_POLY = 0x07
UINT16_MODULO = 0x10000


class SineValue:
    def __init__(self, minimum, maximum):
        self.minimum = minimum
        self.maximum = maximum
        self.phase = random.random() * math.tau

    def next(self, dt):
        period = random.uniform(5.0, 20.0)
        self.phase = (self.phase + (math.tau * dt / period)) % math.tau
        normalized = (math.sin(self.phase) + 1.0) * 0.5
        return self.minimum + normalized * (self.maximum - self.minimum)


def update_crc8(value, crc_seed):
    crc = (value ^ crc_seed) & 0xFF
    for _ in range(8):
        if crc & 0x80:
            crc = ((crc << 1) ^ CRC8_POLY) & 0xFF
        else:
            crc = (crc << 1) & 0xFF
    return crc


def get_crc8(data):
    crc = 0
    for value in data:
        crc = update_crc8(value, crc)
    return crc


def clamp_u16(value):
    return max(0, min(0xFFFF, int(round(value))))


def build_packet(temperature_c, voltage_v, current_a, consumption_mah, erpm):
    temperature = max(0, min(0xFF, int(round(temperature_c))))
    voltage_centivolts = clamp_u16(voltage_v * 100.0)
    current_centiamps = clamp_u16(current_a * 100.0)
    erpm_hundreds = clamp_u16(erpm / 100.0)

    payload = struct.pack(
        ">BHHHH",
        temperature,
        voltage_centivolts,
        current_centiamps,
        consumption_mah,
        erpm_hundreds,
    )
    return payload + bytes((get_crc8(payload),))


def open_serial(port, baud):
    try:
        import serial
    except ImportError as exc:
        raise SystemExit("pyserial is required when --port is specified. Install it with: pip install pyserial") from exc

    return serial.Serial(port=port, baudrate=baud, bytesize=8, parity="N", stopbits=1, timeout=0)


def parse_args():
    parser = argparse.ArgumentParser(description="Generate AM32 KISS telemetry packets.")
    parser.add_argument("-p", "--port", help="Serial port to write packets to, for example COM6 or /dev/ttyUSB0.")
    parser.add_argument("-b", "--baud", type=int, default=115200, help="Serial baud rate. Default: 115200.")
    return parser.parse_args()


def main():
    args = parse_args()
    serial_port = open_serial(args.port, args.baud) if args.port else None

    signals = {
        "temperature": SineValue(20.0, 80.0),
        "voltage": SineValue(23.0, 25.0),
        "current": SineValue(0.0, 100.0),
        "erpm": SineValue(0.0, 10000.0),
    }
    consumption = 0
    next_send = time.monotonic()

    try:
        while True:
            now = time.monotonic()
            if now < next_send:
                time.sleep(next_send - now)
                now = time.monotonic()

            temperature = signals["temperature"].next(PACKET_INTERVAL_S)
            voltage = signals["voltage"].next(PACKET_INTERVAL_S)
            current = signals["current"].next(PACKET_INTERVAL_S)
            erpm = signals["erpm"].next(PACKET_INTERVAL_S)
            packet = build_packet(temperature, voltage, current, consumption, erpm)

            if serial_port is not None:
                serial_port.write(packet)

            print(
                f"temp={temperature:5.1f}C "
                f"voltage={voltage:5.2f}V "
                f"current={current:6.2f}A "
                f"consumption={consumption:5d}mAh "
                f"erpm={erpm:7.1f} "
                f"packet={packet.hex(' ')}",
                flush=True,
            )

            consumption = (consumption + 1) % UINT16_MODULO
            next_send += PACKET_INTERVAL_S
            if next_send < now:
                next_send = now + PACKET_INTERVAL_S
    except KeyboardInterrupt:
        print("\nStopped.")
    finally:
        if serial_port is not None:
            serial_port.close()


if __name__ == "__main__":
    main()
