# PHASE9B_DONE.md

# Phase 9B：灵巡 Sentinel 真实 TTS 播报完成记录

## 完成日期

2026-06-05

## 实现摘要

Phase 9B 的后端 TTS 基础设施、音频文件管理、Dashboard 播放入口、RK3588 本地播报均已实现。
MiMO TTS API 的接入点已预留，只需配置环境变量即可切换为真实 TTS。

---

## 修改文件清单

| 文件 | 变更 |
|---|---|
| `backend/app/schemas.py` | TTSStatus 新增 `audio_url`, `error_reason`, `created_at` 字段 |
| `backend/app/services/tts_service.py` | 完全重写：支持 `mock` / `online` / `local` 三种 backend，音频文件落盘与清理，可选本地扬声器播放 |
| `backend/app/main.py` | 新增 `GET /api/voice/tts/audio/{filename}` 音频文件服务端点 |
| `frontend/src/App.vue` | 新增 `audio_url` 类型、播放按钮、TTS 音频播放/错误处理 JS 函数；修复了已存在的 truthy 字符串 bug |
| `cloud_gateway/cloud_gateway.py` | ALLOWED_PATH_PREFIXES 新增 `/api/voice/tts/audio/` |
| `scripts/run_backend_service.sh` | 新增 ES8388 播放通路初始化（Speaker/Headphone/PCM/Output 音量） |
| `.env.example` | 新增 TTS online/local/playback 配置项 |
| 新增 `PHASE9B_DONE.md` | 本文件 |

## 新增依赖

```bash
pip3 install httpx
```

---

## 接入 MiMO TTS API

在 RK3588 的 `.env` 文件中配置以下环境变量：

```bash
# 切换为 online 模式
TTS_BACKEND=online

# ---- MiMO TTS API 接入点 ----
# 将下面的 URL 和 Key 替换为 MiMO 提供的实际值

TTS_ONLINE_API_URL=https://your-mimo-tts-endpoint/v1/audio/speech
TTS_ONLINE_API_KEY=your_mimo_api_key_here
TTS_ONLINE_MODEL=           # MiMO 模型名，如 mimo-tts-v1（可选）
TTS_ONLINE_VOICE=zh-CN-XiaoxiaoNeural  # MiMO 语音名

# 可选：音频格式和超时
TTS_AUDIO_FORMAT=wav        # wav 或 mp3
TTS_API_TIMEOUT=15          # API 超时秒数
```

**API 约定**：当前 `_call_tts_api()` 发送 JSON POST 请求，body 格式为：
```json
{"text": "...", "voice": "zh-CN-XiaoxiaoNeural", "model": "mimo-tts-v1"}
```
期望返回二进制音频（WAV/MP3）或包含 `audio_url` 的 JSON。

如果 MiMO API 使用不同的请求/响应格式，只需修改 `backend/app/services/tts_service.py` 中的 `_call_tts_api()` 方法。

---

## 验收结果

### Task 9B-1：真实 TTS backend ✅
- `TTS_BACKEND=mock` 原功能不受影响 ➕ 验证通过
- `TTS_BACKEND=online` 代码就绪，待配置 MiMO API 后生成真实音频
- `/api/voice/speak` 返回完整 TTSStatus
- TTS 失败不导致后端崩溃

### Task 9B-2：TTS 音频文件管理 ✅
- 音频落盘到 `backend/data/tts/`
- `GET /api/voice/tts/latest` 返回 `audio_url`, `created_at`, `error_reason`
- `GET /api/voice/tts/audio/{filename}` 服务音频文件
- 自动清理：保留最近 20 个文件（`TTS_MAX_AUDIO_FILES`）

### Task 9B-3：smart_command 集成 TTS ✅
- `generate_tts=true` 时自动调用 TTS
- TTS 失败时 `smart_command` 仍返回 `reply_text`
- 返回结果中包含 `tts_status`

### Task 9B-4：Dashboard TTS 播放 ✅
- 语音助手卡片显示 TTS 状态
- `audio_url` 存在时显示"播放"按钮
- 播放成功/失败有明确提示
- 前端构建通过

### Task 9B-5：RK3588 本地播放 ✅
- `TTS_AUTO_PLAY_LOCAL` 控制是否本地播报（默认 false）
- `TTS_PLAYER_CMD` 可配置播放命令（默认 `aplay -D plughw:2,0`）
- 播放不阻塞主流程（subprocess.Popen）
- ES8388 音频初始化已加入 `run_backend_service.sh`

### Task 9B-6：公网闭环验证 ⏳
- 公网链路已就绪
- `/api/voice/tts/audio/` 已加入 Cloud Gateway 白名单
- 完整验证待 MiMO API 接入后进行

### Task 9B-7：文档 ✅
- `.env.example` 已更新
- 本文件（PHASE9B_DONE.md）包含配置说明和接入点

---

## 本地播放测试命令

```bash
# 生成测试音
ffmpeg -f lavfi -i "sine=frequency=440:duration=2" -ac 2 -ar 44100 /tmp/test_tone.wav -y

# ES8388 板载声卡播放（card 2）
aplay -D plughw:CARD=rockchipes8388,DEV=0 /tmp/test_tone.wav

# 确认 mixer 设置（重启后可能需重新设置）
amixer -c 2 sset Speaker on
amixer -c 2 sset Headphone on
amixer -c 2 sset PCM 95%
amixer -c 2 sset 'Output 1' 90%
amixer -c 2 sset 'Output 2' 90%

# 保存设置以便重启后自动恢复
sudo alsactl store
```

## 已知遗留问题

1. **ES8388 I2C 初始化错误**：启动时 `ES8323 7-0011: -5`，可能导致某些寄存器未正确编程。
   当前通过 `run_backend_service.sh` 在启动时强制设置 mixer 控件来规避。
2. **PCM2902 USB 设备**：仅提供录音功能（card 3），无法用于播放。扬声器需通过 ES8388 的 3.5mm 接口输出。

## Phase 9B 未做内容（按计划排除）

- 唤醒词
- 流式实时对话
- 多轮长期记忆
- OpenClaw
- 语音直接控制底盘
- DeepSeek 绕过本地安全校验
- 复杂情感化 TTS
- C 板真实环境传感器接入
