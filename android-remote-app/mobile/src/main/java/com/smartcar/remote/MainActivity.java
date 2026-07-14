package com.smartcar.remote;

import android.app.Activity;
import android.content.Context;
import android.graphics.Canvas;
import android.graphics.Color;
import android.graphics.Paint;
import android.graphics.RectF;
import android.graphics.Typeface;
import android.graphics.drawable.ColorDrawable;
import android.graphics.drawable.GradientDrawable;
import android.os.Bundle;
import android.os.Handler;
import android.os.Looper;
import android.view.Gravity;
import android.view.MotionEvent;
import android.view.View;
import android.view.Window;
import android.view.WindowManager;
import android.webkit.WebSettings;
import android.webkit.WebView;
import android.webkit.WebViewClient;
import android.widget.Button;
import android.widget.EditText;
import android.widget.LinearLayout;
import android.widget.ScrollView;
import android.widget.SeekBar;
import android.widget.TextView;

import android.util.Base64;

import java.io.BufferedInputStream;
import java.io.IOException;
import java.io.OutputStream;
import java.net.InetSocketAddress;
import java.net.Socket;
import java.nio.charset.StandardCharsets;
import java.security.SecureRandom;
import java.util.Arrays;
import java.util.ArrayList;
import java.util.List;
import java.util.Locale;
import java.util.concurrent.ExecutorService;
import java.util.concurrent.Executors;
import java.util.regex.Matcher;
import java.util.regex.Pattern;

public class MainActivity extends Activity {
    private static final String CMD_TOPIC = "/cmd_vel";
    private static final String CMD_TYPE = "geometry_msgs/Twist";
    private static final long HEARTBEAT_MS = 200L;
    private static final double MAX_LINEAR_SPEED = 0.35;
    private static final double MAX_STRAFE_SPEED = 0.25;
    private static final double MAX_ANGULAR_SPEED = 0.9;
    private static final long BUTTON_STOP_DELAY_MS = 350L;
    private static final int CONNECT_TIMEOUT_MS = 3000;
    private static final int HEARTBEAT_UI_UPDATE_EVERY = 5;

    private final Handler handler = new Handler(Looper.getMainLooper());
    private final List<Button> controlButtons = new ArrayList<>();

    private EditText hostInput;
    private EditText portInput;
    private TextView statusText;
    private TextView speedText;
    private TextView commandText;
    private TextView linkText;
    private TextView packetText;
    private TextView modeText;
    private TextView logText;
    private TextView heartbeatText;
    private TextView alarmText;
    private TextView connectionGuideText;
    private TextView videoStatusText;
    private TextView serviceStatusText;
    private TextView telemetryText;
    private WebView videoWebView;
    private DetectionPreview detectionPreview;
    private PatrolMapView patrolMapView;
    private JoystickView joystickView;
    private SeekBar speedSeek;
    private Button connectButton;
    private Button modeButton;
    private ScrollView mainScrollView;
    private View auxiliaryPanel;
    private LinearLayout auxiliaryContent;
    private Button videoTabButton;
    private Button mapTabButton;
    private Button logTabButton;

    private SmartConnection connection;
    private boolean connected = false;
    private boolean mockMode = false;
    private int sentCount = 0;
    private int heartbeatCount = 0;
    private final android.os.Handler aiPollHandler = new android.os.Handler();
    private Runnable aiPollRunnable;
    private int alarmCount = 0;
    private int connectionGeneration = 0;
    private String lastLogMessage = "等待连接...";
    private String lastAlarmMessage = "报警列表：暂无报警";
    private String telemetrySummary = "遥测：未订阅。连接成功后会自动订阅 /scan、/imu、/voltage、/vel_raw、/joint_states。";
    private double currentLinearX = 0.0;
    private double currentLinearY = 0.0;
    private double currentAngularZ = 0.0;
    private boolean shuttingDown = false;
    private boolean telemetrySubscribed = false;
    private int selectedAuxiliaryTab = -1;
    private long lastTelemetryUiUpdateMs = 0L;

    private final Runnable delayedButtonStop = () -> {
        if (connected) {
            emergencyStop();
        }
    };

    private final Runnable heartbeat = new Runnable() {
        @Override
        public void run() {
            if (connected) {
                publishCurrentVelocity();
                heartbeatCount++;
                if (heartbeatCount % HEARTBEAT_UI_UPDATE_EVERY == 0) {
                    updateHeartbeatText();
                }
                handler.postDelayed(this, HEARTBEAT_MS);
            }
        }
    };

    @Override
    protected void onCreate(Bundle savedInstanceState) {
        super.onCreate(savedInstanceState);
        prepareOpaqueWindow();
        setContentView(buildUi());
    }

    private void prepareOpaqueWindow() {
        Window window = getWindow();
        int background = Color.rgb(5, 13, 27);
        window.clearFlags(WindowManager.LayoutParams.FLAG_TRANSLUCENT_STATUS);
        window.clearFlags(WindowManager.LayoutParams.FLAG_TRANSLUCENT_NAVIGATION);
        window.addFlags(WindowManager.LayoutParams.FLAG_DRAWS_SYSTEM_BAR_BACKGROUNDS);
        window.setBackgroundDrawable(new ColorDrawable(background));
        window.setStatusBarColor(background);
        window.setNavigationBarColor(background);
        window.getDecorView().setBackgroundColor(background);
    }

    @Override
    protected void onDestroy() {
        shuttingDown = true;
        handler.removeCallbacksAndMessages(null);
        sendStopBeforeDestroy();
        if (videoWebView != null) {
            destroyVideoWebView();
        }
        if (connection != null) {
            connection.close();
        }
        super.onDestroy();
    }

