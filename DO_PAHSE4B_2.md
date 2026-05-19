# DO_PAHSE4B_2.md

## 任务名称

Phase 4B-2：前端板端录音入口开发

## 当前状态

后端接口 `POST /api/voice/record_command` 已完成并验证可用。

现有链路已经跑通：

```text
RK3588 USB 麦克风
→ 后端调用 arecord 录音
→ FunASR 离线识别
→ recognized_text
→ intent_parser / waypoint_resolver
→ mission_gateway
→ 返回 task_status
```

当前测试结果已证明：

```text
/api/voice/record_command
→ recognized_text = 去201
→ intent = go_to_waypoint
→ waypoint_id = wp_201
→ accepted = true
```

因此本阶段只开发**前端触发 RK3588 板端录音识别入口**。

---

## 一、任务目标

在现有 Dashboard 中新增一个简洁的语音录音控制入口，让操作者可以在网页上点击按钮，触发 RK3588 后端直接使用 USB 麦克风录音并识别。

注意：

本阶段不是浏览器麦克风录音，而是调用后端接口：

```http
POST /api/voice/record_command
```

即：

```text
Dashboard 按钮
→ POST /api/voice/record_command
→ RK3588 后端使用 USB 麦克风录音
→ FunASR 识别
→ mission_gateway
→ 页面显示识别结果和任务状态
```

---

## 二、本阶段不做的事情

本阶段不要做：

- 浏览器 MediaRecorder 录音
- 浏览器麦克风权限申请
- WebRTC / 音频流
- 唤醒词
- 流式 ASR
- 多轮语音对话
- OpenClaw
- LLM 自由任务规划
- YOLO
- RT-Thread 直连
- 语音直接控制电机
- Dashboard 大改版

本阶段只做：

```text
前端点击按钮
→ 调用 /api/voice/record_command
→ 显示识别文本、意图、目标点、任务受理结果
```

---

## 三、前端功能要求

### 1. Dashboard 新增语音录音卡片

在现有 Dashboard 页面中新增一个卡片，建议标题为：

```text
语音任务入口
```

卡片内容至少包括：

- 当前录音状态
- 录音时长选择或固定显示
- “开始板端录音识别”按钮
- 识别文本
- 解析意图
- 目标点
- 是否受理
- 任务状态
- 错误信息
- 最近一次录音文件路径，可选

---

### 2. 按钮行为

新增按钮：

```text
开始板端录音识别
```

点击后：

1. 前端立即进入 loading 状态；
2. 按钮禁用，避免重复点击；
3. 调用后端：

```http
POST /api/voice/record_command
Content-Type: application/json
```

请求体：

```json
{
  "duration": 3,
  "source": "dashboard-record-button",
  "requested_by": "operator",
  "keep_audio": true
}
```

4. 等待后端返回；
5. 页面显示识别与任务解析结果；
6. 请求完成后恢复按钮可点击。

---

### 3. 录音时长

第一版可以固定 3 秒。

如果实现简单，可以做一个下拉框：

```text
2 秒 / 3 秒 / 5 秒
```

默认值：

```text
3 秒
```

如果为了最小实现，固定 3 秒即可，不强制做下拉框。

---

### 4. Loading 状态

录音和识别期间，页面需要明确提示：

```text
正在录音并识别，请说话...
```

或：

```text
识别中...
```

按钮在请求未完成前必须 disabled。

---

### 5. 成功结果展示

成功返回后，页面展示以下字段：

```text
识别文本：recognized_text
意图：intent
命令：command
目标点：waypoint_id
是否受理：accepted
提示信息：detail
ASR 后端：asr_backend
ASR 耗时：asr_time_s
模型加载耗时：model_load_time_s
音频文件：audio_path
```

如果有 `task_status`，展示：

```text
任务类型：task_status.task_type
任务状态：task_status.state
任务进度：task_status.progress
任务来源：task_status.source
```

---

### 6. 错误结果展示

如果接口返回失败或请求异常，需要显示清晰错误信息。

常见错误包括：

```text
audio_record_failed
empty_audio_file
asr_failed
unknown command
network error
```

页面不要静默失败。

---

### 7. 未知命令处理

如果返回：

```json
{
  "accepted": false,
  "intent": "unknown"
}
```

页面应显示：

```text
未识别到可执行任务命令
```

并且不要显示为任务执行成功。

---

## 四、API 调用要求

前端应新增或复用 API 封装方法，例如：

```ts
recordVoiceCommand(payload: {
  duration?: number;
  source?: string;
  requested_by?: string;
  keep_audio?: boolean;
})
```

调用地址：

```text
/api/voice/record_command
```

注意：

- 不要直接写死完整 IP；
- 继续使用当前前端已有的 `/api` 代理方式；
- 不要绕过现有 API 封装风格。

---

## 五、UI 约束

