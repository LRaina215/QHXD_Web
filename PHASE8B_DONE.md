# PHASE8B_DONE

## 完成范围

Phase 8B 已完成公网双语音入口：

- 网页麦克风识别：浏览器录音后上传到云端 `/api/voice/browser_audio_command`，云端转码为 `16kHz mono wav`，再转发到 RK3588 `/api/voice/audio_command`。
- 车载麦克风识别：公网调用 `/api/robot/voice/onboard_record_command`，云端转发到 RK3588 `/api/voice/record_command`。
- 原始 `/api/voice/record_command` 仍保持公网禁用，只能作为 RK3588 本地录音接口使用。
- 两个公网语音入口均要求 `Authorization: Bearer <PUBLIC_API_TOKEN>`。
- `PUBLIC_CONTROL_ENABLED=false` 时允许识别和解析，但 mission 控制仍由安全开关阻断。

## 代码改动

### cloud_gateway/cloud_gateway.py

- `cloud_gateway/cloud_gateway.py:5-8`：新增 `shutil`、`subprocess`、`wave`，用于临时音频管理、ffmpeg 转码和 wav 时长校验。
- `cloud_gateway/cloud_gateway.py:16`：新增 FastAPI `File`、`Form`、`UploadFile`，支持浏览器 multipart 音频上传。
- `cloud_gateway/cloud_gateway.py:27-31`：新增浏览器音频大小、时长、临时目录、保留目录和保留数量配置。
- `cloud_gateway/cloud_gateway.py:45-47`：保持 `/api/voice/record_command` 为公网禁用接口。
- `cloud_gateway/cloud_gateway.py:49-79`：将 `/api/voice/browser_audio_command` 与 `/api/robot/voice/onboard_record_command` 加入公网允许路径和写接口鉴权范围。
- `cloud_gateway/cloud_gateway.py:193-239`：新增布尔解析、浏览器音频 MIME/大小校验、wav 时长读取和保留音频清理逻辑。
- `cloud_gateway/cloud_gateway.py:242-280`：新增转发 wav 到 RK3588 `/api/voice/audio_command` 的 multipart helper。
- `cloud_gateway/cloud_gateway.py:282-327`：新增 JSON 转发 helper，用于车载麦克风录音接口。
- `cloud_gateway/cloud_gateway.py:347-462`：新增 `POST /api/voice/browser_audio_command`，执行 token 校验、限流、RK 在线检查、临时保存、ffmpeg 转码、时长校验、转发和临时文件清理。
- `cloud_gateway/cloud_gateway.py:464-495`：新增 `POST /api/robot/voice/onboard_record_command`，执行 token 校验、限流、RK 在线检查，并转发到 RK3588 本地录音接口。

### frontend/src/App.vue

- `frontend/src/App.vue:137-147`：放宽录音识别结果字段为可选，兼容浏览器上传音频和车载录音两类返回。
- `frontend/src/App.vue:240-242`：新增网页麦克风录音和车载麦克风录音状态。
- `frontend/src/App.vue:624-630`：录音状态提示区分网页麦克风、车载麦克风和本地录音。
- `frontend/src/App.vue:1204-1274`：新增 `recordBrowserVoiceCommand()`，使用 `MediaRecorder` 调用浏览器麦克风，上传到 `/api/voice/browser_audio_command`。
- `frontend/src/App.vue:1276-1314`：新增 `recordOnboardVoiceCommand()`，调用 `/api/robot/voice/onboard_record_command` 触发车载麦克风录音。
- `frontend/src/App.vue:1713-1757`：语音 / LLM 面板新增两个明确按钮：`网页麦克风识别` 与 `车载麦克风识别`，并保留本地录音按钮的开发模式能力。

### frontend/src/style.css

- `frontend/src/style.css:965-976`：调整命令面板按钮区域为自适应网格，避免新增两个录音按钮后在不同宽度下挤压错位。

### README.md

- `README.md:112-140`：新增 Phase 8B 公网双语音入口说明，包含两个接口、token 要求、安全边界、ffmpeg 要求、临时音频目录和限制配置。

### cloud_gateway/README.md

- `cloud_gateway/README.md:25-26`：新增浏览器音频大小和时长配置。
- `cloud_gateway/README.md:50-76`：新增公网浏览器麦克风和车载麦克风入口说明，并明确 `/api/voice/record_command` 不直接公网开放。