    private View buildUi() {
        LinearLayout screen = new LinearLayout(this);
        screen.setOrientation(LinearLayout.VERTICAL);
        screen.setBackgroundColor(Color.rgb(5, 13, 27));

        ScrollView scrollView = new ScrollView(this);
        scrollView.setFillViewport(true);
        scrollView.setBackgroundColor(Color.rgb(5, 13, 27));
        mainScrollView = scrollView;

        LinearLayout root = new LinearLayout(this);
        root.setOrientation(LinearLayout.VERTICAL);
        root.setPadding(dp(18), dp(20), dp(18), dp(20));
        root.setBackgroundColor(Color.rgb(5, 13, 27));

        TextView title = new TextView(this);
        title.setText("SMART CAR COMMAND");
        title.setTextSize(25);
        title.setTypeface(Typeface.DEFAULT_BOLD);
        title.setTextColor(Color.rgb(234, 249, 255));
        title.setGravity(Gravity.CENTER_HORIZONTAL);
        root.addView(title, matchWrap());

        TextView subtitle = new TextView(this);
        subtitle.setText("新手遥控台  |  先连接  再低速  随时急停");
        subtitle.setTextColor(Color.rgb(108, 226, 255));
        subtitle.setTextSize(13);
        subtitle.setGravity(Gravity.CENTER_HORIZONTAL);
        subtitle.setPadding(0, dp(6), 0, dp(16));
        root.addView(subtitle, matchWrap());

        LinearLayout statusCard = panel();
        LinearLayout statusRow = row();
        linkText = metric("链路", "OFFLINE");
        modeText = metric("模式", "CAR");
        packetText = metric("发送", "0");
        statusRow.addView(linkText, weighted());
        statusRow.addView(modeText, weighted());
        statusRow.addView(packetText, weighted());
        statusCard.addView(statusRow, matchWrap());

        statusText = hintText("未连接：当前是真实小车模式，请填写小车 IP 和 9090 端口。");
        statusCard.addView(statusText, matchWrap());
        heartbeatText = hintText("心跳保护：连接后会持续发送当前速度，断开或急停会发停止指令。");
        heartbeatText.setTextColor(Color.rgb(157, 235, 255));
        statusCard.addView(heartbeatText, matchWrap());
        root.addView(statusCard, matchWrapWithBottom(14));

        LinearLayout guideCard = panel();
        guideCard.addView(sectionTitle("上手步骤"), matchWrap());
        guideCard.addView(hintText("1. 小车和手机连接同一网络；2. 小车启动 rosbridge，确认 9090 已监听；3. App 选择 CAR 后连接；4. 车轮悬空，速度 10%-25%，先试急停。"), matchWrap());
        root.addView(guideCard, matchWrapWithBottom(14));

        LinearLayout connectCard = panel();
        connectCard.addView(sectionTitle("连接控制"), matchWrap());
        connectCard.addView(hintText("真实小车：IP 填小车终端显示的地址，端口通常为 9090。模拟测试才使用 10.0.2.2。"), matchWrap());
        connectCard.addView(hintText("小车端检查：hostname -I 查看 IP；ss -lntp | grep 9090 确认 rosbridge 已启动。"), matchWrap());
        connectionGuideText = hintText("");
        connectCard.addView(connectionGuideText, matchWrap());

        LinearLayout connectRow = row();
        hostInput = input("172.20.10.14");
        portInput = input("9090");
        connectButton = button("连接");
        styleButton(connectButton, Color.rgb(20, 210, 255), Color.rgb(0, 83, 122), Color.WHITE);
        connectButton.setOnClickListener(v -> toggleConnection());
        modeButton = button("真实小车：WebSocket");
        styleButton(modeButton, Color.rgb(30, 46, 70), Color.rgb(30, 46, 70), Color.rgb(116, 231, 255));
        modeButton.setOnClickListener(v -> toggleMockMode());
        connectRow.addView(hostInput, weighted());
        connectRow.addView(portInput, fixedDp(86));
        connectRow.addView(connectButton, fixedDp(88));
        connectCard.addView(connectRow, matchWrap());

        LinearLayout presetConnectRow = row();
        presetConnectRow.addView(actionButton("填入小车地址", v -> applyCarConnectionPreset()), weighted());
        presetConnectRow.addView(actionButton("填入模拟器地址", v -> applyMockConnectionPreset()), weighted());
        connectCard.addView(presetConnectRow, matchWrap());
        connectCard.addView(modeButton, matchWrap());
        root.addView(connectCard, matchWrapWithBottom(14));

        LinearLayout commandCard = panel();
        commandCard.addView(sectionTitle("主控方向"), matchWrap());
        commandCard.addView(hintText("按住按钮移动，松开后自动停车。第一次只按 1 秒，确认方向正确后再继续。"), matchWrap());

        commandText = new TextView(this);
        commandText.setText("当前指令：停止");
        commandText.setTextColor(Color.rgb(157, 235, 255));
        commandText.setTextSize(13);
        commandText.setPadding(0, dp(12), 0, dp(12));
        commandCard.addView(commandText, matchWrap());

        commandCard.addView(controlRow("左前", "前进", "右前",
                command(1, 1, 0), command(1, 0, 0), command(1, -1, 0)));
        commandCard.addView(controlRow("左移", "停止", "右移",
                command(0, 1, 0), command(0, 0, 0), command(0, -1, 0)));
        commandCard.addView(controlRow("左后", "后退", "右后",
                command(-1, 1, 0), command(-1, 0, 0), command(-1, -1, 0)));
        commandCard.addView(controlRow("左转", "急停", "右转",
                command(0, 0, 1), command(0, 0, 0), command(0, 0, -1)));
        root.addView(commandCard, matchWrapWithBottom(14));

        LinearLayout speedCard = panel();
        speedCard.addView(sectionTitle("速度设置"), matchWrap());
        speedCard.addView(hintText("建议实车测试先用低速。速度越高，前进/转向指令越明显。"), matchWrap());

        speedText = new TextView(this);
        speedText.setText("速度：30%");
        speedText.setTextSize(18);
        speedText.setTypeface(Typeface.DEFAULT_BOLD);
        speedText.setTextColor(Color.rgb(234, 249, 255));
        speedCard.addView(speedText, matchWrap());

        speedSeek = new SeekBar(this);
        speedSeek.setMax(100);
        speedSeek.setProgress(30);
        speedSeek.setOnSeekBarChangeListener(new SeekBar.OnSeekBarChangeListener() {
            @Override
            public void onProgressChanged(SeekBar seekBar, int progress, boolean fromUser) {
                speedText.setText("速度：" + progress + "%");
            }

            @Override
            public void onStartTrackingTouch(SeekBar seekBar) {
            }

            @Override
            public void onStopTrackingTouch(SeekBar seekBar) {
            }
        });
        speedCard.addView(speedSeek, matchWrap());

        LinearLayout presetRow = row();
        presetRow.addView(presetButton("低速", 25), weighted());
        presetRow.addView(presetButton("巡航", 55), weighted());
        presetRow.addView(presetButton("高速", 85), weighted());
        speedCard.addView(presetRow, matchWrap());
        root.addView(speedCard, matchWrapWithBottom(14));

        LinearLayout auxCard = panel();
        auxiliaryPanel = auxCard;
        auxCard.addView(sectionTitle("辅助功能"), matchWrap());
        auxCard.addView(hintText("通过底部导航栏切换视频、地图和日志，辅助面板会保持在当前页面。"), matchWrap());
        auxiliaryContent = new LinearLayout(this);
        auxiliaryContent.setOrientation(LinearLayout.VERTICAL);
        auxCard.addView(auxiliaryContent, matchWrap());
        root.addView(auxCard, matchWrapWithBottom(14));

        LinearLayout nav = bottomNavigation();
        refreshConnectionGuide();
        selectAuxiliaryTab(0);
        setControlsEnabled(false);
        scrollView.addView(root);
        screen.addView(scrollView, new LinearLayout.LayoutParams(
                LinearLayout.LayoutParams.MATCH_PARENT,
                0,
                1f
        ));
        screen.addView(nav, matchWrap());
        return screen;
    }

    private LinearLayout bottomNavigation() {
        LinearLayout nav = new LinearLayout(this);
        nav.setOrientation(LinearLayout.HORIZONTAL);
        nav.setGravity(Gravity.CENTER);
        nav.setPadding(dp(10), dp(8), dp(10), dp(10));
        nav.setBackground(rounded(Color.rgb(6, 18, 32), Color.rgb(25, 96, 125), 1, 0));

        videoTabButton = tabButton("视频 / AI", 0);
        mapTabButton = tabButton("地图", 1);
        logTabButton = tabButton("日志 / 报警", 2);
        nav.addView(videoTabButton, weighted());
        nav.addView(mapTabButton, weighted());
        nav.addView(logTabButton, weighted());
        return nav;
    }

    private Button tabButton(String label, int index) {
        Button button = button(label);
        button.setTextSize(12);
        button.setMinHeight(dp(48));
        button.setOnClickListener(v -> {
            selectAuxiliaryTab(index);
            scrollToAuxiliaryPanel();
        });
        return button;
    }

    private void scrollToAuxiliaryPanel() {
        if (mainScrollView == null || auxiliaryPanel == null) {
            return;
        }
        mainScrollView.post(() -> mainScrollView.scrollTo(0, auxiliaryPanel.getTop()));
    }

    private void destroyVideoWebView() {
        if (videoWebView == null) {
            return;
        }
        if (auxiliaryContent != null) {
            auxiliaryContent.removeView(videoWebView);
        }
        videoWebView.stopLoading();
        videoWebView.destroy();
        videoWebView = null;
    }

