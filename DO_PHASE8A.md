# DO_PHASE8A.md

# Phase 8A：公网 Dashboard + Cloud Gateway + RK3588 转发链路

> 本文件已按当前 RK3588 `/home/robomaster/QHXD`、云服务器 `ubuntu@106.53.169.127` 与最新决策重新校准。  
> Phase 8A 不再只是静态前端部署，而是要完成公网前端、公网 API、公网 WebSocket、云端中继到 RK3588 的最终版基础链路。  
> 云服务器不部署完整 QHXD backend；完整 QHXD backend 继续运行在 RK3588 上。

---

## 0. 架构结论

### 最终部署角色

```text
浏览器 / 小程序 / 外部客户端
        |
        v
云服务器 Nginx
        |
        v
Cloud Gateway: 127.0.0.1:9000
        |
        v
RK3588 QHXD backend
```

云服务器只部署：

```text
1. 静态前端 dist
2. Nginx HTTPS / 反代
3. cloud gateway / 云端中继后端
```

云服务器不部署完整 QHXD backend，原因：

```text
FunASR、YOLO NPU、USB/Hik 相机、USB 麦克风、Navi 通信、C 板通信都依赖机器人本体环境。
```

RK3588 继续运行完整本体后端：

```text
/home/robomaster/QHXD/backend
```

---

## 1. 当前实际情况核对

### RK3588 项目

```text
项目路径：/home/robomaster/QHXD
前端：frontend/，Vue 3 + Vite + TypeScript
后端：backend/app/main.py
```

当前前端主要文件：

```text
frontend/src/App.vue
frontend/src/components/NavigationAssistPanel.vue
frontend/src/components/NavMapPlaceholder.vue
frontend/src/components/VoiceConfirmDialog.vue
frontend/vite.config.ts
```

当前前端开发态：

```text
fetch / ws 使用相对路径 /api 与 /ws
Vite dev proxy 使用 VITE_BACKEND_URL，默认 http://127.0.0.1:8000
```

当前 RK3588 backend 已有重要接口：

```text
GET  /health
GET  /api/state/latest
GET  /api/alerts
GET  /api/commands/logs
GET  /api/tasks/current
GET  /api/imu/latest
GET  /api/perception/latest_frame
HEAD /api/perception/latest_frame
GET  /api/perception/frame_stream

POST /api/voice/text_command
POST /api/voice/asr_text_mock
POST /api/voice/confirm_command
POST /api/voice/audio_command
POST /api/voice/record_command

POST /api/mission/go_to_waypoint
POST /api/mission/start_patrol
POST /api/mission/pause
POST /api/mission/resume
POST /api/mission/return_home

POST /api/system/mode/switch

POST /api/internal/perception/detection_status
POST /api/internal/nuc/state
POST /api/internal/nuc/imu

WS   /ws/state
WS   /ws/imu
```

注意：

```text
当前不存在 GET /api/sensors/env/latest。
Phase 8A 不得要求前端调用这个不存在的接口。
```

### 云服务器

SSH：

```bash
ssh ubuntu@106.53.169.127
```

当前状态：

```text
Ubuntu 24.04
Nginx 已安装
/var/www/lingxunrobot 已存在，但当前只是占位 index.html
```

已有 Nginx 站点：

```text
/etc/nginx/sites-enabled/lingxunrobot-front
/etc/nginx/sites-enabled/lingxunrobot-api
```

当前前端站点：

```text
lingxunrobot.cn
www.lingxunrobot.cn
root /var/www/lingxunrobot
SPA fallback: try_files $uri $uri/ /index.html
```

当前 API 站点：

```text
api.lingxunrobot.cn
proxy_pass http://127.0.0.1:9000
已配置 WebSocket Upgrade 头
client_max_body_size 20M
```

当前 9000 服务：

```text
GET http://127.0.0.1:9000/health
返回 {"status": "ok", "service": "lingxun-cloud-test"}
```

结论：

```text
当前 127.0.0.1:9000 只是测试服务，不是正式 cloud gateway。
Phase 8A 需要替换/扩展它为云端中继后端。
```

---

## 2. 公网入口规范

### Web 前端优先同域入口

浏览器访问：

```text
https://lingxunrobot.cn
```

