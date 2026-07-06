import os

from ament_index_python.packages import get_package_share_directory
from launch import LaunchDescription
from launch.actions import DeclareLaunchArgument
from launch.substitutions import LaunchConfiguration
from launch_ros.actions import Node


def generate_launch_description():
    package_dir = get_package_share_directory("navigation_web_bridge")
    default_params = os.path.join(package_dir, "config", "navigation_web_bridge.yaml")
    params_file = LaunchConfiguration("params_file")

    return LaunchDescription([
        DeclareLaunchArgument("params_file", default_value=default_params),
        Node(
            package="navigation_web_bridge",
            executable="navigation_web_bridge_node",
            name="navigation_web_bridge",
            output="screen",
            parameters=[params_file],
        ),
    ])
