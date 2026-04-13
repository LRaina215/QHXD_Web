# arc_p2.md

## 1. 文档定位

本文件描述 **Phase 2：RK3588 ↔ NUC 真实桥接阶段** 的系统边界、通信方式、模块划分、数据流和目录更新策略。

Phase 1 已完成“空壳中台”建设；Phase 2 的重点是把 RK3588 从 mock 中台升级为**真实任务与状态中台**。该定位与前期已明确的三机协同方案一致：

- NUC11：主智能计算平台
- RT-Thread 控制器：实时执行与安全闭环
- RK3588：业务交互与边缘服务节点fileciteturn8file0

---

## 2. 系统边界

### 2.1 NUC11 负责

- SLAM
- 定位
- 全局 / 局部路径规划
- Nav2 或主导航栈
- 主任务状态机
- 主视觉感知与异常识别
- 高层决策与复杂数据处理

### 2.2 RT-Thread 控制器负责

- 电机控制
- 编码器 / IMU 采集
- 速度闭环
- 底盘执行
- 急停
- 失联保护
- 低层故障状态

### 2.3 RK3588 负责

- Web / App 后端
- 状态聚合
- 任务入口管理
- 任务桥接
- 日志与数据库
- WebSocket 实时推送
- mock / real 模式管理
- 后续语音、巡检、视频服务的承载基础

### 2.4 Phase 2 明确不做

- RK3588 主导航
- RK3588 主视觉推理
- RK3588 主控制链路
- RK3588 直接取代 NUC 与 RT-Thread 的控制分层

---

## 3. Phase 2 架构目标

将 Phase 1 的数据流：

```text
Mock generator -> RK3588 backend -> WebSocket -> Frontend
```

升级为：

```text
Web/App -> RK3588 -> NUC11 -> RT-Thread
                       |
                       v
                  Real state back to RK3588 -> Frontend
```

即：

- 外部任务先进入 RK3588
- RK3588 将结构化任务请求发送给 NUC
- NUC 再驱动主导航与 RT-Thread 执行
- NUC 的真实状态返回给 RK3588
- RK3588 汇总并对前端展示

这与既定主控制链路一致：**RT-Thread 不挂在 RK3588 后面当主控制从属节点，RT-Thread 的主控制对象仍是 NUC。**fileciteturn8file0

---

## 4. 通信与数据流

## 4.1 RK3588 ↔ NUC11

### 物理层

- 同一局域网 / 以太网

### 协议层

- HTTP：任务与查询接口
- WebSocket：实时状态推送（如需要，也可由 RK3588 主动拉取/接收）

### 当前实现选择

当前 Round 2 先采用 **NUC 主动通过 HTTP 向 RK3588 上送状态** 的方式进行联调，具体入口为：

- `POST /api/internal/nuc/state`

当前 Round 3 的任务桥接则采用 **RK3588 主动通过 HTTP 向 NUC 转发命令** 的方式进行联调，具体入口为：

- `POST /api/internal/rk3588/mission`

### Phase 2 承载内容

#### RK3588 -> NUC

- 任务命令
- 参数化命令请求
- 模式切换相关命令（如后续需要）

#### NUC -> RK3588

- robot_pose
- nav_status
- current_goal
- task_status
- detection_status（可先占位）
- 错误状态 / 连接状态

---

## 4.2 NUC11 ↔ RT-Thread

### 物理层

- USB CDC 虚拟串口（当前推荐）
- 或 CAN / UART（后续可升级）

### 协议层

- 自定义控制协议

### Phase 2 说明

本阶段不改动主控制链路，只要求 RK3588 通过 NUC 间接看到底层状态回传结果，不要求 RK3588 直接控制 RT-Thread。fileciteturn8file0

---

## 4.3 RK3588 ↔ Frontend

### 协议层

- HTTP：任务接口、查询接口
- WebSocket：实时状态推送

### 当前阶段不做

- WebRTC / RTSP 真实图传
- 跨公网复杂部署

---

## 5. 模块划分（Phase 2）

RK3588 后端建议拆分为以下模块：

### 5.1 `state_store`

职责：

- 统一缓存当前最新机器人状态
- 区分 mock / real 状态源
- 为 REST 和 WebSocket 提供统一读取入口

当前状态：

- 已实现最小共享状态存储
- `GET /api/state/latest` 与 `GET /api/tasks/current` 已从共享状态读取

### 5.2 `nuc_adapter`

职责：

- 负责与 NUC 的真实通信
- 接收真实状态
- 发送任务命令
- 处理超时、错误码、连接状态

当前状态：

- 已实现最小 `nuc_adapter`
- 已覆盖 **NUC -> RK3588 的真实状态输入**
- 已覆盖 **RK3588 -> NUC 的最小任务命令转发**

### 5.3 `mission_gateway`

职责：

- 接收前端命令
- 做参数校验
- 生成结构化任务请求
- 调用 `nuc_adapter` 转发给 NUC
- 记录命令日志

当前状态：

- 已实现最小 `mission_gateway`
- mock 模式继续走本地占位流程
- real 模式下通过 `nuc_adapter` 转发命令到 NUC
- NUC 返回的任务结果会写入 SQLite 并刷新共享状态

### 5.4 `mode_manager`

职责：

- 管理 mock / real 模式
- 决定当前状态数据源
- 支持联调回退

当前状态：

- 已实现最小 `mode_manager`
- 切到 `real` 时会先进入“等待 NUC 首包”状态
- real 模式下支持状态超时离线标记
- NUC 状态恢复或命令桥恢复后，会自动回到在线状态
- 模式切换、超时、恢复会写入轻量告警，便于前端观察

### 5.5 `websocket_push`

