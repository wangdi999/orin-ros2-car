cmake_minimum_required(VERSION 3.5)
project(icar_base_node)

if(NOT CMAKE_CXX_STANDARD)
  set(CMAKE_CXX_STANDARD 14)
endif()

find_package(ament_cmake REQUIRED)
find_package(geometry_msgs REQUIRED)
find_package(nav_msgs REQUIRED)
find_package(rclcpp REQUIRED)
find_package(tf2 REQUIRED)

add_library(odometry_integrator src/odometry_integrator.cpp)
target_include_directories(odometry_integrator PUBLIC
  $<BUILD_INTERFACE:${CMAKE_CURRENT_SOURCE_DIR}/include>
  $<INSTALL_INTERFACE:include>)

add_executable(base_node_X3 src/base_node_X3.cpp)
target_link_libraries(base_node_X3 odometry_integrator)
ament_target_dependencies(base_node_X3 geometry_msgs nav_msgs rclcpp tf2)

install(TARGETS odometry_integrator base_node_X3
  ARCHIVE DESTINATION lib
  LIBRARY DESTINATION lib
  RUNTIME DESTINATION lib/${PROJECT_NAME})
install(DIRECTORY include/ DESTINATION include)

if(BUILD_TESTING)
  find_package(ament_cmake_gtest REQUIRED)
  ament_add_gtest(test_odometry_integrator test/test_odometry_integrator.cpp)
  if(TARGET test_odometry_integrator)
    target_link_libraries(test_odometry_integrator odometry_integrator)
    target_include_directories(test_odometry_integrator PRIVATE include)
  endif()
endif()

ament_export_include_directories(include)
ament_export_libraries(odometry_integrator)
ament_package()
