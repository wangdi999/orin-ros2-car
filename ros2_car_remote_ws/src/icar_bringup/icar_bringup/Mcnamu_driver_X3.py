#!/usr/bin/env python3
"""Safety-hardened Rosmaster driver for the X3 mecanum chassis."""

import atexit
import math
import signal
import time

from Rosmaster_Lib import Rosmaster
from geometry_msgs.msg import Twist
import rclpy
from rclpy.node import Node
from sensor_msgs.msg import Imu, JointState, MagneticField
from std_msgs.msg import Bool, Float32, Int32

from .driver_safety import (
    DriverSafety,
    ReconnectBackoff,
    exclusive_publisher_matches,
    serial_endpoint_is_healthy,
)


class IcarDriver(Node):
    """ROS-facing X3 driver with independent hardware safety enforcement."""

    def __init__(self, name='driver_node'):
        super().__init__(name)
        self.declare_parameter('car_type', 'X3')
        self.declare_parameter('imu_link', 'imu_link')
        self.declare_parameter('Prefix', '')
        self.declare_parameter('xlinear_limit', 0.50)
        self.declare_parameter('ylinear_limit', 0.50)
        self.declare_parameter('angular_limit', 2.00)
        self.declare_parameter('command_timeout_sec', 0.30)
        self.declare_parameter('reconnect_interval_sec', 5.0)
        self.declare_parameter('expected_cmd_vel_publisher', 'cmd_vel_arbiter')

        self.imu_link = self.get_parameter('imu_link').value
        self.prefix = self.get_parameter('Prefix').value
        self.expected_publisher = self.get_parameter(
            'expected_cmd_vel_publisher').value
        self.safety = DriverSafety(
            x_limit=self.get_parameter('xlinear_limit').value,
            y_limit=self.get_parameter('ylinear_limit').value,
            angular_limit=self.get_parameter('angular_limit').value,
            command_timeout_sec=self.get_parameter(
                'command_timeout_sec').value,
        )
        self.reconnect = ReconnectBackoff(
            self.get_parameter('reconnect_interval_sec').value)

        self.car = None
        self.connected = False
        self._shutting_down = False
        self._last_owner_warning_at = -math.inf

        self.create_subscription(Twist, '/cmd_vel', self._cmd_vel_callback, 1)
        self.create_subscription(Int32, 'RGBLight', self._rgb_callback, 10)
        self.create_subscription(Bool, 'Buzzer', self._buzzer_callback, 10)

        self.edition_publisher = self.create_publisher(Float32, 'edition', 10)
        self.voltage_publisher = self.create_publisher(Float32, 'voltage', 10)
        self.joint_publisher = self.create_publisher(
            JointState, 'joint_states', 10)
        self.velocity_publisher = self.create_publisher(Twist, 'vel_raw', 10)
        self.imu_publisher = self.create_publisher(Imu, 'imu/data_raw', 10)
        self.attitude_publisher = self.create_publisher(
            Imu, 'imu/attitude', 10)
        self.mag_publisher = self.create_publisher(
            MagneticField, 'imu/mag', 10)
        self.connection_publisher = self.create_publisher(
            Bool, '/chassis/connected', 10)

        self.create_timer(0.10, self._publish_data)
        self.create_timer(0.05, self._watchdog_tick)
        self.create_timer(0.25, self._reconnect_tick)

        self._attempt_connect(initial=True)

    def shutdown(self):
        """Best-effort zero and serial close for graceful process exit."""
        if self._shutting_down:
            return
        self._shutting_down = True
        self._send_zero('driver shutdown')
        self._close_serial()
        self.connected = False
        self._publish_connection()

    def _cmd_vel_callback(self, message):
        now = time.monotonic()
        publishers = self.get_publishers_info_by_topic('/cmd_vel')
        if not exclusive_publisher_matches(publishers, self.expected_publisher):
            self._send_zero('cmd_vel publisher ownership mismatch')
            if now - self._last_owner_warning_at >= 1.0:
                self.get_logger().error(
                    'Rejected /cmd_vel: expected exactly one publisher named %s'
                    % self.expected_publisher)
                self._last_owner_warning_at = now
            return

        motion = self.safety.sanitize(
            message.linear.x, message.linear.y, message.angular.z)
        if motion is None:
            self.get_logger().error('Rejected non-finite /cmd_vel command')
            self._send_zero('invalid command')
            return
        if not self.connected or not self._serial_is_healthy():
            self._mark_disconnected('command received while serial unavailable')
            return
        try:
            self.car.set_car_motion(
                motion.linear_x, motion.linear_y, motion.angular_z)
        except Exception as exc:
            self._mark_disconnected('serial command failed: %s' % exc)
            return
        if not self._serial_is_healthy():
            self._mark_disconnected('serial failed while sending command')
            return
        self.safety.record_valid_command(now)

    def _watchdog_tick(self):
        if self.safety.watchdog_zero_due(time.monotonic()):
            if not self._send_zero('command watchdog timeout'):
                self._mark_disconnected('watchdog zero failed')
            self.get_logger().warning('Command watchdog stopped the chassis')

    def _reconnect_tick(self):
        if self._shutting_down or self.connected:
            return
        now = time.monotonic()
        if self.reconnect.retry_due(now):
            self._attempt_connect(initial=False)

    def _attempt_connect(self, initial=False):
        now = time.monotonic()
        self.reconnect.record_attempt(now)
        self._close_serial()
        try:
            car = Rosmaster()
            self.car = car
            car.set_car_type(1)
            car.create_receive_threading()
            car.set_auto_report_state(True)
            time.sleep(0.05)
            if not self._serial_is_healthy():
                raise RuntimeError('serial port did not open')
            self.connected = True
            self.reconnect.mark_connected()
            self._send_zero('serial connected')
            self.get_logger().info(
                'Rosmaster serial connected%s' % (' at startup' if initial else ''))
        except Exception as exc:  # Hardware library exposes several error types.
            self._close_serial()
            self.car = None
            self.connected = False
            self.reconnect.mark_disconnected(now)
            self.get_logger().error('Rosmaster connection failed: %s' % exc)
        self._publish_connection()

    def _publish_data(self):
        self._publish_connection()
        if not self.connected or not self._serial_is_healthy():
            self._mark_disconnected('serial health check failed')
            return
        try:
            timestamp = self.get_clock().now().to_msg()
            version = float(self.car.get_version())
            voltage = float(self.car.get_battery_voltage())
            ax, ay, az = self.car.get_accelerometer_data()
            gx, gy, gz = self.car.get_gyroscope_data()
            roll, pitch, yaw = self.car.get_imu_attitude_data(ToAngle=False)
            mx, my, mz = self.car.get_magnetometer_data()
            vx, vy, angular = self.car.get_motion_data()
            values = (
                version, voltage, ax, ay, az, gx, gy, gz, roll, pitch, yaw,
                mx, my, mz, vx, vy, angular,
            )
            if not all(math.isfinite(float(value)) for value in values):
                raise ValueError('telemetry contains non-finite values')
        except Exception as exc:
            self._mark_disconnected('telemetry read failed: %s' % exc)
            return

        self.edition_publisher.publish(Float32(data=version))
        self.voltage_publisher.publish(Float32(data=voltage))

        velocity = Twist()
        velocity.linear.x = float(vx)
        velocity.linear.y = float(vy)
        velocity.angular.z = float(angular)
        self.velocity_publisher.publish(velocity)

        imu = Imu()
        imu.header.stamp = timestamp
        imu.header.frame_id = self.imu_link
        imu.orientation_covariance[0] = -1.0
        imu.linear_acceleration.x = float(ax)
        imu.linear_acceleration.y = float(ay)
        imu.linear_acceleration.z = float(az)
        imu.angular_velocity.x = float(gx)
        imu.angular_velocity.y = float(gy)
        imu.angular_velocity.z = float(gz)
        imu.angular_velocity_covariance = [
            0.02, 0.0, 0.0,
            0.0, 0.02, 0.0,
            0.0, 0.0, 0.02,
        ]
        imu.linear_acceleration_covariance = [
            0.10, 0.0, 0.0,
            0.0, 0.10, 0.0,
            0.0, 0.0, 0.10,
        ]
        self.imu_publisher.publish(imu)

        attitude = Imu()
        attitude.header.stamp = timestamp
        attitude.header.frame_id = self.imu_link
        half_roll = float(roll) * 0.5
        half_pitch = float(pitch) * 0.5
        half_yaw = float(yaw) * 0.5
        cr, sr = math.cos(half_roll), math.sin(half_roll)
        cp, sp = math.cos(half_pitch), math.sin(half_pitch)
        cy, sy = math.cos(half_yaw), math.sin(half_yaw)
        attitude.orientation.x = sr * cp * cy - cr * sp * sy
        attitude.orientation.y = cr * sp * cy + sr * cp * sy
        attitude.orientation.z = cr * cp * sy - sr * sp * cy
        attitude.orientation.w = cr * cp * cy + sr * sp * sy
        attitude.orientation_covariance = [
            0.01, 0.0, 0.0,
            0.0, 0.01, 0.0,
            0.0, 0.0, 0.01,
        ]
        attitude.angular_velocity.x = float(gx)
        attitude.angular_velocity.y = float(gy)
        attitude.angular_velocity.z = float(gz)
        attitude.angular_velocity_covariance = list(
            imu.angular_velocity_covariance)
        attitude.linear_acceleration_covariance[0] = -1.0
        self.attitude_publisher.publish(attitude)

        magnetic = MagneticField()
        magnetic.header.stamp = timestamp
        magnetic.header.frame_id = self.imu_link
        magnetic.magnetic_field.x = float(mx)
        magnetic.magnetic_field.y = float(my)
        magnetic.magnetic_field.z = float(mz)
        magnetic.magnetic_field_covariance = [
            1e-6, 0.0, 0.0,
            0.0, 1e-6, 0.0,
            0.0, 0.0, 1e-6,
        ]
        self.mag_publisher.publish(magnetic)

        joints = JointState()
        joints.header.stamp = timestamp
        joints.header.frame_id = 'base_link'
        names = [
            'back_right_joint', 'back_left_joint',
            'front_left_steer_joint', 'front_left_wheel_joint',
            'front_right_steer_joint', 'front_right_wheel_joint',
        ]
        joints.name = [self.prefix + name for name in names]
        joints.position = [0.0] * len(names)
        joints.velocity = [float(vx), float(vx), 0.0, float(vx), 0.0, float(vx)]
        self.joint_publisher.publish(joints)

    def _send_zero(self, reason):
        self.safety.mark_zero_sent()
        if self.car is None:
            return False
        try:
            self.car.set_car_motion(0.0, 0.0, 0.0)
            return self._serial_is_healthy()
        except Exception as exc:
            self.get_logger().error(
                'Unable to send zero (%s): %s' % (reason, exc))
            return False

    def _mark_disconnected(self, reason):
        if self.connected:
            self._send_zero(reason)
            self.get_logger().error('Chassis disconnected: %s' % reason)
        self.connected = False
        self.reconnect.mark_disconnected(time.monotonic())
        self._close_serial()
        self._publish_connection()

    def _serial_is_healthy(self):
        serial_port = getattr(self.car, 'ser', None) if self.car else None
        return serial_endpoint_is_healthy(serial_port)

    def _close_serial(self):
        serial_port = getattr(self.car, 'ser', None) if self.car else None
        if serial_port is not None:
            try:
                if getattr(serial_port, 'is_open', False):
                    serial_port.close()
            except Exception:
                pass

    def _publish_connection(self):
        self.connection_publisher.publish(Bool(data=bool(self.connected)))

    def _rgb_callback(self, message):
        if not self.connected or self.car is None:
            return
        try:
            self.car.set_colorful_effect(int(message.data), 6, parm=1)
        except Exception as exc:
            self._mark_disconnected('RGB command failed: %s' % exc)

    def _buzzer_callback(self, message):
        if not self.connected or self.car is None:
            return
        try:
            self.car.set_beep(1 if message.data else 0)
        except Exception as exc:
            self._mark_disconnected('buzzer command failed: %s' % exc)


# Preserve the original class import name for downstream code.
icar_driver = IcarDriver


def main(args=None):
    """Run the driver and guarantee best-effort zero on graceful exit."""
    rclpy.init(args=args)
    driver = IcarDriver()
    atexit.register(driver.shutdown)

    def _terminate(_signum, _frame):
        driver.shutdown()
        if rclpy.ok():
            rclpy.shutdown()

    signal.signal(signal.SIGTERM, _terminate)
    try:
        rclpy.spin(driver)
    except KeyboardInterrupt:
        pass
    finally:
        driver.shutdown()
        driver.destroy_node()
        if rclpy.ok():
            rclpy.shutdown()


if __name__ == '__main__':
    main()
