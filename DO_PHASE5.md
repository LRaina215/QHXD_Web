# DO_PHASE5.md

# Phase 5：语音与视觉能力工程收口阶段

## 1. 阶段定位

Phase 4 已经完成语音任务入口、FunASR 离线识别、RKNN YOLO26 单图推理、USB 摄像头连续检测、`detection_status` 后端接入、最新检测画面接口和 Dashboard 展示闭环。

Phase 5 不再继续堆叠新功能，也不做长期稳定性测试。本阶段目标是对 Phase 4 已经完成的语音与视觉能力进行工程收口，使其更适合比赛现场演示和后续集成。

本阶段重点包括：

- 服务启动方式规范化；
- YOLO 检测结果调试与稳定显示；
- 视觉事件策略优化；
- 语音命令词表与安全边界收口；
- Dashboard 展示体验完善；
- 文档、配置和验收路径固化。

本阶段不做：

- 长时间稳定性测试；
- OpenClaw 接入；
- LLM 多轮对话；
- 浏览器麦克风录音；
- RTSP / WebRTC 视频流；
- YOLO 结果直接控制底盘；
- Hik 相机 SDK 正式接入；
- 模型重新训练、ONNX 重新导出、RKNN 重新转换或 INT8 量化。

---

## 2. 当前系统基础

当前已有能力：

### 2.1 语音任务入口

已有接口：

- `POST /api/voice/text_command`
- `POST /api/voice/asr_text_mock`
- `POST /api/voice/audio_command`
- `POST /api/voice/record_command`

已有能力：

- 文本命令解析；
- FunASR 离线识别；
- USB 麦克风录音识别；
- waypoint alias 解析；
- 未知语音不触发 mission；
- 语音识别结果复用既有 `mission_gateway`。

### 2.2 RKNN YOLO26 视觉检测

已有能力：

- RK3588 本地加载 `yolo26n_fp32.rknn`；
- 单图推理；
- USB 摄像头抽帧检测；
- `detection_status` JSON 输出；
- 检测状态提交后端；
- 最新带框图片生成；
- Dashboard 展示视觉检测状态和最新图片。

### 2.3 后端与 Dashboard

已有接口：

- `POST /api/internal/perception/detection_status`
- `GET /api/perception/latest_frame`
- `HEAD /api/perception/latest_frame`
- `GET /api/state/latest`
- `WS /ws/state`

---

## 3. Phase 5 总目标

Phase 5 的总目标是：

> 将 Phase 4 中已经跑通的语音与视觉能力从“能运行的功能原型”整理为“可配置、可排查、可演示、可交接”的工程模块。

完成后应达到：

- 语音命令边界清楚；
- YOLO 检测结果可调试、可解释；
- Dashboard 展示不闪烁、不误导；
- 服务启动方式清楚；
- 配置文件与 README 说明完整；
- 比赛现场出现问题时能快速判断问题位置。

---

## 4. 任务清单与验收标准

## Task 5.1：启动脚本与运行流程规范化

### 任务目标

将后端、前端、YOLO 摄像头服务的启动流程整理为统一脚本，降低手动启动出错概率。

### 开发任务

1. 新增 `scripts/` 目录。
2. 新增启动脚本：
   - `scripts/start_backend.sh`
   - `scripts/start_frontend.sh`
   - `scripts/start_yolo_camera.sh`
   - `scripts/start_all.sh`
3. 新增停止脚本：
   - `scripts/stop_all.sh`
4. 新增状态检查脚本：
   - `scripts/status_all.sh`
5. 脚本中应明确：
   - 项目根目录；
   - 后端端口；
   - 前端端口；
   - YOLO 配置文件路径；
   - 日志输出路径。
6. 不做 systemd 服务化，不做开机自启。

### 验收标准

- 执行 `scripts/start_backend.sh` 后，`GET /health` 正常返回。
- 执行 `scripts/start_yolo_camera.sh` 后，`outputs/latest_camera_detection.jpg` 能生成或更新。
- 执行 `scripts/start_all.sh` 后，后端、前端、YOLO 摄像头服务均可启动。
- 执行 `scripts/stop_all.sh` 后，对应进程能被停止。
- 执行 `scripts/status_all.sh` 后，能看到后端、前端、YOLO 服务的运行状态。
- 脚本失败时能输出明确错误信息，而不是静默失败。

---

## Task 5.2：YOLO 输入帧与检测结果调试能力增强

### 任务目标

解决“上一帧有检测框、下一帧同场景无检测框”这类问题时缺少排查依据的问题。YOLO 是单帧检测模型，静止目标理论上仍应被检测，若出现明显波动，需要能够判断问题出在输入帧、阈值、后处理还是 Dashboard 展示同步。

### 开发任务

