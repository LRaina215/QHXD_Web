from launch import LaunchDescription
from launch.actions import DeclareLaunchArgument
from launch.substitutions import LaunchConfiguration, PathJoinSubstitution
from launch_ros.actions import Node
from launch_ros.substitutions import FindPackageShare


def generate_launch_description():
    config_arg = DeclareLaunchArgument(
        'config',
        default_value=PathJoinSubstitution([
            FindPackageShare('rtt_nav_bridge'),
            'config',
            'rtt_nav_bridge.yaml',
        ]),
        description='Path to rtt_nav_bridge YAML config.',
    )
    return LaunchDescription([
        config_arg,
        Node(
            package='rtt_nav_bridge',
            executable='rtt_nav_bridge_node',
            name='rtt_nav_bridge_node',
            output='screen',
            parameters=[LaunchConfiguration('config')],
        ),
    ])
