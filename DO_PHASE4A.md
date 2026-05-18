# DO_PHASE4A.md

## Phase 4A：RK3588 语音任务入口与本地 YOLO / RKNN 感知原型阶段

## 1. 阶段定位

本阶段用于在现有 **NUC + RK3588 + RT-Thread** 三机协同架构基础上，提前推进两个后续具有迁移价值的智能模块：

1. **RK3588 语音 / 文本任务入口**
2. **RK3588 本地 YOLO / RKNN / NPU 视觉感知原型**

本阶段的目标不是替换现有 NUC 主导航，也不是开始做二维导航迁移，而是在不破坏当前主链路的前提下，将语音交互和视觉识别能力优先部署在 RK3588 上，避免后续系统向 RK3588 集中时出现大规模迁移成本。

当前主链路仍保持：

```text
Web / 语音 / YOLO 事件
        ↓
      RK3588
        ↓
mission bridge / state_store
        ↓
       NUC
        ↓
   RT-Thread
```

本阶段两个模块的原则：

- 语音只负责产生任务命令，不直接控制底盘；
- YOLO 只负责产生检测事件，不直接改变导航或底盘行为；
- 两者均作为 RK3588 侧的弱耦合模块接入现有中台；
- YOLO 模型允许在外部电脑、NUC 或服务器训练，RK3588 只负责加载和运行转换后的 `.rknn` 模型；
- 当前阶段不要求 RK3588 完成模型训练、ONNX 导出或 RKNN 转换，只预留模型目录、加载入口、推理入口和错误提示。

---

## 2. 本阶段目标

### 2.1 语音任务入口目标

在 RK3588 上实现一个可调试、可扩展的任务入口模块，先从文本命令开始，逐步预留 ASR 接入能力。

第一阶段不直接做真实麦克风语音识别，而是先实现：

```text
文本命令
    ↓
意图解析 intent_parser
    ↓
目标点映射 waypoint_resolver
    ↓
mission_gateway
    ↓
当前：转发给 NUC
未来：可切换到 RK3588 本地导航
```

### 2.2 YOLO 感知原型目标

在 RK3588 上建立本地 YOLO / RKNN / NPU 推理原型。由于 YOLO 模型通常需要在外部设备上完成训练、导出和 RKNN 转换，本阶段只在 RK3588 项目中完成以下内容：

1. 预留 `.rknn` 模型放置目录；
2. 明确模型命名规范与放置规范；
3. 编写 `.rknn` 模型加载和图片推理入口；
4. 在 RKNN Runtime / RKNN-Toolkit-Lite2 不存在时给出清晰错误；
5. 在模型文件缺失时给出清晰错误；
6. 将推理结果封装为 `detection_status`；
7. 后续再接入 state_store 和 Dashboard。

本阶段不在 RK3588 上训练 YOLO，不负责训练流程本身；允许使用外部训练并转换好的 `.rknn` 模型文件。

推荐模型流转流程：

```text
本地 / NUC / 服务器训练 YOLO
        ↓
得到 best.pt
        ↓
导出 best.onnx
        ↓
使用 RKNN-Toolkit2 转换为 .rknn
        ↓
复制 .rknn 到 RK3588 项目指定目录
        ↓
RK3588 使用 RKNN Runtime / RKNN-Toolkit-Lite2 推理
        ↓
输出 detection_status
        ↓
state_store / REST / WebSocket / Dashboard
```

---

## 3. 本阶段不做的内容

Phase 4A 明确不做以下内容：

- 不做二维导航迁移；
- 不把 Nav2 / SLAM 迁到 RK3588；
- 不做 OpenClaw 集成；
- 不做完整大模型多轮对话；
- 不在 RK3588 上训练 YOLO；
- 不在本阶段负责 `.pt -> .onnx -> .rknn` 的完整转换流水线；
- 不自动下载或提交大模型文件；
- 不做实时图传 / WebRTC / RTSP；
- 不让语音命令直接发送速度控制量；
- 不让 YOLO 检测结果直接控制底盘停车、转向或修改 costmap；
- 不重构现有 mission bridge、NUC bridge、RT-Thread 控制链路。

说明：

- “不训练 YOLO”指的是不把训练任务纳入 RK3588 项目代码和 Codex 当前任务；
- 你们可以在外部设备完成训练和 RKNN 转换，然后把 `.rknn` 模型放入 RK3588 项目的 `experiments/rknn_yolo/models/` 目录进行推理验证。

