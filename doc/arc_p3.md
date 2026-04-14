# arc_p3.md

## 1. 文档目的

本文件用于定义 **Phase 3：三机真实闭环与 P0 收口阶段** 的系统边界、通信拓扑、数据流向、模块划分与开发约束。

Phase 3 的本质，是把已完成的 RK3588 Phase 2 中台能力，从“NUC 真实桥接”继续推进到“NUC + RT-Thread + RK3588 三机闭环”。

---

## 2. 总体分层与职责边界

### 2.1 NUC11：主智能计算平台

负责：

- SLAM / 定位 / 导航主链路
- 全局/局部规划
- Mission Manager
- 主视觉感知与上层任务逻辑
- 向下与 RT-Thread 通信
- 向上向 RK3588 上送整机状态

### 2.2 RT-Thread：实时执行与安全闭环

负责：

- 电机控制
- 编码器 / IMU / 低层状态采集
- 速度闭环
- 底盘执行
- 急停
- 失联保护
- 低层 fault_code 与底层设备状态

### 2.3 RK3588：业务交互与边缘服务节点

负责：

- Dashboard / Web 服务
- 状态聚合与展示
- 任务入口
- mission bridge 前端接口
- real / mock 模式管理
- 基础日志与告警展示

该分层保持不变，符合之前确定的三机协同关系：NUC 管“会不会做”，RK3588 管“怎么用、怎么展示、怎么接入任务”，RT-Thread 管“怎么稳稳执行”。fileciteturn11file1turn11file2

---

## 3. Phase 3 通信拓扑

### 3.1 主通信拓扑

```text
Frontend / Browser
        |
        | HTTP / WebSocket
        v
      RK3588
        |
        | HTTP (业务桥接 / 状态上送)
        v
       NUC11
        |
        | USB CDC / UART / CAN（按你们当前底层方案）
        v
   RT-Thread Controller
```

### 3.2 通信原则

- **RK3588 不直接作为 RT-Thread 主控制上位机**
- **RT-Thread 只认 NUC 的主执行控制链路**
- **NUC 对上说业务语言（HTTP/JSON），对下说控制语言（串口/CAN/自定义协议）**

这也是你们前面已经确定的总方向。fileciteturn11file1turn11file13

---

## 4. Phase 3 数据流

### 4.1 命令流

```text
Frontend
-> RK3588 /api/mission/*
-> mission_gateway
-> NUC mission endpoint
-> NUC Mission Manager
-> NUC -> RT-Thread execution command
-> RT-Thread executes / changes low-level state
```

### 4.2 状态流

```text
RT-Thread low-level state
-> NUC state_collector / mapper
-> POST /api/internal/nuc/state to RK3588
-> state_store
-> REST / WS / Dashboard
```

### 4.2.1 Phase 3 状态映射冻结表

| RK3588 契约字段 | 来源节点 | NUC 内部模块 | 映射规则 |
| --- | --- | --- | --- |
| `robot_pose.*` | NUC | `state_mapper` | 直接映射 NUC 的定位 / 位姿输出。 |
| `nav_status.mode/state/current_goal/remaining_distance` | NUC | `state_mapper` | 直接映射 NUC 导航状态。 |
| `task_status.*` | NUC | `state_mapper` | 直接映射 NUC Mission Manager 状态。 |
| `device_status.battery_percent` | RT-Thread | `rtt_state_collector -> state_mapper` | 由 NUC 从底层读取后归一化为百分比。 |
| `device_status.emergency_stop` | RT-Thread | `rtt_state_collector -> state_mapper` | 由底层急停量或安全状态映射为布尔值。 |
| `device_status.fault_code` | RT-Thread | `rtt_state_collector -> state_mapper` | 由底层 fault 或错误寄存器归一化为字符串或 `null`。 |
| `device_status.online` | RT-Thread | `rtt_state_collector -> state_mapper` | 表示底层设备链路是否在线，不等同于 NUC 或 Web 在线。 |
| `env_sensor.temperature_c` | RT-Thread 或无 | `rtt_state_collector -> state_mapper` | 有真实传感器则填值，无则填 `null`。 |
| `env_sensor.humidity_percent` | RT-Thread 或无 | `rtt_state_collector -> state_mapper` | 有真实传感器则填值，无则填 `null`。 |
| `env_sensor.status` | NUC 归一化 | `state_mapper` | 真实传感器未就绪时，统一映射为 `offline`。 |
| `alerts[*]` 中 RT-Thread 相关告警 | RT-Thread 经 NUC | `state_mapper` | 建议使用 `rtt-device` / `rtt-safety` 作为来源。 |

### 4.3 异常流

```text
RT-Thread fault / estop / offline
-> NUC normalized state / alerts
-> RK3588 alerts + device_status
-> Dashboard / GET /api/alerts
```

---

## 5. Phase 3 需要落地的模块

### 5.1 NUC 侧新增/增强模块

#### A. `rtt_state_collector`

职责：

