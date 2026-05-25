# RK3588 Middleware Phase 2

## 快捷启动

在项目根目录 `/home/robomaster/QHXD` 下执行：

```bash
# 启动后端
./scripts/start_backend.sh

# 启动前端
./scripts/start_frontend.sh

# 首次部署或更换 USB 摄像头后，绑定稳定设备名 /dev/qhxd-usb-camera
./scripts/setup_usb_camera_alias.sh

# 启动 YOLO 摄像头检测服务，默认使用 USB / UVC 摄像头
./scripts/start_yolo_camera.sh

# 启动 YOLO 摄像头检测服务，使用 Hikrobot / MVS 相机配置
./scripts/start_yolo_hik_camera.sh

# 一键启动三项服务，YOLO 默认仍使用 USB / UVC 摄像头
./scripts/start_all.sh

# 查看状态
./scripts/status_all.sh

# 停止由脚本启动的服务
./scripts/stop_all.sh
```

三项服务默认配置：后端 `8000`、前端 `5173`、YOLO 配置 `experiments/rknn_yolo/camera_config.json`、日志目录 `logs/`、pid 目录 `.runtime/`。`setup_usb_camera_alias.sh` 会写入 udev 规则，执行时需要 sudo。`camera_config.json` 默认使用稳定设备名 `/dev/qhxd-usb-camera` 作为 USB 摄像头入口；Hik 快捷脚本使用 `experiments/rknn_yolo/camera_config_hik.example.json`，并复用同一个 `yolo_camera` 服务名，所以 `status_all.sh` / `stop_all.sh` 对 USB 与 Hik 启动方式都有效。切换 USB 和 Hik 前，建议先执行 `./scripts/stop_all.sh` 或确认 `yolo_camera` 已停止。


## 相机采集、YOLO 处理与前端刷新频率

这里有三层频率，含义不同，现场调试时不要混在一起：

- Hik 相机硬件采集帧率：相机本身每秒输出多少帧，写在 `experiments/rknn_yolo/camera_config_hik.example.json` 的 `hik_params` 中。
- YOLO 服务处理/上传 latest 图片频率：服务每秒取多少帧进入 RKNN、保存 latest 图片、提交 detection_status，写在 `camera_config*.json` 的 `fps` 中。
- Dashboard 前端画面显示方式：默认使用 MJPEG JPEG bytes 流 `/api/perception/frame_stream`，由 `.env` 的 `VITE_USE_MJPEG_STREAM=true` 开启。
- MJPEG 流检查 latest 图片的间隔：后端环境变量 `PERCEPTION_MJPEG_INTERVAL_MS`，默认 `200` 毫秒。
- latest-frame 轮询 fallback 间隔：前端环境变量 `VITE_LATEST_FRAME_INTERVAL_MS`，默认 `2000` 毫秒；只有关闭 MJPEG 或 MJPEG 出错回退时才主要使用。
- 视觉事件保持时间：前端环境变量 `VITE_DETECTION_EVENT_HOLD_MS`，默认 `15000` 毫秒；事件出现后会留在 YOLO Events 和最近事件列表中，直到过期或被更新事件顶替。

如果你想改“海康相机画面在前端显示更新得多快”，优先确认 MJPEG 已开启：

```bash
cd /home/robomaster/QHXD
grep '^VITE_USE_MJPEG_STREAM=' .env
grep '^PERCEPTION_MJPEG_INTERVAL_MS=' .env
```

推荐配置：

```env
VITE_USE_MJPEG_STREAM=true
PERCEPTION_MJPEG_INTERVAL_MS=200
VITE_LATEST_FRAME_INTERVAL_MS=1000
VITE_DETECTION_EVENT_HOLD_MS=15000
VITE_DETECTION_EVENT_MAX_ITEMS=12
```

`PERCEPTION_MJPEG_INTERVAL_MS=200` 表示后端 MJPEG 流最多每 200ms 检查一次是否有新 latest 图片。它不会凭空制造新帧，如果 YOLO 服务没有产生新图，前端仍然只能看到上一帧。

改完 `.env` 后需要重启后端和前端。`start_frontend.sh` 如果发现前端已经可访问，会直接退出，所以要先停掉旧前端进程：

```bash
cd /home/robomaster/QHXD
source scripts/common.sh
stop_service backend
stop_service frontend
./scripts/start_backend.sh
./scripts/start_frontend.sh
```

如果要临时关闭 MJPEG，改为：

```env
VITE_USE_MJPEG_STREAM=false
```

关闭后前端会回到 `/api/perception/latest_frame?t=...` 轮询模式，此时 `VITE_LATEST_FRAME_INTERVAL_MS` 才是主要显示刷新间隔。最低允许值为 `200ms`；配置得更低会被前端保护到 `200ms`，避免浏览器过度请求。

如果你想改 YOLO 服务生成 latest 图片和提交 detection_status 的频率，改 `fps`：

```json
{
  "fps": 1
}
```

常用配置文件：

- USB / UVC 摄像头：`experiments/rknn_yolo/camera_config.json`
- Hikrobot / MVS 相机：`experiments/rknn_yolo/camera_config_hik.example.json`

也可以临时用 CLI 覆盖：

```bash
cd /home/robomaster/QHXD/experiments/rknn_yolo
python3 camera_detect_service.py --config camera_config.json --fps 2
python3 camera_detect_service.py --config camera_config_hik.example.json --fps 2
```

如果你想改 Hik 相机硬件采集帧率，改 `camera_config_hik.example.json` 里的 `hik_params`：

```json
{
  "hik_params": {
    "bool": {
      "AcquisitionFrameRateEnable": true
    },
    "float": {
      "AcquisitionFrameRate": 10.0
    }
  }
}
```

`AcquisitionFrameRate=10.0` 表示限制 Hik 相机侧目标 10 FPS 出帧；这不等于 YOLO 每秒推理 10 帧，也不等于前端每秒显示 10 次。

