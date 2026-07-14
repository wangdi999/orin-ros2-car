"""Launch the fail-closed chassis, estimation, lidar and safety foundation."""

import os

from ament_index_python.packages import get_package_share_directory
from launch import LaunchDescription
from launch.actions import (
    DeclareLaunchArgument,
    IncludeLaunchDescription,
    SetEnvironmentVariable,
)
from launch.conditions import IfCondition
from launch.launch_description_sources import PythonLaunchDescriptionSource
from launch.substitutions import LaunchConfiguration
from launch_ros.actions import Node
from launch_ros.parameter_descriptions import ParameterValue

from icar_navigation.config_utils import merge_node_parameters


def generate_launch_description():
    """Create the D1 stack without a map-to-odom owner."""
    navigation_share = get_package_share_directory('icar_navigation')
    bringup_share = get_package_share_directory('icar_bringup')
    lidar_share = get_package_share_directory('sllidar_ros2')

    arbiter_config = os.path.join(
        navigation_share, 'config', 'arbiter.yaml')
    safety_config = os.path.join(
        navigation_share, 'config', 'safety.yaml')
    ekf_config = os.path.join(navigation_share, 'config', 'ekf.yaml')
    fastdds_profile = os.path.join(
        navigation_share, 'config', 'fastdds_localhost.xml')
    arbiter_parameters = merge_node_parameters(
        arbiter_config,
        'cmd_vel_arbiter',
        {
            'max_linear_x': ParameterValue(
                LaunchConfiguration('max_linear'), value_type=float),
            'max_linear_y': ParameterValue(
                LaunchConfiguration('max_linear'), value_type=float),
            'max_angular_z': ParameterValue(
                LaunchConfiguration('max_angular'), value_type=float),
        })

    arguments = [
        DeclareLaunchArgument('runtime_mode', default_value='base'),
        DeclareLaunchArgument('startup_grace_sec', default_value='5.0'),
        DeclareLaunchArgument('max_linear', default_value='0.50'),
        DeclareLaunchArgument('max_angular', default_value='2.00'),
        DeclareLaunchArgument('start_driver', default_value='true'),
        DeclareLaunchArgument('start_lidar', default_value='true'),
        DeclareLaunchArgument('lidar_frame', default_value='laser_link'),
        DeclareLaunchArgument('lidar_serial_port', default_value='/dev/rplidar'),
        DeclareLaunchArgument('lidar_serial_baudrate', default_value='115200'),
    ]

    hardware_bringup = IncludeLaunchDescription(
        PythonLaunchDescriptionSource(os.path.join(
            bringup_share, 'launch', 'icar_bringup_X3_launch.py')),
        launch_arguments={
            'start_driver': LaunchConfiguration('start_driver'),
            'xlinear_limit': '0.50',
            'ylinear_limit': '0.50',
            'angular_limit': '2.00',
            'command_timeout_sec': '0.30',
            'reconnect_interval_sec': '5.0',
        }.items(),
    )
    lidar = IncludeLaunchDescription(
        PythonLaunchDescriptionSource(os.path.join(
            lidar_share, 'launch', 'sllidar_launch.py')),
        condition=IfCondition(LaunchConfiguration('start_lidar')),
        launch_arguments={
            'serial_port': LaunchConfiguration('lidar_serial_port'),
            'serial_baudrate': LaunchConfiguration(
                'lidar_serial_baudrate'),
            'frame_id': LaunchConfiguration('lidar_frame'),
            'inverted': 'false',
            'angle_compensate': 'true',
        }.items(),
    )
    ekf = Node(
        package='robot_localization',
        executable='ekf_node',
        name='ekf_filter_node',
        output='screen',
        parameters=[ekf_config],
        remappings=[('odometry/filtered', '/odom')],
    )
    arbiter = Node(
        package='icar_navigation',
        executable='cmd_vel_arbiter',
        name='cmd_vel_arbiter',
        output='screen',
        parameters=[arbiter_parameters],
    )
    safety = Node(
        package='icar_navigation',
        executable='safety_manager',
        name='safety_manager',
        output='screen',
        parameters=[
            safety_config,
            {
                'runtime_mode': ParameterValue(
                    LaunchConfiguration('runtime_mode'), value_type=str),
                'startup_grace_sec': ParameterValue(
                    LaunchConfiguration('startup_grace_sec'),
                    value_type=float),
            },
        ],
    )

    return LaunchDescription([
        SetEnvironmentVariable(
            name='ROS_LOCALHOST_ONLY', value='1'),
        SetEnvironmentVariable(
            name='FASTRTPS_DEFAULT_PROFILES_FILE', value=fastdds_profile),
    ] + arguments + [
        hardware_bringup,
        lidar,
        ekf,
        arbiter,
        safety,
    ])
