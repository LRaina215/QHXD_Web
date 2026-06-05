# DO_PHASE9B.md

# Phase 9B：灵巡 Sentinel 真实 TTS 播报与语音助手体验收口

## 1. 阶段目标

在 Phase 9A 已完成智能语音理解、状态查询、天气查询、DeepSeek fallback、mission_candidate 和 mock TTS 的基础上，本阶段实现真实 TTS 播报闭环。

目标链路：

```text
smart_command / speak
→ reply_text
→ TTS backend
→ audio file / audio_url
→ Dashboard 播放
→ 可选 RK3588 本地扬声器播放
```

本阶段不做：

- 唤醒词；
- 流式实时对话；
- 多轮长期记忆；
- OpenClaw；
- 语音直接控制底盘；
- DeepSeek 绕过本地安全校验；
- 复杂情感化 TTS；
- C 板真实环境传感器接入。

---

## 2. 任务清单与验收标准

## Task 9B-1：接入真实 TTS backend

### 任务内容

在现有 `tts_service.py` 基础上增加真实 TTS 后端。

保留：

```text
TTS_BACKEND=mock
```

新增：

```text
TTS_BACKEND=online
```

预留：

```text
TTS_BACKEND=local
```

要求：

- TTS provider 的 API Key 只能从环境变量读取；
- 不得写入前端；
- 不得提交到 Git；
- TTS 失败不能影响 `reply_text` 返回。

### 验收标准

- `TTS_BACKEND=mock` 时原功能不受影响；
- `TTS_BACKEND=online` 时可根据文本生成真实音频；
- `/api/voice/speak` 可返回 TTS 状态；
- TTS 失败时返回明确错误，不导致后端崩溃；
- 单元测试覆盖 mock 与失败分支。

---

## Task 9B-2：完善 TTS 音频文件管理

### 任务内容

实现 TTS 音频文件落盘与访问。

建议目录：

```text
backend/data/tts/
```

建议文件命名：

```text
tts_<timestamp>_<request_id>.wav/mp3
```

要求：

- 保存最近一次 TTS 状态；
- 支持 `GET /api/voice/tts/latest`；
- 支持返回音频 URL；
- 避免无限堆积音频文件。

### 验收标准

- 生成 TTS 后能在指定目录看到音频文件；
- `GET /api/voice/tts/latest` 返回最近一次 TTS 状态；
- 返回字段包含：
  - `backend`
  - `status`
  - `text`
  - `audio_url`
  - `created_at`
  - `error_reason`
- 音频文件路径不暴露系统敏感目录；
- README 中说明清理策略。

---

## Task 9B-3：smart_command 集成真实 TTS

### 任务内容

扩展 `/api/voice/smart_command`。

当请求包含：

```json
{
  "generate_tts": true
}
```

且存在 `reply_text` 时，自动调用 TTS。

适用场景：

- `query_self_identity`
- `query_capability`
- `query_robot_status`
- `query_weather`
- `query_perception_status`
- 运动类任务的确认提示

### 验收标准

- “你是谁”返回文字回复并生成 TTS；
- “今天天气怎么样”返回文字回复并生成 TTS；
- “帮我送到二零一实验室”返回等待确认提示并生成 TTS；
- 运动类命令仍然不直接执行；
- TTS 失败时 `smart_command` 仍返回 `reply_text`；
- 返回结果中包含 `tts_status` 或等价字段。

---

## Task 9B-4：Dashboard 增加 TTS 播放能力

### 任务内容

在“灵巡 Sentinel 智能语音助手”卡片中显示 TTS 状态，并提供播放入口。

展示内容：

```text
reply_text
TTS backend
TTS status
audio_url
播放按钮
错误原因
```

### 验收标准

- smart command 成功生成 TTS 后，Dashboard 显示“播放语音回复”；
- 点击按钮可以播放音频；
- 没有音频时不显示无效播放按钮；
- 播放失败有明确提示；
- 不影响 mission_candidate 的确认/取消流程；
- 前端构建通过。

