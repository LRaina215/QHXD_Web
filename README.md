# QHXD 琼海芯动车载机器人中台

QHXD 是琼海芯动车载机器人的 RK3588 中台工程。当前已打通公网 Dashboard、云端中继、语音/LLM/TTS、Hik/USB 相机、RKNN YOLO26、实时视频与 ROS 2 导航通信入口。

安全原则：视觉和 LLM 不直接控制底盘；移动类指令必须二次确认；公网写接口需要 Token，mission 控制还受 `PUBLIC_CONTROL_ENABLED` 开关限制。

## 当前进度（2026-07-08）

- 公网前端在云服务器，Cloud Gateway 反代到 RK3588 backend；`https://lingxunrobot.cn`、`https://api.lingxunrobot.cn`、`/api/*` 与 `/ws/*` 当前可用。
- 云服务器只运行 Nginx、静态前端、Cloud Gateway 和 MediaMTX；完整 QHXD backend 仍在 RK3588 上，因为 ASR、TTS、YOLO、相机、ROS 2、C 板和导航都依赖本体环境。
- RK backend 正常入口是 `http://127.0.0.1:8000`。正常开机由 `qhxd-backend.service` 提供 backend，手动调试时也可能由 `scripts/start_backend.sh` 拉起 PID 模式；判断是否可用以 `./scripts/status_public_robot.sh` 和 `/health` 为准，不只看某一个 systemd unit 是否 active。
- C 板通信正式使用 `standard_robot_pp_ros2`。当前 Point-LIO 导航配置为 `standard_robot_pp_ros2_pointlio.yaml`，保留串口、`/cmd_vel` 下发和 `/serial/imu_backend` 20 Hz 后端镜像，但关闭 C 板 `/odom` 与 `odom -> base_link`，避免和 Point-LIO TF 冲突。
- IMU 后端桥已切到 C++ `imu_backend_bridge_node`，`/api/imu/latest` 已实测 `source=rk3588_cboard_ros2`，Cloud Gateway 也能转发公网 IMU API。
- 导航本体在 `/home/robomaster/livox_ws`（QHXD_NAV），不是 QHXD 主仓库的一部分。当前使用 MID360 + Point-LIO 提供 `odom -> base_link`，再接 slam_toolbox/AMCL/Nav2/Omni PID Pursuit。
- Phase 10 F1 已接入 `qhxd-nav-mission.service`：`/api/mission/* -> FastAPI MissionGateway -> 127.0.0.1:9101 Nav2 Mission Executor -> NavigateToPose -> 状态回写`。
- 网页端导航可视化由 QHXD 内的 `navigation_web_bridge` 只读桥接 `/map`、`map -> base_link`、`/plan`、`/local_plan` 和 `/odometry`。桥接已加入 `/map` watchdog：ROS 已有地图但后端地图缓存为空时，会自动重启一次桥接恢复网页地图。
- 点位 `wp_001`、`wp_002`、`wp_201`、`home` 当前已经在 `backend/app/config/waypoints.json` 配置真实 pose；仍建议现场复核 yaw、通道安全和地图版本一致性。
- Phase 10 F2 已把文本、网页麦克风和车载麦克风统一进 smart assistant；移动类任务仍需二次确认。天气、前方视觉/导航状态查询由结构化上下文和 LLM 综合回答，不直接控制底盘。
- Hik/USB 相机、RKNN YOLO26、视觉事件持久化、视频健康接口、H.264 推流和 WebRTC/HLS/MJPEG 回退已经接入。`/api/perception/video_health` 会识别 stale PID，旧 PID 不再被误判为 YOLO 正在运行。
- 当前导航、网页桥接和任务链路已达到阶段演示预期；后续仍建议继续做动态障碍、急停/通信中断和连续导航压力测试，这些属于实车安全加固项。

## 快捷启动

以下命令默认在 RK3588 执行：

```bash
cd /home/robomaster/QHXD
```

### 生产环境：开机自启

RK3588 已启用：

- `qhxd-backend.service`：完整 FastAPI 后端的正常开机入口，异常退出时由 systemd 管理。
- `qhxd-boot.service`：backend 就绪后切换 `real` 模式，启动 C 板通信、YOLO 相机、导航前置六窗格和导航 Web 桥接。
- `qhxd-nav-mission.service`：Nav2 Mission Executor，只监听本机 `127.0.0.1:9101`，等待 backend 转发任务。

