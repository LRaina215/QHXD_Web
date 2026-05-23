# PHASE7 DONE - DeepSeek V4 语音语义解析接入

## 阶段定位

Phase 7 在 Phase 4B 语音识别链路之上，增加 DeepSeek V4 API 作为语音文本的语义解析 fallback。

本阶段没有让 LLM 直接控制底盘、RT-Thread、NUC 或 mission bridge。当前设计是：

1. FunASR / mock ASR 得到文本；
2. 本地规则解析器优先解析简单固定命令；
3. 复杂自然语言在 `LLM_ENABLE=true` 或请求显式 `use_llm=true` 时调用 DeepSeek；
4. DeepSeek 只输出结构化 JSON 意图；
5. 本地安全校验通过后才进入现有 `mission_gateway`；
6. 移动类任务默认进入待确认队列，不会立即执行。

## 已完成内容

- 新增 DeepSeek V4 API 配置、客户端、Prompt、Schema 与安全校验模块。
- 新增 LLM 语义解析入口，并保留规则解析优先策略。
- 新增语音移动类命令二次确认机制。
- 扩展 `/api/voice/text_command`、`/api/voice/audio_command`、`/api/voice/record_command` 的 LLM 相关返回字段。
- 新增 `/api/voice/confirm_command` 用于确认或取消待执行语音命令。
- 扩展查询类意图：`query_status`、`query_task`、`query_detection`。
- 更新 README 中 DeepSeek V4 API 配置、接口用法与安全说明。
- 增加单元测试覆盖：复杂自然语言确认后执行、未知语义不触发任务、取消确认不触发任务。
- 真实环境已验证 DeepSeek API 可用，并处理了 RK3588 上 Python urllib TLS 失败但 curl 可访问的问题。
- `.env.example` 已恢复为占位 key，真实 `DEEPSEEK_API_KEY` 只应放在 `.env` 或环境变量中。

## 关键实现

### 1. LLM 客户端与环境变量加载

新增文件：`backend/app/services/voice/llm_client.py`

- 第 13-30 行：启动时从项目根目录或 `backend/` 下的 `.env` 读取环境变量，但不打印、不记录 API Key。
- 第 40-56 行：定义 `LLMClientConfig`，只有 `LLM_BACKEND=deepseek`、`LLM_ENABLE=true` 或强制启用、并且存在 `DEEPSEEK_API_KEY` 时才启用。
- 第 69-95 行：读取 DeepSeek 配置，包括 `DEEPSEEK_BASE_URL`、`DEEPSEEK_MODEL`、超时、token、temperature、debug raw。
- 第 97-145 行：新增 curl fallback。RK3588 上实测 `curl` 可以访问 DeepSeek，但 Python urllib 出现 TLS EOF，因此在 urllib 失败时使用 `curl --config` 兜底。
- 第 148-190 行：调用 OpenAI-compatible `/v1/chat/completions`，使用 `response_format={"type":"json_object"}` 获取 JSON 输出。

安全注意：curl fallback 会临时生成包含 Authorization header 的 config 文件，函数退出时第 127-130 行会删除临时文件；真实 key 不会作为命令行参数暴露。

### 2. LLM 输出 Schema 与 Prompt

新增文件：`backend/app/services/voice/llm_schema.py`

- 第 6-16 行：白名单 intent：`go_to_waypoint`、`start_patrol`、`pause_task`、`resume_task`、`return_home`、`query_status`、`query_task`、`query_detection`、`unknown`。
- 第 18-30 行：白名单 command、移动类命令与低风险命令集合。
- 第 33-66 行：`LLMIntent` 数据结构与 `from_dict()`，对 confidence、missing_slots 等字段做基础规整。

新增文件：`backend/app/services/voice/llm_prompt.py`

- 第 8-15 行：System prompt 限制 LLM 只能做机器人语音命令解析，只输出 JSON，不能编造 waypoint，不能生成代码或 shell 命令。
- 第 17-27 行：定义期望 JSON 字段。
- 第 30-52 行：把当前 `waypoints.json` 中的 waypoint 列表注入 prompt，并写入安全规则。

