# QHXD 琼海芯动车载机器人中台

QHXD 是琼海芯动车载机器人项目的 RK3588 中台工程。当前仓库同时包含：

- RK3588 本体后端：状态聚合、任务入口、语音/LLM、视觉状态、Dashboard API。
- Web Dashboard：本地调试与公网部署共用的机器人状态中枢页面。
- RKNN YOLO26 感知链路：USB / Hik 相机采集、单图推理、连续检测、MJPEG 最新帧。
- ROS 2 导航通信：当前正式链路为 `standard_robot_pp_ros2`，对接 C 板与 `/cmd_vel`、`/odom`。
- 云端 Cloud Gateway：公网 API / WebSocket / 前端静态资源反代到 RK3588。

项目原则：语音、LLM、YOLO 只通过已有任务/状态接口接入；视觉结果不直接控制底盘；公网控制默认关闭并需要 token 与安全开关。

## 当前部署架构

公网前端与完整业务后端不在同一台机器上：

```text
浏览器
  |-- https://lingxunrobot.cn/        -> 云服务器 Nginx -> 静态前端
  |-- https://lingxunrobot.cn/api/*   -> 云服务器 Cloud Gateway :9000
  `-- wss://lingxunrobot.cn/ws/*      -> 云服务器 Cloud Gateway :9000
                                                   |
                                                   | Tailscale
                                                   v
                                          RK3588 QHXD backend :8000
                                                   |
                     FunASR / DeepSeek / YOLO / 相机 / 麦克风 / ROS 2 / C 板
```

| 部署位置 | 运行内容 | 是否完整 QHXD 后端 |
| --- | --- | --- |
| 云服务器 | Nginx、公网静态前端、`lingxun-cloud-gateway` (`127.0.0.1:9000`) | 否，只做认证、限流、日志和转发 |
| RK3588 | FastAPI 完整后端 (`0.0.0.0:8000`)、语音、LLM、YOLO、导航与硬件接入 | 是 |
| RK3588 本地前端 | Vite dev server (`0.0.0.0:5173`) | 只用于本地开发调试，公网运行不需要 |

## 快捷启动

以下命令默认在 RK3588 项目根目录执行：

```bash
cd /home/robomaster/QHXD
```

### 当前生产启动方式（推荐）

当前 RK3588 已启用两个 systemd 服务：

- `qhxd-backend.service`：启动完整 QHXD FastAPI 后端，异常退出后自动重启。
- `qhxd-boot.service`：等待后端就绪、切换 `real` 模式、启动 `standard_robot_pp_ros2` 与 IMU bridge，并按 Hik 优先、USB 备用的顺序自动启动 YOLO 相机。

因此正常重启 RK3588 后不需要再手动运行 `start_all.sh` 或 `start_public_robot.sh`。直接检查：

```bash
./scripts/status_public_robot.sh
systemctl is-active qhxd-backend qhxd-boot
systemctl is-enabled qhxd-backend qhxd-boot
```

生产环境常用命令：

```bash
# 重启完整后端
sudo systemctl restart qhxd-backend

# 重新执行硬件、导航与相机的开机编排
sudo systemctl restart qhxd-boot

# 查看状态与日志
sudo systemctl status qhxd-backend qhxd-boot
sudo journalctl -u qhxd-backend -f
sudo journalctl -u qhxd-boot -f
```

新机器首次部署时，先安装 backend service，再安装 full-stack boot service：

```bash
./scripts/install_backend_service.sh
sudo install -m 0644 systemd/qhxd-boot.service /etc/systemd/system/qhxd-boot.service
sudo systemctl daemon-reload
sudo systemctl enable --now qhxd-boot.service
```

`qhxd-boot.service` 遇到未接 C 板或相机时会记录警告并继续启动；公网页面和 RK 后端仍可正常使用。

### 手动恢复与按需启动

`start_public_robot.sh` 保留为手动恢复入口。它默认只确保 backend 可用，不启动本地前端、YOLO 或 C 板通信：

```bash
# 只确保 RK backend 运行
./scripts/start_public_robot.sh

# 手动启动 backend + C 板通信
PUBLIC_ROBOT_START_CBOARD=true ./scripts/start_public_robot.sh

# 手动启动 backend + Hik YOLO
PUBLIC_ROBOT_START_YOLO=true PUBLIC_ROBOT_YOLO_MODE=hik ./scripts/start_public_robot.sh

# 手动启动 backend + USB YOLO
PUBLIC_ROBOT_START_YOLO=true PUBLIC_ROBOT_YOLO_MODE=usb ./scripts/start_public_robot.sh
```

### 本地调试启动

本地调试接口仍然保留：

```text
RK 后端：http://127.0.0.1:8000 或 http://<RK3588_IP>:8000
本地前端：http://<RK3588_IP>:5173
```

```bash
# 启动后端
./scripts/start_backend.sh

# 启动前端 Vite dev server
./scripts/start_frontend.sh

# 启动 USB / UVC YOLO 摄像头检测服务
./scripts/start_yolo_camera.sh

# 启动 Hikrobot / MVS YOLO 摄像头检测服务
./scripts/start_yolo_hik_camera.sh

# 本地一键 Hik 调试：后端 + Vite 前端 + Hik YOLO
./scripts/start_hik_web.sh

