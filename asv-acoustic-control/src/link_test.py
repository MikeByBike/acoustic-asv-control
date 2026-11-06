#!/usr/bin/env python3
"""Measure how reliable the acoustic link is: send STAT requests and count the replies.

Usage:   python3 link_test.py PORT [TARGET] [COUNT] [GAP_SECONDS]
Example: python3 link_test.py /dev/serial/by-id/<your-adapter> 234 20 10

Sends COUNT harmless STAT requests (default 20), GAP_SECONDS apart (default 10), each
with the console's retry rules, and prints a summary. Every result is also appended to
link_test.csv. The bridge must be running on the platform.
Needs operator_console.py and acoustic_protocol.py in the same folder.
"""
import csv
import random
import statistics
import sys
import time
from datetime import datetime

import serial  # pip install pyserial

import acoustic_protocol as proto
import operator_console as oc


def one_trial(ser, address, seq):
    """Return (outcome, attempts used, seconds). outcome: ok, no_ack, no_reply, modem_error."""
    text = proto.format_command(seq, "STAT")
    start = time.monotonic()
    result = "no_ack"
    for n in range(1, oc.DEFAULT_ATTEMPTS + 1):
        result, _ = oc.attempt(ser, address, seq, text)
        if result in ("reply", "modem_error"):
            break
    return ("ok" if result == "reply" else result), n, time.monotonic() - start


def summarize(rows):
    n = len(rows)
    if not n:
        return
    first = sum(1 for o, a, _ in rows if o == "ok" and a == 1)
    retried = sum(1 for o, a, _ in rows if o == "ok" and a > 1)
    silent = sum(1 for o, _, _ in rows if o == "no_reply")
    lost = sum(1 for o, _, _ in rows if o in ("no_ack", "modem_error"))
    times = [s for o, _, s in rows if o == "ok"]
    print(f"\nSummary of {n} requests:")
    print(f"  answered on the first try:  {first}")
    print(f"  answered after a retry:     {retried}")
    print(f"  failed, other modem heard it but nothing answered: {silent}")
    print(f"  failed, never acknowledged: {lost}")
    print(f"  answered overall: {first + retried} of {n} ({100 * (first + retried) / n:.0f} %)")
    if times:
        print(f"  median time to a reply: {statistics.median(times):.1f} s")


def main():
    args = sys.argv[1:]
    if not 1 <= len(args) <= 4:
        sys.exit(__doc__)
    address = int(args[1]) if len(args) > 1 else 234
    count = int(args[2]) if len(args) > 2 else 20
    gap = float(args[3]) if len(args) > 3 else 10.0
    ser = serial.Serial(args[0], 9600, bytesize=8, parity="N", stopbits=1, timeout=0.2)
    seq, rows = random.randint(1, 99), []
    print(f"Sending {count} STAT requests to modem {address}, {gap:.0f} s apart. Ctrl+C to stop.")
    try:
        with open("link_test.csv", "a", newline="") as f:
            log = csv.writer(f)
            for i in range(1, count + 1):
                seq = seq % 99 + 1
                outcome, attempts, seconds = one_trial(ser, address, seq)
                rows.append((outcome, attempts, seconds))
                log.writerow([datetime.now().strftime("%Y-%m-%d %H:%M:%S"), address,
                              outcome, attempts, f"{seconds:.1f}"])
                f.flush()
                print(f"{i:>3}/{count}  {outcome:<12} attempts={attempts}  {seconds:.1f} s",
                      flush=True)
                if i == 3 and all(r[0] != "ok" for r in rows):
                    print("The first 3 all failed: nothing is answering. Is the bridge "
                          "running on the platform? Stopping.")
                    break
                if i < count:
                    time.sleep(gap)
    except KeyboardInterrupt:
        print("\nStopped early.")
    finally:
        ser.close()
    summarize(rows)


if __name__ == "__main__":
    main()