    private void selectAuxiliaryTab(int index) {
        if (auxiliaryContent == null) {
            return;
        }
        if (index == selectedAuxiliaryTab && auxiliaryContent.getChildCount() > 0) {
            refreshDiagnosticPanel();
            return;
        }
        if (videoWebView != null) {
            destroyVideoWebView();
        }
        selectedAuxiliaryTab = index;
        auxiliaryContent.removeAllViews();
        styleTab(videoTabButton, index == 0);
        styleTab(mapTabButton, index == 1);
        styleTab(logTabButton, index == 2);

        if (index == 0) {
            auxiliaryContent.addView(hintText("视频流来自成品控制台约定的小车端口：6500/video_feed。若画面为空，请先在小车端启动视频服务。"), matchWrap());
            videoStatusText = hintText("视频状态：未打开。连接小车后点击“打开视频流”。");
            videoStatusText.setTextColor(Color.rgb(157, 235, 255));
            auxiliaryContent.addView(videoStatusText, matchWrap());
            videoWebView = new WebView(this);
            WebSettings settings = videoWebView.getSettings();
            settings.setLoadWithOverviewMode(true);
            settings.setUseWideViewPort(true);
            settings.setBuiltInZoomControls(false);
            settings.setDisplayZoomControls(false);
            videoWebView.setWebViewClient(new WebViewClient());
            videoWebView.setBackgroundColor(Color.rgb(7, 18, 31));
            videoWebView.loadDataWithBaseURL(
                    null,
                    "<html><body style='margin:0;background:#07121f;color:#9dcfeb;font-family:sans-serif;display:flex;align-items:center;justify-content:center;height:100vh;text-align:center;'>等待视频流<br/>http://小车IP:6500/video_feed</body></html>",
                    "text/html",
                    "UTF-8",
                    null
            );
            auxiliaryContent.addView(videoWebView, fixedHeight(dp(190)));
            LinearLayout videoActions = row();
            videoActions.addView(actionButton("打开视频流", v -> openVideoStream()), weighted());
            videoActions.addView(actionButton("刷新视频", v -> openVideoStream()), weighted());
            auxiliaryContent.addView(videoActions, matchWrap());
            auxiliaryContent.addView(sectionTitle("AI 检测框"), matchWrap());
            auxiliaryContent.addView(hintText("当前先用模拟检测展示告警框和报警联动；后续接入真实识别结果后，可把检测框坐标映射到此区域。"), matchWrap());
            detectionPreview = new DetectionPreview(this);
            auxiliaryContent.addView(detectionPreview, fixedHeight(dp(178)));
            LinearLayout visionActions = row();
            visionActions.addView(actionButton("清空告警", v -> clearAlarms()), weighted());
            auxiliaryContent.addView(visionActions, matchWrap());
            return;
        }

        if (index == 1) {
            auxiliaryContent.addView(hintText("巡检地图用于展示路线、当前位置和报警点。当前为演示地图，后续可接入真实定位数据。"), matchWrap());
            patrolMapView = new PatrolMapView(this);
            patrolMapView.setActiveIndex(alarmCount);
            auxiliaryContent.addView(patrolMapView, fixedHeight(dp(150)));
            auxiliaryContent.addView(hintText("提示：点击“模拟检测”后，地图上的黄色点会切换到新的报警位置。"), matchWrap());
            auxiliaryContent.addView(sectionTitle("辅助摇杆"), matchWrap());
            auxiliaryContent.addView(hintText("摇杆适合连续微调方向；新手测试优先使用上方主控按钮。"), matchWrap());
            joystickView = new JoystickView(this);
            joystickView.setListener((x, y) -> {
                if (!connected) {
                    setStatus("未连接：摇杆控制不可用");
                    return;
                }
                setVelocity(-y, x, 0);
            });
            auxiliaryContent.addView(joystickView, fixedHeight(dp(180)));
            return;
        }

        auxiliaryContent.addView(hintText("诊断模块参考成品控制台：检查 ROSBridge、视频流、/cmd_vel 与遥测 topic。"), matchWrap());
        serviceStatusText = hintText(buildServiceStatusText());
        serviceStatusText.setTextColor(Color.rgb(157, 235, 255));
        auxiliaryContent.addView(serviceStatusText, matchWrap());
        telemetryText = hintText(telemetrySummary);
        telemetryText.setTextColor(Color.rgb(157, 235, 255));
        auxiliaryContent.addView(telemetryText, matchWrap());
        LinearLayout diagnosticActions = row();
        diagnosticActions.addView(actionButton("订阅遥测", v -> subscribeTelemetry()), weighted());
        diagnosticActions.addView(actionButton("刷新状态", v -> refreshDiagnosticPanel()), weighted());
        auxiliaryContent.addView(diagnosticActions, matchWrap());
        auxiliaryContent.addView(sectionTitle("运行日志"), matchWrap());
        auxiliaryContent.addView(hintText("运行日志用于判断连接是否成功、rosbridge 是否报错、控制指令是否发出。"), matchWrap());
        logText = new TextView(this);
        logText.setText(lastLogMessage);
        logText.setTextColor(Color.rgb(172, 190, 210));
        logText.setTextSize(12);
        logText.setPadding(0, dp(8), 0, 0);
        auxiliaryContent.addView(logText, matchWrap());
        auxiliaryContent.addView(sectionTitle("报警列表"), matchWrap());
        alarmText = new TextView(this);
        alarmText.setText(lastAlarmMessage);
        alarmText.setTextColor(Color.rgb(255, 196, 112));
        alarmText.setTextSize(12);
        alarmText.setPadding(0, dp(10), 0, 0);
        auxiliaryContent.addView(alarmText, matchWrap());
    }

    private void styleTab(Button button, boolean selected) {
        if (button == null) {
            return;
        }
        if (selected) {
            styleButton(button, Color.rgb(20, 210, 255), Color.rgb(0, 83, 122), Color.WHITE);
        } else {
            styleButton(button, Color.rgb(15, 34, 56), Color.rgb(15, 34, 56), Color.rgb(116, 231, 255));
        }
    }

    private LinearLayout controlRow(String a, String b, String c, double[] va, double[] vb, double[] vc) {
        LinearLayout row = row();
        row.addView(controlButton(a, va), weighted());
        row.addView(controlButton(b, vb), weighted());
        row.addView(controlButton(c, vc), weighted());
        return row;
    }

    private Button controlButton(String label, double[] velocity) {
        Button button = button(label);
        button.setTextSize(18);
        button.setTypeface(Typeface.DEFAULT_BOLD);
        if ("急停".equals(label)) {
            styleButton(button, Color.rgb(255, 73, 100), Color.rgb(115, 22, 42), Color.WHITE);
        } else if ("停止".equals(label)) {
            styleButton(button, Color.rgb(255, 180, 77), Color.rgb(90, 58, 22), Color.WHITE);
        } else {
            styleButton(button, Color.rgb(31, 53, 84), Color.rgb(31, 53, 84), Color.rgb(205, 247, 255));
        }
        button.setOnTouchListener((v, event) -> {
            if (!connected) {
                setStatus("未连接：请先连接小车");
                addLog("控制被拒绝：未连接");
                return true;
            }
            if (event.getAction() == MotionEvent.ACTION_DOWN) {
                handler.removeCallbacks(delayedButtonStop);
                setVelocity(velocity[0], velocity[1], velocity[2]);
                addLog("按下控制：" + label);
                return true;
            }
            if (event.getAction() == MotionEvent.ACTION_UP || event.getAction() == MotionEvent.ACTION_CANCEL) {
                handler.removeCallbacks(delayedButtonStop);
                handler.postDelayed(delayedButtonStop, BUTTON_STOP_DELAY_MS);
                return true;
            }
            return false;
        });
        controlButtons.add(button);
        return button;
    }

