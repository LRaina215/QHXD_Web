# DO_PHASE4B_1.md

## 任务名称

**Phase 4B-1：RK3588 板端录音识别接口 `/api/voice/record_command`**

## 当前前提

`/api/voice/audio_command` 已验证可用：

```text
wav 文件上传
→ FunASR 识别
→ recognized_text
→ intent_parser / waypoint_resolver
→ voice_entry_service
→ mission_gateway
```

当前任务是在 RK3588 后端新增“板端直接录音”能力：

```text
POST /api/voice/record_command
→ 后端调用 arecord 使用 USB 麦克风录音
→ 生成唯一 wav 文件
→ FunASR 识别
→ 复用现有 text_command 流程
→ 返回识别结果与任务结果
```

---

## 一、实现目标

新增接口：

```http
POST /api/voice/record_command
```

该接口由 RK3588 后端直接调用 `arecord` 录音，使用当前已确认可用的 USB 麦克风：

```bash
plughw:CARD=Device,DEV=0
```

---

## 二、请求格式

```json
{
  "duration": 3,
  "source": "rk3588-usb-mic",
  "requested_by": "operator",
  "keep_audio": true
}
```

默认值：

```text
duration = 3
source = "rk3588-record-command"
requested_by = "operator"
keep_audio = true
```

`duration` 限制：

```text
1 <= duration <= 10
```

---

## 三、环境变量

必须支持以下环境变量：

```bash
AUDIO_DEVICE=plughw:CARD=Device,DEV=0
AUDIO_SAMPLE_RATE=16000
AUDIO_CHANNELS=1
AUDIO_FORMAT=S16_LE
AUDIO_RECORD_SECONDS=3
VOICE_RECORD_DIR=/home/robomaster/QHXD/backend/data/voice_records
VOICE_KEEP_RECORDINGS=true
```

若未配置，使用默认值：

```text
AUDIO_DEVICE=plughw:CARD=Device,DEV=0
AUDIO_SAMPLE_RATE=16000
AUDIO_CHANNELS=1
AUDIO_FORMAT=S16_LE
AUDIO_RECORD_SECONDS=3
VOICE_RECORD_DIR=backend/data/voice_records
VOICE_KEEP_RECORDINGS=true
```

---

## 四、录音实现要求

后端实际效果等价于：

```bash
arecord -D "$AUDIO_DEVICE" -r 16000 -c 1 -f S16_LE -d 3 output.wav
```

实现要求：

1. 使用 `subprocess.run([...])`，不要使用 shell 字符串拼接。
2. 自动创建 `VOICE_RECORD_DIR`。
3. 每次录音生成唯一文件名。
4. 录音失败时不调用 ASR。
5. 录音文件为空时不调用 ASR。

推荐新增模块：

```text
backend/app/services/voice/audio_recorder.py
```

---

## 五、录音文件命名

禁止固定使用：

```text
/tmp/voice_cmd.wav
```

推荐格式：

```text
voice_YYYYMMDD_HHMMSS_mmm_<uuid8>.wav
```

示例：

```text
voice_20260519_143512_381_a8f21c9d.wav
```

---

## 六、复用现有流程

`record_command` 必须复用已有链路：

```text
record_command
→ audio_recorder.record()
→ asr_service.transcribe_audio_file(audio_path)
→ voice_entry_service.handle_text_command(recognized_text, source, requested_by)
```

不要重复实现：

- `intent_parser`
- `waypoint_resolver`
- `mission_gateway`
- `text_command` 业务逻辑

---

## 七、FunASR 模型缓存要求

当前 `/api/voice/audio_command` 可能每次请求都重新加载模型，表现为：

```text
model_load_time_s ≈ 15s
```

本轮要求检查并优化：

1. FunASR 模型实例应在进程内缓存。
2. 第一次调用时懒加载。
3. 后续请求复用同一个模型实例。
4. 返回结果继续包含：
   - `model_load_time_s`
   - `asr_time_s`

期望：

```text
第一次调用：model_load_time_s > 0
第二次及以后：model_load_time_s = 0 或接近 0
```

---

## 八、返回格式

返回格式应与 `/api/voice/audio_command` 基本一致，并额外包含录音信息。

示例：

