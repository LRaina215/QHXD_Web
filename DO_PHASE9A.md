# DO_PHASE9A.md

# Phase 9A：灵巡 Sentinel 智能语音助手与身份认知闭环

## 1. 阶段定位

本阶段目标是在现有语音入口、FunASR、DeepSeek fallback、任务接口、状态接口和 Dashboard 基础上，将机器人语音能力从“固定指令触发”升级为“受控型智能语音助手”。

机器人正式命名为：**灵巡 Sentinel**。

它应具备明确身份、能力边界和安全规则，能够理解自然语言、查询机器人状态和外部数据、生成自然语言回复，并通过 TTS 播报结果。但所有涉及运动控制的任务，必须转成结构化 JSON，并经过本地校验、权限判断和确认流程后才能执行。

本阶段核心链路：

```text
语音输入 / 文本输入
→ FunASR / 浏览器语音
→ 规则解析优先
→ DeepSeek fallback
→ 结构化 intent / query / mission_candidate
→ 本地安全校验
→ 查询状态 / 查询天气 / 候选任务确认
→ TTS 播报
→ Dashboard 展示交互结果
```

## 2. 本阶段不做内容

本阶段暂不实现：

- 大模型直接控制底盘；
- 大模型直接生成速度指令；
- 唤醒词；
- 连续流式对话；
- 长期记忆；
- 复杂多轮任务规划；
- 视觉检测结果自动控制机器人；
- 传感器板正式接入后的环境数据替换；
- 小程序/App 完整重构。

---

# 3. 任务清单与验收标准

## Task 9A.1：建立机器人身份档案 `robot_profile`

### 任务内容

新增机器人身份配置文件，例如：

```text
backend/config/robot_profile.json
```

建议包含：

```json
{
  "robot_name": "灵巡",
  "english_name": "Sentinel",
  "full_name": "灵巡 Sentinel 配送巡检一体化智能机器人",
  "role": "室内配送巡检机器人",
  "team": "海南大学嵌赛项目组",
  "abilities": [
    "语音任务交互",
    "目标点配送",
    "室内巡检",
    "视觉目标检测",
    "机器人状态查询",
    "天气与环境信息播报"
  ],
  "safety_rules": [
    "不能直接控制底盘速度",
    "运动类任务必须经过安全校验",
    "目标点不明确时必须请求确认",
    "未知命令不能触发任务"
  ],
  "self_intro": "你好，我是灵巡 Sentinel，一台面向实验楼和仓储场景的配送巡检一体化智能机器人。我可以执行定点配送、巡检任务、状态查询和视觉检测播报。"
}
```

### 验收标准

- 后端可读取 `robot_profile.json`；
- 机器人名称固定为 **灵巡 Sentinel**；
- 询问“你是谁”“你叫什么名字”时能返回身份介绍；
- 询问“你能做什么”时能返回能力列表；
- 身份信息不硬编码在多个业务文件中，应从统一配置读取；
- 修改 `robot_profile.json` 后，不需要改动核心解析逻辑。

---

## Task 9A.2：新增身份与能力查询 intent

### 任务内容

在现有语音 intent 体系中新增：

```text
query_self_identity
query_capability
query_safety_rule
```

示例输入：

```text
你是谁？
你叫什么名字？
你能做什么？
你可以自己控制底盘吗？
你有哪些安全规则？
```

### 验收标准

- “你是谁”解析为 `query_self_identity`；
- “你能做什么”解析为 `query_capability`；
- “你可以自己控制底盘吗”解析为 `query_safety_rule`；
- 查询类 intent 不触发 mission；
- 回复内容来自 `robot_profile`，不是 DeepSeek 自由编造；
- Dashboard 能显示识别文本、intent 和回复文本。

---

## Task 9A.3：清理 waypoint 与命令别名歧义

### 任务内容

清理当前 waypoint alias，避免语音和 LLM 解析时误触发。

建议：

```text
wp_201：
- 201实验室
- 二零一实验室
- 201
- 二零一

wp_001：
- 一号点
- 1号点
- 1 号点
- 一号

home：
- 起点
- 装载点
- 返回点
- home
```

避免：

```text
wp_001 同时包含 “201”“实验室”“送到实验室”等模糊别名
```

### 验收标准

