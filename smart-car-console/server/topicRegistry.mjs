export const TOPIC_REGISTRY = [
  {
    key: 'cmdVelManual',
    topic: '/cmd_vel_manual',
    type: 'geometry_msgs/msg/Twist',
    direction: 'publish',
    queueLength: 1,
    description: 'Manual command input to the sole command arbiter'
  },
  {
    key: 'safetyEstop',
    topic: '/safety/estop',
    type: 'std_msgs/msg/Bool',
    direction: 'publish',
    queueLength: 1,
    description: 'Latched emergency-stop request'
  },
  {
    key: 'scan',
    topic: '/scan',
    type: 'sensor_msgs/LaserScan',
    direction: 'subscribe',
    throttleRate: 120,
    queueLength: 1,
    description: 'Lidar scan for local occupancy and safety'
  },
  {
    key: 'map',
    topic: '/map',
    type: 'nav_msgs/OccupancyGrid',
    direction: 'subscribe',
    throttleRate: 750,
    queueLength: 1,
    optional: true,
    description: 'Global occupancy grid when SLAM/map server is available'
  },
  {
    key: 'odom',
    topic: '/odom',
    type: 'nav_msgs/Odometry',
    direction: 'subscribe',
    throttleRate: 100,
    queueLength: 1,
    optional: true,
    description: 'Robot pose fallback when TF is unavailable'
  },
  {
    key: 'tf',
    topic: '/tf',
    type: 'tf2_msgs/msg/TFMessage',
    direction: 'subscribe',
    throttleRate: 50,
    queueLength: 1,
    optional: true,
    description: 'Dynamic transforms used to resolve map to base_footprint'
  },
  {
    key: 'tfStatic',
    topic: '/tf_static',
    type: 'tf2_msgs/msg/TFMessage',
    direction: 'subscribe',
    throttleRate: 0,
    queueLength: 10,
    optional: true,
    description: 'Transient static transforms used by map pose resolution'
  },
  {
    key: 'amclPose',
    topic: '/amcl_pose',
    type: 'geometry_msgs/msg/PoseWithCovarianceStamped',
    direction: 'subscribe',
    throttleRate: 100,
    queueLength: 1,
    optional: true,
    description: 'Preferred fresh global localization pose'
  },
  {
    key: 'globalPath',
    topic: '/plan',
    type: 'nav_msgs/msg/Path',
    direction: 'subscribe',
    throttleRate: 250,
    queueLength: 1,
    optional: true,
    description: 'Nav2 global planner path'
  },
  {
    key: 'localPath',
    topic: '/local_plan',
    type: 'nav_msgs/msg/Path',
    direction: 'subscribe',
    throttleRate: 250,
    queueLength: 1,
    optional: true,
    description: 'Nav2 controller local path'
  },
  {
    key: 'globalCostmap',
    topic: '/global_costmap/costmap',
    type: 'nav_msgs/msg/OccupancyGrid',
    direction: 'subscribe',
    throttleRate: 750,
    queueLength: 1,
    optional: true,
    description: 'Nav2 global costmap, downsampled for the browser'
  },
  {
    key: 'localCostmap',
    topic: '/local_costmap/costmap',
    type: 'nav_msgs/msg/OccupancyGrid',
    direction: 'subscribe',
    throttleRate: 750,
    queueLength: 1,
    optional: true,
    description: 'Nav2 local costmap, downsampled for the browser'
  },
  {
    key: 'navigateStatus',
    topic: '/navigate_to_pose/_action/status',
    type: 'action_msgs/msg/GoalStatusArray',
    direction: 'subscribe',
    throttleRate: 200,
    queueLength: 1,
    optional: true,
    description: 'Read-only NavigateToPose action status'
  },
  {
    key: 'navigationStatus',
    topic: '/navigation/status',
    type: 'std_msgs/msg/String',
    direction: 'subscribe',
    throttleRate: 100,
    queueLength: 1,
    optional: true,
    description: 'Unified single-goal, patrol, and return-home status'
  },
  {
    key: 'imuRaw',
    topic: '/imu/data_raw',
    type: 'sensor_msgs/Imu',
    direction: 'subscribe',
    throttleRate: 200,
    queueLength: 1,
    description: 'Raw IMU telemetry'
  },
  {
    key: 'imuMag',
    topic: '/imu/mag',
    type: 'sensor_msgs/MagneticField',
    direction: 'subscribe',
    throttleRate: 200,
    queueLength: 1,
    description: 'Magnetometer telemetry'
  },
  {
    key: 'voltage',
    topic: '/voltage',
    type: 'std_msgs/Float32',
    direction: 'subscribe',
    throttleRate: 200,
    queueLength: 1,
    description: 'Main battery voltage'
  },
  {
    key: 'velRaw',
    topic: '/vel_raw',
    type: 'geometry_msgs/Twist',
    direction: 'subscribe',
    throttleRate: 100,
    queueLength: 1,
    description: 'Chassis velocity feedback'
  },
  {
    key: 'jointStates',
    topic: '/joint_states',
    type: 'sensor_msgs/JointState',
    direction: 'subscribe',
    throttleRate: 200,
    queueLength: 1,
    optional: true,
    description: 'Raw chassis joint diagnostic; not treated as encoder feedback on X3'
  },
  {
    key: 'alarmEvents',
    topic: '/alarm_events',
    type: 'std_msgs/String',
    direction: 'subscribe',
    throttleRate: 100,
    queueLength: 10,
    optional: true,
    description: 'Optional car-side alarm events as JSON or text'
  },
  {
    key: 'alarm',
    topic: '/alarm',
    type: 'car_interfaces/msg/Alarm',
    direction: 'subscribe',
    throttleRate: 100,
    queueLength: 10,
    optional: true,
    description: 'Typed safety and navigation alarm stream'
  },
  {
    key: 'activeSource',
    topic: '/control/active_source',
    type: 'std_msgs/msg/String',
    direction: 'subscribe',
    throttleRate: 100,
    queueLength: 1,
    description: 'Arbiter-selected command source'
  },
  {
    key: 'safetyState',
    topic: '/safety/state',
    type: 'std_msgs/msg/String',
    direction: 'subscribe',
    throttleRate: 100,
    queueLength: 1,
    description: 'Authoritative safety state heartbeat'
  },
  {
    key: 'chassisConnected',
    topic: '/chassis/connected',
    type: 'std_msgs/msg/Bool',
    direction: 'subscribe',
    throttleRate: 100,
    queueLength: 1,
    description: 'Chassis driver connection heartbeat'
  },
  {
    key: 'patrolStatus',
    topic: '/patrol/status',
    type: 'std_msgs/msg/String',
    direction: 'subscribe',
    throttleRate: 100,
    queueLength: 1,
    description: 'Patrol state and return-home authorization heartbeat'
  },
  {
    key: 'patrolRoute',
    topic: '/patrol/route',
    type: 'nav_msgs/msg/Path',
    direction: 'subscribe',
    throttleRate: 500,
    queueLength: 1,
    description: 'Transient-local read-only configured patrol route'
  }
];

export function subscriptionTopics() {
  return TOPIC_REGISTRY
    .filter((entry) => entry.direction === 'subscribe')
    .map((entry) => ({
      topic: entry.topic,
      type: rosbridgeMessageType(entry.type),
      throttleRate: entry.throttleRate,
      queueLength: entry.queueLength
    }));
}

function rosbridgeMessageType(type) {
  return String(type).replace('/msg/', '/').replace('/srv/', '/');
}

export function publicTopicRegistry() {
  return TOPIC_REGISTRY.map((entry) => ({ ...entry }));
}
