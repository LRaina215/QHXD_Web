# DO_PHASE4B.md

## 1. 阶段名称

**Phase 4B：FunASR 真实语音输入封装与语音任务入口接入**

---

## 2. 当前背景

Phase 4A 已完成 RK3588 侧语音任务入口的基础能力：

- 已有文本命令入口：`POST /api/voice/text_command`
- 已有 ASR mock / 文本占位入口：`POST /api/voice/asr_text_mock`
- 已有意图解析链路：`intent_parser`
- 已有目标点别名解析链路：`waypoint_resolver`
- 已有语音任务服务：`voice_entry_service`
- 已有任务桥接链路：`mission_gateway`
- Dashboard 已具备文本任务入口

当前人工测试已完成：

- RK3588 可以通过麦克风录制 wav 音频
- FunASR 已在 RK3588 上成功安装并运行
- `SenseVoiceSmall` 本地模型可以加载
- `fsmn-vad` 本地 VAD 模型可以加载
- RK3588 可以离线识别中文音频
- 当前测试结果表明：约 9.8 秒语音识别耗时约 4.7 秒，短命令具备继续封装价值

因此，Phase 4B 的目标不是重写语音任务链路，而是把已经验证可用的 FunASR 离线识别能力封装为现有 `asr_service` 的真实 backend，并接入当前文本命令链路。

---

## 3. 本阶段目标

本阶段目标是实现：

```text
wav 音频上传
    ↓
FunASR / SenseVoiceSmall 离线识别
    ↓
recognized_text
    ↓
复用现有 text_command / voice_entry_service
    ↓
intent_parser + waypoint_resolver
    ↓
mission_gateway
    ↓
NUC mission bridge
```

即：

**把真实语音输入接到现有任务入口，而不是重写任务系统。**

---

## 4. 重要原则

### 4.1 不允许重写已有任务链路

禁止重写或大规模修改：

- `intent_parser`
- `waypoint_resolver`
- `voice_entry_service`
- `mission_gateway`
- `nuc_adapter`
- `mode_manager`

这些模块已经在 Phase 4A 中形成文本任务闭环，本阶段只能复用，不应推倒重来。

### 4.2 FunASR 只能作为 ASR backend

FunASR 的职责只包括：

```text
音频 → 文本
```

它不负责：

- 意图解析
- 地点匹配
- 任务安全判断
- mission 转发
- 底盘控制

### 4.3 不能直接控制电机

语音输入绝不能直接生成 `vx / vy / wz` 或直接访问 RT-Thread。

正确链路必须是：

```text
voice -> RK3588 voice service -> mission_gateway -> NUC -> RT-Thread
```

### 4.4 模型必须只加载一次

FunASR 模型不能每次请求重新加载。

正确策略：

- 后端启动时加载一次，或第一次请求时懒加载一次
- 后续请求复用同一个 `AutoModel` 实例

否则每次识别都会额外消耗数秒模型加载时间，无法用于实际交互。

---

## 5. 环境变量设计

请通过环境变量配置 FunASR，不要把路径写死在代码逻辑中。

建议环境变量：

```bash
ASR_BACKEND=funasr
FUNASR_MODEL_PATH=/home/robomaster/.cache/modelscope/hub/models/iic/SenseVoiceSmall
FUNASR_VAD_MODEL_PATH=/home/robomaster/.cache/modelscope/hub/models/iic/speech_fsmn_vad_zh-cn-16k-common-pytorch
FUNASR_DEVICE=cpu
FUNASR_LANGUAGE=zh
FUNASR_USE_ITN=true
FUNASR_DISABLE_UPDATE=true
VOICE_MAX_AUDIO_SECONDS=10
VOICE_MAX_UPLOAD_MB=20
```

说明：

- `ASR_BACKEND=mock` 时不要求安装 FunASR
- `ASR_BACKEND=funasr` 时才加载 FunASR
- 如果 FunASR 未安装但 `ASR_BACKEND=mock`，后端必须仍能正常启动
- 模型路径优先使用本地路径，避免比赛现场联网下载

---

## 6. 需要实现的功能

## F1. 扩展 ASR Service

### 要求

在现有 ASR 服务基础上扩展 backend 能力：

```text
asr_service
├── mock backend
└── funasr backend
```

至少提供统一接口：

```python
def transcribe_audio_file(audio_path: str) -> ASRResult:
    ...
```

建议 `ASRResult` 字段：

```python
recognized_text: str
raw_text: str | None
backend: str
success: bool
error: str | None
asr_time_s: float | None
model_load_time_s: float | None
```

### 验收标准

- `ASR_BACKEND=mock` 时后端可启动
- `ASR_BACKEND=funasr` 且模型路径正确时后端可启动
- FunASR 模型只加载一次
- 后续音频识别请求复用已加载模型
- FunASR 返回结果能提取干净的中文文本

---

## F2. 新增真实音频命令接口

### 接口

新增：

```http
POST /api/voice/audio_command
Content-Type: multipart/form-data
```

