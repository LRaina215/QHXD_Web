from setuptools import setup

package_name = 'rtt_nav_bridge'

setup(
    name=package_name,
    version='0.1.0',
    packages=[package_name],
    data_files=[
        ('share/ament_index/resource_index/packages', ['resource/' + package_name]),
        ('share/' + package_name, ['package.xml']),
        ('share/' + package_name + '/config', ['config/rtt_nav_bridge.yaml']),
        ('share/' + package_name + '/launch', ['launch/rtt_nav_bridge.launch.py']),
    ],
    install_requires=['setuptools'],
    zip_safe=True,
    maintainer='robomaster',
    maintainer_email='robomaster@example.com',
    description='ROS2 bridge between Nav2 topics and RT-Thread/C-board navigation serial protocol.',
    license='Apache-2.0',
    tests_require=['pytest'],
    entry_points={
        'console_scripts': [
            'rtt_nav_bridge_node = rtt_nav_bridge.rtt_nav_bridge_node:main',
        ],
    },
)
