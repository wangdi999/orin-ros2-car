cmake_minimum_required(VERSION 3.5)
project(car_interfaces)

# 默认使用 C++14
if(NOT CMAKE_CXX_STANDARD)
  set(CMAKE_CXX_STANDARD 14)
endif()

# 提升编译器警告级别
if(CMAKE_COMPILER_IS_GNUCXX OR CMAKE_CXX_COMPILER_ID MATCHES "Clang")
  add_compile_options(-Wall -Wextra -Wpedantic)
endif()

find_package(ament_cmake REQUIRED)
find_package(rosidl_default_generators REQUIRED)

# 自定义消息定义
rosidl_generate_interfaces(${PROJECT_NAME}
  "msg/Alarm.msg"
)

ament_export_dependencies(rosidl_default_runtime)

ament_package()