# 本地一键 USB 调试：后端 + Vite 前端 + USB YOLO
./scripts/start_all.sh

# 查看脚本托管的本地服务状态
./scripts/status_all.sh

# 停止脚本托管的前端 / YOLO / 后端
./scripts/stop_all.sh
```

注意：

- 公网前端由云服务器托管，不需要 RK 上的 `start_frontend.sh`。
- `start_backend.sh` 是 pid 文件模式，只适合手动调试；生产环境使用 `qhxd-backend.service`。
- `status_all.sh` 主要查看 pid 文件托管的本地调试进程；当前生产架构请使用 `status_public_robot.sh`。
- `stop_all.sh` 只停止脚本托管的调试进程，不代替 `systemctl stop qhxd-backend qhxd-boot`。

启动入口用途速查：

| 入口 | 用途 | 当前是否推荐 |
| --- | --- | --- |
| `qhxd-backend.service` + `qhxd-boot.service` | RK 生产环境开机自启 | 是 |
| `scripts/status_public_robot.sh` | 统一检查 RK backend、Tailscale、公网 gateway、YOLO 与 ROS 2 | 是 |
| `scripts/start_public_robot.sh` | systemd 异常时的手动恢复或按需启动 | 是，仅手动场景 |
| `scripts/start_frontend.sh` | RK 本地 Vite 开发页面 | 仅前端调试 |
| `scripts/start_all.sh` | backend + 本地 Vite + USB YOLO | 仅 USB 本地联调 |
| `scripts/start_hik_web.sh` | backend + 本地 Vite + Hik YOLO | 仅 Hik 本地联调 |

### 相机快捷入口

首次部署或更换 USB 摄像头后，建议绑定稳定设备名：

```bash
./scripts/setup_usb_camera_alias.sh
```

默认 USB 配置使用 `/dev/qhxd-usb-camera`：

```bash
./scripts/start_yolo_camera.sh
```

Hik 相机使用 MVS SDK 配置：

```bash
./scripts/start_yolo_hik_camera.sh
```

USB 与 Hik 复用同一个 `yolo_camera` 服务名；切换前建议先停掉旧服务：

```bash
source scripts/common.sh
stop_service yolo_camera
```

### 导航通信启动

当前正式 C 板通信包是 `standard_robot_pp_ros2`，不要再把旧 `rtt_nav_bridge` 当作主链路启动，否则可能抢占串口。

推荐使用脚本托管通信节点，避免手动 `ros2 launch` 后留下孤儿进程继续占用串口：

```bash
cd /home/robomaster/QHXD
./scripts/start_cboard_comm.sh
./scripts/status_public_robot.sh
./scripts/stop_cboard_comm.sh
```

如果需要手动调试，也可以直接启动 ROS 2 launch：

```bash
cd /home/robomaster/QHXD
source /opt/ros/humble/setup.bash
source install/setup.bash
ros2 launch standard_robot_pp_ros2 standard_robot_pp_ros2.launch.py
```

串口默认配置：

```text
standard_robot_pp_ros2/config/standard_robot_pp_ros2.yaml
device_name: /dev/ttyCBoard
baud_rate: 115200
publish_odom: true
publish_odom_tf: true
```

快速验证：

```bash
ros2 topic list | sort | grep -E '^/(cmd_vel|odom|tf|serial/robot_motion|serial/imu)'
ros2 topic echo /serial/imu --once
ros2 topic echo /serial/robot_motion --once
ros2 topic echo /odom --once
ros2 topic hz /odom
```

### C 板 IMU 到前端状态流

公网前端已经部署在云服务器，浏览器仍然只访问 `https://lingxunrobot.cn/api` 与 `wss://lingxunrobot.cn/ws`。C 板直接接入 RK3588 后，前端不直连 ROS 2；RK3588 本地 IMU bridge 将 ROS 2 话题写入现有后端契约：

```text
C 板 -> standard_robot_pp_ros2 -> /serial/imu
-> scripts/ros2_imu_bridge.py
-> POST /api/internal/nuc/imu
-> GET /api/imu/latest 与 WS /ws/imu
-> Cloud Gateway -> 公网前端
```

真实 IMU 接入前必须切到 `real` 模式，否则后端会按设计忽略 `/api/internal/nuc/imu` 输入：

```bash
curl -X POST http://127.0.0.1:8000/api/system/mode/switch \
  -H "Content-Type: application/json" \
  -d '{"mode":"real"}'
```

启动完整现场链路：

```bash
cd /home/robomaster/QHXD
PUBLIC_ROBOT_START_CBOARD=true ./scripts/start_public_robot.sh
```

IMU bridge 默认订阅 `/serial/imu`，以 20Hz 写入 `http://127.0.0.1:8000/api/internal/nuc/imu`，数据源标记为 `rk3588_cboard_ros2`。可通过环境变量覆盖：

```bash
ROS2_IMU_TOPIC=/serial/imu \
ROS2_IMU_BRIDGE_RATE_HZ=20 \
ROS2_IMU_BRIDGE_BACKEND_URL=http://127.0.0.1:8000 \
ROS2_IMU_BRIDGE_SOURCE=rk3588_cboard_ros2 \
./scripts/start_cboard_comm.sh
```

本地验收：

