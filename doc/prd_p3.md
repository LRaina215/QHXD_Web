# phase3_prd.md

## 1. 文档目的

本文件用于定义 **Phase 3：三机真实闭环与 P0 收口阶段** 的产品目标、范围、功能列表与验收标准。

Phase 3 的核心任务不是新增炫技功能，而是把已经完成的 RK3588 Phase 2 中台能力，继续向下打通到 **NUC + RT-Thread**，形成真实的三机闭环：

**前端任务 -> RK3588 -> NUC -> RT-Thread -> NUC -> RK3588 -> Dashboard**

当前阶段严格遵循既定优先级：先完成 **P0 基本闭环**，再进入 P1/P2 的语音、图传、视觉异常检测与 LLM 增强。fileciteturn11file4

---

## 2. 阶段定位

### 2.1 当前阶段目标

在已完成 RK3588 Phase 2 的前提下，完成以下三项核心任务：

1. 将 **RT-Thread 底层真实状态** 纳入 NUC 上送给 RK3588 的真实状态包。
2. 将 **前端 mission 命令** 从 RK3588 经 NUC 继续打通到 RT-Thread 执行侧，形成真实闭环。
3. 完成 **基础巡检数据** 的真实接入与显示，使 P0 的“配送 + 基础巡检 + Web 可视化 + 基础异常提示”真正成立。fileciteturn11file1turn11file4

### 2.2 当前阶段不做的内容

以下能力不属于 Phase 3 范围：

- 语音任务入口真实接入
- OpenClaw / 大模型多轮对话
- 实时图传 / WebRTC / RTSP
- YOLO 异常检测联动与视觉增强
- 多终端复杂前端
- RK3588 直连 RT-Thread 的主控制链路
- 复杂云端系统与公网服务

这些能力仍属于 P1/P2 增强段，必须在 P0 收口后再推进。fileciteturn11file8

---

## 3. 用户与场景

### 3.1 目标用户

- 机器人开发成员
- 联调测试人员
- 比赛现场操作者

### 3.2 核心场景

1. 开发人员从前端下发一个配送任务，机器人真实执行。
2. NUC 读取 RT-Thread 实际底盘状态，并把任务进度与底层状态上送到 RK3588。
3. Dashboard 可以真实显示：任务状态、当前目标点、底层在线状态、电量、急停、基础巡检传感器数据。
4. 当底层掉线、急停、故障码变化时，前端能看到对应提示。

---

## 4. Phase 3 功能列表

### F1. 三机真实状态闭环

**说明**：
RK3588 页面展示的数据不再仅仅来自 NUC 高层状态，还要覆盖 RT-Thread 侧底层执行状态，由 NUC 统一采集、映射、上送。

**输入来源**：

- NUC 当前导航状态
- NUC 当前任务状态
- RT-Thread 当前底盘与设备状态

**输出目标**：

- `GET /api/state/latest`
- `GET /api/tasks/current`
- `WS /ws/state`
- Dashboard

**验收标准**：

- 页面可看到真实 `robot_pose`、`task_status`、`device_status`
- `device_status.online` 能反映真实底层在线状态
- `battery_percent`、`emergency_stop`、`fault_code` 不再长期停留在 mock 值
- NUC 一次真实状态变化后，RK3588 1 秒内可见页面刷新

### F1.1 Phase 3 最小字段来源冻结

为避免三机联调时重复争论字段归属，Phase 3 先冻结如下最小来源规则。

| RK3588 public field | Phase 3 主来源 | 说明 |
| --- | --- | --- |
| `robot_pose` | NUC 直接提供 | 来自 NUC 的 SLAM / 定位结果，不要求 RT-Thread 直接提供。 |
| `nav_status` | NUC 直接提供 | 来自 NUC 导航状态机与当前目标。 |
| `task_status` | NUC 直接提供 | 来自 NUC Mission Manager；底层执行结果通过 NUC 回写到该状态。 |
| `device_status.battery_percent` | RT-Thread 经 NUC 提供 | Phase 3 最小必接字段，RK3588 不新增平行字段。 |
| `device_status.emergency_stop` | RT-Thread 经 NUC 提供 | 反映真实底层急停状态。 |
| `device_status.fault_code` | RT-Thread 经 NUC 提供 | 反映底层故障码；没有故障时允许为 `null`。 |
| `device_status.online` | RT-Thread 经 NUC 提供 | 表示底层设备链路是否在线；不是浏览器在线状态。 |
| `env_sensor.temperature_c` | RT-Thread 经 NUC 提供，或 `null` 占位 | 没有真实传感器时允许为 `null`。 |
| `env_sensor.humidity_percent` | RT-Thread 经 NUC 提供，或 `null` 占位 | 没有真实传感器时允许为 `null`。 |
| `env_sensor.status` | NUC 归一化提供 | 真实传感器未就绪时，可上送 `offline` 或等价不可用状态。 |

