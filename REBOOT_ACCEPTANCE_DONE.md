# RK3588 重启验收记录

验收日期：2026-07-02

## 结论

RK3588 连续完成两次真实重启。后端、公网中继、Hik/YOLO、H.264 视频、FunASR、DeepSeek、MiMO TTS、USB 麦克风与 ES8388 扬声器均在重启后通过验收。

C 板 ROS 2 节点与 topic 可自动启动，但下位机 IMU/odom 持续数据未作为本轮阻塞项，保留为独立实机联调。

## 自启与后端

- `qhxd-backend.service`：`enabled` / `active`。
- `qhxd-boot.service`：`enabled` / `active`。
- 重启后约 15 秒 `/health` 恢复。
- `status_public_robot.sh` 确认本地 backend、公网 gateway、公网 Web 与 state proxy 正常。

## 语音链路

重启后已验证：

1. `audio_test/cmd_201.wav` 识别为“去201实验室”。
2. 解析为 `go_to_waypoint / wp_201`，返回 `need_confirm=true`，未直接执行移动。
3. DeepSeek 开放问答正常，API 请求别名为 `deepseek-chat`，实际响应模型为 `deepseek-v4-flash`。
4. MiMO TTS 成功生成 WAV，`aplay -D plughw:2,0` 播放正常。
5. 板载扬声器播放“去一号点”，USB 麦克风实际回录后 FunASR 成功识别，安全确认流程正常。
6. 公网 `/api/voice/browser_smart_command` 上传 WAV 返回 HTTP 200。
7. 公网 `/api/robot/voice/onboard_smart_command` 能转发 RK 录音；无语音时正确返回“FunASR 未识别到有效文本”。

### 本轮修正

- 屏蔽用户 PulseAudio 的 service/socket，避免重启后抢占 ALSA 设备。
- `boot_startup.sh` 在硬件编排前再次防御性停止 PulseAudio。
- DeepSeek 请求使用 `deepseek-chat`，超时调整为 45 秒，返回实际 model 字段。
- Cloud Gateway 的浏览器 WAV 输入与 ffmpeg 输出改为不同路径，解决同名文件转码失败。

## 视觉与公网视频

- Hik 相机在开机编排中被正确选中。
- YOLO camera service 自动运行。
- RK MPP H.264 publisher 已连接云端。
- MediaMTX `robot/front` 为 `ready=true`，H.264 1280x720 Baseline，未见入站帧错误。

## 导航/C 板边界

- `standard_robot_pp_ros2`、`ros2_imu_bridge.py` 和 `/cmd_vel`、`/serial/imu`、`/serial/robot_motion`、`/odom`、`/tf` 可自动启动。
- topic 存在不代表下位机已持续上发有效数据。
- 外部 C 板 watchdog 保留为诊断能力，默认 `CBOARD_WATCHDOG_ENABLED=false`，不影响其他服务启动。

## 测试结果

- Backend Phase1：27 项通过。
- Cloud Gateway：5 项通过，包含 WAV 上传路径回归测试。
- 公网 Web：HTTP 200。
- Cloud Gateway health：RK online。
