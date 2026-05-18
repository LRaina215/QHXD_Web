# PAHSE4A_DONE.md

> 文件名按当前任务要求使用 `PAHSE4A_DONE.md`。如果后续整理文档，可另补一个拼写修正版 `PHASE4A_DONE.md`。

## 1. 本轮重新阅读范围

已重新扫描并阅读 / 核对 `QHXD` 项目文件。阅读时排除了以下生成或依赖目录：

- `.git/`
- `frontend/node_modules/`
- `frontend/dist/`
- `__pycache__/`

项目内有效文件统计：

- 文本 / 源码 / 配置 / 文档文件：66 个
- 二进制运行数据文件：1 个，`backend/data/rk3588_phase1.db`
- 合计：67 个项目文件

重点阅读对象：

- 根文档：`AGENT.md`、`README.md`、`DO_PHASE4A.md`
- 阶段文档：`doc/arc_p1.md`、`doc/arc_p2.md`、`doc/arc_p3.md`、`doc/prd_p1.md`、`doc/prd_p2.md`、`doc/prd_p3.md`、`doc/project_p1.md`、`doc/project_p2.md`、`doc/project_p3.md`
- NUC 联调文档：`NUC_DO*.md`、`NUC_DONE*.md`、`PHASE3_ROUND*.md`
- 后端源码：`backend/app/main.py`、`backend/app/schemas.py`、`backend/app/services/*.py`
- 前端源码：`frontend/src/App.vue`、`frontend/src/style.css`、`frontend/src/main.ts`
- Phase 4A 实验目录：`experiments/rknn_yolo/*`
- 测试：`backend/tests/test_phase1.py`

## 2. 当前项目整体情况

`QHXD` 是 RK3588 车载交互与状态中台主工程。系统设计采用三节点协同：

- `NUC11`：主智能计算节点，负责 SLAM、定位、导航、感知与任务管理。
- `RT-Thread`：底层实时控制与安全闭环，负责底盘执行、传感器、急停和故障保护。
- `RK3588`：状态聚合、任务入口、Web 服务、Dashboard、日志，以及后续语音 / 感知增强能力承载。

当前代码状态已经超过早期 `AGENT.md` / README 开头描述的 Phase 1/2 口径：

- Phase 1：FastAPI + Vue Dashboard + mock 状态链路已具备。
- Phase 2：`NUC -> RK3588` 状态上送、`RK3588 -> NUC` mission bridge、mock / real 模式切换已具备。
- Phase 3：RT-Thread 状态经 NUC 归一化后进入 RK3588 契约的路径已经在 RK 侧冻结；IMU 专项链路已具备。
- Phase 4A：本轮已新增文本任务入口、ASR mock 占位、本地 YOLO/RKNN 实验目录、`detection_status` 状态接入和 Dashboard 最小展示。

后端核心结构：

- `backend/app/main.py`：FastAPI 路由、WebSocket、后台 mock/real health loop。
- `backend/app/schemas.py`：全局公开数据契约真源。
- `backend/app/services/mock_state.py`：mock 状态生成、任务模拟、SQLite 日志写入。
- `backend/app/services/state_store.py`：共享最新状态缓存，统一支撑 REST / WS / Dashboard。
- `backend/app/services/mission_gateway.py`：mock / real mission 命令分流。
- `backend/app/services/nuc_adapter.py`：NUC 状态接入、NUC mission bridge、IMU 接入。
- `backend/app/services/mode_manager.py`：mock/real 模式切换、NUC 超时、bridge 错误状态。
- `backend/app/services/persistence.py`：SQLite command logs / alerts / state snapshots。
- `backend/app/services/ws_manager.py`：状态和 IMU WebSocket 连接管理。

前端核心结构：

- `frontend/src/App.vue`：单页 Dashboard，展示模式、任务、设备、环境、IMU、文本命令、视觉检测、告警。
- `frontend/src/style.css`：Dashboard 样式。
- `frontend/vite.config.ts`：Vite dev server 与 `/api`、`/ws` 代理。

## 3. 本轮完成内容概览

### 3.1 语音 / 文本任务入口

新增了 Phase 4A 文本任务入口，但没有接入真实麦克风、ASR、LLM 或 OpenClaw。

当前链路：

```text
文本命令
-> intent_parser
-> waypoint_resolver
-> voice_entry_service
-> mission_gateway
-> mock_state_service 或 NUC bridge
-> state_store / WS / Dashboard
```

