"""砍掉 Android App 模拟代码 + 替换文字 + 优化布局"""
import re

with open('mobile/src/main/java/com/smartcar/remote/MainActivity.java', 'r', encoding='utf-8') as f:
    code = f.read()

# ============================================================
# 1. 删除 mockMode 字段
# ============================================================
code = code.replace('    private boolean mockMode = false;\n', '')

# 删除模式按钮引用
code = code.replace('    private Button modeButton;\n', '')
code = re.sub(r'\s*modeText = metric\("模式", "CAR"\);\n', '', code)
code = re.sub(r"\s*modeText = metric\(\"模式\", \"CAR\"\);\n", '', code)

# ============================================================
# 2. 删除 toggleMockMode + applyMockConnectionPreset
# ============================================================
# toggleMockMode
m = re.search(r'private void toggleMockMode\(\) \{.*?\n    \}', code, re.DOTALL)
if m: code = code.replace(m.group(), '')

# applyMockConnectionPreset
m = re.search(r'private void applyMockConnectionPreset\(\) \{.*?\n    \}', code, re.DOTALL)
if m: code = code.replace(m.group(), '')

# ============================================================
# 3. 删除 SimpleTcpConnection 类
# ============================================================
m = re.search(r'private static final class SimpleTcpConnection.*?\n    \}', code, re.DOTALL)
if m: code = code.replace(m.group(), '')

# ============================================================
# 4. 简化 connect() mockMode 分支
# ============================================================
code = code.replace(
    '        connection = mockMode\n'
    '                ? new SimpleTcpConnection(host, portNumber, callback)\n'
    '                : new SimpleWebSocket(host, portNumber, callback);',
    '        connection = new SimpleWebSocket(host, portNumber, callback);'
)
code = code.replace(
    '        setStatus("正在连接：" + (mockMode ? "mock://" : "ws://") + host + ":" + portNumber);',
    '        setStatus("正在连接 ws://" + host + ":" + portNumber);'
)
code = code.replace(
    'setStatus("已连接：" + (mockMode ? "模拟服务 " : url));',
    'setStatus("已连接 ws://" + host + ":" + port);'
)

# 删除 connect() 中 mockMode 判断逻辑块
code = re.sub(
    r'if \(!mockMode && host\.startsWith\("10\.0\.2\.2"\)\).*?\n        \}',
    '',
    code, flags=re.DOTALL
)

# 删除 setConnectionGuide mockMode 三元
code = re.sub(
    r'setConnectionGuide\(mockMode\s*\n\s*\?.*?\n\s*:.*?\);\n',
    'setConnectionGuide("正在连接 ws://" + host + ":" + port + " ...");\n',
    code, flags=re.DOTALL
)

# 删除 connect 中的 mockMode 判断
code = re.sub(
    r'if \(!mockMode && host\.startsWith\("10\.0\.2\.2"\)\) \{\n.*?\n.*?\n.*?\n',
    '',
    code
)

# ============================================================
# 5. 替换文字
# ============================================================
replacements = [
    ('statusText = hintText("未连接：当前是真实小车模式，请填写小车 IP 和 9090 端口。");',
     'statusText = hintText("未连接：请输入小车 IP 和端口");'),
    ('connectCard.addView(hintText("真实小车：IP 填小车终端显示的地址，端口通常为 9090。模拟测试才使用 10.0.2.2。"), matchWrap());',
     'connectCard.addView(hintText("输入小车终端显示的 IP 地址，端口默认 9090"), matchWrap());'),
    ('auxiliaryContent.addView(hintText("视频流来自成品控制台约定的小车端口：6500/video_feed。若画面为空，请先在小车端启动视频服务。"), matchWrap());',
     'auxiliaryContent.addView(hintText("AI检测画面来自小车 :6501/video_feed，若空白请确认 ai_web_bridge 已启动"), matchWrap());'),
    ('auxiliaryContent.addView(hintText("当前先用模拟检测展示告警框和报警联动；后续接入真实识别结果后，可把检测框坐标映射到此区域。"), matchWrap());',
     'auxiliaryContent.addView(hintText("AI检测告警将自动轮询刷新（每3秒），无需手动触发"), matchWrap());'),
    ('auxiliaryContent.addView(hintText("提示：点击"模拟检测"后，地图上的黄色点会切换到新的报警位置。"), matchWrap());',
     ''),
    ('auxiliaryContent.addView(hintText("诊断模块参考成品控制台：检查 ROSBridge、视频流、/cmd_vel 与遥测 topic。"), matchWrap());',
     'auxiliaryContent.addView(hintText("连接后自动订阅遥测并轮询 AI 告警"), matchWrap());'),
    ('setConnectionGuide("连接成功。现在请把速度调到 10%-25%，车轮悬空，先按"急停"，再短按"前进"。");',
     'setConnectionGuide("连接成功。可使用摇杆控制小车，AI检测画面自动加载");'),
    ('addLog("连接成功");',
     'addLog("已连接小车 ROSBridge，AI告警轮询已启动");'),
    ('telemetrySummary = "遥测：未订阅。连接成功后会自动订阅 /scan、/imu、/voltage、/vel_raw、/joint_states。";',
     'telemetrySummary = "遥测：等待连接...";'),
    ('telemetrySummary = "遥测：已订阅，无需重复订阅。等待 /scan、/imu、/voltage 等数据。";',
     'telemetrySummary = "遥测：等待传感器数据...";'),
    ('telemetrySummary = "遥测：已订阅 /scan、/imu/data_raw、/imu/mag、/voltage、/vel_raw、/joint_states，等待小车发布数据。";',
     'telemetrySummary = "遥测：等待小车发布传感器数据...";'),
    ('setStatus("未连接：请先连接小车，再订阅遥测");',
     'setStatus("未连接：请先连接小车");'),
    ('addLog("遥测订阅被拒绝：未连接");',
     'addLog("遥测：未连接小车");'),
    ('addLog("遥测已订阅，跳过重复请求");',
     'addLog("遥测：已订阅");'),
    ('addLog("已订阅遥测 topic");',
     'addLog("遥测订阅完成");'),
    ('setConnectionGuide("端口只能输入数字。真实小车 rosbridge 通常是 9090。");',
     'setConnectionGuide("端口默认 9090（ROSBridge WebSocket）");'),
    ('setStatus("连接失败：IP 和端口不能为空");',
     'setStatus("请输入小车 IP 和端口");'),
    ('setConnectionGuide("请先填写小车 IP。小车终端可用 hostname -I 查看，端口通常填 9090。");',
     'setConnectionGuide("请填写小车 IP 地址和端口号");'),
    ('return "找不到小车：请检查 IP 是否是小车当前 IP，不要把模拟器地址 10.0.2.2 用在真实小车上。";',
     'return "找不到小车：请检查 IP 是否正确，手机和小车是否在同一网络";'),
    ('return "WebSocket 握手失败：端口可能不是 rosbridge 服务。真实小车需要 rosbridge_server 监听 9090。";',
     'return "WebSocket 握手失败：请确认小车端 rosbridge_server 正在运行（端口 9090）";'),
    ('return "连接被拒绝：IP 能找到，但端口没有服务。请在小车终端启动 rosbridge，并确认 ss -lntp | grep 9090 有输出。";',
     'return "连接被拒绝：端口无服务。请在小车端运行 rosbridge_server";'),
    ('setControlsEnabled(false);\n        setStatus("未连接：摇杆控制不可用");',
     'setControlsEnabled(false);\n        setStatus("未连接");'),
    ('addLog("控制被拒绝：未连接");',
     'addLog("控制：未连接小车");'),
    ('addLog("控制被拒绝：未连接"',
     'addLog("控制：未连接小车"'),
    ('"订阅遥测"', '"刷新遥测"'),
    ('modeText.setText("模式\\n" + (mockMode ? "MOCK" : "CAR"));',
     'modeText.setText("类型\\nROS2");'),
]