实际前端看到的画面更新速度取决于更慢的那一层：如果 YOLO `fps=1`，即使前端每 `200ms` 请求一次，也只会反复拿到同一张图；如果 YOLO `fps=5`，但前端 `VITE_LATEST_FRAME_INTERVAL_MS=2000`，页面仍然大约 2 秒才换一次图。如果 RKNN 推理、相机取帧或后端提交耗时超过 `1 / fps`，实际 YOLO 处理频率也会低于配置值，这是正常保护行为。


## DeepSeek V4 API 配置

DeepSeek V4 只用于语音识别文本之后的语义解析 fallback，不直接控制底盘、不直接调用 RT-Thread，也不替代本地规则解析。简单命令仍优先走规则解析；复杂自然语言在允许 LLM 时才会调用 DeepSeek。

真实 API Key 禁止提交到 Git。项目只提供占位示例：

```text
.env.example
```

推荐配置：

```bash
cp .env.example .env
# 编辑 .env，把 DEEPSEEK_API_KEY 改成真实 key；不要提交 .env
```

也可以直接在启动后端前导出环境变量：

```bash
export LLM_BACKEND=deepseek
export LLM_ENABLE=true
export DEEPSEEK_API_KEY="真实 key 放这里，不提交 Git"
export DEEPSEEK_BASE_URL="https://api.deepseek.com"
export DEEPSEEK_MODEL="deepseek-v4-flash"
```

后端读取这些变量：

```bash
DEEPSEEK_API_KEY
DEEPSEEK_BASE_URL
DEEPSEEK_MODEL
DEEPSEEK_TIMEOUT_SECONDS
DEEPSEEK_MAX_TOKENS
DEEPSEEK_TEMPERATURE
LLM_CONFIDENCE_THRESHOLD
LLM_REQUIRE_CONFIRM_FOR_MOTION
VOICE_PENDING_TTL_SECONDS
```

推荐模型：

```bash
DEEPSEEK_MODEL=deepseek-v4-flash
```

如果语义解析效果不够，再切换：

```bash
DEEPSEEK_MODEL=deepseek-v4-pro
```

未配置 `DEEPSEEK_API_KEY` 或 `LLM_ENABLE=false` 时，后端不会启动失败，会自动保持规则解析路径。API 超时、返回非 JSON、低置信度、未知 intent、非法 waypoint 都不会触发 mission。

文本命令可按请求控制是否允许 LLM：

```bash
curl -X POST http://127.0.0.1:8000/api/voice/text_command \
  -H 'Content-Type: application/json' \
  -d '{"text":"帮我把样品送到二零一实验室","source":"text-debug","requested_by":"operator","use_llm":true}'
```

移动类 LLM 结果默认需要二次确认，首次返回 `accepted=false`、`need_confirm=true`、`pending_command_id=...`，不会立即调用 `mission_gateway`。确认执行：

```bash
curl -X POST http://127.0.0.1:8000/api/voice/confirm_command \
  -H 'Content-Type: application/json' \
  -d '{"pending_command_id":"voice_pending_xxx","confirmed":true,"requested_by":"operator"}'
```

取消执行：

```bash
curl -X POST http://127.0.0.1:8000/api/voice/confirm_command \
  -H 'Content-Type: application/json' \
  -d '{"pending_command_id":"voice_pending_xxx","confirmed":false,"requested_by":"operator"}'
```

音频上传和录音接口也支持可选 LLM：`/api/voice/audio_command` 的 multipart 字段可带 `use_llm=true`，`/api/voice/record_command` 的 JSON 可带 `"use_llm": true`。


## 项目目的

本项目用于把 RK3588 做成 RoboMaster 车载系统的交互与状态中台。

基础系统最初完成 Phase 2 的核心目标：

- 保留 Phase 1 的 mock 中台能力
- 接入 `NUC -> RK3588` 的真实状态上送
- 接入 `RK3588 -> NUC` 的 mission bridge
- 让 Dashboard 通过 REST / WebSocket 观察 mock 与 real 两种模式

后续 Phase 4 / Phase 5 已在此基础上增加语音入口、RKNN YOLO26 视觉检测、USB 摄像头抽帧检测、最新检测图片接口与 Dashboard 展示。Phase 7 在语音规则解析之后增加可选 DeepSeek V4 语义解析 fallback；当前仍不做 OpenClaw、视频流或 YOLO 直接控制底盘。

## 手动开发启动（不用脚本时）

正常现场启动优先使用本文开头的 `scripts/start_*.sh`。下面命令只用于手动开发、临时排障或不想使用脚本时。

### 后端

默认使用系统 Python 启动后端，不要先 `source /home/robomaster/funasr_test/.venv/bin/activate`。该 venv 只包含 FunASR 相关依赖，未安装 `uvicorn` 等后端 Web 依赖。

```bash
cd /home/robomaster/QHXD/backend
python3 -m pip install -r requirements.txt
ASR_BACKEND=mock python3 -m uvicorn app.main:app --host 0.0.0.0 --port 8000
```

如果你的 shell 已经进入 `(.venv)`，先退出：

```bash
deactivate
```

最小检查：

```bash
curl http://127.0.0.1:8000/health
curl http://127.0.0.1:8000/api/state/latest
```

数据库默认写入：

```text
backend/data/rk3588_phase1.db
```

### 前端

前端也不需要进入 Python venv。另开一个终端执行：

```bash
cd /home/robomaster/QHXD/frontend
npm install
npm run dev -- --host 0.0.0.0 --port 5173
```

打开：

```text
http://127.0.0.1:5173
```

开发态默认把 `/api` 和 `/ws` 代理到 `http://127.0.0.1:8000`。

## 如何使用 Mock 模式

默认启动后即可直接使用 mock 模式。

在 mock 模式下：

- 状态来自 [backend/app/services/mock_state.py](/home/robomaster/QHXD/backend/app/services/mock_state.py)
- 页面会显示 `MOCK`
- mission 接口走本地 mock 流程
- WebSocket 会持续推送本地生成的状态

手工切回 mock：