1. 在 `camera_detect_service.py` 中增加可选参数：
   - `--save-debug-frames`
   - `--debug-frame-dir`
   - `--debug-every-n`
2. 调试模式下，每次推理可保存：
   - 输入原图；
   - 带框输出图；
   - 当前帧 detection JSON。
3. 每帧日志中增加关键统计：
   - frame sequence；
   - raw output count；
   - confidence filter 后数量；
   - NMS 后数量；
   - final detections 数量；
   - 主要类别与置信度。
4. 保持默认运行不保存调试帧，避免占用磁盘。
5. 不改变现有推理预处理链路：
   - RGB；
   - NHWC；
   - float32 / 255.0；
   - 640x640；
   - `xyxy_score_class`。

### 验收标准

- 默认运行时不生成大量 debug 文件。
- 打开 `--save-debug-frames` 后，能在指定目录看到输入图、输出图和 JSON。
- 漏检时可以通过保存的输入图确认“送入 YOLO 的图中是否确实有人/障碍”。
- 日志中能看到每帧 `raw/conf/nms/final` 数量。
- 现有 `--submit`、`--save-latest`、`--config` 功能不受影响。

---

## Task 5.3：检测结果短时保持与 Dashboard 防闪烁

### 任务目标

降低 YOLO 偶发漏检导致 Dashboard 视觉状态频繁闪烁的问题。短时保持只用于显示和告警稳定，不参与底盘控制。

### 开发任务

1. 在 YOLO 服务或后端状态层增加最近检测缓存。
2. 对指定类别增加短时保持策略，例如：
   - `person` 保持 2 秒；
   - `obstacle` 保持 2 秒；
   - `possible_blockage` 按连续帧规则生成。
3. `detection_status` 中增加可选字段或事件，用于表达：
   - 当前帧检测到；
   - 最近若干秒内检测到；
   - 上次检测时间。
4. Dashboard 中显示“当前检测”与“最近检测”区别。
5. 不得将短时保持结果用于自动控制底盘。

### 验收标准

- person 偶发 1 帧漏检时，Dashboard 不会立刻从“有人”跳成“无目标”。
- 超过保持时间后，若持续无检测，Dashboard 正确显示无近期目标或离线状态。
- `detection_status` 中能区分当前帧目标和 recently seen 目标。
- 不改变 mission、NUC bridge、RT-Thread 控制链路。

---

## Task 5.4：视觉事件策略优化

### 任务目标

把 YOLO 检测结果从“原始目标列表”整理成更适合展示和告警的事件，减少重复刷屏和误报。

### 开发任务

1. 保留三类基础事件：
   - `person_detected`
   - `obstacle_detected`
   - `possible_blockage`
2. 增加事件节流配置：
   - 同类事件最小上报间隔；
   - 连续 N 帧障碍才生成 `possible_blockage`。
3. 增加小目标过滤：
   - bbox 面积过小不触发 obstacle 事件；
   - 低置信度目标不触发告警。
4. Dashboard 中视觉事件显示更清楚：
   - 事件类型；
   - 等级；
   - 最近更新时间；
   - 简短中文说明。
5. 不新增复杂行为识别。

### 验收标准

- 空场景不会频繁刷出 `obstacle_detected`。
- 人员进入画面时能稳定出现 `person_detected`。
- 障碍物连续出现达到规则后才触发 `possible_blockage`。
- 同类事件不会每一帧都刷屏。
- Dashboard 中事件展示清楚，不影响原有任务和状态卡片。

---

## Task 5.5：语音命令安全边界与词表收口

### 任务目标

将语音交互从“能识别并触发任务”整理为“词表明确、边界明确、误触发可控”的任务入口。

### 开发任务

1. 整理并冻结第一版语音命令词表。
2. 整理并冻结第一版 waypoint alias 表。
3. 对每类命令明确执行策略：
   - 可直接执行；
   - 需要确认；
   - 不允许执行。
4. 未知命令、低置信度命令、目标点不唯一时，不触发 mission。
5. Dashboard 显示最近语音识别结果：
   - 识别文本；
   - intent；
   - waypoint；
   - accepted；
   - detail。
6. 增加语音记录目录清理说明或简单清理脚本。
7. 不做 wake word、streaming ASR、LLM、OpenClaw。

### 建议第一版命令词表

| 命令类型 | 示例表达 | 执行策略 |
|---|---|---|
| 前往目标点 | 去 201 实验室、去装载点 | 可执行或需要确认，按当前系统能力配置 |
| 暂停任务 | 暂停、暂停任务、停一下 | 可直接执行 |
| 继续任务 | 继续、恢复任务 | 可直接执行 |
| 返回起点 | 返回起点、返航、回装载点 | 建议需要确认 |
| 开始巡检 | 开始巡检、执行巡检 | 建议需要确认 |
| 查询状态 | 当前状态、现在在哪 | 可直接执行 |