### 3. LLM 安全校验

新增文件：`backend/app/services/voice/llm_safety.py`

- 第 21-30 行：读取 `LLM_CONFIDENCE_THRESHOLD` 与 `LLM_REQUIRE_CONFIRM_FOR_MOTION`。
- 第 33-76 行：本地安全校验主逻辑。
- 第 37-44 行：拒绝非白名单 intent / command 和低置信度输出。
- 第 45-57 行：拒绝缺少槽位、非法 waypoint 或无法唯一匹配的目标点。
- 第 62-66 行：移动类任务强制确认，查询/暂停/继续等低风险命令不强制确认。
- 第 78-87 行：安全拒绝统一转为 `intent=unknown`，不触发 mission。

### 4. LLM 解析器接入规则解析器之后

新增文件：`backend/app/services/voice/llm_intent_parser.py`

- 第 20-31 行：先调用本地规则解析器，再根据配置和文本复杂度决定是否调用 LLM。
- 第 32-43 行：LLM 未启用、缺 key、超时或调用失败时失败安全，不触发复杂未知任务。
- 第 45-58 行：LLM 输出不是合法 JSON 时拒绝执行。
- 第 60-82 行：LLM 输出必须通过 `llm_safety_validator` 后才转换为 `ParsedIntent`。
- 第 84-93 行：`use_llm=false` 会强制禁用 LLM；简单高置信规则命令优先保留规则结果。
- 第 95-99 行：对“帮我、样品、送到、请你”等复杂自然语言标记启用 LLM fallback。

修改文件：`backend/app/services/intent_parser.py`

- 第 7-17 行：`ParsedIntent` 增加 `parser`、`llm_backend`、`llm_model`、`llm_raw_output`，用于接口返回和调试追踪。

### 5. Waypoint 能力补充

修改文件：`backend/app/services/waypoint_resolver.py`

- 第 27-28 行：新增 `list_waypoints()`，供 prompt 注入当前可用地点列表。
- 第 30-33 行：新增 `waypoint_exists()`，供 LLM 安全校验确认目标点真实存在。

### 6. 语音入口与二次确认机制

修改文件：`backend/app/services/voice_entry.py`

- 第 25-26 行：定义移动类意图和查询类意图集合。
- 第 29-35 行：新增 `PendingVoiceCommand`。
- 第 40-41 行：新增内存 pending 命令缓存。
- 第 43-57 行：`handle_text_command()` 改为调用 LLM-aware parser；移动类且需要确认的命令只生成 `pending_command_id`，不立即执行。
- 第 79-120 行：新增 `confirm_pending_command()`，支持确认执行或取消 pending 命令。
- 第 122-140 行：新增状态、任务、视觉检测查询类语音意图处理。
- 第 142-166 行：仍然复用已有 `mission_gateway` 执行任务，不绕过现有任务入口。
- 第 168-190 行：pending 命令带 TTL，默认由 `VOICE_PENDING_TTL_SECONDS=30` 控制。
- 第 202-225 行：统一返回 `parser`、`llm_backend`、`llm_model`、`llm_raw_output`、`pending_command_id`。

### 7. API Schema 与路由扩展

修改文件：`backend/app/schemas.py`

- 第 182-186 行：`VoiceTextCommandRequest` 增加 `use_llm`。
- 第 189-202 行：`VoiceCommandResult` 增加 LLM 追踪字段和 `pending_command_id`。
- 第 210-229 行：`VoiceAudioCommandResult` 增加同样的 LLM 追踪字段和 `pending_command_id`。
- 第 237-242 行：`VoiceRecordCommandRequest` 增加 `use_llm`。
- 第 261-269 行：新增 `VoiceConfirmCommandRequest` 与 `VoiceConfirmCommandResponse`。

修改文件：`backend/app/main.py`

