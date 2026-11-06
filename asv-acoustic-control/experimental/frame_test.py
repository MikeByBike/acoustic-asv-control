#!/usr/bin/env python3
"""Supervised test move for the platform: goal = current position + (DX, DY) metres.

Usage, inside the platform's ROS 2 environment (workspace sourced):
    python3 frame_test.py DX DY
Example:  python3 frame_test.py 0.8 0

It reads the odometry topic, shows the goal, and publishes ONE goal to
the goal topic (settings ODOM_TOPIC and GOAL_TOPIC) only after you switch to ROS mode (B) and type yes. The goal keeps the
current heading. It then prints the position every second for 40 s and a summary.
Press B (manual mode) at any time to take over.

Safety limits: each offset must be within 1.0 m, and the test is refused unless x and
y are about equal (within 0.4 m). That way the move is the same size whichever frame
(map or map_ned, which swaps x and y) the goal topic is read in.
"""
import math
import os
import sys
import time

import rclpy
from geometry_msgs.msg import Pose
from nav_msgs.msg import Odometry
from rclpy.node import Node
from rclpy.qos import qos_profile_sensor_data

GOAL_TOPIC = os.environ.get("GOAL_TOPIC", "/vehicle/cmd_pos")
ODOM_TOPIC = os.environ.get("ODOM_TOPIC", "/vehicle/odometry/filtered")
MAX_OFFSET = 1.0        # metres, per axis
MAX_DIAGONAL_GAP = 0.4  # metres: largest allowed |x - y| at the start
WATCH_SECONDS = 40


def yaw_deg(q):
    return math.degrees(math.atan2(2 * (q.w * q.z + q.x * q.y), 1 - 2 * (q.y ** 2 + q.z ** 2)))


class Nudge(Node):
    def __init__(self):
        super().__init__("frame_test")
        self.odom = None
        self.create_subscription(Odometry, ODOM_TOPIC, self.on_odom,
                                 qos_profile_sensor_data)
        self.pub = self.create_publisher(Pose, GOAL_TOPIC, 10)

    def on_odom(self, msg):
        self.odom = msg

    def spin_for(self, seconds):
        end = time.monotonic() + seconds
        while time.monotonic() < end:
            rclpy.spin_once(self, timeout_sec=0.05)

    def wait_for_odom(self, timeout):
        end = time.monotonic() + timeout
        self.odom = None
        while self.odom is None and time.monotonic() < end:
            rclpy.spin_once(self, timeout_sec=0.1)
        return self.odom


def pose_tuple(node):
    if node.odom is None:
        return None
    p = node.odom.pose.pose
    return p.position.x, p.position.y, yaw_deg(p.orientation)


def run(node, dx, dy):
    odom = node.wait_for_odom(5.0)
    if odom is None:
        sys.exit(f"No position on {ODOM_TOPIC}. Is the platform software running, "
                 "and does the camera see the tag? Nothing was sent.")
    p, q = odom.pose.pose.position, odom.pose.pose.orientation
    if abs(p.x - p.y) > MAX_DIAGONAL_GAP:
        sys.exit(f"Refused: x={p.x:.2f} and y={p.y:.2f} differ by more than {MAX_DIAGONAL_GAP} m. "
                 "Drive the platform with the joystick to where x and y are about equal "
                 "(for example near x=2, y=2), then run this again. Nothing was sent.")
    start = (p.x, p.y, yaw_deg(q))
    goal = Pose()
    goal.position.x, goal.position.y, goal.position.z = p.x + dx, p.y + dy, 0.0
    goal.orientation = q
    print(f"Now:  x={start[0]:.2f}  y={start[1]:.2f}  heading={start[2]:.0f} deg")
    print(f"Goal: x={goal.position.x:.2f}  y={goal.position.y:.2f}  "
          f"(offset dx={dx:+.2f}, dy={dy:+.2f}), same heading")
    answer = input("Switch to ROS mode with B now, then type yes to publish this goal ONCE: ")
    if answer.strip().lower() != "yes":
        sys.exit("Cancelled. Nothing was sent.")
    end = time.monotonic() + 5.0
    while node.pub.get_subscription_count() < 1 and time.monotonic() < end:
        rclpy.spin_once(node, timeout_sec=0.1)
    if node.pub.get_subscription_count() < 1:
        sys.exit(f"Nobody is listening on {GOAL_TOPIC}. Is navigation running? Nothing was sent.")
    node.pub.publish(goal)
    print("Goal sent. Press B for manual mode at any time.", flush=True)
    last = start
    try:
        for t in range(1, WATCH_SECONDS + 1):
            node.spin_for(1.0)
            now = pose_tuple(node)
            if now is None:
                print(f"{t:>3} s  no position")
                continue
            last = now
            dist = math.hypot(goal.position.x - now[0], goal.position.y - now[1])
            print(f"{t:>3} s  x={now[0]:.2f}  y={now[1]:.2f}  heading={now[2]:.0f}  "
                  f"to goal {dist:.2f} m", flush=True)
    except KeyboardInterrupt:
        print("\nStopped watching. Press B for manual mode if it is still moving.")
    print(f"\nRequested move: dx={dx:+.2f} m, dy={dy:+.2f} m")
    print(f"Actual move:    dx={last[0] - start[0]:+.2f} m, dy={last[1] - start[1]:+.2f} m, "
          f"heading change {last[2] - start[2]:+.0f} deg")


def main():
    if len(sys.argv) != 3:
        sys.exit(__doc__)
    dx, dy = float(sys.argv[1]), float(sys.argv[2])
    if abs(dx) > MAX_OFFSET or abs(dy) > MAX_OFFSET:
        sys.exit(f"Refused: each offset must be within {MAX_OFFSET} m.")
    rclpy.init()
    node = Nudge()
    try:
        run(node, dx, dy)
    except KeyboardInterrupt:
        print("\nInterrupted. Press B for manual mode if the platform is still moving.")
    finally:
        node.destroy_node()
        rclpy.shutdown()


if __name__ == "__main__":
    main()