浏览器前端优先使用同域相对路径：

```text
REST: /api
WS:   /ws/state
WS:   /ws/imu
```

实际经过 Nginx 转发：

```text
https://lingxunrobot.cn/api/* -> http://127.0.0.1:9000/api/*
wss://lingxunrobot.cn/ws/*    -> http://127.0.0.1:9000/ws/*
```

### 小程序 / 外部客户端入口

外部客户端访问：

```text
https://api.lingxunrobot.cn
wss://api.lingxunrobot.cn/ws/state
wss://api.lingxunrobot.cn/ws/imu
```

实际经过 Nginx 转发：

```text
https://api.lingxunrobot.cn/* -> http://127.0.0.1:9000/*
```

### 两种入口必须等价

以下两组路径最终都必须进入 cloud gateway：

```text
https://lingxunrobot.cn/api/state/latest
https://api.lingxunrobot.cn/api/state/latest
```

```text
wss://lingxunrobot.cn/ws/state
wss://api.lingxunrobot.cn/ws/state
```

---

## 3. 本阶段目标

```text
[ ] 前端公网可访问：https://lingxunrobot.cn
[ ] 前端通过同域 /api /ws 访问 cloud gateway
[ ] api.lingxunrobot.cn 作为小程序/外部客户端入口可用
[ ] cloud gateway 监听云服务器 127.0.0.1:9000
[ ] cloud gateway 能转发请求到 RK3588 QHXD backend
[ ] /ws/state 与 /ws/imu 公网可用
[ ] /api/perception/frame_stream MJPEG 公网可用
[ ] /api/voice/audio_command 公网可用
[ ] /api/voice/record_command 不暴露到公网
[ ] mission 控制具备鉴权与安全开关
[ ] 不改变 RK3588 后端现有业务 API 契约
```

---

## 4. 本阶段不做

```text
[×] 不把完整 QHXD backend 部署到云服务器
[×] 不改 RK3588 后端已有 API 路由名称
[×] 不改 mission 执行语义
[×] 不让公网前端直接访问 RK3588 局域网 / Tailscale 地址
[×] 不让公网前端直接访问 ESP8266 / C 板 / Navi
[×] 不重新训练模型
[×] 不重新转换 RKNN
[×] 不改 FunASR / YOLO / Navi / C 板本体能力
[×] 不暴露 /api/voice/record_command 到公网
[×] 不跳过移动类任务二次确认
[×] 不把公网控制裸奔暴露
```

允许做：

```text
[✓] 新增 cloud gateway 服务
[✓] 新增 cloud gateway systemd 服务
[✓] 新增云端鉴权、安全开关、日志、限流
[✓] 新增前端 API 配置文件
[✓] 调整前端 URL 生成方式
[✓] 调整云端 Nginx /api /ws 反代
[✓] 新增部署 README
[✓] 新增 RK3588 到云端的转发/隧道客户端，前提是不破坏本地 backend API
```

---

## 5. 推荐转发方案

### 首选：RK3588 主动连接云端 tunnel

推荐 cloud gateway 与 RK3588 之间采用 RK 主动出站连接：

```text
RK3588 gateway client  --->  cloud gateway
```

理由：

```text
1. 不需要公网直接暴露 RK3588。
2. 不依赖路由器端口映射。
3. 云端统一承接公网 HTTPS / WSS。
4. 机器人离线时 cloud gateway 可以明确返回 offline。
```

可选实现：

```text
1. WebSocket tunnel
2. HTTP reverse tunnel
3. Tailscale 私网直连作为临时验收路径
```

无论内部采用哪种方式，对外路径必须保持：

```text
/api/...
/ws/state
/ws/imu
```

---

## 6. Cloud Gateway 职责

cloud gateway 不是完整机器人后端，只做：

```text
1. 公网鉴权
2. 请求白名单
3. 安全开关检查
4. 限流
5. 操作日志
6. 机器人在线状态判断
7. 转发 REST 到 RK3588 backend
8. 代理 WebSocket 到 RK3588 backend
9. 代理 MJPEG / latest_frame 到 RK3588 backend
10. 对公网隐藏不应暴露的本地接口
```

cloud gateway 不做：

