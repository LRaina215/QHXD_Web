# QHXD 琼海芯动车载机器人中台

QHXD 是琼海芯动车载机器人的 RK3588 中台工程。当前已打通公网 Dashboard、云端中继、语音/LLM/TTS、Hik/USB 相机、RKNN YOLO26、实时视频与 ROS 2 导航通信入口。

安全原则：视觉和 LLM 不直接控制底盘；移动类指令必须二次确认；公网写接口需要 Token，mission 控制还受 `PUBLIC_CONTROL_ENABLED` 开关限制。

## 快捷启动

以下命令默认在 RK3588 执行：

```bash
cd /home/robomaster/QHXD
```

### 生产环境：开机自启

RK3588 已启用：

- `qhxd-backend.service`：完整 FastAPI 后端，异常退出自动重启。
- `qhxd-boot.service`：切换 `real` 模式，启动导航/C 板桥接，并按 Hik 优先、USB 备用选择相机。

正常重启后无需手动运行 `start_all.sh`：

```bash
./scripts/status_public_robot.sh
systemctl is-enabled qhxd-backend qhxd-boot
systemctl is-active qhxd-backend qhxd-boot
```

常用管理命令：

```bash
sudo systemctl restart qhxd-backend
sudo systemctl restart qhxd-boot
sudo systemctl status qhxd-backend qhxd-boot
sudo journalctl -u qhxd-backend -f
sudo journalctl -u qhxd-boot -f
```

新 RK3588 首次部署：

```bash
./scripts/install_backend_service.sh
./scripts/configure_robot_audio.sh
sudo install -m 0644 systemd/qhxd-boot.service /etc/systemd/system/qhxd-boot.service
sudo systemctl daemon-reload
sudo systemctl enable --now qhxd-boot.service
```

`qhxd-boot` 遇到未接 C 板或相机时会记录警告后继续，不会阻止后端、语音和公网页面启动。

### 手动恢复

```bash
# 只确保 RK backend 可用
./scripts/start_public_robot.sh

# 按需附加 C 板通信
PUBLIC_ROBOT_START_CBOARD=true ./scripts/start_public_robot.sh

# 按需附加 Hik 或 USB YOLO
PUBLIC_ROBOT_START_YOLO=true PUBLIC_ROBOT_YOLO_MODE=hik ./scripts/start_public_robot.sh
PUBLIC_ROBOT_START_YOLO=true PUBLIC_ROBOT_YOLO_MODE=usb ./scripts/start_public_robot.sh
```

### 本地开发调试

```bash
./scripts/start_backend.sh
./scripts/start_frontend.sh
./scripts/start_yolo_camera.sh       # USB / UVC
./scripts/start_yolo_hik_camera.sh   # Hik MVS

./scripts/start_all.sh               # backend + Vite + USB YOLO
./scripts/start_hik_web.sh           # backend + Vite + Hik YOLO
./scripts/status_all.sh
./scripts/stop_all.sh
```

- 公网前端在云服务器，不需要 RK 运行 `start_frontend.sh`。
- `start_backend.sh` 和 `status_all.sh` 是 PID 文件调试模式；生产状态以 systemd 和 `status_public_robot.sh` 为准。
- `stop_all.sh` 不会停止 `qhxd-backend` / `qhxd-boot`。

### 相机与导航快捷入口

```bash
# USB 相机稳定设备名 /dev/qhxd-usb-camera
./scripts/setup_usb_camera_alias.sh

# 单独启动相机检测
./scripts/start_yolo_camera.sh
./scripts/start_yolo_hik_camera.sh

# 当前正式 C 板通信包
./scripts/start_cboard_comm.sh
./scripts/stop_cboard_comm.sh
```

不要同时启动旧 `rtt_nav_bridge` 和 `standard_robot_pp_ros2`，否则可能抢占同一串口。

## 部署架构

公网前端与完整业务后端分离部署：