---

## 4. 语音任务入口任务清单

## 4.1 Voice Round 1：文本命令解析接口

### 目标

在 RK3588 后端新增文本命令入口，将自然语言文本解析为结构化任务命令，并复用已有 mission_gateway。

### 需要完成

新增接口：

```http
POST /api/voice/text_command
```

请求示例：

```json
{
  "text": "去一号点",
  "source": "text-debug",
  "requested_by": "operator"
}
```

返回示例：

```json
{
  "success": true,
  "data": {
    "accepted": true,
    "intent": "go_to_waypoint",
    "command": "go_to_waypoint",
    "payload": {
      "waypoint_id": "wp_001"
    },
    "confidence": 0.95,
    "need_confirm": false,
    "detail": "已解析为前往一号点任务"
  }
}
```

### 支持命令范围

| 用户表达示例 | intent | 行为 |
|---|---|---|
| 去一号点 / 去 201 / 送到实验室 | `go_to_waypoint` | 调用目标点任务 |
| 开始巡检 | `start_patrol` | 调用巡检任务 |
| 暂停任务 | `pause_task` | 暂停当前任务 |
| 继续任务 / 恢复任务 | `resume_task` | 恢复当前任务 |
| 返回起点 / 返航 / 回家 | `return_home` | 返回起点 |
| 当前状态 / 现在在哪 | `query_status` | 查询当前状态 |

### 实现要求

- 新增 `intent_parser`；
- 新增或配置 `waypoint_resolver`；
- waypoint 第一版可以写死或使用 JSON 配置文件；
- mission 类命令必须复用现有 `mission_gateway`；
- 未知命令不得触发机器人任务；
- 不接入麦克风、ASR、LLM 或 OpenClaw。

### 验收标准

- [ ] 后端服务可正常启动；
- [ ] 输入“去一号点”可解析为 `go_to_waypoint`，并得到 `waypoint_id`；
- [ ] 输入“暂停任务”可解析为 `pause_task`；
- [ ] 输入“返回起点”可解析为 `return_home`；
- [ ] 输入未知文本时，返回 `need_confirm=true` 或 `accepted=false`；
- [ ] mission 类命令走现有 mission bridge，而不是重复实现转发逻辑；
- [ ] 原有 mock / real 模式不被破坏。

---

## 4.2 Voice Round 2：Dashboard 文本命令卡片

### 目标

在 Dashboard 上增加最小文本命令入口，用于调试和演示语音任务链路的前置版本。

### 需要完成

在 Dashboard 增加一个简单卡片：

```text
语音/文本任务入口
[ 输入：去一号点              ] [发送]
解析结果：go_to_waypoint / wp_001
执行结果：accepted=true
```

### 实现要求

- 增加一个输入框；
- 增加一个发送按钮；
- 调用 `POST /api/voice/text_command`；
- 显示解析出的：
  - intent
  - command
  - waypoint_id
  - accepted
  - detail message
- 不重做 Dashboard UI；
- 不新增复杂页面；
- 不接入真实 ASR。

### 验收标准

- [ ] 前端可正常启动；
- [ ] 在页面输入“去一号点”后，能调用后端接口；
- [ ] 页面能显示解析结果；
- [ ] 页面能显示命令是否 accepted；
- [ ] 原有状态显示、mock/real 模式显示不受影响；
- [ ] 未知命令不会误触发任务。

---

## 4.3 Voice Round 3：ASR 占位接口

### 目标

为后续真实语音识别预留服务接口，但本阶段不接入真实 ASR 引擎。

### 需要完成

新增 ASR 抽象服务，例如：

```text
asr_service
```

新增占位接口：

```http
POST /api/voice/asr_text_mock
```

该接口仍然接收文本，并复用 `text_command` 流程。

### 实现要求

- 增加 ASR 服务抽象层；
- 增加 `asr_text_mock` 接口；
- 复用现有文本命令解析逻辑；
- 文档说明未来真实 ASR 的接入位置；
- 不引入 Whisper / FunASR / 在线 ASR 依赖；
- 不实现麦克风流式输入。

### 验收标准

