#include "icar_base_node/odometry_integrator.hpp"

#include <algorithm>
#include <cmath>

namespace icar_base_node
{

OdometryIntegrator::OdometryIntegrator(double max_dt_sec)
: max_dt_sec_(std::max(0.01, max_dt_sec))
{
}

bool OdometryIntegrator::update(
  double timestamp_sec, double linear_x, double linear_y,
  double angular_z)
{
  if (!std::isfinite(timestamp_sec)) {
    return false;
  }

  if (!initialized_) {
    initialized_ = true;
    last_timestamp_sec_ = timestamp_sec;
    return false;
  }

  const double dt = timestamp_sec - last_timestamp_sec_;
  last_timestamp_sec_ = timestamp_sec;
  if (!std::isfinite(linear_x) || !std::isfinite(linear_y) ||
    !std::isfinite(angular_z) || !std::isfinite(dt) || dt <= 0.0 ||
    dt > max_dt_sec_)
  {
    return false;
  }

  const double midpoint_yaw = pose_.yaw + 0.5 * angular_z * dt;
  const double cos_yaw = std::cos(midpoint_yaw);
  const double sin_yaw = std::sin(midpoint_yaw);
  pose_.x += (linear_x * cos_yaw - linear_y * sin_yaw) * dt;
  pose_.y += (linear_x * sin_yaw + linear_y * cos_yaw) * dt;
  pose_.yaw = normalize_angle(pose_.yaw + angular_z * dt);
  return true;
}

void OdometryIntegrator::reset()
{
  initialized_ = false;
  last_timestamp_sec_ = 0.0;
  pose_ = Pose2D{};
}

const Pose2D & OdometryIntegrator::pose() const
{
  return pose_;
}

bool OdometryIntegrator::initialized() const
{
  return initialized_;
}

double OdometryIntegrator::normalize_angle(double angle)
{
  constexpr double kPi = 3.14159265358979323846;
  while (angle > kPi) {
    angle -= 2.0 * kPi;
  }
  while (angle < -kPi) {
    angle += 2.0 * kPi;
  }
  return angle;
}

}  // namespace icar_base_node
