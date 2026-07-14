"""
AI检测结果 Web可视化桥接节点。

订阅 /camera/ai_detections (可视化帧) 和 /chassis/ai_alarm (报警)，
在 HTTP :6501 端口提供：
  - GET /           自包含HTML仪表盘页面
  - GET /video_feed MJPEG实时视频流（浏览器原生支持）
  - GET /api/alarms 报警列表JSON
  - GET /api/perf   性能指标JSON

零外部依赖：仅使用 Python stdlib + ROS2 + OpenCV。
"""

import json
import os
import sys
import time
import threading
from collections import deque
from http.server import BaseHTTPRequestHandler, HTTPServer
from socketserver import ThreadingMixIn
from typing import Tuple, List, Optional, Dict, Any

import cv2
import numpy as np
import rclpy
from rclpy.node import Node
from sensor_msgs.msg import Image
from cv_bridge import CvBridge, CvBridgeError

# ROS2 报警消息类型
try:
    from car_ai_interfaces.msg import Alarm
except ImportError:
    Alarm = None


# ============================================================
# 常量
# ============================================================

DEFAULT_PORT = 6501
JPEG_QUALITY = 80
MAX_ALARMS = 50

# MJPEG multipart 边界
BOUNDARY = b'frame_boundary'

# HTML仪表盘页面（内嵌，零文件依赖）
DASHBOARD_HTML = r"""<!DOCTYPE html>
<html lang="zh-CN">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>AI检测可视化仪表盘</title>
<style>
  * { margin:0; padding:0; box-sizing:border-box; }
  body {
    background:#0d1117; color:#c9d1d9; font-family:'Segoe UI',system-ui,sans-serif;
    height:100vh; display:flex; flex-direction:column; overflow:hidden;
  }
  header {
    background:#161b22; padding:10px 20px; border-bottom:1px solid #30363d;
    display:flex; align-items:center; justify-content:space-between;
  }
  header h1 { font-size:1.2em; color:#58a6ff; }
  .status-dot {
    display:inline-block; width:10px; height:10px; border-radius:50%; margin-right:6px;
  }
  .status-dot.live { background:#3fb950; box-shadow:0 0 6px #3fb950; animation:pulse 2s infinite; }
  .status-dot.idle { background:#d29922; }
  @keyframes pulse { 0%,100%{opacity:1} 50%{opacity:0.4} }
  main {
    display:flex; flex:1; gap:12px; padding:12px; min-height:0;
  }
  .video-panel {
    flex:2; display:flex; flex-direction:column; background:#161b22;
    border-radius:8px; border:1px solid #30363d; overflow:hidden;
  }
  .video-panel h2 {
    padding:8px 12px; font-size:0.95em; background:#21262d;
    border-bottom:1px solid #30363d;
  }
  .video-panel img {
    flex:1; width:100%; object-fit:contain; background:#000;
  }
  .right-panel {
    flex:1; display:flex; flex-direction:column; gap:12px; min-width:320px; max-width:420px;
  }
  .alarm-panel, .perf-panel {
    background:#161b22; border-radius:8px; border:1px solid #30363d;
    display:flex; flex-direction:column; overflow:hidden;
  }
  .alarm-panel { flex:2; }
  .perf-panel { flex:1; }
  .panel-header {
    padding:8px 12px; font-size:0.95em; font-weight:600;
    background:#21262d; border-bottom:1px solid #30363d;
  }
  .alarm-list {
    flex:1; overflow-y:auto; padding:8px; font-size:0.82em;
  }
  .alarm-item {
    padding:6px 8px; margin-bottom:4px; border-radius:4px;
    border-left:3px solid; font-family:'Cascadia Code',Consolas,monospace;
  }
  .alarm-item.person {
    background:rgba(210,153,34,0.1); border-color:#d29922;
  }
  .alarm-item.abnormal {
    background:rgba(248,81,73,0.15); border-color:#f85149;
  }
  .alarm-time { color:#8b949e; font-size:0.85em; }
  .alarm-type { font-weight:600; }
  .alarm-conf { color:#7ee787; }
  .perf-grid {
    display:grid; grid-template-columns:1fr 1fr; gap:8px; padding:12px;
  }
  .perf-card {
    background:#0d1117; border-radius:6px; padding:10px; text-align:center;
  }
  .perf-value { font-size:1.8em; font-weight:700; color:#58a6ff; }
  .perf-label { font-size:0.75em; color:#8b949e; margin-top:4px; }
  .perf-card.alarm-card .perf-value { color:#f85149; }
  .perf-card.alarm-card.abnormal-card .perf-value { color:#f0883e; }
  .empty-state {
    color:#484f58; text-align:center; padding:20px; font-style:italic;
  }
</style>
</head>
<body>
<header>
  <h1>AI检测可视化仪表盘</h1>
  <div>
    <span class="status-dot" id="statusDot"></span>
    <span id="statusText" style="font-size:0.85em;">连接中...</span>
  </div>
</header>
<main>
  <div class="video-panel">
    <h2>AI检测画面 (带检测框)</h2>
    <img src="/video_feed" alt="AI检测视频流" id="videoImg"
         onerror="document.getElementById('statusDot').className='status-dot idle';
                  document.getElementById('statusText').textContent='视频流断开'"
         onload="document.getElementById('statusDot').className='status-dot live';
                 document.getElementById('statusText').textContent='实时'">
  </div>
  <div class="right-panel">
    <div class="alarm-panel">
      <div class="panel-header">检测告警日志</div>
      <div class="alarm-list" id="alarmList">
        <div class="empty-state">等待告警...</div>
      </div>
    </div>
    <div class="perf-panel">
      <div class="panel-header">性能指标</div>
      <div class="perf-grid">
        <div class="perf-card">
          <div class="perf-value" id="perfFps">--</div>
          <div class="perf-label">接收FPS</div>
        </div>
        <div class="perf-card">
          <div class="perf-value" id="perfFrames">--</div>
          <div class="perf-label">总帧数</div>
        </div>
        <div class="perf-card alarm-card">
          <div class="perf-value" id="perfPerson">0</div>
          <div class="perf-label">人员检测</div>
        </div>
        <div class="perf-card alarm-card abnormal-card">
          <div class="perf-value" id="perfAbnormal">0</div>
          <div class="perf-label">异常行为</div>
        </div>
      </div>
    </div>
  </div>
</main>
<script>
  const ALARM_LIST = document.getElementById('alarmList');
  function timeAgo(ts) {
    if (!ts) return '';
    var d = new Date(ts);
    if (isNaN(d.getTime())) return ts;
    var now = new Date();
    var diff = Math.floor((now - d) / 1000);
    if (diff < 60) return diff + '秒前';
    if (diff < 3600) return Math.floor(diff/60) + '分钟前';
    return Math.floor(diff/3600) + '小时前';
  }
  function updateAlarms() {
    fetch('/api/alarms')
      .then(function(r) { return r.json(); })
      .then(function(data) {
        var alarms = data.alarms || [];
        if (alarms.length === 0) {
          ALARM_LIST.innerHTML = '<div class="empty-state">等待告警...</div>';
        } else {
          var html = '';
          for (var i = alarms.length - 1; i >= 0; i--) {
            var a = alarms[i];
            var cls = (a.danger_type === 'abnormal_behavior') ? 'abnormal' : 'person';
            var typeLabel = (a.danger_type === 'abnormal_behavior') ? 'ABNORMAL' : '人员检测';
            html += '<div class="alarm-item ' + cls + '">';
            html += '<span class="alarm-time">' + timeAgo(a.timestamp) + '</span> ';
            html += '<span class="alarm-type">' + typeLabel + '</span> ';
            html += '<span class="alarm-conf">conf=' + (a.confidence || 0).toFixed(2) + '</span>';
            if (a.pos_x != null) {
              html += ' pos=(' + a.pos_x.toFixed(1) + ',' + a.pos_y.toFixed(1) + ')';
            }
            html += '</div>';
          }
          ALARM_LIST.innerHTML = html;
        }
      })
      .catch(function() {
        ALARM_LIST.innerHTML = '<div class="empty-state">API连接失败</div>';
      });
  }
  function updatePerf() {
    fetch('/api/perf')
      .then(function(r) { return r.json(); })
      .then(function(data) {
        document.getElementById('perfFps').textContent = (data.fps || 0).toFixed(1);
        document.getElementById('perfFrames').textContent = data.total_frames || 0;
        document.getElementById('perfPerson').textContent =
          (data.total_by_type || {}).person_detected || 0;
        document.getElementById('perfAbnormal').textContent =
          (data.total_by_type || {}).abnormal_behavior || 0;
      })
      .catch(function() {});
  }
  // 每2秒轮询报警和性能数据
  setInterval(updateAlarms, 2000);
  setInterval(updatePerf, 2000);
  updateAlarms();
  updatePerf();
</script>
</body>
</html>"""


