# QHXD 琼海芯动车载机器人中台

QHXD 是琼海芯动车载机器人的 RK3588 中台工程。当前已打通公网 Dashboard、云端中继、语音/LLM/TTS、Hik/USB 相机、RKNN YOLO26、实时视频与 ROS 2 导航通信入口。

安全原则：视觉和 LLM 不直接控制底盘；移动类指令必须二次确认；公网写接口需要 Token，mission 控制还受 `PUBLIC_CONTROL_ENABLED` 开关限制。

## 当前进度（2026-07-06）

- 公网前端、Cloud Gateway 与 RK3588 backend 稳定连通，公网 API/WS 地址保持不变。
- C 板通信正式使用 `standard_robot_pp_ros2`，可接收 IMU/底盘数据并下发 `/cmd_vel`。
- `/serial/imu_backend` 20 Hz 镜像与 C++ backend bridge 已修复；libcurl 对本机 backend 明确绕过系统 HTTP 代理，`/api/imu/latest` 实测返回 `source=rk3588_cboard_ros2`。
- 导航正式使用 MID360 + Point-LIO 提供 `odom -> base_link`，不再使用 C 板 odom 或上位机速度积分作为导航前端里程计。
- 2D 建图、地图保存、AMCL/Nav2 链路、全向 PID Pursuit 平移控制和上位机旋转指令已打通。
- Phase 10 F1 已加入独立 `qhxd-nav-mission.service`、Nav2 Action 任务状态回写、pause/resume/cancel、巡检路线和任务事件；点位真实坐标尚待现场填写，未配置时会安全拒绝 Goal。
- 剩余导航收尾项是 Nav2 目标点旋转验收、动态障碍实机避障与安全停车测试；它们不阻塞其他业务模块开发。

## 快捷启动

以下命令默认在 RK3588 执行：

```bash
cd /home/robomaster/QHXD
```

### 生产环境：开机自启

RK3588 已启用：

- `qhxd-backend.service`：完整 FastAPI 后端，异常退出自动重启。
- `qhxd-boot.service`：切换 `real` 模式，启动导航/C 板桥接，并按 Hik 优先、USB 备用选择相机。

`qhxd-boot` 中的 C 板通信默认使用 Point-LIO 导航配置：

```text
params_file=/home/robomaster/QHXD/standard_robot_pp_ros2/config/standard_robot_pp_ros2_pointlio.yaml
use_respawn=false
```

该配置保留串口和 IMU，但关闭 C 板 `/odom` 与 `odom -> base_link`，避免与
Point-LIO interfaces 重复发布 TF。禁用 launch respawn 可避免节点退出后被旧父
进程反复拉起并继续占用串口。

正常重启后无需手动运行 `start_all.sh`：

```bash
./scripts/status_public_robot.sh
systemctl is-enabled qhxd-backend qhxd-boot
systemctl is-active qhxd-backend qhxd-boot qhxd-nav-mission
```

常用管理命令：

```bash
sudo systemctl restart qhxd-backend
sudo systemctl restart qhxd-nav-mission
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

# 导航 Web 可视化桥（需要 ROS 2 /map 与 map -> base_link TF）
./scripts/start_navigation_web_bridge.sh
./scripts/stop_navigation_web_bridge.sh

# Nav2 业务任务执行器（只监听 loopback :9101，不会自行发送 Goal）
./scripts/start_nav2_mission_executor.sh
./scripts/stop_nav2_mission_executor.sh
```

`start_cboard_comm.sh` 默认启动 Point-LIO 专用通信配置。需要临时覆盖时，可在
`~/QHXD/.env` 设置：

```bash
CBOARD_PARAMS_FILE=/home/robomaster/QHXD/standard_robot_pp_ros2/config/standard_robot_pp_ros2_pointlio.yaml
CBOARD_USE_RESPAWN=false
```

检查实际启动参数：

```bash
ps -eo pid,ppid,cmd | grep standard_robot_pp_ros2_node | grep -v grep
grep -E 'params_file|use_respawn' logs/standard_robot_pp_ros2.log
```

