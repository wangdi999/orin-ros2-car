"""异常行为规则引擎单元测试。"""

from car_ai_vision.abnormal_behavior import AbnormalBehaviorDetector


def _fallen_bbox(x=100, y=200, width=200, height=80):
    """宽高比 2.5 的倒地姿态框。"""
    return (x, y, x + width, y + height)


def _standing_bbox(x=100, y=100, width=60, height=180):
    """宽高比 ~0.33 的站立姿态框。"""
    return (x, y, x + width, y + height)


def _feed_frames(detector, bbox, count, depth=None):
    """连续喂入相同检测框，返回最后一帧判定结果。"""
    results = []
    for _ in range(count):
        depth_values = [depth] if depth is not None else None
        results = detector.update([bbox], depth_values)
    return results[0]


class TestAbnormalBehaviorDetector:
    def test_standing_person_is_not_abnormal(self):
        detector = AbnormalBehaviorDetector(consecutive_frames=5)
        result = _feed_frames(detector, _standing_bbox(), count=10)
        assert result is False

    def test_fallen_person_triggers_after_consecutive_still_frames(self):
        detector = AbnormalBehaviorDetector(consecutive_frames=5)
        bbox = _fallen_bbox()
        results = []
        for _ in range(5):
            results = detector.update([bbox], None)
        assert results[0] is False
        results = detector.update([bbox], None)
        assert results[0] is True

    def test_high_depth_variance_blocks_abnormal(self):
        detector = AbnormalBehaviorDetector(consecutive_frames=3)
        bbox = _fallen_bbox()
        depths = [1.0, 2.0, 3.0]
        results = []
        for depth in depths:
            results = detector.update([bbox], [depth])
        assert results[0] is False

    def test_low_depth_variance_allows_abnormal(self):
        detector = AbnormalBehaviorDetector(consecutive_frames=3)
        bbox = _fallen_bbox()
        depths = [1.5, 1.51, 1.49, 1.5]
        results = []
        for depth in depths:
            results = detector.update([bbox], [depth])
        assert results[0] is True

    def test_hysteresis_locks_fallen_state_until_recovery(self):
        detector = AbnormalBehaviorDetector(consecutive_frames=3)
        standing = _standing_bbox()
        fallen = _fallen_bbox()

        for _ in range(4):
            detector.update([standing], None)
        for _ in range(4):
            detector.update([fallen], None)

        partial_recovery = (100, 200, 160, 280)
        results = detector.update([partial_recovery], None)
        assert results[0] is False

        full_recovery = (100, 100, 60, 180)
        for _ in range(3):
            results = detector.update([full_recovery], None)
        assert results[0] is False

    def test_reset_clears_tracks(self):
        detector = AbnormalBehaviorDetector(consecutive_frames=3)
        _feed_frames(detector, _fallen_bbox(), count=5)
        detector.reset()
        assert len(detector._tracks) == 0

    def test_iou_matching_tracks_same_person(self):
        detector = AbnormalBehaviorDetector(consecutive_frames=3)
        bbox_a = (10, 10, 50, 90)
        bbox_b = (12, 12, 52, 92)
        detector.update([bbox_a], None)
        detector.update([bbox_b], None)
        assert len(detector._tracks) == 1
