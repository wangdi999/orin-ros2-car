import os

from ament_index_python.packages import get_package_share_directory
from launch import LaunchDescription
from launch.actions import DeclareLaunchArgument
from launch.substitutions import LaunchConfiguration
from launch_ros.actions import Node


def generate_launch_description():
    patrol_share = get_package_share_directory("car_patrol")
    safety_share = get_package_share_directory("car_safety")
    default_locations = os.path.join(patrol_share, "config", "locations.yaml")
    safety_config = os.path.join(safety_share, "config", "safety.yaml")

    locations_file = LaunchConfiguration("locations_file")
    nav_action_name = LaunchConfiguration("nav_action_name")

    return LaunchDescription(
        [
            DeclareLaunchArgument("locations_file", default_value=default_locations),
            DeclareLaunchArgument("nav_action_name", default_value="navigate_to_pose"),
            Node(
                package="car_safety",
                executable="safety_supervisor",
                name="safety_supervisor",
                output="screen",
                parameters=[safety_config],
            ),
            Node(
                package="car_patrol",
                executable="patrol_manager",
                name="patrol_manager",
                output="screen",
                parameters=[
                    {
                        "locations_file": locations_file,
                        "nav_action_name": nav_action_name,
                        "max_retries": 1,
                        "map_frame": "map",
                    }
                ],
            ),
        ]
    )
