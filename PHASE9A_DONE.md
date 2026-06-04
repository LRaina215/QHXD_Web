# PHASE9A_DONE.md

# Phase 9A：灵巡 Sentinel 智能语音助手与身份认知闭环完成记录

## 完成概览

Phase 9A 已将现有语音入口升级为受控型智能语音助手链路：

```text
文本 / ASR 结果
-> 规则解析优先
-> DeepSeek fallback
-> 本地 schema 与安全校验
-> 查询数据 / 生成 mission_candidate
-> 可选 TTS
-> Dashboard 展示结果与确认状态
```

机器人正式身份固定为 **灵巡 Sentinel**。查询类命令只回答，不触发 mission；运动类任务必须进入确认流程；直接速度控制和危险命令会被拒绝。

## 关键改动

### 机器人身份与 waypoint 清理

- `backend/app/config/robot_profile.json:1` 新增统一身份档案，包含 `robot_name=灵巡`、`english_name=Sentinel`、能力列表、安全规则和自我介绍。
- `backend/app/config/waypoints.json:1` 清理 waypoint 别名：`wp_201` 独占 `201/二零一/二零一实验室`，`wp_001` 不再包含 `201` 或 `实验室` 等歧义别名，`home` 增加 `装载点/返回点`。

### 后端 schema 与接口

- `backend/app/schemas.py:25` 扩展语音 intent，加入身份、能力、安全规则、机器人状态、任务状态、电量、急停、视觉、天气和环境查询类 intent。
- `backend/app/schemas.py:155` 新增 `RobotProfile`；`backend/app/schemas.py:166` 新增 `WeatherData`。
- `backend/app/schemas.py:318` 新增 `TTSStatus`；`backend/app/schemas.py:327` 新增 `SmartCommandRequest/SmartCommandResult/SmartCommandResponse`。
- `backend/app/main.py:478` 新增 `GET /api/external/weather/latest`。
- `backend/app/main.py:498` 新增 `POST /api/voice/smart_command`。
- `backend/app/main.py:525` 新增 `POST /api/voice/speak`。
- `backend/app/main.py:530` 新增 `GET /api/voice/tts/latest`。

### 数据聚合与智能语音服务

- `backend/app/services/profile_provider.py:7` 新增 profile provider，集中读取 `robot_profile.json` 并生成身份、能力、安全边界回复。
- `backend/app/services/weather_provider.py:7` 新增天气 provider，当前通过环境变量/mock 配置返回结构化天气，`source=weather_provider`。
- `backend/app/services/robot_status_provider.py:6` 新增机器人状态 provider，从 `state_store`、任务、告警、视觉检测状态生成自然语言摘要。
- `backend/app/services/data_service.py:7` 新增统一数据读取层，避免 DeepSeek 直接拼凑零散接口数据。
- `backend/app/services/tts_service.py:7` 新增 TTS 服务，当前稳定支持 `TTS_BACKEND=mock`，未实现的 backend 返回非阻塞占位状态。
- `backend/app/services/smart_voice_service.py:13` 新增 smart command 主流程，负责 query 回复、mission_candidate 生成、TTS 触发和 JSONL 日志。

### 解析、安全和 LLM fallback

- `backend/app/services/intent_parser.py:23` 扩展规则解析：身份、能力、安全、天气、视觉、任务、状态、电量、急停等查询优先本地解析。
- `backend/app/services/intent_parser.py:52` 对 `向前走/走一米/开快/撞过去/底盘速度` 等直接速度或危险控制请求做本地高置信度拒绝。
- `backend/app/services/voice/llm_intent_parser.py:88` 对高置信度本地 `unknown` 安全拒绝停止 LLM fallback，防止危险命令被二次解释。
- `backend/app/services/voice/llm_schema.py` 与 `backend/app/services/voice/llm_prompt.py` 扩展结构化 intent schema 和提示词，要求 DeepSeek 输出固定 JSON，不能直接控制底盘。
- `backend/app/services/voice_entry.py:27` 扩展查询 intent 集合；`backend/app/services/voice_entry.py:141` 查询类回复改由 `data_service` 统一生成。

### Dashboard 展示

- `frontend/src/App.vue:156` 新增 smart command/TTS 类型定义。
- `frontend/src/App.vue:1119` 新增 `sendSmartCommand()`，调用 `/api/voice/smart_command` 并复用原确认弹窗处理 `mission_candidate`。
- `frontend/src/App.vue:1838` 在命令面板新增“智能助手解析”按钮。
- `frontend/src/App.vue:1879` 新增“灵巡 Sentinel 智能语音助手”展示区，显示 reply、recognized_text、intent、data_source、TTS、mission_candidate 和错误原因。
- `frontend/src/style.css:1168` 新增智能助手卡片样式。

### 云端 gateway 与文档

- `cloud_gateway/cloud_gateway.py:49` 公网写路径加入 `/api/voice/smart_command` 与 `/api/voice/speak`。
- `cloud_gateway/cloud_gateway.py:65` 公网白名单加入 `/api/external/weather/latest`、`/api/voice/smart_command`、`/api/voice/speak`、`/api/voice/tts/latest`。
- `README.md:263` 更新接口清单；`README.md:305` 新增“灵巡 Sentinel 智能助手”说明；`README.md:438` 记录天气接口；`README.md:462` 记录 TTS 配置；`README.md:807` 增加 Phase 9A 验收命令。
- `.env.example` 增加 `TTS_BACKEND` 与天气 mock 配置。
- `.gitignore` 增加 `backend/data/*.jsonl`，避免智能语音交互日志进入 git。

## 验收结果

### 后端单测

在 RK3588 `/home/robomaster/QHXD` 执行：

```bash
PYTHONPATH=backend python3 -m unittest backend.tests.test_phase1 -v
```