    private void toggleConnection() {
        if (connected) {
            disconnect();
            return;
        }

        String host = hostInput.getText().toString().trim();
        String port = portInput.getText().toString().trim();
        if (host.isEmpty() || port.isEmpty()) {
            setStatus("连接失败：IP 和端口不能为空");
            setConnectionGuide("请先填写小车 IP。小车终端可用 hostname -I 查看，端口通常填 9090。");
            return;
        }
        int portNumber;
        try {
            portNumber = Integer.parseInt(port);
        } catch (NumberFormatException e) {
            setStatus("连接失败：端口必须是数字");
            setConnectionGuide("端口只能输入数字。真实小车 rosbridge 通常是 9090。");
            return;
        }
        if (!mockMode && host.startsWith("10.0.2.2")) {
            setConnectionGuide("当前是 CAR 模式，但 IP 是模拟器地址。真实小车请填 172.20.x.x 或小车终端显示的 IP。");
        } else if (mockMode && !host.equals("10.0.2.2")) {
            setConnectionGuide("当前是 MOCK 模式，建议 IP 使用 10.0.2.2；如果要连真实小车，请先切换到 CAR。");
        } else {
            setConnectionGuide(mockMode
                    ? "正在连接模拟服务：请确认电脑端 mock 服务已启动，端口为 9090。"
                    : "正在连接真实小车：请确认手机和小车同网，且小车终端 ss -lntp | grep 9090 有输出。");
        }

        String url = "ws://" + host + ":" + portNumber;
        setStatus("正在连接：" + (mockMode ? "mock://" : "ws://") + host + ":" + portNumber);
        final int requestGeneration = ++connectionGeneration;

        SmartConnection.Callback callback = new SmartConnection.Callback() {
            @Override
            public void onOpen() {
                runOnUiThread(() -> {
                    if (!isActiveConnection(requestGeneration)) {
                        return;
                    }
                    connected = true;
                    connectButton.setText("断开");
                    styleButton(connectButton, Color.rgb(255, 83, 112), Color.rgb(115, 22, 42), Color.WHITE);
                    setStatus("已连接：" + (mockMode ? "模拟服务 " : url));
                    setConnectionGuide("连接成功。现在请把速度调到 10%-25%，车轮悬空，先按“急停”，再短按“前进”。");
                    setControlsEnabled(true);
                    updateConnectionPanel();
                    addLog("连接成功");
                    advertiseCmdVel();
                    subscribeTelemetry();
                    startAiPolling();
                    resetVelocity();
                    publishCurrentVelocity();
                    handler.removeCallbacks(heartbeat);
                    handler.post(heartbeat);
                });
            }

            @Override
            public void onFailure(Exception exception) {
                runOnUiThread(() -> {
                    if (!isActiveConnection(requestGeneration)) {
                        return;
                    }
                    connected = false;
                    telemetrySubscribed = false;
                    connection = null;
                    resetVelocity();
                    handler.removeCallbacks(heartbeat);
                    connectButton.setText("连接");
                    styleButton(connectButton, Color.rgb(20, 210, 255), Color.rgb(0, 83, 122), Color.WHITE);
                    setControlsEnabled(false);
                    setStatus("连接失败：" + exception.getMessage());
                    setConnectionGuide(connectionFailureHint(exception.getMessage()));
                    updateConnectionPanel();
                    addLog("连接失败：" + exception.getMessage());
                });
            }

            @Override
            public void onClosed(String reason) {
                runOnUiThread(() -> {
                    if (!isActiveConnection(requestGeneration)) {
                        return;
                    }
                    connected = false;
                    telemetrySubscribed = false;
                    connection = null;
                    resetVelocity();
                    handler.removeCallbacks(heartbeat);
                    connectButton.setText("连接");
                    styleButton(connectButton, Color.rgb(20, 210, 255), Color.rgb(0, 83, 122), Color.WHITE);
                    setControlsEnabled(false);
                    setStatus("已断开：" + reason);
                    refreshConnectionGuide();
                    updateConnectionPanel();
                    addLog("连接断开");
                });
            }

            @Override
            public void onMessage(String text) {
                runOnUiThread(() -> {
                    if (!isActiveConnection(requestGeneration)) {
                        return;
                    }
                    handleRosbridgeMessage(text);
                });
            }
        };
        connection = mockMode
                ? new SimpleTcpConnection(host, portNumber, callback)
                : new SimpleWebSocket(host, portNumber, callback);
        connection.connect();
    }

    private void disconnect() {
        emergencyStop();
        connectionGeneration++;
        connected = false;
        telemetrySubscribed = false;
        handler.removeCallbacks(heartbeat);
        SmartConnection closingConnection = connection;
        connection = null;
        connectButton.setText("连接");
        styleButton(connectButton, Color.rgb(20, 210, 255), Color.rgb(0, 83, 122), Color.WHITE);
        setControlsEnabled(false);
        stopAiPolling();
        setStatus("已断开");
        refreshConnectionGuide();
        updateConnectionPanel();
        addLog("手动断开");
        if (closingConnection != null) {
            handler.postDelayed(closingConnection::close, 160L);
        }
    }

    private boolean isActiveConnection(int requestGeneration) {
        return !shuttingDown && requestGeneration == connectionGeneration;
    }

    private void advertiseCmdVel() {
        send("{\"op\":\"advertise\",\"topic\":\"" + CMD_TOPIC + "\",\"type\":\"" + CMD_TYPE + "\"}");
    }

    private void subscribeTelemetry() {
        if (!connected || connection == null) {
            setStatus("未连接：请先连接小车，再订阅遥测");
            addLog("遥测订阅被拒绝：未连接");
            return;
        }
        if (telemetrySubscribed) {
            telemetrySummary = "遥测：已订阅，无需重复订阅。等待 /scan、/imu、/voltage 等数据。";
            refreshDiagnosticPanel();
            addLog("遥测已订阅，跳过重复请求");
            return;
        }
        subscribeTopic("/scan", "sensor_msgs/LaserScan", 120);
        subscribeTopic("/imu/data_raw", "sensor_msgs/Imu", 200);
        subscribeTopic("/imu/mag", "sensor_msgs/MagneticField", 200);
        subscribeTopic("/voltage", "std_msgs/Float32", 200);
        subscribeTopic("/vel_raw", "geometry_msgs/Twist", 200);
        subscribeTopic("/joint_states", "sensor_msgs/JointState", 200);
        telemetrySubscribed = true;
        telemetrySummary = "遥测：已订阅 /scan、/imu/data_raw、/imu/mag、/voltage、/vel_raw、/joint_states，等待小车发布数据。";
        refreshDiagnosticPanel();
        addLog("已订阅遥测 topic");
    }

    private void subscribeTopic(String topic, String type, int throttleRate) {
        send("{\"op\":\"subscribe\",\"topic\":\"" + topic + "\",\"type\":\"" + type + "\",\"throttle_rate\":" + throttleRate + ",\"queue_length\":1}");
    }

    private void setVelocity(double linearX, double linearY, double angularZ) {
        double scale = Math.max(0.0, speedSeek.getProgress() / 100.0);
        currentLinearX = linearX * scale * MAX_LINEAR_SPEED;
        currentLinearY = linearY * scale * MAX_STRAFE_SPEED;
        currentAngularZ = angularZ * scale * MAX_ANGULAR_SPEED;
        updateCommandText();
        publishCurrentVelocity();
    }

    private void emergencyStop() {
        resetVelocity();
        publishCurrentVelocity();
    }

    private void resetVelocity() {
        currentLinearX = 0.0;
        currentLinearY = 0.0;
        currentAngularZ = 0.0;
        updateCommandText();
    }

    private void publishCurrentVelocity() {
        send(buildVelocityMessage());
    }

    private String buildVelocityMessage() {
        return String.format(
                Locale.US,
                "{\"op\":\"publish\",\"topic\":\"%s\",\"msg\":{\"linear\":{\"x\":%.3f,\"y\":%.3f,\"z\":0.0},\"angular\":{\"x\":0.0,\"y\":0.0,\"z\":%.3f}}}",
                CMD_TOPIC,
                currentLinearX,
                currentLinearY,
                currentAngularZ
        );
    }

    private void sendStopBeforeDestroy() {
        if (connected && connection != null) {
            currentLinearX = 0.0;
            currentLinearY = 0.0;
            currentAngularZ = 0.0;
            connection.send(buildVelocityMessage());
        }
    }

    private void send(String text) {
        if (!shuttingDown && connected && connection != null) {
            connection.send(text);
            sentCount++;
            if (sentCount % HEARTBEAT_UI_UPDATE_EVERY == 0) {
                updateConnectionPanel();
            }
        }
    }

    private String compactMessage(String text) {
        if (text == null) {
            return "";
        }
        String compact = text.replace('\n', ' ').replace('\r', ' ').trim();
        if (compact.length() > 120) {
            return compact.substring(0, 120) + "...";
        }
        return compact;
    }

    private void openVideoStream() {
        String host = hostInput == null ? "" : hostInput.getText().toString().trim();
        if (host.isEmpty()) {
            setStatus("视频流失败：请先填写小车 IP");
            if (videoStatusText != null) {
                videoStatusText.setText("视频状态：缺少小车 IP。");
            }
            return;
        }
        String url = "http://" + host + ":6501/video_feed";
        if (videoWebView != null) {
            videoWebView.loadUrl(url);
        }
        if (videoStatusText != null) {
            videoStatusText.setText("视频状态：正在打开 " + url);
        }
        addLog("打开视频流：" + url);
    }