- “去二零一实验室”解析为 `wp_201`；
- “去201”解析为 `wp_201`，或进入确认流程；
- “去一号点”解析为 `wp_001`；
- “去实验室”如果无法唯一确定，返回 `ambiguous_waypoint` 或 `need_confirm=true`，不触发 mission；
- 未知地点不会触发 mission；
- waypoint_id 与后端/导航侧实际目标点一致。

---

## Task 9A.4：扩展智能语音 intent 类型

### 任务内容

在现有固定任务命令基础上，扩展状态查询、天气查询、视觉查询和身份查询。

建议支持：

```text
任务控制类：
- go_to_waypoint
- start_patrol
- pause_task
- resume_task
- return_home

身份认知类：
- query_self_identity
- query_capability
- query_safety_rule

机器人状态查询类：
- query_robot_status
- query_task_status
- query_battery
- query_emergency_stop
- query_perception_status

外部/环境数据查询类：
- query_weather
- query_environment

播报类：
- speak_last_result
```

### 验收标准

- “你现在状态正常吗”解析为 `query_robot_status`；
- “当前任务是什么”解析为 `query_task_status`；
- “你还有多少电”解析为 `query_battery`；
- “现在天气怎么样”解析为 `query_weather`；
- “你刚才看到了什么”解析为 `query_perception_status`；
- “你是谁”解析为 `query_self_identity`；
- 查询类 intent 不触发 mission；
- 控制类 intent 继续走安全校验和确认机制。

---

## Task 9A.5：新增 data_service 数据聚合层

### 任务内容

新增统一数据读取服务，不允许 DeepSeek 直接访问零散接口。

建议模块：

```text
backend/app/services/data_service.py
backend/app/services/robot_status_provider.py
backend/app/services/weather_provider.py
backend/app/services/profile_provider.py
```

数据来源：

```text
profile_provider：
- robot_profile.json

robot_status_provider：
- state_store
- task_status
- device_status
- detection_status
- alerts
- voice_status

weather_provider：
- 当前先读取天气数据
- 后续替换/叠加 C 板环境传感器 env_sensor
```

### 验收标准

- `data_service` 能读取机器人身份档案；
- `data_service` 能读取当前机器人状态；
- `data_service` 能读取任务状态；
- `data_service` 能读取视觉检测状态；
- `weather_provider` 能返回结构化天气数据；
- 数据源失败时返回明确错误，不让 DeepSeek 编造结果；
- 后续传感器板接入时，不需要重写语音主流程。

---

## Task 9A.6：新增天气/环境查询接口

### 任务内容

由于传感器板尚未准备好，本阶段先用天气数据作为环境查询来源。

新增接口：

```http
GET /api/external/weather/latest
```

返回示例：

```json
{
  "success": true,
  "data": {
    "location": "海南海口",
    "temperature_c": 28.6,
    "humidity_percent": 82,
    "weather": "多云",
    "wind": "东南风",
    "source": "weather_provider",
    "updated_at": "2026-xx-xxTxx:xx:xx"
  }
}
```

### 验收标准

- `/api/external/weather/latest` 可正常返回结构化天气数据；
- 返回数据包含 `location`、`temperature_c`、`humidity_percent`、`weather`、`source`、`updated_at`；
- 接口失败时返回结构化错误；
- “现在天气怎么样”能调用该数据源；
- “当前环境适合巡检吗”能基于天气数据生成回答；
- 天气数据不能伪装成机器人本体传感器数据，应明确 `source=weather_provider`。

---

## Task 9A.7：完善 DeepSeek fallback 的结构化输出

### 任务内容

DeepSeek 只用于复杂自然语言理解和自然语言总结，不直接执行任务。

DeepSeek 输出必须符合固定 JSON schema。

任务候选输出示例：

```json
{
  "intent": "go_to_waypoint",
  "waypoint_id": "wp_201",
  "confidence": 0.91,
  "need_confirm": true,
  "reply_text": "我识别到目标地点为二零一实验室，请确认是否执行。"
}
```

查询输出示例：

```json
{
  "intent": "query_robot_status",
  "confidence": 0.93,
  "need_confirm": false,
  "reply_text": "当前机器人在线，未触发急停，任务状态为空闲。"
}
```

### 验收标准