职责：

- 监听状态变化
- 向前端实时推送
- 处理在线 / 离线和重连

### 5.6 `log_service`

职责：

- 写入命令日志
- 写入状态异常日志
- 写入告警摘要

### 5.7 `frontend_dashboard`

职责：

- 展示状态、任务、告警
- 调用命令接口
- 显示 mock / real 模式

当前状态：

- 已显示当前系统模式
- 已支持从页面切换 mock / real
- 已显示 NUC bridge 在线、等待首包、超时、bridge 异常等状态
- WebSocket 断开后会自动重连，并在重连后主动拉取最新状态

---

## 6. 状态模型（Phase 2）

Phase 2 继续沿用 Phase 1 的统一公开状态契约，不重新发明字段，只做 real 数据适配。

### 6.1 `robot_pose`

- `x: float`
- `y: float`
- `yaw: float`
- `frame_id: str`
- `timestamp: str`

### 6.2 `nav_status`

- `mode: str`
- `state: str`
- `current_goal: str | null`
- `remaining_distance: float | null`

### 6.3 `task_status`

- `task_id: str`
- `task_type: str`
- `state: str`
- `progress: int`
- `source: str`

### 6.4 `device_status`

- `battery_percent: int | null`
- `emergency_stop: bool`
- `fault_code: str | null`
- `online: bool`

### 6.5 `env_sensor`

- `temperature_c: float | null`
- `humidity_percent: float | null`
- `status: "mock" | "nominal" | "warning" | "fault" | "offline"`

### 6.6 `alert_event`

- `alert_id: str`
- `level: "info" | "warning" | "error" | "critical"`
- `source: str`
- `message: str`
- `timestamp: str`
- `acknowledged: bool`

### 6.7 `system_mode`

- `mode: "mock" | "real"`
- `updated_at: str`

说明：

- `system_mode` 用于描述中台当前运行模式
- `nav_status.mode` 与 `system_mode.mode` 语义不同
- `nav_status.mode` 只表示导航工作模式，如 `auto` / `manual`

---

## 6.8 当前冻结请求 / 响应契约

### 读取类接口

- `GET /api/state/latest -> StateLatestResponse`
- `GET /api/alerts -> AlertsResponse`
- `GET /api/tasks/current -> CurrentTaskResponse`

### 命令类接口

- `POST /api/mission/go_to_waypoint -> GoToWaypointRequest / MissionActionResponse`
- `POST /api/mission/start_patrol -> StartPatrolRequest / MissionActionResponse`
- `POST /api/mission/pause -> PauseMissionRequest / MissionActionResponse`
- `POST /api/mission/resume -> ResumeMissionRequest / MissionActionResponse`
- `POST /api/mission/return_home -> ReturnHomeRequest / MissionActionResponse`

### 模式切换接口

- `POST /api/system/mode/switch -> ModeSwitchRequest / ModeSwitchResponse`

---

## 7. 目录结构建议（Phase 2）

```text
rk_platform/
├─ backend/
│  ├─ app/
│  │  ├─ api/
│  │  ├─ schemas/
│  │  ├─ services/
│  │  │  ├─ state_store.py
│  │  │  ├─ mode_manager.py
│  │  │  ├─ mission_gateway.py
│  │  │  ├─ nuc_adapter.py
│  │  │  └─ log_service.py
│  │  ├─ core/
│  │  └─ main.py
│  ├─ tests/
│  └─ requirements.txt
├─ frontend/
│  ├─ src/
│  │  ├─ views/
│  │  ├─ components/
│  │  ├─ stores/
│  │  ├─ api/
│  │  └─ types/
│  └─ package.json
├─ doc/
│  ├─ prd_p1.md
│  ├─ arc_p1.md
│  ├─ project_p1.md
│  ├─ prd_p2.md
│  ├─ arc_p2.md
│  └─ project_p2.md
└─ README.md
```

---

## 8. Phase 2 数据流图

### 8.1 命令流

```text
Frontend -> RK3588 Mission API -> mission_gateway -> nuc_adapter -> NUC Mission Manager
```

### 8.2 状态流

```text
NUC State -> nuc_adapter -> state_store -> websocket_push -> Frontend
```

### 8.3 日志流

```text
Mission/API/State events -> log_service -> SQLite
```

### 8.4 模式流

```text
Mode setting -> mode_manager -> choose mock source or real NUC source
```

---

## 9. 联调策略

### 9.1 原则

- 先锁数据契约，再做真实接入
- 保留 mock，避免一次性切死退路
- 先桥接状态，再桥接命令
- 每打通一条链路就单独验收

### 9.2 联调顺序

1. 冻结字段与 API
2. 先接收 NUC 真实状态
3. 再打通任务命令桥
4. 再补状态反馈闭环
5. 最后做错误处理与调试页

---

## 10. 风险点与规避措施

### 风险 R1：NUC 字段与 RK3588 契约不一致

**措施**：在 `nuc_adapter` 中做适配，不直接污染前端公开状态模型

### 风险 R2：真实联调导致前端无法继续开发

**措施**：保留 mock / real 双模式

### 风险 R3：命令链路打通但状态回传不完整

**措施**：将“状态—命令—反馈闭环”设为本阶段硬验收条件

### 风险 R4：RK3588 职责越界，开始承接导航或底层控制

**措施**：严格遵守三机边界，不将 RK3588 引入主控制闭环fileciteturn8file0

---

## 11. Phase 2 完成判据

架构层面判定 Phase 2 完成，需要满足：

- 有真实 NUC 适配器
- 前后端使用真实状态链路
- 任务桥接真实有效
- mock / real 切换仍可用
- 文档与代码一致
