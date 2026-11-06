#!/usr/bin/env python3
"""Minimal terminal for a Succorfish Delphis modem (9600 baud, 8N1, no flow control).

Usage:  python3 delphis_term.py /dev/serial/by-id/<your-modem-adapter>

Type a command such as  $?  and press Enter. Replies are printed as they arrive,
including messages that come in later from the other modem. Type q to quit.

Each command is sent in ONE write: the modem times out if bytes arrive more than
2 ms apart, so a normal serial terminal (which sends keystrokes one by one)
does not work well.
"""
import re
import sys
import threading
import time

import serial  # pip install pyserial

# Reply to $?  ->  #A<address>V<voltage code>R<firmware>B<build date>
STATUS = re.compile(r"#A(\d{3})V(\d{5})R(\d{3}\.\d{3}\.\d{3})B(\S+)")


def reader(ser, stop):
    buf = b""
    while not stop.is_set():
        buf += ser.read(64)  # returns after the 0.2 s timeout if nothing arrives
        while b"\n" in buf:
            line, buf = buf.split(b"\n", 1)
            text = line.decode("ascii", errors="replace").strip()
            if not text:
                continue
            print(f"\n{time.strftime('%H:%M:%S')}  < {text}")
            m = STATUS.match(text)
            if m:
                volts = int(m.group(2)) * 15 / 65536
                print(f"          address {int(m.group(1))}, supply {volts:.2f} V, "
                      f"firmware {m.group(3)}")
            print("> ", end="", flush=True)


def main():
    if len(sys.argv) != 2:
        sys.exit(__doc__)
    ser = serial.Serial(sys.argv[1], 9600, bytesize=8, parity="N", stopbits=1,
                        timeout=0.2)
    stop = threading.Event()
    threading.Thread(target=reader, args=(ser, stop), daemon=True).start()
    print("Connected. After powering the modem, wait about 7 s before sending anything.")
    try:
        while True:
            cmd = input("> ").strip()
            if cmd.lower() == "q":
                break
            if not cmd.startswith("$"):
                print("Commands start with $ (for example $?)")
                continue
            if cmd.startswith("$A") and input(
                    "$A changes the address stored in the modem. Type yes to continue: "
            ) != "yes":
                continue
            ser.write(cmd.encode("ascii"))  # one write, no terminator needed
    finally:
        stop.set()
        ser.close()


if __name__ == "__main__":
    main()