### 验收标准

- 已知命令能正确解析并触发对应 mission 或查询。
- 未知命令不会触发 mission。
- 目标点无法解析或存在歧义时不会触发 mission。
- 语音识别失败时返回明确错误信息。
- Dashboard 能显示最近一次语音识别和执行结果。
- `voice_records` 不会无限增长且有清理说明。

---

## Task 5.6：README 与交接文档更新

### 任务目标

把当前语音、YOLO、Dashboard 的运行方式和调试方式写清楚，保证队友能复现。

### 开发任务

1. 更新 README 中 Phase 5 说明。
2. 新增或更新以下内容：
   - 后端启动方式；
   - 前端启动方式；
   - YOLO 摄像头服务启动方式；
   - 调试帧保存方式；
   - 语音命令测试方式；
   - 常见错误排查；
   - Phase 5 不包含的内容；
   - 汇总所有模式下的启动方式，放在文档的前部分。
3. 新增 `DONE_PHASE5.md` 到项目根目录或文档目录。
4. 标注当前仍不做：
   - 长时间稳定性测试；
   - systemd 服务化；
   - Hik SDK；
   - OpenClaw；
   - 视频流；
   - 模型训练和量化。

### 验收标准

- 新成员按 README 能启动后端、前端和 YOLO 摄像头服务。
- README 中能找到语音测试命令。
- README 中能找到 YOLO 调试帧保存方法。
- README 中能找到 Dashboard 最新检测画面接口说明。
- 文档与实际接口、脚本名称一致。

---

## 5. 本阶段推荐执行顺序

建议按以下顺序推进：

1. Task 5.1：启动脚本与运行流程规范化；
2. Task 5.2：YOLO 输入帧与检测结果调试能力增强；
3. Task 5.3：检测结果短时保持与 Dashboard 防闪烁；
4. Task 5.4：视觉事件策略优化；
5. Task 5.5：语音命令安全边界与词表收口；
6. Task 5.6：README 与交接文档更新。

---

## 6. Codex 分轮 Prompt

## Round 1：启动脚本与运行流程规范化

```text
Read AGENTS.md, README.md, PHASE4_DONE.md, and DO_PHASE5.md.

Task:
Implement Phase 5 Round 1: startup and status scripts.

Requirements:
1. Add scripts/start_backend.sh.
2. Add scripts/start_frontend.sh.
3. Add scripts/start_yolo_camera.sh.
4. Add scripts/start_all.sh.
5. Add scripts/stop_all.sh.
6. Add scripts/status_all.sh.
7. Scripts should use project-relative paths where possible.
8. Scripts should print clear status and error messages.
9. Do not add systemd services.
10. Do not change backend, frontend, mission, voice, or YOLO behavior.

Validation:
- start_backend.sh can start backend.
- start_yolo_camera.sh can start camera_detect_service.py with camera_config.json.
- status_all.sh reports running or not running.
- stop_all.sh stops processes started by scripts.

Only modify files required for startup scripts and minimal README notes.
```

---

## Round 2：YOLO 调试帧与检测链路统计

```text
Read AGENTS.md, PHASE4_DONE.md, and DO_PHASE5.md.

Task:
Implement Phase 5 Round 2: YOLO debug frame saving and detection pipeline statistics.

Requirements:
1. Add optional CLI/config support for saving debug frames.
2. Save input frame, output frame, and detection JSON when debug frame saving is enabled.
3. Add per-frame diagnostic logging:
   - frame sequence
   - raw candidate count
   - confidence-passed count
   - NMS-passed count
   - final detection count
   - top classes and confidences
4. Debug saving must be disabled by default.
5. Do not change the verified preprocessing pipeline.
6. Do not change mission bridge or backend state semantics.

Validation:
- Default camera service behavior remains unchanged.
- With debug enabled, files appear in the configured debug directory.
- Logs clearly show per-frame detection statistics.
- Existing submit and latest-frame behavior still works.

Only modify YOLO camera/inference related files and documentation if needed.
```

---

## Round 3：检测结果短时保持

```text
Read AGENTS.md, PHASE4_DONE.md, and DO_PHASE5.md.

Task:
Implement Phase 5 Round 3: detection result short-term hold for display stability.

Requirements:
1. Add short-term hold for selected classes such as person and obstacle.
2. The hold should only affect detection_status display/events, not robot control.
3. Include enough metadata to distinguish current detections from recently seen detections.
4. Make hold duration configurable.
5. Dashboard should show recent detections clearly without misleading them as current-frame detections.
6. Do not add tracking, re-identification, or control actions.

Validation:
- A one-frame missed detection does not immediately clear the Dashboard display.
- After the hold duration expires, stale detections disappear.
- detection_status remains valid JSON.
- Existing YOLO submit and latest-frame features still work.

Only modify detection_status / YOLO service / Dashboard files required for this task.
```

