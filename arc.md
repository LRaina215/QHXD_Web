# ARC：RK3588 车载交互与状态中台系统架构（第一阶段）

## 1. 文档目的

本文档用于定义 RK3588 中台在当前项目中的系统边界、模块职责、数据流向、目录落点和 Phase 1 当前实现状态，作为后续继续接入 NUC11 与 RT-Thread 的架构依据。

---

## 2. 整体系统背景

本项目采用三节点协同：

- **NUC11**：主智能计算平台，负责 SLAM、定位、路径规划、视觉推理、任务主状态机
- **RT-Thread 控制器**：底层实时执行与安全闭环，负责底盘控制、传感器采集、急停与故障保护
- **RK3588**：车载业务交互与边缘服务节点，负责任务入口、状态聚合、可视化、日志与后续扩展能力

第一阶段只解决 **RK3588 空壳中台** 的架构落地，不解决真实三机联调。

---

## 3. 第一阶段架构目标

1. 在 RK3588 上建立独立可运行的后端和前端框架
2. 形成统一状态模型与任务模型
3. 固定 RK3588 的输入、输出和职责边界
4. 允许使用模拟数据驱动完整页面
5. 为后续接入 NUC11 和 RT-Thread 预留适配层

---

## 4. 系统边界

### 4.1 RK3588 当前负责

- Web API 服务
- WebSocket 实时状态推送
- 状态快照缓存
- SQLite 本地持久化
- 任务命令入口
- 命令日志与告警日志
- Dashboard 可视化
- 面向 NUC11 / RT-Thread 的适配层预留

### 4.2 RK3588 当前不负责

- 主导航
- SLAM
- 主视觉推理
- 底盘控制
- 急停闭环
- 直接对电机下发控制命令

### 4.3 第一阶段与真实系统的关系

第一阶段允许使用模拟数据替代真实链路，但要求数据模型、API 和页面结构未来可平滑替换为真机数据。

---

## 5. 系统关系图

```text
Browser
   |
   v
RK3588
(状态中台 / 任务入口 / Dashboard / 日志)
   |
   +---- 未来业务状态桥接 ----> NUC11
   |
   +---- 未来底层状态接入 ----> RT-Thread
```

说明：

- 第一阶段优先构建 RK3588 自身中台
- 前端不直接连接 NUC11 或 RT-Thread
- 真实适配在后续阶段替换 mock 数据源

---

## 6. 核心模块划分

### 6.1 API 模块

职责：

- 提供查询接口
- 提供命令接口
- 输出统一响应结构

当前接口范围：

- `GET /health`
- `GET /api/state/latest`
- `GET /api/alerts`
- `GET /api/commands/logs`
- `GET /api/tasks/current`
- `POST /api/mission/go_to_waypoint`
- `POST /api/mission/start_patrol`
- `POST /api/mission/pause`
- `POST /api/mission/resume`
- `POST /api/mission/return_home`
- `WS /ws/state`

### 6.2 WebSocket 模块

职责：

- 向前端推送实时状态
- 统一输出状态快照
- 管理连接与断开

当前实现：

- 由后台 mock 循环每 1 秒生成新状态
- 将最新状态广播到所有已连接客户端

### 6.3 状态聚合模块

职责：

- 缓存最新状态
- 合并不同来源数据
- 输出当前状态快照

当前状态来源：

- 来自 mock 状态生成器的导航 / 任务 / 位姿 / 设备 / 传感器数据

后续状态来源：

- NUC11 业务与导航状态适配器
- RT-Thread 底层设备与传感器状态适配器

### 6.4 命令管理模块

职责：

- 接收前端命令
- 校验命令入参
- 写入命令日志
- 返回模拟处理结果

当前阶段仅负责：

- 入参接收
- mock 任务状态切换
- SQLite 命令日志记录

### 6.5 持久化模块

职责：

- 保存命令日志
- 保存最近告警
- 保存状态快照

数据库：SQLite

当前最小表结构：

- `command_logs`
- `alerts`
- `state_snapshots`

### 6.6 模拟数据模块

职责：

- 在无真实设备时定时生成状态数据
- 驱动 API、WebSocket 和 Dashboard
- 支撑前后端联调