```bash
curl -X POST http://127.0.0.1:8000/api/system/mode/switch \
  -H 'Content-Type: application/json' \
  -d '{"mode":"mock","source":"manual-check","requested_by":"operator"}'
```

## 如何使用 Real 模式

### 1. 正确启动 RK3588 后端

如果要桥接 NUC mission 服务，RK3588 后端必须带上正确的环境变量。

示例：

```bash
export NUC_BASE_URL=http://192.168.10.3:8090
export NUC_MISSION_PATH=/api/internal/rk3588/mission

cd backend
python3 -m uvicorn app.main:app --host 0.0.0.0 --port 8000
```

这一步非常关键。Round 3 / Round 4 联调中出现过：

- NUC 状态上送正常
- NUC mission 服务正常
- 但 RK3588 public mission API 返回 `accepted=false`

最终确认根因是：

- **RK3588 正式运行实例没有带着正确的 `NUC_BASE_URL` / `NUC_MISSION_PATH` 启动**

也就是说，这类问题优先检查 RK3588 启动配置，而不是先怀疑 NUC 功能缺失。

### 2. 切换到 real 模式

```bash
curl -X POST http://127.0.0.1:8000/api/system/mode/switch \
  -H 'Content-Type: application/json' \
  -d '{"mode":"real","source":"manual-check","requested_by":"operator"}'
```

切到 real 后，如果还没收到 NUC 首包，页面和状态会显示：

- `system_mode.mode=real`
- `device_status.online=false`
- `device_status.fault_code=waiting-for-real-state`

### 3. 确认 NUC 接口直连正常

先从 RK3588 直接打一次 NUC mission 服务：

```bash
curl --noproxy '*' -X POST http://192.168.10.3:8090/api/internal/rk3588/mission \
  -H 'Content-Type: application/json' \
  -d '{"command":"go_to_waypoint","source":"rk3588-direct-check","requested_by":"operator","payload":{"waypoint_id":"wp-check-001"}}'
```

如果这里成功，再测试 RK3588 public mission API：

```bash
curl -X POST http://127.0.0.1:8000/api/mission/go_to_waypoint \
  -H 'Content-Type: application/json' \
  -d '{"waypoint_id":"wp-check-001","source":"manual-check","requested_by":"operator"}'
```

### 4. NUC 状态上送入口

NUC 的真实状态通过这个接口进入 RK3588：

```text
POST /api/internal/nuc/state
```

进入后会写入共享状态，再通过：

- `GET /api/state/latest`
- `GET /api/tasks/current`
- `WS /ws/state`
- Dashboard

统一对外可见。

### 5. NUC IMU 调试入口

为了配合当前 C 板只能稳定提供 IMU 的联调阶段，RK3588 还提供了一个最小 IMU 专项链路：

```text
POST /api/internal/nuc/imu
GET /api/imu/latest
WS /ws/imu
```

说明：

- 这条链路不改已有 `POST /api/internal/nuc/state` 契约
- 适合 NUC 先把真实 IMU 样本独立送到 RK3588 做专项验收
- 前端 Dashboard 已增加最小 IMU 调试卡片

## NUC 适配器接入点

当前 NUC 相关逻辑主要在这些文件：

- [backend/app/services/nuc_adapter.py](/home/robomaster/QHXD/backend/app/services/nuc_adapter.py)
- [backend/app/services/state_store.py](/home/robomaster/QHXD/backend/app/services/state_store.py)
- [backend/app/services/mission_gateway.py](/home/robomaster/QHXD/backend/app/services/mission_gateway.py)
- [backend/app/services/mode_manager.py](/home/robomaster/QHXD/backend/app/services/mode_manager.py)

职责分工：

- `nuc_adapter.py`
  负责 NUC 状态接入和 mission bridge
- `state_store.py`
  负责保存当前共享状态
- `mission_gateway.py`
  负责 mock / real 命令分流
- `mode_manager.py`
  负责模式切换、离线判定、恢复判定和 bridge 错误暴露


## Phase 4A 语音文本入口与视觉检测原型

### 文本命令入口

Phase 4A 新增了 RK3588 侧的文本任务入口，用于后续 ASR 前置调试。该入口不接入真实麦克风、ASR、LLM 或 OpenClaw，只做规则解析并复用现有 mission gateway。

```text
POST /api/voice/text_command
POST /api/voice/asr_text_mock
```

示例：

```bash
curl -X POST http://127.0.0.1:8000/api/voice/text_command \
  -H 'Content-Type: application/json' \
  -d '{"text":"去一号点","source":"text-debug","requested_by":"operator"}'
```

支持的第一版意图：

- `go_to_waypoint`：例如“去一号点”“去 201”“送到实验室”
- `start_patrol`：例如“开始巡检”
- `pause_task`：例如“暂停任务”
- `resume_task`：例如“继续任务”“恢复任务”
- `return_home`：例如“返回起点”“返航”“回家”
- `query_status`：例如“当前状态”“现在在哪”

目标点别名配置位于：

```text
backend/app/config/waypoints.json
```

未知文本或无法解析目标点时不会触发机器人任务。

### 本地视觉检测状态入口

Phase 4A 为后续 YOLO / RKNN 检测接入预留了可选 `detection_status`，后端启动不依赖 RKNN 环境。调试入口：

```text
POST /api/internal/perception/detection_status
```

示例：

```bash
curl -X POST http://127.0.0.1:8000/api/internal/perception/detection_status \
  -H 'Content-Type: application/json' \
  -d '{"detection_status":{"enabled":true,"source":"rk3588-rknn-yolo","model_name":"custom_delivery_yolo_rk3588.rknn","frame_id":"camera_front","timestamp":"2026-04-12T15:20:30Z","objects":[{"class_name":"person","confidence":0.86,"bbox_xyxy":[120,80,260,360]}],"events":[{"event_type":"person_detected","level":"info","message":"检测到人员目标"}]}}'
```

提交后可通过 `GET /api/state/latest` 和 `WS /ws/state` 观察 `detection_status`。Dashboard 会显示最小视觉检测状态卡片。