支持意图：

- `go_to_waypoint`
- `start_patrol`
- `pause_task`
- `resume_task`
- `return_home`
- `query_status`

未知文本或目标点无法解析时，不会触发 mission。

### 3.2 ASR 占位入口

新增 `POST /api/voice/asr_text_mock`，当前仍接收文本，复用 `text_command` 同一套解析与任务分发流程。

这只是后续真实 ASR 的服务抽象预留，不加载 Whisper / FunASR / 在线 ASR 依赖。

### 3.3 YOLO / RKNN 独立实验目录

新增 `experiments/rknn_yolo/`，用于后续放置外部训练并转换好的 `.rknn` 模型，进行 RK3588 单张图片推理验证。

当前不做：

- 不训练 YOLO。
- 不导出 ONNX。
- 不转换 RKNN。
- 不下载或提交模型文件。
- 不接视频流。

### 3.4 detection_status 状态接入

新增可选 `detection_status` 契约，并提供 debug endpoint：

```text
POST /api/internal/perception/detection_status
```

提交后可以通过以下链路观察：

```text
GET /api/state/latest
WS /ws/state
Dashboard 视觉检测状态卡片
```

主后端启动不依赖 RKNN Runtime。

## 4. 修改 / 新增代码说明（含文件与行号）

### 4.1 后端公开契约

文件：`backend/app/schemas.py`

- `VoiceIntentValue`：第 16 行起，新增文本命令意图枚举。
- `DetectionObject`：第 89 行起，新增检测目标结构。
- `DetectionStatus`：第 101 行起，新增视觉检测状态结构。
- `RobotState.detection_status`：第 118 行，主状态新增可选视觉检测状态字段。
- `VoiceTextCommandRequest`：第 175 行起，新增文本命令请求体。
- `VoiceCommandResult`：第 181 行起，新增文本命令解析 / 执行结果。
- `PerceptionDetectionStatusRequest`：第 299 行起，新增 detection_status debug 上报请求。
- `PerceptionDetectionStatusResult`：第 303 行起，新增上报结果。

代码摘要：

```python
VoiceIntentValue = Literal[
    "go_to_waypoint", "start_patrol", "pause_task",
    "resume_task", "return_home", "query_status",
]

class DetectionStatus(ContractModel):
    enabled: bool
    source: str
    model_name: str | None
    frame_id: str
    timestamp: datetime
    objects: list[DetectionObject]
    events: list[DetectionEvent]

class RobotState(ContractModel):
    ...
    detection_status: DetectionStatus | None = None
```

### 4.2 后端 API 路由

文件：`backend/app/main.py`

- `POST /api/voice/text_command`：第 112 行起，文本命令入口。
- `POST /api/voice/asr_text_mock`：第 120 行起，ASR 文本 mock 占位入口。
- `POST /api/internal/perception/detection_status`：第 183 行起，视觉检测状态 debug 上报入口。

代码摘要：

```python
@app.post("/api/voice/text_command")
async def text_command(request: VoiceTextCommandRequest):
    result, state = voice_entry_service.handle_text_command(request)
    if state is not None:
        await ws_manager.broadcast_state(state)
    return VoiceCommandResponse(data=result)

@app.post("/api/internal/perception/detection_status")
async def ingest_detection_status(request: PerceptionDetectionStatusRequest):
    latest_state = state_store.update_detection_status(request.detection_status)
    await ws_manager.broadcast_state(latest_state)
```

### 4.3 状态存储

文件：`backend/app/services/state_store.py`

- `update_detection_status()`：第 28 行起，手动刷新最新 detection_status。
- `_store_state()` 保留检测状态：第 63 行起，mock / real 状态刷新时，如果新状态不带 detection_status，则保留已有视觉检测状态。

代码摘要：

```python
def update_detection_status(self, detection_status: DetectionStatus) -> RobotState:
    latest_state = self.get_latest_state().model_copy(
        update={"detection_status": detection_status, "updated_at": self._timestamp()}
    )
    self._latest_state = latest_state
    return self.get_latest_state()
```

### 4.4 语音 / 文本服务

文件：`backend/app/services/intent_parser.py`

- `IntentParser`：第 16 行起。
- `parse()`：第 19 行起。
- `query_status` 规则：第 26 行。
- `pause_task` 规则：第 34 行。
- `return_home` 规则：第 50 行。
- `start_patrol` 规则：第 58 行。
- `go_to_waypoint` 规则：第 69 行起。