- DeepSeek 返回必须经过 JSON schema 校验；
- 非 JSON 输出不触发 mission；
- 低置信度输出不触发 mission；
- 非法 waypoint 不触发 mission；
- 控制类 intent 必须 `need_confirm=true`；
- 查询类 intent 可直接返回 `reply_text`；
- DeepSeek 失败时，系统返回明确错误，不影响规则解析已有能力。

---

## Task 9A.8：新增 `smart_command` 统一智能语音接口

### 任务内容

新增接口：

```http
POST /api/voice/smart_command
```

功能：

```text
输入文本 / ASR 结果
→ 规则解析优先
→ DeepSeek fallback
→ 查询数据 / 生成 mission_candidate / 生成 reply_text
→ 可选 TTS
```

返回示例：

```json
{
  "success": true,
  "data": {
    "recognized_text": "你是谁",
    "intent": "query_self_identity",
    "data_source": "robot_profile",
    "reply_text": "我是灵巡 Sentinel，一台配送巡检一体化智能机器人。",
    "need_confirm": false,
    "mission_candidate": null,
    "tts_generated": false
  }
}
```

### 验收标准

- “你是谁”能返回身份回复；
- “你能做什么”能返回能力回复；
- “现在天气怎么样”能返回天气回复；
- “当前机器人状态正常吗”能返回状态总结；
- “帮我送到二零一实验室”返回 mission_candidate，但不直接执行；
- 未知命令返回可理解的失败原因；
- 原有 `/api/voice/text_command`、`audio_command`、`record_command` 不被破坏。

---

## Task 9A.9：接入 TTS 语音播报

### 任务内容

新增 TTS 服务：

```text
backend/app/services/tts_service.py
```

新增接口：

```http
POST /api/voice/speak
GET /api/voice/tts/latest
```

支持后端配置：

```text
TTS_BACKEND=mock
TTS_BACKEND=online
TTS_BACKEND=local
```

第一版允许先做 mock TTS 或文本播报占位，但接口和状态字段要稳定。

### 验收标准

- `/api/voice/speak` 能接收文本；
- TTS 成功时返回音频路径、播放状态或占位结果；
- TTS 失败不影响 `reply_text` 返回；
- `smart_command` 可选择生成 TTS；
- Dashboard 能显示 TTS 状态；
- 若使用 RK3588 本地播放，需确认 `aplay` 或等效播放链路可用；
- TTS 不阻塞 mission 主流程。

---

## Task 9A.10：控制类命令确认机制收口

### 任务内容

明确智能语音助手的安全边界。

建议：

```text
可直接回答：
- query_self_identity
- query_capability
- query_robot_status
- query_task_status
- query_weather
- query_perception_status

可直接执行：
- pause_task

必须确认：
- go_to_waypoint
- start_patrol
- return_home

必须拒绝：
- 直接速度控制
- 关闭急停
- 忽略故障
- 撞过去
- 非法 waypoint
- 多地点歧义
- LLM 非 JSON
- ASR 空文本
- 公网控制未开启
- token 不合法
```

### 验收标准

- “暂停任务”可直接执行；
- “去二零一实验室”进入等待确认；
- 确认后才调用 mission；
- 取消后不调用 mission；
- “向前走一米”“开快一点”不会直接控制底盘；
- 公网控制关闭时，运动类命令不会执行；
- Dashboard 能显示“等待确认 / 已确认 / 已取消 / 已拒绝”。

---

## Task 9A.11：Dashboard 智能语音助手展示

### 任务内容

前端新增或增强“灵巡 Sentinel 智能语音助手”区域。

建议展示：

```text
机器人名称：灵巡 Sentinel
识别文本
解析 intent
数据来源
reply_text
TTS 状态
mission_candidate
确认 / 取消按钮
最近一次执行结果
错误原因
```

示例展示：

```text
识别文本：你是谁
意图：query_self_identity
数据来源：robot_profile
回复：我是灵巡 Sentinel，一台配送巡检一体化智能机器人。
TTS：已生成
```

任务类展示：

```text
识别文本：帮我送到二零一实验室
意图：go_to_waypoint
目标点：wp_201
状态：等待确认
操作：确认执行 / 取消
```

### 验收标准