---

## Round 4：视觉事件策略优化

```text
Read AGENTS.md, PHASE4_DONE.md, and DO_PHASE5.md.

Task:
Implement Phase 5 Round 4: visual event policy refinement.

Requirements:
1. Keep these event types:
   - person_detected
   - obstacle_detected
   - possible_blockage
2. Add configurable event throttling.
3. Add configurable repeated-frame requirement for possible_blockage.
4. Add small-object filtering based on bbox area.
5. Improve Dashboard event text for readability.
6. Do not implement behavior recognition.
7. Do not make YOLO events control the robot.

Validation:
- Repeated identical events are throttled.
- possible_blockage appears only after repeated detections.
- Small noisy boxes do not trigger obstacle events.
- Dashboard event display remains clear.

Only modify YOLO event policy and Dashboard display files required for this task.
```

---

## Round 5：语音命令安全边界与词表收口

```text
Read AGENTS.md, PHASE4_DONE.md, and DO_PHASE5.md.

Task:
Implement Phase 5 Round 5: voice command safety boundary and vocabulary cleanup.

Requirements:
1. Review current waypoint aliases and command aliases.
2. Make the first-version command vocabulary explicit in config or documentation.
3. Unknown commands must not trigger mission.
4. Ambiguous waypoint matches must not trigger mission.
5. Low-confidence or failed ASR results must not trigger mission.
6. Dashboard should display the latest voice recognition / parsing / execution result clearly.
7. Add a small cleanup note or script for voice_records.
8. Do not add wake word, streaming ASR, LLM, OpenClaw, or browser microphone recording.

Validation:
- Known voice/text commands still work.
- Unknown command does not trigger mission.
- Ambiguous waypoint does not trigger mission.
- Dashboard shows latest voice result.
- Existing backend tests pass.

Only modify voice-related files, Dashboard display, and docs required for this task.
```

---

## Round 6：文档收口

```text
Read AGENTS.md, README.md, PHASE4_DONE.md, and DO_PHASE5.md.

Task:
Implement Phase 5 Round 6: documentation and handoff cleanup.

Requirements:
1. Update README with Phase 5 status.
2. Document startup scripts.
3. Document YOLO debug frame saving.
4. Document detection short-hold and event policy configuration.
5. Document voice command vocabulary and safety boundary.
6. Document what Phase 5 intentionally does not include.
7. Do not change runtime behavior unless documentation reveals a mismatch that must be fixed.

Validation:
- README commands match actual script names and paths.
- DO_PHASE5.md remains consistent with implemented behavior.
- A teammate can follow the docs to start backend, frontend, and YOLO service.

Only modify documentation unless a small consistency fix is necessary.
```

---

## 7. Phase 5 总体验收标准

Phase 5 完成后，应满足以下条件：

1. 后端、前端、YOLO 摄像头服务有统一启动与停止方式。
2. YOLO 检测具备输入帧与输出结果的调试保存能力。
3. 检测结果偶发漏检不会导致 Dashboard 严重闪烁。
4. 视觉事件不会高频重复刷屏。
5. 语音命令词表、waypoint alias 和安全边界明确。
6. 未知语音、歧义地点、识别失败不会触发 mission。
7. Dashboard 能清楚显示语音结果、视觉状态、视觉事件和最新检测图片。
8. README 能指导队友复现当前阶段功能。
9. 不引入长时间稳定性测试作为当前阶段验收项。
10. 不改变底盘控制语义，不让 YOLO 或语音直接控制 RT-Thread。

---

## 8. 人工验收建议

### 8.1 语音人工验收

至少测试以下语句：

- 去二零一实验室；
- 暂停任务；
- 继续任务；
- 返回起点；
- 开始巡检；
- 随机未知语句。

检查：

- 已知命令是否正确解析；
- 未知命令是否不触发任务；
- Dashboard 是否显示最近识别结果；
- 录音设备错误时是否返回明确错误。

### 8.2 YOLO 人工验收

至少测试以下场景：

- 画面无人；
- 画面有人静止；
- 人进入画面；
- 障碍物静止；
- 光照变化。

检查：

- 输入帧是否真实反映当前画面；
- 检测框是否大致合理；
- 偶发漏检是否被短时保持平滑；
- 空场景是否不频繁误报；
- Dashboard 最新图片是否持续更新。

---

## 9. 本阶段通过后的后续方向

Phase 5 通过后，再考虑进入下一阶段：

- Hik 相机 SDK 接入；
- 更正式的视频流展示；
- YOLO 模型重训或 INT8 量化；
- LLM / OpenClaw 接入；
- 视觉事件与任务策略联动；
- RK3588 本地二维导航迁移预研。