# ============================================================
# 线程安全的HTTPServer
# ============================================================

class ThreadedHTTPServer(ThreadingMixIn, HTTPServer):
    """多线程HTTP服务器，每个请求独立线程处理。"""
    allow_reuse_address = True
    daemon_threads = True


# ============================================================
# HTTP请求处理器
# ============================================================

class DashboardHandler(BaseHTTPRequestHandler):
    """
    HTTP请求处理器（由ThreadedHTTPServer每连接创建实例）。

    路由：
      GET /            仪表盘HTML页面
      GET /video_feed  MJPEG实时视频流
      GET /api/alarms  报警列表JSON
      GET /api/perf    性能指标JSON
    """

    # 类变量：由 AIWebBridgeNode 启动时注入
    bridge_node = None  # type: Optional[AIWebBridgeNode]

    def log_message(self, fmt, *args):
        """抑制HTTP访问日志（避免污染ROS2日志）。"""
        pass

    def _send_json(self, data, status=200):
        """发送JSON响应。"""
        body = json.dumps(data, ensure_ascii=False, default=str).encode('utf-8')
        self.send_response(status)
        self.send_header('Content-Type', 'application/json; charset=utf-8')
        self.send_header('Content-Length', len(body))
        self.send_header('Access-Control-Allow-Origin', '*')
        self.end_headers()
        self.wfile.write(body)

    def _send_html(self, html, status=200):
        """发送HTML响应。"""
        body = html.encode('utf-8')
        self.send_response(status)
        self.send_header('Content-Type', 'text/html; charset=utf-8')
        self.send_header('Content-Length', len(body))
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self):
        """GET请求路由。"""
        node = DashboardHandler.bridge_node
        if node is None:
            self._send_json({'error': 'Bridge node not ready'}, 503)
            return

        path = self.path.split('?')[0]  # 去掉查询参数

        # ---- / 仪表盘 ----
        if path == '/' or path == '/index.html':
            self._send_html(DASHBOARD_HTML)

        # ---- /video_feed MJPEG流 ----
        elif path == '/video_feed':
            self._stream_mjpeg(node)

        # ---- /api/alarms ----
        elif path == '/api/alarms':
            self._send_json(node.get_alarms_json())

        # ---- /api/perf ----
        elif path == '/api/perf':
            self._send_json(node.get_perf_json())

        # ---- 404 ----
        else:
            self._send_json({'error': 'Not found', 'path': path}, 404)

    def do_OPTIONS(self):
        """CORS预检请求。"""
        self.send_response(200)
        self.send_header('Access-Control-Allow-Origin', '*')
        self.send_header('Access-Control-Allow-Methods', 'GET, OPTIONS')
        self.send_header('Access-Control-Allow-Headers', '*')
        self.end_headers()

    def _stream_mjpeg(self, node):
        """
        MJPEG multipart/x-mixed-replace 实时流。

        持续从 node 获取最新帧，编码为JPEG推送。
        客户端断开时自动退出。
        """
        self.send_response(200)
        self.send_header(
            'Content-Type',
            'multipart/x-mixed-replace; boundary={}'.format(BOUNDARY.decode())
        )
        self.send_header('Cache-Control', 'no-cache, no-store, must-revalidate')
        self.send_header('Pragma', 'no-cache')
        self.send_header('Expires', '0')
        self.send_header('Access-Control-Allow-Origin', '*')
        self.send_header('Connection', 'close')
        self.end_headers()

        encode_param = [int(cv2.IMWRITE_JPEG_QUALITY), JPEG_QUALITY]

        try:
            while node.is_running():
                frame = node.get_latest_frame(timeout=1.0)
                if frame is None:
                    # 超时无新帧，发送心跳注释保持连接
                    self.wfile.write(
                        b'--%s\r\nContent-Type: text/plain\r\n\r\nheartbeat\r\n'
                        % BOUNDARY
                    )
                    self.wfile.flush()
                    continue

                # JPEG编码
                ok, jpeg = cv2.imencode('.jpg', frame, encode_param)
                if not ok:
                    continue

                # multipart帧
                self.wfile.write(b'--%s\r\n' % BOUNDARY)
                self.wfile.write(b'Content-Type: image/jpeg\r\n')
                self.wfile.write(
                    b'Content-Length: %d\r\n\r\n' % len(jpeg)
                )
                self.wfile.write(jpeg.tobytes())
                self.wfile.write(b'\r\n')
                self.wfile.flush()

        except (BrokenPipeError, ConnectionResetError, ConnectionAbortedError):
            # 客户端正常断开
            pass
        except Exception:
            # 其他错误，静默退出
            pass