```json
{
  "success": true,
  "data": {
    "audio_path": "backend/data/voice_records/voice_20260519_143512_381_a8f21c9d.wav",
    "duration": 3,
    "audio_device": "plughw:CARD=Device,DEV=0",
    "recognized_text": "去201实验室",
    "raw_text": "<|zh|><|NEUTRAL|><|Speech|><|withitn|>去201实验室。",
    "asr_backend": "funasr",
    "asr_time_s": 1.8,
    "model_load_time_s": 0.0,
    "intent": "go_to_waypoint",
    "command": "go_to_waypoint",
    "payload": {
      "waypoint_id": "wp_201"
    },
    "waypoint_id": "wp_201",
    "accepted": true,
    "need_confirm": false,
    "detail": "已受理前往目标点 wp_201 的模拟命令。",
    "error": null,
    "task_status": {}
  }
}
```

---

## 九、错误处理

### 1. 录音失败

```json
{
  "success": false,
  "error": "audio_record_failed",
  "detail": "arecord failed: ..."
}
```

### 2. 录音文件为空

```json
{
  "success": false,
  "error": "empty_audio_file"
}
```

### 3. ASR 失败

```json
{
  "success": false,
  "error": "asr_failed",
  "detail": "..."
}
```

### 4. 未知命令

识别成功但命令未知时，不触发 mission。

```json
{
  "success": true,
  "data": {
    "recognized_text": "今天天气不错",
    "intent": "unknown",
    "accepted": false,
    "need_confirm": true,
    "detail": "未识别到可执行任务命令"
  }
}
```

---

## 十、本轮不要做

不要实现：

- 浏览器麦克风录音
- 唤醒词
- 流式 ASR
- 多轮对话
- OpenClaw
- LLM 自由规划
- YOLO
- RT-Thread 直连
- 语音直接控制电机
- 前端大改版

本轮只做：

```text
RK3588 后端调用 USB 麦克风录音
→ FunASR
→ text_command
→ mission_gateway
```

---

## 十一、Codex Prompt

```text
Read AGENTS.md, README.md, and current voice module code.

Current status:
POST /api/voice/audio_command already works. It can upload a wav file, run FunASR, produce recognized_text, and reuse the existing text_command / voice_entry_service / mission_gateway flow.

Task:
Implement Phase 4B-1: server-side RK3588 USB microphone recording command endpoint.

Add:
POST /api/voice/record_command

Goal:
The backend should call arecord on RK3588 using the configured USB microphone, save a unique wav file, run FunASR, then reuse the existing text_command flow.

Requirements:
1. Add POST /api/voice/record_command.
2. Request JSON fields: duration, source, requested_by, keep_audio.
3. Default duration=3, source="rk3588-record-command", requested_by="operator", keep_audio=true.
4. Read recording config from env vars:
   - AUDIO_DEVICE, default "plughw:CARD=Device,DEV=0"
   - AUDIO_SAMPLE_RATE, default 16000
   - AUDIO_CHANNELS, default 1
   - AUDIO_FORMAT, default "S16_LE"
   - AUDIO_RECORD_SECONDS, default 3
   - VOICE_RECORD_DIR, default backend/data/voice_records
   - VOICE_KEEP_RECORDINGS, default true
5. Use subprocess.run([...]) instead of unsafe shell strings.
6. Limit duration to 1-10 seconds.
7. Generate a unique wav filename for every request:
   voice_YYYYMMDD_HHMMSS_mmm_<uuid8>.wav
8. Automatically create VOICE_RECORD_DIR.
9. Return audio_path, duration, audio_device, recognized_text, raw_text, asr_backend, asr_time_s, model_load_time_s, intent, command, payload, waypoint_id, accepted, need_confirm, detail, error, and task_status.
10. Reuse existing asr_service.transcribe_audio_file or equivalent.
11. Reuse existing voice_entry_service / text_command flow after ASR.
12. Do not duplicate intent_parser, waypoint_resolver, or mission_gateway logic.
13. Handle these errors:
   - audio_record_failed
   - empty_audio_file
   - asr_failed
   - unknown command must not trigger mission
14. Check and improve FunASR model caching:
   - first call may load model
   - subsequent calls should reuse model instance
   - model_load_time_s should be 0 or near 0 after first call if possible
15. Add minimal tests if the current project has backend tests.
16. Update README or docs with usage examples.

Do not:
- add browser microphone recording
- add wake word
- add streaming ASR
- add LLM / OpenClaw
- add YOLO
- change mission bridge behavior
- directly control motors
- redesign Dashboard

Validation:
- backend starts
- POST /api/voice/record_command exists
- it records using AUDIO_DEVICE
- it creates a unique wav file
- it runs FunASR
- it returns recognized_text
- known command "去201实验室" maps to go_to_waypoint / wp_201
- unknown speech does not trigger mission
- keep_audio=false deletes or does not retain the recording
- second ASR call avoids reloading the model if caching is implemented

Only modify files required for this feature.
```