`qhxd-boot` 中的 C 板通信默认使用 Point-LIO 导航配置：

```text
params_file=/home/robomaster/QHXD/standard_robot_pp_ros2/config/standard_robot_pp_ros2_pointlio.yaml
use_respawn=false
```

该配置保留串口和 IMU，但关闭 C 板 `/odom` 与 `odom -> base_link`，避免与
Point-LIO interfaces 重复发布 TF。禁用 launch respawn 可避免节点退出后被旧父
进程反复拉起并继续占用串口。

正常重启后无需手动运行 `start_all.sh`。优先用以下命令看整体状态：

```bash
./scripts/status_public_robot.sh
systemctl is-enabled qhxd-backend qhxd-boot
systemctl is-active qhxd-boot qhxd-nav-mission
curl http://127.0.0.1:8000/health
```

如果你刚手动重启过 backend，可能看到 `qhxd-backend.service` 为 `inactive`，
但 PID 调试模式的 backend 仍在运行；只要 `/health` 和 `status_public_robot.sh`
显示 backend OK，公网 Gateway 就仍能转发到 RK。

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
Hik/USB 相机服务的 PID 会校验命令行，旧 PID 不会再阻止重新启动 YOLO。

如果 WiFi 和 MID360 有线网口都在 `192.168.1.0/24`，必须保证雷达 IP 走
`eth1`，否则 Livox 驱动会启动但 `/livox/lidar` 没有数据，表现为 RViz
初始化位姿不收敛、`/scan` 和 costmap 不显示。`qhxd-boot` 和
`start_navigation_frontend_detached.sh` 会自动设置：

```bash
./scripts/ensure_livox_route.sh
```

可在 `~/QHXD/.env` 覆盖：

```env
WIFI_GATEWAY_IP=192.168.1.1
WIFI_INTERFACE=wlan0
LIVOX_LIDAR_IP=192.168.1.3
LIVOX_INTERFACE=eth1
LIVOX_HOST_IP=192.168.1.50
```

检查命令：

```bash
ip route get 192.168.1.3
ros2 topic hz /livox/lidar
ros2 topic hz /scan
```

如果你只手动运行 `ros2 launch rk3588_navigation bringup.launch.py`，但没有先启动
导航前置 1-6，AMCL 只能看到 map_server/Nav2，收不到雷达、Point-LIO TF 和 `/scan`，
`2D Pose Estimate` 会表现为无法定位。正确顺序是：

```bash
cd ~/QHXD
./scripts/start_navigation_frontend_detached.sh

cd ~/livox_ws
unset LD_LIBRARY_PATH
source /opt/ros/humble/setup.bash
source ~/livox_ws/install/setup.bash
ros2 launch rk3588_navigation bringup.launch.py
```

`start_navigation_frontend_detached.sh` 会分阶段等待健康信号：

```text
MID360 -> /livox/lidar
Point-LIO -> /aft_mapped_to_init
interfaces -> /sensor_scan
LaserScan -> /scan
```

如果任一阶段超时，后续阶段不会硬启动。此时先看对应 tmux 窗格和
`ip route get 192.168.1.3`，不要直接反复启动 `bringup.launch.py`。

导航开机行为由 `~/QHXD/.env` 控制：

```env
# 开机启动前置 1-6：C 板日志/MID360/Point-LIO/静态 TF/LIO interfaces/LaserScan
QHXD_BOOT_START_NAV_FRONTEND=true

# 开机启动导航 Web 只读桥，给公网 Dashboard 的 /ws/navigation 提供数据
QHXD_BOOT_START_NAV_WEB_BRIDGE=true

# 可选：Web 桥启动后短时监控 ROS /map。
# 若 /map 已存在但后端 /api/navigation/map/metadata 仍为空，会自动重启一次桥接。
QHXD_NAV_WEB_BRIDGE_MAP_WATCHDOG=true
QHXD_NAV_WEB_BRIDGE_MAP_WAIT_SECONDS=600

# 默认不替用户选择建图或导航，避免 slam_toolbox 与 AMCL 同时拥有 map -> odom
QHXD_BOOT_NAV_MODE=none

# 可选：mapping | localization | navigation | bringup | none
# mapping      = 前置 1-6 + slam_toolbox
# localization = 前置 1-6 + AMCL/map_server
# navigation   = 只启动 Nav2 规划控制，要求 localization 已经启动
# bringup      = AMCL/map_server + Nav2 合并启动
```