# ============================================================
# ROS2桥接节点
# ============================================================

class AIWebBridgeNode(Node):
    """
    AI检测结果Web可视化桥接节点。

    订阅话题：
      - /camera/ai_detections  → MJPEG输出
      - /chassis/ai_alarm       → JSON API

    提供HTTP服务：
      - :6501 (可配置)
    """

    def __init__(self, port=DEFAULT_PORT):
        super().__init__('ai_web_bridge')

        self._port = port
        self._bridge = CvBridge()

        # ---- 帧缓存 ----
        self._frame_lock = threading.Lock()
        self._latest_frame = None  # type: Optional[np.ndarray]
        self._frame_available = threading.Event()

        # ---- 报警缓存 ----
        self._alarm_lock = threading.Lock()
        self._alarms = deque(maxlen=MAX_ALARMS)  # type: deque
        self._alarm_count_by_type = {
            'person_detected': 0,
            'abnormal_behavior': 0,
        }

        # ---- 性能统计 ----
        self._perf_lock = threading.Lock()
        self._frame_count = 0
        self._start_time = time.time()

        # ---- 运行控制 ----
        self._running = True

        # ---- 订阅 ----
        from rclpy.qos import QoSProfile

        sensor_qos = QoSProfile(depth=1)

        self._detections_sub = self.create_subscription(
            Image,
            '/camera/ai_detections',
            self._detections_callback,
            10,
        )

        if Alarm is not None:
            self._alarm_sub = self.create_subscription(
                Alarm,
                '/chassis/ai_alarm',
                self._alarm_callback,
                10,
            )
        else:
            self.get_logger().warn(
                'car_ai_interfaces.Alarm 不可用，报警订阅已禁用'
            )

        self.get_logger().info(
            'AI Web Bridge 已初始化，端口: {}'.format(self._port)
        )

    # ========================================================
    # ROS2回调
    # ========================================================

    def _detections_callback(self, msg: Image) -> None:
        """接收可视化帧 → 缓存最新帧。"""
        if not self._running:
            return
        try:
            frame = self._bridge.imgmsg_to_cv2(msg, desired_encoding='bgr8')

            with self._frame_lock:
                self._latest_frame = frame
                self._frame_available.set()

            with self._perf_lock:
                self._frame_count += 1

        except CvBridgeError as e:
            self.get_logger().warn(
                'CvBridge转换失败: {}'.format(e)
            )
        except Exception as e:
            self.get_logger().error(
                '帧回调异常: {}'.format(e)
            )

    def _alarm_callback(self, msg) -> None:
        """接收报警消息 → 追加到滚动列表。"""
        if not self._running:
            return

        try:
            alarm_dict = {
                'danger_type': msg.danger_type,
                'confidence': round(float(msg.confidence), 4),
                'timestamp': msg.timestamp,
                'pos_x': round(float(msg.pos_x), 2),
                'pos_y': round(float(msg.pos_y), 2),
                'coord_frame': msg.coord_frame,
                'bbox_center_x': round(float(msg.bbox_center_x), 2),
                'bbox_center_y': round(float(msg.bbox_center_y), 2),
                'bbox_width': round(float(msg.bbox_width), 2),
                'bbox_height': round(float(msg.bbox_height), 2),
            }

            dtype = alarm_dict['danger_type']
            with self._alarm_lock:
                self._alarms.append(alarm_dict)
                if dtype in self._alarm_count_by_type:
                    self._alarm_count_by_type[dtype] += 1

        except Exception as e:
            self.get_logger().error(
                '报警回调异常: {}'.format(e)
            )

    # ========================================================
    # 帧获取（供HTTP处理器调用）
    # ========================================================

    def get_latest_frame(self, timeout=1.0):
        """
        获取最新帧（阻塞等待）。

        Args:
            timeout: 等待超时秒数

        Returns:
            BGR numpy数组 或 None（超时）
        """
        if not self._frame_available.wait(timeout=timeout):
            return None
        self._frame_available.clear()

        with self._frame_lock:
            frame = self._latest_frame

        return frame

    def is_running(self):
        """检查节点是否仍在运行。"""
        return self._running and rclpy.ok()

    # ========================================================
    # JSON API（供HTTP处理器调用）
    # ========================================================

    def get_alarms_json(self):
        """获取报警列表JSON。"""
        with self._alarm_lock:
            alarms = list(self._alarms)
            total_by_type = dict(self._alarm_count_by_type)

        return {
            'alarms': alarms,
            'total_by_type': total_by_type,
            'count': len(alarms),
        }

    def get_perf_json(self):
        """获取性能指标JSON。"""
        with self._perf_lock:
            total_frames = self._frame_count
        with self._alarm_lock:
            total_by_type = dict(self._alarm_count_by_type)

        uptime = time.time() - self._start_time
        fps = total_frames / uptime if uptime > 0 else 0.0

        return {
            'fps': round(fps, 2),
            'total_frames': total_frames,
            'uptime_seconds': round(uptime, 1),
            'total_by_type': total_by_type,
        }

    # ========================================================
    # HTTP服务器
    # ========================================================

    def start_http_server(self):
        """在独立线程中启动HTTP服务器。"""
        DashboardHandler.bridge_node = self

        self._httpd = ThreadedHTTPServer(('0.0.0.0', self._port), DashboardHandler)

        self.get_logger().info(
            'AI可视化仪表盘: http://<jetson_ip>:{}/'.format(self._port)
        )
        self.get_logger().info(
            'MJPEG视频流:   http://<jetson_ip>:{}/video_feed'.format(self._port)
        )

        http_thread = threading.Thread(
            target=self._httpd.serve_forever,
            name='HTTPThread',
            daemon=True,
        )
        http_thread.start()

    # ========================================================
    # 生命周期
    # ========================================================

    def shutdown(self):
        """优雅关闭。"""
        self.get_logger().info('正在关闭 AI Web Bridge...')
        self._running = False
        self._frame_available.set()  # 唤醒等待线程

        if hasattr(self, '_httpd') and self._httpd is not None:
            self._httpd.shutdown()
            self._httpd.server_close()

        self.get_logger().info('AI Web Bridge 已关闭')


# ============================================================
# 入口
# ============================================================

def main(args=None):
    """节点入口函数（ros2 run 调用或直接 python3 执行）。"""
    rclpy.init(args=args)

    # 解析 --port 参数
    port = DEFAULT_PORT
    ros_args = []
    for i, arg in enumerate(sys.argv[1:]):
        if arg == '--port' or arg == '-p':
            if i + 1 < len(sys.argv) - 1:
                port = int(sys.argv[i + 2])
                ros_args = sys.argv[1:i + 1] + sys.argv[i + 3:]
                break
            else:
                port = int(sys.argv[i + 2])
                ros_args = sys.argv[1:i + 1]
                break
    else:
        ros_args = sys.argv[1:]

    # 也检查环境变量
    port = int(os.environ.get('AI_VIEWER_PORT', port))

    node = AIWebBridgeNode(port=port)
    node.start_http_server()

    try:
        rclpy.spin(node)
    except KeyboardInterrupt:
        node.get_logger().info('收到键盘中断')
    finally:
        node.shutdown()
        node.destroy_node()
        rclpy.shutdown()


# ============================================================
# 直接运行入口 (python3 ai_web_bridge.py --port 6501)
# ============================================================

if __name__ == '__main__':
    main()