停止通信后，当前 C 板固件要求重新插拔 USB 或重新上电后才能再次启动。lock 文件
可以保留；以 `fuser -v /dev/ttyCBoard` 是否存在实际占用为准。

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
同域 WS：wss://lingxunrobot.cn/ws/state、/ws/imu 与 /ws/navigation
外部 API：https://api.lingxunrobot.cn
外部 WS：wss://api.lingxunrobot.cn/ws/state、/ws/imu 与 /ws/navigation
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
- 天气：语音/文本天气查询通过 Open-Meteo 获取实时气温、体感温度、湿度、降雨概率和紫外线，并生成出行建议；成功结果在进程内短时缓存。
- 感知：Hik MVS 优先、USB/UVC 备用，RKNN YOLO26 独立推理并提交 `detection_status`，后端持久化最近视觉事件。
- 视频：相机帧与 YOLO 异步，MPP H.264 上传至 MediaMTX，前端 WebRTC 优先，后端提供视频健康状态。
- 导航：`standard_robot_pp_ros2` 负责 C 板数据与 `/cmd_vel`；`QHXD_NAV` 使用 MID360 + Point-LIO 提供前端里程计，使用 slam_toolbox/AMCL/Nav2 完成 2D 建图、定位、规划和控制。
- 导航可视化：`navigation_web_bridge` 只读接入 `/map`、`map -> base_link`、`/plan`、`/local_plan` 和 `/odometry`，不发布控制话题。
- 云端：Cloud Gateway 完成认证、限流、路由白名单、操作日志、API/WS 转发与视频会话。

## 目录说明

```text
backend/                  RK3588 FastAPI 后端
frontend/                 Vue 3 Dashboard
cloud_gateway/            云端公网中继
experiments/rknn_yolo/    RKNN YOLO26 与相机检测
standard_robot_pp_ros2/   当前正式 C 板 / ROS 2 通信包
navigation_web_bridge/    ROS 2 导航到 Web 的只读可视化桥
rtt_nav_bridge/           旧桥接，仅保留参考
scripts/                  启动、状态、清理、设备绑定
systemd/                  RK3588 systemd 服务模板
streaming/                MediaMTX、Nginx 与视频配置
docs/                     协议和阶段文档
audio_test/               语音验收样本
```

`.runtime/`、`logs/`、`backend/data/voice_records/`、`backend/data/tts/` 和 YOLO `outputs/` 已通过 `.gitignore` 排除。

## 语音、LLM 与 TTS

### 实时天气

天气查询不使用固定占位值，也不需要额外 API Key。默认通过 Open-Meteo 查询机器人配置地点，
联网失败时优先使用最近一次成功缓存，不会把 `.env` 数值冒充实时天气：

```env
WEATHER_LOCATION=海南海口
WEATHER_LATITUDE=20.0440
WEATHER_LONGITUDE=110.1999
WEATHER_TIMEZONE=Asia/Shanghai
WEATHER_TIMEOUT_SECONDS=6
WEATHER_CACHE_TTL_SECONDS=300
```

修改地点时必须同时修改地点名称、纬度和经度。`WEATHER_CACHE_TTL_SECONDS` 控制查询缓存，
默认 300 秒，既保证数据较新，也避免每次语音问答都访问公网。

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

常用查询类语义不会生成 mission：

```bash
curl -X POST http://127.0.0.1:8000/api/voice/smart_command \
  -H 'Content-Type: application/json' \
  -d '{"text":"当前导航怎么样","source":"curl","generate_tts":false}'

curl -X POST http://127.0.0.1:8000/api/voice/smart_command \
  -H 'Content-Type: application/json' \
  -d '{"text":"前方安全吗","source":"curl","generate_tts":false}'

curl -X POST http://127.0.0.1:8000/api/voice/smart_command \
  -H 'Content-Type: application/json' \
  -d '{"text":"天气怎么样，适合出门吗","source":"curl","generate_tts":false}'
```