### cloud_gateway/.env.example

- 新增 `PUBLIC_BROWSER_AUDIO_MAX_MB`、`PUBLIC_BROWSER_AUDIO_MAX_SECONDS`、`GATEWAY_AUDIO_TMP_DIR`、`GATEWAY_AUDIO_KEEP_DIR`、`GATEWAY_AUDIO_KEEP_MAX_FILES` 示例配置。

## 部署状态

- RK3588 前端已重新构建：
  - `frontend/dist/assets/index-BpXXC7mL.css`
  - `frontend/dist/assets/index-l4Tiv9oM.js`
- 云服务器已部署新版静态前端到 `/var/www/lingxunrobot/`。
- 云服务器已部署新版 Cloud Gateway 到 `/opt/lingxun-cloud-gateway/`。
- 云服务器已安装并验证 `ffmpeg`。
- Cloud Gateway systemd 服务 `lingxun-cloud-gateway` 当前为 `active`。

## 验收结果

### 云端健康检查

```bash
curl http://127.0.0.1:9000/health
```

结果：

```json
{
  "status": "ok",
  "service": "lingxun-cloud-gateway",
  "rk_backend_base_url": "http://100.113.173.115:8000",
  "rk_online": true,
  "public_control_enabled": false
}
```

### 浏览器音频入口

已用测试 WebM 音频验证：

```bash
curl -X POST https://lingxunrobot.cn/api/voice/browser_audio_command \
  -H "Authorization: Bearer <PUBLIC_API_TOKEN>" \
  -F "file=@/tmp/phase8b_browser_test.webm;type=audio/webm" \
  -F "source=browser-mic" \
  -F "requested_by=phase8b-validation" \
  -F "keep_audio=false"
```

结果：请求成功到达 RK3588 `/api/voice/audio_command`，云端完成 WebM -> 16kHz mono wav 转码，并返回 FunASR 结果。测试音频是纯音，不包含人声，因此 `recognized_text` 为空，`accepted=false`，这是预期结果。

### 鉴权验证

未携带 token 调用：

```bash
curl -X POST https://lingxunrobot.cn/api/voice/browser_audio_command
```

结果：返回 `401 unauthorized`。

### 原始本地录音接口公网禁用

```bash
curl -X POST https://lingxunrobot.cn/api/voice/record_command
```

结果：返回 `403 public_endpoint_disabled`。

### 车载麦克风入口

```bash
curl -X POST https://lingxunrobot.cn/api/robot/voice/onboard_record_command \
  -H "Authorization: Bearer <PUBLIC_API_TOKEN>" \
  -H "Content-Type: application/json" \
  -d '{"duration":1,"source":"onboard-mic","requested_by":"phase8b-validation"}'
```

结果：请求成功转发到 RK3588 `/api/voice/record_command`。自动验收时未对车载麦克风说话，因此返回 `asr_failed` / 未识别到有效文本，但接口链路、鉴权和转发路径均已打通。

### 前端构建

```bash
cd /home/robomaster/QHXD/frontend
npm run build
```

结果：构建通过，公网前端构建产物中包含 `网页麦克风识别` 与 `车载麦克风识别` 两个入口。

## 人工验收提示

1. 打开 `https://lingxunrobot.cn`。
2. 在页面顶部 Token 输入框填入云服务器 `/etc/lingxun-cloud-gateway.env` 中的 `PUBLIC_API_TOKEN`，保存。
3. 点击 `网页麦克风识别`，浏览器允许麦克风权限后说出命令。
4. 点击 `车载麦克风识别`，靠近 RK3588 连接的 USB 麦克风说话。
5. 移动类命令应继续走二次确认弹窗；在 `PUBLIC_CONTROL_ENABLED=false` 时，公网 mission 执行仍应被安全开关拒绝。

## 已知限制

- 命令行验收只能验证上传、转码、鉴权和转发链路；真实网页麦克风语音内容需要在浏览器中人工说话测试。
- 车载麦克风入口依赖 RK3588 本机音频设备、FunASR 模型和后端运行状态。
- 当前不会将浏览器临时音频默认长期保存；只有请求 `keep_audio=true` 时才会保留到云端保留目录，并受 `GATEWAY_AUDIO_KEEP_MAX_FILES` 限制。