```bash
ros2 topic echo /serial/imu --once
tail -f logs/ros2_imu_bridge.log
curl --noproxy '*' -s http://127.0.0.1:8000/api/imu/latest
```

公网验收：

```bash
curl -s https://api.lingxunrobot.cn/health
curl -s https://lingxunrobot.cn/api/imu/latest
```

注意：默认串口配置仍是 `/dev/ttyCBoard`。如果当前只检测到 `/dev/ttyACM0`，先运行：

```bash
cd /home/robomaster/QHXD/standard_robot_pp_ros2
sudo ./script/create_udev_rules.sh
```

或者临时修改 `standard_robot_pp_ros2/config/standard_robot_pp_ros2.yaml` 与安装后的参数文件，将 `device_name` 改为实际串口。不要同时启动 `rtt_nav_bridge` 和 `standard_robot_pp_ros2`。

## 当前入口

### 公网入口

```text
Web 前端：https://lingxunrobot.cn
同域 API：https://lingxunrobot.cn/api
同域 WS：wss://lingxunrobot.cn/ws/state 与 /ws/imu

外部 API：https://api.lingxunrobot.cn
外部 WS：wss://api.lingxunrobot.cn/ws/state 与 /ws/imu
```

两类公网入口最终都反代到云服务器本机：

```text
http://127.0.0.1:9000
```

再由 Cloud Gateway 经 Tailscale 转发到 RK3588：

```text
http://100.113.173.115:8000
```

公网写接口需要页面顶部保存 token。token 是云服务器：

```text
/etc/lingxun-cloud-gateway.env
PUBLIC_API_TOKEN=...
```

### 本地入口

```text
RK backend：http://127.0.0.1:8000
健康检查：http://127.0.0.1:8000/health
Vite 前端：http://127.0.0.1:5173
MJPEG 最新帧：http://127.0.0.1:8000/api/perception/frame_stream
```

## 系统架构

```text
浏览器 / 小程序 / 外部客户端
        |
        | 公网 HTTPS / WSS
        v
云服务器 Nginx
        |
        | 127.0.0.1:9000
        v
Cloud Gateway
        |
        | Tailscale / HTTP
        v
RK3588 QHXD backend
        |
        +-- FunASR / USB 麦克风 / 浏览器上传音频
        +-- DeepSeek V4 语义解析 fallback
        +-- RKNN YOLO26 / USB 或 Hik 相机
        +-- ROS 2 standard_robot_pp_ros2 / C 板
        +-- Dashboard state_store / WebSocket
```

运行模式：

- `mock`：后端按 mock 状态循环刷新，适合前端与接口调试。
- `real`：等待真实导航、IMU、视觉、C 板等链路更新状态。

模式切换接口：

```bash
curl -X POST http://127.0.0.1:8000/api/system/mode/switch \
  -H "Content-Type: application/json" \
  -d '{"mode":"real"}'
```

## 目录说明

```text
backend/                  RK3588 FastAPI 后端
frontend/                 Vue 3 Dashboard
cloud_gateway/            云服务器公网中继服务
experiments/rknn_yolo/    RKNN YOLO26 推理与相机检测
standard_robot_pp_ros2/   当前正式 C 板 / 导航 ROS 2 通信包
rtt_nav_bridge/           旧 Phase6 桥接包，保留作参考与历史兼容
pb_rm_interfaces/         ROS 2 自定义消息依赖
scripts/                  本地启动、状态、清理、udev 绑定脚本
systemd/                  RK3588 systemd 服务模板
docs/                     协议、桥接与阶段文档
audio_test/               语音命令测试样本
```

运行时目录：

```text
.runtime/                         脚本 pid 文件
logs/                             脚本日志
backend/data/voice_records/       RK3588 本地录音文件
experiments/rknn_yolo/outputs/    YOLO JSON、画框图、latest frame
```

这些运行时文件已在 `.gitignore` 中忽略，避免上传录音、图片、日志和 ROS build 产物。

## 后端 API

后端入口文件：`backend/app/main.py`。

常用读取接口：

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

语音 / LLM 接口：

```text
POST /api/voice/text_command
POST /api/voice/asr_text_mock
POST /api/voice/smart_command
POST /api/voice/smart_audio_command
POST /api/voice/smart_record_command
POST /api/voice/audio_command
POST /api/voice/record_command
POST /api/robot/voice/onboard_smart_command
POST /api/voice/confirm_command
POST /api/voice/speak
GET  /api/voice/tts/latest
```

任务接口：

```text
POST /api/mission/go_to_waypoint
POST /api/mission/start_patrol
POST /api/mission/pause
POST /api/mission/resume
POST /api/mission/return_home
```

内部状态接入：

```text
POST /api/internal/perception/detection_status
POST /api/internal/nuc/state
POST /api/internal/nuc/imu
```

说明：`/api/internal/nuc/*` 是历史命名，前端显示已经逐步改为 Nav/Navi 概念；接口名暂不改，以保持兼容。

## 语音与 LLM

### 灵巡 Sentinel 智能助手

Phase 9A 后，机器人正式身份为：

```text
灵巡 Sentinel
```

统一身份档案：

```text
backend/app/config/robot_profile.json
```

修改机器人名称、能力列表、安全规则、自我介绍时，只改这个配置文件；后端查询回复会从该配置读取，不在多个业务文件中硬编码。

