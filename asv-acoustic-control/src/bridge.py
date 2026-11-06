#!/usr/bin/env python3
"""Vehicle bridge for the platform: acoustic commands in, goals for the platform out.

Usage, inside the platform's ROS 2 environment (workspace sourced):
    python3 bridge.py PORT [OPERATOR_ADDRESS] [--live] [--log FILE]
Example:
    python3 bridge.py /dev/serial/by-id/<modem-adapter> 255 --live

Commands it understands (typed on the Pi console):
    go A     publish the goal for place A (see PLACES) to the goal topic once a second,
             like the lab's example, until the platform is within 0.2 m or 120 s pass
    stop     stop publishing and publish the current position as the goal (hold)
    status   reply with position and heading
Everything else is answered NO NOTYET. Without --live nothing is published: the bridge
only prints what it WOULD do and replies DRY. Switch to ROS mode (B) yourself, and B back
to manual is the brake. Needs acoustic_protocol.py in the same folder.
"""
import argparse
import math
import os
import sys
import time
from datetime import datetime

import rclpy
import serial  # pip install pyserial
from geometry_msgs.msg import Pose
from nav_msgs.msg import Odometry
from rclpy.node import Node
from rclpy.qos import qos_profile_sensor_data

import acoustic_protocol as proto

REPLY_DELAY = 0.7           # seconds: let the modem finish its own acknowledgement first
GOAL_TOPIC = os.environ.get("GOAL_TOPIC", "/vehicle/cmd_pos")             # set GOAL_TOPIC to your platform's goal topic
ODOM_TOPIC = os.environ.get("ODOM_TOPIC", "/vehicle/odometry/filtered")   # set ODOM_TOPIC to its position topic
PLACES = {"A": (2.0, 2.0)}  # named places, map-frame metres (the lab's go-to example)
REPUBLISH_S = 1.0           # the lab's example repeats the goal once a second
ARRIVED_M = 0.2             # stop publishing when this close to the goal
GOAL_TIMEOUT_S = 120        # ... or after this long
MAX_POSE_AGE_S = 2.0        # a position older than this counts as missing
LOG = None                  # the open log file, set in main()


def log(text):
    """Write a timestamped line to the log file only."""
    if LOG:
        LOG.write(f"{datetime.now():%Y-%m-%d %H:%M:%S}  {text}\n")
        LOG.flush()


def say(text):
    """Print a line on the screen and write it to the log file."""
    print(f"{datetime.now():%H:%M:%S}  {text}", flush=True)
    log(text)


def yaw_deg(q):
    return math.degrees(math.atan2(2 * (q.w * q.z + q.x * q.y), 1 - 2 * (q.y ** 2 + q.z ** 2)))


def make_pose(x, y, q=None):
    pose = Pose()
    pose.position.x, pose.position.y, pose.position.z = x, y, 0.0
    if q is None:
        pose.orientation.w = 1.0  # facing +x, as in the lab's example
    else:
        pose.orientation.x, pose.orientation.y = q.x, q.y
        pose.orientation.z, pose.orientation.w = q.z, q.w
    return pose


class Bridge(Node):
    def __init__(self):
        super().__init__("acoustic_bridge")
        self.pose, self.pose_time = None, 0.0
        self.create_subscription(Odometry, ODOM_TOPIC, self.on_odom,
                                 qos_profile_sensor_data)
        self.pub = self.create_publisher(Pose, GOAL_TOPIC, 10)

    def on_odom(self, msg):
        self.pose, self.pose_time = msg.pose.pose, time.monotonic()

    def position(self):
        """(x, y, heading in degrees), or None when the position is missing or old."""
        if self.pose is None or time.monotonic() - self.pose_time > MAX_POSE_AGE_S:
            return None
        return self.pose.position.x, self.pose.position.y, yaw_deg(self.pose.orientation)


class Goal:
    """The place the platform is being sent to; republished until arrival or timeout."""

    def __init__(self):
        self.xy = None
        self.started = self.last_pub = self.last_say = 0.0

    def start(self, xy):
        self.xy, self.started = xy, time.monotonic()
        self.last_pub = self.last_say = 0.0

    def clear(self):
        self.xy = None


def tick(node, goal):
    """Called often: republish the active goal once a second, stop on arrival or timeout."""
    if goal.xy is None:
        return
    now, pos = time.monotonic(), node.position()
    left = math.hypot(goal.xy[0] - pos[0], goal.xy[1] - pos[1]) if pos else None
    if left is not None and left < ARRIVED_M:
        say(f"Arrived: {left:.2f} m from the goal. No longer publishing.")
        goal.clear()
    elif now - goal.started > GOAL_TIMEOUT_S:
        say("Goal timed out. No longer publishing (press B if it is still moving).")
        goal.clear()
    else:
        if now - goal.last_pub >= REPUBLISH_S:
            goal.last_pub = now
            node.pub.publish(make_pose(*goal.xy))
        if now - goal.last_say >= 5.0:
            goal.last_say = now
            say("  heading for the goal, " +
                ("position missing" if left is None else f"{left:.2f} m to go"))