### FunASR 真实语音输入与板端录音验收

Phase 4B 语音模块已经形成两条入口，二者都会复用同一条安全链路：

```text
音频输入
-> ASR 得到 recognized_text
-> intent_parser / waypoint_resolver
-> voice_entry_service
-> mission_gateway
-> 返回 accepted / task_status
```

该链路不会绕过 `mission_gateway`，也不会在前端或 ASR 层直接控制底盘。

#### 支持的语音命令

当前规则解析支持以下第一版命令：

| 命令类别 | intent / command | 示例说法 | 行为 |
| --- | --- | --- | --- |
| 前往目标点 | `go_to_waypoint` | `去二零一实验室`、`去201`、`去一号点`、`送到实验室` | 解析目标点后提交导航任务 |
| 开始巡检 | `start_patrol` | `开始巡检` | 提交巡检任务 |
| 暂停任务 | `pause_task` | `暂停任务` | 暂停当前任务 |
| 继续任务 | `resume_task` | `继续任务`、`恢复任务` | 恢复当前任务 |
| 返回起点 | `return_home` | `返回起点`、`返航`、`回家` | 提交返航任务 |
| 查询状态 | `query_status` | `当前状态`、`现在在哪` | 查询当前状态，不发起新导航 |

未知命令、空识别文本、无法解析目标点的指令会返回 `accepted=false` 或 `intent=unknown`，不会触发 mission。

#### 目标点与别名

目标点别名配置位于：

```text
backend/app/config/waypoints.json
```

当前配置摘要：

| waypoint_id | 名称 | aliases |
| --- | --- | --- |
| `wp_201` | 二零一实验室 | `二零一实验室`、`201实验室`、`二零一`、`201` |
| `wp_001` | 一号点 | `一号点`、`1号点`、`1 号点`、`一号`、`201`、`实验室`、`送到实验室` |
| `wp_002` | 二号点 | `二号点`、`2号点`、`2 号点`、`二号`、`202` |
| `home` | 起点 | `起点`、`home`、`家` |

解析规则会按 `waypoints.json` 中的顺序匹配 `waypoint_id`、`name` 和 `aliases`。如果多个地点包含同一个别名，排在前面的地点优先生效。当前 `wp_201` 位于 `wp_001` 之前，因此“201”会优先解析为 `wp_201`。

#### mock backend 启动

默认 mock 模式不要求安装 FunASR，适合开发和接口自测：

```bash
export ASR_BACKEND=mock
export VOICE_MOCK_RECOGNIZED_TEXT=暂停任务
cd /home/robomaster/QHXD/backend
python3 -m uvicorn app.main:app --host 0.0.0.0 --port 8000
```

mock ASR 的推荐验收方式是按场景设置 `VOICE_MOCK_RECOGNIZED_TEXT`，例如已知命令设置为 `去二零一实验室`，未知命令设置为 `打开窗户`。这样 `/api/voice/audio_command` 和 `/api/voice/record_command` 都能得到稳定结果。

如果直接调用 ASR service 并传入原始文件路径，mock ASR 也保留了按文件名推断文本的调试映射：

| 文件名片段 | mock recognized_text |
| --- | --- |
| `cmd_201` | `去二零一实验室` |
| `pause_task` | `暂停任务` |
| `resume_task` | `继续任务` |
| `return_home` | `返回起点` |
| `start_patrol` | `开始巡检` |
| `unknown_command` | `打开窗户` |

注意：`/api/voice/audio_command` 会先把上传文件保存为后端临时文件，因此接口级 mock 验收不要依赖上传文件名推断，应该显式设置 `VOICE_MOCK_RECOGNIZED_TEXT`。

#### FunASR backend 启动

当前机器上 FunASR 安装在 `/home/robomaster/funasr_test/.venv`，但这个 venv 没有安装 `uvicorn` / FastAPI 后端依赖。因此不要 `source` 进入该 venv 后直接启动后端。

推荐方式是：使用系统 Python 启动后端，同时把 FunASR venv 的 `site-packages` 暴露给系统 Python：

```bash
deactivate 2>/dev/null || true

export ASR_BACKEND=funasr
export FUNASR_MODEL_PATH=/home/robomaster/.cache/modelscope/hub/models/iic/SenseVoiceSmall
export FUNASR_VAD_MODEL_PATH=/home/robomaster/.cache/modelscope/hub/models/iic/speech_fsmn_vad_zh-cn-16k-common-pytorch
export FUNASR_DEVICE=cpu
export FUNASR_LANGUAGE=zh
export FUNASR_USE_ITN=true
export FUNASR_DISABLE_UPDATE=true
export VOICE_MAX_AUDIO_SECONDS=10
export VOICE_MAX_UPLOAD_MB=20
export PYTHONPATH=/home/robomaster/funasr_test/.venv/lib/python3.10/site-packages

cd /home/robomaster/QHXD/backend
python3 -m uvicorn app.main:app --host 0.0.0.0 --port 8000
```

模型缓存行为：FunASR 模型在当前后端进程第一次音频识别请求时懒加载；首次返回的 `model_load_time_s` 是实际加载耗时。后续请求复用同一个 `AutoModel` 实例，`model_load_time_s=0.0`。如果重启后端进程，第一次请求会重新加载模型。

如果你坚持在 FunASR venv 内启动后端，需要先给该 venv 安装后端依赖：

```bash
source /home/robomaster/funasr_test/.venv/bin/activate
cd /home/robomaster/QHXD/backend
python -m pip install -r requirements.txt
python -m uvicorn app.main:app --host 0.0.0.0 --port 8000
```

#### `/api/voice/audio_command`：上传 wav 音频命令

```text
POST /api/voice/audio_command
Content-Type: multipart/form-data
```

用途：上传已有 `.wav` 文件，后端完成 ASR 并复用文本语音命令链路。

请求示例：

```bash
curl -X POST http://127.0.0.1:8000/api/voice/audio_command \
  -F "file=@/home/robomaster/QHXD/audio_test/cmd_201.wav" \
  -F "source=manual-audio-check" \
  -F "requested_by=operator"
```