```text
浏览器
  |-- https://lingxunrobot.cn/       -> 云 Nginx -> 静态前端
  |-- https://lingxunrobot.cn/api/*  -> 云 Cloud Gateway :9000
  `-- wss://lingxunrobot.cn/ws/*     -> 云 Cloud Gateway :9000
                                              |
                                              | Tailscale
                                              v
                                     RK3588 backend :8000
                                              |
                 FunASR / DeepSeek / TTS / YOLO / 相机 / ROS 2 / C 板
```

```text
Hik/USB 相机 -> RK3588 MPP H.264 -> RTMP/Tailscale -> 云 MediaMTX
-> WebRTC/WHEP（首选）-> HLS（回退）-> MJPEG latest frame（最终兜底）
```

| 位置 | 运行内容 |
| --- | --- |
| 云服务器 | Nginx、静态前端、Cloud Gateway、MediaMTX |
| RK3588 | 完整 FastAPI 后端、FunASR、DeepSeek、TTS、YOLO、相机、ROS 2 与硬件接入 |
| RK 本地 Vite | 只用于前端开发，不是公网生产依赖 |

当前 Hik `MV-CS020-10UC` 是通过 MVS SDK 输出原始帧的 USB 工业相机，由 RK3588 MPP 编码 H.264，不是可直接输出 RTSP 的网络相机。

## 访问入口

### 公网

```text
Web：https://lingxunrobot.cn
同域 API：https://lingxunrobot.cn/api
同域 WS：wss://lingxunrobot.cn/ws/state 与 /ws/imu
外部 API：https://api.lingxunrobot.cn
外部 WS：wss://api.lingxunrobot.cn/ws/state 与 /ws/imu
```

公网写操作的 Token 是云服务器 `/etc/lingxun-cloud-gateway.env` 中的 `PUBLIC_API_TOKEN`。不要把 Token 写入代码或提交到 Git。

### RK3588 本地

```text
Backend：http://127.0.0.1:8000 或 http://<RK-IP>:8000
健康检查：http://127.0.0.1:8000/health
Vite 调试：http://<RK-IP>:5173
MJPEG 兜底：http://127.0.0.1:8000/api/perception/frame_stream
```

## 当前实现能力

- Dashboard：Mock/Real 切换、状态卡片、导航可视化、任务链路、任务控制、视觉事件、告警、语音/LLM 交互。
- 语音：文本、浏览器麦克风、RK 车载麦克风三种入口统一进入智能助手。
- ASR：FunASR SenseVoiceSmall + FSMN VAD，模型在进程内缓存，首次识别后复用。
- LLM：DeepSeek 负责开放问答和复杂语义 fallback；本地规则、schema、白名单和确认流程负责安全。
- TTS：MiMO V2.5 在线合成，可通过 ES8388 板载扬声器自动播放。
- 感知：Hik MVS 优先、USB/UVC 备用，RKNN YOLO26 独立推理并提交 `detection_status`。
- 视频：相机帧与 YOLO 异步，MPP H.264 上传至 MediaMTX，前端 WebRTC 优先。
- 导航：`standard_robot_pp_ros2` 提供 `/cmd_vel`、`/serial/imu`、`/serial/robot_motion`、`/odom` 和 TF 链路。
- 云端：Cloud Gateway 完成认证、限流、路由白名单、操作日志、API/WS 转发与视频会话。

## 目录说明

```text
backend/                  RK3588 FastAPI 后端
frontend/                 Vue 3 Dashboard
cloud_gateway/            云端公网中继
experiments/rknn_yolo/    RKNN YOLO26 与相机检测
standard_robot_pp_ros2/   当前正式 C 板 / ROS 2 通信包
rtt_nav_bridge/           旧桥接，仅保留参考
scripts/                  启动、状态、清理、设备绑定
systemd/                  RK3588 systemd 服务模板
streaming/                MediaMTX、Nginx 与视频配置
docs/                     协议和阶段文档
audio_test/               语音验收样本
```

`.runtime/`、`logs/`、`backend/data/voice_records/`、`backend/data/tts/` 和 YOLO `outputs/` 已通过 `.gitignore` 排除。

## 语音、LLM 与 TTS

### 统一智能助手

机器人身份为“灵巡 Sentinel”，配置在：

```text
backend/app/config/robot_profile.json
```

Dashboard 的“发送文本命令”“网页麦克风”“车载麦克风”均进入 smart assistant，无需另外点击智能解析。

```bash
curl -X POST http://127.0.0.1:8000/api/voice/smart_command \
  -H 'Content-Type: application/json' \
  -d '{"text":"你使用的模型是什么？","source":"curl","requested_by":"operator"}'
