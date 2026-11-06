#!/usr/bin/env python3
"""Operator console: send small movement commands to the platform over the Delphis modem.

Usage:   python3 operator_console.py PORT [TARGET_ADDRESS]
Example: python3 operator_console.py /dev/serial/by-id/<your-adapter> 234

Commands (type, then Enter):
    forward 50   back 50   left 50   right 50    step by that many cm (f, b, l, r work too)
    turn left 30   turn right 30                  turn by that many degrees (tl, tr work too)
    go A                                          drive to a named place
    stop                                          cancel the current move
    status                                        ask for position and heading
    q                                             quit
Needs acoustic_protocol.py in the same folder.
"""
import random
import sys
import time

import serial  # pip install pyserial

import acoustic_protocol as proto

REPLY_WAIT = 8.0         # seconds to wait for the vehicle's reply after each send
DEFAULT_ATTEMPTS = 3     # sends per command (the same number is reused, so no double move)
ATTEMPTS = {"STOP": 5}   # STOP is retried harder
WORDS = {"forward": "F", "f": "F", "back": "B", "backward": "B", "b": "B",
         "left": "L", "l": "L", "right": "R", "r": "R", "tl": "TL", "tr": "TR",
         "go": "GO", "stop": "STOP", "status": "STAT", "stat": "STAT"}


def to_verb_arg(line):
    """'forward 50' -> ('F', '50'); 'turn left 30' -> ('TL', '30'). Raises ValueError."""
    words = line.lower().split()
    if len(words) > 1 and words[0] == "turn" and words[1] in ("left", "right"):
        words = ["tl" if words[1] == "left" else "tr"] + words[2:]
    if not words or words[0] not in WORDS or len(words) > 2:
        raise ValueError("unknown command")
    return WORDS[words[0]], (words[1].upper() if len(words) == 2 else None)


def describe(words):
    """Turn a vehicle reply into a sentence for the operator."""
    if words == ["OK"]:
        return "OK: the platform accepted it"
    if words[0] == "NO":
        reasons = {"BAD": "it did not understand the command",
                   "FAR": "it is over the platform's limit"}
        why = words[1] if len(words) > 1 else ""
        return "REFUSED: " + reasons.get(why, " ".join(words[1:]) or "no reason given")
    if words[0] == "POS" and len(words) == 4:
        try:
            x, y, h = (int(w) for w in words[1:])
            return f"position x={x / 100:.2f} m, y={y / 100:.2f} m, heading {h} degrees"
        except ValueError:
            pass
    return "reply: " + " ".join(words)


def attempt(ser, address, seq, text):
    """Send once. Returns (result, words): reply | no_ack | no_reply | modem_error."""
    ser.reset_input_buffer()
    ser.write(proto.frame_unicast(address, text))  # one write: the modem needs one burst
    deadline = time.monotonic() + REPLY_WAIT
    buf, acked = b"", False
    while time.monotonic() < deadline:
        buf += ser.read(64)
        while b"\n" in buf:
            line, buf = buf.split(b"\n", 1)
            line = line.decode("ascii", errors="replace").strip()
            if line == "E":
                return "modem_error", None
            if line.startswith("#TO"):
                return "no_ack", None  # the other modem never acknowledged the message
            if line.startswith("#R"):
                acked = True  # the other modem heard it
            msg = proto.message_from_line(line)
            if msg is not None:
                try:
                    got_seq, words = proto.parse_reply(msg)
                except proto.ProtocolError:
                    continue
                if got_seq == seq:
                    return "reply", words
    return ("no_reply" if acked else "no_ack"), None


def send_command(ser, address, seq, verb, arg):
    """Send with retries. Returns True if the platform replied. Raises ProtocolError."""
    text = proto.format_command(seq, verb, arg)
    attempts = ATTEMPTS.get(verb, DEFAULT_ATTEMPTS)
    for n in range(1, attempts + 1):
        print(f"  sending '{text}' (attempt {n}/{attempts})")
        result, words = attempt(ser, address, seq, text)
        if result == "reply":
            print("  " + describe(words))
            return True
        if result == "modem_error":
            print("  your modem rejected the command, not retrying")
            return False
        print("  no reply: " + ("the other modem heard it, but nothing answered"
                                if result == "no_reply" else "no acknowledgement"))
    return False


def main():
    if len(sys.argv) not in (2, 3):
        sys.exit(__doc__)
    address = int(sys.argv[2]) if len(sys.argv) == 3 else 234
    ser = serial.Serial(sys.argv[1], 9600, bytesize=8, parity="N", stopbits=1, timeout=0.2)
    seq = random.randint(1, 99)  # random start, so a new session never repeats old numbers
    print(f"Console ready, talking to modem {address}. Type q to quit.")
    try:
        while True:
            line = input("> ").strip()
            if line.lower() in ("q", "quit", "exit"):
                break
            if not line:
                continue
            try:
                verb, arg = to_verb_arg(line)
            except ValueError:
                print("  unknown command. Try: forward 50, left 30, turn right 45, go A, stop, status")
                continue
            seq = seq % 99 + 1  # 1..99, then wraps
            try:
                ok = send_command(ser, address, seq, verb, arg)
            except proto.ProtocolError as err:
                what = "over the limit" if err.reason == "FAR" else "not a valid command"
                print(f"  not sent: {what} (steps up to {proto.MAX_STEP_CM} cm, "
                      f"turns up to {proto.MAX_TURN_DEG} degrees)")
                continue
            if not ok and verb == "STOP":
                print("  !! STOP NOT CONFIRMED. Assume the platform may still be moving: "
                      "use the joystick.")
            elif not ok:
                print("  !! No confirmation. The platform may or may not have received it. "
                      "Use 'status' or 'stop' to find out.")
    except (KeyboardInterrupt, EOFError):
        print()
    finally:
        ser.close()


if __name__ == "__main__":
    main()
