# project_p2.md

## 1. 当前阶段定位

### 阶段名称

**Phase 2：RK3588 ↔ NUC 真实桥接阶段**

### 阶段说明

Phase 1 已完成“空壳中台”建设并通过验收。当前进入 Phase 2，目标是把 RK3588 从 mock 中台推进为**真实接入 NUC 的任务与状态中台**。

这一阶段仍然遵循原定推进节奏：

- 先保证基础闭环
- 再做增强功能
- 暂不进入语音、图传、视觉异常联动等高阶特性

这与原计划中的 P0 -> P1 -> P2 分层一致：当前仍处于 P0 的延伸与收口阶段。fileciteturn7file0turn8file0

---

## 2. Phase 1 回顾

### 已完成内容

- RK3588 后端服务骨架
- FastAPI 健康检查与基础 REST 接口
- WebSocket 状态推送占位
- SQLite 本地持久化
- Vue Dashboard 基础页面
- mock 状态链路与页面联动
- 第一阶段验收完成

### 已确认的系统定位

- NUC11：主智能计算平台
- RT-Thread：实时执行与安全闭环
- RK3588：业务交互与边缘服务节点fileciteturn8file0

---

## 3. Phase 2 阶段目标

### 总目标

完成 RK3588 ↔ NUC 的真实状态与任务桥接，形成：

**前端任务入口 -> RK3588 中台 -> NUC 任务管理 -> 状态反馈 -> RK3588 页面更新**

### 细化目标

1. 冻结 NUC ↔ RK3588 数据契约
2. 实现 NUC 状态接入适配器
3. 实现任务命令桥接
4. 实现 mock / real 模式切换
5. 实现真实状态—命令—反馈闭环
6. 补齐日志与联调排障能力

---

## 4. 本阶段不做的事

- 不做真实语音交互接入
- 不做 OpenClaw
- 不做真实视频图传
- 不做新传感器硬件接入
- 不做主视觉检测桥接
- 不让 RK3588 进入主导航或主控制闭环

这些内容留到后续 P1 / P2 阶段。fileciteturn8file0turn7file0

---

## 5. 阶段任务规划

本阶段拆分为 5 个轮次，每轮都应遵守：

- 小步迭代
- 仅改与当前任务直接相关的文件
- 每轮完成后立即本地验证
- 每轮完成后立即 Git commit

这与 Vibe Coding 工作流中的“小步切片、立即验证、立即提交”一致。fileciteturn3file0

---

## 6. 分轮次任务计划

## Round 1：冻结字段与接口契约

### 目标

把 Phase 1 的模型和接口从“能用”变成“和 NUC 对接可执行”。

### 任务

- 对照 NUC 当前可输出字段，冻结以下状态字段：
  - `robot_pose`
  - `nav_status`
  - `task_status`
  - `device_status`
  - `env_sensor`
  - `alert_event`
  - `system_mode`
- 冻结以下命令接口：
  - `go_to_waypoint`
  - `start_patrol`
  - `pause`
  - `resume`
  - `return_home`
- 新增并冻结模式切换接口：
  - `POST /api/system/mode/switch`
- 明确字段类型、单位、枚举值、空值语义
- 明确错误返回格式和连接异常表示方式

### 交付物

- 字段对照表
- 命令对照表
- API 契约更新

### 验收

- 文档和代码中的字段定义一致
- NUC 开发侧可以按该契约接入

### Codex Prompt（Round 1）