- [ ] `text_command` 仍然正常；
- [ ] `asr_text_mock` 能复用同一套解析逻辑；
- [ ] 后端启动不依赖 ASR 环境；
- [ ] 文档中说明真实 ASR 的预留位置；
- [ ] 不影响 mission bridge。

---

## 5. YOLO / RKNN 感知原型任务清单

## 5.1 YOLO Round 1：RKNN 模型目录与推理加载入口

### 目标

在 RK3588 项目中预留本地 YOLO / RKNN 实验目录，建立 `.rknn` 模型放置规范和推理入口。此轮不负责训练、不负责模型转换、不下载模型，只负责把“模型放在哪里、如何加载、缺失时如何报错、如何运行单张图片推理”这条链路准备好。

### 需要完成

新增目录：

```text
experiments/rknn_yolo/
├── README.md
├── infer_image.py
├── detection_status_builder.py        # 可先占位，Round 2 再完善
├── models/
│   ├── .gitkeep
│   └── README.md
├── samples/
│   ├── .gitkeep
│   └── README.md
└── outputs/
    └── .gitkeep
```

其中：

```text
experiments/rknn_yolo/models/
```

用于后续放置外部训练并转换好的 `.rknn` 模型。

模型命名建议：

```text
experiments/rknn_yolo/models/yolov8n_rk3588_int8.rknn
experiments/rknn_yolo/models/yolo11n_rk3588_int8.rknn
experiments/rknn_yolo/models/custom_delivery_yolo_rk3588.rknn
```

### 模型流转说明

本阶段默认模型来自外部训练与转换：

```text
best.pt
  ↓ 导出
best.onnx
  ↓ RKNN-Toolkit2 转换
best.rknn
  ↓ 复制到 RK3588
experiments/rknn_yolo/models/custom_delivery_yolo_rk3588.rknn
```

### `infer_image.py` 要求

脚本参数：

```bash
python3 infer_image.py \
  --model models/custom_delivery_yolo_rk3588.rknn \
  --image samples/test.jpg \
  --labels labels.txt \
  --conf 0.25
```

必须检查：

- `--model` 文件是否存在；
- `--image` 文件是否存在；
- RKNN Runtime / RKNN-Toolkit-Lite2 是否可导入；
- 缺模型时提示用户将 `.rknn` 放入 `experiments/rknn_yolo/models/`；
- 缺 RKNN 环境时提示需要在 RK3588 设备端安装对应运行库；
- 推理失败时输出清晰错误，不影响主后端。

### 输出格式

推理成功时，输出结构化检测结果：

```json
{
  "timestamp": "2026-04-12T15:20:30Z",
  "objects": [
    {
      "class_name": "person",
      "confidence": 0.86,
      "bbox_xyxy": [120, 80, 260, 360]
    }
  ]
}
```

### 实现要求

- 独立实验，不接入主 backend；
- 支持图片输入；
- 摄像头输入可以预留，不强制实现；
- 不提交 `.rknn`、`.pt`、`.onnx` 等大模型文件；
- `models/` 目录只提交 `.gitkeep` 和 `README.md`；
- RKNN Runtime / RKNN Lite 不存在时，要给出清晰报错；
- 不修改 mission bridge；
- 不修改 state_store；
- 不修改 Dashboard。

### 验收标准

- [ ] `experiments/rknn_yolo/` 目录存在；
- [ ] `models/`、`samples/`、`outputs/` 目录存在；
- [ ] `models/README.md` 说明 `.rknn` 模型放置规范；
- [ ] `infer_image.py` 支持 `--model`、`--image`、`--labels`、`--conf` 参数；
- [ ] 模型缺失时有明确错误提示；
- [ ] 图片缺失时有明确错误提示；
- [ ] RKNN 环境缺失时有明确错误提示；
- [ ] 推理成功时能输出结构化检测结果；
- [ ] 不影响主后端启动；
- [ ] 不影响现有 RK3588 中台功能。

---

## 5.2 YOLO Round 2：封装 detection_status

### 目标

将 YOLO 检测结果整理成项目统一使用的 `detection_status` 结构，为后续接入 state_store 做准备。

### detection_status 示例

```json
{
  "detection_status": {
    "enabled": true,
    "source": "rk3588-rknn-yolo",
    "model_name": "custom_delivery_yolo_rk3588.rknn",
    "frame_id": "camera_front",
    "timestamp": "2026-04-12T15:20:30Z",
    "objects": [
      {
        "class_name": "person",
        "confidence": 0.86,
        "bbox_xyxy": [120, 80, 260, 360]
      }
    ],
    "events": [
      {
        "event_type": "person_detected",
        "level": "info",
        "message": "检测到人员目标"
      }
    ]
  }
}
```