```

开放问答会返回 DeepSeek 的 `reply_text`，但 `open_chat` 永远不生成 mission。移动类指令只生成候选任务：

```text
intent=go_to_waypoint
need_confirm=true
mission_candidate.command=go_to_waypoint
pending_command_id=...
```

使用 `/api/voice/confirm_command` 确认或取消。

### 支持命令与点位

配置：

```text
backend/app/config/voice_commands.json
backend/app/config/waypoints.json
```

已支持去目标点、暂停、继续、返回起点、开始巡检、查询机器人/任务/视觉/天气与开放问答。未知命令不触发 mission。

| ID | 名称与常用别名 |
| --- | --- |
| `wp_201` | 二零一实验室、201实验室、201 |
| `wp_001` | 一号点、1号点、一号 |
| `wp_002` | 二号点、2号点、202 |
| `home` | 起点、装载点、返回点、home、家 |

新增点位优先只修改 `waypoints.json`；不要让多个点位共享同一短别名。

### 语音入口

```bash
# 文件识别（legacy 底层调试）
curl -X POST http://127.0.0.1:8000/api/voice/audio_command \
  -F 'file=@audio_test/cmd_201.wav;type=audio/wav'

# 文件识别 + 智能助手
curl -X POST http://127.0.0.1:8000/api/voice/smart_audio_command \
  -F 'file=@audio_test/cmd_201.wav;type=audio/wav'

# RK 本机麦克风录音 + 智能助手
curl -X POST http://127.0.0.1:8000/api/voice/smart_record_command \
  -H 'Content-Type: application/json' \
  -d '{"duration":3,"source":"rk-mic","requested_by":"operator"}'
```

公网不直接暴露 `/api/voice/record_command`，因为它会录服务器本机麦克风。

```text
浏览器麦克风 -> /api/voice/browser_smart_command
-> 云 ffmpeg 转 16kHz mono WAV -> RK /api/voice/smart_audio_command

车载麦克风 -> /api/robot/voice/onboard_smart_command
-> RK /api/voice/smart_record_command
```

### FunASR / ALSA 配置

```env
ASR_BACKEND=funasr
FUNASR_MODEL_PATH=/home/robomaster/.cache/modelscope/hub/models/iic/SenseVoiceSmall
FUNASR_VAD_MODEL_PATH=/home/robomaster/.cache/modelscope/hub/models/iic/speech_fsmn_vad_zh-cn-16k-common-pytorch
FUNASR_DEVICE=cpu
FUNASR_LANGUAGE=zh
FUNASR_USE_ITN=true
FUNASR_DISABLE_UPDATE=true

AUDIO_DEVICE=plughw:CARD=Device,DEV=0
AUDIO_RECORD_SECONDS=3
AUDIO_CHANNELS=1
AUDIO_SAMPLE_RATE=16000
AUDIO_FORMAT=S16_LE
```

FunASR 模型在 backend 进程内惰加载和缓存：首次识别耗时更长，后续请求复用同一模型实例。

运行 `./scripts/configure_robot_audio.sh` 会屏蔽用户 PulseAudio 自启，避免抢占 USB 麦克风和 ES8388 扬声器。

### DeepSeek / TTS 配置

```env
LLM_BACKEND=deepseek
LLM_ENABLE=true
DEEPSEEK_API_KEY=...
DEEPSEEK_BASE_URL=https://api.deepseek.com
DEEPSEEK_MODEL=deepseek-chat
DEEPSEEK_DISPLAY_MODEL="DeepSeek V4 Flash"
DEEPSEEK_TIMEOUT_SECONDS=45
LLM_REQUIRE_CONFIRM_FOR_MOTION=true