Dashboard 的“发送文本命令”“网页麦克风识别”“车载麦克风识别”默认都进入智能助手链路，不需要再单独点击“智能助手解析”。Legacy 的 `/api/voice/text_command`、`audio_command`、`record_command` 保留用于兼容和底层调试。

智能助手文本接口：

```bash
curl -X POST http://127.0.0.1:8000/api/voice/smart_command \
  -H "Content-Type: application/json" \
  -d '{"text":"你是谁","source":"curl","requested_by":"operator","generate_tts":true}'
```

典型返回字段：

```json
{
  "recognized_text": "你是谁",
  "intent": "query_self_identity",
  "data_source": "robot_profile",
  "reply_text": "你好，我是灵巡 Sentinel...",
  "need_confirm": false,
  "mission_candidate": null,
  "tts_status": {
    "backend": "mock",
    "status": "generated"
  }
}
```

查询类命令会直接返回自然语言回复，不触发 mission：

```text
你是谁
你使用的模型是什么
你能做什么
你可以自己控制底盘吗
当前机器人状态正常吗
当前任务是什么
你还有多少电
急停了吗
视觉检测到了什么
现在天气怎么样
当前环境适合巡检吗
```

开放问答会通过 DeepSeek fallback 返回 `open_chat` 的 `reply_text`，但不能触发机器人运动：

```bash
curl -X POST http://127.0.0.1:8000/api/voice/smart_command \
  -H "Content-Type: application/json" \
  -d '{"text":"请用一句话解释你如何协助导航","use_llm":true}'
```

其中 `open_chat` 只能用于回答，不能包含 `mission_candidate`。涉及导航时，回复应说明运动控制仍由结构化任务、本地安全校验和用户确认流程接管。

运动类命令只生成候选任务和待确认 ID：

```bash
curl -X POST http://127.0.0.1:8000/api/voice/smart_command \
  -H "Content-Type: application/json" \
  -d '{"text":"帮我送到二零一实验室","source":"curl","requested_by":"operator"}'
```

返回中应包含：

```text
intent=go_to_waypoint
need_confirm=true
mission_candidate.command=go_to_waypoint
mission_candidate.payload.waypoint_id=wp_201
pending_command_id=...
```

确认执行仍使用原有接口：

```bash
curl -X POST http://127.0.0.1:8000/api/voice/confirm_command \
  -H "Content-Type: application/json" \
  -d '{"pending_command_id":"<id>","confirmed":true,"requested_by":"operator"}'
```

取消：

```bash
curl -X POST http://127.0.0.1:8000/api/voice/confirm_command \
  -H "Content-Type: application/json" \
  -d '{"pending_command_id":"<id>","confirmed":false,"requested_by":"operator"}'
```

智能助手交互日志：

```text
backend/data/smart_voice_logs.jsonl
```

日志字段包括 `request_id`、`recognized_text`、`intent`、`data_source`、`reply_text`、`need_confirm`、`mission_candidate`、`tts_status`、`error_reason`、`timestamp`。

### 支持命令

配置文件：

```text
backend/app/config/voice_commands.json
backend/app/config/waypoints.json
```

当前支持：

- 去某个目标点，例如“去二零一实验室”“去一号点”。
- 暂停任务。
- 继续任务。
- 返回起点。
- 开始巡检。
- 查询状态 / 查询任务 / 查询视觉检测。
- 未知命令：拒绝，不触发 mission。

当前 waypoint：

```text
wp_201：二零一实验室，别名：二零一实验室 / 201实验室 / 二零一 / 201
wp_001：一号点，别名：一号点 / 1号点 / 1 号点 / 一号
wp_002：二号点，别名：二号点 / 2号点 / 2 号点 / 二号 / 202
home：起点，别名：起点 / 装载点 / 返回点 / home / 家
```

注意：不要让多个 waypoint 共享同一个短别名，例如 `201` 或 `实验室`。歧义地点不会触发 mission。

### 天气 / 环境查询

传感器板正式接入前，环境查询先走 weather provider，不伪装成机器人本体传感器：

```bash
curl http://127.0.0.1:8000/api/external/weather/latest
```

返回字段包含：

```text
location, temperature_c, humidity_percent, weather, wind, source, updated_at
```

`source` 固定为 `weather_provider`。当前可用 `.env` 覆盖 mock 天气：

```env
WEATHER_LOCATION=海南海口
WEATHER_TEMPERATURE_C=28.6
WEATHER_HUMIDITY_PERCENT=82
WEATHER_TEXT=多云
WEATHER_WIND=东南风
```

### TTS 播报

第一版 TTS 默认是 mock，占位接口稳定但不阻塞任务主流程：

```env
TTS_BACKEND=mock
```

手动播报：

```bash
curl -X POST http://127.0.0.1:8000/api/voice/speak \
  -H "Content-Type: application/json" \
  -d '{"text":"我是灵巡 Sentinel。","source":"curl"}'
```

查询最近一次 TTS 状态：

```bash
curl http://127.0.0.1:8000/api/voice/tts/latest
```

### 本地文本命令

```bash
curl -X POST http://127.0.0.1:8000/api/voice/text_command \
  -H "Content-Type: application/json" \
  -d '{"text":"去一号点","source":"text-debug","requested_by":"operator"}'
```

移动类语义默认进入二次确认：

