#!/usr/bin/env python3
"""Ping a Delphis modem at a fixed interval and log every result to a CSV file.

Usage:  python3 delphis_ping_log.py PORT TARGET [INTERVAL_SECONDS]
Example: python3 delphis_ping_log.py /dev/serial/by-id/<your-adapter> 234 300

PORT is your own modem's serial port, TARGET is the address of the modem to ping,
INTERVAL_SECONDS defaults to 300 (5 minutes, minimum 10). Results are appended to
ping_log.csv in the current folder. Stop with Ctrl+C.

Only one program can use the serial port at a time: close delphis_term.py first.
"""
import csv
import os
import re
import sys
import time
from datetime import datetime

import serial  # pip install pyserial

REPLY = re.compile(r"#R(\d{3})T(\d+)")
METRES_PER_COUNT = 1500 * 3.125e-5  # manual: range = T x c x 3.125e-5, c = 1500 m/s


def ping(ser, target, timeout):
    """Send one ping and return (result, T). Result: ok, timeout, error or no_reply."""
    ser.reset_input_buffer()
    ser.write(f"$P{target:03d}".encode("ascii"))  # one write: modem needs one burst
    deadline = time.monotonic() + timeout
    buf = b""
    while time.monotonic() < deadline:
        buf += ser.read(64)
        while b"\n" in buf:
            line, buf = buf.split(b"\n", 1)
            text = line.decode("ascii", errors="replace").strip()
            if text == "E":
                return "error", None
            if text.startswith("#TO"):
                return "timeout", None
            m = REPLY.match(text)
            if m:
                return "ok", int(m.group(2))
    return "no_reply", None  # the modem said nothing at all: check power and cable


def run(port, target, interval, outfile="ping_log.csv", ping_timeout=6.0, max_pings=None):
    ser = serial.Serial(port, 9600, bytesize=8, parity="N", stopbits=1, timeout=0.2)
    new_file = not os.path.exists(outfile) or os.path.getsize(outfile) == 0
    ok = total = 0
    next_time = time.monotonic()
    try:
        with open(outfile, "a", newline="") as f:
            log = csv.writer(f)
            if new_file:
                log.writerow(["time", "target", "result", "T", "range_m"])
            while True:
                result, t = ping(ser, target, ping_timeout)
                total += 1
                ok += result == "ok"
                t_txt = "-" if t is None else str(t)
                r_txt = "-" if t is None else f"{t * METRES_PER_COUNT:.2f}"
                now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
                log.writerow([now, target, result, "" if t is None else t,
                              "" if t is None else r_txt])
                f.flush()
                print(f"{now}  {result:<8} T={t_txt:<6} range={r_txt} m  "
                      f"({ok}/{total} ok)", flush=True)
                if max_pings is not None and total >= max_pings:
                    break
                next_time += interval
                time.sleep(max(0.0, next_time - time.monotonic()))
    finally:
        ser.close()


def main():
    if len(sys.argv) not in (3, 4):
        sys.exit(__doc__)
    port, target = sys.argv[1], int(sys.argv[2])
    interval = float(sys.argv[3]) if len(sys.argv) == 4 else 300.0
    if not 0 <= target <= 255 or interval < 10:
        sys.exit("TARGET must be 0-255 and INTERVAL at least 10 seconds.")
    print(f"Pinging address {target} every {interval:.0f} s. Ctrl+C to stop.")
    try:
        run(port, target, interval)
    except KeyboardInterrupt:
        print("\nStopped.")
    except serial.SerialException as err:
        sys.exit(f"Serial port problem: {err}")


if __name__ == "__main__":
    main()