- 不要重做 Dashboard 布局；
- 不要引入新的大型 UI 组件库；
- 不要做复杂动画；
- 保持现有工业监控风格；
- 卡片应尽量简洁，可读性优先。

---

## 六、建议展示结构

卡片可以类似：

```text
语音任务入口

[开始板端录音识别]

状态：空闲 / 录音识别中 / 成功 / 失败
识别文本：去201
解析意图：go_to_waypoint
目标点：wp_201
受理结果：已受理
任务状态：running
ASR耗时：3.09s
模型加载：0.00s
音频文件：voice_20260519_xxx.wav
错误信息：无
```

---

## 七、Codex Prompt

```text
Read AGENTS.md, README.md, and the current frontend/backend voice module code.

Current status:
The backend endpoint POST /api/voice/record_command is implemented and verified. It records audio on RK3588 using the USB microphone, runs FunASR, reuses the existing text_command / voice_entry_service / mission_gateway flow, and returns recognized_text, intent, waypoint_id, accepted, task_status, audio_path, asr_time_s, and model_load_time_s.

Task:
Implement Phase 4B-2: add a frontend Dashboard entry for server-side RK3588 voice recording.

Requirements:
1. Add a small Dashboard card titled "语音任务入口".
2. Add a button: "开始板端录音识别".
3. On click, call POST /api/voice/record_command.
4. Use request body:
   {
     "duration": 3,
     "source": "dashboard-record-button",
     "requested_by": "operator",
     "keep_audio": true
   }
5. Show loading state while the request is pending.
6. Disable the button while recording/recognition is running.
7. Display returned fields:
   - recognized_text
   - intent
   - command
   - waypoint_id
   - accepted
   - detail
   - asr_backend
   - asr_time_s
   - model_load_time_s
   - audio_path
   - task_status if available
8. Display errors clearly if the request fails or success=false.
9. If accepted=false or intent=unknown, show that no executable command was accepted.
10. Keep the existing Dashboard layout and style. Do not redesign the whole frontend.
11. Do not implement browser microphone recording.
12. Do not add wake word, streaming ASR, LLM, OpenClaw, YOLO, or new backend behavior.
13. Do not change mission_gateway or ASR backend logic.

Validation:
- frontend starts successfully
- Dashboard shows the new voice card
- clicking the button calls /api/voice/record_command
- button is disabled while waiting
- response for "去201" shows recognized_text, go_to_waypoint, wp_201, accepted=true
- unknown speech shows accepted=false or intent=unknown without displaying task success
- existing Dashboard state display still works

Only modify files required for this frontend voice recording entry.
```

---

## 八、验收标准

### A. 页面显示验收

```text
[ ] Dashboard 出现“语音任务入口”卡片
[ ] 页面无白屏
[ ] 原有 Dashboard 状态显示不受影响
[ ] 按钮显示为“开始板端录音识别”或等价文案
```

---

### B. 接口调用验收

点击按钮后，后端应收到：

```http
POST /api/voice/record_command
```

验收：

```text
[ ] 点击按钮能触发后端录音接口
[ ] 请求体包含 duration/source/requested_by/keep_audio
[ ] 不出现 404
[ ] 不出现前端跨域或代理错误
```

---

### C. Loading 状态验收

```text
[ ] 请求进行中按钮被禁用
[ ] 页面显示“录音中/识别中”提示
[ ] 请求结束后按钮恢复可点击
```

---

### D. 已知命令验收

对着 RK3588 USB 麦克风说：

```text
去201
```

页面应显示：

```text
[ ] recognized_text 包含“201”
[ ] intent = go_to_waypoint
[ ] waypoint_id = wp_201
[ ] accepted = true
[ ] task_status.state = running 或等价状态
```

---

### E. 未知命令验收

对着麦克风说：

```text
今天天气不错
```

页面应显示：

```text
[ ] recognized_text 正常显示或部分显示
[ ] accepted = false 或 intent = unknown
[ ] 页面不显示任务执行成功
[ ] 不改变当前任务状态
```

---

### F. 错误显示验收

临时停止后端或配置错误录音设备后测试。

页面应显示：

```text
[ ] 网络错误 / 后端错误有明确提示
[ ] audio_record_failed 能显示给用户
[ ] asr_failed 能显示给用户
[ ] 页面不崩溃
```

---

### G. 性能与重复点击验收

连续点击测试。

```text
[ ] 请求中无法重复触发第二次录音
[ ] 完成后可以再次点击
[ ] 第二次请求能正常返回
[ ] 页面显示最新一次识别结果
```

---

## 九、通过条件

本阶段通过需要满足：

```text
[ ] 前端可以一键触发 RK3588 板端录音
[ ] 后端能完成 FunASR 识别
[ ] 页面能显示识别文本和任务解析结果
[ ] 已知命令能触发 mission
[ ] 未知命令不会误触发 mission
[ ] 原有 Dashboard 功能不受影响
```