---

## 十二、验收清单

### A. 环境变量验收

启动后端前设置：

```bash
export AUDIO_DEVICE=plughw:CARD=Device,DEV=0
export AUDIO_SAMPLE_RATE=16000
export AUDIO_CHANNELS=1
export AUDIO_FORMAT=S16_LE
export AUDIO_RECORD_SECONDS=3
export VOICE_RECORD_DIR=/home/robomaster/QHXD/backend/data/voice_records
export VOICE_KEEP_RECORDINGS=true
```

验收：

```text
[ ] 后端启动不报错
[ ] 未设置环境变量时使用默认值
[ ] 设置 AUDIO_DEVICE 后实际使用 USB 麦克风录音
```

### B. 接口存在性验收

```bash
curl -X POST http://127.0.0.1:8000/api/voice/record_command \
  -H "Content-Type: application/json" \
  -d '{"duration":3,"source":"rk3588-usb-mic","requested_by":"operator","keep_audio":true}'
```

验收：

```text
[ ] 接口存在
[ ] 返回 JSON
[ ] 不出现 404
[ ] 不出现 500
```

### C. 录音文件验收

```bash
ls -lh /home/robomaster/QHXD/backend/data/voice_records
file /home/robomaster/QHXD/backend/data/voice_records/*.wav
```

验收：

```text
[ ] 生成 wav 文件
[ ] 文件名每次不同
[ ] 文件不是 0 字节
[ ] 文件为 16kHz / mono / S16_LE，或符合环境变量配置
[ ] 返回 JSON 中包含 audio_path
```

### D. 语音识别验收

调用接口时说：

```text
去201实验室
```

验收：

```text
[ ] recognized_text 包含“201”或“实验室”
[ ] raw_text 有 FunASR 原始输出
[ ] asr_backend = funasr
[ ] asr_time_s 有数值
```

### E. 意图解析验收

验收：

```text
[ ] intent = go_to_waypoint
[ ] command = go_to_waypoint
[ ] waypoint_id = wp_201
[ ] payload.waypoint_id = wp_201
[ ] accepted = true
```

### F. 任务链路验收

```text
[ ] 返回 task_status
[ ] mock 模式下能受理模拟命令
[ ] real 模式下能通过 mission bridge 发给 NUC
[ ] Dashboard 或 /api/state/latest 能看到任务状态变化
```

### G. 未知命令安全验收

录入无关语音，例如：

```text
今天天气不错
```

验收：

```text
[ ] recognized_text 正常返回或部分返回
[ ] intent = unknown 或 accepted = false
[ ] 不触发 mission
[ ] 不改变当前任务
```

### H. 模型缓存验收

连续调用两次：

```bash
curl -X POST http://127.0.0.1:8000/api/voice/record_command \
  -H "Content-Type: application/json" \
  -d '{"duration":3,"source":"cache-check","requested_by":"operator","keep_audio":true}'
```

验收：

```text
[ ] 第一次可能 model_load_time_s 较大
[ ] 第二次 model_load_time_s 明显降低，最好为 0 或接近 0
[ ] 第二次总耗时明显低于第一次
```

如果第二次仍然：

```text
model_load_time_s ≈ 15s
```

说明模型缓存未做好，需要返工。

### I. `keep_audio=false` 验收

```bash
curl -X POST http://127.0.0.1:8000/api/voice/record_command \
  -H "Content-Type: application/json" \
  -d '{"duration":3,"source":"delete-check","requested_by":"operator","keep_audio":false}'
```

验收：

```text
[ ] 识别流程正常
[ ] 返回中说明音频已删除，或 audio_path 为 null / 临时路径
[ ] 录音文件不会长期保留
```

### J. 错误设备验收

临时设置错误设备：

```bash
export AUDIO_DEVICE=plughw:CARD=WrongDevice,DEV=0
```

调用接口。

验收：

```text
[ ] 返回 success=false
[ ] error = audio_record_failed
[ ] 不调用 ASR
[ ] 不触发 mission
```

---

## 十三、通过标准

全部满足则 Phase 4B-1 通过：

```text
[ ] /api/voice/record_command 可用
[ ] 后端能直接调用 RK3588 USB 麦克风录音
[ ] 每次录音文件名唯一
[ ] FunASR 能识别录音
[ ] 识别文本能进入现有 text_command 流程
[ ] 已知命令能触发 mission
[ ] 未知命令不会触发 mission
[ ] keep_audio=true/false 行为正确
[ ] FunASR 模型不再每次重新加载，或至少有明确 TODO
```
