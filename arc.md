# ARC：RK3588 车载交互与状态中台系统架构（第一阶段）

## 1. 文档目的

本文档用于定义 RK3588 中台在当前项目中的系统边界、模块分层、数据流向、目录结构、技术栈和变更约束，为后续 AI 辅助开发提供统一架构上下文。Vibe Coding 工作流要求在开发前先明确系统边界、技术栈、量化架构草案，并建立可持续更新的架构文档。fileciteturn3file0

---

## 2. 整体系统背景

本项目最终采用三节点协同：

- **NUC11**：主智能计算平台，负责 SLAM、定位、路径规划、视觉推理、任务主状态机。
- **RT-Thread 控制器**：底层实时执行与安全闭环，负责底盘控制、传感器采集、急停与故障保护。
- **RK3588**：车载业务交互与边缘服务节点，负责任务入口、状态聚合、可视化、日志与巡检数据服务。

赛题指南中，Linux 侧承担复杂智能算法、人机交互与界面扩展，RT-Thread 侧承担多传感器融合定位、电机 PID、姿态稳定与紧急停障等高实时任务。fileciteturn0file0

---

## 3. 第一阶段架构目标

第一阶段只解决 **RK3588 空壳中台的架构落地**，不解决真实三机联调。架构目标包括：

1. 在 RK3588 上建立独立可运行的后端和前端框架。
2. 形成统一状态模型与任务模型。
3. 固定 RK3588 的输入、输出和职责边界。
4. 允许使用模拟数据驱动完整页面。
5. 为后续接入 NUC11 和 RT-Thread 预留适配层。

---

## 4. 系统边界

### 4.1 RK3588 负责的内容

- Web API 服务
- WebSocket 实时状态推送
- 状态快照缓存
- SQLite 本地持久化
- 任务命令入口
- 命令日志与告警日志
- 环境传感器数据服务占位
- 后续语音交互模块挂载位置

### 4.2 RK3588 不负责的内容

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
Web / Browser
      |
      v
   RK3588
(状态中台 / 任务入口 / 数据服务)
      |
      +------HTTP / WebSocket------> NUC11
      |
      +------状态接入占位----------> RT-Thread
