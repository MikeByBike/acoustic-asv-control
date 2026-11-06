# Acoustic remote control of a surface platform

Send short commands from a Raspberry Pi to a pool robot through the water, using two
Succorfish Delphis acoustic modems. A bridge program on the robot's computer checks each
message and turns `go A` into a position goal for the robot's own ROS 2 controller.

Status: **first trials, not a finished system.** It was built and tested during a SeaTecHub staff
exchange on a platform that belongs to a host laboratory. It moved that platform only under
supervision, with a person holding the joystick. Please read "Limitations" before you use any of it.

## How it works

```
Raspberry Pi 5                                   platform computer (ROS 2 Humble, in a container)
operator_console.py                              bridge.py
   |  serial, 9600 baud                             |  serial, 9600 baud
Delphis modem (address 255)  ~~ acoustic link ~~  Delphis modem (address 234)
                                                    |
                                       goal topic (a pose)  <-  the platform's own controller drives the thrusters
                                       odometry topic (position)  ->  bridge.py
```

- Messages are plain ASCII, at most 7 bytes for a command, for example `12 GO A`.
- The console sends one command at a time, waits for the reply, and retries (3 times, 5 for STOP).
- The bridge answers duplicate commands from a short memory, so a resend never moves the robot twice.
- `go A` publishes the fixed goal (2.0, 2.0) once a second until the robot is within 0.2 m or 120 s pass.

## Layout

| Path | What it is |
|---|---|
| `src/acoustic_protocol.py` | Message format, limits, modem framing, duplicate cache (no ROS, no serial) |
| `src/operator_console.py` | Interactive console for the Pi: `go A`, `stop`, `status` and more |
| `src/link_test.py` | Sends N harmless status requests and summarises how many were answered |
| `src/delphis_term.py` | Small terminal for the modem that sends each command in one burst |
| `src/dry_bridge.py` | Bridge in dry-run mode: checks commands, replies `DRY`, needs no ROS |
| `src/bridge.py` | The live bridge: needs ROS 2 and the platform's topics; dry run unless `--live` |
| `tests/test_protocol.py` | 10 unit tests for the message module |
| `experimental/` | Two scripts that were written but never used on the equipment |
| `data/` | Results of the repeated arrival-time test |

## Quick start

Operator side (Raspberry Pi):

```bash
python3 -m venv venv
venv/bin/pip install -r requirements.txt
venv/bin/python src/operator_console.py /dev/serial/by-id/<your-adapter> 234
```

Use the `/dev/serial/by-id/...` path of your modem's adapter. The numbered names (`ttyUSB0`) can change.
Wait about 7 seconds after powering a Delphis modem before the first command.

Platform side (inside the ROS 2 container, with the workspace sourced):

```bash
python3 src/dry_bridge.py <port> 255          # dry run, no ROS needed
python3 src/bridge.py <port> 255               # dry run (the default)
python3 src/bridge.py <port> 255 --live        # really publishes goals: only with supervision
```

Set `GOAL_TOPIC` (a `geometry_msgs/Pose` goal) and `ODOM_TOPIC` (a `nav_msgs/Odometry` position) to your platform's topic names before running the bridge. The defaults are generic placeholders.

Only one program may use a modem's serial port at a time.

Tests:

```bash
python3 -m unittest discover -s tests
```

## Results in short

- Link test, 20 status requests each: 20 of 20 answered at 1.5 m, 2 of 20 and 11 of 20 at 3 m, no replies
  in an attempt at 5 m whose setup was not verified. Median reply time 2.0 s.
- Repeated `go A` test, 17 counted attempts: 10 arrived within 0.2 m of the goal (median about 35 s,
  range 15 to 111 s). 12 of 17 came within 0.5 m (median about 30 s). Five timed out and two failed
  for reasons not known. See `data/arrival_attempts.csv`.
- Small pools are poor places to test acoustic modems (the modem manual says so too), so the 3 m and 5 m
  results say little about the modem's real range.

## Limitations

- There is no failsafe for a lost link, and `stop` (hold position) has not been tested on hardware.
- All tests were carried out within a pool which limits the acoustic signals
- There is no authentication: any modem that sends to the platform's address can issue commands.
- The only destination is the fixed place A. The coordinate frame of the goal topic is not settled, so
  other goals could send the robot the wrong way.
- Arrival within 0.2 m is unreliable and the reasons are not established.
- The programs were tested in simulation with stand-ins for the serial and ROS libraries. Real equipment
  was used only for the trials listed above.

## License

MIT, see `LICENSE`.
