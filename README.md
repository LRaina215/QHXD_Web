# RK3588 Middleware Phase 2

## 项目目的

本项目用于把 RK3588 做成 RoboMaster 车载系统的交互与状态中台。

当前已完成 Phase 2 的核心目标：

- 保留 Phase 1 的 mock 中台能力
- 接入 `NUC -> RK3588` 的真实状态上送
- 接入 `RK3588 -> NUC` 的 mission bridge
- 让 Dashboard 通过 REST / WebSocket 观察 mock 与 real 两种模式

当前范围仍然只覆盖 Phase 2：

- 不接 RT-Thread 直连
- 不做语音、图传、视觉增强能力
- 不扩展到多页面复杂前端

## 快速运行

### 后端

```bash
cd backend
python3 -m pip install -r requirements.txt
python3 -m uvicorn app.main:app --host 0.0.0.0 --port 8000
```

最小检查：

```bash
curl http://127.0.0.1:8000/health
curl http://127.0.0.1:8000/api/state/latest
```

数据库默认写入：

```text
backend/data/rk3588_phase1.db
```

### 前端

```bash
cd frontend
npm install
npm run dev -- --host 0.0.0.0 --port 5173
```

打开：

```text
http://127.0.0.1:5173
```

开发态默认把 `/api` 和 `/ws` 代理到 `http://127.0.0.1:8000`。

## 如何使用 Mock 模式

默认启动后即可直接使用 mock 模式。

在 mock 模式下：

- 状态来自 [backend/app/services/mock_state.py](/home/robomaster/QHXD/backend/app/services/mock_state.py)
- 页面会显示 `MOCK`
- mission 接口走本地 mock 流程
- WebSocket 会持续推送本地生成的状态

手工切回 mock：

```bash
curl -X POST http://127.0.0.1:8000/api/system/mode/switch \
  -H 'Content-Type: application/json' \
  -d '{"mode":"mock","source":"manual-check","requested_by":"operator"}'
```

## 如何使用 Real 模式

### 1. 正确启动 RK3588 后端

如果要桥接 NUC mission 服务，RK3588 后端必须带上正确的环境变量。

示例：

```bash
export NUC_BASE_URL=http://192.168.10.3:8090
export NUC_MISSION_PATH=/api/internal/rk3588/mission

cd backend
python3 -m uvicorn app.main:app --host 0.0.0.0 --port 8000
```

这一步非常关键。Round 3 / Round 4 联调中出现过：

- NUC 状态上送正常
- NUC mission 服务正常
- 但 RK3588 public mission API 返回 `accepted=false`

最终确认根因是：

- **RK3588 正式运行实例没有带着正确的 `NUC_BASE_URL` / `NUC_MISSION_PATH` 启动**

也就是说，这类问题优先检查 RK3588 启动配置，而不是先怀疑 NUC 功能缺失。

### 2. 切换到 real 模式

```bash
curl -X POST http://127.0.0.1:8000/api/system/mode/switch \
  -H 'Content-Type: application/json' \
  -d '{"mode":"real","source":"manual-check","requested_by":"operator"}'
```

切到 real 后，如果还没收到 NUC 首包，页面和状态会显示：

- `system_mode.mode=real`
- `device_status.online=false`
- `device_status.fault_code=waiting-for-real-state`

### 3. 确认 NUC 接口直连正常

先从 RK3588 直接打一次 NUC mission 服务：

```bash
curl --noproxy '*' -X POST http://192.168.10.3:8090/api/internal/rk3588/mission \
  -H 'Content-Type: application/json' \
  -d '{"command":"go_to_waypoint","source":"rk3588-direct-check","requested_by":"operator","payload":{"waypoint_id":"wp-check-001"}}'
```

如果这里成功，再测试 RK3588 public mission API：

```bash
curl -X POST http://127.0.0.1:8000/api/mission/go_to_waypoint \
  -H 'Content-Type: application/json' \
  -d '{"waypoint_id":"wp-check-001","source":"manual-check","requested_by":"operator"}'
```

### 4. NUC 状态上送入口

NUC 的真实状态通过这个接口进入 RK3588：

```text
POST /api/internal/nuc/state
```

进入后会写入共享状态，再通过：

- `GET /api/state/latest`
- `GET /api/tasks/current`
- `WS /ws/state`
- Dashboard

统一对外可见。

### 5. NUC IMU 调试入口

为了配合当前 C 板只能稳定提供 IMU 的联调阶段，RK3588 还提供了一个最小 IMU 专项链路：