```text
Read AGENT.md and then read:
- doc/prd_p1.md
- doc/arc_p1.md
- doc/project_p1.md
- doc/prd_p2.md
- doc/arc_p2.md
- doc/project_p2.md

Task:
Freeze the Phase 2 data contracts and API contracts for RK3588 <-> NUC integration.

Requirements:
1. Review existing backend schemas and mission endpoints
2. Refine and freeze the typed schemas for:
   - robot_pose
   - nav_status
   - task_status
   - device_status
   - env_sensor
   - alert_event
   - system_mode
3. Make request/response contracts explicit for:
   - GET /api/state/latest
   - GET /api/alerts
   - GET /api/tasks/current
   - POST /api/mission/go_to_waypoint
   - POST /api/mission/start_patrol
   - POST /api/mission/pause
   - POST /api/mission/resume
   - POST /api/mission/return_home
   - POST /api/system/mode/switch
4. Do not implement real communication yet
5. Update docs only where needed for consistency

Constraints:
- Keep changes small and reviewable
- No unrelated refactors
- Do not redesign frontend

Validation:
- backend starts
- schemas are imported correctly
- endpoints still return valid JSON

Only modify files required for this contract-freezing task.
At the end, summarize changed files and the frozen contracts.
```

---

## Round 2：实现 NUC 状态接入适配器

### 目标

让 RK3588 从 NUC 接收真实状态，替换纯 mock 数据源。

### 任务

- 新增 `nuc_adapter`
- 接收 NUC 状态
- 写入 `state_store`
- 通过 WebSocket 推送给前端
- 页面展示真实状态

### 交付物

- NUC 适配器骨架
- real 状态接入链路
- 前端显示真实状态的基础能力

### 验收

- RK3588 能接收到 NUC 的真实状态
- 前端能看到真实状态更新
- NUC 断开时页面能提示离线

### Codex Prompt（Round 2）

```text
Continue in the same thread.

Task:
Implement the Phase 2 NUC real-state adapter for RK3588.

Requirements:
1. Add a nuc_adapter service in backend
2. Support receiving real state updates from NUC through the chosen Phase 2 integration method
3. Feed real state into the shared state_store
4. Keep mock mode intact
5. Expose current mode and current latest state through existing APIs
6. Push real state to websocket clients
7. Do not implement RT-Thread direct communication

Constraints:
- Only touch files required for backend state integration and the smallest necessary frontend updates
- No broad refactors
- Preserve mock mode

Validation:
- backend starts
- mock mode still works
- real mode accepts real state input from NUC
- websocket reflects real state changes

At the end, summarize state flow, changed files, and validation steps.
```

---

## Round 3：实现任务桥接

### 目标

把前端命令真实转给 NUC，而不是仅在 RK3588 本地假执行。

### 任务

- 实现 `mission_gateway`
- 将任务命令转成结构化请求发给 NUC
- 接收 NUC 的命令响应
- 写命令日志
- 页面显示命令结果

### 交付物

- 真实任务桥接链路
- 至少 3 个命令真实可用
- 命令日志入库

### 验收

- `go_to_waypoint`
- `pause_task`
- `return_home`
  至少这三个命令能真实闭环

### Codex Prompt（Round 3）

```text
Continue in the same thread.

Task:
Implement the mission bridge from RK3588 to NUC for Phase 2.

Requirements:
1. Add a mission_gateway layer if not already present
2. Forward these mission commands to NUC:
   - go_to_waypoint
   - start_patrol
   - pause_task
   - resume_task
   - return_home
3. Record command logs into SQLite
4. Return structured success/failure responses
5. Surface command outcomes to the frontend through existing API/state mechanisms
6. Keep mock mode and existing mock flow available

Constraints:
- Do not redesign public APIs unless strictly necessary
- Keep changes scoped to mission bridging and related logging
- No unrelated refactors

Validation:
- at least three commands can be forwarded to NUC
- command logs are persisted
- frontend can trigger commands and observe results

At the end, summarize the command flow and validation results.
```

---

## Round 4：补齐状态—命令—反馈闭环与模式切换

### 目标

让联调时真正具备“能发命令、能看到状态变化、能回退 mock”的能力。

### 任务

- 完善 `mode_manager`
- 完成 mock / real 模式切换
- 补齐任务状态回显
- 补齐离线、错误和重连处理

### 交付物

- mock / real 模式切换
- 任务状态闭环
- 基础错误提示

### 验收