代码摘要：

```python
if self._contains_any(normalized, ["暂停任务", "暂停", "停一下"]):
    return ParsedIntent(intent="pause_task", confidence=0.94, need_confirm=False)

if self._contains_any(normalized, ["去", "到", "前往", "送到"]):
    waypoint_id, waypoint_name = waypoint_resolver.resolve(text)
    ...
```

文件：`backend/app/services/waypoint_resolver.py`

- `WaypointResolver`：第 5 行起。
- `resolve()`：第 12 行起。
- `waypoint_resolver` 单例：第 43 行。

文件：`backend/app/config/waypoints.json`

- `wp_001`：第 3 行，别名包括“一号点 / 201 / 实验室 / 送到实验室”。
- `wp_002`：第 8 行。
- `home`：第 13 行。

文件：`backend/app/services/voice_entry.py`

- `VoiceEntryService`：第 16 行起。
- `handle_text_command()`：第 19 行起，统一处理解析、查询和 mission 分发。
- `query_status`：第 28 行起。
- `_dispatch_mission()`：第 53 行起，复用 `mission_gateway`。
- `go_to_waypoint` 分发：第 56 行。
- `start_patrol` 分发：第 64 行。
- `pause/resume/return_home` 分发：第 72、74、76 行。

文件：`backend/app/services/asr_service.py`

- `ASRService`：第 4 行起。
- `transcribe_text_mock()`：第 7 行起，作为真实 ASR 前的文本 mock 抽象。

### 4.5 前端 Dashboard

文件：`frontend/src/App.vue`

- `DetectionStatus` 前端类型：第 4 行起。
- `RobotState.detection_status`：第 58 行。
- `VoiceCommandResponse` 前端类型：第 90 行起。
- `textCommand` / `voiceResult` 状态：第 159、160 行。
- `detectionStatusLabel`：第 274 行起。
- `sendTextCommand()`：第 460 行起。
- “语音/文本任务入口”卡片：第 656 行起。
- “视觉检测状态”卡片：第 805 行起。

代码摘要：

```ts
async function sendTextCommand() {
  const response = await fetch('/api/voice/text_command', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ text: textCommand.value, source: 'dashboard-text' }),
  })
  voiceResult.value = payload.data
}
```

文件：`frontend/src/style.css`

- `overflow-wrap: anywhere`：第 247 行，避免长内容挤破卡片。
- `.command-result-grid`：第 250 行。
- `.wide-detail`：第 254 行。

### 4.6 RKNN YOLO 实验目录

文件：`experiments/rknn_yolo/detection_status_builder.py`

- `OBSTACLE_CLASSES`：第 5 行。
- `build_detection_status()`：第 8 行起。
- `person_detected` 事件：第 48 行。
- `obstacle_detected` 事件：第 55 行。
- `possible_blockage` 事件：第 62 行。

代码摘要：

```python
def build_detection_status(objects, *, model_name, frame_id="camera_front", ...):
    normalized_objects = [_normalize_object(item) for item in objects]
    events = _build_events(normalized_objects, blockage_frames)
    return {"enabled": enabled, "objects": normalized_objects, "events": events}
```

文件：`experiments/rknn_yolo/infer_image.py`

- `argparse` 参数入口：第 13 行起。
- `--model`：第 14 行。
- `--image`：第 15 行。
- `--labels`：第 16 行。
- `--conf`：第 17 行。
- `--format`：第 20 行起。
- RKNN Runtime 导入：第 43 行。
- `RKNNLite()` 初始化：第 56 行。
- `_parse_outputs()`：第 93 行起。

文件：`experiments/rknn_yolo/README.md`

- 说明该目录是独立实验，不接入主后端。
- 给出推理命令和 `--format detection_status` 输出方式。

文件：`experiments/rknn_yolo/models/README.md`

- 说明 `.rknn` 模型放置规范。
- 明确不提交 `.pt`、`.onnx`、`.rknn` 大模型文件。

文件：`experiments/rknn_yolo/samples/README.md`

- 说明样例图片放置方式。

### 4.7 README 文档

文件：`README.md`

