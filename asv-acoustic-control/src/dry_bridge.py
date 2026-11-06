#!/usr/bin/env python3
"""Vehicle bridge, DRY-RUN version: listens on the platform's Delphis modem, checks every
command, prints what it WOULD do and replies. It never touches ROS or the platform.

Usage:   python3 dry_bridge.py PORT [OPERATOR_ADDRESS] [LOGFILE]
Example: python3 dry_bridge.py /dev/serial/by-id/<modem-adapter> 255 /tmp/bridge_log.txt

Replies go to OPERATOR_ADDRESS, because a received message does not say who sent it.
Everything shown on the screen is also appended to LOGFILE (default /tmp/bridge_log.txt),
together with every raw line from the modem. On Ctrl+C it prints how many messages
it saw. Needs acoustic_protocol.py in the same folder.
"""
import sys
import time
from datetime import datetime

import serial  # pip install pyserial

import acoustic_protocol as proto

REPLY_DELAY = 0.7  # seconds: let the modem finish its own acknowledgement first
STEP_NAMES = {"F": "forward", "B": "back", "L": "left", "R": "right"}
LOG = None  # the open log file, set in main()


def log(text):
    """Write a timestamped line to the log file only."""
    if LOG:
        LOG.write(f"{datetime.now():%Y-%m-%d %H:%M:%S}  {text}\n")
        LOG.flush()


def say(text):
    """Print a line on the screen and write it to the log file."""
    print(f"{datetime.now():%H:%M:%S}  {text}", flush=True)
    log(text)


def describe(cmd):
    if cmd.verb in STEP_NAMES:
        return f"step {STEP_NAMES[cmd.verb]} {cmd.arg} cm"
    if cmd.verb in ("TL", "TR"):
        return f"turn {'left' if cmd.verb == 'TL' else 'right'} {cmd.arg} degrees"
    if cmd.verb == "GO":
        return f"drive to place {cmd.arg}"
    return "cancel the current move" if cmd.verb == "STOP" else "report position and heading"


def handle(msg, cache):
    """Return (reply or None, note for the screen, kind). Dry run: acts on nothing."""
    try:
        cmd = proto.parse_command(msg)
    except proto.ProtocolError as err:
        words = msg.split()
        if words and words[0].isascii() and words[0].isdigit() and 1 <= int(words[0]) <= 99:
            reply = proto.format_reply(int(words[0]), "NO", err.reason)
            return reply, f"rejected: {err.reason}", "rejected"
        return None, "no valid command number: ignored", "ignored"
    cached = cache.lookup(cmd.seq)
    if cached:
        note = "same number as the last command: repeating the reply, not the action"
        return cached, note, "repeat"
    reply = proto.format_reply(cmd.seq, "DRY")
    cache.store(cmd.seq, reply)
    note = f"WOULD DO: {describe(cmd)}  (dry run: nothing sent to the platform)"
    return reply, note, "new"


def main():
    global LOG
    args = sys.argv[1:]
    if not 1 <= len(args) <= 3:
        sys.exit(__doc__)
    operator = int(args[1]) if len(args) > 1 else 255
    log_path = args[2] if len(args) > 2 else "/tmp/bridge_log.txt"
    try:
        ser = serial.Serial(args[0], 9600, bytesize=8, parity="N", stopbits=1, timeout=0.2)
    except serial.SerialException as err:
        sys.exit(f"Cannot open the modem port: {err}\n"
                 "Is the adapter plugged in, and is another program using it? Check with:\n"
                 "  ps aux | grep -E 'delphis|dry_bridge' | grep -v grep")
    LOG = open(log_path, "a")
    counts = {"new": 0, "repeat": 0, "rejected": 0, "ignored": 0}
    cache, buf, failed = proto.ReplyCache(), b"", False
    say(f"DRY-RUN bridge started: port {args[0]}, replies to modem {operator}, log {log_path}")
    print("Ctrl+C to stop.")
    try:
        while True:
            buf += ser.read(64)
            while b"\n" in buf:
                line, buf = buf.split(b"\n", 1)
                line = line.decode("ascii", errors="replace").strip()
                if line:
                    log(f"raw: {line}")
                msg = proto.message_from_line(line)
                if msg is None:
                    if line.startswith("#"):
                        say(f"(modem says: {line})")
                    continue
                say(f"< {msg}")
                reply, note, kind = handle(msg, cache)
                counts[kind] += 1
                say(f"  {note}")
                if reply:
                    time.sleep(REPLY_DELAY)
                    ser.write(proto.frame_unicast(operator, reply, ack=False))
                    say(f"> {reply}")
    except KeyboardInterrupt:
        print()
    except serial.SerialException as err:
        say(f"MODEM PORT ERROR: {err}")
        say("Another program may be using the port, or the adapter was unplugged.")
        failed = True
    finally:
        say("Stopped. Messages received: " + ", ".join(f"{k} {v}" for k, v in counts.items()))
        ser.close()
        LOG.close()
    if failed:
        sys.exit(1)


if __name__ == "__main__":
    main()