TTS_BACKEND=online
MIMO_API_KEY=...
MIMO_BASE_URL=https://api.xiaomimimo.com/v1
MIMO_TTS_MODEL=mimo-v2.5-tts
MIMO_TTS_VOICE=茉莉
TTS_AUTO_PLAY_LOCAL=true
TTS_PLAYER_CMD="aplay -D plughw:2,0"
```

`DEEPSEEK_MODEL=deepseek-chat` 是 API 请求别名；当前 API 响应的实际模型为 `deepseek-v4-flash`，页面展示名由 `DEEPSEEK_DISPLAY_MODEL` 控制。

## YOLO、相机与实时视频

已验证模型：

```text
models/yolo26n_fp32.rknn
RGB / NHWC / float32 / 0.0~1.0 / 640x640
output shape=(1, 300, 6)
output layout=xyxy_score_class
```

配置文件：

```text
USB：experiments/rknn_yolo/camera_config.json
Hik：experiments/rknn_yolo/camera_config_hik.example.json
```

关键参数：

```json
{
  "fps": 5,
  "stream_enabled": true,
  "stream_fps": 10,
  "stream_width": 1280,
  "stream_height": 720,
  "stream_bitrate": 1200000,
  "stream_queue_size": 2,
  "max_det": 20,
  "output_layout": "xyxy_score_class"
}
```

- `fps`：YOLO 取最新帧推理和提交状态的频率。
- `stream_fps`：前端实时 H.264 视频的目标帧率。
- `hik_params.float.AcquisitionFrameRate`：Hik 硬件采集帧率，应不低于 `stream_fps`。
- `stream_queue_size`：拥塞时丢弃旧帧，避免延迟和内存增长。

RK 根目录 `.env`：

```env
QHXD_VIDEO_STREAM_ENABLED=true
QHXD_VIDEO_STREAM_URL='rtmp://<cloud-tailscale-ip>:1935/robot/front?user=<publisher>&pass=<secret>'
```

`PERCEPTION_MJPEG_INTERVAL_MS` 只控制最终 MJPEG 兜底的检查间隔，不决定 WebRTC/HLS 正常视频帧率。详细模型、labels 和调试参数见 `experiments/rknn_yolo/README.md`。

## ROS 2 导航与 C 板

当前正式包为 `standard_robot_pp_ros2`：

- 打开 `/dev/ttyCBoard`（默认 115200）。
- BCP 协议接收下位机数据。
- 发布 `/serial/robot_motion`、`/serial/imu`、`/odom` 和可选 TF。
- 保留全速 `/serial/imu` 给导航，同时发布最多 20Hz 的 `/serial/imu_backend` 给 Dashboard 后端。
- 订阅 `/cmd_vel` 并下发给 C 板。

`/odom` 的位姿不是上位机速度积分结果，而是直接使用 C 板 `0x11`
帧中的 `x/y/yaw`。上位机会严格检查帧长、校验、有限值、合理范围与单帧跳变，
异常帧不会发布到 ROS。

实车确认 C 板上行为 `+x` 向后、`+y` 向右、`+yaw` 顺时针。
`standard_robot_pp_ros2` 默认在发布前对 `x/y/yaw` 和 `vx/vy/wz` 全部取反，
统一为 ROS `+x` 向前、`+y` 向左、`+yaw` 逆时针。

```bash
source /opt/ros/humble/setup.bash
source /home/robomaster/QHXD/install/setup.bash
ros2 topic list | sort
ros2 topic echo /serial/imu --once
ros2 topic hz /serial/imu_backend
ros2 topic echo /serial/robot_motion --once
ros2 topic echo /odom --once
```

IMU 后端桥接默认使用 C++ `rclcpp + libcurl`，将 `/serial/imu_backend` 写入现有 `/api/internal/nuc/imu`，不改前后端接口。空闲或 20Hz 输入下实测约 2% CPU；旧 Python bridge 保留作为回退。

```bash
# 立即切换，不重启 C 板串口节点
./scripts/switch_imu_bridge.sh cpp
./scripts/switch_imu_bridge.sh python
./scripts/status_public_robot.sh
```

持久回退可在根目录 `.env` 设置：

```env
ROS2_IMU_BRIDGE_IMPL=python
ROS2_IMU_TOPIC=/serial/imu_backend
ROS2_IMU_BRIDGE_RATE_HZ=20
```

本次修改前的完整备份：

```text
/home/robomaster/QHXD_backups/imu_bridge_20260703_120420.tar.gz
```

注意：topic 存在只证明 publisher 已启动，不等于 C 板在持续上发。当前重启验收已确认节点和 topic 自启，但下位机 IMU/odom 持续数据仍作为独立实机待验项。

`CBOARD_WATCHDOG_ENABLED=false` 默认关闭。只有在下位机本应持续上发时才建议打开，避免无数据时循环重启串口。

详见 `standard_robot_pp_ros2/README.md`。

### MID360 轻量 2D 建图

导航继续使用 `livox_ros_driver2`、`pointcloud_to_laserscan`和 `slam_toolbox`
的原生节点，完整 TF 所有权为：

```text
map -> odom                 slam_toolbox（建图）/ AMCL（导航）
odom -> base_link           standard_robot_pp_ros2 + C 板里程计
base_link -> livox_frame    静态外参
```

当前保守配置直接保存在 `~/livox_ws/config/mid360_to_scan.yaml` 和
`~/livox_ws/config/slam_toolbox_mid360.yaml`：3° 扫描、4 m 量程、队列 1、
SLAM 分辨率 0.15 m、关闭回环。调试时使用六个前台终端，不使用后台一键启动脚本。

```bash
# 终端 1：保持 standard_robot_pp_ros2 运行，提供 /odom 和 odom -> base_link

