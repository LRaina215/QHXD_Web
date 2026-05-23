# DO_PHASE6.md

# Phase 6：DeepSeek V4 API 语义解析接入

## 0. 阶段定位

当前语音链路已经完成：

```text
RK3588 USB 麦克风
→ /api/voice/record_command
→ FunASR 本地识别
→ recognized_text
→ 规则 intent_parser / waypoint_resolver
→ mission_gateway
→ 任务状态回显
```

Phase 6 的目标不是重新做 ASR，也不是让大模型直接控制机器人，而是在现有语音识别结果之后接入 **DeepSeek V4 API**，用于处理更复杂的自然语言语义解析。

目标链路：

```text
FunASR recognized_text
→ 规则解析优先
→ 规则无法稳定解析时调用 DeepSeek V4 API
→ LLM 输出严格 JSON
→ 本地安全校验
→ 复用现有 voice_entry_service / mission_gateway
```

本阶段只做：

```text
ASR 文本 → LLM 语义解析 → 结构化任务意图 → 本地校验 → 现有任务链路
```

本阶段不做：

```text
LLM 直接控制底盘
LLM 直接调用 RT-Thread
LLM 自由规划多步任务
OpenClaw
浏览器本地录音
唤醒词
连续对话智能体
```

---

## 1. DeepSeek V4 API 接入策略

### 1.1 当前选择

本阶段采用 **DeepSeek V4 API**，不做本地 LLM 部署。

推荐默认模型：

```bash
DEEPSEEK_MODEL=deepseek-v4-flash
```

如果需要更强语义理解能力，可切换为：

```bash
DEEPSEEK_MODEL=deepseek-v4-pro
```

DeepSeek API 使用 OpenAI-compatible Chat Completions 形式，默认 base URL：

```bash
https://api.deepseek.com
```

模型可使用：

```text
deepseek-v4-flash
deepseek-v4-pro
```

---

## 2. API Key 与配置位置要求

## 2.1 严禁事项

严禁将真实 API Key 写入：

```text
代码文件
前端文件
README 明文
Git 仓库
测试文件
提交记录
```

特别禁止：

```python
api_key = "sk-xxxx"
```

或：

```ts
const API_KEY = "sk-xxxx"
```

---

## 2.2 必须预留的 API Key 位置

需要在项目根目录或后端目录中提供：

```text
.env.example
```

只允许写占位符，不允许写真实密钥。

示例内容：

```bash
# DeepSeek V4 API configuration
LLM_BACKEND=deepseek
DEEPSEEK_API_KEY=your_deepseek_api_key_here
DEEPSEEK_BASE_URL=https://api.deepseek.com
DEEPSEEK_MODEL=deepseek-v4-flash
DEEPSEEK_TIMEOUT_SECONDS=5
DEEPSEEK_MAX_TOKENS=512
DEEPSEEK_TEMPERATURE=0.1
DEEPSEEK_ENABLE=true

# LLM safety
LLM_CONFIDENCE_THRESHOLD=0.75
LLM_REQUIRE_CONFIRM_FOR_MOTION=true
LLM_FALLBACK_TO_RULE=true
```

真实运行时由操作者在服务器环境变量或本地 `.env` 文件中配置：

```bash
export LLM_BACKEND=deepseek
export DEEPSEEK_API_KEY="真实 key 放这里，不提交 Git"
export DEEPSEEK_BASE_URL="https://api.deepseek.com"
export DEEPSEEK_MODEL="deepseek-v4-flash"
```

---

## 2.3 README 必须写清楚的位置

Codex 必须在 README 中新增一节：

```md
## DeepSeek V4 API 配置
```

该节必须明确说明：

1. 真实 API Key 不允许提交 Git。
2. 配置示例在 `.env.example`。
3. 真实运行时通过环境变量或 `.env` 提供。
4. 后端读取以下变量：

```bash
DEEPSEEK_API_KEY
DEEPSEEK_BASE_URL
DEEPSEEK_MODEL
DEEPSEEK_TIMEOUT_SECONDS
DEEPSEEK_MAX_TOKENS
DEEPSEEK_TEMPERATURE
```

5. 推荐模型：

```bash
DEEPSEEK_MODEL=deepseek-v4-flash
```

6. 如果语义解析效果不够，再切换：

```bash
DEEPSEEK_MODEL=deepseek-v4-pro
```

7. 如果没有配置 `DEEPSEEK_API_KEY`，后端必须自动降级到规则解析，不允许启动失败。

---

## 3. 模块设计要求

建议新增或整理以下模块：

```text
backend/app/services/voice/
├── llm_client.py
├── llm_intent_parser.py
├── llm_schema.py
├── llm_safety.py
└── llm_prompt.py
```

### 3.1 `llm_client.py`

职责：