```text
1. 不直接控制底盘
2. 不直接跑 YOLO
3. 不直接跑 FunASR 本机录音
4. 不直接连 C 板
5. 不改变 RK backend 的业务响应结构
```

---

## 7. 公网接口暴露规则

### 允许公网只读接口

```text
GET /health
GET /api/state/latest
GET /api/alerts
GET /api/commands/logs
GET /api/tasks/current
GET /api/imu/latest
GET /api/perception/latest_frame
GET /api/perception/frame_stream
WS  /ws/state
WS  /ws/imu
```

### 允许公网语音/LLM接口

```text
POST /api/voice/text_command
POST /api/voice/audio_command
POST /api/voice/confirm_command
```

说明：

```text
公网语音应由浏览器/小程序录音后上传音频到 /api/voice/audio_command。
```

### 禁止公网暴露接口

```text
POST /api/voice/record_command
```

原因：

```text
/api/voice/record_command 是“服务器本机录音”语义。
公网请求该接口会变成让云服务器录音，而不是让用户浏览器录音，也不应误导成远程录音功能。
该接口只能留在 RK3588 本地测试/本地网页使用。
```

公网访问该接口应返回：

```text
403 forbidden
或 404 not found
```

### mission 控制接口

以下接口公网可存在，但必须经过安全链路：

```text
POST /api/mission/go_to_waypoint
POST /api/mission/start_patrol
POST /api/mission/pause
POST /api/mission/resume
POST /api/mission/return_home
POST /api/system/mode/switch
```

必须满足：

```text
1. Token / 登录鉴权
2. PUBLIC_CONTROL_ENABLED=true 才允许移动类控制，默认 false
3. 移动类任务二次确认
4. 命令白名单
5. 操作日志
6. 请求限流
7. 机器人离线时禁止执行
8. 急停时禁止执行
9. 故障状态时禁止执行
```

移动类任务包括但不限于：

```text
go_to_waypoint
start_patrol
return_home
system mode real 切换后触发真实控制的命令
```

---

## 8. 安全配置要求

cloud gateway 必须支持环境变量：

```bash
PUBLIC_CONTROL_ENABLED=false
PUBLIC_API_TOKEN=
PUBLIC_RATE_LIMIT_PER_MINUTE=60
PUBLIC_AUDIO_MAX_MB=20
RK_BACKEND_BASE_URL=http://127.0.0.1:8000
RK_TUNNEL_MODE=
```

说明：

```text
PUBLIC_CONTROL_ENABLED 默认必须是 false。
即使有 token，只要 PUBLIC_CONTROL_ENABLED=false，移动类 mission 也不能执行。
```

鉴权要求：

```text
只读状态接口可按部署策略决定是否免登录。
写接口必须鉴权。
mission / system mode 写接口必须鉴权 + 安全开关。
```

建议请求头：

```text
Authorization: Bearer <token>
```

操作日志至少记录：

```text
timestamp
client_ip
method
path
user/token_id
request_id
accepted/rejected
reject_reason
forward_status
```

---

## 9. 前端改造任务

## Task 1：统一前端 API / WS / Frame URL 配置

新增或更新：

```text
frontend/src/config/api.ts
```

至少导出：

```ts
API_BASE_URL
WS_STATE_URL
WS_IMU_URL
apiUrl(path: string): string
wsUrl(path: string): string
perceptionFrameStreamUrl(): string
perceptionLatestFrameUrl(): string
```

生产 Web 推荐配置：

```bash
VITE_API_BASE_URL=
VITE_WS_STATE_URL=
VITE_WS_IMU_URL=
```

含义：

```text
留空表示同域：
apiUrl('/api/state/latest') -> /api/state/latest
wsUrl('/ws/state') -> wss://lingxunrobot.cn/ws/state
```

外部客户端不使用前端 env，直接访问：

```text
https://api.lingxunrobot.cn
wss://api.lingxunrobot.cn/ws/state
```

开发环境继续保留：

```bash
VITE_BACKEND_URL=http://127.0.0.1:8000
```

该变量只给 Vite dev proxy 使用。

### 必须替换的位置

当前前端中以下调用不能继续散落硬编码：