for old, new in replacements:
    if old in code:
        code = code.replace(old, new)
    else:
        # Some may have slight formatting differences
        pass

# ============================================================
# 6. 删除 modeButton UI + 预设按钮
# ============================================================
code = code.replace('LinearLayout presetConnectRow = row();\n', '')
code = code.replace('presetConnectRow.addView(actionButton("填入模拟器地址", v -> applyMockConnectionPreset()), weighted());\n', '')
code = re.sub(r'connectCard\.addView\(presetConnectRow, matchWrap\(\)\);\n', '', code)

# modeButton 相关行
code = re.sub(r'modeButton = button\("真实小车：WebSocket"\);\n', '', code)
code = re.sub(r'modeButton\.setOnClickListener\(v -> toggleMockMode\(\)\);\n', '', code)
code = re.sub(r'styleButton\(modeButton.*?;\n', '', code)
code = re.sub(r'connectCard\.addView\(modeButton, matchWrap\(\)\);\n', '', code)

# ============================================================
# 7. 删除 HTML 占位视频用真实描述
# ============================================================
code = code.replace(
    '"<html><body style=\'margin:0;background:#07121f;color:#9dcfeb;font-family:sans-serif;display:flex;align-items:center;justify-content:center;height:100vh;text-align:center;\'>等待视频流<br/>http://小车IP:6500/video_feed</body></html>"',
    '"<html><body style=\'margin:0;background:#07121f;color:#9dcfeb;font-family:sans-serif;display:flex;align-items:center;justify-content:center;height:100vh;text-align:center;\'>等待AI检测画面<br/>http://小车IP:6501/video_feed</body></html>"'
)

# ============================================================
# 8. setConnectionGuide 清理
# ============================================================
code = re.sub(
    r'setConnectionGuide\(mockMode\n\s*\?.*?\n\s*:.*?\);\n',
    'setConnectionGuide("手机和小车需在同一网络，IP 填小车终端显示的地址");\n',
    code, flags=re.DOTALL
)

# ============================================================
# 9. 更新 PatrolMapView 提示
# ============================================================
code = code.replace(
    'canvas.drawText("巡检地图区域", 28, 44, paint);',
    'canvas.drawText("等待巡逻数据...", 28, 44, paint);'
)
code = code.replace(
    'canvas.drawText("提示：点击"模拟检测"后，地图上的黄色点会切换到新的报警位置。"',
    'canvas.drawText("等待巡逻数据..."'
)

# ============================================================
# 10. 清理残留的 mockMode 引用
# ============================================================
# 清理残留 mockMode（只在赋值/比较上下文中）
code = code.replace('mockMode', 'false')
# 恢复误改的字符串常量
code = code.replace('"false"', '"mockMode"')  # 恢复日志中的文本

with open('mobile/src/main/java/com/smartcar/remote/MainActivity.java', 'w', encoding='utf-8') as f:
    f.write(code)

print(f"Cleaned! {len(code)} chars")
