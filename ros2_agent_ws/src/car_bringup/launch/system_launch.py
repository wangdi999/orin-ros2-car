from launch import LaunchDescription
from launch.actions import LogInfo


def generate_launch_description():
    return LaunchDescription(
        [
            LogInfo(
                msg=(
                    "Legacy Agent safety/patrol launch is disabled. "
                    "Use icar_navigation launches so cmd_vel_arbiter remains the sole /cmd_vel publisher."
                )
            )
        ]
    )
