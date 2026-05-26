# Copyright 2025 SMBU-PolarBear-Robotics-Team
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#     http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.

import os

from ament_index_python.packages import get_package_share_directory
from launch import LaunchDescription
from launch.actions import DeclareLaunchArgument, SetEnvironmentVariable
from launch.substitutions import LaunchConfiguration
from launch_ros.actions import Node


def generate_launch_description():
    pkg_dir = get_package_share_directory("standard_robot_pp_ros2")

    params_file = LaunchConfiguration("params_file")
    use_respawn = LaunchConfiguration("use_respawn")
    log_level = LaunchConfiguration("log_level")

    return LaunchDescription([
        SetEnvironmentVariable("RCUTILS_LOGGING_BUFFERED_STREAM", "1"),
        SetEnvironmentVariable("RCUTILS_COLORIZED_OUTPUT", "1"),
        DeclareLaunchArgument(
            "params_file",
            default_value=os.path.join(pkg_dir, "config", "standard_robot_pp_ros2.yaml"),
            description="Path to the standard_robot_pp_ros2 parameter file",
        ),
        DeclareLaunchArgument(
            "use_respawn",
            default_value="True",
            description="Whether to respawn the communication node if it exits",
        ),
        DeclareLaunchArgument("log_level", default_value="info", description="ROS log level"),
        Node(
            package="standard_robot_pp_ros2",
            executable="standard_robot_pp_ros2_node",
            name="standard_robot_pp_ros2",
            output="screen",
            respawn=use_respawn,
            respawn_delay=2.0,
            parameters=[params_file],
            arguments=["--ros-args", "--log-level", log_level],
        ),
    ])