```bash
curl -X POST http://127.0.0.1:8000/api/voice/confirm_command \
  -H "Content-Type: application/json" \
  -d '{"pending_command_id":"<id>","confirm":true,"source":"operator"}'
```

### 文件音频识别

```bash
curl -X POST http://127.0.0.1:8000/api/voice/audio_command \
  -F "file=@audio_test/cmd_201.wav;type=audio/wav" \
  -F "source=audio-test" \
  -F "requested_by=operator"
```

### RK3588 车载麦克风录音

本地接口：

```bash
curl -X POST http://127.0.0.1:8000/api/voice/smart_record_command \
  -H "Content-Type: application/json" \
  -d '{"duration":3,"source":"rk3588-record-command","requested_by":"operator"}'
```

公网不直接暴露 `/api/voice/record_command`，因为它会录云服务器本机而不是机器人本体。公网车载麦克风默认走智能助手：

```text
POST /api/robot/voice/onboard_smart_command
```

### 浏览器麦克风

公网前端的“网页麦克风识别”使用浏览器 `MediaRecorder` 录音：

```text
浏览器 webm/ogg/wav
-> /api/voice/browser_smart_command
-> 云端 ffmpeg 转 16kHz mono wav
-> RK3588 /api/voice/smart_audio_command
-> ASR 结果进入 /api/voice/smart_command
```

### LLM 配置

`.env` 示例：

```env
LLM_BACKEND=deepseek
LLM_ENABLE=true
DEEPSEEK_ENABLE=true
DEEPSEEK_API_KEY=your_deepseek_api_key_here
DEEPSEEK_BASE_URL=https://api.deepseek.com
DEEPSEEK_MODEL=deepseek-v4-flash
LLM_REQUIRE_CONFIRM_FOR_MOTION=true
VOICE_PENDING_TTL_SECONDS=30
```

规则解析优先；LLM 只作为复杂自然语言 fallback。LLM 输出必须经过本地 schema 和安全校验；非法 waypoint、低置信度、非 JSON、API 失败都不会触发任务。

## YOLO 感知与相机

目录：

```text
experiments/rknn_yolo/
```

当前已验证 RKNN 模型配置：

```text
模型：models/yolo26n_fp32.rknn
labels：models/labels.txt
输入：RGB + NHWC + float32 / 255.0 + 640x640
输出 shape：(1, 300, 6)
推荐输出 layout：xyxy_score_class
```

单图验收：

```bash
cd /home/robomaster/QHXD/experiments/rknn_yolo

python3 infer_image.py \
  --model models/yolo26n_fp32.rknn \
  --image samples/test.jpg \
  --labels models/labels.txt \
  --conf 0.25 \
  --format detection_status \
  --output-layout xyxy_score_class \
  --max-det 20 \
  --draw-output outputs/test_fixed_preprocess.jpg \
  > outputs/detection_status_fixed_preprocess.json
```

连续检测配置：

```text
USB：experiments/rknn_yolo/camera_config.json
Hik：experiments/rknn_yolo/camera_config_hik.example.json
```

配置重点：

```json
{
  "fps": 5,
  "submit": true,
  "save_latest": "outputs/latest_hik_detection.jpg",
  "max_det": 20,
  "output_layout": "xyxy_score_class",
  "camera_backend": "hik"
}
```

`fps` 是 YOLO 服务取帧、推理、保存 latest、提交 `detection_status` 的频率，不是前端显示刷新率，也不是 Hik 相机硬件采集帧率。

Hik 硬件采集帧率在 `hik_params` 中：

```json
{
  "hik_params": {
    "bool": {
      "AcquisitionFrameRateEnable": true
    },
    "float": {
      "AcquisitionFrameRate": 5.0
    }
  }
}
```

前端显示使用后端 MJPEG：

```env
VITE_USE_MJPEG_STREAM=true
PERCEPTION_MJPEG_INTERVAL_MS=200
VITE_LATEST_FRAME_INTERVAL_MS=2000
PERCEPTION_LATEST_FRAME_MAX_AGE_SECONDS=10
```

`PERCEPTION_MJPEG_INTERVAL_MS=200` 表示后端 MJPEG 流最多每 200ms 检查一次 latest 图片；如果 YOLO 服务没有产生新图，前端不会凭空刷新。

## ROS 2 导航通信

当前正式包：

```text
standard_robot_pp_ros2/
```

职责：

- 打开 C 板 USB CDC 串口，默认 `/dev/ttyCBoard`。
- 通过 BCP 协议接收下位机数据。
- 发布 `/serial/robot_motion`、`/serial/imu`。
- 将底盘速度积分为 `/odom`。
- 可选发布 `odom -> base_link` TF。
- 订阅 `/cmd_vel` 并下发给 C 板。

编译：

```bash
cd /home/robomaster/QHXD
source /opt/ros/humble/setup.bash
colcon build --packages-select standard_robot_pp_ros2 --symlink-install
source install/setup.bash
```

启动：

```bash
ros2 launch standard_robot_pp_ros2 standard_robot_pp_ros2.launch.py
```

不要同时启动：

```text
rtt_nav_bridge
standard_robot_pp_ros2
```

否则两个节点可能抢同一个 `/dev/ttyACM0` / `/dev/ttyCBoard`。

如果 `/odom` topic 存在但没有数据，先确认 C 板是否真的持续上发：