```

说明：

- 第一阶段优先构建 RK3588 自身的中台框架。
- 与 NUC11、RT-Thread 的真实通信在后续阶段替换模拟数据。
- 不采用“前端直接连接 NUC 或 RT-Thread”的结构。

---

## 6. 核心模块划分

### 6.1 API 模块

职责：

- 提供查询接口
- 提供命令接口
- 输出统一响应格式

第一阶段接口范围：

- `GET /health`
- `GET /api/state/latest`
- `GET /api/alerts`
- `GET /api/tasks/current`
- `POST /api/mission/go_to_waypoint`
- `POST /api/mission/start_patrol`
- `POST /api/mission/pause`
- `POST /api/mission/resume`
- `POST /api/mission/return_home`

---

### 6.2 WebSocket 模块

职责：

- 向前端推送实时状态
- 统一输出状态快照
- 支持重连与断开标识

---

### 6.3 状态聚合模块

职责：

- 缓存最新状态
- 合并不同来源数据
- 提供当前状态快照

状态来源分为：

- 来自 NUC11 的业务与导航状态（当前阶段先模拟）
- 来自 RT-Thread 的底层状态与传感器状态（当前阶段先模拟）

---

### 6.4 命令管理模块

职责：

- 接收前端命令
- 校验命令合法性
- 写入命令日志
- 向后续业务层转发命令

当前阶段仅负责：

- 入参校验
- 命令记录
- 模拟反馈

---

### 6.5 持久化模块

职责：

- 保存命令日志
- 保存最近告警
- 保存必要状态摘要

数据库：SQLite

---

### 6.6 模拟数据模块

职责：

- 在无真实设备时定时生成状态数据
- 驱动页面和 WebSocket
- 支撑前后端联调

该模块是第一阶段的关键模块，因为第一阶段必须独立于真实设备联调推进。fileciteturn3file0

---

## 7. 数据流向

### 7.1 查询类数据流

前端发起查询 → API 模块 → 状态聚合模块 / SQLite → 返回结构化结果

### 7.2 推送类数据流

模拟数据模块更新状态 → 状态聚合模块刷新快照 → WebSocket 模块推送给前端

### 7.3 命令类数据流

前端发起命令 → API 模块 → 命令管理模块校验 → SQLite 写命令日志 → 返回命令受理结果

### 7.4 后续真实数据流（预留）

NUC11 / RT-Thread 适配层 → 状态聚合模块 → WebSocket / API → 前端

---

## 8. 统一数据模型草案

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

字段说明：

- `x`：机器人在地图坐标系中的横坐标，单位 m
- `y`：机器人在地图坐标系中的纵坐标，单位 m
- `yaw`：朝向角，单位 rad
- `frame_id`：坐标系名称
- `timestamp`：更新时间

---

### 8.2 NavStatus

```json
{
  "mode": "auto",
  "state": "idle",
  "current_goal": null,
  "remaining_distance": null
}
```

---

### 8.3 TaskStatus

```json
{
  "task_id": "task_001",
  "task_type": "deliver",
  "state": "pending",
  "progress": 0,
  "source": "web"
}
```

---

### 8.4 DeviceStatus

```json
{
  "battery_percent": 100,
  "emergency_stop": false,
  "fault_code": null,
  "online": true
}
```

---

### 8.5 EnvSensor

```json
{
  "temperature": null,
  "humidity": null,
  "smoke": null
}
```

---

### 8.6 AlertEvent

```json
{
  "level": "info",
  "source": "system",
  "message": "mock alert",
  "timestamp": "2026-04-11T18:00:00Z"
}
```

---

### 8.7 StateSnapshot（推荐给前端的统一快照）

```json
{
  "robot_pose": {},
  "nav_status": {},
  "task_status": {},
  "device_status": {},
  "env_sensor": {},
  "alerts": []
}
```

---

## 9. API 设计草案

### 9.1 健康检查

`GET /health`

返回：

```json
{
  "status": "ok",
  "service": "rk-backend"
}
```

### 9.2 最新状态

`GET /api/state/latest`

返回统一 `StateSnapshot`

### 9.3 当前任务

`GET /api/tasks/current`

### 9.4 最近告警

`GET /api/alerts`

### 9.5 任务命令接口

- `POST /api/mission/go_to_waypoint`
- `POST /api/mission/start_patrol`
- `POST /api/mission/pause`
- `POST /api/mission/resume`
- `POST /api/mission/return_home`

命令类统一响应：

```json
{
  "success": true,
  "message": "command accepted",
  "command_id": "cmd_001"
}
```

错误统一响应：

```json
{
  "success": false,
  "message": "invalid waypoint"
}
```

---

## 10. 前端页面架构

### 10.1 页面列表

- Dashboard
- Mission
- Devices
- Logs

### 10.2 页面布局

- 左侧导航
- 顶部状态栏（可选）
- 主内容区域

### 10.3 页面职责

#### Dashboard

展示系统全局状态摘要

#### Mission

提供任务命令操作

#### Devices

展示设备节点状态

#### Logs

展示告警和命令日志

---

## 11. 技术栈选型

Vibe Coding 强调：技术选型必须选择“可验证、资料多、工具链成熟”的技术，而不是盲目追新。fileciteturn3file0

### 后端

- Python 3.11+
- FastAPI
- WebSocket
- Pydantic
- SQLite
- SQLAlchemy（可选）

### 前端

- Vue 3
- TypeScript
- Vite
- 可选 Element Plus

### 原因

- FastAPI 文档完整，适合接口与 WebSocket
- Vue3 + TS 工程化程度高，资料丰富
- SQLite 适合第一阶段轻量持久化
- 组合成熟，便于代码审查和自动化测试

---

## 12. 目录结构草案

```text
rk_platform/
├─ backend/
│  ├─ app/
│  │  ├─ api/
│  │  ├─ core/
│  │  ├─ models/
│  │  ├─ schemas/
│  │  ├─ services/
│  │  └─ main.py
│  ├─ tests/
│  └─ requirements.txt
├─ frontend/
│  ├─ src/
│  │  ├─ api/
│  │  ├─ views/
│  │  ├─ components/
│  │  ├─ stores/
│  │  ├─ types/
│  │  └─ main.ts
│  └─ package.json
├─ docs/
│  ├─ prd.md
│  ├─ arc.md
│  └─ project.md
├─ reference/
├─ scripts/
├─ .env.example
└─ README.md
```

该目录结构符合 Vibe Coding 中“主动规划文件结构、禁止 AI 将所有代码堆在单一文件”的要求。fileciteturn3file0

---

## 13. 非功能需求

### 13.1 使用环境

- 局域网内开发与演示
- 非公网部署
- 非生产商用

### 13.2 性能目标

- 页面状态更新延迟 ≤ 1 秒
- 模拟数据驱动下页面连续运行 30 分钟无崩溃
- WebSocket 支持基础重连

### 13.3 安全要求

- 禁止硬编码敏感配置
- 后端配置使用环境变量
- 不信任前端输入
- 第一阶段不开放公网

---

## 14. 变更纪律

根据 Vibe Coding 工作流，架构草案允许在开发中迭代，但每次架构变更必须记录原因。fileciteturn3file0

当前变更纪律：

- 重大目录变更：记录到 `project.md`
- 数据模型变更：同步更新 `prd.md` 与 `arc.md`
- API 变更：补充变更原因与兼容性说明

---

## 15. 第一阶段完成定义

当满足以下条件时，第一阶段架构准备完成：

1. RK3588 中台职责边界清晰，不与 NUC11 和 RT-Thread 职责重叠。
2. 统一数据模型完成并写入文档。
3. API 与 WebSocket 草案完成。
4. 目录结构与技术栈固定。
5. 页面架构固定。
6. 文档与代码仓库初始化完成。fileciteturn3file0