如果你希望机器人开机后直接进入导航待命，设置：

```env
QHXD_BOOT_NAV_MODE=bringup
```

如果要现场建图，设置：

```env
QHXD_BOOT_NAV_MODE=mapping
```

`mapping` 和 `localization/bringup` 不要同时运行；切换模式前先执行
`./scripts/stop_navigation_mode.sh`。

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
- RK 上看到 `frontend: stopped` 是正常的公网生产状态；只有本地 Vite 调试才需要启动前端。

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

# 导航前置 1-6：无附着启动，适合开机自启
./scripts/start_navigation_frontend_detached.sh
./scripts/start_navigation_frontend_detached.sh --status
./scripts/start_navigation_frontend_detached.sh --attach

# 选择建图/定位/导航模式。默认开机不自动选择，避免 TF 冲突
./scripts/start_navigation_mode.sh mapping
./scripts/start_navigation_mode.sh localization
./scripts/start_navigation_mode.sh navigation
./scripts/start_navigation_mode.sh bringup
./scripts/start_navigation_mode.sh --status
./scripts/stop_navigation_mode.sh

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
- 语音：文本、浏览器麦克风、RK 车载麦克风三种入口统一进入 smart assistant。
- ASR：FunASR SenseVoiceSmall + FSMN VAD，模型在进程内缓存，首次识别后复用。
- LLM：DeepSeek 负责开放问答、复杂语义 fallback 和前方视觉/导航状态综合回复；本地规则、schema、白名单和确认流程负责安全。
- TTS：MiMO V2.5 在线合成，可通过 ES8388 板载扬声器自动播放。
- 天气：语音/文本天气查询通过 Open-Meteo 获取实时气温、体感温度、湿度、降雨概率和紫外线，并生成出行建议；成功结果在进程内短时缓存。
- 感知：Hik MVS 优先、USB/UVC 备用，RKNN YOLO26 独立推理并提交 `detection_status`，后端持久化最近视觉事件并提供 `/api/perception/events`。
- 视频：相机帧与 YOLO 异步，MPP H.264 上传至 MediaMTX，前端 WebRTC 优先，HLS/MJPEG 回退，后端提供 `/api/perception/video_health`。
- 导航：`standard_robot_pp_ros2` 负责 C 板数据与 `/cmd_vel`；导航本体在 `/home/robomaster/livox_ws`，使用 MID360 + Point-LIO 提供前端里程计，使用 slam_toolbox/AMCL/Nav2 完成 2D 建图、定位、规划和控制。
- Mission：`/api/mission/*` 在 Real 模式下经 MissionGateway 转发到本机 `qhxd-nav-mission.service`，由 Nav2 `NavigateToPose` 执行并回写任务事件。
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

导航本体仓库不在 QHXD 目录内，位于 `/home/robomaster/livox_ws`；建图、定位、Nav2、
RViz 和底层 launch 细节以 `/home/robomaster/livox_ws/README.md` 为准。QHXD 只提供
开机编排和 Web 桥接脚本，不修改导航本体代码。

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
FRONT_STATUS_LLM_ENABLE=true
FRONT_STATUS_FRESH_SECONDS=15
FRONT_STATUS_RECENT_SECONDS=60

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
`FRONT_STATUS_LLM_ENABLE=true` 时，前方状态查询会把当前视觉、最近视觉事件、导航状态和任务状态整理为受控上下文，再交给 LLM 生成自然回复；正常情况下不会在语音回复里说 `rk3588`、`YOLO`、`detection_status` 或更新时间。只有视觉链路明显异常或数据过旧时，才提示“现在无法可靠查看前方画面”。
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
- YOLO 相机健康判断会校验 PID 对应命令是否真的是 `camera_detect_service.py`，旧 PID 不会再被误判为运行中。
- 视频健康接口会对推流 URL 做脱敏，不暴露 `pass`、`token`、`secret` 等参数。