常用测试样例：

```bash
# 已知命令：应解析为 go_to_waypoint / wp_201 / accepted=true
curl -X POST http://127.0.0.1:8000/api/voice/audio_command \
  -F "file=@/home/robomaster/QHXD/audio_test/cmd_201.wav" \
  -F "source=acceptance-audio-known" \
  -F "requested_by=operator"

# 未知命令：应返回 accepted=false 或 intent=unknown，且不触发 mission
curl -X POST http://127.0.0.1:8000/api/voice/audio_command \
  -F "file=@/home/robomaster/QHXD/audio_test/unknown_command.wav" \
  -F "source=acceptance-audio-unknown" \
  -F "requested_by=operator"
```

返回字段包括：

- `recognized_text` / `raw_text`
- `asr_backend`
- `asr_time_s`
- `model_load_time_s`
- `intent`
- `command`
- `payload`
- `waypoint_id`
- `accepted`
- `need_confirm`
- `detail`
- `error`
- `task_status`

上传限制由以下环境变量控制：

```bash
export VOICE_MAX_AUDIO_SECONDS=10
export VOICE_MAX_UPLOAD_MB=20
```

当前只接受 `.wav` 文件。超过大小或时长限制会返回错误，不会触发 mission。

#### `/api/voice/record_command`：RK3588 后端 USB 麦克风录音识别

```text
POST /api/voice/record_command
Content-Type: application/json
```

用途：前端或 curl 触发后端在 RK3588 板端调用 `arecord`，使用 USB 麦克风录音，然后走 FunASR / mock ASR 和同一条任务解析链路。本接口不是浏览器麦克风录音。

录音配置环境变量：

```bash
export AUDIO_DEVICE=plughw:CARD=Device,DEV=0
export AUDIO_SAMPLE_RATE=16000
export AUDIO_CHANNELS=1
export AUDIO_FORMAT=S16_LE
export AUDIO_RECORD_SECONDS=3
export VOICE_RECORD_DIR=/home/robomaster/QHXD/backend/data/voice_records
export VOICE_KEEP_RECORDINGS=true
```

字段说明：

- `AUDIO_DEVICE`：`arecord -D` 使用的输入设备，当前 USB 麦克风验收值为 `plughw:CARD=Device,DEV=0`。
- `AUDIO_SAMPLE_RATE`：采样率，默认 `16000`。
- `AUDIO_CHANNELS`：通道数，默认 `1`。
- `AUDIO_FORMAT`：采样格式，默认 `S16_LE`。
- `AUDIO_RECORD_SECONDS`：请求不传 `duration` 时使用的默认录音秒数。
- `VOICE_RECORD_DIR`：临时/保留 wav 文件目录。
- `VOICE_KEEP_RECORDINGS`：请求不传 `keep_audio` 时是否保留录音文件。

请求示例：

```bash
curl -X POST http://127.0.0.1:8000/api/voice/record_command \
  -H "Content-Type: application/json" \
  -d '{"duration":3,"source":"rk3588-usb-mic","requested_by":"operator","keep_audio":true}'
```

前端 Dashboard 的“语音任务入口”按钮使用的请求体：

```json
{
  "duration": 3,
  "source": "dashboard-record-button",
  "requested_by": "operator",
  "keep_audio": true
}
```

接口内部等价于：

```bash
arecord -D "$AUDIO_DEVICE" -r "$AUDIO_SAMPLE_RATE" -c "$AUDIO_CHANNELS" -f "$AUDIO_FORMAT" -d 3 output.wav
```

`record_command` 返回字段包含 `audio_command` 的全部语义字段，并额外包含：

- `audio_path`
- `duration`
- `audio_device`
- `audio_retained`

#### `voice_records` 目录行为

`record_command` 会在 `VOICE_RECORD_DIR` 下创建唯一 wav 文件，文件名形如：

```text
voice_YYYYMMDD_HHMMSS_mmm_<uuid8>.wav
```

行为规则：

- `keep_audio=true`：识别完成后保留 wav，返回真实 `audio_path` 和 `audio_retained=true`。
- `keep_audio=false`：识别完成后删除 wav，返回 `audio_path=null` 和 `audio_retained=false`。
- 录音失败、设备错误、空文件等情况返回 `success=false`，不会调用 mission。
- 目录不存在时后端会按需创建。

错误设备验证：

```bash
AUDIO_DEVICE=plughw:CARD=WrongDevice,DEV=0 curl -X POST http://127.0.0.1:8000/api/voice/record_command \
  -H "Content-Type: application/json" \
  -d '{"duration":3,"source":"wrong-device-check","requested_by":"operator","keep_audio":false}'
```

预期返回 `success=false`、`error=audio_record_failed`，且不会调用 ASR 或触发 mission。

#### 前端入口

Dashboard 已提供“语音任务入口”卡片：

- 点击“开始板端录音识别”后调用 `/api/voice/record_command`。
- 请求中按钮 disabled，并提示“正在录音并识别，请说话...”。
- 返回后显示 `recognized_text`、`intent`、`command`、`waypoint_id`、`accepted`、`detail`、`asr_backend`、`asr_time_s`、`model_load_time_s`、`audio_path` 和 `task_status`。
- 未知命令显示“未识别到可执行任务命令”，不会显示为任务执行成功。

#### 已知限制

Phase 4B 到此只完成“点击/上传 -> 离线识别 -> 规则意图 -> mission_gateway”的验收链路，明确不包含：

- 无唤醒词。
- 无流式 ASR。
- 无浏览器麦克风录音，网页按钮触发的是 RK3588 后端 USB 麦克风录音。
- 无多轮语音对话。
- 无 LLM 自由任务规划。
- 无 OpenClaw。
- 无语音直接控制电机。
- 不改变现有 mission 行为。

#### Phase 4B 手工验收清单

后端启动：

```bash
cd /home/robomaster/QHXD/backend
ASR_BACKEND=mock VOICE_MOCK_RECOGNIZED_TEXT=去二零一实验室 python3 -m uvicorn app.main:app --host 127.0.0.1 --port 8000
```