---

## Task 9B-5：RK3588 本地播放能力

### 任务内容

增加可选的本地播放能力，让机器人本体可以通过扬声器播报。

建议新增配置：

```text
TTS_AUTO_PLAY_LOCAL=false
TTS_PLAYER_CMD=aplay
```

要求：

- 默认不自动播放；
- 开启后，TTS 生成成功再播放；
- 播放失败不影响接口响应；
- 播放过程不能阻塞 mission 主流程。

### 验收标准

- `TTS_AUTO_PLAY_LOCAL=false` 时不自动播放；
- `TTS_AUTO_PLAY_LOCAL=true` 且音频设备正常时，RK3588 可本地播报；
- 音频设备不可用时返回明确错误；
- 不影响 Dashboard 前端播放；
- README 中记录本地播放测试命令。

---

## Task 9B-6：公网语音助手闭环验证

### 任务内容

验证公网链路下的语音输入与 TTS 回复。

链路：

```text
公网浏览器麦克风
→ cloud gateway
→ RK3588 smart_command
→ reply_text
→ TTS
→ Dashboard 播放
```

### 验收标准

- 公网前端可提交 smart command；
- 公网前端可获取 TTS 状态；
- 公网前端可播放生成音频；
- 公网控制关闭时，运动类命令仍不会执行；
- 无 token 或 token 错误时，写接口被拒绝；
- 查询类命令不受 mission 控制开关影响。

---

## Task 9B-7：文档与测试收口

### 任务内容

更新文档和测试。

需更新：

- README；
- `.env.example`；
- Phase 9B 验收命令；
- TTS provider 配置说明；
- Dashboard 播放说明；
- 本地播放说明。

新增或更新测试：

- `/api/voice/speak`
- `/api/voice/tts/latest`
- `/api/voice/smart_command generate_tts=true`
- TTS 失败分支
- 无音频时前端展示状态

### 验收标准

- 后端单测通过；
- 前端 `npm run build` 通过；
- README 命令可复现；
- `.env.example` 不包含真实密钥；
- 文档明确写出 Phase 9B 不做的内容。

---

## 3. 推荐执行顺序

```text
1. Task 9B-1：真实 TTS backend
2. Task 9B-2：音频文件与 latest 状态
3. Task 9B-3：smart_command 集成 TTS
4. Task 9B-4：Dashboard 播放
5. Task 9B-5：RK3588 本地播放
6. Task 9B-6：公网链路验证
7. Task 9B-7：文档与测试收口
```

---

## 4. 总体验收标准

Phase 9B 完成后应满足：

1. `reply_text` 可以生成真实 TTS 音频；
2. `/api/voice/speak` 可独立调用；
3. `/api/voice/smart_command` 支持 `generate_tts=true`；
4. Dashboard 可以播放语音助手回复；
5. RK3588 可选本地扬声器播报；
6. TTS 失败不影响文字回复和任务安全逻辑；
7. 公网语音助手链路可播放 TTS；
8. API Key 不进入前端和 Git；
9. 运动类命令仍必须确认后才执行；
10. 后端测试和前端构建均通过。

---

## 5. Codex 执行提示词

```text
Read AGENTS.md, README.md, PHASE9A_DONE.md, and DO_PHASE9B.md.

Task:
Implement Phase 9B: real TTS playback loop for Lingxun Sentinel.

Scope:
Only implement TTS backend, audio file output, smart_command TTS integration, Dashboard playback, optional RK3588 local playback, and docs/tests.

Do not implement:
- wake word
- streaming dialogue
- OpenClaw
- long-term memory
- direct motor control
- bypassing mission safety confirmation
- real C-board environment sensors

Validation:
- backend tests pass
- frontend build passes
- /api/voice/speak works
- /api/voice/tts/latest works
- smart_command generate_tts=true returns reply_text and tts status
- Dashboard can play generated audio
- TTS failure does not break smart_command
```
