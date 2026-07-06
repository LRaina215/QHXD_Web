cmake_minimum_required(VERSION 3.8)
project(navigation_web_bridge)

if(CMAKE_CXX_COMPILER_ID MATCHES "GNU|Clang")
  add_compile_options(-Wall -Wextra -Wpedantic)
endif()

find_package(ament_cmake REQUIRED)
find_package(CURL REQUIRED)
find_package(geometry_msgs REQUIRED)
find_package(nav_msgs REQUIRED)
find_package(rclcpp REQUIRED)
find_package(tf2_ros REQUIRED)

add_executable(navigation_web_bridge_node src/navigation_web_bridge.cpp)
target_compile_features(navigation_web_bridge_node PUBLIC cxx_std_17)
target_link_libraries(navigation_web_bridge_node CURL::libcurl)
ament_target_dependencies(
  navigation_web_bridge_node
  geometry_msgs
  nav_msgs
  rclcpp
  tf2_ros
)

install(TARGETS navigation_web_bridge_node
  DESTINATION lib/${PROJECT_NAME}
)
install(DIRECTORY config launch
  DESTINATION share/${PROJECT_NAME}
)

ament_package()
