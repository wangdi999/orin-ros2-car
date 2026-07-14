#!/usr/bin/env python3
"""Collect bounded ROS graph, topic-rate, command, and TF evidence."""

import json
import math
import time

from geometry_msgs.msg import Twist
from nav_msgs.msg import OccupancyGrid, Odometry
import rclpy
from rclpy.node import Node
from rclpy.qos import (
    QoSProfile,
    QoSDurabilityPolicy,
    QoSHistoryPolicy,
    QoSReliabilityPolicy,
)
from rclpy.time import Time
from sensor_msgs.msg import LaserScan
from std_msgs.msg import Bool, String
from tf2_ros import Buffer, TransformListener


SAMPLE_SECONDS = 8.0
DISCOVERY_TIMEOUT_SECONDS = 5.0


def main():
    """Run one subscriber-only probe and print a stable JSON snapshot."""
    rclpy.init()
    node = Node('read_only_navigation_evidence_probe')
    counts = {
        name: 0 for name in (
            'cmd_vel', 'scan', 'odom', 'connected', 'source',
            'safety', 'patrol', 'map', 'alarm_events')
    }
    last = {}
    nonzero_commands = [0]

    def callback(name):
        def receive(message):
            counts[name] += 1
            last[name] = message
            if name == 'cmd_vel':
                values = (
                    message.linear.x,
                    message.linear.y,
                    message.angular.z,
                )
                if not all(
                        math.isfinite(value) and abs(value) <= 1e-9
                        for value in values):
                    nonzero_commands[0] += 1
        return receive

    subscriptions = [
        node.create_subscription(
            Twist, '/cmd_vel', callback('cmd_vel'), 50),
        node.create_subscription(
            LaserScan, '/scan', callback('scan'), 20),
        node.create_subscription(
            Odometry, '/odom', callback('odom'), 100),
        node.create_subscription(
            OccupancyGrid, '/map', callback('map'), QoSProfile(
                history=QoSHistoryPolicy.KEEP_LAST,
                depth=1,
                reliability=QoSReliabilityPolicy.RELIABLE,
                durability=QoSDurabilityPolicy.TRANSIENT_LOCAL,
            )),
        node.create_subscription(
            Bool, '/chassis/connected', callback('connected'), 20),
        node.create_subscription(
            String, '/control/active_source', callback('source'), 20),
        node.create_subscription(
            String, '/safety/state', callback('safety'), 20),
        node.create_subscription(
            String, '/patrol/status', callback('patrol'), 20),
        node.create_subscription(
            String, '/alarm_events', callback('alarm_events'), 20),
    ]
    tf_buffer = Buffer()
    tf_listener = TransformListener(tf_buffer, node)

    core_topics = ('/cmd_vel', '/scan', '/odom')
    discovery_deadline = time.monotonic() + DISCOVERY_TIMEOUT_SECONDS
    while time.monotonic() < discovery_deadline:
        rclpy.spin_once(node, timeout_sec=0.05)
        if all(node.get_publishers_info_by_topic(topic)
               for topic in core_topics):
            break

    for name in counts:
        counts[name] = 0
    nonzero_commands[0] = 0
    started = time.monotonic()
    while time.monotonic() - started < SAMPLE_SECONDS:
        rclpy.spin_once(node, timeout_sec=0.05)
    elapsed = time.monotonic() - started

    important_topics = (
        '/cmd_vel', '/cmd_vel_manual', '/cmd_vel_nav', '/scan',
        '/odom', '/map', '/control/active_source', '/safety/state',
        '/chassis/connected', '/patrol/status', '/alarm',
        '/alarm_events', '/tf', '/tf_static')
    publishers = {}
    for topic in important_topics:
        publishers[topic] = sorted(
            info.node_name
            for info in node.get_publishers_info_by_topic(topic))

    transforms = {}
    for target, source, label in (
            ('odom', 'base_footprint', 'odom_to_base_footprint'),
            ('base_footprint', 'base_link', 'base_footprint_to_base_link'),
            ('base_link', 'laser_link', 'base_link_to_laser_link'),
            ('map', 'odom', 'map_to_odom')):
        transforms[label] = bool(
            tf_buffer.can_transform(target, source, Time()))

    topic_types = {
        name: sorted(types)
        for name, types in node.get_topic_names_and_types()
    }
    service_types = {
        name: sorted(types)
        for name, types in node.get_service_names_and_types()
    }
    result = {
        'schema': 'RosReadOnlySnapshot/v1',
        'read_only': True,
        'sample_window_sec': round(elapsed, 3),
        'nodes': sorted(node.get_node_names()),
        'topic_types': topic_types,
        'service_types': service_types,
        'publishers': publishers,
        'counts': counts,
        'rates_hz': {
            name: round(counts[name] / elapsed, 3)
            for name in (
                'cmd_vel', 'scan', 'odom', 'connected', 'safety', 'map')
        },
        'nonzero_cmd_vel_count': nonzero_commands[0],
        'last': {
            'scan_frame': (
                last['scan'].header.frame_id if 'scan' in last else None),
            'odom_frame': (
                last['odom'].header.frame_id if 'odom' in last else None),
            'odom_child_frame': (
                last['odom'].child_frame_id if 'odom' in last else None),
            'chassis_connected': (
                bool(last['connected'].data)
                if 'connected' in last else None),
            'active_source': (
                last['source'].data if 'source' in last else None),
            'safety_state': (
                last['safety'].data if 'safety' in last else None),
            'patrol_status': (
                last['patrol'].data if 'patrol' in last else None),
            'alarm_event': (
                last['alarm_events'].data
                if 'alarm_events' in last else None),
            'map_frame': (
                last['map'].header.frame_id if 'map' in last else None),
            'map_width': (
                int(last['map'].info.width) if 'map' in last else None),
            'map_height': (
                int(last['map'].info.height) if 'map' in last else None),
            'map_resolution': (
                float(last['map'].info.resolution)
                if 'map' in last else None),
        },
        'transforms': transforms,
    }
    print(json.dumps(result, indent=2, sort_keys=True))
    node.destroy_node()
    rclpy.shutdown()


if __name__ == '__main__':
    main()
