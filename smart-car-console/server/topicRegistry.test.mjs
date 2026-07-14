import assert from 'node:assert/strict';
import test from 'node:test';
import { subscriptionTopics, TOPIC_REGISTRY } from './topicRegistry.mjs';

test('topic registry exposes TF, AMCL, paths, costmaps, action status and patrol route read-only inputs', () => {
  const byTopic = new Map(TOPIC_REGISTRY.map((entry) => [entry.topic, entry]));
  for (const topic of [
    '/tf', '/tf_static', '/amcl_pose', '/plan', '/local_plan',
    '/global_costmap/costmap', '/local_costmap/costmap',
    '/navigate_to_pose/_action/status', '/patrol/route'
  ]) {
    assert.equal(byTopic.get(topic)?.direction, 'subscribe', topic);
  }
  assert.ok(byTopic.get('/map').throttleRate >= 500);
  assert.ok(byTopic.get('/global_costmap/costmap').throttleRate >= 500);
  assert.match(byTopic.get('/joint_states').description, /not treated as encoder/i);
});

test('rosbridge subscriptions use ROS 1-style type spelling required by rosbridge', () => {
  const subscriptions = new Map(subscriptionTopics().map((entry) => [entry.topic, entry.type]));
  assert.equal(subscriptions.get('/tf'), 'tf2_msgs/TFMessage');
  assert.equal(subscriptions.get('/amcl_pose'), 'geometry_msgs/PoseWithCovarianceStamped');
  assert.equal(subscriptions.get('/plan'), 'nav_msgs/Path');
});
