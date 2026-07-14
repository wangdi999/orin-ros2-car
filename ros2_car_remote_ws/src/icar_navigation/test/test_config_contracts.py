"""Static tests for Foxy configs, launch ownership and safety defaults."""

from pathlib import Path
import re
import unittest
from xml.etree import ElementTree

import yaml

from icar_navigation.route_loader import load_route
from icar_navigation.config_utils import merge_node_parameters


ROOT = Path(__file__).resolve().parents[1]
CONFIG = ROOT / 'config'
LAUNCH = ROOT / 'launch'


class TestConfigContracts(unittest.TestCase):
    """Keep generated ROS artifacts aligned with the Spec Kit contracts."""

    def yaml(self, name):
        return yaml.safe_load((CONFIG / name).read_text(encoding='utf-8'))

    def test_all_yaml_files_parse(self):
        for path in CONFIG.glob('*.yaml'):
            with self.subTest(path=path.name):
                self.assertIsNotNone(yaml.safe_load(
                    path.read_text(encoding='utf-8')))

    def test_fastdds_profile_is_loopback_only_with_expanded_peer_range(self):
        root = ElementTree.parse(CONFIG / 'fastdds_localhost.xml').getroot()
        namespace = {
            'f': 'http://www.eprosima.com/XMLSchemas/fastRTPS_Profiles'}
        profiles = root.find('f:profiles', namespace)
        self.assertIsNotNone(profiles)
        descriptor = profiles.find(
            'f:transport_descriptors/f:transport_descriptor', namespace)
        self.assertEqual(descriptor.findtext(
            'f:maxInitialPeersRange', namespaces=namespace), '64')
        addresses = [element.text for element in descriptor.findall(
            'f:interfaceWhiteList/f:address', namespace)]
        self.assertEqual(addresses, ['127.0.0.1'])
        participant = profiles.find('f:participant', namespace)
        self.assertEqual(participant.get('is_default_profile'), 'true')

    def test_arbiter_and_safety_defaults_are_fail_closed(self):
        arbiter = self.yaml('arbiter.yaml')['cmd_vel_arbiter']['ros__parameters']
        self.assertEqual(arbiter['manual_timeout_sec'], 0.30)
        self.assertEqual(arbiter['nav_timeout_sec'], 0.30)
        self.assertEqual(arbiter['safety_state_timeout_sec'], 0.30)
        self.assertEqual(arbiter['chassis_state_timeout_sec'], 0.30)
        self.assertLessEqual(arbiter['max_linear_x'], 0.10)
        self.assertLessEqual(arbiter['max_angular_z'], 0.40)

        safety = self.yaml('safety.yaml')['safety_manager']['ros__parameters']
        self.assertNotIn('runtime_mode', safety)
        self.assertNotIn('startup_grace_sec', safety)
        self.assertFalse(safety['enable_real_low_battery'])
        self.assertEqual(safety['low_battery_window'], 10)
        self.assertEqual(safety['low_battery_threshold_v'], 10.8)
        self.assertEqual(safety['low_battery_recovery_v'], 11.1)
        self.assertEqual(safety['low_battery_sustain_sec'], 5.0)

    def test_safe_base_merges_exact_arbiter_params_before_overrides(self):
        merged = merge_node_parameters(
            CONFIG / 'arbiter.yaml',
            'cmd_vel_arbiter',
            {
                'max_linear_x': 0.05,
                'max_linear_y': 0.05,
                'max_angular_z': 0.30,
            })
        self.assertEqual(merged['manual_timeout_sec'], 0.30)
        self.assertEqual(merged['max_linear_x'], 0.05)
        self.assertEqual(merged['max_linear_y'], 0.05)
        self.assertEqual(merged['max_angular_z'], 0.30)
        launch = (LAUNCH / 'safe_base.launch.py').read_text(encoding='utf-8')
        self.assertIn('merge_node_parameters(', launch)
        self.assertIn('parameters=[arbiter_parameters]', launch)
        self.assertNotIn('parameters=[\n            arbiter_config,', launch)

    def test_ekf_is_only_odom_tf_owner(self):
        ekf = self.yaml('ekf.yaml')['ekf_filter_node']['ros__parameters']
        self.assertTrue(ekf['publish_tf'])
        self.assertEqual(ekf['odom_frame'], 'odom')
        self.assertEqual(ekf['base_link_frame'], 'base_footprint')
        self.assertGreaterEqual(float(ekf['frequency']), 20.0)
        self.assertLessEqual(float(ekf['sensor_timeout']), 0.02)
        self.assertTrue(ekf['odom0_config'][5])
        self.assertTrue(ekf['odom0_config'][11])
        self.assertNotIn('imu0', ekf)
        bringup = (Path(__file__).resolve().parents[2] / 'icar_bringup' /
                   'launch' / 'icar_bringup_X3_launch.py')
        self.assertIn("'pub_odom_tf': False", bringup.read_text(encoding='utf-8'))

    def test_cartographer_uses_external_odom_and_one_scan(self):
        lua = (CONFIG / 'cartographer_2d.lua').read_text(encoding='utf-8')
        required = [
            'tracking_frame = "base_link"',
            'published_frame = "odom"',
            'provide_odom_frame = false',
            'use_odometry = true',
            'num_laser_scans = 1',
        ]
        for text in required:
            self.assertIn(text, lua)

    def test_map_save_request_matches_foxy_write_state(self):
        save_map = (ROOT / 'scripts' / 'save_map.sh').read_text(
            encoding='utf-8')
        self.assertIn(
            'cartographer_ros_msgs/srv/WriteState', save_map)
        self.assertIn('"{filename: \'${pbstream}\'}"', save_map)
        self.assertNotIn('include_unfinished_submaps', save_map)
        self.assertIn(
            'image: ${basename}.pgm', save_map)
        self.assertIn('grep -Fxq', save_map)

    def test_mapping_and_navigation_map_owners_are_mutually_exclusive(self):
        mapping = (LAUNCH / 'mapping.launch.py').read_text(encoding='utf-8')
        navigation = (LAUNCH / 'navigation.launch.py').read_text(
            encoding='utf-8')
        self.assertIn("executable='cartographer_node'", mapping)
        self.assertIn("executable='occupancy_grid_node'", mapping)
        self.assertNotIn("executable='amcl'", mapping)
        self.assertIn("executable='amcl'", navigation)
        self.assertNotIn("executable='cartographer_node'", navigation)

    def test_slow_modes_extend_startup_grace_without_auto_reset(self):
        safe_base = (LAUNCH / 'safe_base.launch.py').read_text(
            encoding='utf-8')
        mapping = (LAUNCH / 'mapping.launch.py').read_text(encoding='utf-8')
        navigation = (LAUNCH / 'navigation.launch.py').read_text(
            encoding='utf-8')
        self.assertIn(
            "DeclareLaunchArgument('startup_grace_sec', default_value='5.0')",
            safe_base)
        self.assertIn(
            "DeclareLaunchArgument('startup_grace_sec', default_value='12.0')",
            mapping)
        self.assertIn(
            "DeclareLaunchArgument('startup_grace_sec', default_value='60.0')",
            navigation)
        self.assertIn("LaunchConfiguration('startup_grace_sec')", safe_base)
        self.assertIn("'startup_grace_sec': LaunchConfiguration(", mapping)
        self.assertIn("'startup_grace_sec': LaunchConfiguration(", navigation)

    def test_lidar_frame_is_fixed_at_source_without_alias_tf(self):
        safe_base = (LAUNCH / 'safe_base.launch.py').read_text(encoding='utf-8')
        self.assertIn("default_value='laser_link'", safe_base)
        for launch_file in (
                'safe_base.launch.py', 'mapping.launch.py',
                'navigation.launch.py', 'demo.launch.py'):
            text = (LAUNCH / launch_file).read_text(encoding='utf-8')
            self.assertIn("name='ROS_LOCALHOST_ONLY', value='1'", text)
            self.assertIn("name='FASTRTPS_DEFAULT_PROFILES_FILE'", text)
        combined = '\n'.join(path.read_text(encoding='utf-8')
                             for path in LAUNCH.glob('*.py'))
        self.assertNotIn('laser → laser_link', combined)
        self.assertNotIn('laser_to_laser_link', combined)

    def test_nav2_uses_foxy_plugins_footprint_and_zero_lateral_speed(self):
        nav = self.yaml('nav2_foxy.yaml')
        self.assertNotIn(
            'yaml_filename', nav['map_server']['ros__parameters'])
        self.assertNotIn(
            'default_bt_xml_filename',
            nav['bt_navigator']['ros__parameters'])
        self.assertEqual(
            nav['amcl']['ros__parameters']['robot_model_type'], 'differential')
        controller = nav['controller_server']['ros__parameters']
        follow = controller['FollowPath']
        self.assertEqual(follow['plugin'], 'dwb_core::DWBLocalPlanner')
        self.assertEqual(follow['max_vel_x'], 0.10)
        self.assertEqual(follow['max_vel_y'], 0.0)
        self.assertEqual(follow['max_vel_theta'], 0.40)
        self.assertEqual(controller['goal_checker']['xy_goal_tolerance'], 0.15)
        self.assertEqual(controller['goal_checker']['yaw_goal_tolerance'], 0.15)
        planner = nav['planner_server']['ros__parameters']['GridBased']
        self.assertEqual(planner['plugin'], 'nav2_navfn_planner/NavfnPlanner')
        footprint = nav['local_costmap']['local_costmap']['ros__parameters'][
            'footprint']
        local_costmap = nav['local_costmap']['local_costmap'][
            'ros__parameters']
        self.assertIsInstance(local_costmap['width'], int)
        self.assertIsInstance(local_costmap['height'], int)
        self.assertIn('-0.22', footprint)
        self.assertIn('0.18', footprint)

    def test_only_arbiter_source_code_publishes_final_cmd_vel(self):
        sources = list((ROOT / 'icar_navigation').glob('*.py'))
        pattern = re.compile(
            r"create_publisher\(\s*Twist\s*,\s*['\"]\/cmd_vel['\"]",
            re.MULTILINE)
        owners = [path.name for path in sources
                  if pattern.search(path.read_text(encoding='utf-8'))]
        self.assertEqual(owners, ['cmd_vel_arbiter.py'])
        navigation = (LAUNCH / 'navigation.launch.py').read_text(
            encoding='utf-8')
        self.assertEqual(
            navigation.count("('cmd_vel', '/cmd_vel_nav')"), 2)

    def test_repository_route_is_an_inert_null_coordinate_template(self):
        route = load_route(CONFIG / 'patrol_route.yaml')
        self.assertFalse(route.configured)
        self.assertIsNone(route.home.x)
        self.assertEqual(len(route.waypoints), 3)

    def test_demo_never_auto_starts_and_has_share_defaults(self):
        demo = (LAUNCH / 'demo.launch.py').read_text(encoding='utf-8')
        self.assertIn(
            "DeclareLaunchArgument('map', default_value=default_map)", demo)
        self.assertIn(
            "DeclareLaunchArgument('route_file', default_value=default_route)",
            demo)
        self.assertIn(
            "DeclareLaunchArgument('auto_start_patrol', default_value='false')",
            demo)

    def test_cancel_failure_estop_is_latched_until_explicit_reset(self):
        patrol = (ROOT / 'icar_navigation' / 'patrol_manager.py').read_text(
            encoding='utf-8')
        self.assertIn('self.estop_publisher.publish(Bool(data=True))', patrol)
        self.assertNotIn(
            'self.estop_publisher.publish(Bool(data=False))', patrol)

    def test_manual_takeover_cancels_patrol_and_direct_nav2_goals(self):
        arbiter = (ROOT / 'icar_navigation' / 'cmd_vel_arbiter.py').read_text(
            encoding='utf-8')
        self.assertIn("'/patrol/cancel'", arbiter)
        self.assertIn("'/navigate_to_pose/_action/cancel_goal'", arbiter)
        self.assertIn("'/navigate_to_pose/_action/status'", arbiter)

    def test_patrol_route_is_read_only_transient_local_path(self):
        patrol = (ROOT / 'icar_navigation' / 'patrol_manager.py').read_text(
            encoding='utf-8')
        self.assertIn("Path, '/patrol/route'", patrol)
        self.assertIn('DurabilityPolicy.TRANSIENT_LOCAL', patrol)
        self.assertIn('ReliabilityPolicy.RELIABLE', patrol)
        self.assertIn("message.header.frame_id = 'map'", patrol)
        self.assertIn('route_path_points(self.route)', patrol)


if __name__ == '__main__':
    unittest.main()
