# PHASE8A_DONE

## 完成内容

Phase 8A 已从“静态前端部署”升级为公网 Dashboard + Cloud Gateway + RK3588 转发链路：

- 前端公网部署到 `https://lingxunrobot.cn`
- Web 前端优先使用同域 `/api` 与 `/ws`
- 外部客户端保留 `https://api.lingxunrobot.cn`
- 云服务器运行 `lingxun-cloud-gateway`，监听 `127.0.0.1:9000`
- 完整 QHXD backend 继续运行在 RK3588
- Cloud Gateway 通过 Tailscale 访问 RK3588 backend：`http://100.113.173.115:8000`

## 主要代码改动

### frontend/src/config/api.ts

新增统一前端 API 配置：

- `apiUrl(path)`
- `wsUrl(path)`
- `perceptionFrameStreamUrl()`
- `perceptionLatestFrameUrl()`
- `authHeaders()`
- `ENABLE_LOCAL_RECORD_COMMAND`

生产环境默认走同域：

```text
/api
/ws/state
/ws/imu
```

### frontend/src/App.vue

将散落的 `fetch('/api/...')` 与 `new WebSocket(...)` 改为统一配置：

- REST 请求通过 `apiUrl(...)`
- WebSocket 通过 `wsUrl(...)`
- MJPEG / latest frame 通过 `perceptionFrameStreamUrl()` / `perceptionLatestFrameUrl()`
- 写接口自动带 `Authorization: Bearer <token>`
- 公网生产默认隐藏板端录音 `record_command` 按钮

### frontend/.env.production

新增生产配置：

```env
VITE_API_BASE_URL=
VITE_WS_STATE_URL=
VITE_WS_IMU_URL=
VITE_ENABLE_LOCAL_RECORD_COMMAND=false
VITE_USE_MJPEG_STREAM=true
```

### frontend/.env.development

新增开发配置：

```env
VITE_BACKEND_URL=http://127.0.0.1:8000
VITE_ENABLE_LOCAL_RECORD_COMMAND=true
```

### cloud_gateway/

新增云端中继服务：

- `cloud_gateway.py`
- `requirements.txt`
- `.env.example`
- `lingxun-cloud-gateway.service`
- `README.md`

Cloud Gateway 功能：

- 白名单转发公网 REST
- 代理 `/ws/state`
- 代理 `/ws/imu`
- 代理 MJPEG `/api/perception/frame_stream`
- 禁止公网 `/api/voice/record_command`
- 写接口 token 鉴权
- mission 控制安全开关
- 请求限流
- 操作日志
- CORS 支持
- RK 离线时返回明确错误

### README.md

新增 Phase 8A 公网访问与 Cloud Gateway 说明：

- 公网入口
- 云端环境变量
- 安全边界
- `record_command` 禁止公网暴露
- `audio_command` 作为公网语音入口
- gateway 启停与日志命令

## 云服务器部署

静态前端：

```text
/var/www/lingxunrobot
```

Cloud Gateway：

```text
/opt/lingxun-cloud-gateway
/etc/lingxun-cloud-gateway.env
/etc/systemd/system/lingxun-cloud-gateway.service
```

Nginx：

```text
lingxunrobot.cn /api/ -> http://127.0.0.1:9000/api/
lingxunrobot.cn /ws/  -> http://127.0.0.1:9000/ws/
api.lingxunrobot.cn/* -> http://127.0.0.1:9000/*
```

## 当前安全配置

```text
PUBLIC_CONTROL_ENABLED=false
```

因此公网 mission 移动类控制即使带 token 也会被拒绝，返回：

```text
public_control_disabled
```

公网禁用：

```text
POST /api/voice/record_command
```

返回：

```text
403 public_endpoint_disabled
```

## 验收结果

已验证：

- RK3588 backend `/health` 正常
- 前端 `npm run build` 成功
- Cloud Gateway systemd active
- `GET http://127.0.0.1:9000/health` 返回 `rk_online=true`
- `GET https://lingxunrobot.cn/api/state/latest` 可经 gateway 到 RK
- `GET https://api.lingxunrobot.cn/health` 可用
- `wss://lingxunrobot.cn/ws/state` 可收到 RK 状态
- `wss://api.lingxunrobot.cn/ws/state` 可收到 RK 状态
- `/api/voice/record_command` 公网 403
- 无 token 写接口 401
- 带 token mission 在 `PUBLIC_CONTROL_ENABLED=false` 时 403
- 操作日志写入 `/var/log/lingxun-cloud-gateway/operations.jsonl`
- CORS 预检允许 `https://lingxunrobot.cn`

## 非阻塞说明

当前 RK3588 未接入 Hik 相机、USB 相机和 C 板，因此：

- YOLO 摄像头服务无法打开相机是预期现象
- `/api/perception/latest_frame` 可能返回过期或 404
- `/api/perception/frame_stream` 链路可转发，但没有新相机帧可用于视觉验收
- C 板 / Navi 真实链路不作为本轮 Phase 8A 公网 gateway 验收阻塞项

后续接入相机和 C 板后，只需保持 RK backend 与 YOLO 服务正常运行，公网 Dashboard 会继续通过 Cloud Gateway 访问同一组 `/api` 与 `/ws` 接口。

## 追加修复：公网写接口可操作性

用户验收时发现公网前端点击 Real、发送文本命令、前往目标点时只显示泛化失败信息。原因是 Phase 8A gateway 已按安全要求拦截公网写接口，但前端没有提供 Token 输入入口，也没有展示 gateway 返回的真实错误码。

已修复：

- `frontend/src/App.vue` 顶部新增公网 Token 输入/保存控件，保存到 `localStorage.qhxd_api_token`。
- `frontend/src/App.vue` 写接口失败时解析 gateway JSON 错误，显示 `unauthorized`、`public_control_disabled`、`public_endpoint_disabled`、`robot_offline` 等明确原因。
- `cloud_gateway/cloud_gateway.py` 调整安全策略：`/api/system/mode/switch` 仍需要 Token，但不再受 `PUBLIC_CONTROL_ENABLED=false` 阻断；安全开关继续用于 `/api/mission/*` 移动类控制。
- 已重新构建并部署公网前端 dist。
- 已重启云端 `lingxun-cloud-gateway`。

复验：

- 带 Token 调用 `/api/system/mode/switch` 返回 200。
- 带 Token 调用 `/api/voice/text_command` 返回 `need_confirm=true` 和 `pending_command_id`。
- 带 Token 调用 `/api/mission/go_to_waypoint` 在 `PUBLIC_CONTROL_ENABLED=false` 时仍返回 `403 public_control_disabled`，符合公网安全开关要求。

注意：公网页面需要先在顶部保存 Token，写接口才会执行。移动类 mission 还需要云服务器 `/etc/lingxun-cloud-gateway.env` 中 `PUBLIC_CONTROL_ENABLED=true` 才允许进入真实执行链路。
