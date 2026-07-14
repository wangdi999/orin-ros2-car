"""Mutually exclusive AMCL/Nav2 navigation and patrol mode for Foxy."""

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
from launch_ros.parameter_descriptions import ParameterValue


def generate_launch_description():
    """Launch safe base, AMCL, NavFn, DWB, BT Navigator and patrol."""
    share = get_package_share_directory('icar_navigation')
    nav2_share = get_package_share_directory('nav2_bt_navigator')
    nav_params = os.path.join(share, 'config', 'nav2_foxy.yaml')
    fastdds_profile = os.path.join(
        share, 'config', 'fastdds_localhost.xml')
    patrol_params = os.path.join(share, 'config', 'patrol.yaml')
    default_map = os.path.join(share, 'maps', 'campus_map.yaml')
    default_route = os.path.join(share, 'config', 'patrol_route.yaml')
    default_bt = os.path.join(
        nav2_share, 'behavior_trees',
        'navigate_w_replanning_and_recovery.xml')

    arguments = [
        DeclareLaunchArgument('map', default_value=default_map),
        DeclareLaunchArgument('route_file', default_value=default_route),
        DeclareLaunchArgument('max_linear', default_value='0.10'),
        DeclareLaunchArgument('max_angular', default_value='0.40'),
        DeclareLaunchArgument('startup_grace_sec', default_value='60.0'),
        DeclareLaunchArgument('start_driver', default_value='true'),
        DeclareLaunchArgument('start_lidar', default_value='true'),
        DeclareLaunchArgument('lidar_frame', default_value='laser_link'),
    ]

    safe_base = IncludeLaunchDescription(
        PythonLaunchDescriptionSource(os.path.join(
            share, 'launch', 'safe_base.launch.py')),
        launch_arguments={
            'runtime_mode': 'navigation',
            'startup_grace_sec': LaunchConfiguration(
                'startup_grace_sec'),
            'max_linear': LaunchConfiguration('max_linear'),
            'max_angular': LaunchConfiguration('max_angular'),
            'start_driver': LaunchConfiguration('start_driver'),
            'start_lidar': LaunchConfiguration('start_lidar'),
            'lidar_frame': LaunchConfiguration('lidar_frame'),
        }.items(),
    )

    map_server = Node(
        package='nav2_map_server',
        executable='map_server',
        name='map_server',
        output='screen',
        parameters=[
            nav_params,
            {'yaml_filename': ParameterValue(
                LaunchConfiguration('map'), value_type=str)},
        ],
    )
    amcl = Node(
        package='nav2_amcl',
        executable='amcl',
        name='amcl',
        output='screen',
        parameters=[nav_params],
    )
    localization_lifecycle = Node(
        package='nav2_lifecycle_manager',
        executable='lifecycle_manager',
        name='lifecycle_manager_localization',
        output='screen',
        parameters=[{
            'use_sim_time': False,
            'autostart': True,
            'node_names': ['map_server', 'amcl'],
        }],
    )

    common_remappings = [('/tf', 'tf'), ('/tf_static', 'tf_static')]
    controller = Node(
        package='nav2_controller',
        executable='controller_server',
        name='controller_server',
        output='screen',
        parameters=[nav_params],
        remappings=common_remappings + [('cmd_vel', '/cmd_vel_nav')],
    )
    planner = Node(
        package='nav2_planner',
        executable='planner_server',
        name='planner_server',
        output='screen',
        parameters=[nav_params],
        remappings=common_remappings,
    )
    recoveries = Node(
        package='nav2_recoveries',
        executable='recoveries_server',
        name='recoveries_server',
        output='screen',
        parameters=[nav_params],
        remappings=common_remappings + [('cmd_vel', '/cmd_vel_nav')],
    )
    navigator = Node(
        package='nav2_bt_navigator',
        executable='bt_navigator',
        name='bt_navigator',
        output='screen',
        parameters=[nav_params, {'default_bt_xml_filename': default_bt}],
        remappings=common_remappings,
    )
    navigation_lifecycle = Node(
        package='nav2_lifecycle_manager',
        executable='lifecycle_manager',
        name='lifecycle_manager_navigation',
        output='screen',
        parameters=[{
            'use_sim_time': False,
            'autostart': True,
            'node_names': [
                'controller_server', 'planner_server',
                'recoveries_server', 'bt_navigator',
            ],
        }],
    )
    patrol = Node(
        package='icar_navigation',
        executable='patrol_manager',
        name='patrol_manager',
        output='screen',
        parameters=[
            patrol_params,
            {'route_file': ParameterValue(
                LaunchConfiguration('route_file'), value_type=str)},
        ],
    )

    return LaunchDescription([
        SetEnvironmentVariable(
            name='ROS_LOCALHOST_ONLY', value='1'),
        SetEnvironmentVariable(
            name='FASTRTPS_DEFAULT_PROFILES_FILE', value=fastdds_profile),
    ] + arguments + [
        safe_base,
        map_server,
        amcl,
        localization_lifecycle,
        controller,
        planner,
        recoveries,
        navigator,
        navigation_lifecycle,
        patrol,
    ])