```text
fetch('/api/state/latest')
fetch('/api/alerts')
fetch('/api/imu/latest')
fetch('/api/voice/text_command')
fetch('/api/voice/record_command')
fetch('/api/voice/confirm_command')
fetch('/api/system/mode/switch')
sendMission('/api/mission/...')
new WebSocket(`${protocol}://${window.location.host}/ws/state`)
new WebSocket(`${protocol}://${window.location.host}/ws/imu`)
latestFrameUrl = `/api/perception/frame_stream?t=...`
latestFrameUrl = `/api/perception/latest_frame?t=...`
```

### record_command 前端限制

公网生产页面不得调用：

```text
POST /api/voice/record_command
```

如仍需本地 RK 页面使用板端录音，必须通过环境变量或本地模式隐藏/显示：

```text
VITE_ENABLE_LOCAL_RECORD_COMMAND=false
```

生产默认：

```text
false
```

---

## Task 2：前端环境变量

新增或更新：

```text
frontend/.env.production
```

推荐：

```bash
# Web 生产优先走同域 Nginx 反代。
VITE_API_BASE_URL=
VITE_WS_STATE_URL=
VITE_WS_IMU_URL=
VITE_ENABLE_LOCAL_RECORD_COMMAND=false
VITE_USE_MJPEG_STREAM=true
VITE_LATEST_FRAME_INTERVAL_MS=2000
VITE_DETECTION_EVENT_HOLD_MS=15000
VITE_DETECTION_EVENT_MAX_ITEMS=12
```

新增或保留：

```text
frontend/.env.development
```

推荐：

```bash
VITE_API_BASE_URL=
VITE_WS_STATE_URL=
VITE_WS_IMU_URL=
VITE_BACKEND_URL=http://127.0.0.1:8000
VITE_ENABLE_LOCAL_RECORD_COMMAND=true
VITE_USE_MJPEG_STREAM=true
VITE_LATEST_FRAME_INTERVAL_MS=2000
VITE_DETECTION_EVENT_HOLD_MS=15000
VITE_DETECTION_EVENT_MAX_ITEMS=12
```

---

## Task 3：前端硬编码清理

执行：

```bash
cd ~/QHXD/frontend
grep -R "localhost\|127.0.0.1\|192.168\|http://\|https://\|ws://\|wss://" src vite.config.ts -n
```

允许保留：

```text
src/config/api.ts
vite.config.ts
.env.production
.env.development
README
```

不允许：

```text
App.vue 或业务组件散落本地/生产 API 地址。
```

---

## Task 4：WebSocket 与轮询降级

公网 Web 必须连接：

```text
wss://lingxunrobot.cn/ws/state
wss://lingxunrobot.cn/ws/imu
```

外部客户端可连接：

```text
wss://api.lingxunrobot.cn/ws/state
wss://api.lingxunrobot.cn/ws/imu
```

如果 `/ws/state` 失败：

```text
降级轮询 GET /api/state/latest
页面显示“实时流断开，轮询中”
```

如果 `/ws/imu` 失败：

```text
降级轮询 GET /api/imu/latest
页面显示“IMU 流断开，轮询中”
```

---

## Task 5：MJPEG 与 latest_frame

公网 Web 默认：

```text
GET /api/perception/frame_stream
```

fallback：

```text
GET /api/perception/latest_frame?t=...
```

要求：

```text
YOLO 感知监视器不能被删除。
MJPEG 出错时仍回退 latest_frame。
图像流失败时显示空状态，不白屏。
```

---

## 10. Cloud Gateway 任务

## Task 6：实现 cloud gateway 服务

新增云端服务代码，建议目录：

```text
cloud_gateway/
```

或放入 QHXD 中可同步部署的目录：

```text
deploy/cloud_gateway/
```

服务监听：

```text
127.0.0.1:9000
```

必须实现：

```text
GET /health
REST /api/* 白名单转发
WS /ws/state 转发
WS /ws/imu 转发
MJPEG /api/perception/frame_stream 转发
latest_frame /api/perception/latest_frame 转发
公网禁止 /api/voice/record_command
写接口鉴权
mission 安全开关
限流
操作日志
机器人离线时返回清晰错误
```

### Cloud Gateway 到 RK3588

推荐支持两种方式：

```text
1. RK_BACKEND_BASE_URL 直连模式
2. RK 主动 tunnel 模式
```

直连模式用于临时验收：

```bash
RK_BACKEND_BASE_URL=http://<rk3588-private-ip>:8000
```

tunnel 模式用于最终部署：

```text
RK3588 主动连接 cloud gateway，cloud gateway 通过该连接转发请求。
```

---

## Task 7：公网安全控制

cloud gateway 必须对写接口做鉴权：

```text
POST /api/voice/text_command
POST /api/voice/audio_command
POST /api/voice/confirm_command
POST /api/mission/*
POST /api/system/mode/switch
```

mission 与真实控制必须额外检查：

```text
PUBLIC_CONTROL_ENABLED=true
机器人在线
非急停
非故障
命令在白名单中
二次确认已完成
```

未通过时必须拒绝，不得转发到 RK3588。

---

## Task 8：Nginx 同域与 API 子域反代

前端站点必须支持：

```nginx
server_name lingxunrobot.cn www.lingxunrobot.cn;
root /var/www/lingxunrobot;

location /api/ {
    proxy_pass http://127.0.0.1:9000/api/;
}

location /ws/ {
    proxy_pass http://127.0.0.1:9000/ws/;
    proxy_http_version 1.1;
    proxy_set_header Upgrade $http_upgrade;
    proxy_set_header Connection "upgrade";
}

location / {
    try_files $uri $uri/ /index.html;
}
```

API 子域必须支持：

```nginx
server_name api.lingxunrobot.cn;

location / {
    proxy_pass http://127.0.0.1:9000;
    proxy_http_version 1.1;
    proxy_set_header Upgrade $http_upgrade;
    proxy_set_header Connection "upgrade";
    client_max_body_size 20M;
}
```

注意：

```text
Web 前端优先同域 /api /ws。
api.lingxunrobot.cn 保留给小程序和外部客户端。
```

---

## Task 9：部署前端 dist

构建：

```bash
cd ~/QHXD/frontend
npm install
npm run build
```

部署：

```bash
rsync -av --delete dist/ ubuntu@106.53.169.127:/tmp/lingxunrobot-dist/

ssh ubuntu@106.53.169.127
sudo mkdir -p /var/www/lingxunrobot
sudo rsync -av --delete /tmp/lingxunrobot-dist/ /var/www/lingxunrobot/
sudo nginx -t
sudo systemctl reload nginx
```

---

## Task 10：文档更新

更新：

```text
README.md
frontend/README.md
cloud_gateway/README.md 或 deploy/cloud_gateway/README.md
```

必须写清楚：

```text
公网前端：https://lingxunrobot.cn
Web API 入口：https://lingxunrobot.cn/api
Web WS 入口：wss://lingxunrobot.cn/ws/state
外部 API 入口：https://api.lingxunrobot.cn
外部 WS 入口：wss://api.lingxunrobot.cn/ws/state
cloud gateway 监听：127.0.0.1:9000
完整 QHXD backend 仍在 RK3588
/api/voice/record_command 不公网暴露
公网语音用 /api/voice/audio_command
PUBLIC_CONTROL_ENABLED 默认 false
如何启停 cloud gateway
如何查看 gateway 日志
如何切换 RK_BACKEND_BASE_URL / tunnel
```

---

# 11. 验收标准

## A. 前端公网验收

```text
[ ] https://lingxunrobot.cn 能打开 Dashboard
[ ] https://www.lingxunrobot.cn 能访问或跳转
[ ] 浏览器无证书错误
[ ] 页面刷新后不 404
[ ] dist/assets 无 404
[ ] 页面没有请求 localhost / 127.0.0.1 / 192.168.x.x
```

## B. 同域 API 验收

```text
[ ] GET https://lingxunrobot.cn/api/state/latest 可到达 cloud gateway
[ ] GET https://lingxunrobot.cn/api/imu/latest 可到达 cloud gateway
[ ] GET https://lingxunrobot.cn/api/perception/latest_frame 可到达 cloud gateway
[ ] GET https://lingxunrobot.cn/api/perception/frame_stream 可到达 cloud gateway
[ ] wss://lingxunrobot.cn/ws/state 可连接或清晰降级
[ ] wss://lingxunrobot.cn/ws/imu 可连接或清晰降级
```

## C. API 子域验收

```text
[ ] GET https://api.lingxunrobot.cn/health 返回 cloud gateway 健康状态
[ ] GET https://api.lingxunrobot.cn/api/state/latest 可用
[ ] wss://api.lingxunrobot.cn/ws/state 可用
[ ] wss://api.lingxunrobot.cn/ws/imu 可用
```

## D. RK3588 转发验收

```text
[ ] cloud gateway 能判断 RK3588 online/offline
[ ] RK online 时 /api/state/latest 返回 RK 后端状态
[ ] RK online 时 /api/perception/frame_stream 可显示实时图像
[ ] RK online 时 /ws/state 能收到状态更新
[ ] RK offline 时公网 API 返回明确 offline，不白屏
```

## E. 语音接口验收

```text
[ ] POST /api/voice/audio_command 公网可上传音频并转发
[ ] POST /api/voice/text_command 公网可用但必须鉴权
[ ] POST /api/voice/confirm_command 公网可用但必须鉴权
[ ] POST /api/voice/record_command 公网返回 403 或 404
[ ] 前端生产页面不显示“板端录音/record_command”入口
```

## F. 控制安全验收

```text
[ ] 未带 token 的 mission 写请求被拒绝
[ ] PUBLIC_CONTROL_ENABLED=false 时移动类 mission 被拒绝
[ ] PUBLIC_CONTROL_ENABLED=true 且 token 正确时才允许进入二次确认流程
[ ] 移动类任务仍触发前端二次确认弹窗
[ ] 命令不在白名单时被拒绝
[ ] RK 离线时 mission 被拒绝
[ ] 急停/故障时 mission 被拒绝
[ ] 操作日志能记录 accepted/rejected 与原因
[ ] 请求限流生效
```

## G. 前端功能回归

```text
[ ] 顶部状态卡片正常
[ ] Mock / Real 模式切换仍存在
[ ] 语音 / LLM 命令面板仍存在
[ ] 移动任务二次确认弹窗仍存在
[ ] YOLO 感知监视器仍存在
[ ] MJPEG 流仍存在
[ ] latest_frame fallback 仍存在
[ ] 导航实时可视化仍存在
[ ] Navigation Assist 任务执行链路仍存在
[ ] 任务快捷控制仍存在
[ ] 告警 / 事件区域仍存在
```

## H. 硬编码清理验收

执行：

```bash
cd ~/QHXD/frontend
grep -R "localhost\|127.0.0.1\|192.168\|http://\|https://\|ws://\|wss://" src vite.config.ts -n
```

验收：

```text
[ ] App.vue 不散落 API 地址
[ ] 业务组件不直接写生产 API 地址
[ ] 地址只出现在 config / vite / env / 文档中
```

---

# 12. 阶段通过标准

Phase 8A 通过条件：

```text
[ ] 前端公网可访问
[ ] Web 前端通过同域 /api /ws 使用 cloud gateway
[ ] api.lingxunrobot.cn 可供外部客户端使用
[ ] cloud gateway 运行在云服务器 127.0.0.1:9000
[ ] cloud gateway 能转发到 RK3588 backend
[ ] /ws/state 与 /ws/imu 公网链路可用或可降级
[ ] /api/perception/frame_stream 公网链路可用
[ ] /api/voice/audio_command 公网链路可用
[ ] /api/voice/record_command 不公网暴露
[ ] mission 控制有 token / 安全开关 / 二次确认 / 白名单 / 日志 / 限流 / 离线故障拦截
[ ] 前端现有 Dashboard 功能未被删除
[ ] README 记录部署、启动、配置与安全边界
```

---

# 13. 风险与注意事项

```text
1. 如果采用 Tailscale 直连 RK3588，云端到 RK 的网络可用性需要单独验收。
2. 如果采用 RK 主动 tunnel，需要设计长连接断线重连与请求超时。
3. MJPEG 经公网转发可能带宽较高，需要限并发与超时。
4. /api/voice/audio_command 上传文件需要限制大小和格式。
5. mission 控制默认必须关闭，不能因部署完成就默认允许公网移动机器人。
6. 同域 /api 反代优先，能减少浏览器 CORS 问题。
7. api.lingxunrobot.cn 仍需保留 CORS 策略给小程序/外部客户端。
```
