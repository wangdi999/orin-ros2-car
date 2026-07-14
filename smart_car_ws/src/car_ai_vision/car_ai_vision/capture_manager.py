"""
异常行为截帧保存模块。

当 abnormal_behavior 触发时，自动保存前后各 30 帧到 ~/smart_car_ws/captures/。
文件命名格式: abnormal_<timestamp>_frame_<seq>.jpg
"""

import os
import time
import threading
from collections import deque
from pathlib import Path

import cv2
import numpy as np


class CaptureManager:
    """
    异常行为截帧管理器。

    维护一个环形缓冲区，保留最近 N 帧；
    当异常行为触发时，将缓冲区 + 后续 N 帧写入磁盘。
    """

    def __init__(self, buffer_size: int = 30, capture_dir: str = None):
        """
        初始化截帧管理器。

        Args:
            buffer_size: 前后各保存的帧数（默认30）
            capture_dir: 保存目录，默认为 ~/smart_car_ws/captures/
        """
        self._buffer_size = buffer_size
        self._buffer = deque(maxlen=buffer_size)
        self._lock = threading.Lock()

        if capture_dir is None:
            capture_dir = os.path.join(
                str(Path.home()), "smart_car_ws", "captures"
            )
        self._capture_dir = capture_dir
        os.makedirs(self._capture_dir, exist_ok=True)

        # 截帧状态
        self._active = False           # 是否正在截帧
        self._frames_to_save = 0       # 还需保存的后置帧数
        self._save_buffer = []         # 待写入的帧缓存
        self._save_timestamp = ""      # 截帧批次时间戳

    def feed(self, frame: np.ndarray) -> None:
        """
        输入一帧到缓冲区。

        Args:
            frame: BGR 格式的 numpy 图像
        """
        with self._lock:
            self._buffer.append(frame.copy())

            if self._active:
                self._frames_to_save -= 1
                self._save_buffer.append(frame.copy())
                if self._frames_to_save <= 0:
                    # 后置帧收集完毕，异步写入磁盘
                    self._active = False
                    self._flush_async()

    def trigger(self) -> None:
        """触发异常行为截帧——保存缓冲区内前置帧并开始收集后置帧。"""
        with self._lock:
            if self._active:
                # 已在截帧中，重置后置帧计数并清空已收集的后置帧
                # （避免新旧截帧批次帧交错）
                self._frames_to_save = self._buffer_size
                self._save_buffer = list(self._buffer)
                self._save_timestamp = time.strftime("%Y%m%d_%H%M%S")
                return

            self._active = True
            self._frames_to_save = self._buffer_size
            self._save_timestamp = time.strftime("%Y%m%d_%H%M%S")
            # 复制缓冲区作为前置帧
            self._save_buffer = list(self._buffer)

    def _flush_async(self) -> None:
        """异步将截帧写入磁盘（在独立线程中执行）。"""
        frames_copy = self._save_buffer[:]
        timestamp = self._save_timestamp
        capture_dir = self._capture_dir

        thread = threading.Thread(
            target=self._write_frames,
            args=(frames_copy, timestamp, capture_dir),
            daemon=True,
        )
        thread.start()

    @staticmethod
    def _write_frames(
        frames: list, timestamp: str, capture_dir: str
    ) -> None:
        """
        将帧列表写入磁盘。

        Args:
            frames: BGR 格式图像列表
            timestamp: 批次时间戳
            capture_dir: 保存目录
        """
        for seq, frame in enumerate(frames):
            filename = f"abnormal_{timestamp}_frame_{seq:04d}.jpg"
            filepath = os.path.join(capture_dir, filename)
            cv2.imwrite(filepath, frame, [cv2.IMWRITE_JPEG_QUALITY, 85])

    @property
    def is_active(self) -> bool:
        """是否正在截帧中。"""
        return self._active
