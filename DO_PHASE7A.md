# DO_PHASE7A.md

# Phase 7A：前端移动任务确认弹窗

## 1. 阶段目标

在已完成 DeepSeek V4 / LLM 语义解析与后端 pending confirmation 机制的基础上，为前端增加移动类任务确认弹窗。

本阶段目标是：当语音或文本命令被解析为会导致机器人移动或改变任务状态的命令时，前端不得直接执行任务，而应展示确认弹窗，由用户二次确认后再调用后端确认接口执行。

完整链路：

```text
语音 / 文本输入
→ 后端 ASR / LLM / rule parser
→ 返回 need_confirm=true + pending_command_id
→ 前端弹窗展示解析结果
→ 用户确认 / 取消
→ POST /api/voice/confirm_command
→ 后端执行或取消 pending command
→ Dashboard 更新任务状态
```

---

## 2. 当前前提

后端已完成或应已具备：

```text
POST /api/voice/text_command
POST /api/voice/audio_command
POST /api/voice/record_command
POST /api/voice/confirm_command
```

当移动类任务需要确认时，后端会返回类似：

```json
{
  "success": true,
  "data": {
    "accepted": false,
    "need_confirm": true,
    "pending_command_id": "voice_pending_xxx",
    "recognized_text": "帮我把样品送到二零一实验室",
    "intent": "go_to_waypoint",
    "command": "go_to_waypoint",
    "waypoint_id": "wp_201",
    "confidence": 0.95,
    "detail": "已识别为前往 wp_201，请确认是否执行。"
  }
}
```

本阶段只做前端确认交互，不改后端语义解析逻辑，不改 mission bridge。

---

## 3. 需要确认的命令范围

### 3.1 必须弹窗确认的命令

```text
go_to_waypoint
start_patrol
return_home
```

这些命令会导致机器人移动、开始任务或改变任务流，必须经过用户确认。

### 3.2 可不弹窗的命令

```text
query_status
query_task
query_detection
pause_task
```

其中 `pause_task` 偏安全，可以直接执行。

### 3.3 可按项目需要决定是否确认的命令

```text
resume_task
```

如担心误恢复任务，可也加入确认范围。

---

## 4. 任务清单

## Task 1：扩展前端语音响应类型

### 任务要求

在前端 API 类型定义中补充以下字段：

```ts
need_confirm?: boolean
pending_command_id?: string | null
recognized_text?: string
intent?: string
command?: string
waypoint_id?: string | null
confidence?: number
parser?: string
llm_backend?: string
llm_model?: string
detail?: string
error?: string | null
```

### 实现要求

- 不破坏已有语音文本入口、板端录音入口、音频上传入口；
- 所有语音接口返回结果统一进入同一个结果处理函数；
- 对 `need_confirm=true` 且存在 `pending_command_id` 的结果触发弹窗。

---

## Task 2：新增移动任务确认弹窗组件

### 建议组件名

```text
VoiceConfirmDialog.vue
```

### 弹窗展示内容

弹窗至少展示：

```text
识别文本 recognized_text
解析意图 intent
执行命令 command
目标点 waypoint_id
置信度 confidence
解析方式 parser / llm_backend / llm_model，如有
详情 detail
```

### 弹窗按钮

```text
确认执行
取消任务
```

### UI 要求

- 保持现有 Dashboard 风格；
- 不进行整页重构；
- 弹窗信息必须足够让操作者判断是否确认执行；
- 移动类任务弹窗应有明确风险提示，例如“该操作将使机器人移动”。

---

## Task 3：语音命令返回后触发确认逻辑

### 逻辑要求

当前端调用以下任一接口后：

```text
/api/voice/text_command
/api/voice/audio_command
/api/voice/record_command
```

若返回：

```ts
result.need_confirm === true && result.pending_command_id
```

则：

```text
不显示任务已执行
不直接修改为 accepted 状态
打开 VoiceConfirmDialog
保存 pending_command_id
等待用户确认或取消
```

若返回：

```text
accepted=true
```

则按现有逻辑显示任务已受理。

若返回：

```text
accepted=false 且 need_confirm=false
```

则显示未识别、拒绝原因或错误信息，不触发弹窗执行。

---

## Task 4：实现确认 / 取消 API 调用

### 新增前端 API 函数

```ts
confirmVoiceCommand(pendingCommandId: string, confirmed: boolean, requestedBy?: string)
```

### 后端接口

```http
POST /api/voice/confirm_command
```

### 请求示例：确认执行

```json
{
  "pending_command_id": "voice_pending_xxx",
  "confirmed": true,
  "requested_by": "operator"
}
```

### 请求示例：取消任务

```json
{
  "pending_command_id": "voice_pending_xxx",
  "confirmed": false,
  "requested_by": "operator"
}
```

### 前端处理

确认成功后：

```text
关闭弹窗
显示“任务已确认执行”
刷新任务状态 / 等待 WebSocket 状态更新
```

取消成功后：

```text
关闭弹窗
显示“任务已取消”
不触发 mission
不改变当前任务状态
```

---

## Task 5：处理 pending 过期和异常情况

### 需要处理的异常

```text
pending_command_id 不存在
pending 已过期
后端返回确认失败
网络错误
用户重复点击确认
用户重复点击取消
```

### 前端行为要求

- 确认按钮点击后进入 loading 状态；
- 请求完成前避免重复点击；
- 如果后端返回 pending 过期，提示“确认已过期，请重新下达命令”；
- 如果网络错误，提示“确认请求失败，请检查连接”；
- 弹窗异常关闭时，不应默认执行任务。

---

## Task 6：保留已有语音入口能力

本阶段不得破坏以下功能：