```text
POST /api/internal/nuc/imu
GET /api/imu/latest
WS /ws/imu
```

说明：

- 这条链路不改已有 `POST /api/internal/nuc/state` 契约
- 适合 NUC 先把真实 IMU 样本独立送到 RK3588 做专项验收
- 前端 Dashboard 已增加最小 IMU 调试卡片

## NUC 适配器接入点

当前 NUC 相关逻辑主要在这些文件：

- [backend/app/services/nuc_adapter.py](/home/robomaster/QHXD/backend/app/services/nuc_adapter.py)
- [backend/app/services/state_store.py](/home/robomaster/QHXD/backend/app/services/state_store.py)
- [backend/app/services/mission_gateway.py](/home/robomaster/QHXD/backend/app/services/mission_gateway.py)
- [backend/app/services/mode_manager.py](/home/robomaster/QHXD/backend/app/services/mode_manager.py)

职责分工：

- `nuc_adapter.py`
  负责 NUC 状态接入和 mission bridge
- `state_store.py`
  负责保存当前共享状态
- `mission_gateway.py`
  负责 mock / real 命令分流
- `mode_manager.py`
  负责模式切换、离线判定、恢复判定和 bridge 错误暴露

## 开发调试说明

### 状态流

mock 模式：

```text
mock_state_service.tick()
-> state_store
-> REST / WS / Dashboard
```

real 模式：

```text
NUC
-> POST /api/internal/nuc/state
-> nuc_adapter
-> state_store
-> REST / WS / Dashboard
```

### 命令流

mock 模式：

```text
Frontend
-> /api/mission/*
-> mission_gateway
-> mock_state_service
-> state_store
-> REST / WS / Dashboard
```

real 模式：

```text
Frontend
-> /api/mission/*
-> mission_gateway
-> nuc_adapter.forward_mission_command()
-> NUC /api/internal/rk3588/mission
-> NUC 状态回传 /api/internal/nuc/state
-> state_store
-> REST / WS / Dashboard
```

### 常见故障点

1. `real` 模式下命令返回 `accepted=false`
   先检查 RK3588 是否用正确的 `NUC_BASE_URL` / `NUC_MISSION_PATH` 启动。

2. 页面一直显示“等待 NUC”
   说明已经切到 `real`，但 NUC 还没有向 `/api/internal/nuc/state` 发首包。

3. 页面显示 `nuc-state-timeout`
   说明 NUC 实时状态上送超过超时阈值未更新。

4. 页面显示 `nuc-bridge-unreachable`
   说明 RK3588 调 NUC mission 服务失败，优先查 NUC 监听地址、端口和 RK3588 启动配置。

5. RK3588 直连 NUC 失败
   先在 NUC 上确认 mission 服务是否真的监听在 `0.0.0.0:8090` 或 `192.168.10.3:8090`。

## 最小验证

### 后端自检

当前最小 `unittest` 已覆盖：

- `GET /health`
- 一个 mission endpoint：`go_to_waypoint`
- 模式切换：`POST /api/system/mode/switch`
- real 模式下命令转发与失败返回

运行方式：

```bash
cd backend
python3 -m unittest discover -s tests -v
```

### 手工检查

1. 健康检查：

```bash
curl http://127.0.0.1:8000/health
```

2. 模式切换：

```bash
curl -X POST http://127.0.0.1:8000/api/system/mode/switch \
  -H 'Content-Type: application/json' \
  -d '{"mode":"mock","source":"manual-check","requested_by":"operator"}'
```

```bash
curl -X POST http://127.0.0.1:8000/api/system/mode/switch \
  -H 'Content-Type: application/json' \
  -d '{"mode":"real","source":"manual-check","requested_by":"operator"}'
```

3. 一个 mission 命令：

```bash
curl -X POST http://127.0.0.1:8000/api/mission/go_to_waypoint \
  -H 'Content-Type: application/json' \
  -d '{"waypoint_id":"wp-demo-001","source":"manual-check","requested_by":"operator"}'
```

4. 前端观察点：

- 页面能显示 `MOCK / REAL`
- mock / real 切换后状态变化可见
- real 模式下能看到“等待 NUC / 在线 / 超时 / bridge 异常”等状态

## 当前交接状态

Phase 2 已达到可交接、可验收状态：

- 后端与前端可启动
- mock / real 两种模式都可发现、可测试
- NUC 状态上送与 mission bridge 已打通
- Dashboard 能观察到命令和状态反馈闭环
- 最小自检和手工复验路径已经写入本 README
