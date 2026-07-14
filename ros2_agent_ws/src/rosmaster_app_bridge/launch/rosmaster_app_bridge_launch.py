import os

from ament_index_python.packages import get_package_share_directory
from launch import LaunchDescription
from launch.actions import DeclareLaunchArgument
from launch.substitutions import LaunchConfiguration
from launch_ros.actions import Node


def generate_launch_description():
    package_share = get_package_share_directory("rosmaster_app_bridge")
    default_config = os.path.join(package_share, "config", "rosmaster_app_bridge.yaml")

    return LaunchDescription(
        [
            DeclareLaunchArgument("config_file", default_value=default_config),
            Node(
                package="rosmaster_app_bridge",
                executable="rosmaster_app_bridge",
                name="rosmaster_app_bridge",
                output="screen",
                parameters=[LaunchConfiguration("config_file")],
            ),
        ]
    )
