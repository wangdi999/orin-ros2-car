#include <cmath>
#include <limits>

#include "gtest/gtest.h"
#include "icar_base_node/odometry_integrator.hpp"

using icar_base_node::OdometryIntegrator;

TEST(OdometryIntegrator, FirstFrameOnlyEstablishesTimeBaseline)
{
  OdometryIntegrator integrator;
  EXPECT_FALSE(integrator.update(1000.0, 1.0, 0.0, 0.0));
  EXPECT_TRUE(integrator.initialized());
  EXPECT_DOUBLE_EQ(integrator.pose().x, 0.0);
  EXPECT_DOUBLE_EQ(integrator.pose().y, 0.0);
}

TEST(OdometryIntegrator, IntegratesForwardAndLateralVelocity)
{
  OdometryIntegrator integrator;
  integrator.update(0.0, 0.0, 0.0, 0.0);
  EXPECT_TRUE(integrator.update(0.1, 1.0, 0.5, 0.0));
  EXPECT_NEAR(integrator.pose().x, 0.1, 1e-9);
  EXPECT_NEAR(integrator.pose().y, 0.05, 1e-9);
}

TEST(OdometryIntegrator, UsesMidpointHeadingForTurningMotion)
{
  OdometryIntegrator integrator;
  integrator.update(0.0, 0.0, 0.0, 0.0);
  EXPECT_TRUE(integrator.update(0.2, 1.0, 0.0, 1.0));
  EXPECT_NEAR(integrator.pose().x, std::cos(0.1) * 0.2, 1e-9);
  EXPECT_NEAR(integrator.pose().y, std::sin(0.1) * 0.2, 1e-9);
  EXPECT_NEAR(integrator.pose().yaw, 0.2, 1e-9);
}

TEST(OdometryIntegrator, RejectsLargeAndBackwardTimeStepsWithoutJump)
{
  OdometryIntegrator integrator(0.5);
  integrator.update(1.0, 0.0, 0.0, 0.0);
  EXPECT_FALSE(integrator.update(2.0, 1.0, 0.0, 0.0));
  EXPECT_DOUBLE_EQ(integrator.pose().x, 0.0);
  EXPECT_FALSE(integrator.update(1.5, 1.0, 0.0, 0.0));
  EXPECT_DOUBLE_EQ(integrator.pose().x, 0.0);
  EXPECT_TRUE(integrator.update(1.6, 1.0, 0.0, 0.0));
  EXPECT_NEAR(integrator.pose().x, 0.1, 1e-9);
}

TEST(OdometryIntegrator, RejectsNonFiniteFeedback)
{
  OdometryIntegrator integrator;
  integrator.update(0.0, 0.0, 0.0, 0.0);
  EXPECT_FALSE(integrator.update(
    0.1, std::numeric_limits<double>::quiet_NaN(), 0.0, 0.0));
  EXPECT_DOUBLE_EQ(integrator.pose().x, 0.0);
}

TEST(OdometryIntegrator, NormalizesYaw)
{
  OdometryIntegrator integrator(10.0);
  integrator.update(0.0, 0.0, 0.0, 0.0);
  EXPECT_TRUE(integrator.update(1.0, 0.0, 0.0, 4.0));
  EXPECT_GE(integrator.pose().yaw, -3.14159265358979323846);
  EXPECT_LE(integrator.pose().yaw, 3.14159265358979323846);
}