- 读取 DeepSeek API 环境变量
- 调用 OpenAI-compatible Chat Completions API
- 设置超时
- 捕获 API 错误
- 返回模型原始输出

要求：

- API Key 只能从环境变量读取
- 不允许前端参与 DeepSeek API 调用
- 不允许在日志中打印完整 API Key
- API 失败时必须返回结构化错误，不得抛出未处理异常

---

### 3.2 `llm_prompt.py`

职责：

- 构造 system prompt
- 构造 user prompt
- 强制模型只输出 JSON
- 注入当前 waypoint 列表
- 注入允许的 intent 列表

允许的 intent 第一版只包括：

```text
go_to_waypoint
start_patrol
pause_task
resume_task
return_home
query_status
query_task
query_detection
unknown
```

---

### 3.3 `llm_schema.py`

职责：

定义 LLM 输出结构。

LLM 必须输出如下 JSON：

```json
{
  "intent": "go_to_waypoint",
  "command": "go_to_waypoint",
  "waypoint_alias": "201实验室",
  "waypoint_id": "wp_201",
  "confidence": 0.92,
  "need_confirm": true,
  "reason": "用户表达了将物品送往201实验室的意图",
  "missing_slots": [],
  "ask_text": null
}
```

未知或不确定时：

```json
{
  "intent": "unknown",
  "command": null,
  "waypoint_alias": null,
  "waypoint_id": null,
  "confidence": 0.3,
  "need_confirm": true,
  "reason": "无法确定用户要执行的机器人任务",
  "missing_slots": ["target_waypoint"],
  "ask_text": "请问你要让机器人去哪个位置？"
}
```

---

### 3.4 `llm_safety.py`

职责：

对 LLM 输出做本地安全校验。

必须检查：

```text
intent 是否在白名单
command 是否在白名单
waypoint_id 是否存在
confidence 是否达到阈值
移动类任务是否需要确认
是否出现多个目标点
是否缺少必要槽位
是否包含不允许执行的动作
```

移动类命令默认需要确认：

```text
go_to_waypoint
start_patrol
return_home
```

可直接执行或低风险命令：

```text
query_status
query_task
query_detection
pause_task
resume_task
```

如果校验失败，不能调用 mission_gateway。

---

### 3.5 `llm_intent_parser.py`

职责：

- 接收 recognized_text
- 优先调用现有规则解析器
- 规则解析失败或低置信度时调用 LLM
- 返回统一解析结果

逻辑：

```text
recognized_text
→ rule_parser
→ 如果规则成功且高置信度，直接返回
→ 如果规则失败或 ambiguous，调用 DeepSeek V4
→ 解析 JSON
→ 本地安全校验
→ 返回统一 VoiceCommandResult
```

---

## 4. 接口接入要求

### 4.1 不新增复杂接口，优先复用现有语音接口

现有接口：

```text
POST /api/voice/text_command
POST /api/voice/audio_command
POST /api/voice/record_command
```

本阶段要求在这些接口内部增加可选 LLM 解析能力。

建议新增参数：

```json
{
  "use_llm": true
}
```

或者通过环境变量控制：

```bash
LLM_ENABLE=true
```

推荐行为：

```text
LLM_ENABLE=false：只用规则解析
LLM_ENABLE=true：规则解析失败时启用 LLM
use_llm=true：本次请求允许启用 LLM
use_llm=false：本次请求禁用 LLM
```

---

### 4.2 返回结果要求

语音接口返回中需要增加 LLM 相关字段：

```json
{
  "recognized_text": "帮我把样品送到二零一实验室",
  "parser": "llm",
  "llm_backend": "deepseek",
  "llm_model": "deepseek-v4-flash",
  "llm_raw_output": "...可选，调试模式才返回...",
  "intent": "go_to_waypoint",
  "command": "go_to_waypoint",
  "waypoint_id": "wp_201",
  "confidence": 0.92,
  "need_confirm": true,
  "accepted": false,
  "detail": "已识别目标为201实验室，请确认是否执行。"
}
```

默认情况下不建议返回完整 `llm_raw_output`，避免日志过长；可通过调试开关开启。

---

## 5. 确认机制要求

本阶段先实现最小确认机制。

### 5.1 待确认任务缓存

当 LLM 解析出移动类任务时，如果 `need_confirm=true`，系统应返回：

```text
accepted=false
need_confirm=true
pending_command_id=xxx
```

不立即调用 mission_gateway。

### 5.2 确认接口

新增接口：

```http
POST /api/voice/confirm_command
```

请求：

```json
{
  "pending_command_id": "voice_pending_001",
  "confirmed": true,
  "requested_by": "operator"
}
```

行为：

```text
confirmed=true：执行 pending command
confirmed=false：取消 pending command
```

### 5.3 Pending command 过期时间

默认：

