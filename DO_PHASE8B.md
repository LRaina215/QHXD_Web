# DO_PHASE8B.md

# Phase 8B：公网前端双语音入口接入

## 1. 阶段目标

在公网 Web 前端中同时提供两种语音输入方式：

```text
1. 网页麦克风识别：使用当前浏览器/手机/电脑麦克风录音，适合远程语音控制。
2. 车载麦克风识别：触发 RK3588 车载 USB 麦克风录音，适合现场人机交互。
```

两种入口最终都应复用已有 RK3588 语音处理链路：

```text
音频输入
→ RK3588 FunASR
→ rule parser / LLM parser
→ 安全校验
→ 移动任务二次确认
→ mission_gateway
```

本阶段重点是公网前端、云端 gateway 与 RK3588 之间的语音链路打通，不重新实现 ASR、不重写 mission、不破坏已有本地语音功能。

---

## 2. 总体链路

## 2.1 网页麦克风识别

```text
公网 Web 前端
→ 浏览器麦克风录音，通常为 webm/opus
→ POST /api/voice/browser_audio_command
→ 云服务器临时接收音频
→ ffmpeg 转换为 16kHz mono wav
→ 转发给 RK3588 /api/voice/audio_command
→ RK3588 FunASR 识别与任务解析
→ 云端返回结果给前端
```

## 2.2 车载麦克风识别

```text
公网 Web 前端
→ 点击“车载麦克风识别”
→ POST /api/robot/voice/onboard_record_command
→ 云服务器鉴权与安全检查
→ 转发给 RK3588 /api/voice/record_command
→ RK3588 调用 arecord 使用车载 USB 麦克风录音
→ FunASR 识别与任务解析
→ 云端返回结果给前端
```

---

## 3. 接口定义

## 3.1 网页麦克风识别接口

### 公网接口

```http
POST /api/voice/browser_audio_command
```

### 请求类型

```text
multipart/form-data
```

### 字段

```text
file: 浏览器录音文件，通常为 webm/opus
source: browser-mic
requested_by: operator
keep_audio: false
```

### 云端处理要求

```text
1. 接收浏览器录音文件。
2. 校验文件大小、MIME 类型、录音时长。
3. 临时保存到云服务器。
4. 使用 ffmpeg 转为 16kHz mono wav。
5. 转发给 RK3588 /api/voice/audio_command。
6. 拿到 RK3588 返回结果后返回前端。
7. 默认删除临时音频文件。
```

### 转码格式

```bash
ffmpeg -y -i input.webm -ac 1 -ar 16000 -sample_fmt s16 output.wav
```

---

## 3.2 车载麦克风识别接口

### 公网接口

```http
POST /api/robot/voice/onboard_record_command
```

### 请求 JSON

```json
{
  "duration": 3,
  "source": "web-onboard-mic",
  "requested_by": "operator",
  "keep_audio": true
}
```

### 云端处理要求

```text
1. 校验用户身份。
2. 检查公网控制安全开关。
3. 检查 RK3588 在线状态。
4. 转发到 RK3588 本地 /api/voice/record_command。
5. 将 RK3588 返回结果原样或规范化后返回前端。
```

### 注意

公网不要直接暴露 RK3588 的原始 `/api/voice/record_command`。公网侧使用 `/api/robot/voice/onboard_record_command`，以区分“云端请求机器人录音”和“服务器本机录音”。

---

## 4. 前端 UI 要求

在现有语音控制卡片中新增两个明确按钮：

```text
[网页麦克风识别]
说明：使用当前浏览器/手机/电脑麦克风，适合远程语音控制。

[车载麦克风识别]
说明：使用机器人 RK3588 上的 USB 麦克风，适合现场交互。
```

## 4.1 网页麦克风按钮行为

```text
1. 点击后请求浏览器麦克风权限。
2. 开始录音，默认 3 秒，也可支持手动停止。
3. 录音期间按钮显示 loading / recording 状态。
4. 录音结束后上传到 /api/voice/browser_audio_command。
5. 展示 recognized_text、intent、waypoint_id、accepted、need_confirm、detail。
6. 若 need_confirm=true，复用已有移动任务确认弹窗。
```