- Phase 4A 章节起点：第 192 行。
- `POST /api/voice/text_command` / `POST /api/voice/asr_text_mock`：第 199、200 行。
- 文本命令 curl 示例：第 206 行起。
- `detection_status` 说明：第 230 行起。
- `POST /api/internal/perception/detection_status`：第 233 行。
- detection_status curl 示例：第 239 行起。
- `experiments/rknn_yolo/` 说明：第 251 行起。
- RKNN 推理命令：第 257 行起。

### 4.8 测试

文件：`backend/tests/test_phase1.py`

- `test_voice_text_command_routes_to_existing_mission_gateway`：第 209 行起。
- `test_voice_text_command_unknown_does_not_trigger_mission`：第 228 行起。
- `test_asr_text_mock_reuses_text_command_flow`：第 244 行起。
- `test_detection_status_update_is_visible_in_latest_state`：第 259 行起。

覆盖点：

- “去一号点”能解析为 `go_to_waypoint` 并走现有 mission gateway。
- 未知文本不会写 mission 日志，不会触发任务。
- `asr_text_mock` 复用文本命令流程。
- `detection_status` 能进入最新 `RobotState`。

## 5. 验证记录

已执行：

```bash
cd ~/QHXD/backend
python3 -m unittest discover -s tests
```

结果：

```text
Ran 16 tests in 0.656s
OK
```

已执行：

```bash
cd ~/QHXD/frontend
npm run build
```

结果：

```text
vue-tsc --noEmit && vite build
built successfully
```

已执行：

```bash
cd ~/QHXD/backend
timeout 5s python3 -m uvicorn app.main:app --host 127.0.0.1 --port 8010
```

结果：

```text
Application startup complete
```

已执行：

```bash
cd ~/QHXD/experiments/rknn_yolo
python3 infer_image.py --model models/missing.rknn --image samples/missing.jpg --labels labels.txt --conf 0.25
```

结果：

```text
模型文件不存在：models/missing.rknn。请将 .rknn 模型放入 experiments/rknn_yolo/models/ 后重试。
```

已执行：

```bash
cd ~/QHXD/experiments/rknn_yolo
PYTHONDONTWRITEBYTECODE=1 python3 -c 'from detection_status_builder import build_detection_status; status = build_detection_status([{"class_name":"person","confidence":0.86,"bbox_xyxy":[120,80,260,360]},{"class_name":"chair","confidence":0.72,"bbox_xyxy":[20,30,80,110]}], model_name="custom_delivery_yolo_rk3588.rknn", blockage_frames=3); assert status["events"][0]["event_type"] == "person_detected"; assert any(event["event_type"] == "obstacle_detected" for event in status["events"]); assert any(event["event_type"] == "possible_blockage" for event in status["events"]); print(status["model_name"], len(status["objects"]), len(status["events"]))'
```

结果：

```text
custom_delivery_yolo_rk3588.rknn 2 3
```

## 6. 当前 Git / 工作树注意事项

当前仓库状态：

- 分支：`master`
- 本地分支领先 `origin/master` 1 个提交
- HEAD：`856fd14 Tagv4.1 语音交互与YOLO检测接口加入`
- `DO_PHASE4A.md`、Phase 4A 后端 / 前端 / 实验目录改动已经包含在上述本地提交中
- 本文件 `PAHSE4A_DONE.md` 为本轮新增，尚未提交

当前 `git status --short --untracked-files=all` 仍可见：

```text
MM backend/data/rk3588_phase1.db
?? PAHSE4A_DONE.md
```

说明：

- `backend/data/rk3588_phase1.db` 被运行 / 测试写入后显示 staged + unstaged modified。该文件本身已在 `.gitignore` 中配置 `backend/data/*.db`，但当前仓库历史中仍有跟踪状态。
- `PAHSE4A_DONE.md` 为本文件，本轮新增。

## 7. 后续建议

1. 同步修正文档阶段口径：`AGENT.md` 和 README 开头仍偏 Phase 1/2，应补充 Phase 3/4A 当前状态说明。
2. 若准备提交 Git，建议确认是否继续跟踪 `backend/data/rk3588_phase1.db` 和 `frontend/dist/`。
3. 后续真实 ASR 接入时，只需替换 `backend/app/services/asr_service.py` 的真实转写逻辑，再复用 `voice_entry_service`。
4. 后续真实 RKNN 推理接主系统时，可以先由 `infer_image.py --format detection_status` 输出结果，再 POST 到 `/api/internal/perception/detection_status` 验证 Dashboard 展示。