### 事件规则

| 检测结果 | 事件 |
|---|---|
| person | `person_detected` |
| chair / backpack / suitcase 等 | `obstacle_detected` |
| 障碍连续出现 N 帧 | `possible_blockage` |

### 实现要求

- 完善 `detection_status_builder.py`；
- 输出字段包括：
  - enabled
  - source
  - model_name
  - frame_id
  - timestamp
  - objects
  - events
- 支持空检测结果；
- 仍然保持独立实验，不接入主 backend；
- 不引入视频流展示。

### 验收标准

- [ ] 实验脚本可输出 `detection_status` JSON；
- [ ] 无检测目标时能输出空 objects/events；
- [ ] 检测到 person 时能生成 `person_detected`；
- [ ] 检测到障碍类目标时能生成 `obstacle_detected`；
- [ ] 主后端行为不受影响。

---

## 5.3 YOLO Round 3：接入 RK3588 后端状态流

### 目标

将本地 YOLO 检测状态接入 RK3588 后端，使其可以通过 REST / WebSocket 对外展示。

### 需要完成

- 后端状态模型支持可选 `detection_status`；
- 新增本地感知服务接口；
- `state_store` 能保存最新 `detection_status`；
- `GET /api/state/latest` 返回 `detection_status`；
- `WS /ws/state` 推送 `detection_status`；
- 新增一个临时 debug endpoint，用于手工提交 sample detection_status。

建议 debug endpoint：

```http
POST /api/internal/perception/detection_status
```

### 实现要求

- 后端启动不依赖 RKNN 环境；
- RKNN YOLO 实验和主后端解耦；
- detection_status 缺失时，系统正常运行；
- 不做视频流；
- 不改 mission bridge。

### 验收标准

- [ ] 后端可正常启动；
- [ ] 可以手动提交 sample detection_status；
- [ ] `GET /api/state/latest` 能看到 detection_status；
- [ ] WebSocket 能推送 detection_status；
- [ ] 未提交 detection_status 时，状态结构仍然合法；
- [ ] mock / real 模式不被破坏。

---

## 5.4 YOLO Round 4：Dashboard 显示检测状态

### 目标

在 Dashboard 上增加一个最小视觉检测卡片，用于显示本地 YOLO 感知结果。

### 页面内容

卡片内容建议：

```text
视觉检测状态
状态：enabled / offline
来源：rk3588-rknn-yolo
模型：custom_delivery_yolo_rk3588.rknn
最近目标：person 0.86
最近事件：检测到人员目标
```

### 实现要求

- 显示 detection enabled/offline；
- 显示 source；
- 显示 model_name；
- 显示 latest objects；
- 显示 latest events；
- 不显示视频画面；
- 不重做 Dashboard UI。

### 验收标准

- [ ] 前端可正常启动；
- [ ] Dashboard 能显示 detection_status；
- [ ] 手动提交 sample detection_status 后，页面能刷新；
- [ ] 无 detection_status 时页面显示 offline 或 no data；
- [ ] 原有任务、状态、模式显示不受影响。

---

## 6. 推荐执行顺序

建议按以下顺序推进：

1. **Voice Round 1**：文本命令解析接口
2. **Voice Round 2**：Dashboard 文本命令卡片
3. **YOLO Round 1**：RKNN 模型目录与推理加载入口
4. **YOLO Round 2**：封装 detection_status
5. **YOLO Round 3**：接入 RK3588 后端状态流
6. **YOLO Round 4**：Dashboard 显示检测状态
7. **Voice Round 3**：ASR 占位接口

原因：

- 语音文本命令最容易复用现有 mission bridge，最快形成可展示闭环；
- YOLO 模型训练与转换不在 RK3588 上做，当前先把 RKNN 模型目录和加载入口留好；
- YOLO 接主系统前必须先证明 detection_status 格式稳定；
- ASR 不急，文本命令已经能覆盖语音任务入口的核心逻辑。

---

## 7. Codex Prompt 序列

## 7.1 Voice Round 1 Prompt