## ROS 2 导航与 C 板

### Phase 10 F1 Mission -> Nav2

公网与本地继续使用原有 `/api/mission/*`。Real 模式下命令进入独立
`qhxd-nav-mission.service`，由它调用 Nav2 `NavigateToPose`：

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

点位配置位于 `backend/app/config/waypoints.json`。当前四个点位已经配置
`[x, y, yaw]` 地图坐标；如更换地图或重新建图，必须重新现场复核，不要沿用旧地图 pose：

```json
[
  {"waypoint_id": "wp_201", "pose": [-2.27, 4.02, 0]},
  {"waypoint_id": "wp_001", "pose": [0.237, 5.01, 0]},
  {"waypoint_id": "wp_002", "pose": [1.5, 0.398, 0]},
  {"waypoint_id": "home", "pose": [-1.05, 4.54, 0]}
]
```

修改点位后检查并重启 Executor：

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
准入门优先使用真实设备状态；兼容旧字段为空或离线时，使用现有
`ROS2_IMU_HEARTBEAT_FILE` 判断 C 板链路，默认最大年龄为 3 秒，不新增轮询进程。

当前正式包为 `standard_robot_pp_ros2`：

- 打开 `/dev/ttyCBoard`（默认 115200）。
- BCP 协议接收下位机数据。
- 发布 `/serial/robot_motion`、`/serial/imu`、`/serial/imu_backend`。Point-LIO 正式导航配置关闭 C 板 `/odom` 与 `odom -> base_link` TF，避免 TF 冲突。
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

IMU 后端桥接默认使用 C++ `rclcpp + libcurl`，将 `/serial/imu_backend` 写入现有兼容接口 `/api/internal/nuc/imu`，不改前后端接口。本机 `127.0.0.1/localhost/::1` 请求强制不经过 `http_proxy`。空闲或 20Hz 输入下实测约 2% CPU；旧 Python bridge 保留作为回退。

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

导航已独立整理到 `~/livox_ws`（GitHub：`LRaina215/QHXD_NAV`）。该仓库
README 是建图、定位、Nav2、RViz 和底层 launch 的权威手册；QHXD 主仓库只负责
开机编排、网页端导航桥接和业务任务转发。当前正式链路为：

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

QHXD 侧无附着启动六个导航前置窗格，适合开机自启：

```bash
cd ~/QHXD
./scripts/start_navigation_frontend_detached.sh
./scripts/start_navigation_frontend_detached.sh --status
./scripts/start_navigation_frontend_detached.sh --attach
```

手动在 `livox_ws` 中启动六窗格仍然可用，适合现场调试：

```bash
cd ~/livox_ws
bash ~/livox_ws/scripts/start_navigation_frontend.sh
```

查看 tmux 窗格与实际 ROS 2 节点：

```bash
cd ~/livox_ws
bash ~/livox_ws/scripts/start_navigation_frontend.sh --status
```

建图/定位/导航模式由用户选择，QHXD 不会默认同时启动互斥模式：

```bash
cd ~/QHXD
./scripts/start_navigation_mode.sh mapping       # slam_toolbox 建图
./scripts/start_navigation_mode.sh localization  # map_server + AMCL
./scripts/start_navigation_mode.sh navigation    # 单独 Nav2，要求定位已启动
./scripts/start_navigation_mode.sh bringup       # 定位 + Nav2 合并启动
./scripts/start_navigation_mode.sh --status
./scripts/stop_navigation_mode.sh
```

开机默认行为：

```text
QHXD_BOOT_START_NAV_FRONTEND=true
QHXD_BOOT_START_NAV_WEB_BRIDGE=true
QHXD_BOOT_NAV_MODE=none
```