## 4.2 车载麦克风按钮行为

```text
1. 点击后调用 /api/robot/voice/onboard_record_command。
2. 按钮显示“车载麦克风录音中”。
3. 等待 RK3588 录音、识别、解析返回。
4. 展示 recognized_text、intent、waypoint_id、accepted、need_confirm、detail。
5. 若 need_confirm=true，复用已有移动任务确认弹窗。
```

---

## 5. 安全要求

## 5.1 公网语音入口必须鉴权

以下接口必须要求登录或 Token：

```text
POST /api/voice/browser_audio_command
POST /api/robot/voice/onboard_record_command
```

## 5.2 公网控制安全开关

需要支持环境变量：

```bash
PUBLIC_CONTROL_ENABLED=false
```

当 `PUBLIC_CONTROL_ENABLED=false` 时：

```text
允许状态查看。
允许语音识别测试返回 recognized_text。
不允许触发 mission 控制。
移动类任务必须返回 accepted=false，并提示公网控制未开启。
```

## 5.3 文件限制

网页录音上传必须限制：

```text
最大文件大小：建议 5MB
最大录音时长：建议 8s 或 10s
允许 MIME：audio/webm、audio/ogg、audio/wav
```

## 5.4 移动任务确认

所有移动类任务必须复用已有二次确认机制：

```text
go_to_waypoint
start_patrol
return_home
```

不得因为来自网页麦克风或车载麦克风而绕过确认。

---

## 6. 临时音频文件策略

## 6.1 云服务器

默认不长期保存浏览器录音。

```text
上传 webm → 临时保存 → 转码 wav → 转发 RK3588 → 删除临时文件
```

支持调试参数：

```text
keep_audio=true
```

调试模式下可保存最近若干条音频，但不得无限堆积。

## 6.2 RK3588

RK3588 端沿用现有 `audio_command` / `record_command` 的保留策略。

---

## 7. 任务清单

## Task 1：云端新增网页录音上传接口

实现：

```http
POST /api/voice/browser_audio_command
```

要求：

```text
[ ] 接收 multipart/form-data 音频文件
[ ] 校验文件大小、格式、时长
[ ] 临时保存音频文件
[ ] 使用 ffmpeg 转为 16kHz mono wav
[ ] 转发到 RK3588 /api/voice/audio_command
[ ] 返回 RK3588 识别与解析结果
[ ] 默认删除临时文件
```

---

## Task 2：云端新增车载麦克风转发接口

实现：

```http
POST /api/robot/voice/onboard_record_command
```

要求：

```text
[ ] 校验 Token / 登录态
[ ] 检查 PUBLIC_CONTROL_ENABLED
[ ] 检查 RK3588 在线状态
[ ] 转发到 RK3588 /api/voice/record_command
[ ] 返回 RK3588 识别与解析结果
[ ] 不直接暴露原始 /api/voice/record_command
```

---

## Task 3：前端新增两个语音按钮

要求：

```text
[ ] 新增“网页麦克风识别”按钮
[ ] 新增“车载麦克风识别”按钮
[ ] 两个按钮文案和说明必须区分麦克风来源
[ ] 请求中按钮禁用，避免重复触发
[ ] 返回结果统一展示
[ ] need_confirm=true 时复用已有确认弹窗
```

---

## Task 4：前端浏览器录音实现

要求：

```text
[ ] 使用浏览器麦克风录音
[ ] 录音期间有明显状态提示
[ ] 录音完成后上传到 /api/voice/browser_audio_command
[ ] 麦克风权限被拒绝时给出提示
[ ] 浏览器不支持录音时给出提示
[ ] 不影响车载麦克风入口
```

---

## Task 5：结果展示统一

两种语音入口返回后均展示：

```text
recognized_text
raw_text，可选
asr_backend
asr_time_s
parser / llm_backend，可选
intent
command
waypoint_id
accepted
need_confirm
detail
error
task_status
```