未知命令验收时，把 `VOICE_MOCK_RECOGNIZED_TEXT` 改为 `打开窗户` 后重新启动后端。

- [ ] `GET /api/state/latest` 返回 `success=true`。
- [ ] `/api/voice/audio_command` 上传任意有效测试 wav 后，已知命令场景返回 `recognized_text` 包含 `201` 或 `二零一`。
- [ ] `/api/voice/audio_command` 已知命令场景返回 `intent=go_to_waypoint`、`waypoint_id=wp_201`、`accepted=true`。
- [ ] `/api/voice/audio_command` 未知命令场景返回 `accepted=false` 或 `intent=unknown`，不触发 mission。
- [ ] `/api/voice/record_command` 使用 `AUDIO_DEVICE=plughw:CARD=Device,DEV=0` 能完成板端录音并返回识别结果。
- [ ] `/api/voice/record_command` 请求中 `keep_audio=false` 时录音文件会被删除，返回 `audio_path=null`。
- [ ] 错误 `AUDIO_DEVICE` 会返回 `audio_record_failed`，页面/接口不崩溃。
- [ ] Dashboard 出现“语音任务入口”卡片，点击按钮会调用 `/api/voice/record_command`。
- [ ] Dashboard 请求中按钮 disabled，结束后恢复可点击。
- [ ] Dashboard 对未知命令显示“未识别到可执行任务命令”。
- [ ] FunASR 模式下，第一次请求 `model_load_time_s>0`，同一后端进程后续请求 `model_load_time_s=0.0`。
- [ ] 原有 Dashboard 状态显示、mission 按钮、文本命令入口不受影响。

#### 常见问题

1. `ASR_BACKEND=mock` 但返回空文本
   设置 `VOICE_MOCK_RECOGNIZED_TEXT`；接口级 mock 验收不要依赖上传文件名推断。

2. `ASR_BACKEND=funasr` 提示未安装 FunASR
   确认启动前设置了 `PYTHONPATH=/home/robomaster/funasr_test/.venv/lib/python3.10/site-packages`，或把 FunASR 安装到当前 Python 环境。

3. 模型路径错误
   检查 `FUNASR_MODEL_PATH` 和 `FUNASR_VAD_MODEL_PATH` 是否为本机已存在目录。

4. 音频格式错误
   目前只允许 `.wav`，并限制大小和时长。默认 `VOICE_MAX_UPLOAD_MB=20`、`VOICE_MAX_AUDIO_SECONDS=10`。

5. 识别为空或未知命令
   不会触发 mission，返回 `accepted=false` / `need_confirm=true`，并写入语音命令日志。

### RKNN YOLO26 本地推理接入

Phase 4C 的 RKNN YOLO26 单图推理入口位于：

```text
experiments/rknn_yolo/
```

当前验收模型、标签与样例路径：

```text
experiments/rknn_yolo/models/yolo26n_fp32.rknn
experiments/rknn_yolo/models/labels.txt
experiments/rknn_yolo/samples/test.jpg
```

当前已验证推理配置：

```text
输入尺寸：640x640
输入格式：RGB
输入 layout：NHWC
输入 dtype：float32
输入范围：0.0 ~ 1.0
输出 shape：(1, 300, 6)
推荐输出 layout：xyxy_score_class
```

推荐运行单图推理并输出 `detection_status`：

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

`infer_image.py` 会在 OpenCV 分支和 Pillow fallback 分支统一执行 RGB、NHWC、`float32 / 255.0`、640x640 预处理。需要诊断输入时增加 `--debug-raw`，stderr 会打印 `input_tensor shape/dtype/min/max`，stdout 仍保持纯 JSON。

`models/labels.txt` 必须与导出 ONNX / RKNN 的模型类别顺序一致。COCO 80 类 labels 只适用于 COCO 预训练模型；自训练 `best.pt` 必须从同一个模型或训练配置导出 labels。labels 错误通常只影响类别名，不应导致框位置整体错乱。

输出 JSON 可提交给后端状态流：

```bash
curl -X POST http://127.0.0.1:8000/api/internal/perception/detection_status \
  -H "Content-Type: application/json" \
  -d @outputs/detection_status_fixed_preprocess.json
```

提交后可通过 `GET /api/state/latest`、`WS /ws/state` 和 Dashboard “视觉检测状态”卡片观察。YOLO 结果只更新 `detection_status`，不直接控制底盘、导航或 mission。

更详细的 labels 生成方法、调试命令和人工验收清单见 `experiments/rknn_yolo/README.md`。

### RKNN YOLO26 摄像头连续检测

Phase 4D 新增连续检测脚本：

```text
experiments/rknn_yolo/camera_detect_service.py
```

dry-run：

```bash
cd /home/robomaster/QHXD/experiments/rknn_yolo
python3 camera_detect_service.py \
  --model models/yolo26n_fp32.rknn \
  --labels models/labels.txt \
  --camera /dev/qhxd-usb-camera \
  --fps 1 \
  --dry-run \
  --save-latest outputs/latest_camera_detection.jpg
```

提交后端：

```bash
python3 camera_detect_service.py \
  --model models/yolo26n_fp32.rknn \
  --labels models/labels.txt \
  --camera /dev/qhxd-usb-camera \
  --fps 1 \
  --backend-url http://127.0.0.1:8000 \
  --submit \
  --save-latest outputs/latest_camera_detection.jpg
```

查看 USB 摄像头设备用 `ls /dev/video*`、`ls -l /dev/qhxd-usb-camera` 和 `lsusb`。USB 入口默认使用 `/dev/qhxd-usb-camera` 这个 udev 稳定别名，不再死查找 `/dev/video0`；OpenCV 打不开时才 fallback 到 ffmpeg。首次部署或更换 USB 摄像头后，运行 `./scripts/setup_usb_camera_alias.sh` 生成/更新该别名。Hikrobot 相机入口已接入 MVS SDK，可通过 `camera_backend=hik` 或 `camera_config_hik.example.json` 切换；USB 入口仍保留，`camera_config.json` 默认仍为 `camera_backend=usb`。Phase 4D 阶段只更新 `detection_status`；Phase 4D_2 后 Dashboard 会显示最新识别图片，但仍不做 WebRTC / RTSP / MJPEG 真视频流。YOLO 结果不直接控制底盘或 mission。