- 第 255-307 行：`_voice_result_from_asr()` 增加 `use_llm` 参数，并把 LLM 字段映射到 audio/record 响应。
- 第 368-373 行：`/api/voice/text_command` 使用新的语音入口。
- 第 387-392 行：新增 `/api/voice/confirm_command`。
- 第 395-416 行：`/api/voice/audio_command` 支持 multipart 字段 `use_llm`。
- 第 422-476 行：`/api/voice/record_command` 支持 JSON 字段 `use_llm`。

修改文件：`backend/app/services/asr_service.py`

- 第 33-39 行：mock ASR 文本链路保留 `use_llm` 字段，避免 mock 测试绕过 LLM 控制。

### 8. README 与配置

修改文件：`.env.example`

- 第 1-17 行：新增 DeepSeek 与 LLM 安全配置示例。
- 第 5 行保持占位：`DEEPSEEK_API_KEY=your_deepseek_api_key_here`。

修改文件：`.gitignore`

- 第 29-33 行：忽略 `.env` 和 `.env.*`，但保留 `.env.example` 与 `backend/.env.example` 可提交。

修改文件：`README.md`

- 第 36-38 行：说明 DeepSeek 只用于 ASR 文本后的语义解析 fallback，不直接控制底盘。
- 第 40-51 行：说明真实 API Key 不允许提交，只能放入 `.env` 或环境变量。
- 第 55-60 行：给出 DeepSeek 启动环境变量示例。
- 第 63-75 行：列出后端读取的 LLM 配置变量。
- 第 77-87 行：推荐 `deepseek-v4-flash`，必要时可切换 `deepseek-v4-pro`。
- 第 89 行：说明无 key、LLM 关闭、API 失败、非 JSON、低置信度、非法 waypoint 都不会触发 mission。
- 第 91-115 行：补充 `/api/voice/text_command`、`/api/voice/confirm_command`、`/api/voice/audio_command`、`/api/voice/record_command` 的 LLM 用法。

### 9. 单元测试

修改文件：`backend/tests/test_phase1.py`

- 第 36-46 行：引入确认请求、LLM mock 响应和 LLM parser 模块。
- 第 340-396 行：测试复杂自然语言“帮我把样品送到二零一实验室”先生成 pending，确认后才执行 `go_to_waypoint`。
- 第 398-436 行：测试未知 LLM 结果不会触发 mission。
- 第 438-482 行：测试 pending 命令取消后不会触发 mission。

## 接口行为

### 文本命令

```bash
curl -X POST http://127.0.0.1:8000/api/voice/text_command \
  -H 'Content-Type: application/json' \
  -d '{"text":"帮我把样品送到二零一实验室","source":"text-debug","requested_by":"operator","use_llm":true}'
```

移动类 LLM 结果默认返回：

```json
{
  "accepted": false,
  "need_confirm": true,
  "parser": "llm",
  "pending_command_id": "voice_pending_xxx"
}
```

### 确认执行

```bash
curl -X POST http://127.0.0.1:8000/api/voice/confirm_command \
  -H 'Content-Type: application/json' \
  -d '{"pending_command_id":"voice_pending_xxx","confirmed":true,"requested_by":"operator"}'
```

### 取消执行

```bash
curl -X POST http://127.0.0.1:8000/api/voice/confirm_command \
  -H 'Content-Type: application/json' \
  -d '{"pending_command_id":"voice_pending_xxx","confirmed":false,"requested_by":"operator"}'
```

### 音频上传与录音

- `/api/voice/audio_command`：multipart form 可带 `use_llm=true`。
- `/api/voice/record_command`：JSON body 可带 `"use_llm": true`。

## 真实 DeepSeek 验收结果

当前环境已配置真实 DeepSeek API Key，并完成真实调用测试。真实 key 未写入仓库文档。

### DeepSeek 配置读取

实测配置读取结果：

```text
llm_backend deepseek
llm_enabled True
has_api_key True
base_url https://api.deepseek.com
model deepseek-v4-flash
timeout_seconds 5.0
```

### 网络与 TLS 情况