def execute(node, goal, cmd, live):
    """Carry out one command. Returns (reply words, note for the screen)."""
    if cmd.verb == "STAT":
        pos = node.position()
        if pos is None:
            return ["NO", "NOPOS"], "no position available"
        return (["POS", round(pos[0] * 100), round(pos[1] * 100), round(pos[2])],
                f"position x={pos[0]:.2f} y={pos[1]:.2f} heading={pos[2]:.0f}")
    if cmd.verb == "GO":
        if cmd.arg not in PLACES:
            return ["NO", "UNKNOWN"], f"unknown place {cmd.arg}"
        if node.position() is None:
            return ["NO", "NOPOS"], "no position available: goal refused"
        x, y = PLACES[cmd.arg]
        if not live:
            return ["DRY"], f"WOULD DO: publish goal ({x:.1f}, {y:.1f}) once a second (dry run)"
        goal.start((x, y))
        return ["OK"], f"GO {cmd.arg}: publishing goal ({x:.1f}, {y:.1f}) once a second"
    if cmd.verb == "STOP":
        goal.clear()
        if not live:
            return ["DRY"], "WOULD DO: stop publishing and hold the current position (dry run)"
        if node.position() is None:
            return ["NO", "NOPOS"], "stopped publishing, but there is no position to hold: press B!"
        p = node.pose.position
        node.pub.publish(make_pose(p.x, p.y, node.pose.orientation))
        return ["OK"], "goal cancelled; current position published as the goal (hold)"
    return ["NO", "NOTYET"], f"{cmd.verb} is not implemented yet"


def handle(msg, cache, node, goal, live):
    """Return (reply text or None, note for the screen, kind)."""
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
    words, note = execute(node, goal, cmd, live)
    reply = proto.format_reply(cmd.seq, *words)
    cache.store(cmd.seq, reply)
    return reply, note, "new"


def main():
    global LOG
    ap = argparse.ArgumentParser(description="Acoustic vehicle bridge for the platform.")
    ap.add_argument("port")
    ap.add_argument("operator", type=int, nargs="?", default=255,
                    help="modem address the replies go to (default 255)")
    ap.add_argument("--live", action="store_true", help="really publish goals (default: dry run)")
    ap.add_argument("--log", default="/tmp/bridge_log.txt")
    args = ap.parse_args()
    try:
        ser = serial.Serial(args.port, 9600, bytesize=8, parity="N", stopbits=1, timeout=0.2)
    except serial.SerialException as err:
        sys.exit(f"Cannot open the modem port: {err}\n"
                 "Is the adapter plugged in, and is another program using it? Check with:\n"
                 "  ps aux | grep -E 'delphis|bridge' | grep -v grep")
    rclpy.init()
    node, goal, cache = Bridge(), Goal(), proto.ReplyCache()
    LOG = open(args.log, "a")
    counts = {"new": 0, "repeat": 0, "rejected": 0, "ignored": 0}
    buf, failed = b"", False
    mode = "LIVE" if args.live else "DRY-RUN"
    say(f"{mode} bridge started: port {args.port}, replies to modem {args.operator}, "
        f"log {args.log}")
    print("Ctrl+C to stop.")
    try:
        while True:
            rclpy.spin_once(node, timeout_sec=0)
            tick(node, goal)
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
                reply, note, kind = handle(msg, cache, node, goal, args.live)
                counts[kind] += 1
                say(f"  {note}")
                if reply:
                    time.sleep(REPLY_DELAY)
                    ser.write(proto.frame_unicast(args.operator, reply, ack=False))
                    say(f"> {reply}")
    except KeyboardInterrupt:
        print()
    except serial.SerialException as err:
        say(f"MODEM PORT ERROR: {err}")
        say("Another program may be using the port, or the adapter was unplugged.")
        failed = True
    finally:
        if goal.xy is not None:
            say("WARNING: a goal was still active. The platform may keep moving: press B.")
        say("Stopped. Messages received: " + ", ".join(f"{k} {v}" for k, v in counts.items()))
        ser.close()
        LOG.close()
        node.destroy_node()
        rclpy.shutdown()
    if failed:
        sys.exit(1)


if __name__ == "__main__":
    main()