### RKNN YOLO26 识别图像流

Phase 4D_2 使用“最新识别图片”方案，不做 WebRTC / RTSP / MJPEG。YOLO 服务保存：

```text
experiments/rknn_yolo/outputs/latest_camera_detection.jpg
```

后端提供：

```http
GET /api/perception/latest_frame
```

MJPEG JPEG bytes 流接口：

```http
GET /api/perception/frame_stream
```

前端默认用 `<img src="/api/perception/frame_stream">` 显示连续 JPEG bytes；如果流接口异常，会回退到 `latest_frame` 轮询。

推荐启动优先使用本文开头的快捷脚本：`./scripts/start_backend.sh`、`./scripts/start_frontend.sh`、`./scripts/start_yolo_camera.sh` 或 `./scripts/start_yolo_hik_camera.sh`。

Dashboard 的视觉检测卡片默认显示 `/api/perception/frame_stream` MJPEG 图像流；如果 MJPEG 关闭或异常，会回退到 `/api/perception/latest_frame?t=...` 轮询。同时保留 detection_status 的 objects / events 显示。YOLO 采集与提交频率由 `camera_config*.json` 的 `fps` 控制，详见本文前面的“相机采集、YOLO 处理与前端刷新频率”。更完整的配置和排障说明见 `experiments/rknn_yolo/README.md`。

### Hikrobot 相机入口

Hik 相机作为可选采集后端接入在：

```text
experiments/rknn_yolo/hik_camera_source.py
experiments/rknn_yolo/camera_detect_service.py
experiments/rknn_yolo/camera_config_hik.example.json
```

Dashboard 的 `/api/perception/latest_frame` 会自动选择 USB/Hik 两个 latest 输出中更新时间最新的一张；超过 `PERCEPTION_LATEST_FRAME_MAX_AGE_SECONDS`（默认 10 秒）未更新时返回 `latest_frame_stale`，避免前端显示旧图。

USB 与 Hik 的切换只影响采集层，不改变 RKNN 推理、`detection_status`、后端 state_store、Dashboard 或 mission 行为。当前测试记录：Hik 设备已被识别为 `2bdf:0001 Hikrobot MV-CS020-10UC`，MVS SDK 标签为 `USB MV-CS020-10UC DA3860587`；已验证可枚举、打开、start grabbing、读取 RGB 帧，并可作为 YOLO 图像源生成 `outputs/latest_hik_detection.jpg`。`camera_config_hik.example.json` 默认不绑定 serial，会打开第 1 台枚举到的 Hik 相机；如果现场有多台 Hik 相机，可把 `hik_serial` 设置为目标序列号。

Hik dry-run：

```bash
cd /home/robomaster/QHXD/experiments/rknn_yolo
python3 camera_detect_service.py --config camera_config_hik.example.json --dry-run --max-frames 2 --read-fail-limit 2
```

USB 默认入口：

```bash
cd /home/robomaster/QHXD/experiments/rknn_yolo
python3 camera_detect_service.py --config camera_config.json
```

## 开发调试说明

### 状态流

mock 模式：

```text
mock_state_service.tick()
-> state_store
-> REST / WS / Dashboard
```

real 模式：

```text
NUC
-> POST /api/internal/nuc/state
-> nuc_adapter
-> state_store
-> REST / WS / Dashboard
```

### 命令流

mock 模式：

```text
Frontend
-> /api/mission/*
-> mission_gateway
-> mock_state_service
-> state_store
-> REST / WS / Dashboard
```

real 模式：

```text
Frontend
-> /api/mission/*
-> mission_gateway
-> nuc_adapter.forward_mission_command()
-> NUC /api/internal/rk3588/mission
-> NUC 状态回传 /api/internal/nuc/state
-> state_store
-> REST / WS / Dashboard
```

### 常见故障点

1. `real` 模式下命令返回 `accepted=false`
   先检查 RK3588 是否用正确的 `NUC_BASE_URL` / `NUC_MISSION_PATH` 启动。

2. 页面一直显示“等待 NUC”
   说明已经切到 `real`，但 NUC 还没有向 `/api/internal/nuc/state` 发首包。

3. 页面显示 `nuc-state-timeout`
   说明 NUC 实时状态上送超过超时阈值未更新。

4. 页面显示 `nuc-bridge-unreachable`
   说明 RK3588 调 NUC mission 服务失败，优先查 NUC 监听地址、端口和 RK3588 启动配置。

5. RK3588 直连 NUC 失败
   先在 NUC 上确认 mission 服务是否真的监听在 `0.0.0.0:8090` 或 `192.168.10.3:8090`。

## 最小验证

### 后端自检

当前最小 `unittest` 已覆盖：

- `GET /health`
- 一个 mission endpoint：`go_to_waypoint`
- 模式切换：`POST /api/system/mode/switch`
- real 模式下命令转发与失败返回

运行方式：

```bash
cd backend
python3 -m unittest discover -s tests -v
```

### 手工检查

1. 健康检查：

```bash
curl http://127.0.0.1:8000/health
```

2. 模式切换：

```bash
curl -X POST http://127.0.0.1:8000/api/system/mode/switch \
  -H 'Content-Type: application/json' \
  -d '{"mode":"mock","source":"manual-check","requested_by":"operator"}'
```

```bash
curl -X POST http://127.0.0.1:8000/api/system/mode/switch \
  -H 'Content-Type: application/json' \
  -d '{"mode":"real","source":"manual-check","requested_by":"operator"}'
```

3. 一个 mission 命令：