    private void refreshDiagnosticPanel() {
        if (serviceStatusText != null) {
            serviceStatusText.setText(buildServiceStatusText());
        }
        if (telemetryText != null) {
            telemetryText.setText(telemetrySummary);
        }
    }

    private String buildServiceStatusText() {
        String host = hostInput == null ? "未填写" : hostInput.getText().toString().trim();
        String port = portInput == null ? "9090" : portInput.getText().toString().trim();
        return "服务状态：\n"
                + "ROSBridge：" + (connected ? "ONLINE  ws://" + host + ":" + port : "OFFLINE，需小车端监听 9090") + "\n"
                + "视频流：请在小车端确认 6500/video_feed 可访问\n"
                + "运动话题：/cmd_vel  geometry_msgs/Twist\n"
                + "参考检查：小车终端运行 ss -lntp | grep -E '9090|6500'";
    }

    private void handleRosbridgeMessage(String text) {
        String op = extractJsonString(text, "op");
        String level = extractJsonString(text, "level");
        if ("status".equals(op) || "error".equalsIgnoreCase(level)) {
            addLog("rosbridge: " + compactMessage(text));
        }
        if (!"publish".equals(op)) {
            return;
        }
        String topic = extractJsonString(text, "topic");
        if (topic.isEmpty()) {
            return;
        }
        if ("/scan".equals(topic)) {
            telemetrySummary = "遥测：收到 /scan 雷达数据，说明 rosbridge 能收到传感器消息。";
        } else if ("/imu/data_raw".equals(topic) || "/imu/mag".equals(topic)) {
            telemetrySummary = "遥测：收到 " + topic + "，IMU 数据在线。";
        } else if ("/voltage".equals(topic)) {
            telemetrySummary = "遥测：收到 /voltage 电压数据 " + compactMessage(text);
        } else if ("/vel_raw".equals(topic)) {
            telemetrySummary = "遥测：收到 /vel_raw 速度反馈 " + compactMessage(text);
        } else if ("/joint_states".equals(topic)) {
            telemetrySummary = "遥测：收到 /joint_states 轮速/关节状态。";
        } else {
            telemetrySummary = "遥测：收到 " + topic;
        }
        refreshTelemetryPanelThrottled();
    }

    private void refreshTelemetryPanelThrottled() {
        long now = System.currentTimeMillis();
        if (now - lastTelemetryUiUpdateMs < 800L) {
            return;
        }
        lastTelemetryUiUpdateMs = now;
        refreshDiagnosticPanel();
    }

    private String extractJsonString(String text, String key) {
        Matcher matcher = Pattern
                .compile("\"" + Pattern.quote(key) + "\"\\s*:\\s*\"([^\"]*)\"")
                .matcher(text);
        return matcher.find() ? matcher.group(1) : "";
    }

    private void toggleMockMode() {
        if (connected) {
            setStatus("请先断开连接，再切换模式");
            return;
        }
        mockMode = !mockMode;
        modeButton.setText(mockMode ? "模拟测试：开" : "真实小车：WebSocket");
        setStatus(mockMode
                ? "模拟测试模式：IP 使用 10.0.2.2，端口 9090"
                : "真实小车模式：输入小车 IP，端口通常为 9090");
        refreshConnectionGuide();
        updateConnectionPanel();
        addLog(mockMode ? "切换到模拟测试模式" : "切换到真实小车模式");
    }

    private void applyCarConnectionPreset() {
        if (connected) {
            setConnectionGuide("请先断开连接，再修改连接地址。");
            return;
        }
        mockMode = false;
        hostInput.setText("172.20.10.14");
        portInput.setText("9090");
        modeButton.setText("真实小车：WebSocket");
        setStatus("已切换到真实小车连接配置");
        refreshConnectionGuide();
        updateConnectionPanel();
        addLog("已填入真实小车连接配置");
    }

    private void applyMockConnectionPreset() {
        if (connected) {
            setConnectionGuide("请先断开连接，再修改连接地址。");
            return;
        }
        mockMode = true;
        hostInput.setText("10.0.2.2");
        portInput.setText("9090");
        modeButton.setText("模拟测试：开");
        setStatus("已切换到模拟测试连接配置");
        refreshConnectionGuide();
        updateConnectionPanel();
        addLog("已填入模拟器连接配置");
    }

    private void refreshConnectionGuide() {
        if (connected) {
            setConnectionGuide("已连接。操作顺序：低速 -> 急停 -> 短按前进/后退 -> 观察小车和 /cmd_vel。");
            return;
        }
        setConnectionGuide(mockMode
                ? "模拟测试：电脑运行 mock 服务，App 填 10.0.2.2:9090，然后点击连接。"
                : "真实小车：手机和小车同一网络；小车终端确认 9090 已监听；App 填小车 IP:9090 后连接。");
    }

    private void setConnectionGuide(String text) {
        if (connectionGuideText != null) {
            connectionGuideText.setText(text);
        }
    }

    private String connectionFailureHint(String message) {
        String detail = message == null ? "" : message;
        if (detail.contains("ECONNREFUSED") || detail.contains("refused")) {
            return "连接被拒绝：IP 能找到，但端口没有服务。请在小车终端启动 rosbridge，并确认 ss -lntp | grep 9090 有输出。";
        }
        if (detail.contains("timed out") || detail.contains("timeout")) {
            return "连接超时：通常是手机和小车不在同一网络，或 IP 填错。请重新查看小车 IP，并确认手机连接同一 Wi-Fi/热点。";
        }
        if (detail.contains("No route") || detail.contains("host")) {
            return "找不到小车：请检查 IP 是否是小车当前 IP，不要把模拟器地址 10.0.2.2 用在真实小车上。";
        }
        if (detail.contains("握手") || detail.contains("handshake")) {
            return "WebSocket 握手失败：端口可能不是 rosbridge 服务。真实小车需要 rosbridge_server 监听 9090。";
        }
        return "连接失败：请确认网络同一、IP 正确、端口 9090 已监听；仍失败就查看“日志 / 报警”页的错误信息。";
    }

    private void setStatus(String status) {
        statusText.setText(status);
    }

    private void addLog(String message) {
        lastLogMessage = "[" + String.format(Locale.US, "%03d", sentCount) + "] " + message;
        if (logText == null) {
            return;
        }
        logText.setText(lastLogMessage);
    }

    private void updateHeartbeatText() {
        if (heartbeatText != null) {
            heartbeatText.setText("心跳保护：200ms 周期  |  已发送 " + heartbeatCount + " 次");
        }
    }

    private void pollAiAlarms() {
        if (host == null || host.isEmpty()) return;
        new Thread(() -> {
            try {
                java.net.URL url = new java.net.URL("http://" + host + ":6501/api/alarms");
                java.net.HttpURLConnection conn = (java.net.HttpURLConnection) url.openConnection();
                conn.setConnectTimeout(3000);
                conn.setReadTimeout(3000);
                java.io.InputStream is = conn.getInputStream();
                java.util.Scanner s = new java.util.Scanner(is).useDelimiter("\\A");
                String body = s.hasNext() ? s.next() : "{}";
                s.close();
                conn.disconnect();
                // simple JSON parse: extract counts and latest alarm
                int personCount = extractInt(body, "person_detected");
                int abnormalCount = extractInt(body, "abnormal_behavior");
                int crackCount = extractInt(body, "cracked_tile");
                String latestDanger = extractString(body, "danger_type");
                String latestConf = extractString(body, "confidence");
                runOnUiThread(() -> {
                    if (detectionPreview != null) {
                        detectionPreview.setDetecting(personCount > 0 || abnormalCount > 0 || crackCount > 0);
                        detectionPreview.setAlarmInfo(personCount, abnormalCount, crackCount);
                    }
                    if (alarmText != null) {
                        StringBuilder sb = new StringBuilder("实时告警：\n");
                        sb.append("人员: ").append(personCount).append("  异常: ").append(abnormalCount).append("  裂缝: ").append(crackCount);
                        if (personCount + abnormalCount + crackCount > 0) {
                            sb.append("\n最新: ").append(latestDanger).append(" conf=").append(latestConf);
                            lastAlarmMessage = "告警: " + latestDanger + " conf=" + latestConf;
                        }
                        alarmText.setText(sb.toString());
                    }
                });
            } catch (Exception e) {
                // silent - ai_web_bridge may not be running
            }
        }).start();
    }

