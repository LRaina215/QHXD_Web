cmake_minimum_required(VERSION 3.10)
project(standard_robot_pp_ros2)

set(CMAKE_CXX_STANDARD 14)
set(CMAKE_CXX_STANDARD_REQUIRED ON)

add_definitions(-Wall -Werror)
set(CMAKE_EXPORT_COMPILE_COMMANDS ON)

find_package(ament_cmake_auto REQUIRED)
ament_auto_find_build_dependencies()

ament_auto_add_library(${PROJECT_NAME} SHARED
  src/crc8_crc16.cpp
  src/standard_robot_pp_ros2.cpp
)

ament_target_dependencies(${PROJECT_NAME}
  rclcpp
  rclcpp_components
  serial_driver
  tf2_geometry_msgs
  geometry_msgs
  sensor_msgs
  std_msgs
  std_srvs
  pb_rm_interfaces
)

rclcpp_components_register_node(${PROJECT_NAME}
  PLUGIN standard_robot_pp_ros2::StandardRobotPpRos2Node
  EXECUTABLE standard_robot_pp_ros2_node
)

if(BUILD_TESTING)
  set(ament_cmake_clang_format_CONFIG_FILE "${CMAKE_SOURCE_DIR}/.clang-format")
  find_package(ament_lint_auto REQUIRED)
  list(APPEND AMENT_LINT_AUTO_EXCLUDE
    ament_cmake_uncrustify
    ament_cmake_flake8
  )
  ament_lint_auto_find_test_dependencies()
endif()

ament_auto_package(
  USE_SCOPED_HEADER_INSTALL_DIR
  INSTALL_TO_SHARE
  config
  launch
)