```text
Read AGENTS.md and current project docs.

Task:
Implement the first RK3588 voice-entry slice as a text-command interface.

Scope:
This is NOT real ASR yet. Only implement text command parsing and routing.

Requirements:
1. Add POST /api/voice/text_command
2. Request fields:
   - text
   - source
   - requested_by
3. Implement a rule-based intent parser for:
   - go_to_waypoint
   - start_patrol
   - pause_task
   - resume_task
   - return_home
   - query_status
4. Add a small waypoint alias resolver.
5. For mission commands, reuse existing mission_gateway. Do not duplicate mission forwarding logic.
6. Unknown commands must not trigger robot missions.
7. Do not implement microphone, ASR, LLM, OpenClaw, or navigation changes.

Validation:
- backend starts
- "去一号点" parses to go_to_waypoint with waypoint_id
- "暂停任务" parses to pause_task
- "返回起点" parses to return_home
- unknown command returns need_confirm=true or accepted=false
- existing mission bridge still works

Only modify files required for this task. Do not refactor unrelated code.
```

---

## 7.2 Voice Round 2 Prompt

```text
Continue in the same thread.

Task:
Add a minimal text command panel to the existing Dashboard.

Requirements:
1. Add one input box and one submit button.
2. Submit text to POST /api/voice/text_command.
3. Display:
   - parsed intent
   - waypoint_id if available
   - accepted status
   - detail message
4. Keep the UI consistent with the current Dashboard style.
5. Do not redesign the whole UI.
6. Do not add real ASR or microphone UI yet.

Validation:
- frontend starts
- typing "去一号点" calls the backend endpoint
- parsed result is displayed
- existing Dashboard state display still works

Only modify frontend files required for this task.
```

---

## 7.3 YOLO Round 1 Prompt

```text
Read AGENTS.md and current project docs.

Task:
Prepare the RK3588 RKNN YOLO experiment workspace.

Scope:
Do not train YOLO.
Do not convert .pt to .rknn.
Do not download models.
Only create the local model placement structure and inference loading entry.

Requirements:
1. Create experiments/rknn_yolo/
2. Create experiments/rknn_yolo/models/ with .gitkeep and README.md
3. Create experiments/rknn_yolo/samples/ with .gitkeep and README.md
4. Create experiments/rknn_yolo/outputs/ with .gitkeep
5. Add infer_image.py that accepts:
   - --model path/to/model.rknn
   - --image path/to/image.jpg
   - --labels path/to/labels.txt if needed
   - --conf confidence_threshold
6. infer_image.py should check:
   - model file exists
   - image file exists
   - RKNN runtime / rknn-toolkit-lite2 is available
7. If RKNN runtime is unavailable, fail with a clear message explaining the missing dependency.
8. If the model file is missing, fail with a clear message telling the user to put a .rknn model under experiments/rknn_yolo/models/
9. Add README.md explaining the expected local training -> ONNX -> RKNN -> RK3588 deployment flow.
10. Do not modify main backend, mission bridge, state_store, Dashboard, NUC adapter, or RT-Thread-related code.

Validation:
- Running infer_image.py with a missing model path prints a clear error.
- The model directory exists and is documented.
- No large model files are committed.
- Main backend behavior is unchanged.

Only modify files under experiments/rknn_yolo/ unless minimal docs are needed.
```

---

## 7.4 YOLO Round 2 Prompt

```text
Continue in the same thread.

Task:
Add detection_status formatting for the RKNN YOLO experiment.

Scope:
Still keep this independent from the main backend.

Requirements:
1. Complete or update detection_status_builder.py.
2. Output fields:
   - enabled
   - source
   - model_name
   - frame_id
   - timestamp
   - objects
   - events
3. Convert detections into simple events:
   - person_detected
   - obstacle_detected
   - possible_blockage if repeated obstacle detections are observed
4. Provide a sample JSON output file or documented example.
5. Do not connect this to state_store yet.
6. Do not train or convert models in this round.

Validation:
- running the experiment can print or save detection_status JSON
- empty detections produce enabled=true with empty objects/events
- no changes to main backend behavior

Only modify experiment files.
```

---

## 7.5 YOLO Round 3 Prompt

