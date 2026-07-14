"""Hardware-only X3 bringup; navigation and EKF live in icar_navigation."""

import os

from ament_index_python.packages import (
    get_package_share_directory,
)
from launch import LaunchDescription
from launch.actions import DeclareLaunchArgument
from launch.conditions import IfCondition
from launch.substitutions import Command, LaunchConfiguration
from launch_ros.actions import Node
from launch_ros.parameter_descriptions import ParameterValue


def generate_launch_description():
    """Create the X3 driver, raw odometry, IMU filter and fixed TF owners."""
    description_share = get_package_share_directory('icar_description')
    default_model = os.path.join(
        description_share, 'urdf', 'icar_X3.urdf')
    bringup_share = get_package_share_directory('icar_bringup')
    imu_config = os.path.join(bringup_share, 'param', 'imu_filter_param.yaml')

    model = LaunchConfiguration('model')
    robot_description = ParameterValue(Command(['xacro ', model]), value_type=str)

    arguments = [
        DeclareLaunchArgument('model', default_value=default_model),
        DeclareLaunchArgument('xlinear_limit', default_value='0.50'),
        DeclareLaunchArgument('ylinear_limit', default_value='0.50'),
        DeclareLaunchArgument('angular_limit', default_value='2.00'),
        DeclareLaunchArgument('command_timeout_sec', default_value='0.30'),
        DeclareLaunchArgument('reconnect_interval_sec', default_value='5.0'),
        DeclareLaunchArgument('start_driver', default_value='true'),
    ]

    robot_state_publisher = Node(
        package='robot_state_publisher',
        executable='robot_state_publisher',
        name='robot_state_publisher',
        output='screen',
        parameters=[{'robot_description': robot_description}],
    )
    driver = Node(
        package='icar_bringup',
        executable='Mcnamu_driver_X3',
        name='driver_node',
        output='screen',
        condition=IfCondition(LaunchConfiguration('start_driver')),
        parameters=[{
            'xlinear_limit': ParameterValue(
                LaunchConfiguration('xlinear_limit'), value_type=float),
            'ylinear_limit': ParameterValue(
                LaunchConfiguration('ylinear_limit'), value_type=float),
            'angular_limit': ParameterValue(
                LaunchConfiguration('angular_limit'), value_type=float),
            'command_timeout_sec': ParameterValue(
                LaunchConfiguration('command_timeout_sec'), value_type=float),
            'reconnect_interval_sec': ParameterValue(
                LaunchConfiguration('reconnect_interval_sec'), value_type=float),
            'expected_cmd_vel_publisher': 'cmd_vel_arbiter',
        }],
    )
    base_node = Node(
        package='icar_base_node',
        executable='base_node_X3',
        name='base_node_X3',
        output='screen',
        parameters=[{'pub_odom_tf': False}],
    )
    imu_filter = Node(
        package='imu_filter_madgwick',
        executable='imu_filter_madgwick_node',
        name='imu_filter_madgwick',
        output='screen',
        parameters=[imu_config],
        remappings=[('imu/data_raw', '/imu/data_raw'),
                    ('imu/data', '/imu/data')],
    )

    return LaunchDescription(arguments + [
        robot_state_publisher,
        driver,
        base_node,
        imu_filter,
    ])
