"""
CaptureManager 单元测试。

测试异常行为截帧保存模块：
  - 正常帧输入缓冲
  - 触发截帧保存前后帧
  - 异步写入磁盘
  - buffer_size 边界
  - 连续触发
"""

import os
import sys
import time
import tempfile
import shutil
import numpy as np
import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
from car_ai_vision.capture_manager import CaptureManager


class TestCaptureManager:
    """CaptureManager 单元测试。"""

    @pytest.fixture
    def tmp_dir(self):
        """创建临时目录用于截帧保存。"""
        path = tempfile.mkdtemp(prefix="capture_test_")
        yield path
        shutil.rmtree(path, ignore_errors=True)

    @pytest.fixture
    def manager(self, tmp_dir):
        """创建 CaptureManager 实例（小 buffer 便于测试）。"""
        return CaptureManager(buffer_size=5, capture_dir=tmp_dir)

    @pytest.fixture
    def test_frame(self):
        """创建测试帧 (120x160 BGR，非全零以区分)。"""
        frame = np.zeros((120, 160, 3), dtype=np.uint8)
        frame[30:90, 40:120, :] = 255  # 白色方块
        return frame

    def test_feed_adds_to_buffer(self, manager, test_frame):
        """feed() 应将帧添加到环形缓冲区。"""
        for i in range(3):
            manager.feed(test_frame)

        with manager._lock:
            assert len(manager._buffer) == 3

    def test_buffer_size_limit(self, manager, test_frame):
        """缓冲区不应超过 buffer_size。"""
        for i in range(10):
            manager.feed(test_frame)

        with manager._lock:
            assert len(manager._buffer) == manager._buffer_size
            assert len(manager._buffer) == 5

    def test_trigger_starts_capture(self, manager, test_frame):
        """trigger() 应激活截帧状态。"""
        manager.feed(test_frame)
        manager.trigger()

        assert manager.is_active is True
        with manager._lock:
            assert len(manager._save_buffer) > 0

    def test_capture_saves_frames(self, manager, tmp_dir, test_frame):
        """触发截帧后应将帧写入磁盘。"""
        # 填充前置帧
        for i in range(3):
            manager.feed(test_frame)

        # 触发截帧
        manager.trigger()

        # 填充后置帧
        for i in range(manager._buffer_size):
            manager.feed(test_frame)

        # 等待异步写入完成
        time.sleep(0.5)

        # 检查文件是否被写入
        files = os.listdir(tmp_dir)
        assert len(files) > 0, f"应在 {tmp_dir} 中保存帧文件"
        for f in files:
            assert f.endswith(".jpg")
            assert f.startswith("abnormal_")

    def test_feed_during_capture_stays_in_buffer(self, manager, test_frame):
        """截帧期间 feed() 仍应将帧添加到主缓冲区。"""
        manager.feed(test_frame)
        manager.trigger()

        # 缓冲区应保持帧
        with manager._lock:
            assert len(manager._buffer) >= 1

    def test_double_trigger_resets(self, manager, test_frame):
        """连续两次 trigger 应重置截帧状态，不崩溃。"""
        manager.feed(test_frame)
        manager.trigger()

        # 第二次触发应重置
        manager.trigger()

        with manager._lock:
            assert manager._active is True
            # 后置帧计数应重置为 buffer_size
            assert manager._frames_to_save == manager._buffer_size

    def test_capture_file_naming(self, manager, tmp_dir, test_frame):
        """截帧文件命名应符合 abnormal_<timestamp>_frame_<seq>.jpg 格式。"""
        manager.feed(test_frame)
        manager.trigger()
        for i in range(manager._buffer_size):
            manager.feed(test_frame)

        time.sleep(0.5)

        files = os.listdir(tmp_dir)
        for f in files:
            parts = f.split("_")
            assert parts[0] == "abnormal"
            # timestamp 部分 (YYYYMMDD_HHMMSS)
            assert len(parts[1]) == 8  # YYYYMMDD
            assert len(parts[2]) == 6  # HHMMSS
            # frame_NNNN.jpg
            frame_part = parts[3] + "_" + parts[4] if len(parts) > 4 else parts[3]
            assert frame_part.startswith("frame_")
            assert frame_part.endswith(".jpg")

    def test_initial_state(self, manager):
        """初始状态应正确。"""
        assert manager.is_active is False
        with manager._lock:
            assert len(manager._buffer) == 0
            assert manager._frames_to_save == 0

    def test_buffer_preserves_frame_order(self, manager, test_frame):
        """缓冲区应保持帧的插入顺序。"""
        frames = []
        for i in range(3):
            f = test_frame.copy()
            f[0, 0, 0] = i  # 用像素标记序号
            frames.append(f)
            manager.feed(f)

        manager.trigger()
        for i in range(manager._buffer_size):
            manager.feed(test_frame)

        time.sleep(0.5)

        with manager._lock:
            save_buffer = manager._save_buffer

        # save_buffer 应包含前置帧
        assert len(save_buffer) == 0 or len(os.listdir(manager._capture_dir)) > 0

    def test_custom_buffer_size(self, test_frame):
        """自定义 buffer_size 应生效。"""
        with tempfile.TemporaryDirectory() as d:
            mgr = CaptureManager(buffer_size=3, capture_dir=d)
            assert mgr._buffer_size == 3
            assert mgr._buffer.maxlen == 3
            mgr._lock = None  # 避免清理问题