也就是说，默认开机会准备好前置链路和网页可视化桥，但不会替用户决定建图还是导航。
如果需要开机直接进入导航待命，可在 `~/QHXD/.env` 设置 `QHXD_BOOT_NAV_MODE=bringup`。

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
GET /api/navigation/latest
GET /api/navigation/map/metadata
GET /api/navigation/map/image
WS  /ws/state
WS  /ws/imu
WS  /ws/navigation
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
POST /api/internal/navigation/map
POST /api/internal/navigation/state
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
PUBLIC_CONTROL_ENABLED=false  # 默认建议 false；演示/验收需要公网控制时可临时设为 true
PUBLIC_RATE_LIMIT_PER_MINUTE=60
PUBLIC_AUDIO_MAX_MB=20
PUBLIC_BROWSER_AUDIO_MAX_MB=5
PUBLIC_BROWSER_AUDIO_MAX_SECONDS=10
```

- 读接口可按白名单公开转发。
- 语音、模式切换和任务等写接口需 `Authorization: Bearer <PUBLIC_API_TOKEN>`。
- mission 控制另需 `PUBLIC_CONTROL_ENABLED=true`。
- 当前云端实际开关以 `curl https://api.lingxunrobot.cn/health` 返回的 `public_control_enabled` 为准。
- `/api/voice/record_command` 永远不直接暴露到公网。

## 重启后验收

### 一键状态

```bash
cd /home/robomaster/QHXD
./scripts/status_public_robot.sh
```

预期：RK backend、公网 gateway、公网 Web 正常；有相机时 YOLO 与 H.264 publisher 运行。
backend 可能显示为 systemd backend active，也可能显示为 PID debug backend running；只要
本地 `/health` 与公网 state proxy 正常即可。

### 后端与公网

```bash
curl --noproxy '*' http://127.0.0.1:8000/health
curl https://api.lingxunrobot.cn/health
curl https://lingxunrobot.cn/api/state/latest
```

### 导航地图与网页桥接

网页导航地图依赖三层同时正常：`livox_ws` 导航/定位产生 `/map` 与 TF，`navigation_web_bridge` 上传地图和位姿，Cloud Gateway 公网反代给前端。

```bash
cd /home/robomaster/QHXD
./scripts/start_navigation_frontend_detached.sh --status
./scripts/status_public_robot.sh

source /opt/ros/humble/setup.bash
source /home/robomaster/livox_ws/install/setup.bash
ros2 topic echo /map --once --field info
ros2 run tf2_ros tf2_echo map base_link

curl http://127.0.0.1:8000/api/navigation/map/metadata
curl http://127.0.0.1:8000/api/navigation/latest
curl https://lingxunrobot.cn/api/navigation/map/metadata
curl https://lingxunrobot.cn/api/navigation/latest
```

预期：metadata 返回 `width/height/resolution/image_url`，latest 返回 `map_version` 与 `pose`。如果 metadata 为 404，先执行 `./scripts/start_navigation_web_bridge.sh`，脚本会启动地图 watchdog 自动恢复一次。

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

预期：查询类响应 `mission_candidate=null`；前方状态会基于当前视觉对象、最近视觉事件和导航状态生成自然回复，不出现 `rk3588`、`YOLO`、`detection_status`、更新时间等工程描述；天气回复包含实时温湿度、降雨概率和出行建议；视频健康状态不暴露推流密钥。

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

### 网页端看不到导航地图

先区分是导航本体没出地图、桥接没上传，还是公网反代/前端缓存问题：

```bash
cd /home/robomaster/QHXD
./scripts/status_public_robot.sh

source /opt/ros/humble/setup.bash
source /home/robomaster/livox_ws/install/setup.bash
ros2 topic echo /map --once --field info
ros2 run tf2_ros tf2_echo map base_link

curl http://127.0.0.1:8000/api/navigation/map/metadata
curl https://lingxunrobot.cn/api/navigation/map/metadata
```

- `/map` 没有输出：先启动或修复 `~/livox_ws` 的定位/导航 bringup。
- `map -> base_link` 不存在：检查 AMCL/Point-LIO/TF 所有权，避免多个节点抢 `map -> odom` 或 `odom -> base_link`。
- 本地 metadata 404 但 `/map` 正常：重启 QHXD 桥接。

```bash
./scripts/stop_navigation_web_bridge.sh
./scripts/start_navigation_web_bridge.sh
tail -n 80 logs/navigation_web_bridge.log
tail -n 80 logs/navigation_web_bridge_map_watchdog.log
```

当前 `start_navigation_web_bridge.sh` 已带地图 watchdog；开机时如果 ROS `/map` 已存在但后端地图缓存为空，会自动重启一次桥接。若本地 metadata 正常而公网 metadata 异常，再查云端 Cloud Gateway/Nginx。

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
