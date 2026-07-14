import assert from 'node:assert/strict';
import test from 'node:test';
import { configuredMapId, emptyRoute, navigationBlockers, numericRoutePoint, setRoutePoint } from '../src/navigationWorkbench.js';

test('workbench exposes concrete navigation blockers', () => {
  const blockers = navigationBlockers({
    config: { navigation: { mode: 'mapping' } },
    navigation: { safetyState: 'BLOCKED', goal: { state: 'ACTIVE' } },
    motionAcknowledged: false,
    route: emptyRoute()
  });
  assert.deepEqual(blockers, [
    '当前不是 navigation 模式',
    '尚未激活托管地图',
    '尚未确认运动风险提示',
    '安全状态为 BLOCKED',
    '已有活动目标',
    '路线尚未配置'
  ]);
});

test('only managed maps are considered active and blank route coordinates remain invalid', () => {
  assert.equal(configuredMapId({ navigation: { map: '/root/maps/campus_map.yaml' } }), 'campus_map');
  assert.equal(configuredMapId({ navigation: { map: '/root/ros2_navigation_overlay/install/share/icar_navigation/maps/campus_map.yaml' } }), null);
  assert.deepEqual(numericRoutePoint({ name: 'Home', x: '', y: null, yaw: '  ' }), {
    name: 'Home', x: null, y: null, yaw: null
  });
});

test('route editor keeps exactly Home plus three points', () => {
  const route = setRoutePoint(emptyRoute(), 3, { x: 2, y: 3, yaw: 1 });
  assert.equal(route.waypoints.length, 3);
  assert.deepEqual(route.waypoints[2], { name: 'Waypoint 3', x: 2, y: 3, yaw: 1 });
});