- 从 RT-Thread 通信链路读取底层状态
- 提供标准化底层状态对象给 NUC 内部使用

最小字段：

- velocity
- battery_percent
- emergency_stop
- fault_code
- online
- env_sensor（如有）

#### B. `state_mapper`

职责：

- 将 NUC 高层状态 + RT-Thread 底层状态合并成统一状态包
- 映射到 RK3588 Phase 2 已冻结契约字段

最小映射约束：

- `robot_pose`、`nav_status`、`task_status` 优先保留 NUC 语义
- `device_status` 优先承载 RT-Thread 真实底层状态
- `env_sensor` 在没有真实传感器前允许保留空值占位，但 `status` 必须能表达不可用
- 不在 RK3588 公开契约中新增 `rtt_*` 平行字段，避免前端和接口再次分叉

#### C. `rk3588_sender`

职责：

- 周期性 HTTP POST 到 RK3588
- 简单重试
- 打日志

这与当前 NUC 状态上送设计保持一致，只是 Phase 3 新增 RT-Thread 真实状态来源。fileciteturn11file10turn11file17

#### D. `mission_execution_bridge`

职责：

- 接收 NUC Mission Manager 的任务状态变化
- 将任务进一步映射到底层执行链路
- 记录执行开始、暂停、恢复、返航等状态

---

### 5.2 RK3588 侧无需新增大架构，只增强现有中台

RK3588 Phase 2 已有：

- `nuc_adapter.py`
- `state_store.py`
- `mission_gateway.py`
- `mode_manager.py`

Phase 3 主要做增强而不是重构：

#### A. 状态展示增强

- 页面增加更明确的 RT-Thread / 底层设备状态展示
- 让 `device_status` 不再只是 NUC 层占位

#### B. 告警展示增强

- 增加底层异常、超时、离线、急停文案

#### C. real/mock 保持双模式

- 保留当前 mock / real 切换
- 允许联调失败时快速切回 mock 排障

---

## 6. Phase 3 状态包要求

Phase 2 已冻结的最小状态契约仍然有效：

- `robot_pose`
- `nav_status`
- `task_status`
- `device_status`
- `env_sensor`
- `alerts`
- `updated_at`

### Phase 3 额外要求

#### `device_status`

必须尽可能来自真实底层链路：

- `battery_percent`
- `emergency_stop`
- `fault_code`
- `online`

#### `env_sensor`

优先由真实底层或真实传感器提供；若暂时没有，可保留：

- `temperature_c: null`
- `humidity_percent: null`
- `status: "offline"`

补充约定：

- `temperature_c` / `humidity_percent` 为 `null` 时不表示协议错误，只表示传感器暂未接入
- 此时前端仍应依赖 `status` 判断“当前无真实环境传感器”

#### `alerts`

应至少支持以下来源：

- `nuc-nav`
- `rtt-device`
- `rtt-safety`
- `integration`

---

## 7. Phase 3 非功能约束

### 7.1 稳定性优先

- 不追求高频推送
- NUC -> RK3588 保持 1Hz~2Hz
- 错误时优先可见、可查，不追求复杂高可用机制

### 7.2 最小改动原则

- 不重写导航主流程
- 不重写 RT-Thread 底层控制框架
- 不让 RK3588 越界接管底层控制

### 7.3 可回退原则

- 保留 mock 模式
- 任何真实联调失败都能退回 mock 继续开发

这也符合你们的 Vibe Coding 纪律：小步迭代、边界清晰、重大改动必须记录。fileciteturn11file11

---

## 8. 目录与模块建议

### RK3588 侧

沿用现有目录，不做大改：

```text
backend/app/services/
  - nuc_adapter.py
  - state_store.py
  - mission_gateway.py
  - mode_manager.py
  - alert_service.py        # 可增
  - integration_state.py    # 可增
```

### NUC 侧建议新增模块

```text
nuc/
  - state_collector/
      - nav_state_collector.py
      - rtt_state_collector.py
  - mapper/
      - rk_state_mapper.py
  - sender/
      - rk3588_sender.py
  - mission/
      - mission_execution_bridge.py
      - mission_receiver.py
```

---

## 9. Phase 3 联调边界

### 9.1 当前阶段必须联调的链路

- RK3588 -> NUC mission command
- NUC -> RT-Thread execute path
- RT-Thread -> NUC low-level status
- NUC -> RK3588 real state update
- RK3588 -> Dashboard render

### 9.2 当前阶段可延后联调的链路

- 语音任务入口
- 视频流
- 视觉异常检测
- 高级巡检传感器
- LLM 总结

---

## 10. Phase 3 验收架构判断标准

### 通过

- 三机职责边界没有被破坏
- 前端命令真实影响到底层
- 底层真实状态能回到页面
- mock / real 都还能用

### 不通过

- RK3588 直接插手 RT-Thread 主控制
- NUC 不再是主智能节点
- 页面状态与真实底层脱节
- 为了联调牺牲了原有主架构清晰性
