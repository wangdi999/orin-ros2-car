from ament_index_python.packages import get_package_share_directory
from launch import LaunchDescription
from launch_ros.actions import Node
import os


def generate_launch_description():
    config = os.path.join(get_package_share_directory("car_safety"), "config", "safety.yaml")
    return LaunchDescription(
        [
            Node(
                package="car_safety",
                executable="safety_supervisor",
                name="safety_supervisor",
                output="screen",
                parameters=[config],
            )
        ]
    )