```bash
curl -X POST http://127.0.0.1:8000/api/mission/go_to_waypoint \
  -H 'Content-Type: application/json' \
  -d '{"waypoint_id":"wp-demo-001","source":"manual-check","requested_by":"operator"}'
```

4. 前端观察点：

- 页面能显示 `MOCK / REAL`
- mock / real 切换后状态变化可见
- real 模式下能看到“等待 NUC / 在线 / 超时 / bridge 异常”等状态

## 当前交接状态

Phase 2 已达到可交接、可验收状态：

- 后端与前端可启动
- mock / real 两种模式都可发现、可测试
- NUC 状态上送与 mission bridge 已打通
- Dashboard 能观察到命令和状态反馈闭环
- 最小自检和手工复验路径已经写入本 README

## Phase 5：语音与视觉工程收口

Phase 5 将 Phase 4 已跑通的语音与视觉能力整理为更适合现场演示和交接的工程模块。本阶段不改变 mission、NUC bridge、RT-Thread 控制语义，也不会让 YOLO 结果直接控制底盘。

### 统一启动脚本

统一启动脚本已整理到本文开头的“快捷启动”。Phase 5 保留的工程约定是：后端默认 `8000`、前端默认 `5173`、YOLO 默认配置 `experiments/rknn_yolo/camera_config.json`、pid 在 `.runtime/`、日志在 `logs/`。如果服务已经由其他方式启动，脚本会尽量识别端口可用状态并输出提示。

### YOLO 调试帧保存

`camera_detect_service.py` 新增调试帧参数，默认关闭，不会占用磁盘：

```bash
cd /home/robomaster/QHXD/experiments/rknn_yolo

python3 camera_detect_service.py \
  --config camera_config.json \
  --dry-run \
  --max-frames 2 \
  --save-debug-frames \
  --debug-frame-dir outputs/debug_frames_phase5 \
  --debug-every-n 1
```

启用后，每个保存周期会生成：

- `frame_000001_input.jpg`：送入 YOLO 前的原始输入帧；
- `frame_000001_output.jpg`：当前帧检测框可视化；
- `frame_000001_detection.json`：当前帧目标、display status 和 pipeline stats。

每帧 stderr 日志会输出：

```text
frame=1 raw=299 conf=0 nms=0 final=0 top=none
```

字段含义：

- `raw`：RKNN 输出中可解析的原始候选行数量；
- `conf`：通过置信度阈值的候选数量；
- `nms`：NMS 后数量；
- `final`：受 `--max-det` 限制后的最终当前帧检测数量；
- `top`：当前帧最高置信度类别摘要。

预处理链路保持 Phase 4C 已验证配置：`RGB + NHWC + float32 / 255.0 + 640x640`，推荐输出布局仍为 `xyxy_score_class`。

### 短时保持与防闪烁

摄像头服务新增显示层短时保持，默认配置在 `experiments/rknn_yolo/camera_config.json`：

```json
{
  "hold_seconds": 2.0,
  "hold_classes": ["person", "obstacle"]
}
```

短时保持只影响 `detection_status` 展示和 Dashboard 稳定性，不参与底盘控制。`detection_status.objects` 中会带上可选字段：

- `current_frame=true`：当前帧直接检测到；
- `recently_seen=true`：当前帧漏检，但仍在短时保持窗口内；
- `last_seen_at`：上次直接检测到的时间；
- `age_s`：距离上次检测到的秒数。

Dashboard 会分开显示“当前检测”和“最近检测”，避免把短时保持目标误认为当前帧直接检测。

### 视觉事件策略

保留事件类型：

- `person_detected`
- `obstacle_detected`
- `possible_blockage`

可配置项：

```json
{
  "event_min_confidence": 0.25,
  "event_min_area_ratio": 0.001,
  "blockage_frames_required": 3,
  "person_event_interval": 5.0,
  "obstacle_event_interval": 5.0,
  "blockage_event_interval": 10.0
}
```

含义：

- 低于 `event_min_confidence` 的目标不触发视觉事件；
- 面积过小的 obstacle 类目标不触发 `obstacle_detected`；
- 障碍连续出现达到 `blockage_frames_required` 后才触发 `possible_blockage`；
- 同类事件按 interval 节流，避免每帧刷屏。

### 语音命令词表与安全边界

第一版命令词表记录在：

```text
backend/app/config/voice_commands.json
```

支持意图：

- `go_to_waypoint`
- `pause_task`
- `resume_task`
- `return_home`
- `start_patrol`
- `query_status`

安全边界：

- 未知命令不触发 mission；
- ASR 失败或空文本不触发 mission；
- 目标点无法解析不触发 mission；
- 目标点存在歧义不触发 mission，例如当前 `去201` 会同时命中 `wp_201` 和 `wp_001`，因此被拒绝；
- `去二零一实验室` 会按最长 alias 匹配到 `wp_201`。

测试示例：

```bash
curl -X POST http://127.0.0.1:8000/api/voice/text_command \
  -H "Content-Type: application/json" \
  -d '{"text":"去二零一实验室","source":"manual-test","requested_by":"operator"}'

curl -X POST http://127.0.0.1:8000/api/voice/text_command \
  -H "Content-Type: application/json" \
  -d '{"text":"去201","source":"manual-test","requested_by":"operator"}'
```

### voice_records 清理

录音目录默认位于：

```text
backend/data/voice_records/
```

新增清理脚本，默认 dry-run：

```bash
./scripts/cleanup_voice_records.sh

# 删除 7 天前的 wav
./scripts/cleanup_voice_records.sh --delete

# 删除 3 天前的 wav
DAYS=3 ./scripts/cleanup_voice_records.sh --delete
```

### Phase 5 不包含

本阶段仍不做：

- 长时间稳定性测试；
- systemd 服务化或开机自启；
- Hik SDK 正式接入；
- OpenClaw / LLM 多轮对话；
- 浏览器麦克风录音；
- MJPEG / RTSP / WebRTC 视频流；
- YOLO 结果直接控制底盘；
- 重新训练模型、重新导出 ONNX、重新转换 RKNN 或 INT8 量化。
