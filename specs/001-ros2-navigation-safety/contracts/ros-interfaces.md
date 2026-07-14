# ROS Interface Contract: ROS2 Navigation Safety

**Target**: ROS 2 Foxy
**Namespace**: root namespace unless launch explicitly remaps it
**Rule**: table owner is the only expected publisher/server in a valid runtime.

## 1. Command Topics

| Name | Type | Owner | Consumers | QoS / timeout | Contract |
|---|---|---|---|---|---|
| `/cmd_vel_manual` | `geometry_msgs/msg/Twist` | Windows console / approved manual teleop | `cmd_vel_arbiter` | reliable, volatile, depth 1; 300 ms freshness | Human request only; finite values; lateral motion allowed within policy |
| `/cmd_vel_nav` | `geometry_msgs/msg/Twist` | Nav2 controller via launch remap | `cmd_vel_arbiter` | reliable, volatile, depth 1; 300 ms freshness | Autonomous request; `linear.y` must be zero |
| `/cmd_vel` | `geometry_msgs/msg/Twist` | `cmd_vel_arbiter` only | X3 driver | reliable, volatile, depth 1; driver watchdog 300 ms | Final hardware boundary; zero when blocked/stale/switching |
| `/safety/estop` | `std_msgs/msg/Bool` | control console or approved safety input | `safety_manager` | reliable, volatile, depth 10; true is latched | `true` requests immediate stop; `false` only clears input, not latch |

Emergency exception: if the normal chain is unavailable, an SSH fallback may publish exactly one zero Twist to `/cmd_vel`; it may never send a non-zero value.

## 2. State and Health Topics