```bash
VOICE_PENDING_TTL_SECONDS=30
```

过期后确认无效。

---

## 6. Prompt 要求

System Prompt 必须强调：

```text
你是机器人语音命令解析器。
你只能把用户文本解析为允许的 JSON 任务意图。
你不能直接控制机器人。
你不能输出自然语言解释。
你不能编造 waypoint_id。
你不能生成代码、shell 命令或任意操作指令。
如果无法确定任务，返回 intent=unknown。
```

User Prompt 必须包含：

```text
用户识别文本
允许的 intent 列表
可用 waypoint 列表
输出 JSON schema
安全规则
```

---

## 7. 任务清单

## Task 1：增加 LLM 配置与 `.env.example`

要求：

- 新增 `.env.example` 或更新现有 `.env.example`
- 增加 DeepSeek V4 相关环境变量
- 不写真实 API Key
- README 明确说明 API Key 位置

验收：

```text
[ ] `.env.example` 中存在 DEEPSEEK_API_KEY 占位符
[ ] README 中写清 DeepSeek V4 API 配置位置
[ ] 代码不含真实 API Key
[ ] 未配置 API Key 时后端不崩溃
```

---

## Task 2：实现 DeepSeek API Client

要求：

- 新增 `llm_client.py`
- 使用 OpenAI-compatible SDK 或 HTTP 请求
- 从环境变量读取：
  - `DEEPSEEK_API_KEY`
  - `DEEPSEEK_BASE_URL`
  - `DEEPSEEK_MODEL`
  - `DEEPSEEK_TIMEOUT_SECONDS`
- 支持超时和错误处理

验收：

```text
[ ] 配置 API Key 后能调用 DeepSeek V4
[ ] API 超时时返回结构化错误
[ ] API Key 不出现在日志中
[ ] 模型名可通过环境变量切换
```

---

## Task 3：实现 LLM JSON 语义解析器

要求：

- 新增 `llm_intent_parser.py`
- 输入 recognized_text
- 输出严格 JSON 结构
- 无法解析时返回 unknown
- JSON 解析失败时安全降级

验收：

```text
[ ] “帮我把样品送到二零一实验室” → go_to_waypoint / wp_201
[ ] “我想让机器人回装载点” → return_home 或 go_to_waypoint/home，按本地规则确定
[ ] “今天天气不错” → unknown，不触发任务
[ ] LLM 输出非 JSON 时不会触发任务
```

---

## Task 4：本地安全校验

要求：

- 新增 `llm_safety.py`
- 白名单校验 intent / command
- 校验 waypoint_id 必须存在
- 校验 confidence 阈值
- 移动类任务默认 require confirm

验收：

```text
[ ] 不存在的 waypoint_id 不执行
[ ] confidence 低于阈值不执行
[ ] unknown 不执行
[ ] 移动类命令默认 need_confirm=true
```

---

## Task 5：接入现有语音链路

要求：

- 不重写 FunASR
- 不重写 record_command
- 不重写 audio_command
- 不重写 mission_gateway
- 在现有语音文本解析后增加 LLM fallback

验收：

```text
[ ] 简单命令“去201”仍走规则解析
[ ] 复杂命令“帮我把样品送到二零一实验室”可走 LLM
[ ] LLM 结果进入统一返回格式
[ ] 未知命令不触发 mission
```

---

## Task 6：实现二次确认接口

要求：

- 新增 pending command 缓存
- 新增 `/api/voice/confirm_command`
- 支持确认执行与取消
- 支持 TTL 过期

验收：

```text
[ ] 移动类命令返回 pending_command_id
[ ] 未确认时不调用 mission_gateway
[ ] confirmed=true 后才执行
[ ] confirmed=false 后取消
[ ] 过期 pending command 不能执行
```

---

## Task 7：README 与文档更新

要求：

README 必须新增：

```md
## DeepSeek V4 API 配置
```

并说明：

- `.env.example` 位置
- 真实 API Key 放环境变量或 `.env`
- 不得提交真实 API Key
- 推荐模型
- 测试命令
- 失败回退行为

验收：

```text
[ ] README 能指导队友配置 DeepSeek V4
[ ] README 写清 API Key 不进入 Git
[ ] README 写清 LLM_BACKEND / DEEPSEEK_MODEL
[ ] README 写清确认机制
```

---

## 8. Codex Prompt