要求：

```text
[ ] 用户能看到识别文本
[ ] 用户能看到解析意图
[ ] 用户能看到任务是否受理
[ ] 未知命令不显示为成功执行
[ ] 错误信息可读
```

---

## Task 6：安全与回归

要求：

```text
[ ] 未登录或 Token 无效时拒绝语音控制
[ ] PUBLIC_CONTROL_ENABLED=false 时不触发真实 mission
[ ] 移动类任务仍需二次确认
[ ] unknown 不触发 mission
[ ] RK3588 离线时返回明确错误
[ ] 不破坏现有状态、YOLO、导航、mission、确认弹窗功能
```

---

## 8. 验收标准

## A. 网页麦克风识别验收

操作：

```text
点击“网页麦克风识别”
对电脑/手机说：去201
```

通过标准：

```text
[ ] 浏览器请求麦克风权限
[ ] 成功录音并上传云服务器
[ ] 云服务器完成 ffmpeg 转码
[ ] 云服务器转发给 RK3588 /api/voice/audio_command
[ ] 页面显示 recognized_text 包含“201”
[ ] intent = go_to_waypoint
[ ] waypoint_id = wp_201
[ ] 移动类任务触发确认弹窗或按安全策略拒绝执行
```

---

## B. 车载麦克风识别验收

操作：

```text
点击“车载麦克风识别”
对机器人车载麦克风说：去201
```

通过标准：

```text
[ ] 前端调用 /api/robot/voice/onboard_record_command
[ ] 云端转发到 RK3588 /api/voice/record_command
[ ] RK3588 使用车载 USB 麦克风录音
[ ] 页面显示 recognized_text 包含“201”
[ ] intent = go_to_waypoint
[ ] waypoint_id = wp_201
[ ] 移动类任务触发确认弹窗或按安全策略拒绝执行
```

---

## C. 安全开关验收

配置：

```bash
PUBLIC_CONTROL_ENABLED=false
```

通过标准：

```text
[ ] 语音可以识别
[ ] 移动类 mission 不执行
[ ] 页面提示公网控制未开启或需要授权
[ ] 查询类命令仍可返回状态
```

---

## D. 二次确认验收

输入：

```text
帮我把样品送到二零一实验室
```

通过标准：

```text
[ ] 页面返回 need_confirm=true
[ ] 弹出确认框
[ ] 未确认前不执行 mission
[ ] 点击确认后才执行 mission
[ ] 点击取消后不执行 mission
```

---

## E. 未知命令验收

输入：

```text
今天天气不错
```

通过标准：

```text
[ ] recognized_text 正常显示
[ ] intent = unknown 或 accepted=false
[ ] 不触发 mission
[ ] 页面显示未识别到有效任务
```

---

## F. 文件与转码验收

通过标准：

```text
[ ] 支持浏览器 webm/opus 音频上传
[ ] ffmpeg 转码输出为 16kHz mono wav
[ ] 转码失败时返回明确错误
[ ] 默认删除临时文件
[ ] keep_audio=true 时可保留调试音频
[ ] 不产生无限音频堆积
```

---

## G. 回归验收

通过标准：

```text
[ ] 前端状态总览正常
[ ] WebSocket 或轮询状态正常
[ ] YOLO 卡片正常
[ ] 导航预留区正常
[ ] LLM 确认弹窗正常
[ ] mission 控制不被误触发
[ ] 现有 RK3588 本地 record_command 不受影响
```

---

## 9. 阶段通过标准

Phase 8B 通过条件：

```text
[ ] 公网前端同时具备“网页麦克风识别”和“车载麦克风识别”两个入口
[ ] 网页麦克风音频可上传云端、转码并转发 RK3588
[ ] 车载麦克风入口可经云端触发 RK3588 本地录音
[ ] 两种语音入口均复用 RK3588 FunASR 与任务解析链路
[ ] 移动类任务不绕过二次确认
[ ] 公网控制受 Token / 安全开关保护
[ ] 临时音频文件策略合理
[ ] 不破坏已有前端功能
```