| Name | Type | Owner | Nominal rate | Allowed values / rule |
|---|---|---|---:|---|
| `/control/active_source` | `std_msgs/msg/String` | `cmd_vel_arbiter` | on change + 2 Hz heartbeat | `NONE`, `ZEROING`, `MANUAL`, `NAVIGATION`, `RETURN_HOME`, `BLOCKED` |
| `/safety/state` | `std_msgs/msg/String` | `safety_manager` | on change + 10 Hz heartbeat | states in [data-model.md](../data-model.md#4-safetystate); arbiter fails closed after 0.30 s stale |
| `/chassis/connected` | `std_msgs/msg/Bool` | X3 driver | 10 Hz and immediately on change | true only after serial is open and telemetry I/O succeeds; stale after 0.30 s |
| `/patrol/status` | `std_msgs/msg/String` | `patrol_manager` | on change; 10 Hz active / 2 Hz idle heartbeat | compact JSON with schema below |
| `/navigation/status` | `std_msgs/msg/String` | `patrol_manager` | same cadence as `/patrol/status` | unified JSON state for single-goal, patrol, and return-home ownership; includes `goal_id` |
| `/voltage` | `std_msgs/msg/Float32` | X3 driver | existing 10 Hz | finite volts; safety manager keeps 10-sample mean |
| `/vel_raw` | `geometry_msgs/msg/Twist` | X3 driver | existing 10 Hz | measured chassis velocity; finite values |
| `/odom_raw` | `nav_msgs/msg/Odometry` | `base_node_X3` | ≥ 20 Hz target | `odom` frame, `base_footprint` child; no TF publication |
| `/odom` | `nav_msgs/msg/Odometry` | robot_localization EKF | ≥ 20 Hz | canonical odometry consumed by Cartographer/Nav2 |
| `/scan` | `sensor_msgs/msg/LaserScan` | SLLIDAR | ≥ 5 Hz | `header.frame_id == laser_link` |

### `/patrol/status` JSON

```json
{
  "state": "IDLE",
  "mode": "PATROL",
  "waypoint": "point_a",
  "index": 0,
  "attempt": 0,
  "route_configured": true,
  "reason": ""
}
```

Required `state`: `IDLE | NAVIGATING | ARRIVED | WAITING | NEXT_GOAL | CANCELLING`. `route_configured` is true only after all measured coordinates pass validation; low-battery simulation and patrol services reject false. Fields not applicable to `IDLE` use empty string or `-1`; no credentials or raw exception traces.

During `LOW_BATTERY_RETURN`, this topic is also the fail-closed authorization and result handshake. The arbiter may label/output `RETURN_HOME` only while a message no older than 0.30 s has `mode=RETURN_HOME` and `state=NAVIGATING`. `reason=home_reached` drives `RETURNED_HOME`; `reason=return_failed` drives `RETURN_FAILED`. Any stale, malformed or conflicting status produces zero output.

## 3. Alarm Topics

### `/alarm`

- Type: `car_interfaces/msg/Alarm`
- Owner: each safety-aware node may publish its own source codes; `(source, code)` is the identity.
- QoS: reliable, volatile, depth 50.
- Consumers: console adapter, evidence collector, optional operator tooling.

```text
std_msgs/Header header
uint8 INFO=0
uint8 WARNING=1
uint8 ERROR=2
uint8 CRITICAL=3
uint8 severity
string code
string source
string state
string message
bool active
```

Required codes:

| Code | Severity | Active until |
|---|---:|---|
| `CMD_TIMEOUT` | WARNING | new valid request or state remains intentionally idle |
| `INVALID_CMD` | ERROR | valid request observed and explicit reset if latched |
| `ESTOP_ACTIVE` | CRITICAL | estop input false and reset accepted |
| `CHASSIS_DISCONNECTED` | CRITICAL | connection restored and reset accepted |
| `SCAN_STALE` | ERROR | scan fresh and reset accepted |
| `ODOM_TF_STALE` | CRITICAL | odom/TF healthy and reset accepted |
| `OWNERSHIP_CONFLICT` | CRITICAL | expected topic/mode owners restored and reset accepted |
| `NAV_GOAL_FAILED` | ERROR | emitted as event; may be immediately inactive after record |
| `WAYPOINT_SKIPPED` | WARNING | event record |
| `LOW_BATTERY_RETURN` | ERROR | returned Home or reset after simulation |
| `RETURN_HOME_FAILED` | CRITICAL | manual recovery and reset accepted |

### `/alarm_events`

- Type: `std_msgs/msg/String`
- Owner: alarm compatibility adapter in `safety_manager` and `patrol_manager`.
- Payload: JSON representation of the same Alarm fields for the current console telemetry path.
- This compatibility topic never controls safety behavior.

## 4. Services

All services use `std_srvs/srv/Trigger` in Foxy. `success=false` must include an operator-readable reason in `message` and must not change a safe latch unless all preconditions pass.

| Name | Server | Preconditions | Success effect |
|---|---|---|---|
| `/safety/reset` | `safety_manager` | estop false; required health fresh; output zero; no active action | clears eligible latch and transitions to `READY` |
| `/safety/simulate_low_battery` | `safety_manager` | navigation mode, valid Home, localization healthy, no existing low-battery run | emits low-battery request consumed by patrol manager |
| `/patrol/start` | `patrol_manager` | safety `READY`; route configured and valid; no active run | starts route at first waypoint |
| `/patrol/cancel` | `patrol_manager` | always callable | cancels active goal, reaches `IDLE`; idempotent when idle |
| `/patrol/return_home` | `patrol_manager` | localization healthy; configured Home; no safety state that forbids controlled return | cancels existing run and starts Home goal |
| `/navigation/send_goal` | `patrol_manager` | navigation mode; safety ready; no active single-goal, patrol, or return-home run | accepts `car_interfaces/srv/NavigatePose {x,y,yaw}` and starts one map-frame goal |
| `/navigation/cancel` | `patrol_manager` | always callable | cancels whichever coordinator-owned goal is active; idempotent when idle |
| `/patrol/reload_route` | `patrol_manager` | coordinator idle; configured route file remains valid | reloads Home plus exactly three waypoints without restarting Nav2 |

The low-battery service does not itself bypass the safety state. `safety_manager` enters `LOW_BATTERY_RETURN`; `patrol_manager` observes it, cancels the old goal and reports `mode=RETURN_HOME` through `/patrol/status`. The arbiter then permits only fresh return-home navigation, and safety consumes the same status for success/failure. No second control topic can accidentally authorize motion.

## 5. Navigation Action

| Interface | Type | Client | Server | Notes |
|---|---|---|---|---|
| `/navigate_to_pose` | `nav2_msgs/action/NavigateToPose` | `patrol_manager` | Nav2 BT Navigator | goal pose frame `map`; one active goal per patrol run |

Foxy-specific result contract:

```text
# Result
std_msgs/Empty result
```

`patrol_manager` must use action status (`STATUS_SUCCEEDED`, `STATUS_ABORTED`, `STATUS_CANCELED`), goal acceptance, cancel response, configured timeout and local attempt count. It must not access post-Foxy error-code fields.

## 6. TF Ownership

| Transform | Mode | Sole owner | Frequency / type |
|---|---|---|---|
| `base_footprint → base_link` | all | robot_state_publisher from URDF | static |
| `base_link → imu_link` | all | robot_state_publisher from URDF | static |
| `base_link → laser_link` | all | robot_state_publisher from URDF | static |
| `base_link → camera_link` | all | robot_state_publisher from URDF | static |
| `odom → base_footprint` | all active modes | robot_localization EKF | dynamic ≥ 20 Hz |
| `map → odom` | mapping | Cartographer | dynamic |
| `map → odom` | navigation | AMCL | dynamic |

`mapping.launch.py` and `navigation.launch.py` are mutually exclusive. `base_node_X3` parameter `pub_odom_tf` is forced false. No `laser → laser_link` compatibility TF is allowed.

## 7. Required Parameters

### Driver

| Parameter | Default | Constraint |
|---|---:|---|
| `xlinear_limit` | 0.35 | `0 < value ≤ 0.35` |
| `ylinear_limit` | 0.35 | `0 < value ≤ 0.35` |
| `angular_limit` | 0.80 | `0 < value ≤ 0.80` |
| `command_timeout_sec` | 0.30 | `0.05..0.30` |
| `reconnect_interval_sec` | 5.0 | `≥ 1.0` |

### Arbiter

| Parameter | Initial value | Constraint |
|---|---:|---|
| `manual_timeout_sec` | 0.30 | `≤ driver timeout` |
| `nav_timeout_sec` | 0.30 | `≤ driver timeout` |
| `max_linear_x/y` | 0.10 | `≤ 0.35`; first movement override to 0.05 |
| `max_angular_z` | 0.40 | `≤ 0.80`; first movement override to 0.20 |
| `zero_cycles_on_switch` | 1 | integer `≥ 1` |
| `safety_state_timeout_sec` | 0.30 | all non-zero output fails closed if safety manager heartbeat stops |
| `patrol_status_timeout_sec` | 0.30 | return-home authorization fails closed when stale |

### Safety

| Parameter | Default | Rule |
|---|---:|---|
| `scan_timeout_sec` | 0.50 | stale locks safety after startup grace |
| `odom_timeout_sec` | 0.20 | stale locks safety after startup grace |
| `startup_grace_sec` | 5.0 | output remains zero |
| `chassis_timeout_sec` | 0.30 | 10 Hz heartbeat stale threshold |
| `ownership_check_period_sec` | 0.20 | graph conflict must be detected within stop-latency gate |
| `enable_real_low_battery` | false | must remain false this feature |
| `low_battery_window` | 10 | sample count |
| `low_battery_threshold_v` | 10.8 | trigger threshold |
| `low_battery_recovery_v` | 11.1 | must exceed trigger threshold |
| `low_battery_sustain_sec` | 5.0 | continuous duration |

## 8. Launch-mode Contract

- `safe_base.launch.py`: driver, base odometry, IMU filter, EKF, robot_state_publisher, lidar frame fix, arbiter, safety manager. No mapping or localization owner. Driver rejects non-zero `/cmd_vel` whenever the graph does not show exactly the expected arbiter publisher.
- `mapping.launch.py`: includes safe base plus Cartographer and occupancy grid; rejects/does not include AMCL/Nav2 localization.
- `navigation.launch.py`: includes safe base plus map server, AMCL, NavFn/DWB/BT Navigator and patrol manager; no Cartographer.
- `demo.launch.py`: navigation mode only, requires `route.configured=true`; otherwise fails before any goal is sent.

Runtime ownership guard: after startup grace, safety manager locks `OWNERSHIP_FAULT` if `/cmd_vel`, `/odom` or `/scan` publisher identity/count differs from this contract, or if AMCL and Cartographer coexist. The driver independently fail-closes non-zero commands on a `/cmd_vel` owner mismatch. TF transform uniqueness is additionally checked by the non-motion evidence gate because a `TFMessage` does not carry per-transform publisher identity.

## 9. Console Contract

- Every manual drive operation advertises/publishes `/cmd_vel_manual`, never `/cmd_vel`.
- Emergency stop publishes `/safety/estop=true` and may additionally use the documented zero-only fallback if rosbridge safety services/topics are unavailable.
- Reset invokes `/safety/reset` and surfaces its `success/message`; it never silently clears local UI state on service failure.
- Service startup reports safe-base, mapping and navigation mode separately and never starts mapping and navigation together.
- The local-only web API owns serialized mode/map operations, managed files under `/home/jetson/maps` and `/home/jetson/routes`, and publishes initial pose only on standard `/initialpose` in frame `map` with X/Y covariance `0.25 m²` and yaw covariance `0.0685 rad²`.
- Motion warning acknowledgement gates non-zero manual control, single goals, patrol, return-home, and low-battery simulation. Zero commands, cancellation, and manual emergency stop always remain callable.
- Browser/API heartbeat loss raises a critical alarm and requests repeated zero manual commands; it does not publish `/safety/estop=true`. The driver and arbiter watchdogs remain fail-closed.