# 终端 2：Livox 驱动
cd ~/livox_ws
source /opt/ros/humble/setup.bash
source install/setup.bash
ros2 launch livox_ros_driver2 msg_MID360_launch.py

# 终端 3：点云转 LaserScan
source /opt/ros/humble/setup.bash
source ~/livox_ws/install/setup.bash
ros2 run pointcloud_to_laserscan pointcloud_to_laserscan_node --ros-args \
  -r cloud_in:=/livox/lidar -r scan:=/scan \
  --params-file ~/livox_ws/config/mid360_to_scan.yaml

# 终端 4：雷达静态 TF
source /opt/ros/humble/setup.bash
source ~/livox_ws/install/setup.bash
ros2 run tf2_ros static_transform_publisher \
  --x 0.0 --y 0.0 --z 0.25 --roll 0.0 --pitch 0.0 --yaw 0.0 \
  --frame-id base_link --child-frame-id livox_frame

# 终端 5：同步建图
source /opt/ros/humble/setup.bash
source ~/livox_ws/install/setup.bash
ros2 launch slam_toolbox online_sync_launch.py \
  slam_params_file:=/home/robomaster/livox_ws/config/slam_toolbox_mid360.yaml

# 终端 6：RViz（已配好 /map、/scan、/odom、TF 和 SLAM markers）
source /opt/ros/humble/setup.bash
source ~/livox_ws/install/setup.bash
rviz2 -d ~/livox_ws/rviz/sentinel_nav_mapping.rviz
```

RViz 必须使用 `-d` 加载配置；`rviz2 ./rviz/sentinel_nav_mapping.rviz`
只会打开默认界面。Rockchip DRI 报错后如仍显示 OpenGL 版本，表示 RViz
已回退到可用渲染路径。

2026-07-03 实测：`/odom` 38.715 Hz，`/livox/lidar` 和 `/scan` 约 10 Hz，
`/map_metadata` 可用，`map -> odom -> base_link -> livox_frame` 连通。单实例导航节点合计约
130 MiB；`slam_toolbox` 约 4–5% 单核，未再出现 OOM。

开始运动建图前仍必须人工确认：前进时 odom x 增大、左移时 y 增大、左转时 yaw
增大，并在 RViz 中确认车前障碍物位于 `base_link +X`。默认雷达外参
`x=0, y=0, z=0.25, rpy=0`仍是待实测的临时值。

当前 C 板 USB CDC 的已知使用限制保持不变：停止上位机通信节点后，
再启动前需重插或重新上电 C 板。

## 后端 API

常用读取：

```text
GET /health
GET /api/state/latest
GET /api/alerts
GET /api/commands/logs
GET /api/tasks/current
GET /api/imu/latest
GET /api/external/weather/latest
GET /api/perception/latest_frame
GET /api/perception/frame_stream
WS  /ws/state
WS  /ws/imu
```

语音与智能助手：

```text
POST /api/voice/smart_command
POST /api/voice/smart_audio_command
POST /api/voice/smart_record_command
POST /api/voice/audio_command
POST /api/voice/record_command                 # 仅 RK 本地
POST /api/robot/voice/onboard_smart_command    # 公网车载麦克风
POST /api/voice/browser_smart_command          # 云网关入口
POST /api/voice/confirm_command
POST /api/voice/speak
GET  /api/voice/tts/latest
```

任务：

```text
POST /api/mission/go_to_waypoint
POST /api/mission/start_patrol
POST /api/mission/pause
POST /api/mission/resume
POST /api/mission/return_home
```

内部状态：

```text
POST /api/internal/perception/detection_status
POST /api/internal/nuc/state
POST /api/internal/nuc/imu
```

`/api/internal/nuc/*` 是为保持兼容而保留的历史接口名，前端已使用 Nav/Navi 表述。

## Cloud Gateway

云端关键路径：

```text
/opt/lingxun-cloud-gateway
/etc/lingxun-cloud-gateway.env
/var/www/lingxunrobot
/etc/lingxun-mediamtx.yml
```

```bash
sudo systemctl status nginx lingxun-cloud-gateway lingxun-mediamtx
sudo systemctl restart lingxun-cloud-gateway
sudo journalctl -u lingxun-cloud-gateway -f
curl http://127.0.0.1:9000/health
curl http://127.0.0.1:9997/v3/paths/list
```

网关环境主要参数：

```env
RK_BACKEND_BASE_URL=http://100.113.173.115:8000
PUBLIC_API_TOKEN=...
PUBLIC_CONTROL_ENABLED=false
PUBLIC_RATE_LIMIT_PER_MINUTE=60
PUBLIC_AUDIO_MAX_MB=20
PUBLIC_BROWSER_AUDIO_MAX_MB=5
PUBLIC_BROWSER_AUDIO_MAX_SECONDS=10
```

- 读接口可按白名单公开转发。
- 语音、模式切换和任务等写接口需 `Authorization: Bearer <PUBLIC_API_TOKEN>`。
- mission 控制另需 `PUBLIC_CONTROL_ENABLED=true`。
- `/api/voice/record_command` 永远不直接暴露到公网。

## 重启后验收

### 一键状态

```bash
cd /home/robomaster/QHXD
./scripts/status_public_robot.sh
```

预期：RK backend、公网 gateway、公网 Web 正常；有相机时 YOLO 与 H.264 publisher 运行。`PID debug backend: not running` 在 systemd backend 为 active 时是正常状态。

### 后端与公网

```bash
curl --noproxy '*' http://127.0.0.1:8000/health
curl https://api.lingxunrobot.cn/health
curl https://lingxunrobot.cn/api/state/latest
```

### 音频设备

```bash
systemctl --user is-enabled pulseaudio.socket pulseaudio.service
systemctl --user is-active pulseaudio.socket pulseaudio.service
arecord -l
aplay -l
arecord -D 'plughw:CARD=Device,DEV=0' -f S16_LE -r 16000 -c 1 -d 2 /tmp/qhxd-mic.wav
aplay -D plughw:2,0 /tmp/qhxd-mic.wav
```

PulseAudio 应为 `masked` / `inactive`，录音应生成非空 WAV。

### 语音与智能助手

```bash
curl -X POST http://127.0.0.1:8000/api/voice/smart_audio_command \
  -F 'file=@/home/robomaster/QHXD/audio_test/cmd_201.wav;type=audio/wav'

curl -X POST http://127.0.0.1:8000/api/voice/smart_command \
  -H 'Content-Type: application/json' \
  -d '{"text":"你使用的模型是什么？"}'
```

预期：音频识别为“去201实验室”并返回 `need_confirm=true`；模型查询返回 DeepSeek V4 Flash。

### 视频

RK：

```bash
grep -E 'camera|H.264|publisher' logs/yolo_camera.log | tail -30
./scripts/status_public_robot.sh
```

云：

```bash
curl http://127.0.0.1:9997/v3/paths/list
```

`robot/front` 应为 `ready=true`。腾讯云安全组需放行 `8189/TCP` 和 `8189/UDP`。

### C 板独立待验

```bash
ros2 topic echo /serial/imu --once
ros2 topic echo /serial/robot_motion --once
ros2 topic echo /odom --once
```

如节点已运行但命令一直等待，说明当前没有收到下位机持续有效帧，不应阻塞其他功能验收。

本次实际重启记录见 `REBOOT_ACCEPTANCE_DONE.md`。

## 构建与测试

```bash
# backend
cd /home/robomaster/QHXD/backend
python3 -m unittest -v tests/test_phase1.py

# frontend
cd /home/robomaster/QHXD/frontend
npm run build

# RKNN 单图
cd /home/robomaster/QHXD/experiments/rknn_yolo
python3 infer_image.py \
  --model models/yolo26n_fp32.rknn \
  --image samples/test.jpg \
  --labels models/labels.txt \
  --format detections \
  --output-layout xyxy_score_class \
  --max-det 20
```

Cloud Gateway：

```bash
cd /opt/lingxun-cloud-gateway
.venv/bin/python -m unittest -v test_media_auth.py
```

## 常见问题

### 重启后需要手动开后端吗？

不需要。先查 `systemctl is-active qhxd-backend qhxd-boot`。本地 Vite 不自启也不影响公网前端。

### 语音报“车载麦克风识别失败”

```bash
systemctl --user is-active pulseaudio.socket pulseaudio.service
fuser -v /dev/snd/* 2>/dev/null || true
arecord -D 'plughw:CARD=Device,DEV=0' -f S16_LE -r 16000 -c 1 -d 2 /tmp/test.wav
journalctl -u qhxd-backend -n 100 --no-pager
```

如 PulseAudio 为 active，重新运行 `./scripts/configure_robot_audio.sh`。

### 网页麦克风上传失败

检查浏览器录音权限、Token、云端 `ffmpeg` 和网关日志：

```bash
ffmpeg -version
sudo journalctl -u lingxun-cloud-gateway -n 100 --no-pager
tail -n 50 /var/log/lingxun-cloud-gateway/operations.jsonl
```

### 前端视频不刷新

先查 RK 的 YOLO/latest frame，再查云端 `robot/front`：

```bash
curl -i 'http://127.0.0.1:8000/api/perception/latest_frame?t=check'
tail -f logs/yolo_camera.log
curl http://127.0.0.1:9997/v3/paths/list
```

WebRTC 不可用时前端会回退 HLS/MJPEG；端口放行、Token 会话和 Hik USB3 线缆/供电均需检查。

### `/odom` 有 topic 但无数据

这表示 ROS 2 publisher 存在，不表示 C 板已上发有效运动帧。检查串口占用、`/serial/robot_motion` 和 `logs/standard_robot_pp_ros2.log`，并确保旧 `rtt_nav_bridge` 没有运行。

## 文档索引

当前模块文档：

```text
experiments/rknn_yolo/README.md
standard_robot_pp_ros2/README.md
cloud_gateway/README.md
REBOOT_ACCEPTANCE_DONE.md
IMU_BRIDGE_CPP_DONE.md
```

阶段交付记录：

```text
PHASE4_DONE.md
PHASE5_DONE.md
PHASE6_DONE.md
PHASE7_DONE.md
PHASE8A_DONE.md
PHASE8B_DONE.md
PHASE9A_DONE.md
HIK_CAMERA_SOURCE_STATUS.md
```

历史 `DO_PHASE*.md` / `DONE*.md` 保留为开发过程档案；新成员以本 README 和各模块 README 为准。