```text
文本命令输入
RK3588 板端录音识别
音频文件上传识别
FunASR 本地识别
LLM 语义解析
rule parser fallback
mission_gateway
Dashboard 状态显示
```

---

## 5. Codex Prompt

将下面 prompt 直接交给 Codex：

```text
Read AGENTS.md, README.md, and current frontend/backend voice-related code.

Current status:
The backend already supports voice command parsing and pending confirmation.
When a movement command needs confirmation, voice APIs may return need_confirm=true and pending_command_id.
The backend also exposes POST /api/voice/confirm_command.

Task:
Implement Phase 7A frontend confirmation dialog for movement voice commands.

Requirements:
1. Extend frontend voice command response types to include:
   - need_confirm
   - pending_command_id
   - recognized_text
   - intent
   - command
   - waypoint_id
   - confidence
   - parser
   - llm_backend
   - llm_model
   - detail
   - error
2. Add a VoiceConfirmDialog component.
3. When any voice command API returns need_confirm=true and pending_command_id, show the dialog instead of treating the command as executed.
4. Dialog must display recognized_text, intent, command, waypoint_id, confidence, parser/LLM info if available, and detail.
5. Dialog must provide two actions:
   - confirm execution
   - cancel task
6. Add frontend API function confirmVoiceCommand(pendingCommandId, confirmed, requestedBy).
7. confirmVoiceCommand must call POST /api/voice/confirm_command.
8. On confirm success, close dialog and show task accepted / confirmed message.
9. On cancel success, close dialog and show task cancelled message.
10. Handle expired pending command, missing pending id, network failure, and duplicate clicks.
11. Do not redesign the dashboard.
12. Do not change backend mission behavior.
13. Do not add browser microphone recording in this task.
14. Do not add new LLM behavior in this task.

Validation:
- Movement command with need_confirm=true opens the confirmation dialog.
- Confirm button calls /api/voice/confirm_command with confirmed=true.
- Cancel button calls /api/voice/confirm_command with confirmed=false.
- Query commands do not open the dialog.
- Unknown commands do not trigger mission execution.
- Existing voice input and dashboard state display still work.

Only modify files required for this feature.
```

---

## 6. 验收标准

## A. 移动类任务弹窗验收

### 测试输入

```text
帮我把样品送到二零一实验室
```

### 通过标准

```text
[ ] 前端不直接显示任务已执行
[ ] 弹出确认框
[ ] 弹窗显示 recognized_text
[ ] 弹窗显示 intent=go_to_waypoint
[ ] 弹窗显示 waypoint_id=wp_201
[ ] 弹窗显示确认执行 / 取消任务按钮
```

---

## B. 确认执行验收

### 操作

点击：

```text
确认执行
```

### 通过标准

```text
[ ] 前端调用 POST /api/voice/confirm_command
[ ] 请求体 confirmed=true
[ ] 请求体包含 pending_command_id
[ ] 后端返回 accepted=true 或任务确认成功
[ ] 弹窗关闭
[ ] 页面显示任务已确认执行
[ ] Dashboard / task_status 显示任务状态变化
```

---

## C. 取消任务验收

### 操作

点击：

```text
取消任务
```

### 通过标准

```text
[ ] 前端调用 POST /api/voice/confirm_command
[ ] 请求体 confirmed=false
[ ] 请求体包含 pending_command_id
[ ] 弹窗关闭
[ ] 页面显示任务已取消
[ ] 不触发 mission
[ ] 当前任务状态不应变为 running
```

---

## D. 查询类命令不弹窗验收

### 测试输入

```text
现在机器人在哪
```

### 通过标准

```text
[ ] 不弹出移动任务确认框
[ ] 直接显示查询结果或状态信息
[ ] 不调用 confirm_command
[ ] 不触发 mission
```

---

## E. 未知命令安全验收

### 测试输入

```text
今天天气不错
```

### 通过标准

```text
[ ] 不弹出确认执行移动任务弹窗
[ ] 不触发 mission
[ ] 页面显示未识别到有效任务或拒绝原因
```

---

## F. pending 过期验收

### 操作

```text
触发 pending command
等待超过后端 TTL
再点击确认执行
```

### 通过标准

```text
[ ] 前端提示确认已过期或确认失败
[ ] 不触发 mission
[ ] 弹窗关闭或提示重新下达命令
```

---

## G. 重复点击验收

### 操作

```text
连续快速点击确认执行按钮
```

### 通过标准

```text
[ ] 请求期间按钮进入 loading 或 disabled 状态
[ ] 不发送重复确认请求
[ ] 不重复触发任务
```

---

## H. 旧功能回归验收

### 通过标准

```text
[ ] 文本命令入口仍可用
[ ] 板端录音识别仍可用
[ ] 音频上传识别仍可用
[ ] Dashboard 状态显示仍可用
[ ] WebSocket 状态推送不受影响
```

---

## 7. 本阶段不做内容

```text
[×] 浏览器本地麦克风录音
[×] 新增 LLM 语义能力
[×] 修改后端 mission bridge
[×] 修改 ASR / FunASR
[×] 修改 YOLO
[×] 修改 NUC / RT-Thread 通信
[×] 语音直接控制电机
[×] 多轮对话
[×] 唤醒词
```

---

## 8. 阶段通过标准

满足以下条件即视为 Phase 7A 通过：

```text
[ ] 所有 need_confirm=true 的移动类语音命令均会弹出确认框
[ ] 用户确认后才执行任务
[ ] 用户取消后不执行任务
[ ] 查询类命令不弹窗
[ ] 未知命令不触发 mission
[ ] pending 过期和网络异常有明确提示
[ ] 不破坏已有语音识别和 Dashboard 功能
```