```text
Read AGENTS.md, README.md, and current voice module code.

Current status:
- FunASR local ASR works on RK3588.
- /api/voice/audio_command works.
- /api/voice/record_command works.
- Existing rule-based parser and mission_gateway must be preserved.

Task:
Implement Phase 6: DeepSeek V4 API based LLM semantic parsing for voice commands.

Requirements:
1. Add DeepSeek V4 API configuration through environment variables.
2. Add or update .env.example with placeholders only. Do not include real API keys.
3. Update README with a clear section: "DeepSeek V4 API 配置".
4. Implement llm_client.py for DeepSeek OpenAI-compatible Chat Completions.
5. Implement llm_intent_parser.py that outputs strict JSON.
6. Implement llm_safety.py for local validation.
7. Keep rule parser as first priority; call LLM only when needed.
8. Do not let LLM directly call mission_gateway.
9. Add confirmation flow for motion commands:
   - pending_command_id
   - /api/voice/confirm_command
   - TTL expiration
10. Integrate with existing text_command, audio_command, and record_command return format.
11. Unknown or unsafe output must not trigger mission.
12. API failures must gracefully fall back to rule parsing or return a safe error.
13. Add minimal tests.

DeepSeek config defaults:
- DEEPSEEK_BASE_URL=https://api.deepseek.com
- DEEPSEEK_MODEL=deepseek-v4-flash
- DEEPSEEK_TIMEOUT_SECONDS=5
- DEEPSEEK_TEMPERATURE=0.1
- DEEPSEEK_MAX_TOKENS=512

Do not:
- hardcode API keys
- commit .env with real keys
- add OpenClaw
- add browser microphone recording
- add wake word
- add streaming ASR
- add YOLO changes
- change RT-Thread or NUC communication
- allow LLM to directly control motors

Validation:
- backend starts without DEEPSEEK_API_KEY
- backend uses rule parser when LLM is disabled
- with API key configured, complex sentence can be parsed by DeepSeek V4
- motion commands require confirmation
- confirmed command executes through existing mission_gateway
- unknown commands never trigger mission
- README clearly documents where to put the API key

Only modify files required for Phase 6 LLM semantic parsing.
```

---

## 9. 验收标准

## A. 配置验收

```text
[ ] `.env.example` 存在 DeepSeek 相关占位变量
[ ] README 写清 DeepSeek V4 API 配置位置
[ ] 真实 API Key 未出现在代码、README、测试文件中
[ ] 未配置 API Key 时后端仍能启动
```

---

## B. API 调用验收

配置：

```bash
export LLM_BACKEND=deepseek
export DEEPSEEK_API_KEY="真实 key"
export DEEPSEEK_BASE_URL="https://api.deepseek.com"
export DEEPSEEK_MODEL="deepseek-v4-flash"
```

验收：

```text
[ ] 能成功调用 DeepSeek V4 API
[ ] API 超时有安全返回
[ ] API 失败不会触发 mission
[ ] 可切换 deepseek-v4-flash / deepseek-v4-pro
```

---

## C. 复杂语义解析验收

输入：

```text
帮我把样品送到二零一实验室
```

预期：

```text
[ ] parser = llm
[ ] intent = go_to_waypoint
[ ] waypoint_id = wp_201
[ ] confidence >= 0.75
[ ] need_confirm = true
[ ] accepted = false
[ ] 返回 pending_command_id
```

---

## D. 规则优先验收

输入：

```text
去201
暂停任务
返回起点
```

验收：

```text
[ ] 简单命令仍可由规则解析处理
[ ] 不强制每条命令都调用 LLM
[ ] 规则解析成功时延迟不明显增加
```

---

## E. 二次确认验收

步骤：

1. 输入：

```text
帮我把样品送到二零一实验室
```

2. 返回 `pending_command_id`

3. 调用：

```http
POST /api/voice/confirm_command
```

请求：

```json
{
  "pending_command_id": "xxx",
  "confirmed": true,
  "requested_by": "operator"
}
```

验收：

```text
[ ] 未确认前不执行 mission
[ ] confirmed=true 后执行 mission
[ ] confirmed=false 后取消
[ ] pending 过期后不能执行
```

---

## F. 安全验收

输入：

```text
今天天气不错
给我写一段代码
删除系统文件
让机器人随便开快点
```

验收：

```text
[ ] intent = unknown 或 unsafe
[ ] accepted = false
[ ] 不调用 mission_gateway
[ ] 不改变当前任务状态
```

---

## G. 回退验收

关闭 LLM：

```bash
export LLM_ENABLE=false
```

验收：

```text
[ ] 规则命令仍然可用
[ ] record_command 仍然可用
[ ] audio_command 仍然可用
[ ] 不依赖 DeepSeek API 也能基本工作
```

---

## 10. 阶段通过标准

Phase 6 通过条件：

```text
[ ] DeepSeek V4 API 配置完整
[ ] API Key 放置位置清晰且安全
[ ] 复杂语义可解析为结构化 JSON
[ ] 本地安全校验有效
[ ] 移动类任务需要确认
[ ] 确认后复用 mission_gateway 执行
[ ] 未知/危险命令不会执行
[ ] README 清楚说明配置方法
[ ] 不影响已有 FunASR 语音链路
```