    private int extractInt(String json, String key) {
        int idx = json.indexOf("\"" + key + "\"");
        if (idx < 0) return 0;
        int colon = json.indexOf(":", idx);
        if (colon < 0) return 0;
        try { return Integer.parseInt(json.substring(colon + 1).replaceAll("[^0-9]", "")); }
        catch (Exception e) { return 0; }
    }

    private String extractString(String json, String key) {
        int idx = json.indexOf("\"" + key + "\"");
        if (idx < 0) return "-";
        int colon = json.indexOf("\"", json.indexOf(":", idx) + 1);
        int end = json.indexOf("\"", colon + 1);
        if (colon < 0 || end < 0) return "-";
        return json.substring(colon + 1, end);
    }

    private void clearAlarms() {
        if (detectionPreview != null) {
            detectionPreview.setDetecting(false);
        }
        lastAlarmMessage = "报警列表：暂无报警";
        if (alarmText != null) {
            alarmText.setText(lastAlarmMessage);
        }
        addLog("报警列表已清空");
    }

    private void startAiPolling() {
        stopAiPolling();
        aiPollRunnable = new Runnable() {
            public void run() {
                pollAiAlarms();
                aiPollHandler.postDelayed(this, 3000);
            }
        };
        aiPollHandler.post(aiPollRunnable);
    }

    private void stopAiPolling() {
        if (aiPollRunnable != null) {
            aiPollHandler.removeCallbacks(aiPollRunnable);
            aiPollRunnable = null;
        }
    }

    private void updateConnectionPanel() {
        if (linkText != null) {
            linkText.setText("链路\n" + (connected ? "ONLINE" : "OFFLINE"));
            linkText.setTextColor(connected ? Color.rgb(78, 255, 179) : Color.rgb(255, 116, 140));
        }
        if (modeText != null) {
            modeText.setText("模式\n" + (mockMode ? "MOCK" : "CAR"));
        }
        if (packetText != null) {
            packetText.setText("发送\n" + sentCount);
        }
        updateHeartbeatText();
    }

    private void updateCommandText() {
        if (commandText == null) {
            return;
        }
        commandText.setText(String.format(
                Locale.US,
                "当前指令：x=%.2f, y=%.2f, z=%.2f",
                currentLinearX,
                currentLinearY,
                currentAngularZ
        ));
    }

    private void setControlsEnabled(boolean enabled) {
        for (Button button : controlButtons) {
            button.setEnabled(enabled);
            button.setAlpha(enabled ? 1.0f : 0.45f);
        }
    }

    private double[] command(double x, double y, double z) {
        return new double[]{x, y, z};
    }

    private LinearLayout row() {
        LinearLayout row = new LinearLayout(this);
        row.setOrientation(LinearLayout.HORIZONTAL);
        row.setGravity(Gravity.CENTER);
        row.setPadding(0, dp(6), 0, dp(6));
        return row;
    }

    private EditText input(String hint) {
        EditText input = new EditText(this);
        input.setSingleLine(true);
        input.setHint(hint);
        input.setText(hint);
        input.setTextSize(16);
        input.setTextColor(Color.rgb(235, 249, 255));
        input.setHintTextColor(Color.rgb(100, 128, 150));
        input.setPadding(dp(10), 0, dp(10), 0);
        input.setBackground(rounded(Color.rgb(11, 24, 43), Color.rgb(49, 118, 148), 1, 10));
        return input;
    }

    private Button button(String text) {
        Button button = new Button(this);
        button.setText(text);
        button.setAllCaps(false);
        button.setMinHeight(dp(44));
        return button;
    }

    private Button presetButton(String label, int progress) {
        Button button = button(label);
        button.setTextSize(14);
        styleButton(button, Color.rgb(13, 38, 62), Color.rgb(13, 38, 62), Color.rgb(122, 231, 255));
        button.setOnClickListener(v -> {
            speedSeek.setProgress(progress);
            addLog("速度档位：" + label + " " + progress + "%");
        });
        return button;
    }

    private Button actionButton(String label, View.OnClickListener listener) {
        Button button = button(label);
        button.setTextSize(14);
        styleButton(button, Color.rgb(21, 67, 98), Color.rgb(13, 42, 69), Color.rgb(232, 250, 255));
        button.setOnClickListener(listener);
        return button;
    }

    private LinearLayout panel() {
        LinearLayout panel = new LinearLayout(this);
        panel.setOrientation(LinearLayout.VERTICAL);
        panel.setPadding(dp(14), dp(14), dp(14), dp(14));
        panel.setBackground(rounded(Color.rgb(9, 20, 36), Color.rgb(25, 96, 125), 1, 16));
        return panel;
    }

    private TextView sectionTitle(String text) {
        TextView title = new TextView(this);
        title.setText(text);
        title.setTextSize(14);
        title.setTypeface(Typeface.DEFAULT_BOLD);
        title.setTextColor(Color.rgb(119, 231, 255));
        title.setPadding(0, 0, 0, dp(8));
        return title;
    }

    private TextView hintText(String text) {
        TextView hint = new TextView(this);
        hint.setText(text);
        hint.setTextColor(Color.rgb(171, 190, 208));
        hint.setTextSize(12);
        hint.setLineSpacing(dp(2), 1.0f);
        hint.setPadding(0, dp(4), 0, dp(8));
        return hint;
    }

    private TextView metric(String label, String value) {
        TextView metric = new TextView(this);
        metric.setText(label + "\n" + value);
        metric.setGravity(Gravity.CENTER);
        metric.setTextSize(13);
        metric.setTypeface(Typeface.DEFAULT_BOLD);
        metric.setTextColor(Color.rgb(218, 246, 255));
        metric.setPadding(dp(4), dp(6), dp(4), dp(6));
        metric.setBackground(rounded(Color.rgb(12, 30, 52), Color.rgb(34, 90, 120), 1, 12));
        return metric;
    }

    private void styleButton(Button button, int startColor, int endColor, int textColor) {
        button.setTextColor(textColor);
        button.setBackground(gradient(startColor, endColor, 12));
    }

    private GradientDrawable gradient(int startColor, int endColor, int radiusDp) {
        GradientDrawable drawable = new GradientDrawable(
                GradientDrawable.Orientation.LEFT_RIGHT,
                new int[]{startColor, endColor}
        );
        drawable.setCornerRadius(dp(radiusDp));
        drawable.setStroke(dp(1), Color.argb(130, 115, 235, 255));
        return drawable;
    }

    private GradientDrawable rounded(int color, int strokeColor, int strokeWidthDp, int radiusDp) {
        GradientDrawable drawable = new GradientDrawable();
        drawable.setColor(color);
        drawable.setCornerRadius(dp(radiusDp));
        drawable.setStroke(dp(strokeWidthDp), strokeColor);
        return drawable;
    }

    private LinearLayout.LayoutParams matchWrap() {
        return new LinearLayout.LayoutParams(
                LinearLayout.LayoutParams.MATCH_PARENT,
                LinearLayout.LayoutParams.WRAP_CONTENT
        );
    }

    private LinearLayout.LayoutParams matchWrapWithBottom(int bottomDp) {
        LinearLayout.LayoutParams params = matchWrap();
        params.setMargins(0, 0, 0, dp(bottomDp));
        return params;
    }

    private LinearLayout.LayoutParams weighted() {
        return new LinearLayout.LayoutParams(0, LinearLayout.LayoutParams.WRAP_CONTENT, 1f);
    }

    private LinearLayout.LayoutParams fixedDp(int widthDp) {
        return new LinearLayout.LayoutParams(dp(widthDp), LinearLayout.LayoutParams.WRAP_CONTENT);
    }

    private LinearLayout.LayoutParams fixedHeight(int heightPx) {
        return new LinearLayout.LayoutParams(
                LinearLayout.LayoutParams.MATCH_PARENT,
                heightPx
        );
    }