```bash
ros2 topic echo /serial/robot_motion --once
ros2 topic echo /odom --once
lsof /dev/ttyACM0 2>/dev/null || true
```

更多导航说明见：

```text
standard_robot_pp_ros2/README.md
```

## 公网 Cloud Gateway

云端目录：

```text
/opt/lingxun-cloud-gateway
/etc/lingxun-cloud-gateway.env
/etc/systemd/system/lingxun-cloud-gateway.service
/var/www/lingxunrobot
```

环境变量：

```env
RK_BACKEND_BASE_URL=http://100.113.173.115:8000
PUBLIC_API_TOKEN=replace-with-secret-token
PUBLIC_CONTROL_ENABLED=false
PUBLIC_RATE_LIMIT_PER_MINUTE=60
PUBLIC_AUDIO_MAX_MB=20
PUBLIC_BROWSER_AUDIO_MAX_MB=5
PUBLIC_BROWSER_AUDIO_MAX_SECONDS=10
GATEWAY_OPERATION_LOG=/var/log/lingxun-cloud-gateway/operations.jsonl
```

云服务器常用命令：

```bash
sudo systemctl status lingxun-cloud-gateway
sudo systemctl restart lingxun-cloud-gateway
sudo journalctl -u lingxun-cloud-gateway -f
curl http://127.0.0.1:9000/health
tail -f /var/log/lingxun-cloud-gateway/operations.jsonl
```

公网 endpoint 策略：

- 读接口：`/health`、`/api/state/latest`、`/api/alerts`、`/api/tasks/current`、`/api/imu/latest`、`/api/perception/*`、`/api/external/weather/latest`、`/api/voice/tts/latest`、`/ws/state`、`/ws/imu`。
- 写接口：`/api/voice/text_command`、`/api/voice/audio_command`、`/api/voice/browser_audio_command`、`/api/voice/browser_smart_command`、`/api/voice/smart_command`、`/api/voice/smart_audio_command`、`/api/voice/smart_record_command`、`/api/robot/voice/onboard_smart_command`、`/api/voice/speak`、`/api/voice/confirm_command` 等都需要 `Authorization: Bearer <PUBLIC_API_TOKEN>`。
- mission 控制：还需要 `PUBLIC_CONTROL_ENABLED=true`。
- 禁止公网直连：`POST /api/voice/record_command`。

已知公网域名排障：

- 如果 HTTP 返回 `dnspod.qcloud.com/static/webblock.html` 或 HTTPS 握手提前 EOF，优先检查域名备案、DNSPod/云厂商 WebBlock、证书与安全策略。
- 如果云服务器本机 `curl http://127.0.0.1:9000/health` 正常，且 RK `curl http://127.0.0.1:8000/health` 正常，问题通常不在 RK backend。

## 环境变量总览

根目录 `.env` 会被 `scripts/common.sh` 和后端相关服务读取。`.env` 不应提交。

常用变量：

```env
BACKEND_PORT=8000
BACKEND_HOST=0.0.0.0
FRONTEND_PORT=5173

LLM_ENABLE=true
DEEPSEEK_API_KEY=...

AUDIO_DEVICE=plughw:CARD=Device,DEV=0
AUDIO_RECORD_SECONDS=3
VOICE_MAX_UPLOAD_MB=20
VOICE_MAX_AUDIO_SECONDS=10

VITE_USE_MJPEG_STREAM=true
PERCEPTION_MJPEG_INTERVAL_MS=200
VITE_LATEST_FRAME_INTERVAL_MS=2000
VITE_DETECTION_EVENT_HOLD_MS=15000
VITE_DETECTION_EVENT_MAX_ITEMS=12
```

前端环境：

```text
frontend/.env.development
frontend/.env.production
```

生产前端默认同域访问 `/api` 和 `/ws`；本地开发可通过 Vite proxy 访问 RK backend。

## 构建与验证

后端健康：

```bash
curl --noproxy '*' http://127.0.0.1:8000/health
```

前端构建：

```bash
cd /home/robomaster/QHXD/frontend
npm run build
```

YOLO 单图：

```bash
cd /home/robomaster/QHXD/experiments/rknn_yolo
python3 infer_image.py --model models/yolo26n_fp32.rknn --image samples/test.jpg --labels models/labels.txt --format detections --output-layout xyxy_score_class --max-det 20
```

YOLO 连续服务 dry-run：

```bash
cd /home/robomaster/QHXD/experiments/rknn_yolo
python3 camera_detect_service.py --config camera_config.json --dry-run --max-frames 2
python3 camera_detect_service.py --config camera_config_hik.example.json --dry-run --max-frames 2
```

语音文件：

```bash
curl -X POST http://127.0.0.1:8000/api/voice/audio_command \
  -F "file=@/home/robomaster/QHXD/audio_test/cmd_201.wav;type=audio/wav"
```

智能助手：

```bash
curl -X POST http://127.0.0.1:8000/api/voice/smart_command \
  -H "Content-Type: application/json" \
  -d '{"text":"你是谁","generate_tts":true}'

curl -X POST http://127.0.0.1:8000/api/voice/smart_command \
  -H "Content-Type: application/json" \
  -d '{"text":"帮我送到二零一实验室"}'
```

天气与 TTS：

