# RK3588 Middleware Phase 2

## 项目目的

本项目用于把 RK3588 做成 RoboMaster 车载系统的交互与状态中台。

当前已完成 Phase 2 的核心目标：

- 保留 Phase 1 的 mock 中台能力
- 接入 `NUC -> RK3588` 的真实状态上送
- 接入 `RK3588 -> NUC` 的 mission bridge
- 让 Dashboard 通过 REST / WebSocket 观察 mock 与 real 两种模式

当前范围仍然只覆盖 Phase 2：

- 不接 RT-Thread 直连
- 不做语音、图传、视觉增强能力
- 不扩展到多页面复杂前端

## 快速运行

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

### FunASR 真实语音输入

Phase 4B 新增真实 wav 音频命令入口：

```text
POST /api/voice/audio_command
Content-Type: multipart/form-data
```

该接口只负责“音频 -> 文本 -> 复用现有 text command 链路”，不会直接控制底盘，也不会绕过 `mission_gateway`。

#### mock backend 启动

默认 mock 模式不要求安装 FunASR，适合开发和接口自测：

```bash
export ASR_BACKEND=mock
export VOICE_MOCK_RECOGNIZED_TEXT=暂停任务
cd backend
python3 -m uvicorn app.main:app --host 0.0.0.0 --port 8000
```

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

FunASR 模型会在第一次音频识别请求时懒加载一次，后续请求复用同一个 `AutoModel` 实例。

如果你坚持在 FunASR venv 内启动后端，需要先给该 venv 安装后端依赖：

```bash
source /home/robomaster/funasr_test/.venv/bin/activate
cd /home/robomaster/QHXD/backend
python -m pip install -r requirements.txt
python -m uvicorn app.main:app --host 0.0.0.0 --port 8000
```

#### 板端 USB 麦克风录音识别

Phase 4B-1 新增 RK3588 后端直接录音接口：

```text
POST /api/voice/record_command
Content-Type: application/json
```

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

请求示例：

```bash
curl -X POST http://127.0.0.1:8000/api/voice/record_command \
  -H "Content-Type: application/json" \
  -d '{"duration":3,"source":"rk3588-usb-mic","requested_by":"operator","keep_audio":true}'
```

字段说明：

- `duration`：录音秒数，范围 `1..10`，不传时使用 `AUDIO_RECORD_SECONDS`。
- `source`：任务来源，默认 `rk3588-record-command`。
- `requested_by`：发起人，默认 `operator`。
- `keep_audio`：是否保留录音文件；不传时使用 `VOICE_KEEP_RECORDINGS`。

接口内部等价于：

```bash
arecord -D "$AUDIO_DEVICE" -r "$AUDIO_SAMPLE_RATE" -c "$AUDIO_CHANNELS" -f "$AUDIO_FORMAT" -d 3 output.wav
```

返回中会比 `audio_command` 多出：

- `audio_path`
- `duration`
- `audio_device`
- `audio_retained`

如果 `keep_audio=false`，识别完成后会删除录音文件，并返回 `audio_path=null`、`audio_retained=false`。

错误设备验证：

```bash
AUDIO_DEVICE=plughw:CARD=WrongDevice,DEV=0 curl -X POST http://127.0.0.1:8000/api/voice/record_command \
  -H "Content-Type: application/json" \
  -d '{"duration":3,"source":"wrong-device-check","requested_by":"operator","keep_audio":false}'
```

预期返回 `success=false`、`error=audio_record_failed`，且不会调用 ASR 或触发 mission。

#### curl 上传 wav

```bash
curl -X POST http://127.0.0.1:8000/api/voice/audio_command \
  -F "file=@/home/robomaster/QHXD/audio_test/cmd_201.wav" \
  -F "source=manual-audio-check" \
  -F "requested_by=operator"
```

返回中会包含：

- `recognized_text`
- `asr_backend`
- `asr_time_s`
- `intent`
- `command`
- `waypoint_id`
- `accepted`
- `need_confirm`
- `detail`

#### 常见问题

1. `ASR_BACKEND=mock` 但返回空文本
   设置 `VOICE_MOCK_RECOGNIZED_TEXT`，或使用文件名包含 `cmd_201`、`pause_task`、`resume_task`、`return_home`、`start_patrol`、`unknown_command` 的 wav。

2. `ASR_BACKEND=funasr` 提示未安装 FunASR
   确认启动前设置了 `PYTHONPATH=/home/robomaster/funasr_test/.venv/lib/python3.10/site-packages`，或把 FunASR 安装到当前 Python 环境。

3. 模型路径错误
   检查 `FUNASR_MODEL_PATH` 和 `FUNASR_VAD_MODEL_PATH` 是否为本机已存在目录。

4. 音频格式错误
   目前只允许 `.wav`，并限制大小和时长。默认 `VOICE_MAX_UPLOAD_MB=20`、`VOICE_MAX_AUDIO_SECONDS=10`。

5. 识别为空或未知命令
   不会触发 mission，返回 `accepted=false` / `need_confirm=true`，并写入语音命令日志。

### RKNN YOLO 独立实验

RKNN 推理原型位于：

```text
experiments/rknn_yolo/
```

该目录只提交脚本、说明和占位文件，不提交 `.pt`、`.onnx`、`.rknn` 等模型文件。将外部训练并转换好的 `.rknn` 放到 `experiments/rknn_yolo/models/` 后，可运行：

```bash
cd experiments/rknn_yolo
python3 infer_image.py \
  --model models/custom_delivery_yolo_rk3588.rknn \
  --image samples/test.jpg \
  --labels labels.txt \
  --conf 0.25 \
  --format detection_status
```

缺模型、缺图片或缺 RKNN Runtime 时，脚本会输出明确错误，不影响主后端。

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
