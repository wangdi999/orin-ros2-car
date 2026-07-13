"""
异常行为规则引擎模块。

实现基于规则的倒地人员检测，全部条件 AND 判定：
  1. bbox 宽/高 > 1.5（倒地姿态，正常站立 ~0.3-0.6）
  2. 连续 15 帧同一人不动（IoU 匹配追踪 > 0.5）
  3. 深度方差 < 0.3（全身紧凑，排除站立）
  4. 滞回锁：进入 FALLEN 后必须 bbox 高度 > 原始站立高度 × 0.8 才恢复
"""

import numpy as np


class AbnormalBehaviorDetector:
    """
    异常行为检测器。

    对每个检测到的人员独立追踪帧级状态，
    在全部 AND 条件满足时判定为 abnormal_behavior。
    """

    def __init__(self, consecutive_frames: int = 15, iou_threshold: float = 0.5):
        """
        初始化异常行为检测器。

        Args:
            consecutive_frames: 判定静止所需的连续帧数（默认15）
            iou_threshold: IoU 匹配阈值（默认0.5）
        """
        self._consecutive_frames = consecutive_frames
        self._iou_threshold = iou_threshold

        # 每个追踪 ID 的状态
        # track_id → {
        #   "bbox_history": [(x1,y1,x2,y2), ...],
        #   "depth_history": [float, ...],
        #   "standing_height": float | None,
        #   "fallen": bool,
        #   "still_count": int,
        #   "stale_count": int,      # 连续未匹配帧数（用于延迟清理）
        # }
        self._tracks = {}
        self._next_track_id = 0
        self._max_stale_frames = 60  # 超过此帧数未匹配才清理追踪

    def _compute_iou(self, bbox_a, bbox_b) -> float:
        """
        计算两个边界框的 IoU（交并比）。

        Args:
            bbox_a: (x1, y1, x2, y2) 格式
            bbox_b: (x1, y1, x2, y2) 格式

        Returns:
            IoU 值 [0.0, 1.0]
        """
        x1 = max(bbox_a[0], bbox_b[0])
        y1 = max(bbox_a[1], bbox_b[1])
        x2 = min(bbox_a[2], bbox_b[2])
        y2 = min(bbox_a[3], bbox_b[3])

        inter_area = max(0, x2 - x1) * max(0, y2 - y1)
        area_a = (bbox_a[2] - bbox_a[0]) * (bbox_a[3] - bbox_a[1])
        area_b = (bbox_b[2] - bbox_b[0]) * (bbox_b[3] - bbox_b[1])
        union_area = area_a + area_b - inter_area

        if union_area <= 0:
            return 0.0
        return inter_area / union_area

    def _match_track(self, bbox) -> int:
        """
        将检测框匹配到现有追踪或创建新追踪。

        Args:
            bbox: (x1, y1, x2, y2) 格式

        Returns:
            匹配到的 track_id
        """
        best_iou = 0.0
        best_track_id = None

        for track_id, track in self._tracks.items():
            if not track["bbox_history"]:
                continue
            last_bbox = track["bbox_history"][-1]
            iou = self._compute_iou(last_bbox, bbox)
            if iou > best_iou:
                best_iou = iou
                best_track_id = track_id

        if best_iou >= self._iou_threshold and best_track_id is not None:
            return best_track_id

        # 无匹配，创建新追踪
        new_id = self._next_track_id
        self._next_track_id += 1
        self._tracks[new_id] = {
            "bbox_history": [],
            "depth_history": [],
            "standing_height": None,
            "fallen": False,
            "still_count": 0,
            "stale_count": 0,
        }
        return new_id

    def update(
        self, bboxes: list, depth_values: list
    ) -> list:
        """
        对一帧检测结果进行异常行为判定。

        Args:
            bboxes: 检测框列表，每个为 (x1, y1, x2, y2)
            depth_values: 各检测框对应的深度值列表（可为 None 表示无深度数据）

        Returns:
            异常判定结果列表，与 bboxes 一一对应，
            True 表示该检测框为异常行为
        """
        active_tracks = set()
        results = []

        # 第1步：所有已有追踪的 stale_count +1（后续匹配到的重置为0）
        for track in self._tracks.values():
            track["stale_count"] += 1

        for i, bbox in enumerate(bboxes):
            track_id = self._match_track(bbox)
            active_tracks.add(track_id)
            track = self._tracks[track_id]
            track["stale_count"] = 0  # 当前帧匹配到，重置失活计数

            x1, y1, x2, y2 = bbox
            width = x2 - x1
            height = y2 - y1

            # 条件1：宽高比 > 1.5（倒地姿态）
            aspect_ratio = width / max(height, 1e-6)
            is_wide_aspect = aspect_ratio > 1.5

            # 更新 bbox 历史
            track["bbox_history"].append(bbox)
            if len(track["bbox_history"]) > self._consecutive_frames:
                track["bbox_history"] = track["bbox_history"][
                    -self._consecutive_frames:
                ]

            # 条件2：连续N帧静止（IoU 匹配）
            if len(track["bbox_history"]) >= 2:
                iou_with_prev = self._compute_iou(
                    track["bbox_history"][-1], track["bbox_history"][-2]
                )
                if iou_with_prev >= self._iou_threshold:
                    track["still_count"] += 1
                else:
                    track["still_count"] = max(0, track["still_count"] - 1)
            is_still = track["still_count"] >= self._consecutive_frames

            # 条件3：深度方差 < 0.3
            depth_ok = False
            depth_var = float("inf")
            if (
                depth_values is not None
                and i < len(depth_values)
                and depth_values[i] is not None
            ):
                track["depth_history"].append(depth_values[i])
                if len(track["depth_history"]) > self._consecutive_frames:
                    track["depth_history"] = track["depth_history"][
                        -self._consecutive_frames:
                    ]
                if len(track["depth_history"]) >= 3:
                    depth_var = float(np.var(track["depth_history"]))
                    depth_ok = depth_var < 0.3
            else:
                # 无深度数据时跳过深度校验
                depth_ok = True

            # 记录站立高度（非倒地状态时）
            if not is_wide_aspect and not track["fallen"]:
                prev_height = (
                    track["standing_height"]
                    if track["standing_height"] is not None
                    else 0.0
                )
                track["standing_height"] = max(prev_height, height)

            # 条件4：滞回锁
            if track["fallen"]:
                # 已在倒地状态，检查恢复条件
                if track["standing_height"] is not None:
                    recovery_ratio = (
                        height / max(track["standing_height"], 1e-6)
                    )
                    if recovery_ratio > 0.8:
                        # 高度恢复 → 解除倒地状态
                        track["fallen"] = False
                        track["still_count"] = 0
                        track["depth_history"] = []
                is_abnormal = False
            else:
                # 不在倒地状态，检查是否进入
                is_abnormal = is_wide_aspect and is_still and depth_ok
                if is_abnormal:
                    track["fallen"] = True

            results.append(is_abnormal)

        # 清理不活跃的追踪（超过 max_stale_frames 帧未匹配）
        stale_ids = [
            tid for tid, t in self._tracks.items()
            if t["stale_count"] > self._max_stale_frames
        ]
        for stale_id in stale_ids:
            del self._tracks[stale_id]

        return results

    def reset(self) -> None:
        """重置所有追踪状态。"""
        self._tracks.clear()
        self._next_track_id = 0