结果：

```text
Ran 26 tests in 0.736s
OK
```

覆盖了身份、天气、TTS、smart command、运动候选确认、直接速度命令拒绝、原有语音命令与任务流。

### 前端构建

在 RK3588 `/home/robomaster/QHXD/frontend` 执行：

```bash
npm run build
```

结果：

```text
vue-tsc --noEmit && vite build
✓ built in 2.13s
```

### RK3588 本地接口验收

`qhxd-backend` 已重启并保持 active。

已验证：

- `GET /health` 返回 `{"status":"ok"}`。
- `GET /api/external/weather/latest` 返回结构化天气数据，包含 `location/temperature_c/humidity_percent/weather/wind/source/updated_at`。
- `POST /api/voice/smart_command {"text":"你是谁","generate_tts":true}` 返回 `intent=query_self_identity`、`data_source=robot_profile`，并生成 mock TTS 状态。
- `POST /api/voice/smart_command {"text":"今天天气怎么样"}` 返回 `intent=query_weather`、`data_source=weather_provider`。
- `POST /api/voice/smart_command {"text":"帮我送到二零一实验室"}` 返回 `intent=go_to_waypoint`、`need_confirm=true`、`mission_candidate.payload.waypoint_id=wp_201`，未直接执行 mission。
- `POST /api/voice/smart_command {"text":"向前走一米"}` 返回 `intent=unknown`、`parser=rule`、`mission_candidate=null`，未触发底盘控制。
- `GET /api/voice/tts/latest` 可读取最近一次 mock TTS 状态。

### 云端中继与公网前端部署

- 云服务器 `/opt/lingxun-cloud-gateway/cloud_gateway.py` 已同步并重启 `lingxun-cloud-gateway`。
- 云端本机 `http://127.0.0.1:9000/api/state/latest` 返回 200。
- 云端本机 `http://127.0.0.1:9000/api/external/weather/latest` 返回 200。
- 通过云端本机 HTTPS + `Authorization: Bearer <PUBLIC_API_TOKEN>` 验证 `POST /api/voice/smart_command`，可反代到 RK3588 并返回 `query_self_identity`。
- 云服务器本机 HTTPS 自检：
  - `https://lingxunrobot.cn/` 返回前端 HTML。
  - `https://lingxunrobot.cn/api/external/weather/latest` 返回 200。
- 新前端 `dist` 已发布到 `/var/www/lingxunrobot/`。

注意：从当前 Mac 网络直接 `curl https://lingxunrobot.cn` 时出现连接 reset，但云端 nginx 本机 HTTPS 自检和运行日志显示前端/API/WS 均可命中。若外网浏览器仍异常，应继续排查公网网络链路、证书链路或运营商/安全策略。

## 已知边界

- TTS 当前为 `mock`，接口和状态字段稳定，但尚未接真实语音合成或本地播放。
- 天气数据当前来自配置/mock provider，不是机器人本体环境传感器；后续 C 板环境数据接入后可替换/叠加。
- DeepSeek 只参与结构化理解和总结，不能绕过本地 mission 校验与确认流程。
- 运动类命令仍由原 mission bridge 执行，Phase 9A 未改底盘控制链路。

## Phase 9A 入口收口补充

根据实际前端使用反馈，已继续修正智能助手入口和开放问答能力：

- `backend/app/schemas.py:28` 增加 `query_assistant_model`；`backend/app/schemas.py:37` 增加 `open_chat`。
- `backend/app/services/data_service.py:20` 增加助手模型配置回复，“你使用的模型是什么”会返回当前 DeepSeek backend/model，而不是误答机器人身份。
- `backend/app/services/intent_parser.py:26` 增加模型查询规则，优先走本地配置。
- `backend/app/services/voice/llm_prompt.py:5` 将 DeepSeek 定位从“只能解析固定命令”调整为“受控型智能语音助手”，允许在 JSON 的 `reply_text` 中返回自然语言回答。
- `backend/app/services/voice/llm_safety.py:47` 增加 `open_chat` 安全校验：只能返回回答，不能生成 mission candidate。
- `backend/app/services/smart_voice_service.py:38` 增加 `open_chat` 处理，直接展示 DeepSeek `reply_text`。
- `backend/app/main.py:543` 新增 `POST /api/voice/smart_audio_command`，音频 ASR 后直接进入智能助手。
- `backend/app/main.py:572` 新增 `POST /api/voice/smart_record_command` 与 `POST /api/robot/voice/onboard_smart_command`，车载麦克风录音后直接进入智能助手。
- `cloud_gateway/cloud_gateway.py:53` 增加公网 `browser_smart/onboard_smart/smart_audio` 白名单与转发。
- `frontend/src/App.vue:1081` 将“发送文本命令”改为默认调用 `/api/voice/smart_command`。
- `frontend/src/App.vue:1215` 将板端录音改为 `/api/voice/smart_record_command`。
- `frontend/src/App.vue:1325` 将网页麦克风改为 `/api/voice/browser_smart_command`。
- `frontend/src/App.vue:1354` 将车载麦克风改为 `/api/robot/voice/onboard_smart_command`。

新增验收：

- “你使用的模型是什么”返回 `query_assistant_model`，回复包含 `DeepSeek` 和 `deepseek-v4-flash`。
- “请用一句话解释你如何协助导航”返回 `open_chat`，`data_source=deepseek`，不生成 `mission_candidate`。
- “帮我送到二零一实验室”仍返回 `mission_candidate` 且 `need_confirm=true`。
- “向前走一米”仍由本地规则拒绝，不经过 DeepSeek，不触发 mission。
- 前端不再需要单独“智能助手解析”按钮；文本、网页麦克风、车载麦克风默认进入智能助手。