- Dashboard 能显示机器人名称“灵巡 Sentinel”；
- Dashboard 能显示识别文本、intent、reply_text；
- 查询类命令有自然语言回复；
- 控制类命令有确认/取消按钮；
- TTS 状态可见；
- 错误信息可见；
- 原有任务状态、视觉检测、C 板状态不受影响。

---

## Task 9A.12：日志与测试语句集

### 任务内容

新增智能语音交互日志字段：

```text
request_id
recognized_text
intent
data_source
reply_text
need_confirm
mission_candidate
tts_status
error_reason
timestamp
```

整理测试语句集：

```text
你是谁
你能做什么
你可以自己控制底盘吗
当前机器人状态正常吗
视觉检测到了什么
现在天气怎么样
帮我送到二零一实验室
返回起点
暂停任务
开始巡检
向前走一米
去实验室
随便闲聊一句
```

### 验收标准

- 每次 `smart_command` 有日志；
- 身份类、状态类、天气类、视觉类、控制类、拒绝类语句均有测试覆盖；
- 失败原因可追踪；
- 测试语句结果符合预期；
- DeepSeek 或 TTS 失败不会导致后端崩溃。

---

# 4. 推荐执行顺序

```text
1. 建立 robot_profile.json
2. 新增身份与能力查询 intent
3. 清理 waypoint 歧义
4. 扩展查询类 intent
5. 新增 data_service / profile_provider / weather_provider
6. 新增天气接口
7. 完善 DeepSeek fallback 结构化输出
8. 新增 /api/voice/smart_command
9. 接入 TTS
10. 收口控制类确认机制
11. Dashboard 智能语音助手展示
12. 日志与测试语句集
```

---

# 5. 总体验收标准

Phase 9A 完成后，应满足：

1. 机器人名称固定为 **灵巡 Sentinel**；
2. 机器人能回答“你是谁”“你能做什么”；
3. 机器人能说明自己的安全边界；
4. 语音可以查询机器人状态；
5. 语音可以查询视觉检测结果；
6. 语音可以查询天气/环境数据；
7. DeepSeek 能基于结构化数据生成自然语言总结；
8. DeepSeek 不会直接控制机器人；
9. 运动类命令必须确认后才执行；
10. 非法、歧义、低置信度、非 JSON、空文本不会触发 mission；
11. TTS 能播报或返回语音合成结果；
12. Dashboard 能展示识别文本、意图、回复、TTS 状态、确认状态和错误原因；
13. 天气数据与未来 C 板传感器数据接口解耦；
14. 原有语音入口、mission bridge、YOLO、C 板状态展示不被破坏。

---

# 6. Codex 分轮 Prompt

## Round 1：机器人身份档案与身份查询

```text
Read AGENTS.md, README.md, and DO_PHASE9A.md.

Task:
Implement robot identity profile for Lingxun Sentinel.

Requirements:
1. Add backend/config/robot_profile.json.
2. Add profile_provider service to read robot profile.
3. Add or extend intent parsing for:
   - query_self_identity
   - query_capability
   - query_safety_rule
4. Replies should come from robot_profile, not hardcoded in scattered files.
5. Do not change mission_gateway behavior.
6. Do not add TTS yet.

Validation:
- “你是谁” returns Lingxun Sentinel identity.
- “你能做什么” returns abilities.
- “你可以自己控制底盘吗” returns safety boundary.
- No mission is triggered by identity/capability queries.

Only modify files required for robot identity and query handling.
```

## Round 2：Waypoint 歧义清理与查询类 intent 扩展

```text
Read AGENTS.md, README.md, and DO_PHASE9A.md.

Task:
Clean waypoint aliases and extend query intents.

Requirements:
1. Remove ambiguous waypoint aliases.
2. Ensure wp_201 and wp_001 do not share “201” or “实验室”.
3. Add or verify intents:
   - query_robot_status
   - query_task_status
   - query_battery
   - query_emergency_stop
   - query_perception_status
   - query_weather
4. Ambiguous waypoint should not trigger mission.
5. Unknown waypoint should not trigger mission.

Validation:
- “去二零一实验室” resolves to wp_201.
- “去一号点” resolves to wp_001.
- “去实验室” is ambiguous or rejected.
- “现在天气怎么样” resolves to query_weather.
- “你刚才看到了什么” resolves to query_perception_status.

Only modify waypoint/config/parser files required for this task.
```