冻结结论：

- RK3588 对外公开契约保持 Phase 2 结构不变
- Phase 3 只明确字段来源，不新增新的 `rtt_*` 或 `low_level_*` 平行字段
- RT-Thread 相关字段统一由 NUC 归一化后进入 `/api/internal/nuc/state`

---

### F2. 任务执行真实闭环

**说明**：
前端下发任务后，不能只在 RK3588 与 NUC 之间改状态，而要继续反映到底层执行链路中。

**Phase 3 必须闭环的命令**：

- `go_to_waypoint`
- `pause_task`
- `resume_task`
- `return_home`

**验收标准**：

- 前端点击命令后，RK3588 记录命令日志
- NUC Mission Manager 接收命令并修改任务状态
- NUC 下发到底层执行链路
- RT-Thread 状态变化可通过 NUC 上送反映到页面
- 至少 3 个命令形成“前端 -> 执行 -> 回显”闭环

---

### F3. 基础巡检真实接入

**说明**：
P0 中“基础巡检闭环”至少要在 Phase 3 实现最小落地，不要求复杂环境感知，但必须有真实数据来源。fileciteturn11file4

**优先级建议**：

1. 电量 / 急停 / fault_code
2. 温湿度或舱温（如果已有硬件）
3. 在线 / 离线 / 超时状态

**验收标准**：

- 页面可显示至少 2 类真实巡检/设备状态数据
- 这些数据由 NUC 周期上送，不依赖 mock
- 状态值变化时前端有可见变化
- 没有真实环境传感器时，可接受 `temperature_c: null`、`humidity_percent: null`，但在线/设备状态必须真实。fileciteturn11file17

---

### F4. 基础异常提示

**说明**：
P0 中要求至少具备基础异常处理能力，包括低电量、急停、失联与基本执行异常。fileciteturn11file4

**Phase 3 范围内必须覆盖的异常类型**：

- NUC bridge 不可达
- RT-Thread 底层离线
- 急停触发
- 电量低
- fault_code 非空
- real 状态超时

**验收标准**：

- 页面能看到异常文案或状态标识
- `GET /api/alerts` 能查询到最近异常
- 断开底层/停止上送时，系统能进入离线或超时态，而不是一直显示旧状态

---

## 5. 页面范围

Phase 3 不新增复杂页面，沿用当前 Dashboard 为主。

### 页面必须体现的内容

- 当前模式（mock / real）
- 当前任务
- 当前目标点
- 当前位姿
- 电量
- 急停状态
- 设备在线状态
- 最近告警
- 基础巡检数据

### 页面暂不要求

- 地图交互
- 路径轨迹回放
- 视频流
- 复杂告警筛选

---

## 6. 非功能要求

### 6.1 稳定性

- NUC -> RK3588 上送频率保持 1Hz~2Hz
- 上送失败不阻塞 NUC 主业务线程
- 底层短时掉线时页面能在合理时间内进入异常态，而不是卡死旧数据。fileciteturn11file17turn11file18

### 6.2 可调试性

- 必须保留 mock / real 模式切换
- 必须能通过 REST 接口检查当前状态
- 必须有关键日志，能定位失败点在 RK3588、NUC 还是 RT-Thread

### 6.3 最小实现原则

- 不引入复杂消息队列
- 不引入云端依赖
- 不重写现有导航主流程
- 不重写现有 RT-Thread 底层控制栈

---

## 7. Phase 3 完成标准

满足以下全部条件，视为 Phase 3 通过：

1. 前端能下发真实任务到 NUC
2. NUC 能将任务继续下发到底层执行链路
3. RT-Thread 的真实状态可被 NUC 采集并上送至 RK3588
4. RK3588 页面可显示真实任务进度与底层状态
5. 至少一个基础巡检数据源是真实接入
6. 异常 / 离线 / 急停 / fault_code 至少有 2 类能正确提示
7. mock / real 模式仍可切换

---

## 8. Phase 3 不通过标准

出现以下任一情况，建议判定当前阶段未通过：

- 前端命令只停留在 RK3588 / NUC 状态层，无法影响真实执行链路
- RT-Thread 状态未真正纳入 NUC -> RK3588 上送包
- 页面依然主要显示 mock 或静态旧值
- 底层掉线或急停时，页面无任何变化
- 异常提示无法定位问题来源

---

## 9. Phase 3 完成后进入的下一阶段

Phase 3 完成后，才进入 **Phase 4 / P1 增强能力阶段**，优先顺序为：

1. 语音任务入口
2. 环境传感器增强
3. 图传与路线同步
4. 视觉异常检测
5. 精准停靠优化

这与既定的 P0 -> P1 -> P2 路线保持一致。fileciteturn11file8
