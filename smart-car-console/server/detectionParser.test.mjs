import assert from 'node:assert/strict';
import test from 'node:test';
import { parseDetection2DArray, parseDetectionsMessage, parseJsonDetections } from './detectionParser.mjs';

test('Detection2DArray parser normalizes boxes and best labels', () => {
  const parsed = parseDetection2DArray({
    header: { frame_id: 'camera' },
    detections: [
      {
        bbox: {
          center: { position: { x: 100, y: 80 } },
          size_x: 40,
          size_y: 20
        },
        results: [
          { hypothesis: { class_id: 'person', score: 0.92 } },
          { hypothesis: { class_id: 'chair', score: 0.11 } }
        ]
      }
    ]
  });

  assert.equal(parsed.connected, true);
  assert.equal(parsed.count, 1);
  assert.equal(parsed.detections[0].label, 'person');
  assert.equal(parsed.detections[0].confidence, 0.92);
  assert.equal(parsed.detections[0].x, 80);
  assert.equal(parsed.detections[0].y, 70);
  assert.equal(parsed.detections[0].width, 40);
});

test('std_msgs/String JSON detection parser supports lightweight box payloads', () => {
  const parsed = parseDetectionsMessage({
    data: JSON.stringify({
      width: 320,
      height: 240,
      boxes: [{ label: 'cone', confidence: 0.81, x: 10, y: 20, width: 30, height: 40 }]
    })
  }, 'std_msgs/String');

  assert.equal(parsed.connected, true);
  assert.equal(parsed.sourceWidth, 320);
  assert.equal(parsed.sourceHeight, 240);
  assert.equal(parsed.detections[0].label, 'cone');
  assert.equal(parsed.detections[0].centerX, 25);
});

test('invalid JSON reports a disconnected detection sample', () => {
  const parsed = parseJsonDetections('{bad json');
  assert.equal(parsed.connected, false);
  assert.match(parsed.lastError, /invalid/);
});
