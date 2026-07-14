# Android Studio 同步失败处理说明

## 一、当前问题

Android Studio 已经成功打开了 `app` 工程，但 Gradle 同步失败，报错类似：

```text
Could not install Gradle distribution from
https://services.gradle.org/distributions/gradle-9.3.0-bin.zip

Reason: java.net.SocketTimeoutException: Connect timed out
```

这说明问题不是 App 代码，而是 Android Studio 无法从网络下载 Gradle。

## 二、推荐处理方式

### 方案一：直接重试

如果只是临时网络波动，可以先点击 Android Studio 顶部的：

```text
Try Again
```

如果仍然超时，继续使用方案二。

## 三、方案二：手动安装本地 Gradle

### 1. 下载 Gradle

建议下载和当前项目更匹配的 Gradle 版本：

```text
gradle-8.7-bin.zip
```

原因：本项目使用的 Android Gradle Plugin 是：

```text
com.android.application 8.5.2
```

使用 Gradle 8.7 更稳，不建议优先使用 Gradle 9.x。

### 2. 解压 Gradle

把下载好的压缩包解压到：

```text
D:\D\install2\gradle-8.7
```

解压后目录应该类似：

```text
D:\D\install2\gradle-8.7
  bin
    gradle.bat
  lib
  init.d
```

必须能看到：

```text
D:\D\install2\gradle-8.7\bin\gradle.bat
```

如果没有 `gradle.bat`，说明路径选错了，或者压缩包还没有正确解压。

## 四、在 Android Studio 中指定本地 Gradle

打开 Android Studio 设置：

```text
File > Settings
```

进入：

```text
Build, Execution, Deployment > Build Tools > Gradle
```

找到：

```text
Gradle distribution
```

或者：

```text
Use Gradle from
```

选择：

```text
Local installation
```

路径填写：

```text
D:\D\install2\gradle-8.7
```

注意：这里填的是 Gradle 根目录，不是 `bin`，也不是 `gradle.bat`。

## 五、重新同步工程

设置完成后，点击：

```text
File > Sync Project with Gradle Files
```

或者点击顶部的：

```text
Try Again
```

同步成功后，顶部的 `Gradle project sync failed` 提示会消失。

## 六、同步成功后的下一步

同步成功后继续做：

1. 点击右上角 `Add Configuration`。
2. 选择 `Android App`。
3. Module 选择 `mobile`。
4. 连接安卓手机。
5. 手机开启 USB 调试。
6. 点击绿色运行按钮。
7. 手机上出现 `智能小车遥控`。

## 七、如果仍然失败

如果指定本地 Gradle 后仍然报错，优先检查：

| 问题 | 处理 |
| --- | --- |
| 找不到 Gradle | 确认目录中存在 `bin\gradle.bat` |
| SDK 缺失 | 按 Android Studio 提示安装 SDK |
| 插件下载失败 | 检查 `google()` 和 `mavenCentral()` 是否可访问 |
| 手机不可识别 | 检查 USB 调试和数据线 |
| 运行按钮灰色 | 等 Gradle Sync 完成后再配置运行 |
