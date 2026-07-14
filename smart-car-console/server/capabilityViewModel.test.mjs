import assert from 'node:assert/strict';
import test from 'node:test';
import { capabilityUiState, visibleCapabilityItems } from '../src/capabilityViewModel.js';

function registry(stale, items) {
  return { stale, items: Object.fromEntries(items.map((item) => [item.key, item])) };
}

test('UI scenarios keep supported inactive and stale modules, but hide fresh unsupported modules', () => {
  const scenarios = [
    ['safe_base', { key: 'safe_base', availability: 'SUPPORTED', runtime: 'ACTIVE', safety: 'SAFE' }, true],
    ['mapping', { key: 'mapping', availability: 'SUPPORTED', runtime: 'ACTIVE', safety: 'SAFE' }, true],
    ['navigation', { key: 'localization_navigation', availability: 'SUPPORTED', runtime: 'ACTIVE', safety: 'SAFE' }, true],
    ['vision', { key: 'depth_ir', availability: 'SUPPORTED', runtime: 'INACTIVE', safety: 'SAFE', reason: '已具备，未启动' }, true],
    ['ROS container stopped', { key: 'mapping', availability: 'SUPPORTED', runtime: 'STALE', safety: 'SAFE', reason: '容器停止' }, true],
    ['SSH failed', { key: 'safe_base', availability: 'SUPPORTED', runtime: 'STALE', safety: 'SAFE', reason: '保留缓存' }, true],
    ['fresh unsupported', { key: 'r2_only', availability: 'UNSUPPORTED', runtime: 'INACTIVE', safety: 'SAFE' }, false]
  ];

  for (const [name, item, expectedVisible] of scenarios) {
    const stale = name === 'ROS container stopped' || name === 'SSH failed';
    assert.equal(visibleCapabilityItems(registry(stale, [item])).length > 0, expectedVisible, name);
  }
});

test('blocked vendor cards always expose the fixed safety reason', () => {
  const state = capabilityUiState({
    availability: 'SUPPORTED',
    runtime: 'INACTIVE',
    safety: 'BLOCKED',
    blockedReason: '未接入 `/cmd_vel` 唯一安全仲裁，网页不可启动'
  });

  assert.equal(state.disabled, true);
  assert.equal(state.reason, '未接入 `/cmd_vel` 唯一安全仲裁，网页不可启动');
});