    private int dp(int value) {
        return Math.round(value * getResources().getDisplayMetrics().density);
    }

    private static final class DetectionPreview extends View {
        private final Paint paint = new Paint(Paint.ANTI_ALIAS_FLAG);
        private boolean detecting = false;
        private int personCount = 0;
        private int abnormalCount = 0;
        private int crackCount = 0;

        DetectionPreview(Context context) {
            super(context);
        }

        void setDetecting(boolean detecting) {
            this.detecting = detecting;
            invalidate();
        }

        void setAlarmInfo(int p, int a, int c) {
            this.personCount = p;
            this.abnormalCount = a;
            this.crackCount = c;
            this.detecting = (p + a + c) > 0;
            invalidate();
        }

        @Override
        protected void onDraw(Canvas canvas) {
            super.onDraw(canvas);
            int w = getWidth();
            int h = getHeight();
            paint.setStyle(Paint.Style.FILL);
            paint.setColor(Color.rgb(7, 18, 31));
            canvas.drawRoundRect(new RectF(0, 0, w, h), 22, 22, paint);

            paint.setColor(Color.rgb(12, 42, 64));
            for (int y = 18; y < h; y += 24) {
                canvas.drawLine(14, y, w - 14, y, paint);
            }
            for (int x = 18; x < w; x += 34) {
                canvas.drawLine(x, 14, x, h - 14, paint);
            }

            paint.setStyle(Paint.Style.STROKE);
            paint.setStrokeWidth(3);
            paint.setColor(Color.rgb(76, 231, 255));
            canvas.drawRoundRect(new RectF(12, 12, w - 12, h - 12), 18, 18, paint);

            paint.setStyle(Paint.Style.FILL);
            paint.setColor(Color.rgb(110, 135, 155));
            paint.setTextSize(26);
            canvas.drawText("CAMERA STREAM", 28, 44, paint);

            paint.setColor(Color.rgb(45, 80, 100));
            canvas.drawOval(new RectF(w * 0.60f, h * 0.28f, w * 0.82f, h * 0.62f), paint);
            canvas.drawRect(w * 0.12f, h * 0.66f, w * 0.88f, h * 0.74f, paint);

            if (detecting) {
                paint.setStyle(Paint.Style.STROKE);
                paint.setStrokeWidth(5);
                paint.setColor(Color.rgb(255, 80, 98));
                RectF box = new RectF(w * 0.56f, h * 0.22f, w * 0.86f, h * 0.68f);
                canvas.drawRoundRect(box, 10, 10, paint);

                paint.setStyle(Paint.Style.FILL);
                paint.setColor(Color.rgb(255, 80, 98));
                canvas.drawRoundRect(new RectF(box.left, box.top - 34, box.left + 190, box.top), 8, 8, paint);
                paint.setColor(Color.WHITE);
                paint.setTextSize(22);
                canvas.drawText("人员=" + personCount + " 异常=" + abnormalCount + " 裂缝=" + crackCount, box.left + 10, box.top - 10, paint);
            } else {
                paint.setColor(Color.rgb(95, 120, 140));
                paint.setTextSize(22);
                canvas.drawText("等待AI检测数据...", 28, h - 28, paint);
            }
        }
    }

    private static final class PatrolMapView extends View {
        private final Paint paint = new Paint(Paint.ANTI_ALIAS_FLAG);
        private int activeIndex = 0;

        PatrolMapView(Context context) {
            super(context);
        }

        void nextPoint() {
            activeIndex = (activeIndex + 1) % 4;
            invalidate();
        }

        void setActiveIndex(int index) {
            activeIndex = Math.max(0, index) % 4;
            invalidate();
        }

        @Override
        protected void onDraw(Canvas canvas) {
            super.onDraw(canvas);
            int w = getWidth();
            int h = getHeight();
            paint.setStyle(Paint.Style.FILL);
            paint.setColor(Color.rgb(7, 18, 31));
            canvas.drawRoundRect(new RectF(0, 0, w, h), 22, 22, paint);

            float[][] points = {
                    {w * 0.18f, h * 0.68f},
                    {w * 0.42f, h * 0.34f},
                    {w * 0.68f, h * 0.42f},
                    {w * 0.82f, h * 0.72f}
            };

            paint.setStyle(Paint.Style.STROKE);
            paint.setStrokeWidth(5);
            paint.setColor(Color.rgb(50, 171, 210));
            for (int i = 0; i < points.length - 1; i++) {
                canvas.drawLine(points[i][0], points[i][1], points[i + 1][0], points[i + 1][1], paint);
            }

            paint.setStyle(Paint.Style.FILL);
            for (int i = 0; i < points.length; i++) {
                paint.setColor(i == activeIndex ? Color.rgb(255, 204, 95) : Color.rgb(84, 235, 255));
                canvas.drawCircle(points[i][0], points[i][1], i == activeIndex ? 14 : 10, paint);
            }

            paint.setColor(Color.rgb(225, 247, 255));
            paint.setTextSize(22);
            canvas.drawText("Patrol Map  A-03", 24, 36, paint);
            paint.setColor(Color.rgb(128, 150, 170));
            paint.setTextSize(18);
            canvas.drawText("蓝线：巡检路线   黄点：当前/报警位置", 24, h - 22, paint);
        }
    }

    private final class JoystickView extends View {
        private final Paint paint = new Paint(Paint.ANTI_ALIAS_FLAG);
        private JoystickListener listener;
        private float knobX = 0;
        private float knobY = 0;

        JoystickView(Context context) {
            super(context);
        }

        void setListener(JoystickListener listener) {
            this.listener = listener;
        }

        @Override
        protected void onDraw(Canvas canvas) {
            super.onDraw(canvas);
            float cx = getWidth() / 2f;
            float cy = getHeight() / 2f;
            float radius = Math.min(getWidth(), getHeight()) * 0.36f;

            paint.setStyle(Paint.Style.FILL);
            paint.setColor(Color.rgb(8, 22, 38));
            canvas.drawCircle(cx, cy, radius, paint);
            paint.setStyle(Paint.Style.STROKE);
            paint.setStrokeWidth(4);
            paint.setColor(Color.rgb(76, 231, 255));
            canvas.drawCircle(cx, cy, radius, paint);
            canvas.drawLine(cx - radius, cy, cx + radius, cy, paint);
            canvas.drawLine(cx, cy - radius, cx, cy + radius, paint);

            paint.setStyle(Paint.Style.FILL);
            paint.setColor(Color.rgb(255, 204, 95));
            canvas.drawCircle(cx + knobX * radius, cy + knobY * radius, radius * 0.24f, paint);
        }

        @Override
        public boolean onTouchEvent(MotionEvent event) {
            float cx = getWidth() / 2f;
            float cy = getHeight() / 2f;
            float radius = Math.min(getWidth(), getHeight()) * 0.36f;
            int action = event.getAction();

            if (!connected) {
                knobX = 0;
                knobY = 0;
                if (action == MotionEvent.ACTION_DOWN) {
                    setStatus("未连接：请先连接小车，再使用摇杆");
                    addLog("摇杆控制被拒绝：未连接");
                }
                invalidate();
                return true;
            }

            if (action == MotionEvent.ACTION_UP || action == MotionEvent.ACTION_CANCEL) {
                knobX = 0;
                knobY = 0;
                emergencyStop();
                invalidate();
                return true;
            }

            float dx = (event.getX() - cx) / radius;
            float dy = (event.getY() - cy) / radius;
            float length = (float) Math.sqrt(dx * dx + dy * dy);
            if (length > 1f) {
                dx /= length;
                dy /= length;
            }
            knobX = dx;
            knobY = dy;
            if (listener != null) {
                listener.onMove(knobX, knobY);
            }
            invalidate();
            return true;
        }
    }

    private interface JoystickListener {
        void onMove(float x, float y);
    }

    private interface SmartConnection {
        void connect();

        void send(String text);

        void close();

        interface Callback {
            void onOpen();

            void onFailure(Exception exception);

            void onClosed(String reason);

            void onMessage(String text);
        }
    }