- 模式切换成功
- real 模式任务状态实时变化
- NUC 断连后页面有明确反馈
- 回到 mock 模式后系统仍可运行

### Codex Prompt（Round 4）

```text
Continue in the same thread.

Task:
Complete the Phase 2 command-state-feedback loop and add mock/real mode switching.

Requirements:
1. Implement a clear mock/real mode manager
2. Allow switching modes through backend API and reflected frontend state
3. Ensure command -> NUC -> status update -> frontend feedback is observable
4. Handle offline, reconnect, and adapter error states clearly
5. Keep the UI simple and reuse the existing dashboard layout

Constraints:
- No UI redesign
- No unrelated backend refactors
- Preserve existing mock workflow

Validation:
- switching between mock and real works
- real mode shows real state changes after mission commands
- offline states are visible
- reconnect recovers state updates

At the end, summarize changed files, edge cases handled, and validation steps.
```

---

## Round 5：补日志、README 与 Phase 2 验收准备

### 目标

把当前阶段整理到可交付、可复现、可验收状态。

### 任务

- 补充 README
- 明确如何启动 mock / real 模式
- 明确如何接 NUC
- 补日志和调试说明
- 做最小测试或检查脚本
- 为 Phase 2 验收做准备

### 交付物

- 更新 README
- 更新调试说明
- 最小测试 / 验证脚本
- 可交付的 Phase 2 分支状态

### 验收

- 队友可按 README 跑起来
- 能复现 mock / real 两种模式
- 能完成一轮基础联调

### Codex Prompt（Round 5）

```text
Continue in the same thread.

Task:
Polish Phase 2 for handoff and acceptance.

Requirements:
1. Update README with:
   - project purpose
   - how to run backend/frontend
   - how to use mock mode
   - how to use real mode
   - where the NUC adapter plugs in
2. Add minimal developer notes for debugging:
   - state flow
   - mission flow
   - common failure points
3. Add the smallest useful validation or checks for:
   - health endpoint
   - one mission endpoint
   - mode switching
4. Keep scope limited to Phase 2 handoff readiness

Constraints:
- No broad refactors
- No extra features beyond Phase 2 scope
- Keep documentation practical and concise

Validation:
- README steps work
- backend/frontend start correctly
- mock and real modes are both discoverable and testable

At the end, summarize handoff readiness and remaining Phase 3 items.
```

---

## 7. 本阶段建议验收顺序

### Step 1：文档验收

检查：

- `docs_p2/prd_p2.md`
- `docs_p2/arc_p2.md`
- `docs_p2/project_p2.md`

### Step 2：后端验收

检查：

- NUC 适配器
- 模式切换
- 命令桥接
- SQLite 日志

### Step 3：前端验收

检查：

- Dashboard 显示真实状态
- mock / real 模式显示
- 任务按钮真实联动

### Step 4：联调验收

检查：

- 至少 3 条命令闭环
- 至少 1 次状态离线/重连验证

---

## 8. 风险与注意事项

### 风险 1：字段未冻结就开始联调

结果：前后端 / NUC 三方不断改字段，成本极高

### 风险 2：删掉 mock 模式

结果：联调失败时无法快速回退，前端调试停摆

### 风险 3：RK3588 职责扩张

结果：项目开始把主任务逻辑、主导航逻辑往 RK3588 塞，破坏既定分层

### 风险 4：只打通命令，不关注反馈闭环

结果：表面上接口通了，实际上不可用

---

## 9. Phase 2 通过条件

本阶段通过需满足：

1. NUC 真实状态能进入 RK3588
2. 前端能看到真实状态
3. 至少 3 条任务命令桥接成功
4. 命令—状态—反馈闭环成立
5. mock / real 模式可切换
6. README 与文档可供队友复现

---

## 10. Phase 2 完成后的下一阶段（预告）

Phase 2 完成后，再进入下一层增强：

- 语音任务入口真实接入
- 视频图传服务
- 巡检传感器数据接入
- 视觉异常检测联动
- LLM / OpenClaw 等高级交互