请求字段：

```text
file: wav 音频文件
source: string，可选
requested_by: string，可选
```

### 处理流程

```text
接收 wav 文件
    ↓
保存到临时目录
    ↓
校验文件大小和格式
    ↓
asr_service.transcribe_audio_file()
    ↓
得到 recognized_text
    ↓
复用现有 text_command / voice_entry_service
    ↓
返回识别文本、解析结果、任务执行结果
```

### 返回示例

```json
{
  "success": true,
  "data": {
    "recognized_text": "去二零一实验室",
    "asr_backend": "funasr",
    "asr_time_s": 1.42,
    "intent": "go_to_waypoint",
    "command": "go_to_waypoint",
    "waypoint_id": "wp_201",
    "accepted": true,
    "need_confirm": false,
    "detail": "已解析为前往 201 实验室任务"
  }
}
```

### 验收标准

- 上传 wav 文件后能得到 `recognized_text`
- `recognized_text` 会复用现有 text command 链路
- 已知命令可以进入 mission bridge
- 未知命令不会触发 mission
- ASR 失败时返回明确错误，而不是后端崩溃
- 上传文件处理完成后能清理临时文件

---

## F3. 音频输入安全校验

### 要求

对上传音频做最小安全限制：

- 只允许 `.wav`
- 限制最大文件大小，例如 20 MB
- 限制最大时长，例如 10 秒
- 识别失败不触发任务
- 空文本不触发任务

### 验收标准

- 非 wav 文件被拒绝
- 超大文件被拒绝
- 空音频 / 无人声音频不会触发任务
- ASR 返回空字符串时不会触发 mission

---

## F4. 语音识别日志

### 要求

记录每次语音请求的关键信息：

- 请求时间
- source
- requested_by
- asr_backend
- recognized_text
- intent
- waypoint_id
- accepted
- error
- asr_time_s

可以先写入现有日志系统或 SQLite command logs，不要求新建复杂表结构。

### 验收标准

- 每次 audio_command 调用有日志
- ASR 成功和失败都能追踪
- 能定位失败原因是音频、ASR、解析还是 mission bridge

---

## F5. README / 文档更新

### 要求

更新 README 或对应阶段文档，说明：

- 如何配置 FunASR 环境变量
- 如何启动 mock backend
- 如何启动 funasr backend
- 如何用 curl 上传 wav 测试
- 常见问题：模型路径错误、FunASR 未安装、音频格式错误、识别为空

### curl 示例

```bash
curl -X POST http://127.0.0.1:8000/api/voice/audio_command \
  -F "file=@/home/robomaster/funasr_test/cmd_201.wav" \
  -F "source=manual-audio-check" \
  -F "requested_by=operator"
```

### 验收标准

- 队友按 README 能跑通 mock 测试
- 队友按 README 能配置 FunASR 本地模型路径
- 队友可以使用 curl 上传 wav 并看到识别结果

---

## 7. 不做内容

本阶段禁止做以下内容：

- 不做唤醒词
- 不做连续监听
- 不做流式 ASR
- 不做 OpenClaw
- 不做 LLM 自由任务规划
- 不做大模型多轮对话
- 不做语音直接控制速度
- 不改 NUC mission bridge 行为
- 不改 RT-Thread 控制链路
- 不重构 Dashboard

---

## 8. 推荐实现轮次

## Round 1：ASR backend 抽象与 FunASR 封装

### Codex Prompt

```text
Read AGENTS.md, README.md, and existing voice module code.

Current status:
- Phase 4A already implemented /api/voice/text_command
- Phase 4A already implemented /api/voice/asr_text_mock
- intent_parser, waypoint_resolver, voice_entry_service, and mission_gateway already exist and must be reused

Task:
Implement FunASR as a real ASR backend.

Requirements:
1. Add ASR_BACKEND configuration with at least mock and funasr.
2. Add env vars:
   - FUNASR_MODEL_PATH
   - FUNASR_VAD_MODEL_PATH
   - FUNASR_DEVICE
   - FUNASR_LANGUAGE
   - FUNASR_USE_ITN
   - FUNASR_DISABLE_UPDATE
3. Implement a FunASR backend using funasr AutoModel.
4. Load the FunASR model only once, either at startup or on first request.
5. Add transcribe_audio_file(audio_path: str).
6. Do not import FunASR at module top level if it breaks mock mode when FunASR is not installed.
7. Do not rewrite intent_parser, waypoint_resolver, voice_entry_service, or mission_gateway.

Validation:
- Backend starts with ASR_BACKEND=mock even if FunASR is unavailable.
- Backend starts with ASR_BACKEND=funasr when model paths are valid.
- Unit or minimal tests cover mock mode.
- Code clearly reports missing FunASR or invalid model path errors.

Only modify files required for ASR backend integration.
```

---

## Round 2：实现 /api/voice/audio_command

### Codex Prompt

