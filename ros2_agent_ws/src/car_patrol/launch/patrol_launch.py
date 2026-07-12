from launch import LaunchDescription
from launch_ros.actions import Node


def generate_launch_description():
    return LaunchDescription(
        [
            Node(
                package="car_patrol",
                executable="patrol_manager",
                name="patrol_manager",
                output="screen",
                parameters=[
                    {
                        "locations_file": "",
                        "max_retries": 1,
                        "nav_action_name": "navigate_to_pose",
                    }
                ],
            )
        ]
    )