    private static final class SimpleTcpConnection implements SmartConnection {
        private final String host;
        private final int port;
        private final Callback callback;
        private final ExecutorService sendExecutor = Executors.newSingleThreadExecutor();
        private Socket socket;
        private OutputStream output;
        private volatile boolean closed = false;

        SimpleTcpConnection(String host, int port, Callback callback) {
            this.host = host;
            this.port = port;
            this.callback = callback;
        }

        @Override
        public void connect() {
            new Thread(() -> {
                try {
                    socket = new Socket();
                    socket.connect(new InetSocketAddress(host, port), CONNECT_TIMEOUT_MS);
                    socket.setTcpNoDelay(true);
                    output = socket.getOutputStream();
                    callback.onOpen();
                    while (!closed && socket.isConnected() && !socket.isClosed()) {
                        Thread.sleep(1000L);
                    }
                } catch (Exception exception) {
                    if (!closed) {
                        callback.onFailure(exception);
                    }
                } finally {
                    closeQuietly();
                }
            }, "smart-car-tcp-connect").start();
        }

        @Override
        public void send(String text) {
            sendExecutor.execute(() -> {
                if (closed || output == null) {
                    return;
                }
                try {
                    output.write((text + "\n").getBytes(StandardCharsets.UTF_8));
                    output.flush();
                } catch (IOException exception) {
                    if (!closed) {
                        callback.onFailure(exception);
                    }
                    close();
                }
            });
        }

        @Override
        public void close() {
            closed = true;
            sendExecutor.shutdownNow();
            closeQuietly();
        }

        private void closeQuietly() {
            try {
                if (socket != null) {
                    socket.close();
                }
            } catch (IOException ignored) {
            }
        }
    }

    private static final class SimpleWebSocket implements SmartConnection {

        private final String host;
        private final int port;
        private final Callback callback;
        private final SecureRandom random = new SecureRandom();
        private final ExecutorService sendExecutor = Executors.newSingleThreadExecutor();

        private Socket socket;
        private OutputStream output;
        private volatile boolean closed = false;

        SimpleWebSocket(String host, int port, Callback callback) {
            this.host = host;
            this.port = port;
            this.callback = callback;
        }

        @Override
        public void connect() {
            new Thread(() -> {
                try {
                    socket = new Socket();
                    socket.connect(new InetSocketAddress(host, port), CONNECT_TIMEOUT_MS);
                    socket.setTcpNoDelay(true);
                    socket.setSoTimeout(0);
                    output = socket.getOutputStream();
                    BufferedInputStream input = new BufferedInputStream(socket.getInputStream());

                    String key = createWebSocketKey();
                    String request = "GET / HTTP/1.1\r\n"
                            + "Host: " + host + ":" + port + "\r\n"
                            + "Upgrade: websocket\r\n"
                            + "Connection: Upgrade\r\n"
                            + "Sec-WebSocket-Key: " + key + "\r\n"
                            + "Sec-WebSocket-Version: 13\r\n"
                            + "\r\n";
                    output.write(request.getBytes(StandardCharsets.US_ASCII));
                    output.flush();

                    String response = readHeaders(input);
                    if (!response.startsWith("HTTP/1.1 101") && !response.startsWith("HTTP/1.0 101")) {
                        throw new IOException("握手失败：" + firstLine(response));
                    }

                    callback.onOpen();
                    readFrameLoop(input);
                } catch (Exception exception) {
                    if (!closed) {
                        callback.onFailure(exception);
                    }
                    closeQuietly();
                }
            }, "smart-car-ws-connect").start();
        }

        @Override
        public void send(String text) {
            sendExecutor.execute(() -> {
                if (closed || output == null) {
                    return;
                }
                try {
                    writeTextFrame(text);
                } catch (IOException exception) {
                    if (!closed) {
                        callback.onFailure(exception);
                    }
                    close();
                }
            });
        }

        @Override
        public void close() {
            closed = true;
            sendExecutor.shutdownNow();
            closeQuietly();
        }

        private String createWebSocketKey() {
            byte[] nonce = new byte[16];
            random.nextBytes(nonce);
            return Base64.encodeToString(nonce, Base64.NO_WRAP);
        }

        private String readHeaders(BufferedInputStream input) throws IOException {
            StringBuilder builder = new StringBuilder();
            int previous3 = -1;
            int previous2 = -1;
            int previous1 = -1;
            int current;
            while ((current = input.read()) != -1) {
                builder.append((char) current);
                if (previous3 == '\r' && previous2 == '\n' && previous1 == '\r' && current == '\n') {
                    break;
                }
                previous3 = previous2;
                previous2 = previous1;
                previous1 = current;
            }
            return builder.toString();
        }

        private String firstLine(String response) {
            int lineEnd = response.indexOf("\r\n");
            if (lineEnd < 0) {
                return response;
            }
            return response.substring(0, lineEnd);
        }

        private void readFrameLoop(BufferedInputStream input) throws IOException {
            while (!closed && socket != null && socket.isConnected() && !socket.isClosed()) {
                int first = input.read();
                if (first < 0) {
                    break;
                }
                int second = input.read();
                if (second < 0) {
                    break;
                }
                int opcode = first & 0x0F;
                long length = second & 0x7F;
                if (length == 126) {
                    length = ((long) readRequiredByte(input) << 8) | readRequiredByte(input);
                } else if (length == 127) {
                    length = 0;
                    for (int i = 0; i < 8; i++) {
                        length = (length << 8) | readRequiredByte(input);
                    }
                }
                boolean masked = (second & 0x80) != 0;
                byte[] mask = null;
                if (masked) {
                    mask = new byte[4];
                    readFully(input, mask);
                }
                if (length > 1024 * 1024) {
                    throw new IOException("WebSocket frame too large");
                }
                byte[] payload = new byte[(int) length];
                readFully(input, payload);
                if (masked && mask != null) {
                    for (int i = 0; i < payload.length; i++) {
                        payload[i] = (byte) (payload[i] ^ mask[i % 4]);
                    }
                }
                if (opcode == 0x8) {
                    break;
                }
                if (opcode == 0x9) {
                    writeFrame(0x8A, payload);
                    continue;
                }
                if (opcode == 0x1 && payload.length > 0) {
                    callback.onMessage(new String(payload, StandardCharsets.UTF_8));
                }
            }

            if (!closed) {
                callback.onClosed("连接已关闭");
                closeQuietly();
            }
        }

        private int readRequiredByte(BufferedInputStream input) throws IOException {
            int value = input.read();
            if (value < 0) {
                throw new IOException("WebSocket closed while reading");
            }
            return value;
        }

        private void readFully(BufferedInputStream input, byte[] target) throws IOException {
            int offset = 0;
            while (offset < target.length) {
                int count = input.read(target, offset, target.length - offset);
                if (count < 0) {
                    throw new IOException("WebSocket closed while reading");
                }
                offset += count;
            }
        }

        private void writeTextFrame(String text) throws IOException {
            writeFrame(0x81, text.getBytes(StandardCharsets.UTF_8));
        }

        private synchronized void writeFrame(int firstByte, byte[] payload) throws IOException {
            if (output == null) {
                return;
            }
            byte[] mask = new byte[4];
            random.nextBytes(mask);

            output.write(firstByte);
            if (payload.length <= 125) {
                output.write(0x80 | payload.length);
            } else if (payload.length <= 65535) {
                output.write(0x80 | 126);
                output.write((payload.length >> 8) & 0xFF);
                output.write(payload.length & 0xFF);
            } else {
                output.write(0x80 | 127);
                for (int i = 7; i >= 0; i--) {
                    output.write((payload.length >> (8 * i)) & 0xFF);
                }
            }

            output.write(mask);
            byte[] maskedPayload = Arrays.copyOf(payload, payload.length);
            for (int i = 0; i < maskedPayload.length; i++) {
                maskedPayload[i] = (byte) (maskedPayload[i] ^ mask[i % 4]);
            }
            output.write(maskedPayload);
            output.flush();
        }

        private void closeQuietly() {
            try {
                if (socket != null) {
                    socket.close();
                }
            } catch (IOException ignored) {
            }
        }
    }
}