当前实现：

- 每 1 秒更新一次位姿、任务状态、电量与环境传感器
- 周期性生成 mock 告警
- 同步写入状态快照

---

## 7. 数据流向

### 7.1 查询类数据流

前端查询 → API → 当前状态缓存 / SQLite → 返回结构化结果

### 7.2 推送类数据流

mock 状态循环 → 状态缓存刷新 → WebSocket 广播 → 前端实时更新

### 7.3 命令类数据流

前端发起命令 → API → mock 命令处理 → SQLite 写命令日志 → 返回受理结果

### 7.4 后续真实数据流

NUC11 / RT-Thread 适配层 → 状态聚合模块 → WebSocket / API → 前端

---

## 8. 当前统一数据模型

### 8.1 RobotPose

```json
{
  "x": 0.0,
  "y": 0.0,
  "yaw": 0.0,
  "frame_id": "map",
  "timestamp": "2026-04-11T18:00:00Z"
}
```

### 8.2 NavStatus

```json
{
  "mode": "mock",
  "state": "idle",
  "current_goal": null,
  "remaining_distance": null
}
```

### 8.3 TaskStatus

```json
{
  "task_id": "mock-task",
  "task_type": "placeholder",
  "state": "idle",
  "progress": 0,
  "source": "web"
}
```

### 8.4 DeviceStatus

```json
{
  "battery_percent": 100,
  "emergency_stop": false,
  "fault_code": null,
  "online": true
}
```

### 8.5 EnvSensor

```json
{
  "temperature_c": 25.0,
  "humidity_percent": 45.0,
  "status": "mock"
}
```

### 8.6 AlertEvent

```json
{
  "alert_id": "alert-mock-001",
  "level": "info",
  "message": "mock alert",
  "source": "system",
  "timestamp": "2026-04-11T18:00:00Z",
  "acknowledged": false
}
```

### 8.7 RobotState

```json
{
  "robot_pose": {},
  "nav_status": {},
  "task_status": {},
  "device_status": {},
  "env_sensor": {},
  "updated_at": "2026-04-11T18:00:00Z"
}
```

---

## 9. 当前 API 设计

### 9.1 健康检查

`GET /health`

返回：

```json
{
  "status": "ok"
}
```

### 9.2 最新状态

`GET /api/state/latest`

### 9.3 当前任务

`GET /api/tasks/current`

### 9.4 最近告警

`GET /api/alerts`

### 9.5 命令日志

`GET /api/commands/logs`

### 9.6 任务命令接口

- `POST /api/mission/go_to_waypoint`
- `POST /api/mission/start_patrol`
- `POST /api/mission/pause`
- `POST /api/mission/resume`
- `POST /api/mission/return_home`

命令类当前统一响应形态：

```json
{
  "success": true,
  "data": {
    "accepted": true,
    "command": "go_to_waypoint",
    "task_status": {},
    "received_at": "2026-04-11T18:00:00Z",
    "detail": "command accepted"
  }
}
```

---

## 10. 前端页面架构

### 10.1 当前验收页面

- 单页 Dashboard

### 10.2 页面布局

- 顶部状态区
- 状态卡片区
- 任务操作区
- 传感器区
- 告警区

### 10.3 页面职责

#### Dashboard

展示全局状态摘要、最近告警与基础 mission 操作。

独立 Mission / Devices / Logs 页面不在当前 Phase 1 验收范围内，作为后续补强项保留。

---

## 11. 技术栈

### 后端

- Python 3.10+
- FastAPI
- Pydantic
- WebSocket
- SQLite

### 前端

- Vue 3
- TypeScript
- Vite

---

## 12. 当前实现落点

当前 Phase 1 主要代码落点如下：

- 后端入口：`backend/app/main.py`
- 类型模型：`backend/app/schemas.py`
- mock 状态与 mission 处理：`backend/app/services/mock_state.py`
- SQLite 持久化：`backend/app/services/persistence.py`
- WebSocket 连接管理：`backend/app/services/ws_manager.py`
- 前端看板：`frontend/src/App.vue`

后续真实适配建议继续放在 `backend/app/services/` 下，以独立适配器文件接入 NUC11 与 RT-Thread。