- `curl --noproxy '*' -I https://api.deepseek.com` 可访问，返回 HTTP 401，说明网络与服务入口正常。
- Python urllib 在 RK3588 上曾出现 `SSLEOFError: UNEXPECTED_EOF_WHILE_READING`。
- 已在 `llm_client.py` 增加 curl fallback，真实 LLM 调用随后通过。

### 语义解析实测

输入：`帮我把样品送到二零一实验室`

```text
parser llm
intent go_to_waypoint
payload {'waypoint_id': 'wp_201'}
confidence 0.95
need_confirm True
llm_backend deepseek
llm_model deepseek-v4-flash
```

输入：`今天天气不错`

```text
parser llm
intent unknown
confidence 0.1
need_confirm True
```

输入：`给我写一段代码`

```text
parser llm
intent unknown
confidence 0.0
need_confirm True
```

### 端到端语音任务流实测

```text
simple_rule_parser rule
simple_accepted True
simple_intent pause_task

complex_parser llm
complex_accepted_before_confirm False
complex_intent go_to_waypoint
complex_waypoint wp_201
complex_need_confirm True
pending_command_id_present True

unsafe_parser llm
unsafe_accepted False
unsafe_intent unknown

confirmed_accepted True
confirmed_command go_to_waypoint
confirmed_task_type go_to_waypoint
```

## 自动化验证

### Python 编译检查

已执行后端相关 Python 文件编译检查，未发现语法错误。

### 单元测试

执行命令：

```bash
cd /home/robomaster/QHXD/backend
python3 -m unittest tests/test_phase1.py
```

结果：

```text
Ran 24 tests in 0.741s
OK
```

### 后端启动检查

已验证后端可启动并返回健康状态：

```text
{"status":"ok"}
```

### 无 Key / LLM 关闭场景

已验证未配置 `DEEPSEEK_API_KEY` 或 `LLM_ENABLE=false` 时后端不会启动失败，LLM client 状态为 disabled，语音命令保持规则解析路径。

### 密钥扫描

已对以下路径做过真实 key 模式扫描：

```text
.env.example
README.md
PHASE7_DONE.md
backend/
```

扫描未发现真实 DeepSeek key 常见写法，例如环境变量、代码字段或 Authorization header 中直接携带真实 key。`.env.example` 目前第 5 行是占位值。

## 安全边界

- LLM 不直接调用底盘、串口、RT-Thread、NUC 或 shell。
- LLM 只能输出白名单 JSON 意图。
- LLM 输出必须经过本地安全校验。
- 非 JSON、低置信度、未知 intent、非法 command、非法 waypoint、缺少槽位都会拒绝执行。
- `go_to_waypoint`、`start_patrol`、`return_home` 默认需要二次确认。
- pending 命令默认 30 秒过期。
- 取消 pending 命令不会触发 mission。
- 真实 DeepSeek API Key 不进入 Git，不写入 README 或 DONE 文档。

## 未改变内容

- 未修改 FunASR 模型加载和音频识别主逻辑。
- 未修改 YOLO、摄像头、Hik/USB 图像采集链路。
- 未修改 RKNN runtime。
- 未修改 RT-Thread 下位机协议。
- 未修改 NUC bridge 或 mission bridge 的任务语义。
- 未让 LLM 生成可执行代码或命令。
- 未让 LLM 绕过 `mission_gateway` 直接控制机器人。

## 后续建议

1. 在真实验收时继续保留 `LLM_REQUIRE_CONFIRM_FOR_MOTION=true`。
2. 若 DeepSeek 延迟不稳定，可适当调大 `DEEPSEEK_TIMEOUT_SECONDS`，但不建议超过语音交互可接受范围太多。
3. 若自然语言目标点解析不稳定，应优先补充 `app/config/waypoints.json` 中的 aliases，而不是放宽安全校验。
4. 若未来增加更多机器人任务，先扩展白名单 schema 和 safety validator，再接入 mission gateway。
5. 真实 API Key 只放 `.env` 或系统环境变量；提交代码前继续执行密钥扫描。
