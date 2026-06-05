# PHASE9B_DONE.md

# Phase 9B：灵巡 Sentinel 真实 TTS 播报与语音助手体验收口

## 完成日期

2026-06-05

## 实现摘要

Phase 9B 已接入 MiMO V2.5 TTS API，实现真实语音合成并通过 RK3588 板载 ES8388 音响本地播报。浏览器自动播放已注释保留备用。

端到端链路：

```text
smart_command / speak → reply_text → MiMO TTS API (mimo-v2.5-tts, 茉莉)
→ 24kHz WAV 落盘 (backend/data/tts/)
→ aplay -D plughw:2,0 本地播报
→ 同时返回 audio_url 供 Dashboard 可选播放
```

---

## 修改文件清单

| 文件 | 变更 |
|---|---|
| `backend/app/schemas.py` | TTSStatus 新增 `audio_url`, `error_reason`, `created_at` |
| `backend/app/services/tts_service.py` | 完全重写：`mock`/`online` backend；MiMO chat-completions API 集成；base64 音频解码；文件落盘与自动清理；`subprocess.Popen` 非阻塞本地播放 |
| `backend/app/main.py` | 新增 `GET /api/voice/tts/audio/{filename}` 音频文件服务端点 |
| `frontend/src/App.vue` | 新增 `SmartTtsStatus` 类型字段；`<audio>` 元素；`autoPlayTts()` 函数（已注释）；修复已存在的 truthy 字符串 bug |
| `cloud_gateway/cloud_gateway.py` | ALLOWED_PATH_PREFIXES 新增 `/api/voice/tts/audio/` |
| `scripts/run_backend_service.sh` | 新增 ES8388 播放通路初始化 |
| `.env` | TTS_BACKEND=online；MiMO API 配置；TTS_AUTO_PLAY_LOCAL=true |
| `.env.example` | 新增 MiMO TTS 配置项 |
| 新增 `PHASE9B_DONE.md` | 本文件 |

## 新增依赖

```bash
pip3 install httpx
```

---

## MiMO TTS API 配置（`.env`）

```bash
# Phase 9B MiMO TTS
TTS_BACKEND=online
MIMO_API_KEY=sk-sosntincxfwpfika3gaqar4q9pk11hfhjwuclh08efefoh7
MIMO_BASE_URL=https://api.xiaomimimo.com/v1
MIMO_TTS_MODEL=mimo-v2.5-tts
MIMO_TTS_VOICE=茉莉
MIMO_TTS_FORMAT=wav
TTS_API_TIMEOUT=15
TTS_MAX_AUDIO_FILES=20

# RK3588 本地播报
TTS_AUTO_PLAY_LOCAL=true
TTS_PLAYER_CMD=aplay -D plughw:2,0
```

**API 调用格式**（`_call_mimo_tts()`）：

```python
POST https://api.xiaomimimo.com/v1/chat/completions
Header: api-key: $MIMO_API_KEY
Body: {
    "model": "mimo-v2.5-tts",
    "messages": [
        {"role": "user", "content": "<style prompt>"},
        {"role": "assistant", "content": "<text to speak>"}
    ],
    "audio": {"format": "wav", "voice": "茉莉"}
}
Response: choices[0].message.audio.data → base64 decoded → WAV file
```

**可选 MiMO 音色**：
- 中文：冰糖、茉莉、苏打、白桦
- 英文：Mia、Chloe、Milo、Dean

---

## 验收结果

### Task 9B-1：真实 TTS backend ✅
- `TTS_BACKEND=mock` 不受影响
- `TTS_BACKEND=online` → MiMO V2.5 24kHz WAV 生成正常
- `/api/voice/speak` 返回完整 TTSStatus（含 audio_url、error_reason、created_at）
- TTS 失败（如 invalid key）返回明确错误，不崩溃

### Task 9B-2：TTS 音频文件管理 ✅
- 音频落盘 `backend/data/tts/`（53KB WAV，24kHz mono PCM）
- `GET /api/voice/tts/latest` 返回 `audio_url`、`error_reason`、`created_at`
- `GET /api/voice/tts/audio/{filename}` 服务音频（HTTP 200，284KB 验证通过）
- 自动清理：保留最近 `TTS_MAX_AUDIO_FILES` 个文件

### Task 9B-3：smart_command 集成 TTS ✅
- `generate_tts=true` → 自动生成 TTS 并本地播报
- `smart_record_command` 默认 `generate_tts=True`
- TTS 失败时 `reply_text` 正常返回
- `tts_status` 完整返回

### Task 9B-4：Dashboard TTS 播放
- 浏览器自动播放已注释（`autoPlayTts`），保留备用
- `<audio>` 元素和播放函数完整保留，需要时取消注释即可启用

### Task 9B-5：RK3588 本地播放 ✅
- `TTS_AUTO_PLAY_LOCAL=true` → 每次 TTS 生成后自动 `aplay -D plughw:2,0`
- 非阻塞播放（`subprocess.Popen`）
- ES8388 初始化已加入 `run_backend_service.sh`
- **音响测试通过**：用户确认能听见播报

### Task 9B-6：公网闭环验证 ✅
- 公网 TTS 链路：Nginx → Cloud Gateway → RK3588 → MiMO API
- `/api/voice/tts/audio/` 已加入 Cloud Gateway 白名单
- 音频文件公网可访问（284KB 下载验证通过）

### Task 9B-7：文档 ✅
- `.env.example` 已更新
- 本文件完整记录
- 移除了错误的 API Key（待用户更新）

---

## 验证命令

```bash
# 测试 speak + 本地播报
curl -s -X POST http://127.0.0.1:8000/api/voice/speak \
  -H "Content-Type: application/json" \
  -d '{"text":"你好，我是灵巡 Sentinel。"}' | python3 -m json.tool

# 测试 smart_command + TTS
curl -s -X POST http://127.0.0.1:8000/api/voice/smart_command \
  -H "Content-Type: application/json" \
  -d '{"text":"你是谁","generate_tts":true}' | python3 -m json.tool

# 查看 TTS 状态
curl -s http://127.0.0.1:8000/api/voice/tts/latest | python3 -m json.tool

# 查看音频文件
ls -la /home/robomaster/QHXD/backend/data/tts/

# 直接播放测试（ES8388 card 2）
aplay -D plughw:2,0 <tts_file.wav>
```

## 已知遗留

1. **ES8388 I2C 初始化错误**：启动时 `ES8323 7-0011: -5`，通过 `run_backend_service.sh` 强制设置 mixer 控件规避
2. **PCM2902 USB**：仅录音，无法播放
3. **浏览器自动播放**：已注释在 `frontend/src/App.vue:820`，需启用时取消注释并重新构建部署

## Phase 9B 未做（计划排除）

唤醒词、流式实时对话、多轮长期记忆、OpenClaw、语音直控底盘、DeepSeek 绕过安全校验、复杂情感化 TTS、C 板真实环境传感器接入
