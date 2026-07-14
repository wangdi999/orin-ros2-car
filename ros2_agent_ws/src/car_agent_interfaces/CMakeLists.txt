cmake_minimum_required(VERSION 3.5)
project(car_agent_interfaces)

find_package(ament_cmake REQUIRED)
find_package(rosidl_default_generators REQUIRED)
find_package(std_msgs REQUIRED)

rosidl_generate_interfaces(${PROJECT_NAME}
  "msg/Alarm.msg"
  "msg/PatrolStatus.msg"
  "msg/PatrolEvent.msg"
  "msg/RobotSummary.msg"
  "srv/CreatePatrol.srv"
  "srv/ControlPatrol.srv"
  "srv/GetRobotSummary.srv"
  DEPENDENCIES std_msgs
)

ament_export_dependencies(rosidl_default_runtime)
ament_package()
