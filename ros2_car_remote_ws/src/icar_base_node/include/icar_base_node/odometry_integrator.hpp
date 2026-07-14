#ifndef ICAR_BASE_NODE__ODOMETRY_INTEGRATOR_HPP_
#define ICAR_BASE_NODE__ODOMETRY_INTEGRATOR_HPP_

namespace icar_base_node
{

struct Pose2D
{
  double x{0.0};
  double y{0.0};
  double yaw{0.0};
};

class OdometryIntegrator
{
public:
  explicit OdometryIntegrator(double max_dt_sec = 0.5);

  bool update(
    double timestamp_sec, double linear_x, double linear_y,
    double angular_z);
  void reset();
  const Pose2D & pose() const;
  bool initialized() const;

private:
  static double normalize_angle(double angle);

  double max_dt_sec_;
  bool initialized_{false};
  double last_timestamp_sec_{0.0};
  Pose2D pose_{};
};

}  // namespace icar_base_node

#endif  // ICAR_BASE_NODE__ODOMETRY_INTEGRATOR_HPP_