```bash
curl http://127.0.0.1:8000/api/external/weather/latest
curl -X POST http://127.0.0.1:8000/api/voice/speak \
  -H "Content-Type: application/json" \
  -d '{"text":"我是灵巡 Sentinel。"}'
curl http://127.0.0.1:8000/api/voice/tts/latest
```

公网 gateway：

```bash
# 任意能访问公网的机器
curl https://api.lingxunrobot.cn/health

# 仅在云服务器本机执行
curl http://127.0.0.1:9000/health
```

ROS 2：

```bash
source /opt/ros/humble/setup.bash
source /home/robomaster/QHXD/install/setup.bash
ros2 topic list | sort
```

## 常见问题

### RK3588 重启后是否要手动开后端和硬件链路？

当前这台 RK3588 不需要。`qhxd-backend.service` 负责完整后端，`qhxd-boot.service` 负责 real 模式、C 板/IMU bridge 和相机 YOLO 编排。用以下命令确认：

```bash
systemctl is-active qhxd-backend qhxd-boot
systemctl is-enabled qhxd-backend qhxd-boot
./scripts/status_public_robot.sh
```

本地 Vite 前端不属于公网生产必需服务，RK 重启后不运行 `start_frontend.sh` 也不影响 `https://lingxunrobot.cn`。

### 公网 token 填什么？

填云服务器 `/etc/lingxun-cloud-gateway.env` 中的 `PUBLIC_API_TOKEN`。页面顶部保存后，公网写接口会自动带：

```text
Authorization: Bearer <token>
```

### 前端画面为什么不刷新？

先看后端是否有新图：

```bash
curl --noproxy '*' -i 'http://127.0.0.1:8000/api/perception/latest_frame?t=check'
```

如果返回 `latest_frame_stale`，说明 YOLO 服务没有持续产出新图片。继续看：

```bash
tail -f logs/yolo_camera.log
ls -lh experiments/rknn_yolo/outputs/latest_*_detection.jpg
```

### Hik 相机经常掉线怎么办？

优先确认硬件链路：USB3 口、线缆、供电、MVS SDK 枚举。软件侧已有重连和 stale frame 保护，不会把旧图伪装成实时画面。

```bash
lsusb | grep -i Hik
tail -f logs/yolo_camera.log
```

### C 板接上后 `/odom` 没数据？

`ros2 topic list` 只能说明 publisher 存在，不代表真实数据已上发。先检查：

```bash
ros2 topic echo /serial/robot_motion --once
ros2 topic echo /serial/imu --once
ros2 topic echo /odom --once
lsof /dev/ttyACM0 2>/dev/null || true
```

确认没有旧节点占串口，并优先使用脚本停止通信链路：

```bash
./scripts/stop_cboard_comm.sh
ps -eo pid,ppid,cmd | grep -E 'standard_robot_pp_ros2_node|rtt_nav_bridge' | grep -v grep || true
fuser -v /dev/ttyCBoard 2>/dev/null || true
```

如果 `logs/standard_robot_pp_ros2.log` 出现 `No valid BCP frame`，说明通信节点打开了串口但没有收到 C 板有效帧；如果 `logs/ros2_imu_bridge.log` 持续出现 `waiting for IMU messages`，说明 bridge 已运行但 `/serial/imu` 本身没有真实消息。

### 语音识别失败？

检查麦克风设备、FunASR 模型、录音文件：

```bash
arecord -l
curl -X POST http://127.0.0.1:8000/api/voice/record_command \
  -H "Content-Type: application/json" \
  -d '{"duration":3}'
```

清理录音：

```bash
./scripts/cleanup_voice_records.sh
DAYS=3 ./scripts/cleanup_voice_records.sh --delete
```

## 历史与交接文档

阶段完成记录：

```text
PHASE4_DONE.md
PHASE5_DONE.md
PHASE6_DONE.md
PHASE7_DONE.md
PHASE8A_DONE.md
PHASE8B_DONE.md
HIK_CAMERA_SOURCE_STATUS.md
```

模块细节：

```text
experiments/rknn_yolo/README.md
standard_robot_pp_ros2/README.md
cloud_gateway/README.md
docs/PHASE6_RTT_NAV_BRIDGE.md
docs/PHASE6_NAV_PROTOCOL_V1.md
docs/PHASE6_PROTOCOL_REVIEW.md
```

历史 `DO_PHASE*.md` / `DONE*.md` 文件保留为开发过程记录。新成员优先阅读本 README，再按模块进入对应 README。

## 历史调试经验 (2026-06-05 嵌赛联调)

以下记录了小程序、Cloud Gateway、RK3588 后端三方联调中遇到的典型问题与解决方案。其中备案未完成时的 SSH 隧道方案仅作历史参考，不是当前生产架构。

### 1. 车载麦克风识别报错 422

**现象**：Web 前端点击"车载麦克风识别"总是返回 HTTP 422，浏览器麦克风正常。

**根因**：Cloud Gateway `onboard_record_command` 中 Python `or` 短路求值 bug：

```python
# 修复前
use_smart = request.url.path.endswith("/onboard_smart_command") or _parse_bool(payload.pop("smart", False), False)
# URL 路径以 /onboard_smart_command 结尾时，or 左侧为 True，
# 右侧 payload.pop("smart") 永不执行，"smart" 键残留在 payload 中
```

