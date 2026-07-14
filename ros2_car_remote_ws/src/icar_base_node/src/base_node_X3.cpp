#include <array>
#include <cmath>
#include <functional>
#include <memory>
#include <string>

#include "geometry_msgs/msg/twist.hpp"
#include "icar_base_node/odometry_integrator.hpp"
#include "nav_msgs/msg/odometry.hpp"
#include "rclcpp/rclcpp.hpp"
#include "tf2/LinearMath/Quaternion.h"

namespace icar_base_node
{

class BaseNodeX3 : public rclcpp::Node
{
public:
  BaseNodeX3()
  : Node("base_node_X3"),
    integrator_(declare_parameter<double>("max_dt_sec", 0.5))
  {
    frame_id_ = declare_parameter<std::string>("frame_id", "odom");
    child_frame_id_ = declare_parameter<std::string>(
      "child_frame_id", "base_footprint");
    const bool requested_tf = declare_parameter<bool>("pub_odom_tf", false);
    if (requested_tf) {
      RCLCPP_ERROR(
        get_logger(),
        "pub_odom_tf=true is rejected; robot_localization exclusively owns TF");
    }

    odometry_publisher_ = create_publisher<nav_msgs::msg::Odometry>(
      "/odom_raw", rclcpp::QoS(20));
    velocity_subscription_ = create_subscription<geometry_msgs::msg::Twist>(
      "/vel_raw", rclcpp::QoS(20),
      std::bind(&BaseNodeX3::velocity_callback, this, std::placeholders::_1));
  }

private:
  void velocity_callback(const geometry_msgs::msg::Twist::SharedPtr message)
  {
    const double linear_x = message->linear.x;
    const double linear_y = message->linear.y;
    const double angular_z = message->angular.z;
    if (!std::isfinite(linear_x) || !std::isfinite(linear_y) ||
      !std::isfinite(angular_z))
    {
      RCLCPP_ERROR(get_logger(), "Rejected non-finite /vel_raw feedback");
      return;
    }

    const rclcpp::Time timestamp = now();
    integrator_.update(
      timestamp.seconds(), linear_x, linear_y, angular_z);
    const auto & pose = integrator_.pose();

    nav_msgs::msg::Odometry odometry;
    odometry.header.stamp = timestamp;
    odometry.header.frame_id = frame_id_;
    odometry.child_frame_id = child_frame_id_;
    odometry.pose.pose.position.x = pose.x;
    odometry.pose.pose.position.y = pose.y;
    odometry.pose.pose.position.z = 0.0;

    tf2::Quaternion quaternion;
    quaternion.setRPY(0.0, 0.0, pose.yaw);
    odometry.pose.pose.orientation.x = quaternion.x();
    odometry.pose.pose.orientation.y = quaternion.y();
    odometry.pose.pose.orientation.z = quaternion.z();
    odometry.pose.pose.orientation.w = quaternion.w();

    odometry.twist.twist.linear.x = linear_x;
    odometry.twist.twist.linear.y = linear_y;
    odometry.twist.twist.angular.z = angular_z;
    odometry.pose.covariance = pose_covariance();
    odometry.twist.covariance = twist_covariance();
    odometry_publisher_->publish(odometry);
  }

  static std::array<double, 36> pose_covariance()
  {
    std::array<double, 36> covariance{};
    covariance[0] = 0.02;
    covariance[7] = 0.02;
    covariance[14] = 1000000.0;
    covariance[21] = 1000000.0;
    covariance[28] = 1000000.0;
    covariance[35] = 0.05;
    return covariance;
  }

  static std::array<double, 36> twist_covariance()
  {
    std::array<double, 36> covariance{};
    covariance[0] = 0.03;
    covariance[7] = 0.03;
    covariance[14] = 1000000.0;
    covariance[21] = 1000000.0;
    covariance[28] = 1000000.0;
    covariance[35] = 0.05;
    return covariance;
  }

  std::string frame_id_;
  std::string child_frame_id_;
  OdometryIntegrator integrator_;
  rclcpp::Publisher<nav_msgs::msg::Odometry>::SharedPtr odometry_publisher_;
  rclcpp::Subscription<geometry_msgs::msg::Twist>::SharedPtr
    velocity_subscription_;
};

}  // namespace icar_base_node

int main(int argc, char ** argv)
{
  rclcpp::init(argc, argv);
  rclcpp::spin(std::make_shared<icar_base_node::BaseNodeX3>());
  rclcpp::shutdown();
  return 0;
}
