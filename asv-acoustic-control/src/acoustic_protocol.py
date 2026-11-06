"""Message format for acoustic control of the platform, shared by the operator console
(Raspberry Pi) and the vehicle bridge (platform computer). Pure Python, no ROS, no serial.

Commands (operator -> vehicle) are short ASCII texts, one per acoustic message:
    <seq> F|B|L|R <cm>     step forward / backward / left / right (sideways) by <cm>
    <seq> TL|TR <deg>      turn left / right on the spot by <deg>
    <seq> GO <name>        drive to a named place (the vehicle looks the name up)
    <seq> STOP             cancel the current move
    <seq> STAT             ask for position and heading
<seq> is a number from 1 to 99. Replies (vehicle -> operator) start with the same number:
    <seq> OK     <seq> NO BAD|FAR|...     <seq> POS <x_cm> <y_cm> <heading_deg>
"""
import re
import time
from collections import namedtuple

MAX_STEP_CM = 100  # largest single step
MAX_TURN_DEG = 90  # largest single turn

Command = namedtuple("Command", "seq verb arg")  # arg: int, place name or None
_CMD = re.compile(r"(\d{1,2}) ([A-Z]+)(?: (\w{1,8}))?", re.ASCII)


class ProtocolError(Exception):
    """reason is BAD (cannot be understood) or FAR (over the step or turn limit)."""

    def __init__(self, reason):
        super().__init__(reason)
        self.reason = reason


def parse_command(text):
    """Return a Command, or raise ProtocolError. Anything unclear is rejected."""
    m = _CMD.fullmatch(" ".join(text.upper().split()))
    if not m or not 1 <= int(m[1]) <= 99:
        raise ProtocolError("BAD")
    seq, verb, arg = int(m[1]), m[2], m[3]
    if verb in ("STOP", "STAT") and arg is None:
        return Command(seq, verb, None)
    if verb == "GO" and arg is not None:
        return Command(seq, verb, arg)
    if verb in ("F", "B", "L", "R", "TL", "TR") and arg is not None and arg.isdigit():
        limit = MAX_TURN_DEG if verb.startswith("T") else MAX_STEP_CM
        if not 1 <= int(arg) <= limit:
            raise ProtocolError("FAR")
        return Command(seq, verb, int(arg))
    raise ProtocolError("BAD")


def format_command(seq, verb, arg=None):
    """Build the text to send. Refuses anything the vehicle would reject."""
    text = f"{seq} {verb}" + ("" if arg is None else f" {arg}")
    parse_command(text)
    return text


def format_reply(seq, *words):
    return " ".join(str(w) for w in (seq, *words))


def parse_reply(text):
    """Return (seq, [words]) from a reply such as '12 OK' or '15 POS 120 85 90'."""
    parts = text.split()
    if len(parts) < 2 or not (parts[0].isascii() and parts[0].isdigit()):
        raise ProtocolError("BAD")
    return int(parts[0]), parts[1:]


def frame_unicast(address, text, ack=True):
    """The bytes to write to the modem: $M (with acknowledgement) or $U (without)."""
    data = text.encode("ascii")
    if not 0 <= address <= 255 or not 2 <= len(data) <= 64:
        raise ValueError("address must be 0-255 and the message 2-64 bytes")
    kind = "M" if ack else "U"
    return f"${kind}{address:03d}{len(data):02d}".encode("ascii") + data


def message_from_line(line):
    """The text of an incoming message from a modem line like '#U0712 F 50', else None."""
    m = re.fullmatch(r"#U(\d{2})(.*)", line, re.ASCII | re.DOTALL)
    return m[2] if m and int(m[1]) == len(m[2]) else None


class ReplyCache:
    """Vehicle side: if the same command number arrives again within ttl seconds (the
    operator did not hear our reply and resent it), repeat the reply without carrying
    out the command a second time."""

    def __init__(self, ttl=20.0):
        self.ttl, self.seq, self.reply, self.when = ttl, None, None, 0.0

    def lookup(self, seq):
        if seq == self.seq and time.monotonic() - self.when < self.ttl:
            return self.reply
        return None

    def store(self, seq, reply):
        self.seq, self.reply, self.when = seq, reply, time.monotonic()