修复后分开 pop 和判断：

```python
smart_flag = payload.pop("smart", None)
use_smart = request.url.path.endswith("/onboard_smart_command") or _parse_bool(smart_flag, False)
```

**影响文件**：`cloud_gateway/cloud_gateway.py`（云服务器 `/opt/lingxun-cloud-gateway/cloud_gateway.py`）

### 2. Mock 模式缺少 IMU 数据源

**现象**：小程序在 Mock 模式下 IMU 始终显示"暂无 IMU 数据"。

**根因**：`mock_state.py` 只生成机器人状态（电池、导航、任务），不生成 IMU 数据。IMU 唯一数据源是 C 板 → ROS 2 → `imu_bridge` → `/api/internal/nuc/imu` 的 Real 链路。

**修复**：在 `mock_state.py` 的 `tick()` 中添加 `_tick_mock_imu()` 方法，每秒生成带随机噪声的模拟 IMU 数据（偏航角 ±15° 波动、角速度/加速度小幅噪声），写入 `imu_store`。

**影响文件**：`backend/app/services/mock_state.py`

### 3. 备案前小程序无法直连公网域名（已解决）

**现象**：微信开发者工具中所有 `wx.request` 报 `net::ERR_CONNECTION_CLOSED`，但云服务器本机 curl 正常。

**根因**：`api.lingxunrobot.cn` 未完成 ICP 备案，用户本地网络（国内运营商）在 TCP 层阻断对该域名的访问。云服务器自身、GPT ATLAS 等走不同网络路径不受影响。

**当时的临时方案**：SSH 本地端口转发绕过网络限制：

```bash
# REST/WebSocket 隧道（HTTP → Cloud Gateway）
ssh -f -N -L 18443:127.0.0.1:9000 \
  -i ~/.ssh/UBUNTU.pem ubuntu@106.53.169.127

# 开发时将小程序 config.js ENV 设为 local
```

**当前状态**：网站已完成 ICP 备案与公安联网备案，生产环境应使用 `ENV: prod`，直接访问：

```text
REST: https://api.lingxunrobot.cn
WebSocket: wss://api.lingxunrobot.cn/ws/state 与 /ws/imu
```

SSH 隧道只作域名或网络故障时的临时排障方案。

### 4. 小程序图片无法显示（wx-image 强制 HTTPS）

**现象**：隧道打通后 REST/IMU 数据已正常，但 `<image>` 组件报"不再支持 HTTP 协议，请升级到 HTTPS"。

**根因**：微信小程序 `<image>` 组件底层走 `wx.downloadFile`，在较新基础库上强制要求 HTTPS。通过 SSH 本地转发到云网关的 HTTP 端口不能满足此要求。

**修复**：不再使用 `<image src="https://...">` 外部 URL，改为 `wx.request` 以 HTTP 下载图片 → `wx.arrayBufferToBase64()` 转 base64 → `<image src="data:image/jpeg;base64,...">` 内联显示。每 3 秒刷新一次（`?t=` 缓存控制，与 YOLO 相机 ~5fps 帧率匹配）。

```javascript
// 关键代码模式
wx.request({
  url: imageUrl,
  responseType: arraybuffer,
  success(res) {
    const base64 = wx.arrayBufferToBase64(res.data);
    this.setData({ imageDataUri: `data:image/jpeg;base64,${base64}` });
  }
});
```

### 5. 图片频繁闪烁

**现象**：图片每次刷新时出现白色闪烁（先白后图）。

**根因**：`Date.now()` 作为图片 URL 的 `?t=` 参数每秒变化，`<image>` 组件每次看到新的 `src` 就卸载旧图重新加载，加载间隙为白色。

**尝试过的方案**：
- URL 缓存参数从每秒改为每 3 秒 → 降低频率，未根除
- 双图交替（两张 `image` 叠加，一张可见一张隐藏，交替切换 `src` 和 z-index）→ 仍然闪烁

**最终方案**：base64 内联方案天然避免此问题。`data:` URI 变更时浏览器直接解码渲染，不存在"正在请求外部资源"的空白期。

### 6. 设置页模式切换体验问题

**问题**：用户点击 Mock/Real 切换按钮后无即时反馈，网络失败时 UI 不回退。

**修复**：
- 乐观更新：点击时立即移动 toggle 位置 + 更新模式标签，后台发 API
- 失败回滚：API 返回错误时自动恢复 toggle 到原位
- Token 缺失时在模式卡片内直接显示红色提示条
- 模式切换请求独立超时 15s（默认 8s 不够）

**影响文件**：`pages/settings/settings.js`, `pages/settings/settings.wxml`, `pages/settings/settings.wxss`, `utils/commandClient.js`

### 小程序开发环境速查

| 配置项 | 值 | 说明 |
|--------|-----|------|
| `config.js ENV` | `prod` | 当前生产环境直连 HTTPS / WSS |
| 隧道 REST | `localhost:18443 → cloud:9000` | 仅故障排查时临时使用 |
| 图片加载 | `wx.request` → base64 | 绕过 wx-image HTTPS 限制 |
| 合法域名校验 | 使用已配置的 `api.lingxunrobot.cn` | 真机/发布环境不依赖“不校验”选项 |
| ICP 备案状态 | 已完成 | 公网域名为当前正式入口 |
