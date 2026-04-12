# RK3588 Middleware Phase 1

## 项目目的

本项目是 RK3588 车载交互与状态中台的第一阶段空壳工程。
当前目标是提供一个可运行、可联调、可 review 的最小前后端骨架，用 mock 数据打通：

- 后端 API
- WebSocket 状态推送
- 前端 Dashboard 展示
- 基础 mission 命令入口
- 本地 SQLite 持久化

第一阶段不接入真实 NUC、真实 RT-Thread、真实语音或真实视频。

## 当前 Phase 1 范围

- FastAPI 后端骨架
- Vue 3 + TypeScript + Vite 前端骨架
- `GET /health`
- 状态查询、告警查询、当前任务查询
- mission mock 接口：
  - `POST /api/mission/go_to_waypoint`
  - `POST /api/mission/start_patrol`
  - `POST /api/mission/pause`
  - `POST /api/mission/resume`
  - `POST /api/mission/return_home`
- `WS /ws/state` mock 实时状态流
- SQLite 本地持久化：
  - command logs
  - recent alerts
  - state snapshots

## 运行方式

### 后端

```bash
cd backend
python3 -m pip install -r requirements.txt
python3 -m uvicorn app.main:app --reload --host 0.0.0.0 --port 8000
```

启动后可验证：

```bash
curl http://127.0.0.1:8000/health
curl http://127.0.0.1:8000/api/state/latest
curl http://127.0.0.1:8000/api/alerts
curl http://127.0.0.1:8000/api/tasks/current
curl http://127.0.0.1:8000/api/commands/logs
```

数据库文件默认生成在：

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

说明：

- 开发态通过 `vite` 代理把 `/api` 和 `/ws` 转发到 `http://127.0.0.1:8000`
- 启动前端前，请先启动后端

## 开发说明

### Mock 数据来源

当前所有 mock 状态都来自：

- [backend/app/services/mock_state.py](/home/robomaster/QHXD/backend/app/services/mock_state.py)

该文件负责：

- 定时生成位姿、任务、电量、环境传感器等 mock 状态
- 生成最近告警
- 生成 mission mock 处理结果
- 将状态和日志写入 SQLite

### 未来 NUC 适配器接入点

当前 `mock_state.py` 既扮演状态源，也扮演简化的状态聚合器。
后续接入真实 NUC 时，建议在 `backend/app/services/` 下新增独立适配器，例如：

- `backend/app/services/nuc_adapter.py`

接入位置：

- 替换或扩展 `mock_state.py` 中 `nav_status`、`task_status`、`robot_pose` 的生成逻辑
- 保持对外 API 和 WebSocket 输出结构不变

### 未来 RT-Thread 适配器接入点

后续接入真实 RT-Thread 时，建议在 `backend/app/services/` 下新增独立适配器，例如：

- `backend/app/services/rtthread_adapter.py`

接入位置：

- 替换或扩展 `mock_state.py` 中 `device_status`、`env_sensor`、急停和底层状态生成逻辑
- 保持对外 API 和 WebSocket 输出结构不变

## 最小验证

### 运行检查

后端启动后：

```bash
curl http://127.0.0.1:8000/health
```

前端启动后：

- 页面应显示在线状态、当前任务、当前目标、电量、急停、环境传感器和最近告警
- 点击 mission 按钮后，状态卡片和提示文案会更新

### 后端自检

项目内提供了一个最小 `unittest` 检查，覆盖：

- `health` endpoint
- `go_to_waypoint` mission endpoint
- mock state tick 更新

运行方式：

```bash
cd backend
python3 -m unittest discover -s tests -v
```

## 已验证通过

本仓库当前已实际验证通过：

- 后端可启动
- `GET /health` 返回成功
- 前端可启动
- Dashboard 可渲染当前状态
- WebSocket 会推送变化中的 mock 状态
- mission 按钮会调用后端接口并更新页面
- SQLite 数据库文件可创建，命令日志和告警可持久化