```text
Continue in the same thread.

Task:
Add the real audio command endpoint using the existing ASR service.

Requirements:
1. Add POST /api/voice/audio_command.
2. Accept multipart/form-data wav upload.
3. Save upload to a temporary file.
4. Validate extension, size, and basic input.
5. Call asr_service.transcribe_audio_file().
6. Reuse the existing text_command / voice_entry_service flow after transcription.
7. Return recognized_text, asr_time_s, intent, waypoint_id, accepted, need_confirm, and detail.
8. Clean up temporary files.
9. Unknown or empty recognized_text must not trigger mission.

Do not:
- implement wake word
- implement streaming ASR
- change mission_gateway behavior
- directly control motors

Validation:
- Backend starts.
- Uploading a wav file reaches ASR service.
- Mock ASR can simulate recognized text.
- Known recognized text triggers the existing mission flow.
- Unknown recognized text does not trigger mission.

Only modify files required for this endpoint.
```

---

## Round 3：增加日志与 README

### Codex Prompt

```text
Continue in the same thread.

Task:
Add logging and documentation for Voice Phase 4B.

Requirements:
1. Log audio_command requests with:
   - source
   - requested_by
   - asr_backend
   - recognized_text
   - intent
   - waypoint_id
   - accepted
   - error
   - asr_time_s
2. Update README with:
   - ASR_BACKEND=mock usage
   - ASR_BACKEND=funasr usage
   - required FunASR model env vars
   - curl example for uploading wav
   - common troubleshooting notes
3. Add minimal tests if practical.

Validation:
- README curl example is correct.
- Logs make it possible to distinguish ASR failure from intent parsing failure.
- Existing voice text command tests still pass.

Only modify logging/docs/tests needed for this task.
```

---

## Round 4：可选前端上传入口

> 如果后端接口验收通过，再做这一轮。不要提前做。

### Codex Prompt

```text
Continue in the same thread.

Task:
Add a minimal audio upload panel to the existing Dashboard voice/text card.

Requirements:
1. Add a wav file selector.
2. Add an upload-and-recognize button.
3. Call POST /api/voice/audio_command.
4. Display:
   - recognized_text
   - intent
   - waypoint_id
   - accepted
   - detail
   - asr_time_s
5. Keep current Dashboard style.
6. Do not add browser microphone recording yet.
7. Do not redesign the page.

Validation:
- Frontend starts.
- User can choose a wav file and submit.
- Response is displayed clearly.
- Existing text command panel still works.

Only modify frontend files required for this panel.
```

---

## 9. 阶段验收清单

### 后端验收

- [ ] `ASR_BACKEND=mock` 下后端可启动
- [ ] `ASR_BACKEND=funasr` 下后端可启动
- [ ] FunASR 模型只加载一次
- [ ] `/api/voice/audio_command` 可上传 wav
- [ ] 可返回 `recognized_text`
- [ ] recognized_text 能复用现有 text command 流程
- [ ] 已知命令能触发 mission bridge
- [ ] 未知命令不会触发 mission
- [ ] ASR 失败时后端不崩溃
- [ ] 临时音频文件会清理

### 识别效果验收

至少测试以下音频：

- [ ] “去二零一实验室”
- [ ] “暂停任务”
- [ ] “继续任务”
- [ ] “返回起点”
- [ ] “开始巡检”
- [ ] 一条未知命令

每条记录：

```text
音频长度：
识别耗时：
识别文本：
解析 intent：
是否触发 mission：
是否符合预期：
```

### 性能验收

短命令建议目标：

- 2～4 秒音频识别耗时尽量控制在 1～3 秒内
- 不要求连续流式识别
- 不要求唤醒词
- 不要求长语音实时转写

### 安全验收

- [ ] 空音频不触发 mission
- [ ] 未知语音不触发 mission
- [ ] 地点无法匹配不触发 mission
- [ ] ASR 失败不触发 mission
- [ ] API Key / 模型路径不写入前端

---

## 10. 完成判定

Phase 4B 完成标准：

1. RK3588 后端能使用 FunASR 本地模型识别 wav 音频
2. 音频识别结果能进入现有 text command 流程
3. 已知语音命令能触发 mission bridge
4. 未知或失败语音不会误触发
5. README 中有清晰的运行方法和 curl 验证方法
6. Dashboard 至少可通过后端接口看到语音识别结果；前端上传入口可作为可选项

---

## 11. 人工需要提供的信息

在 Codex 开始前，开发者需要确认或提供：

```text
ASR_BACKEND=funasr
FUNASR_MODEL_PATH=/home/robomaster/.cache/modelscope/hub/models/iic/SenseVoiceSmall
FUNASR_VAD_MODEL_PATH=/home/robomaster/.cache/modelscope/hub/models/iic/speech_fsmn_vad_zh-cn-16k-common-pytorch
FUNASR_DEVICE=cpu
测试 wav 文件路径，例如 /home/robomaster/funasr_test/cmd_201.wav
真实 waypoint_id 和别名表是否已经更新
```

