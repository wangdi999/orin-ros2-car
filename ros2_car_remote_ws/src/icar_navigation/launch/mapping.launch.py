"""Mutually exclusive Cartographer mapping mode."""

import os

from ament_index_python.packages import get_package_share_directory
from launch import LaunchDescription
from launch.actions import (
    DeclareLaunchArgument,
    IncludeLaunchDescription,
    SetEnvironmentVariable,
)
from launch.launch_description_sources import PythonLaunchDescriptionSource
from launch.substitutions import LaunchConfiguration
from launch_ros.actions import Node


def generate_launch_description():
    """Launch safe base plus the sole mapping map-to-odom owner."""
    share = get_package_share_directory('icar_navigation')
    configuration_directory = os.path.join(share, 'config')
    fastdds_profile = os.path.join(
        configuration_directory, 'fastdds_localhost.xml')

    arguments = [
        DeclareLaunchArgument('max_linear', default_value='0.10'),
        DeclareLaunchArgument('max_angular', default_value='0.40'),
        DeclareLaunchArgument('startup_grace_sec', default_value='12.0'),
        DeclareLaunchArgument('start_driver', default_value='true'),
        DeclareLaunchArgument('start_lidar', default_value='true'),
        DeclareLaunchArgument('lidar_frame', default_value='laser_link'),
    ]
    safe_base = IncludeLaunchDescription(
        PythonLaunchDescriptionSource(os.path.join(
            share, 'launch', 'safe_base.launch.py')),
        launch_arguments={
            'runtime_mode': 'mapping',
            'startup_grace_sec': LaunchConfiguration(
                'startup_grace_sec'),
            'max_linear': LaunchConfiguration('max_linear'),
            'max_angular': LaunchConfiguration('max_angular'),
            'start_driver': LaunchConfiguration('start_driver'),
            'start_lidar': LaunchConfiguration('start_lidar'),
            'lidar_frame': LaunchConfiguration('lidar_frame'),
        }.items(),
    )
    cartographer = Node(
        package='cartographer_ros',
        executable='cartographer_node',
        name='cartographer_node',
        output='screen',
        arguments=[
            '-configuration_directory', configuration_directory,
            '-configuration_basename', 'cartographer_2d.lua',
            '-start_trajectory_with_default_topics',
        ],
        remappings=[('scan', '/scan'), ('odom', '/odom')],
    )
    occupancy_grid = Node(
        package='cartographer_ros',
        executable='occupancy_grid_node',
        name='cartographer_occupancy_grid',
        output='screen',
        arguments=['-resolution', '0.05', '-publish_period_sec', '1.0'],
    )
    return LaunchDescription([
        SetEnvironmentVariable(
            name='ROS_LOCALHOST_ONLY', value='1'),
        SetEnvironmentVariable(
            name='FASTRTPS_DEFAULT_PROFILES_FILE', value=fastdds_profile),
    ] + arguments + [
        safe_base,
        cartographer,
        occupancy_grid,
    ])