## Round 3：data_service 与 weather_provider

```text
Read AGENTS.md, README.md, and DO_PHASE9A.md.

Task:
Add data_service, robot_status_provider, profile_provider, and weather_provider.

Requirements:
1. data_service should provide unified read access to:
   - robot profile
   - robot state
   - task status
   - detection status
   - alerts
   - weather data
2. Add GET /api/external/weather/latest.
3. Start with mock or configurable weather provider if real source is not available.
4. Weather data must include source and updated_at.
5. Do not let LLM invent weather data.
6. Do not change mission behavior.

Validation:
- GET /api/external/weather/latest returns structured data.
- data_service can read robot status from existing state_store.
- data_service can read profile data.
- Weather provider failure returns a structured error.

Only modify files required for data service and weather provider.
```

## Round 4：DeepSeek fallback 结构化输出与 smart_command

```text
Read AGENTS.md, README.md, and DO_PHASE9A.md.

Task:
Implement smart_command with rule-first and DeepSeek fallback.

Requirements:
1. Add POST /api/voice/smart_command.
2. Rule parser should run first.
3. DeepSeek should be used only as fallback for complex natural language.
4. DeepSeek output must pass JSON schema validation.
5. Control intents must require confirmation.
6. Query intents should return reply_text.
7. LLM failure must not trigger mission.
8. Illegal waypoint, low confidence, non-JSON output, and ambiguous targets must not trigger mission.

Validation:
- “你是谁” returns identity reply_text.
- “当前机器人状态正常吗” returns status summary.
- “现在天气怎么样” returns weather summary.
- “帮我送到二零一实验室” returns mission_candidate with need_confirm=true.
- LLM malformed output does not trigger mission.

Only modify smart command / LLM / voice service files required for this task.
```

## Round 5：TTS 接入

```text
Read AGENTS.md, README.md, and DO_PHASE9A.md.

Task:
Add TTS service for Lingxun Sentinel voice replies.

Requirements:
1. Add tts_service.
2. Support TTS_BACKEND=mock at minimum.
3. Add POST /api/voice/speak.
4. Add GET /api/voice/tts/latest if needed.
5. smart_command may optionally generate TTS from reply_text.
6. TTS failure must not break text reply.
7. Do not block mission execution on TTS.

Validation:
- POST /api/voice/speak accepts text.
- TTS mock returns success or a placeholder audio/result.
- smart_command can return tts_status.
- TTS error path is handled gracefully.

Only modify files required for TTS.
```

## Round 6：Dashboard 智能语音助手展示与确认收口

```text
Read AGENTS.md, README.md, and DO_PHASE9A.md.

Task:
Update Dashboard for Lingxun Sentinel smart voice assistant.

Requirements:
1. Show robot name: 灵巡 Sentinel.
2. Show recognized_text, intent, data_source, reply_text, tts_status.
3. Show mission_candidate when a control command is parsed.
4. Provide confirm/cancel controls for motion commands.
5. Show error_reason when command is rejected.
6. Do not redesign unrelated Dashboard sections.
7. Do not break existing voice, mission, YOLO, C-board state display.

Validation:
- Identity query result is visible.
- Weather query result is visible.
- Robot status query result is visible.
- Motion command shows waiting confirmation.
- Confirm triggers mission, cancel does not.
- Existing Dashboard cards still work.

Only modify frontend files and minimal backend response fields if required.
```

## Round 7：日志、测试语句与文档收口

```text
Read AGENTS.md, README.md, and DO_PHASE9A.md.

Task:
Add logs, test cases, and documentation for Phase 9A.

Requirements:
1. Add smart voice interaction logging fields:
   - request_id
   - recognized_text
   - intent
   - data_source
   - reply_text
   - need_confirm
   - mission_candidate
   - tts_status
   - error_reason
   - timestamp
2. Add tests or manual test notes for identity, status, weather, perception, control, and rejection cases.
3. Update README with Phase 9A usage.
4. Document safety rules.
5. Document that DeepSeek does not directly control robot motion.

Validation:
- Test phrases cover all major categories.
- Logs are written for smart_command.
- README describes robot identity, smart command, weather query, TTS, and confirmation flow.
- Existing tests still pass.

Only modify files required for logs, tests, and documentation.
```