- “当前导航怎么样”读取 `navigation_store` 和任务状态。
- “前方安全吗 / 前面有什么 / 你看到了什么”读取当前 `detection_status` 与持久化视觉事件。
- “天气怎么样”读取 Open-Meteo 实时天气和缓存，不输出固定占位值。
- 查询类失败也只返回文本说明，不会触发底盘任务。

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
TTS_EVENT_DEDUP_SECONDS=3600
TTS_NORMAL_COOLDOWN_SECONDS=1.5
```

`DEEPSEEK_MODEL=deepseek-chat` 是 API 请求别名；当前 API 响应的实际模型为 `deepseek-v4-flash`，页面展示名由 `DEEPSEEK_DISPLAY_MODEL` 控制。
任务开始、暂停、恢复、到达、完成、取消和失败等事件可自动播报；同一任务事件会按 `event_key` 去重，普通播报有短冷却，TTS 失败不改变任务状态。

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

视觉事件与视频健康接口：

```bash
curl 'http://127.0.0.1:8000/api/perception/events?limit=10'
curl 'http://127.0.0.1:8000/api/perception/video_health'
```

- `/api/perception/events` 返回最近视觉事件，刷新页面后仍可查询。
- 事件按 `event_type + class_name` 在短时间窗口内去重，不逐帧写入 SQLite。
- 第一版事件包括 `person_detected`、`obstacle_detected`、`camera_offline`、`camera_recovered`。
- `/api/perception/video_health` 返回最后帧年龄、YOLO 相机服务 PID、检测状态和最近视觉事件。
- 视频健康接口会对推流 URL 做脱敏，不暴露 `pass`、`token`、`secret` 等参数。

## ROS 2 导航与 C 板

### Phase 10 F1 Mission -> Nav2

公网与本地继续使用原有 `/api/mission/*`。Real 模式下命令不再转发给历史 NUC，
而是进入独立 `qhxd-nav-mission.service`，由它调用 Nav2 `NavigateToPose`：

```text
Web / 小程序 / 语音确认
-> FastAPI MissionGateway（模式、急停、故障、地图、定位与点位准入）
-> 127.0.0.1:9101 Nav2 Mission Executor
-> NavigateToPose
-> /api/internal/mission/update
-> task_status + task_events + /ws/state
```

Executor 空闲时不会发送 Goal；实测稳态约 `0~2%` 单核 CPU。查看状态：

```bash
systemctl status qhxd-nav-mission
curl http://127.0.0.1:9101/health
curl http://127.0.0.1:8000/api/tasks/events
```

点位配置位于 `backend/app/config/waypoints.json`。当前四个点位的 `pose` 故意保持
`null`，因为尚未取得现场真实地图坐标；不得使用 `(0,0,0)` 代替：

```json
{
  "waypoint_id": "wp_001",
  "map_id": "sentinel_map",
  "pose": {"x": 1.25, "y": -0.80, "yaw": 0.0},
  "enabled": true
}
```

填写 `wp_001/wp_002/wp_201/home` 后检查并重启 Executor：

```bash
source /opt/ros/humble/setup.bash
source /home/robomaster/QHXD/install/setup.bash
source /home/robomaster/livox_ws/install/setup.bash
python3 scripts/nav2_mission_executor.py --check-config
sudo systemctl restart qhxd-nav-mission
```

巡检路线配置在 `backend/app/config/patrol_routes.json`。`pause` 的语义是取消当前
Nav2 Goal 但保留任务上下文；`resume` 会重新通过准入门并发送原目标；`cancel`
会清除恢复资格。新任务不会静默抢占现有活动任务。

Mission API 在命令成功进入 ROS Action 发送队列后立即返回
`accepted=true` 和 `state=pending`；Nav2 后续的 accepted/rejected/feedback/result 通过
`task_status` 和 `task_events` 异步收敛，避免网页超时后实际 Goal 仍被执行。
准入门优先使用真实设备状态；当历史 NUC 状态字段为离线时，使用现有
`ROS2_IMU_HEARTBEAT_FILE` 判断 C 板链路，默认最大年龄为 3 秒，不新增轮询进程。

当前正式包为 `standard_robot_pp_ros2`：

- 打开 `/dev/ttyCBoard`（默认 115200）。
- BCP 协议接收下位机数据。
- 发布 `/serial/robot_motion`、`/serial/imu`、`/serial/imu_backend` 以及可选的 `/odom`/TF。
- 保留全速 `/serial/imu` 供 ROS 2 调试和其他模块使用，同时发布最多 20Hz 的 `/serial/imu_backend` 给 Dashboard 后端。
- 订阅 `/cmd_vel` 并下发给 C 板。

`standard_robot_pp_ros2` 仍保留 C 板 `0x11` odom 解析与安全检查，但当前正式导航
配置 `standard_robot_pp_ros2_pointlio.yaml` 已设置 `publish_odom: false` 和
`publish_odom_tf: false`。导航的唯一 `odom -> base_link` 来源是 Point-LIO
接口，避免两个 TF 发布者互相冲突。

```bash
cd /home/robomaster/QHXD
unset LD_LIBRARY_PATH
source /opt/ros/humble/setup.bash
source /home/robomaster/QHXD/install/setup.bash

ros2 topic list | sort
ros2 topic echo /serial/imu --once
ros2 topic hz /serial/imu_backend
ros2 topic echo /serial/robot_motion --once
curl http://127.0.0.1:8000/api/imu/latest
```

IMU 后端桥接默认使用 C++ `rclcpp + libcurl`，将 `/serial/imu_backend` 写入现有 `/api/internal/nuc/imu`，不改前后端接口。本机 `127.0.0.1/localhost/::1` 请求强制不经过 `http_proxy`。空闲或 20Hz 输入下实测约 2% CPU；旧 Python bridge 保留作为回退。

```bash
# 立即切换，不重启 C 板串口节点
cd /home/robomaster/QHXD
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

当前已实测 `/serial/imu_backend` 同时存在 publisher/subscriber，本地
`/api/imu/latest` 持续返回 `source=rk3588_cboard_ros2`。后端必须位于
`real` 模式；`mock` 模式会按设计忽略真实 IMU。

`CBOARD_WATCHDOG_ENABLED=false` 默认关闭。只有在下位机本应持续上发时才建议打开，避免无数据时循环重启串口。

详见 `standard_robot_pp_ros2/README.md`。

### QHXD_NAV 当前导航链路

导航已独立整理到 `~/livox_ws`（GitHub：`LRaina215/QHXD_NAV`），该仓库
README 是唯一建议直接执行的导航启动手册。当前正式链路为：

```text
MID360 CustomMsg + IMU
  -> Point-LIO
  -> loam_interface + sensor_scan_generation
  -> odom -> base_link + /odometry + /registered_scan + /scan
  -> slam_toolbox（建图）或 map_server + AMCL（定位）
  -> Nav2 Theta* + Omni PID Pursuit
  -> /cmd_vel
  -> standard_robot_pp_ros2 -> C 板
```

TF 所有权必须保持唯一：

```text
map -> odom                 slam_toolbox（建图）或 AMCL（导航）
odom -> base_link           Point-LIO 导航接口
base_link -> livox_frame    静态外参
```

一键启动六个导航前置窗格：

```bash
cd ~/livox_ws
bash ~/livox_ws/scripts/start_navigation_frontend.sh
```

查看 tmux 窗格与实际 ROS 2 节点：

```bash
cd ~/livox_ws
bash ~/livox_ws/scripts/start_navigation_frontend.sh --status
```

已完成 Point-LIO 方向/稳定性、2D 建图与地图保存、AMCL/Nav2 软件链路、
全向平移控制与 C 板旋转指令验收。导航运行、建图、定位、地图保存、
RViz、停止和排障命令均见 `~/livox_ws/README.md`。

已知限制：C 板通信节点停止后，当前固件仍需重插 USB 或重新上电后才能
再次启动。不要同时运行 `rtt_nav_bridge` 和 `standard_robot_pp_ros2`。

## 后端 API

常用读取：

```text
GET /health
GET /api/state/latest
GET /api/alerts
GET /api/commands/logs
GET /api/tasks/current
GET /api/tasks/events
GET /api/waypoints
GET /api/waypoints/{waypoint_id}
GET /api/imu/latest
GET /api/external/weather/latest
GET /api/perception/latest_frame
GET /api/perception/frame_stream
GET /api/perception/events
GET /api/perception/video_health
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
POST /api/mission/cancel
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

Phase 10 F2 查询验收：

```bash
curl -X POST http://127.0.0.1:8000/api/voice/smart_command \
  -H 'Content-Type: application/json' \
  -d '{"text":"前方安全吗","source":"manual-check","generate_tts":false}'

curl -X POST http://127.0.0.1:8000/api/voice/smart_command \
  -H 'Content-Type: application/json' \
  -d '{"text":"天气怎么样，适合出门吗","source":"manual-check","generate_tts":false}'

curl 'http://127.0.0.1:8000/api/perception/events?limit=5'
curl 'http://127.0.0.1:8000/api/perception/video_health'
```

预期：查询类响应 `mission_candidate=null`；前方状态会引用当前视觉对象或最近视觉事件；天气回复包含实时温湿度、降雨概率和出行建议；视频健康状态不暴露推流密钥。

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

### C 板与 IMU 链路

```bash
cd /home/robomaster/QHXD
unset LD_LIBRARY_PATH
source /opt/ros/humble/setup.bash
source /home/robomaster/QHXD/install/setup.bash

ros2 topic echo /serial/imu --once
timeout 5 ros2 topic hz /serial/imu_backend
ros2 topic echo /serial/robot_motion --once
curl http://127.0.0.1:8000/api/imu/latest
curl https://lingxunrobot.cn/api/imu/latest
```

当前已验收真实 IMU 从 C 板经 20 Hz C++ bridge 到 RK backend 和公网 API。
预期 `source=rk3588_cboard_ros2` 且 `updated_at` 持续刷新。如命令一直等待，检查
`logs/standard_robot_pp_ros2.log` 和 `logs/ros2_imu_bridge.log`。

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