```text
Read AGENTS.md and current RK3588 backend docs.

Task:
Integrate local RK3588 detection_status into the main backend state flow.

Scope:
Do not implement full video streaming. Do not change mission bridge.
Do not require a real RKNN model for backend startup.

Requirements:
1. Extend backend state models to include optional detection_status if not already supported.
2. Add a local perception service interface that can accept latest detection_status.
3. Store latest detection_status in state_store.
4. Expose detection_status through:
   - GET /api/state/latest
   - WS /ws/state
5. Add a temporary internal test endpoint or debug hook to submit detection_status manually.
6. Do not require RKNN runtime for backend startup.

Validation:
- backend starts without RKNN dependencies
- submitting a sample detection_status updates state_store
- GET /api/state/latest includes detection_status
- WebSocket pushes detection_status updates

Only modify backend files required for this task.
```

---

## 7.6 YOLO Round 4 Prompt

```text
Continue in the same thread.

Task:
Display detection_status on the Dashboard.

Requirements:
1. Add a small visual detection card.
2. Show:
   - enabled/offline status
   - source
   - model_name
   - latest objects
   - latest events
3. Keep UI simple and consistent.
4. Do not add video display.
5. Do not redesign the Dashboard.

Validation:
- frontend starts
- Dashboard shows detection_status from websocket/state API
- sample detection_status appears correctly
- existing mission and system mode UI still works

Only modify frontend files required for this task.
```

---

## 7.7 Voice Round 3 Prompt

```text
Continue in the same thread.

Task:
Add an ASR abstraction placeholder for future microphone speech recognition.

Requirements:
1. Add an asr_service abstraction.
2. Add POST /api/voice/asr_text_mock that accepts text and forwards to existing text_command flow.
3. Document where real ASR will be plugged in later.
4. Do not add Whisper/FunASR/RKNN dependencies yet.
5. Do not implement microphone streaming yet.

Validation:
- text_command still works
- asr_text_mock reuses the same parser
- tests pass

Only modify files required for this task.
```

---

## 8. Phase 4A 总体验收标准

### 8.1 语音任务入口验收

- [ ] `POST /api/voice/text_command` 可用；
- [ ] “去一号点”能触发 `go_to_waypoint`；
- [ ] “暂停任务”能触发 `pause_task`；
- [ ] “返回起点”能触发 `return_home`；
- [ ] 未知命令不会误触发任务；
- [ ] Dashboard 能输入文本命令并显示解析结果；
- [ ] mission 命令走现有 `mission_gateway`；
- [ ] 不影响 mock / real 模式。

### 8.2 YOLO / RKNN 感知原型验收

- [ ] RK3588 上存在独立 `experiments/rknn_yolo/` 实验目录；
- [ ] `models/` 目录存在，并有 `.gitkeep` 与 `README.md`；
- [ ] `models/README.md` 清楚说明 `.rknn` 模型放置方式；
- [ ] 不提交 `.pt`、`.onnx`、`.rknn` 等大模型文件；
- [ ] `infer_image.py` 可通过 `--model` 和 `--image` 指定模型与图片；
- [ ] 模型缺失、图片缺失、RKNN 环境缺失时均有清晰报错；
- [ ] 当放入有效 `.rknn` 模型后，实验脚本可加载模型并处理图片输入；
- [ ] 推理结果能转成结构化检测 JSON；
- [ ] 能封装为 `detection_status`；
- [ ] 后端能接收并保存 `detection_status`；
- [ ] `GET /api/state/latest` 和 `WS /ws/state` 能输出 detection_status；
- [ ] Dashboard 能显示视觉检测状态、最近目标与最近事件；
- [ ] 不做视频流，不影响 mission bridge。

### 8.3 架构边界验收

- [ ] 语音模块不直接控制底盘；
- [ ] YOLO 模块不直接控制底盘；
- [ ] YOLO 结果不直接修改 Nav2 / costmap；
- [ ] RK3588 不接管当前 NUC 主导航；
- [ ] RT-Thread 主控制链路不被改动；
- [ ] 所有新增能力均可关闭或独立调试。

---

## 9. Phase 4A 完成后进入的后续方向

Phase 4A 通过后，再考虑以下内容：

1. 接入真实 ASR；
2. 使用 LLM 做意图解析；
3. 将 YOLO 从图片输入扩展到摄像头输入；
4. 接入视频流或图传页面；
5. 根据实际场景在外部设备训练 YOLO，并转换为 `.rknn` 后部署到 RK3588；
6. 再进一步考虑 RK3588 本地二维导航迁移。
