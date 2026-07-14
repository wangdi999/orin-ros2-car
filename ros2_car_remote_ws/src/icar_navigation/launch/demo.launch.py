"""Navigation demo launch with an explicit opt-in patrol start."""

import os

from ament_index_python.packages import get_package_share_directory
from launch import LaunchDescription
from launch.actions import (
    DeclareLaunchArgument,
    ExecuteProcess,
    IncludeLaunchDescription,
    SetEnvironmentVariable,
    TimerAction,
)
from launch.conditions import IfCondition
from launch.launch_description_sources import PythonLaunchDescriptionSource
from launch.substitutions import LaunchConfiguration


def generate_launch_description():
    """Launch navigation; auto-start remains false until a physical-test gate."""
    share = get_package_share_directory('icar_navigation')
    default_map = os.path.join(share, 'maps', 'campus_map.yaml')
    default_route = os.path.join(share, 'config', 'patrol_route.yaml')
    fastdds_profile = os.path.join(
        share, 'config', 'fastdds_localhost.xml')
    auto_start = LaunchConfiguration('auto_start_patrol')
    navigation = IncludeLaunchDescription(
        PythonLaunchDescriptionSource(os.path.join(
            share, 'launch', 'navigation.launch.py')),
        launch_arguments={
            'map': LaunchConfiguration('map'),
            'route_file': LaunchConfiguration('route_file'),
            'max_linear': LaunchConfiguration('max_linear'),
            'max_angular': LaunchConfiguration('max_angular'),
            'start_driver': LaunchConfiguration('start_driver'),
            'start_lidar': LaunchConfiguration('start_lidar'),
        }.items(),
    )
    start_patrol = TimerAction(
        period=10.0,
        condition=IfCondition(auto_start),
        actions=[ExecuteProcess(
            cmd=[
                'ros2', 'service', 'call', '/patrol/start',
                'std_srvs/srv/Trigger', '{}',
            ],
            output='screen',
        )],
    )
    return LaunchDescription([
        SetEnvironmentVariable(
            name='ROS_LOCALHOST_ONLY', value='1'),
        SetEnvironmentVariable(
            name='FASTRTPS_DEFAULT_PROFILES_FILE', value=fastdds_profile),
        DeclareLaunchArgument('map', default_value=default_map),
        DeclareLaunchArgument('route_file', default_value=default_route),
        DeclareLaunchArgument('max_linear', default_value='0.50'),
        DeclareLaunchArgument('max_angular', default_value='2.00'),
        DeclareLaunchArgument('start_driver', default_value='true'),
        DeclareLaunchArgument('start_lidar', default_value='true'),
        DeclareLaunchArgument('auto_start_patrol', default_value='false'),
        navigation,
        start_patrol,
    ])
