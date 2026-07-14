from launch import LaunchDescription
from launch.actions import DeclareLaunchArgument
from launch.substitutions import LaunchConfiguration
from launch_ros.actions import Node


def generate_launch_description():
    return LaunchDescription(
        [
            DeclareLaunchArgument("http_host", default_value="127.0.0.1"),
            DeclareLaunchArgument("http_port", default_value="8130"),
            DeclareLaunchArgument("nav_action_name", default_value="navigate_to_pose"),
            Node(
                package="car_gateway",
                executable="gateway_bridge",
                name="agent_http_gateway_bridge",
                output="screen",
                parameters=[
                    {
                        "http_host": LaunchConfiguration("http_host"),
                        "http_port": LaunchConfiguration("http_port"),
                        "nav_action_name": LaunchConfiguration("nav_action_name"),
                    }
                ],
            ),
        ]
    )
